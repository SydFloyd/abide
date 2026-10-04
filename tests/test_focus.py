"""Regression checks for the desktop-wide new-window focus policy."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("abide_focus", ROOT / "focus.py")
focus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(focus)


class FocusPolicyTests(unittest.TestCase):
    def setUp(self):
        self.screen = Mock()
        self.root = Mock()
        self.screen.get_windows.return_value = []
        self.watcher = focus.NewWindowFocus(self.screen, self.root)
        self.addCleanup(self.watcher.stop)
        self.window = Mock()
        self.window.get_xid.return_value = 42
        self.window.get_window_type.return_value = focus.Wnck.WindowType.NORMAL
        self.window.is_skip_tasklist.return_value = False
        self.window.is_minimized.return_value = False
        self.window.is_visible_on_workspace.return_value = True
        self.screen.get_windows.return_value = [self.window]
        self.screen.get_active_window.return_value = None

    def test_starting_does_not_focus_existing_windows(self):
        self.screen.force_update.assert_called_once()
        self.window.activate.assert_not_called()

    def test_new_window_uses_fresh_server_time_once(self):
        with patch.object(focus.GdkX11, "x11_get_server_time", return_value=1234):
            self.assertFalse(self.watcher.focus_window(42))
        self.window.activate.assert_called_once_with(1234)

    def test_already_focused_window_needs_no_activation(self):
        self.screen.get_active_window.return_value = self.window
        self.watcher.focus_window(42)
        self.window.activate.assert_not_called()

    def test_dialogs_can_focus_without_a_task_list_entry(self):
        self.window.get_window_type.return_value = focus.Wnck.WindowType.DIALOG
        self.window.is_skip_tasklist.return_value = True
        self.assertTrue(self.watcher.eligible(self.window))

    def test_desktop_surfaces_do_not_take_focus(self):
        for kind in (focus.Wnck.WindowType.DESKTOP, focus.Wnck.WindowType.DOCK,
                     focus.Wnck.WindowType.MENU, focus.Wnck.WindowType.SPLASHSCREEN,
                     focus.Wnck.WindowType.TOOLBAR):
            with self.subTest(kind=kind):
                self.window.get_window_type.return_value = kind
                self.assertFalse(self.watcher.eligible(self.window))
        self.window.get_window_type.return_value = focus.Wnck.WindowType.NORMAL
        self.window.is_skip_tasklist.return_value = True
        self.assertFalse(self.watcher.eligible(self.window))

    def test_hidden_or_closed_windows_do_not_take_focus(self):
        for field in ("is_minimized", "is_visible_on_workspace"):
            with self.subTest(field=field):
                method = getattr(self.window, field)
                original = method.return_value
                method.return_value = field == "is_minimized"
                self.assertFalse(self.watcher.eligible(self.window))
                method.return_value = original
        self.screen.get_windows.return_value = []
        self.watcher.focus_window(42)
        self.window.activate.assert_not_called()

    def test_closing_before_activation_cancels_pending_focus(self):
        with patch.object(focus.GLib, "idle_add", return_value=99) as idle, \
                patch.object(focus.GLib, "source_remove") as remove:
            self.watcher.on_opened(self.screen, self.window)
            self.watcher.on_opened(self.screen, self.window)
            self.watcher.on_closed(self.screen, self.window)
        idle.assert_called_once_with(self.watcher.focus_window, 42)
        remove.assert_called_once_with(99)
        self.assertFalse(self.watcher.pending)


@unittest.skipUnless(os.environ.get("ABIDE_GUI_TEST") == "1", "Set ABIDE_GUI_TEST=1 for desktop checks")
class FocusDesktopTests(unittest.TestCase):
    def pump(self, seconds):
        until = time.monotonic() + seconds
        context = focus.GLib.MainContext.default()
        while time.monotonic() < until:
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)

    def test_reused_server_timestamp_is_overridden_and_focus_stays_with_user(self):
        focus.Gtk.init([])
        screen = focus.Wnck.Screen.get_default()
        screen.force_update()
        original = screen.get_active_window()
        original_xid = original.get_xid() if original else None
        del original
        first = focus.Gtk.Window(title="Abide focus verification · source")
        target = focus.Gtk.Window(title="Abide focus verification · stale timestamp")
        process = None
        try:
            first.show_all()
            first.present()
            self.pump(0.2)
            self.assertTrue(first.is_active())
            process = subprocess.Popen([sys.executable, str(ROOT / "focus.py")],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            bus = focus.Gio.bus_get_sync(focus.Gio.BusType.SESSION, None)
            ready = False
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                ready = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                      "org.freedesktop.DBus", "NameHasOwner",
                                      focus.GLib.Variant("(s)", ("local.abide.Focus",)),
                                      focus.GLib.VariantType.new("(b)"),
                                      focus.Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
                if ready:
                    break
                self.pump(0.02)
            self.assertTrue(ready, "Focus service did not start")
            subprocess.run([sys.executable, str(ROOT / "focus.py")], check=True, timeout=5)
            subprocess.run([sys.executable, str(ROOT / "focus.py"), "--status"], check=True, timeout=5)
            self.assertIsNone(process.poll(), "Repeated startup replaced the original service")
            self.pump(0.1)
            self.assertTrue(first.is_active(), "Starting the service changed existing focus")
            target.realize()
            focus.GdkX11.X11Window.set_user_time(target.get_window(), 0)
            target.show_all()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not target.is_active():
                self.pump(0.02)
            self.assertTrue(target.is_active(), "New window did not receive focus")
            first.present()
            self.pump(0.3)
            self.assertTrue(first.is_active(), "Service took focus back after user navigation")
        finally:
            try:
                if process is not None:
                    subprocess.run([sys.executable, str(ROOT / "focus.py"), "--stop"], check=True, timeout=5)
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        raise
            finally:
                target.destroy()
                first.destroy()
                self.pump(0.1)
                original = focus.Wnck.Window.get(original_xid) if original_xid is not None else None
                if original is not None:
                    root = focus.Gdk.get_default_root_window()
                    root.set_events(root.get_events() | focus.Gdk.EventMask.PROPERTY_CHANGE_MASK)
                    original.activate(focus.GdkX11.x11_get_server_time(root))
                    del original
                    self.pump(0.05)
        self.assertEqual(process.returncode, 0, (stdout + stderr).decode())
        self.assertEqual(subprocess.run([sys.executable, str(ROOT / "focus.py"), "--status"],
                                        timeout=5).returncode, 1)


if __name__ == "__main__":
    unittest.main()
