#!/usr/bin/python3
"""Check main and install a tested revision without touching a user's checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

from release import REPOSITORY, file_hashes, install_identity, maintenance_lock


class Updater:
    def __init__(self, root=None, state=None, repository=REPOSITORY):
        self.root = root or Path.home() / ".local/share/abide"
        self.state = state or Path.home() / ".local/state/abide"
        self.repository = repository
        self.cache = self.state / "updates.git"

    def run(self, arguments, *, cwd=None, timeout=30, env=None):
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        if env:
            environment.update(env)
        try:
            result = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                                    text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("The update check timed out. Check your connection and try again.") from None
        except FileNotFoundError:
            raise RuntimeError("An update tool is missing. Run ./setup.sh to install Debian dependencies.") from None
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail[-2000:] or "The update could not finish.")
        return result.stdout.strip()

    def git(self, *arguments):
        return self.run(["git", "--git-dir", str(self.cache), *arguments])

    def fetch(self):
        if not self.cache.exists():
            self.run(["git", "init", "--bare", "--quiet", str(self.cache)])
        self.git("fetch", "--quiet", "--no-tags", self.repository,
                 "+refs/heads/main:refs/remotes/origin/main")
        return self.git("rev-parse", "refs/remotes/origin/main")

    def same_code(self, revision, files):
        # A squash/rebase can publish identical code under a new commit ID.
        # Recognize that case without allowing a code downgrade or replacement
        # of an unpublished change.
        for name, checksum in files.items():
            result = subprocess.run(["git", "--git-dir", str(self.cache), "show", f"{revision}:{name}"],
                                    capture_output=True, timeout=5)
            if result.returncode or hashlib.sha256(result.stdout).hexdigest() != checksum:
                return False
        return True

    def _check(self):
        try:
            installed = json.loads((self.root / "release.json").read_text())
        except (OSError, ValueError):
            raise RuntimeError("This installation has no update information. Reinstall Abide using ./setup.sh.") from None
        if not isinstance(installed, dict) or installed.get("format") != 1 or installed.get("repository") != REPOSITORY:
            raise RuntimeError("This installation's update information is invalid. Reinstall Abide using ./setup.sh.")
        revision = installed.get("revision")
        if installed.get("local_changes") or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            return {"state": "local", "message": "This is a local build. Publish it to main before using updates."}
        if file_hashes(self.root) != installed.get("files"):
            return {"state": "local", "message": "Abide has local code changes. Updates will preserve them; reinstall when you are ready."}
        latest = self.fetch()
        if latest == revision:
            return {"state": "current", "revision": latest, "message": "Abide is up to date."}
        ancestor = subprocess.run(["git", "--git-dir", str(self.cache), "merge-base", "--is-ancestor", revision, latest],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if ancestor.returncode != 0 and not self.same_code(latest, installed["files"]):
            return {"state": "local", "message": "This build is ahead of main or from another branch. Updates will preserve it."}
        return {"state": "available", "revision": latest, "message": "An Abide update is available."}

    def check(self):
        with maintenance_lock(self.state, "update.lock"):
            return self._check()

    def apply(self, expected=None):
        with maintenance_lock(self.state, "update.lock"):
            identity = install_identity(self.root)
            result = self._check()
            if result["state"] == "current":
                return result
            if result["state"] != "available":
                raise RuntimeError(result["message"])
            revision = result["revision"]
            if expected is not None and revision != expected:
                raise RuntimeError("A newer update appeared. Check again before installing it.")
            with tempfile.TemporaryDirectory(prefix="abide-update-", dir=self.state) as temporary:
                source = Path(temporary) / "release"
                self.run(["git", "clone", "--quiet", "--no-checkout", "--no-hardlinks", str(self.cache), str(source)])
                self.run(["git", "-C", str(source), "checkout", "--quiet", "--detach", revision])
                file_hashes(source)
                if not (source / "tests/test_panels.py").is_file():
                    raise RuntimeError("This release is missing its validation checks. Your installation is unchanged.")
                self.run(["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests"], cwd=source,
                         timeout=60, env={"ABIDE_GUI_TEST": "0", "PYTHONDONTWRITEBYTECODE": "1"})
                # The installer backs up managed files and keys, saves open
                # journals, and rolls back if either desktop service fails.
                # Verify the original installation while holding the install
                # lock, even if somebody installed another build during fetch.
                self.run(["/usr/bin/python3", str(source / "install.py"),
                          "--expected-install", identity], timeout=60)
            return {"state": "installed", "revision": revision, "message": "Abide is updated and ready."}


def run_gui():
    # The check and installer remain usable without importing GTK. Only the
    # graphical entry point needs it, and all slow work stays off its main loop.
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkX11", "3.0")
    from gi.repository import Gdk, GdkX11, GLib, Gtk

    class Updates(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="local.abide.Updates")
            self.updater = Updater()
            self.window = None
            self.applying = False
            self.busy = False
            self.revision = None

        def do_activate(self):
            if self.window is None:
                self.window = Gtk.ApplicationWindow(application=self, title="Abide updates")
                self.window.set_decorated(False)
                self.window.set_resizable(False)
                self.window.set_keep_above(True)
                self.window.set_skip_taskbar_hint(True)
                self.window.set_skip_pager_hint(True)
                self.window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                self.window.set_position(Gtk.WindowPosition.CENTER)
                self.window.set_default_size(460, -1)
                self.window.get_style_context().add_class("abide-guide")
                self.window.connect("delete-event", lambda *_: self.applying)
                self.window.connect("destroy", self.on_destroy)
                self.window.connect("key-press-event", self.on_key)
                css = Gtk.CssProvider()
                css.load_from_path(str(Path(__file__).with_name("app.css")))
                Gtk.StyleContext.add_provider_for_screen(self.window.get_screen(), css,
                                                        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
                body.set_border_width(24)
                title = Gtk.Label(label="Abide updates", xalign=0)
                title.get_style_context().add_class("abide-heading")
                body.pack_start(title, False, False, 0)
                self.message = Gtk.Label(label="Checking for updates…", xalign=0)
                self.message.set_line_wrap(True)
                self.message.set_max_width_chars(46)
                body.pack_start(self.message, False, False, 0)
                self.spinner = Gtk.Spinner()
                body.pack_start(self.spinner, False, False, 0)
                buttons = Gtk.Box(spacing=12)
                self.close_button = Gtk.Button(label="Close")
                self.close_button.connect("clicked", lambda *_: self.window.close())
                self.check_button = Gtk.Button(label="Check again")
                self.check_button.connect("clicked", lambda *_: self.work(self.updater.check, False))
                self.install_button = Gtk.Button(label="Install update")
                self.install_button.set_no_show_all(True)
                self.install_button.connect("clicked", lambda *_: self.work(lambda: self.updater.apply(self.revision), True))
                for button in (self.close_button, self.check_button, self.install_button):
                    buttons.pack_start(button, True, True, 0)
                body.pack_start(buttons, False, False, 0)
                self.window.add(body)
                self.window.show_all()
                if self.busy:
                    self.check_button.set_sensitive(False)
                    self.spinner.start()
                else:
                    self.work(self.updater.check, False)
            root = Gdk.get_default_root_window()
            root.set_events(root.get_events() | Gdk.EventMask.PROPERTY_CHANGE_MASK)
            self.window.present_with_time(GdkX11.x11_get_server_time(root))

        def on_key(self, window, event):
            if event.keyval == Gdk.KEY_Escape:
                window.close()
                return True
            return False

        def on_destroy(self, _window):
            self.window = None

        def work(self, operation, applying):
            self.busy = True
            self.applying = applying
            self.message.set_text("Installing update…" if applying else "Checking for updates…")
            self.close_button.set_sensitive(not applying)
            self.check_button.set_sensitive(False)
            self.install_button.hide()
            self.spinner.start()
            self.hold()
            def worker():
                try:
                    result, error = operation(), None
                except (OSError, RuntimeError, subprocess.SubprocessError) as problem:
                    result, error = None, str(problem)
                GLib.idle_add(self.finish, result, error)
            threading.Thread(target=worker, daemon=True).start()

        def finish(self, result, error):
            self.busy = False
            self.applying = False
            if self.window is None:
                self.release()
                return False
            self.spinner.stop()
            self.close_button.set_sensitive(True)
            self.check_button.set_sensitive(True)
            self.message.set_text(error if error else result["message"])
            if result and result["state"] == "available":
                self.revision = result["revision"]
                self.install_button.show()
            self.release()
            return False

    return Updates().run([sys.argv[0]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--gui", action="store_true", help="open the update panel")
    action.add_argument("--apply", action="store_true", help="install the latest main revision")
    action.add_argument("--check", action="store_true", help="check without installing (the default)")
    args = parser.parse_args()
    if args.gui:
        return run_gui()
    updater = Updater()
    result = updater.apply() if args.apply else updater.check()
    print(result["message"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("Abide: " + str(error), file=sys.stderr)
        raise SystemExit(1)
