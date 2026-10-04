"""Behavior checks for dedicated panels, private data, and desktop activation."""
import importlib.util
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class InstallationTests(unittest.TestCase):
    def test_requested_bindings_and_removed_old_bindings(self):
        installer = module("abide_install", "install.py")
        self.assertEqual(shlex.split(installer.KEYS["<Super>space"]), [str(installer.BIN / "abide-guide"), "--toggle"])
        self.assertTrue(installer.KEYS["<Super>j"].endswith("--journal"))
        self.assertTrue(installer.KEYS["<Super>k"].endswith("--shortcuts"))
        self.assertTrue(installer.KEYS["<Super>Return"].endswith("--terminal"))
        self.assertIsNone(installer.KEYS["<Super>slash"])
        self.assertIsNone(installer.KEYS["<Super>t"])
        self.assertIsNone(installer.KEYS["<Super>q"])
        self.assertEqual(installer.KEYS["<Shift><Super>f"], "thunar")
        self.assertEqual(installer.WINDOW_KEYS["<Super>f"], "fullscreen_key")

    def test_install_preserves_private_data(self):
        installer = module("abide_private_install", "install.py")
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            data = home / ".local/share/abide"
            (data / "journal").mkdir(parents=True)
            secret = "PRIVATE_VERIFICATION_ENTRY"
            for name in ("journal/2026-01-01.txt", "launchers.json", "scripture.json"):
                (data / name).write_text(secret)
            with patch.object(installer, "HOME", home), patch.object(installer, "ROOT", data), \
                    patch.object(installer, "BIN", home / ".local/bin"):
                files = installer.targets()
            self.assertNotIn(data / "scripture.json", files)
            self.assertNotIn(data / "launchers.json", files)
            self.assertFalse(any("journal" in path.parts for path in files))
            self.assertFalse(any(secret.encode() in contents for contents in files.values()))
            self.assertEqual((data / "journal/2026-01-01.txt").read_text(), secret)
            self.assertIn(home / ".local/bin/abide-focus", files)
            self.assertIn(home / ".config/autostart/abide-focus.desktop", files)
            self.assertIn(home / ".local/bin/abide-panels", files)
            self.assertIn(home / ".config/autostart/abide-panels.desktop", files)
            self.assertIn(home / ".local/share/dbus-1/services/local.abide.Panels.service", files)

    def test_undo_stops_focus_and_preserves_previous_service_state(self):
        installer = module("abide_undo_install", "install.py")
        snapshot = {"shortcuts": {}, "files": {}, "focus_listener": False}
        with patch.object(installer, "stop_focus") as stop, patch.object(installer, "start_focus") as start, \
                patch.object(installer, "stop_panels") as stop_panels, \
                patch.object(installer, "start_panels") as start_panels, \
                patch.object(installer.Path, "exists", return_value=True):
            installer.restore(Path("unused-backup"), snapshot)
            stop.assert_called_once()
            start.assert_not_called()
            stop_panels.assert_called_once()
            start_panels.assert_not_called()
            snapshot["focus_listener"] = True
            snapshot["panels_running"] = True
            installer.restore(Path("unused-backup"), snapshot)
            start.assert_called_once()
            start_panels.assert_called_once()

    def test_failed_focus_start_restores_installation(self):
        installer = module("abide_rollback_install", "install.py")
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            state = home / ".local/state/abide"
            target = home / ".local/share/abide/focus.py"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"PREVIOUS_SOURCE")
            with patch.object(installer, "HOME", home), patch.object(installer, "STATE", state), \
                    patch.object(installer, "BIN", home / ".local/bin"), \
                    patch.object(installer, "LEGACY_AUTOSTART", home / ".config/autostart/legacy.desktop"), \
                    patch.object(installer, "targets", return_value={target: b"NEW_SOURCE"}), \
                    patch.object(installer, "check_environment", return_value=[]), \
                    patch.object(installer, "window_bindings", return_value=installer.WINDOW_KEYS), \
                    patch.object(installer, "xfconf", return_value=None), \
                    patch.object(installer, "focus_running", return_value=False), \
                    patch.object(installer, "panels_running", return_value=False), \
                    patch.object(installer, "stop_panels"), \
                    patch.object(installer, "stop_focus"), \
                    patch.object(installer, "start_focus", side_effect=RuntimeError("Service unavailable")), \
                    patch.object(sys, "argv", ["install.py"]):
                with self.assertRaisesRegex(RuntimeError, "Service unavailable"):
                    installer.main()
            self.assertEqual(target.read_bytes(), b"PREVIOUS_SOURCE")
            self.assertFalse((state / "latest-panels-install").exists())

    def test_failed_panels_start_restores_installation(self):
        installer = module("abide_panels_rollback_install", "install.py")
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            state = home / ".local/state/abide"
            target = home / ".local/bin/abide-guide"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"PREVIOUS_LAUNCHER")
            (target.parent / "abide-focus").write_bytes(b"PREVIOUS_FOCUS_HELPER")
            autostart = home / ".config/autostart/abide-panels.desktop"
            with patch.object(installer, "HOME", home), patch.object(installer, "STATE", state), \
                    patch.object(installer, "BIN", home / ".local/bin"), \
                    patch.object(installer, "LEGACY_AUTOSTART", home / ".config/autostart/legacy.desktop"), \
                    patch.object(installer, "targets", return_value={target: b"NEW_LAUNCHER", autostart: b"NEW_SERVICE"}), \
                    patch.object(installer, "check_environment", return_value=[]), \
                    patch.object(installer, "window_bindings", return_value=installer.WINDOW_KEYS), \
                    patch.object(installer, "xfconf", return_value=None), \
                    patch.object(installer, "focus_running", return_value=True), \
                    patch.object(installer, "panels_running", return_value=False), \
                    patch.object(installer, "stop_panels"), patch.object(installer, "stop_focus"), \
                    patch.object(installer, "start_focus") as start_focus, \
                    patch.object(installer, "start_panels", side_effect=RuntimeError("Panels unavailable")), \
                    patch.object(sys, "argv", ["install.py"]):
                with self.assertRaisesRegex(RuntimeError, "Panels unavailable"):
                    installer.main()
                self.assertEqual(start_focus.call_count, 2)
            self.assertEqual(target.read_bytes(), b"PREVIOUS_LAUNCHER")
            self.assertFalse(autostart.exists())
            self.assertFalse((state / "latest-panels-install").exists())


