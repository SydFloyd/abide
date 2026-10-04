#!/usr/bin/python3
"""Suggested, optional Debian tools used by Abide; no bundled engines or plugins."""
import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import threading


@dataclass(frozen=True)
class AddIn:
    identifier: str
    name: str
    software: str
    description: str
    packages: tuple
    commands: tuple


ADDINS = (
    AddIn("browser", "Web browser", "Firefox ESR",
          "A regular browser for links and Abide's browser shortcut.",
          ("firefox-esr",), ("firefox-esr",)),
    AddIn("tiling", "Automatic tiling", "bspwm",
          "Golden-ratio tiles, focus borders, and shortcuts for moving windows.",
          ("bspwm", "xfwm4", "x11-utils"), ("bspwm", "bspc")),
    AddIn("webapps", "Web apps", "Chromium",
          "Separate X and Gmail windows, with persistent sign-in and no browser tabs.",
          ("chromium", "chromium-sandbox"), ("chromium",)),
    AddIn("capture", "Screen capture", "Xfce Screenshooter",
          "Capture the screen, a window, or a selected area.",
          ("xfce4-screenshooter",), ("xfce4-screenshooter",)),
    AddIn("recording", "Screen recording", "SimpleScreenRecorder",
          "Record your screen and audio.",
          ("simplescreenrecorder",), ("simplescreenrecorder",)),
    AddIn("desktop-tools", "Desktop tools", "Xfce Terminal · Thunar · Mousepad · Task Manager",
          "A terminal, file manager, text editor, and system monitor for Abide's shortcuts.",
          ("xfce4-terminal", "thunar", "mousepad", "xfce4-taskmanager"),
          ("xfce4-terminal", "thunar", "mousepad", "xfce4-taskmanager")),
)


def find_addin(identifier):
    return next((addin for addin in ADDINS if addin.identifier == identifier), None)


def available(addin):
    # A user-local binary counts too: the desktop's original PATH may omit it.
    return all(shutil.which(command) or (
        (Path.home() / ".local/bin" / command).is_file()
        and (Path.home() / ".local/bin" / command).stat().st_mode & 0o111
    ) for command in addin.commands)


def install_command(identifier):
    addin = find_addin(identifier)
    if addin is None:
        raise ValueError("Unknown add-in")
    if shutil.which("pkexec") is None:
        raise RuntimeError("The desktop's authentication tool is unavailable. Install with: sudo apt install "
                           + " ".join(addin.packages))
    # Only catalogued package names reach apt. No shell or privileged Abide
    # script is involved; PolicyKit handles authentication when Install is clicked.
    return ["pkexec", "/usr/bin/apt-get", "install", "--no-install-recommends", "-y", *addin.packages]


def install_addin(identifier):
    result = subprocess.run(install_command(identifier), capture_output=True, text=True, timeout=900)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail[-1500:] or "Installation was cancelled or could not finish.")
    installer = Path.home() / ".local/share/abide/install.py"
    if installer.is_file():
        subprocess.run([sys.executable, str(installer), "--refresh-shortcuts"],
                       check=True, capture_output=True, text=True, timeout=30)


