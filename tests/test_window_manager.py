"""Tiling integration failure boundaries and shortcuts shared with the UI."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bindings import WORKSPACES, WINDOWS, shortcut_rows, tiling_bindings
import window_manager as wm


class WindowManagerTests(unittest.TestCase):
    def test_toggle_switches_modes_in_both_directions(self):
        for tiled in (False, True):
            with self.subTest(tiled=tiled), patch.object(sys, "argv", ["abide-wm", "--toggle"]), \
                    patch.object(wm, "enabled", return_value=tiled), \
                    patch.object(wm, "enable") as enable, patch.object(wm, "disable") as disable, \
                    patch.object(wm, "maintenance_lock") as lock:
                self.assertEqual(wm.main(), 0)
                lock.assert_called_once_with(wm.STATE)
                (disable if tiled else enable).assert_called_once_with()
                (enable if tiled else disable).assert_not_called()

    def test_shortcuts_find_user_local_binaries_without_a_shell_path(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "bspc"
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            with patch.object(wm, "BIN", Path(folder)), patch.object(wm.shutil, "which", return_value=None):
                self.assertEqual(wm.executable("bspc"), str(binary))
                self.assertIsNone(wm.executable("bspwm"))

    def test_tiling_keys_replace_snap_keys_and_preserve_app_and_voice_keys(self):
        commands = tiling_bindings(Path("/tmp/Father's Desktop/bin"))
        self.assertEqual(shlex.split(commands["<Super>Left"])[1:], ["focus", "west"])
        self.assertEqual(shlex.split(commands["<Shift><Super>Right"])[1:], ["swap", "east"])
        self.assertEqual(shlex.split(commands["<Primary><Super>Up"])[1:], ["resize", "north"])
        self.assertEqual(shlex.split(commands["<Super>t"])[1:], ["float"])
        for key in ("<Super>j", "<Super>k", "<Super>v", "<Alt><Super>v", "<Primary><Super>v"):
            self.assertNotIn(key, commands)
        with patch("bindings.executable", return_value="/usr/bin/tool"):
            self.assertIn(("Move window with mouse", "Super + left drag"), shortcut_rows([], tiling=True))
            self.assertNotIn(("Tile left", "Super + ←"), shortcut_rows([], tiling=True))

    def test_existing_profiles_gain_workspace_keys_without_losing_restore_values(self):
        original = {"channel": wm.KEYBOARD, "key": "/commands/custom/<Super>1", "kind": "string",
                    "array": False, "value": "previous workspace launcher", "tiling": "old command"}
        data = {"properties": [original], "workspaces": ["1", "2", "3", "4", "5"]}
        with patch.object(wm, "property_value", return_value="previous binding") as read, \
                patch.object(wm, "save_profile") as save:
            wm.update_shortcuts(data)
            self.assertEqual(original["value"], "previous workspace launcher")
            properties = {item["key"]: item for item in data["properties"]}
            floating = {key: action for _title, _label, key, action in WINDOWS}
            for number, symbol in WORKSPACES:
                self.assertEqual(shlex.split(properties[f"/commands/custom/<Super>{number}"]["tiling"])[1:],
                                 ["workspace", str(number)])
                self.assertEqual(shlex.split(properties[f"/commands/custom/<Shift><Super>{symbol}"]["tiling"])[1:],
                                 ["send", str(number)])
                self.assertEqual(floating[f"<Super>{number}"], f"workspace_{number}_key")
            self.assertEqual(properties["/commands/custom/<Super>5"]["value"], "previous binding")
            self.assertEqual(properties["/xfwm4/custom/<Super>5"]["value"], "previous binding")
            save.assert_called_once_with(data)
            read.reset_mock()
            save.reset_mock()
            wm.update_shortcuts(data)
            read.assert_not_called()
            save.assert_not_called()

    def test_missing_dependency_aborts_before_changing_the_desktop(self):
        with patch.object(wm, "executable", return_value=None), patch.object(wm, "save_profile") as save, \
                patch.object(wm, "apply_properties") as change:
            with self.assertRaisesRegex(RuntimeError, "dependencies"):
                wm.enable()
            save.assert_not_called()
            change.assert_not_called()

    def test_failed_first_switch_restores_the_saved_desktop(self):
        with patch.object(wm.shutil, "which", return_value="/usr/bin/tool"), \
                patch.object(wm, "profile", return_value=None), \
                patch.object(wm, "wm_name", return_value="xfwm4"), \
                patch.object(wm, "snapshot", return_value={"saved": True}), \
                patch.object(wm, "save_profile") as save, \
                patch.object(wm, "update_shortcuts"), \
                patch.object(wm, "apply_properties"), \
                patch.object(wm, "start", side_effect=RuntimeError("Startup failed")), \
                patch.object(wm, "disable") as restore:
            with self.assertRaisesRegex(RuntimeError, "Startup failed"):
                wm.enable()
            save.assert_called_once_with({"saved": True})
            restore.assert_called_once()

    def test_reconfiguration_preserves_layout_and_existing_restore_point(self):
        data = {"workspaces": ["Faith", "Hope", "Love"]}
        def reply(*arguments, **_kwargs):
            if arguments == ("bspc", "config", "focus_follows_pointer"):
                return subprocess.CompletedProcess(arguments, 0, "false\n")
            if arguments == ("bspc", "query", "-M", "--names"):
                return subprocess.CompletedProcess(arguments, 0, "screen\n")
            if arguments == ("bspc", "query", "-D", "-m", "screen", "--names"):
                return subprocess.CompletedProcess(arguments, 0, "Faith\nHope\nLove\n")
            return subprocess.CompletedProcess(arguments, 0, "")
        with patch.object(wm, "profile", return_value=data), patch.object(wm, "run", side_effect=reply) as run:
            wm.configure()
        self.assertFalse(any(call.args[:2] == ("bspc", "monitor") for call in run.call_args_list))

    def test_invalid_direction_never_reaches_bspwm(self):
        with patch.object(wm, "run") as run:
            with self.assertRaises(ValueError):
                wm.action("focus", "--kill")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