@unittest.skipUnless(os.environ.get("ABIDE_GUI_TEST") == "1", "Set ABIDE_GUI_TEST=1 for desktop checks")
class PanelTests(unittest.TestCase):
    MODES = {
        "test_search_action_key_alias_and_empty_results": "shortcuts",
        "test_shortcuts_layout_and_keyboard_search": "shortcuts",
        "test_journal_focus_loss_saves_before_closing": "journal",
        "test_failed_save_protects_journal": "journal",
        "test_date_popup_retains_journal": "journal",
        "test_date_selection_saves_and_reloads_entries": "journal",
        "test_terminal_shortcut_closes_journal_and_focuses_terminal": "journal",
    }

    @classmethod
    def setUpClass(cls):
        cls.ui = module("abide_app", "app.py")
        cls.application = cls.ui.Guide()
        cls.application.set_application_id("local.abide.Verification")
        cls.application.register(None)

    @classmethod
    def tearDownClass(cls):
        cls.application.quit()

    def pump(self, seconds=0.25):
        context = self.ui.GLib.MainContext.default()
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)

    def open_panel(self, panel):
        # Exercise the standalone fallback with one GTK registration while
        # building each panel's UI. The resident service has its own tests.
        self.app = self.application
        self.app.panel = panel
        self.app.activate()
        self.window = self.app.get_active_window()
        self.window.set_title("Abide verification · " + panel)
        self.window.present()
        self.pump()
        self.assertTrue(self.window.is_active())

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="abide-verification-")
        self.addCleanup(self.temporary.cleanup)
        root_patch = patch.object(self.ui, "ROOT", Path(self.temporary.name))
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.journal_patch = patch.object(self.ui, "JOURNAL", Path(self.temporary.name) / "journal")
        self.journal_patch.start()
        self.addCleanup(self.journal_patch.stop)
        self.open_panel(self.MODES.get(self._testMethodName, "menu"))

    def tearDown(self):
        for window in list(self.application.get_windows()):
            window.destroy()
        self.pump(0.05)

    def test_panels_are_separate_without_tabs(self):
        applications = [self.ui.Guide(panel) for panel in ("menu", "journal", "shortcuts")]
        identities = {app.get_application_id() for app in applications}
        self.assertEqual(len(identities), 3)
        def widgets(parent):
            yield parent
            if isinstance(parent, self.ui.Gtk.Container):
                for child in parent.get_children():
                    yield from widgets(child)
        for panel in ("menu", "journal", "shortcuts"):
            if self.app.get_windows():
                self.window.destroy()
            self.open_panel(panel)
            self.assertFalse(hasattr(self.app, "stack"))
            tree = list(widgets(self.app.page))
            self.assertEqual(any(isinstance(widget, self.ui.Gtk.TextView) for widget in tree), panel == "journal")
            self.assertEqual(any(isinstance(widget, self.ui.Gtk.SearchEntry) for widget in tree), panel != "journal")
            self.assertFalse(self.window.get_decorated())
            self.assertFalse(self.window.get_resizable())
            self.assertTrue(self.window.get_window().get_state() & self.ui.Gdk.WindowState.ABOVE)
            self.assertFalse(self.app.status.get_visible())
            texts = [widget.get_text() for widget in tree if isinstance(widget, self.ui.Gtk.Label)]
            self.assertNotIn("Faith · Hope · Love", texts)
            self.assertNotIn("SHORTCUTS", texts)
            self.assertFalse(any("Quiet mode" in text or "Esc ·" in text for text in texts))
            if panel == "journal":
                self.assertEqual(len(self.app.page.get_children()), 2)
                self.assertIn("Journal", texts)
                self.assertFalse(self.app.date_popover.get_visible())

    def menu_key(self, keyval):
        event = self.ui.Gdk.Event.new(self.ui.Gdk.EventType.KEY_PRESS)
        event.keyval = keyval
        event.state = 0
        return self.app.on_key(self.window, event)

    def test_menu_search_finds_nested_actions_and_enter_launches(self):
        self.app.menu_search.set_text("display")
        self.pump(0.05)
        rows = self.app.menu_list.get_children()
        self.assertEqual([row.get_tooltip_text() for row in rows], ["Display"])
        with patch.object(self.app, "launch") as launch:
            self.assertTrue(self.menu_key(self.ui.Gdk.KEY_Return))
            launch.assert_called_once_with(rows[0], ["xfce4-display-settings"])
        self.app.menu_search.set_text("no_such_menu_action")
        self.assertTrue(self.app.menu_empty.get_visible())
        self.menu_key(self.ui.Gdk.KEY_Return)
        self.app.menu_search.set_text("")
        titles = [row.get_tooltip_text() for row in self.app.menu_list.get_children()]
        self.assertNotIn("Terminal", titles)
        self.assertNotIn("Browser", titles)
        self.assertNotIn("Mousepad", titles)
        self.assertFalse(self.app.menu_empty.get_visible())

    def test_menu_keyboard_navigation_back_and_dismissal(self):
        self.assertIs(self.window.get_focus(), self.app.menu_search)
        self.menu_key(self.ui.Gdk.KEY_Down)
        self.menu_key(self.ui.Gdk.KEY_Return)
        self.assertEqual(self.app.menu_route, "Settings")
        self.assertEqual(self.app.menu_list.get_row_at_index(0).get_tooltip_text(), "Back")
        self.menu_key(self.ui.Gdk.KEY_Escape)
        self.assertEqual(self.app.menu_route, "Abide")
        self.assertEqual(self.app.menu_list.get_selected_row().get_tooltip_text(), "Settings")
        self.assertEqual(self.app.get_windows(), [self.window])
        for route, back in (("Capture", "click"), ("Session", "backspace"), ("Settings", "escape")):
            with self.subTest(route=route, back=back):
                self.app.menu_search.set_text(route.casefold())
                self.menu_key(self.ui.Gdk.KEY_Return)
                self.assertEqual(self.app.menu_route, route)
                self.assertFalse(self.app.menu_search.get_text())
                if back == "click":
                    self.app.activate_menu_row(self.app.menu_list, self.app.menu_list.get_row_at_index(0))
                else:
                    self.menu_key(self.ui.Gdk.KEY_BackSpace if back == "backspace" else self.ui.Gdk.KEY_Escape)
                self.assertEqual(self.app.menu_route, "Abide")
                self.assertEqual(self.app.menu_list.get_selected_row().get_tooltip_text(), route)
                self.assertIs(self.window.get_focus(), self.app.menu_search)
        self.menu_key(self.ui.Gdk.KEY_Escape)
        self.pump(0.05)
        self.assertEqual(self.app.get_windows(), [])

    def test_menu_sizes_to_visible_actions(self):
        main = self.window.get_size()
        self.assertLess(main.width, 350)
        for route in ("Session", "Settings", "Capture", "Abide"):
            with self.subTest(route=route):
                self.app.change_menu_route(route)
                self.pump(0.1)
                last = self.app.menu_list.get_children()[-1].get_allocation()
                blank = self.app.menu_list.get_allocated_height() - last.y - last.height
                self.assertLessEqual(blank, 2, "Unused space below the last menu row")
                height = self.window.get_size().height
                if route == "Session":
                    self.assertLess(height, main.height)
                elif route == "Settings":
                    self.assertGreater(height, main.height)
                elif route == "Abide":
                    self.assertEqual(height, main.height)
        self.app.menu_search.set_text("simplescreenrecorder")
        self.pump(0.1)
        self.assertEqual([row.get_tooltip_text() for row in self.app.menu_list.get_children()], ["Record screen"])
        self.assertLess(self.window.get_size().height, main.height)

    def search(self, text):
        self.app.shortcut_search.set_text(text)
        self.pump(0.05)
        return [row.get_child().get_children()[0].get_text()
                for row in self.app.shortcut_list.get_children() if row.get_child_visible()]

    def test_search_action_key_alias_and_empty_results(self):
        self.assertEqual(self.search("terminal"), ["Terminal"])
        self.assertEqual(self.search("sUpEr + Return"), ["Terminal", "Browser"])
        self.assertEqual(self.search("Windows Enter"), ["Terminal", "Browser"])
        self.assertEqual(self.search("journal"), ["Journal"])
        self.assertEqual(self.search("missing_unlikely_shortcut"), [])
        self.assertTrue(self.app.shortcut_empty.get_visible())
        self.assertGreater(len(self.search("")), 20)
        self.assertFalse(self.app.shortcut_empty.get_visible())

    def test_shortcuts_layout_and_keyboard_search(self):
        self.assertIs(self.app.page.get_children()[0], self.app.shortcut_search)
        self.assertIs(self.window.get_focus(), self.app.shortcut_search)
        adjustment = self.app.shortcut_scroll.get_vadjustment()
        self.assertGreater(adjustment.get_upper(), adjustment.get_page_size())
        self.assertGreaterEqual(self.window.get_size().width, 800)
        self.app.shortcut_search.set_text("Terminal")
        event = self.ui.Gdk.Event.new(self.ui.Gdk.EventType.KEY_PRESS)
        event.keyval = self.ui.Gdk.KEY_f
        event.state = self.ui.Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(self.app.on_key(self.window, event))
        self.assertEqual(self.app.shortcut_search.get_selection_bounds(), (0, 8))

    def test_every_panel_closes_on_focus_loss(self):
        for panel in ("menu", "journal", "shortcuts"):
            if self.app.get_windows():
                self.window.destroy()
            self.open_panel(panel)
            other = self.ui.Gtk.Window(title="Abide focus verification")
            try:
                other.show_all()
                other.present()
                self.pump(0.4)
                self.assertEqual(self.app.get_windows(), [], panel)
                self.assertEqual(self.app.blur_timer, 0)
                self.assertEqual(self.app.launch_timer, 0)
            finally:
                other.destroy()

    def test_journal_focus_loss_saves_before_closing(self):
        self.app.editor.get_buffer().set_text("Temporary verification entry")
        other = self.ui.Gtk.Window(title="Abide save verification")
        try:
            other.show_all()
            other.present()
            self.pump(0.4)
            self.assertEqual(self.app.get_windows(), [])
            entry = self.ui.JOURNAL / (self.app.day.isoformat() + ".txt")
            self.assertEqual(entry.read_text(), "Temporary verification entry")
            self.assertEqual(entry.stat().st_mode & 0o777, 0o600)
            self.assertEqual(entry.parent.stat().st_mode & 0o777, 0o700)
        finally:
            other.destroy()

    def test_failed_save_protects_journal(self):
        self.app.editor.get_buffer().set_text("Preserve these edits")
        with patch.object(self.ui.os, "replace", side_effect=OSError("Verification save failure")):
            self.window.close()
            self.pump(0.05)
            self.assertEqual(self.app.get_windows(), [self.window])
            self.assertTrue(self.app.dirty)
            self.assertIn("Verification save failure", self.app.status.get_text())
            self.assertTrue(self.app.status.get_visible())
            day = self.app.day
            self.app.change_day(-1)
            self.assertEqual(self.app.day, day)
        self.window.close()
        self.pump(0.05)
        self.assertEqual(self.app.get_windows(), [])

    def test_date_popup_retains_journal(self):
        self.app.date_button.set_active(True)
        self.pump(0.3)
        self.assertEqual(self.app.get_windows(), [self.window])
        self.app.date_popover.popdown()
        self.pump(0.25)
        self.assertEqual(self.app.get_windows(), [self.window])

    def test_date_selection_saves_and_reloads_entries(self):
        self.app.day = self.ui.date.today()
        self.app.load_day()
        today = self.app.day
        self.app.editor.get_buffer().set_text("Entry saved before date change")
        yesterday = today - self.ui.timedelta(days=1)
        self.app.syncing_date = True
        self.app.calendar.select_month(yesterday.month - 1, yesterday.year)
        self.app.syncing_date = False
        self.app.calendar.select_day(yesterday.day)
        self.assertEqual(self.app.day, yesterday)
        path = self.ui.JOURNAL / (today.isoformat() + ".txt")
        self.assertEqual(path.read_text(), "Entry saved before date change")
        self.app.change_day(1)
        buffer = self.app.editor.get_buffer()
        self.assertEqual(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True),
                         "Entry saved before date change")
        self.assertFalse(self.app.status.get_visible())

    def launch_button(self, title, command):
        button = self.ui.Gtk.Button(label=title)
        button.set_tooltip_text(title)
        button.connect("clicked", self.app.launch, command)
        return button

    def test_app_launch_has_activation_and_dismisses_menu(self):
        output = Path(self.temporary.name) / "result.json"
        script = Path(self.temporary.name) / "launch check.py"
        script.write_text("import json, os, pathlib, sys\n"
                          "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
                          "'startup': os.environ.get('DESKTOP_STARTUP_ID'), 'args': sys.argv[2:]}))\n")
        command = [sys.executable, str(script), str(output), "a value with spaces", "it's literal"]
        button = self.launch_button("Launch verification", command)
        self.app.page.pack_start(button, False, False, 0)
        button.show_all()
        button.clicked()
        self.pump(0.3)
        self.assertEqual(self.app.get_windows(), [])
        launched = json.loads(output.read_text())
        self.assertTrue(launched["startup"])
        self.assertNotEqual(launched["startup"].rsplit("_TIME", 1)[-1], "0")
        self.assertEqual(launched["args"], ["a value with spaces", "it's literal"])

    def test_failed_app_launch_retains_menu(self):
        button = self.launch_button("Missing app", ["/nonexistent/abide-verification"])
        self.app.page.pack_start(button, False, False, 0)
        button.show_all()
        button.clicked()
        self.pump(0.1)
        self.assertEqual(self.app.get_windows(), [self.window])
        self.assertIn("is not installed", self.app.status.get_text())

    def check_terminal(self, launch):
        screen = self.ui.Wnck.Screen.get_default()
        screen.force_update()
        existing = {window.get_xid() for window in screen.get_windows()}
        terminal_xid = None
        process = None
        def active_xid():
            active = screen.get_active_window()
            return active.get_xid() if active else None
        try:
            process = launch()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                self.pump(0.05)
                terminal = self.ui.new_terminal(screen, existing)
                if terminal:
                    terminal_xid = terminal.get_xid()
                del terminal
                if terminal_xid and active_xid() == terminal_xid and not self.app.get_windows():
                    break
            self.assertTrue(terminal_xid, "The preferred terminal should open a new window")
            self.assertEqual(active_xid(), terminal_xid)
            self.assertEqual(self.app.get_windows(), [])
            self.assertEqual(self.app.launch_timer, 0)
            if process:
                self.assertEqual(process.wait(timeout=2), 0)
        finally:
            terminal = self.ui.Wnck.Window.get(terminal_xid) if terminal_xid else None
            if terminal is not None:
                terminal.close(self.ui.Gdk.Display.get_default().get_user_time())
            del terminal
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
            self.pump(0.1)

    def test_terminal_shortcut_closes_journal_and_focuses_terminal(self):
        self.app.editor.get_buffer().set_text("Save before opening a terminal")
        self.check_terminal(lambda: subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--terminal"]))
        entry = self.ui.JOURNAL / (self.app.day.isoformat() + ".txt")
        self.assertEqual(entry.read_text(), "Save before opening a terminal")


if __name__ == "__main__":
    unittest.main()