def run_gui():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkX11", "3.0")
    from gi.repository import Gdk, GdkX11, GLib, Gtk
    from window_manager import enabled as tiling_enabled

    class AddIns(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="local.abide.AddIns")
            self.window = None
            self.busy = False
            self.rows = []

        def do_activate(self):
            if self.window is None:
                self.window = Gtk.ApplicationWindow(application=self, title="Abide add-ins")
                self.window.set_wmclass("abide-addins", "AbidePanel")
                self.window.set_decorated(False)
                self.window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                self.window.set_keep_above(True)
                self.window.set_skip_taskbar_hint(True)
                self.window.set_position(Gtk.WindowPosition.CENTER)
                self.window.set_default_size(660, 580)
                self.window.get_style_context().add_class("abide-guide")
                self.window.connect("delete-event", lambda *_: self.busy)
                self.window.connect("destroy", lambda *_: setattr(self, "window", None))
                self.window.connect("key-press-event", self.on_key)
                provider = Gtk.CssProvider()
                provider.load_from_path(str(Path(__file__).with_name("app.css")))
                Gtk.StyleContext.add_provider_for_screen(self.window.get_screen(), provider,
                                                        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
                body.set_border_width(22)
                heading = Gtk.Label(label="Add-ins", xalign=0)
                heading.get_style_context().add_class("abide-heading")
                body.pack_start(heading, False, False, 0)
                intro = Gtk.Label(label="Abide provides the menu, journal, shortcuts, and updates.\n"
                                       "Choose the optional tools you want to use.", xalign=0)
                intro.set_line_wrap(True)
                body.pack_start(intro, False, False, 0)
                core = Gtk.Label(label="Core: Python 3 · GTK 3 · Xfce/X11", xalign=0)
                core.get_style_context().add_class("abide-muted")
                body.pack_start(core, False, False, 0)
                scroll = Gtk.ScrolledWindow()
                scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                catalog = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
                self.rows = []
                for addin in ADDINS:
                    row = Gtk.Box(spacing=16)
                    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    for value, style in ((addin.name, None), (addin.software, "abide-muted"),
                                         (addin.description, None)):
                        line = Gtk.Label(label=value, xalign=0)
                        line.set_line_wrap(True)
                        line.set_max_width_chars(47)
                        if style:
                            line.get_style_context().add_class(style)
                        text.pack_start(line, False, False, 0)
                    status = Gtk.Label(xalign=0)
                    status.get_style_context().add_class("abide-muted")
                    text.pack_start(status, False, False, 0)
                    row.pack_start(text, True, True, 0)
                    button = Gtk.Button()
                    button.set_valign(Gtk.Align.CENTER)
                    button.connect("clicked", self.select, addin)
                    row.pack_end(button, False, False, 0)
                    catalog.pack_start(row, False, False, 0)
                    self.rows.append((addin, status, button))
                scroll.add(catalog)
                body.pack_start(scroll, True, True, 0)
                self.message = Gtk.Label(xalign=0)
                self.message.set_line_wrap(True)
                self.message.set_max_width_chars(68)
                body.pack_start(self.message, False, False, 0)
                self.close_button = Gtk.Button(label="Close")
                self.close_button.connect("clicked", lambda *_: self.window.close())
                body.pack_start(self.close_button, False, False, 0)
                self.window.add(body)
                self.window.show_all()
            self.refresh()
            root = Gdk.get_default_root_window()
            root.set_events(root.get_events() | Gdk.EventMask.PROPERTY_CHANGE_MASK)
            self.window.present_with_time(GdkX11.x11_get_server_time(root))

        def on_key(self, window, event):
            if event.keyval == Gdk.KEY_Escape:
                window.close()
                return True
            return False

        def refresh(self):
            for addin, status, button in self.rows:
                installed = available(addin)
                status.set_text("Installed" if installed else "Optional · not installed")
                button.set_label("Install" if not installed else "Installed")
                button.set_sensitive(not self.busy and not installed)
                if installed and addin.identifier == "tiling":
                    status.set_text("Installed · tiling enabled" if tiling_enabled() else "Installed · floating windows")
                    button.set_label("Use floating" if tiling_enabled() else "Use tiling")
                    button.set_sensitive(not self.busy)
            self.close_button.set_sensitive(not self.busy)

        def select(self, _button, addin):
            if self.busy:
                return
            if available(addin):
                command = [str(Path.home() / ".local/bin/abide-wm"),
                           "--disable" if tiling_enabled() else "--enable"]
                operation = lambda: subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
            else:
                operation = lambda: install_addin(addin.identifier)
            self.busy = True
            self.message.set_text("Changing window mode…" if available(addin) else f"Installing {addin.software}…")
            self.refresh()
            self.hold()
            def worker():
                try:
                    operation()
                    error = None
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as problem:
                    error = (problem.stderr or str(problem)).strip() if isinstance(problem, subprocess.CalledProcessError) else str(problem)
                GLib.idle_add(self.finish, error)
            threading.Thread(target=worker, daemon=True).start()

        def finish(self, error):
            self.busy = False
            if self.window is not None:
                self.message.set_text(error or "Ready.")
                self.refresh()
            self.release()
            return False

    return AddIns().run([sys.argv[0]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gui", action="store_true", help="open the add-in manager")
    mode.add_argument("--list", action="store_true", help="list optional tools and their status")
    mode.add_argument("--install", choices=[addin.identifier for addin in ADDINS])
    args = parser.parse_args()
    if args.install:
        install_addin(args.install)
    elif args.list:
        for addin in ADDINS:
            print(f"{addin.name}: {addin.software} ({'installed' if available(addin) else 'optional'})")
    else:
        return run_gui()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Abide add-ins: " + str(error), file=sys.stderr)
        raise SystemExit(1)
