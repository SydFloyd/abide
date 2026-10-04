"""Persistent profiles, desktop launchers, and reuse of web app windows."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from webapps import WEB_APPS, browser_command, desktop_entry, focus_existing


class WebAppTests(unittest.TestCase):
    def test_profiles_are_private_separate_and_preserved(self):
        with tempfile.TemporaryDirectory(prefix="abide-webapps-") as folder, \
                patch("webapps.shutil.which", return_value="/usr/bin/chromium"):
            home = Path(folder) / "Father's Desktop"
            profiles = home / ".local/share/abide/webapps"
            first = browser_command(WEB_APPS[0], home)
            cookie = profiles / "x" / "Cookies"
            cookie.write_text("SAVED_WEBAPP_SESSION")
            self.assertEqual(browser_command(WEB_APPS[0], home), first)
            second = browser_command(WEB_APPS[1], home)
            self.assertNotEqual(first, second)
            self.assertIn("--user-data-dir=" + str(profiles / "x"), first)
            self.assertIn("--user-data-dir=" + str(profiles / "gmail"), second)
            self.assertEqual(cookie.read_text(), "SAVED_WEBAPP_SESSION")
            for path in (profiles, profiles / "x", profiles / "gmail"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            self.assertFalse((home / ".mozilla").exists())

    def test_missing_browser_explains_how_to_install_it(self):
        with patch("webapps.shutil.which", return_value=None), tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            with self.assertRaisesRegex(RuntimeError, "sudo apt install chromium chromium-sandbox"):
                browser_command(WEB_APPS[0], home)
            self.assertFalse((home / ".local").exists())

    def test_desktop_entries_identify_each_webapp_and_quote_the_launcher(self):
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        with tempfile.TemporaryDirectory() as folder:
            bin_directory = Path(folder) / 'Father\'s "Desktop" $/bin'
            bin_directory.mkdir(parents=True)
            launcher = bin_directory / "abide-webapp"
            launcher.write_text("#!/usr/bin/python3\nfrom pathlib import Path\nimport sys\n"
                                "Path(__file__).with_name('result').write_text(sys.argv[1])\n")
            launcher.chmod(0o755)
            result = bin_directory / "result"
            for app in WEB_APPS:
                entry = Path(folder) / (app.identifier + ".desktop")
                entry.write_text(desktop_entry(app, bin_directory))
                info = Gio.DesktopAppInfo.new_from_filename(str(entry))
                self.assertIsNotNone(info)
                self.assertEqual(info.get_string("StartupWMClass"), app.window_class)
                self.assertTrue(info.launch([], None))
                deadline = time.monotonic() + 3
                while not result.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(result.read_text(), app.identifier)
                result.unlink()

    def test_setup_can_include_the_webapp_browser_without_forwarding_its_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            script = source / "setup.sh"
            shutil.copy2(Path(__file__).resolve().parents[1] / "setup.sh", script)
            (source / "install.py").write_text("import sys\nassert sys.argv[1:] == ['--check']\n")
            tools = source / "tools"
            tools.mkdir()
            log = source / "packages"
            query = tools / "dpkg-query"
            query.write_text("#!/usr/bin/python3\nfrom pathlib import Path\nimport sys\n"
                             + f"with Path({str(log)!r}).open('a') as output: output.write(sys.argv[-1] + '\\n')\n"
                             + "print('installed')\n")
            query.chmod(0o755)
            environment = {**os.environ, "PATH": str(tools) + ":" + os.environ["PATH"],
                           "DISPLAY": ":99", "XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "XFCE"}
            for arguments, included in ((["--check"], False), (["--webapps", "--check"], True)):
                subprocess.run([str(script), *arguments], env=environment, check=True, capture_output=True, timeout=10)
                packages = log.read_text().splitlines()
                self.assertEqual("chromium" in packages, included)
                self.assertEqual("chromium-sandbox" in packages, included)
                log.unlink()


@unittest.skipUnless(os.environ.get("ABIDE_GUI_TEST") == "1", "Set ABIDE_GUI_TEST=1 for desktop checks")
class WebAppDesktopTests(unittest.TestCase):
    def pump(self, seconds=0.2):
        from gi.repository import GLib
        deadline = time.monotonic() + seconds
        context = GLib.MainContext.default()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)

    def test_existing_and_new_webapps_lose_their_frames_only(self):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("Wnck", "3.0")
        from gi.repository import Gtk, Gdk, Wnck
        from focus import NewWindowFocus
        Gtk.init([])
        existing = Gtk.Window(title="Existing Abide web app")
        existing.set_wmclass("abide-webapp-test", WEB_APPS[0].window_class)
        new = Gtk.Window(title="New Abide web app")
        new.set_wmclass("abide-webapp-test", WEB_APPS[1].window_class)
        ordinary = Gtk.Window(title="X")
        dialog = Gtk.Window(title="Web app authentication")
        dialog.set_wmclass("abide-webapp-dialog", WEB_APPS[0].window_class)
        dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        screen = Wnck.Screen.get_default()
        root = Gdk.get_default_root_window()
        root.set_events(root.get_events() | Gdk.EventMask.PROPERTY_CHANGE_MASK)
        watcher = None

        def has_frame(widget):
            screen.force_update()
            window = Wnck.Window.get(widget.get_window().get_xid())
            return window.get_geometry() != window.get_client_window_geometry()

        try:
            for widget in (existing, dialog, ordinary):
                widget.show_all()
            ordinary.present()
            self.pump()
            self.assertTrue(has_frame(existing))
            self.assertTrue(ordinary.is_active())
            watcher = NewWindowFocus(screen, root)
            self.pump()
            self.assertFalse(has_frame(existing))
            self.assertTrue(has_frame(ordinary))
            self.assertTrue(has_frame(dialog))
            self.assertTrue(ordinary.is_active(), "Restyling existing apps must not steal focus")
            existing.get_window().set_decorations(Gdk.WMDecoration.ALL)
            Gdk.Display.get_default().flush()
            self.pump()
            self.assertFalse(has_frame(existing), "A browser must not restore the frame")
            new.show_all()
            self.pump()
            self.assertFalse(has_frame(new))
            new.maximize()
            self.pump()
            new.unmaximize()
            self.pump()
            self.assertFalse(has_frame(new))
            xid = new.get_window().get_xid()
            self.assertIn(xid, watcher.frame_handlers)
            new.destroy()
            self.pump()
            self.assertNotIn(xid, watcher.frame_handlers)
        finally:
            if watcher is not None:
                watcher.stop()
            for widget in (new, ordinary, dialog, existing):
                widget.destroy()
            self.pump()

    def test_shortcut_focuses_the_matching_app_and_restores_minimized_windows(self):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("Wnck", "3.0")
        from gi.repository import Gtk, Wnck
        Gtk.init([])
        app = WEB_APPS[0]
        target = Gtk.Window(title="Web app focus verification")
        target.set_wmclass("abide-webapp-test", app.window_class)
        other = Gtk.Window(title=app.name)
        other.set_wmclass("abide-webapp-other", "AbideWebAppOther")
        screen = Wnck.Screen.get_default()
        screen.force_update()
        original_workspace = screen.get_active_workspace().get_number()
        try:
            target.show_all()
            self.pump()
            other.show_all()
            other.present()
            self.pump()
            self.assertTrue(other.is_active())
            self.assertTrue(focus_existing(app))
            self.pump()
            self.assertTrue(target.is_active())
            target.iconify()
            self.pump()
            self.assertTrue(focus_existing(app))
            self.pump()
            self.assertTrue(target.is_active())
            self.assertFalse(focus_existing(WEB_APPS[1]))
            screen.force_update()
            active = screen.get_active_window()
            self.assertEqual(active.get_xid(), target.get_window().get_xid())
            del active
            self.assertGreater(screen.get_workspace_count(), 1)
            destination = (original_workspace + 1) % screen.get_workspace_count()
            Wnck.Window.get(target.get_window().get_xid()).move_to_workspace(screen.get_workspace(destination))
            self.pump()
            self.assertTrue(focus_existing(app))
            self.pump()
            self.assertEqual(screen.get_active_workspace().get_number(), destination)
            self.assertTrue(target.is_active())
        finally:
            screen.get_workspace(original_workspace).activate(0)
            other.destroy()
            target.destroy()
            self.pump()


if __name__ == "__main__":
    unittest.main()
