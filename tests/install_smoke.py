"""Install, update, and undo in a disposable Xfce desktop (never the real session)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from release import CODE_FILES  # noqa: E402
from updater import Updater  # noqa: E402


def run(*arguments, cwd=None):
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout.strip()


def main():
    if os.environ.get("ABIDE_ISOLATED_DESKTOP") != "1":
        raise SystemExit("This check requires a disposable HOME, X server, and D-Bus session.")
    home = Path.home()
    root = home / ".local/share/abide"
    bin_dir = home / ".local/bin"
    state = home / ".local/state/abide"
    root.mkdir(parents=True)
    (root / "journal").mkdir()
    entry = root / "journal/private.txt"
    entry.write_text("PRIVATE_SMOKE_TEST_ENTRY")
    voice = root / "launchers.json"
    voice.write_text(json.dumps([["Voice test", "Hold Super + V", "audio", ["voice-test"]]]))
    voice_bytes = voice.read_bytes()
    run("xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", "/commands/custom/<Super>v",
        "-n", "-t", "string", "-s", "voice-test-command")
    with tempfile.TemporaryDirectory(prefix="abide-smoke-upstream-") as folder:
        upstream = Path(folder)
        for name in CODE_FILES:
            shutil.copy2(SOURCE / name, upstream / name)
        shutil.copy2(SOURCE / "setup.sh", upstream / "setup.sh")
        shutil.copytree(SOURCE / "tests", upstream / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        run("git", "init", "--quiet", "-b", "main", cwd=upstream)
        run("git", "config", "user.name", "Abide smoke check", cwd=upstream)
        run("git", "config", "user.email", "abide-smoke@example.invalid", cwd=upstream)
        run("git", "config", "commit.gpgsign", "false", cwd=upstream)
        run("git", "add", ".", cwd=upstream)
        run("git", "commit", "--quiet", "-m", "Base release", cwd=upstream)
        print(run(str(upstream / "setup.sh")))
        first_backup = (state / "latest-panels-install").read_text()
        assert "ready" in run(str(bin_dir / "abide"), "--doctor")
        assert "Usage:" in run(str(bin_dir / "abide"), "--help")
        for desktop in (home / ".local/share/applications").glob("abide*.desktop"):
            run("desktop-file-validate", str(desktop))
        for desktop in (home / ".config/autostart").glob("abide*.desktop"):
            run("desktop-file-validate", str(desktop))
        # Real keyboard events verify that fresh Xfce uses the installed keys.
        import ctypes
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Wnck", "3.0")
        from gi.repository import GLib, Gtk, Wnck
        Gtk.init([])
        Wnck.set_client_type(Wnck.ClientType.PAGER)
        screen = Wnck.Screen.get_default()
        x11, xtst = ctypes.CDLL("libX11.so.6"), ctypes.CDLL("libXtst.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x11.XStringToKeysym.restype = ctypes.c_ulong
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XKeysymToKeycode.restype = ctypes.c_uint
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        display = x11.XOpenDisplay(None)
        assert display
        def press(*names):
            codes = [x11.XKeysymToKeycode(display, x11.XStringToKeysym(name.encode())) for name in names]
            assert all(codes)
            for code in codes:
                xtst.XTestFakeKeyEvent(display, code, True, 0)
            for code in reversed(codes):
                xtst.XTestFakeKeyEvent(display, code, False, 0)
            x11.XFlush(display)
        def wait_for_menu(visible):
            context = GLib.MainContext.default()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                active = None
                while context.pending():
                    context.iteration(False)
                screen.force_update()
                active = screen.get_active_window()
                if bool(active and active.get_name() == "Abide") == visible:
                    return
                time.sleep(0.01)
            raise RuntimeError("Installed keyboard shortcut did not change the menu's visibility")
        try:
            time.sleep(0.2)
            press("Super_L", "space")
            wait_for_menu(True)
            press("Super_L", "w")
            wait_for_menu(False)
            run("gapplication", "action", "local.abide.Panels", "stop")
            time.sleep(0.15)
            run(str(bin_dir / "abide"), "--toggle")
            wait_for_menu(True)
            assert run("gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path",
                       "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.NameHasOwner", "local.abide.Panels") == "(true,)"
            press("Super_L", "w")
            wait_for_menu(False)
        finally:
            x11.XCloseDisplay(display)
        print("Fresh desktop: menu and close shortcuts, D-Bus restart, desktop entries, and paths with spaces passed.")
        saved_manifest = (root / "release.json").read_bytes()
        local_manifest = json.loads(saved_manifest)
        local_manifest["local_changes"] = True
        (root / "release.json").write_text(json.dumps(local_manifest))
        assert "local build" in run(str(bin_dir / "abide"), "--check-updates")
        gui = subprocess.Popen([str(bin_dir / "abide-update"), "--gui"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            context = GLib.MainContext.default()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                active = None
                while context.pending():
                    context.iteration(False)
                screen.force_update()
                active = screen.get_active_window()
                if active and active.get_name() == "Abide updates":
                    assert active.is_above()
                    active.close(0)
                    del active
                    break
                time.sleep(0.01)
            else:
                raise RuntimeError("The graphical update panel did not open")
            stdout, stderr = gui.communicate(timeout=5)
            assert gui.returncode == 0, (stdout + stderr).decode()
        finally:
            if gui.poll() is None:
                gui.terminate()
                gui.communicate(timeout=5)
            (root / "release.json").write_bytes(saved_manifest)
        print("CLI and graphical update checks passed; unpublished code stays protected.")
        with (upstream / "app.css").open("a") as css:
            css.write("\n/* Smoke test release */\n")
        run("git", "add", "app.css", cwd=upstream)
        run("git", "commit", "--quiet", "-m", "Next release", cwd=upstream)
        updater = Updater(root, state, str(upstream))
        checked = updater.check()
        assert checked["state"] == "available", checked
        assert updater.apply(checked["revision"])["state"] == "installed"
        assert updater.check()["state"] == "current"
        assert voice.read_bytes() == voice_bytes
        assert entry.read_text() == "PRIVATE_SMOKE_TEST_ENTRY"
        assert run("xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", "/commands/custom/<Super>v") == "voice-test-command"
        print("Real main update: validation, installation, voice shortcuts, and journal preservation passed.")
        run(str(bin_dir / "abide-panels-undo"))
        assert (root / "app.css").read_bytes() == (SOURCE / "app.css").read_bytes()
        # Restore the first install explicitly; undo normally tracks one change.
        (state / "latest-panels-install").write_text(first_backup)
        run(str(bin_dir / "abide-panels-undo"))
        assert not (root / "app.py").exists()
        assert not (bin_dir / "abide").exists()
        assert voice.read_bytes() == voice_bytes
        assert entry.read_text() == "PRIVATE_SMOKE_TEST_ENTRY"
        print("Update undo and initial install undo passed; private integrations remain intact.")


if __name__ == "__main__":
    main()
