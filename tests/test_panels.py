"""Behavior checks for dedicated panels, private data, and desktop activation."""
import importlib.util
import json
import os
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
        self.assertTrue(installer.KEYS["<Super>space"].endswith("abide-guide --toggle"))
        self.assertTrue(installer.KEYS["<Super>j"].endswith("--journal"))
        self.assertTrue(installer.KEYS["<Super>k"].endswith("--shortcuts"))
        self.assertTrue(installer.KEYS["<Super>Return"].endswith("--terminal"))
        self.assertIsNone(installer.KEYS["<Super>slash"])
        self.assertIsNone(installer.KEYS["<Super>t"])

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


@unittest.skipUnless(os.environ.get("ABIDE_GUI_TEST") == "1", "Set ABIDE_GUI_TEST=1 for desktop checks")
class PanelTests(unittest.TestCase):
    MODES = {
        "test_search_action_key_alias_and_empty_results": "shortcuts",
        "test_shortcuts_layout_and_keyboard_search": "shortcuts",
        "test_journal_focus_loss_saves_before_closing": "journal",
        "test_failed_save_protects_journal": "journal",
        "test_scripture_popup_retains_journal": "journal",
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
        # Production runs one application per panel/process. Reuse one GTK
        # registration in this test process while building each panel's UI.
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
        self.journal_patch = patch.object(self.ui, "JOURNAL", Path(self.temporary.name) / "journal")
        self.journal_patch.start()
        self.addCleanup(self.journal_patch.stop)
        self.quiet_patch = patch.object(self.ui.Guide, "sync_quiet", lambda _self: True)
        self.quiet_patch.start()
        self.addCleanup(self.quiet_patch.stop)
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
            self.assertEqual(any(isinstance(widget, self.ui.Gtk.SearchEntry) for widget in tree), panel == "shortcuts")

    def search(self, text):
        self.app.shortcut_search.set_text(text)
        self.pump(0.05)
        return [row.get_child().get_children()[0].get_text()
                for row in self.app.shortcut_list.get_children() if row.get_child_visible()]

    def test_search_action_key_alias_and_empty_results(self):
        self.assertEqual(self.search("terminal"), ["Terminal"])
        self.assertEqual(self.search("sUpEr + Return"), ["Terminal"])
        self.assertEqual(self.search("Windows Enter"), ["Terminal"])
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
        self.assertGreaterEqual(self.window.get_size().width, 900)
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
            self.assertIn("Verification save failure", self.app.save_status.get_text())
        self.window.close()
        self.pump(0.05)
        self.assertEqual(self.app.get_windows(), [])

    def test_scripture_popup_retains_journal(self):
        self.app.scripture.popup()
        self.pump(0.3)
        self.assertEqual(self.app.get_windows(), [self.window])
        self.app.scripture.popdown()
        self.pump(0.25)
        self.assertEqual(self.app.get_windows(), [self.window])

    def test_app_launch_has_activation_and_dismisses_menu(self):
        output = Path(self.temporary.name) / "result.json"
        script = Path(self.temporary.name) / "launch check.py"
        script.write_text("import json, os, pathlib, sys\n"
                          "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
                          "'startup': os.environ.get('DESKTOP_STARTUP_ID'), 'args': sys.argv[2:]}))\n")
        command = [sys.executable, str(script), str(output), "a value with spaces", "it's literal"]
        button = self.app.app_button("Launch verification", "", "utilities-terminal-symbolic", command)
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
        button = self.app.app_button("Missing app", "", "utilities-terminal-symbolic",
                                     ["/nonexistent/abide-verification"])
        self.app.page.pack_start(button, False, False, 0)
        button.show_all()
        button.clicked()
        self.pump(0.1)
        self.assertEqual(self.app.get_windows(), [self.window])
        self.assertIn("Could not open this app", self.app.status.get_text())

    def check_terminal(self, launch):
        screen = self.ui.Wnck.Screen.get_default()
        screen.force_update()
        existing = {window.get_xid() for window in screen.get_windows()}
        new = []
        process = None
        try:
            process = launch()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                self.pump(0.05)
                terminal = self.ui.new_terminal(screen, existing)
                if terminal:
                    new = [terminal]
                    active = screen.get_active_window()
                    if active and active.get_xid() == terminal.get_xid() and not self.app.get_windows():
                        break
            self.assertTrue(new, "The preferred terminal should open a new window")
            self.assertEqual(screen.get_active_window().get_xid(), new[0].get_xid())
            self.assertEqual(self.app.get_windows(), [])
            self.assertEqual(self.app.launch_timer, 0)
            if process:
                self.assertEqual(process.wait(timeout=2), 0)
        finally:
            for terminal in new:
                terminal.close(self.ui.Gdk.Display.get_default().get_user_time())
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
            self.pump(0.1)

    def test_terminal_button_focuses_destination_and_closes_menu(self):
        button = next(button for button in self.app.launcher_grid.get_children()
                      if button.get_tooltip_text().startswith("Terminal ·"))
        self.check_terminal(button.clicked)

    def test_terminal_shortcut_closes_journal_and_focuses_terminal(self):
        self.app.editor.get_buffer().set_text("Save before opening a terminal")
        self.check_terminal(lambda: subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--terminal"]))
        entry = self.ui.JOURNAL / (self.app.day.isoformat() + ".txt")
        self.assertEqual(entry.read_text(), "Save before opening a terminal")


if __name__ == "__main__":
    unittest.main()
