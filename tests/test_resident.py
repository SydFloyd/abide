"""Verify warm panels keep their windows and protect journal edits."""
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


@unittest.skipUnless(os.environ.get("ABIDE_GUI_TEST") == "1", "Set ABIDE_GUI_TEST=1 for desktop checks")
class ResidentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("abide_resident", ROOT / "app.py")
        cls.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ui)
        cls.application = cls.ui.Gtk.Application.get_default()
        if cls.application is None:
            cls.application = cls.ui.Gtk.Application(application_id="local.abide.CacheVerification")
            cls.application.register(None)

    def pump(self, seconds=0.15):
        context = self.ui.GLib.MainContext.default()
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="abide-cache-test-")
        self.addCleanup(self.folder.cleanup)
        root = patch.object(self.ui, "ROOT", Path(self.folder.name))
        root.start()
        self.addCleanup(root.stop)
        data = patch.object(self.ui, "JOURNAL", Path(self.folder.name) / "journal")
        data.start()
        self.addCleanup(data.stop)
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            for window in list(app.get_windows()):
                window.destroy()
        self.pump(0.05)

    def guide(self, panel):
        guide = self.ui.Panel(panel, self.application)
        self.apps.append(guide)
        return guide

    def test_hidden_windows_reopen_without_rebuilding(self):
        for panel in ("menu", "shortcuts", "journal"):
            with self.subTest(panel=panel):
                guide = self.guide(panel)
                guide.activate()
                self.pump()
                window = guide.cached_window
                xid = window.get_window().get_xid()
                window.close()
                self.pump()
                self.assertFalse(window.get_visible())
                self.assertFalse(guide.blur_timer)
                with patch.object(guide, "build_window", side_effect=AssertionError("Window rebuilt")):
                    guide.activate()
                self.pump()
                self.assertTrue(window.is_active())
                self.assertEqual(window.get_window().get_xid(), xid)
                window.close()
                self.pump()

    def test_reopening_resets_search_and_menu_route(self):
        menu = self.guide("menu")
        menu.activate()
        self.pump()
        row = next(row for row in menu.menu_list.get_children() if row.get_tooltip_text() == "Capture")
        menu.activate_menu_row(menu.menu_list, row)
        menu.menu_search.set_text("screenshot")
        menu.cached_window.close()
        self.pump()
        menu.activate()
        self.pump()
        self.assertEqual(menu.menu_route, "Abide")
        self.assertFalse(menu.menu_search.get_text())
        self.assertEqual(menu.menu_list.get_selected_row().get_tooltip_text(), "Apps")
        shortcuts = self.guide("shortcuts")
        shortcuts.activate()
        self.pump()
        shortcuts.shortcut_search.set_text("terminal")
        shortcuts.cached_window.close()
        self.pump()
        shortcuts.activate()
        self.pump()
        self.assertFalse(shortcuts.shortcut_search.get_text())
        self.assertFalse(shortcuts.shortcut_empty.get_visible())

    def test_journal_hide_saves_and_reopen_reads_changes(self):
        guide = self.guide("journal")
        guide.activate()
        self.pump()
        guide.editor.get_buffer().set_text("Saved before hiding")
        guide.cached_window.close()
        self.pump()
        entry = self.ui.JOURNAL / (guide.day.isoformat() + ".txt")
        self.assertEqual(entry.read_text(), "Saved before hiding")
        self.assertEqual(entry.stat().st_mode & 0o777, 0o600)
        entry.write_text("Edited outside Abide")
        guide.activate()
        self.pump()
        buffer = guide.editor.get_buffer()
        self.assertEqual(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True),
                         "Edited outside Abide")

    def test_voice_shortcuts_reload_without_rebuilding_window(self):
        guide = self.guide("shortcuts")
        guide.activate()
        self.pump()
        window = guide.cached_window
        window.close()
        self.pump()
        rows = self.ui.DEFAULT_LAUNCHERS + [("Voice integration test", "Hold Super + V", "audio", ["/usr/bin/true"])]
        temporary = self.ui.ROOT / "launchers.voice-tmp"
        temporary.write_text(json.dumps(rows))
        temporary.replace(self.ui.ROOT / "launchers.json")
        with patch.object(guide, "build_window", side_effect=AssertionError("Rebuilt cached window")):
            guide.activate()
        self.pump()
        guide.shortcut_search.set_text("Voice integration test")
        matches = [row for row in guide.shortcut_list.get_children() if guide.shortcut_matches(row)]
        self.assertEqual(len(matches), 1)
        self.assertIn("hold super + v", matches[0].search_text)
        self.assertIs(guide.cached_window, window)
        self.assertFalse(guide.status.get_visible())

    def test_malformed_config_keeps_panel_usable_and_recovers(self):
        path = self.ui.ROOT / "launchers.json"
        path.write_text("{unfinished")
        guide = self.guide("shortcuts")
        guide.activate()
        self.pump()
        self.assertTrue(guide.cached_window.is_active())
        self.assertTrue(guide.status.get_visible())
        self.assertGreater(len(guide.shortcut_list.get_children()), 20)
        guide.cached_window.close()
        self.pump()
        path.write_text("[]")
        guide.activate()
        self.pump()
        self.assertFalse(guide.status.get_visible())

    def test_service_prewarm_and_failed_save_block_stop(self):
        service = self.ui.Panels()
        def guide(panel):
            if panel not in service.guides:
                service.guides[panel] = self.ui.Panel(panel, self.application)
            return service.guides[panel]
        service.guide = guide
        service.prewarm()
        self.assertEqual(set(service.guides), {"menu", "shortcuts"})
        self.assertFalse(self.ui.JOURNAL.exists())
        self.assertTrue(all(not guide.cached_window.get_visible() for guide in service.guides.values()))
        journal = service.guide("journal")
        self.apps.extend(service.guides.values())
        journal.activate()
        self.pump()
        journal.editor.get_buffer().set_text("Protect these edits")
        with patch.object(self.ui.os, "replace", side_effect=OSError("Test save failure")), \
                patch.object(service, "quit") as quit:
            service.on_stop(None, None)
            self.assertTrue(journal.dirty)
            self.assertTrue(journal.cached_window.get_visible())
            self.assertTrue(journal.status.get_visible())
            quit.assert_not_called()
        service.on_stop(None, None)
        self.assertEqual((self.ui.JOURNAL / (journal.day.isoformat() + ".txt")).read_text(), "Protect these edits")

    def test_fast_launcher_requests_toggle_and_service_shutdown(self):
        env = {**os.environ, "HOME": self.folder.name, "XDG_DATA_HOME": self.folder.name + "/data"}
        screen = self.ui.Wnck.Screen.get_default()
        screen.force_update()
        process = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--service"], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        connection = self.ui.Gio.bus_get_sync(self.ui.Gio.BusType.SESSION, None)
        def owned():
            return connection.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                        "org.freedesktop.DBus", "NameHasOwner",
                                        self.ui.GLib.Variant("(s)", ("local.abide.Panels",)),
                                        self.ui.GLib.VariantType.new("(b)"),
                                        self.ui.Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        def wait_active(title):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                window = None
                self.pump(0.02)
                screen.force_update()
                window = screen.get_active_window()
                if window and window.get_name() == title:
                    return window.get_xid()
            self.fail("Panel did not become active: " + title + "; windows="
                      + repr([(window.get_name(), window.is_active()) for window in screen.get_windows()]))
        try:
            deadline = time.monotonic() + 5
            while not owned() and time.monotonic() < deadline:
                self.pump(0.02)
            self.assertTrue(owned(), "Panel service did not start")
            for panel, option, title in (("menu", "--toggle", "Abide"),
                                         ("shortcuts", "--shortcuts", "Abide Shortcuts"),
                                         ("journal", "--journal", "Abide Journal")):
                with self.subTest(panel=panel):
                    subprocess.run(["sh", str(ROOT / "launcher.sh"), option], check=True, env=env, timeout=3)
                    xid = wait_active(title)
                    if panel == "menu":
                        subprocess.run(["sh", str(ROOT / "launcher.sh"), "--toggle"], check=True, env=env, timeout=3)
                    else:
                        window = self.ui.Wnck.Window.get(xid)
                        window.close(self.ui.Gdk.Display.get_default().get_user_time())
                        del window
                    self.pump(0.2)
                    screen.force_update()
                    self.assertTrue(owned(), "Closing a panel stopped the service")
                    subprocess.run(["sh", str(ROOT / "launcher.sh"), option], check=True, env=env, timeout=3)
                    self.assertEqual(wait_active(title), xid)
            subprocess.run(["gapplication", "action", "local.abide.Panels", "stop"], check=True, timeout=3)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, (stdout + stderr).decode())
            self.assertFalse(owned())
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
