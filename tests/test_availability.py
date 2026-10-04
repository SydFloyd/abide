"""Missing add-ins must not leave advertised shortcuts or launcher entries."""
import os
from pathlib import Path
import tempfile
import shlex
import unittest
from unittest.mock import patch

import availability
from bindings import command_bindings, shortcut_rows
import install
from webapps import WEB_APPS, desktop_entry


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        environment = {"XDG_CONFIG_HOME": str(self.home / "config"),
                       "XDG_CONFIG_DIRS": str(self.home / "system-config"),
                       "XDG_DATA_HOME": str(self.home / "data"),
                       "XDG_DATA_DIRS": str(self.home / "system-data")}
        env_patch = patch.dict(os.environ, environment)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_wrappers_without_backends_do_not_advertise_or_bind_optional_apps(self):
        tools = {"exo-open", "xflock4", "xfwm4", "abide-webapp"}
        with patch.object(availability, "executable", side_effect=lambda name: name if name in tools else None):
            titles = {title for title, _keys in shortcut_rows([
                ["Missing voice", "Super + V", "audio", ["missing-voice"]]])}
            self.assertTrue({"Abide menu", "Journal", "Shortcuts"} <= titles)
            self.assertFalse({"Terminal", "Browser", "X", "Gmail", "Lock", "Files",
                              "Mousepad", "Screenshot", "System monitor", "Missing voice"} & titles)
            keys = command_bindings(self.home / "bin")
            for key in ("<Super>Return", "<Super>b", "<Shift><Super>x", "<Shift><Super>e", "Print"):
                self.assertIsNone(keys[key])
            self.assertIsNotNone(keys["<Super>space"])
            self.assertFalse(availability.command_available(["abide-wm", "--enable"]))

    def test_selected_helper_must_be_installed_even_if_another_browser_exists(self):
        config = self.home / "config/xfce4"
        config.mkdir(parents=True)
        (config / "helpers.rc").write_text("WebBrowser=custom-browser\n")
        helpers = self.home / "data/xfce4/helpers"
        helpers.mkdir(parents=True)
        (helpers / "custom-browser.desktop").write_text(
            "[Desktop Entry]\nX-XFCE-Binaries=custom-browser;\nX-XFCE-Commands=%B;\n")
        tools = {"exo-open", "chromium"}
        with patch.object(availability, "executable", side_effect=lambda name: name if name in tools else None), \
                patch.object(availability.shutil, "which", side_effect=lambda name: name if name in tools else None):
            self.assertFalse(availability.command_available(["exo-open", "--launch", "WebBrowser"]))
            tools.add("custom-browser")
            self.assertTrue(availability.command_available(["exo-open", "--launch", "WebBrowser"]))

    def test_debian_browser_wrapper_needs_a_real_browser_alternative(self):
        config = self.home / "config/xfce4"
        config.mkdir(parents=True)
        (config / "helpers.rc").write_text("WebBrowser=debian-sensible-browser\n")
        tools = {"exo-open", "sensible-browser"}
        with patch.object(availability, "executable", side_effect=lambda name: name if name in tools else None):
            self.assertFalse(availability.command_available(["exo-open", "--launch", "WebBrowser"]))
            tools.add("x-www-browser")
            self.assertTrue(availability.command_available(["exo-open", "--launch", "WebBrowser"]))

    def test_only_existing_workspaces_and_window_manager_shortcuts_are_listed(self):
        with patch("bindings.executable", return_value="/usr/bin/xfwm4"):
            titles = {title for title, _keys in shortcut_rows([], workspace_count=3)}
            self.assertIn("Workspace 3", titles)
            self.assertNotIn("Workspace 4", titles)
            self.assertNotIn("Move to workspace 5", titles)
        with patch("bindings.executable", return_value=None):
            titles = {title for title, _keys in shortcut_rows([], tiling=True)}
            self.assertNotIn("Focus west", titles)
            self.assertNotIn("Move window with mouse", titles)

    def test_user_local_app_hotkeys_resolve_without_the_desktop_path(self):
        binary = self.home / ".local/bin/thunar"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        with patch.object(availability.Path, "home", return_value=self.home), \
                patch.dict(os.environ, {"PATH": "/nonexistent"}):
            commands = command_bindings(self.home / ".local/bin")
            self.assertEqual(shlex.split(commands["<Super>e"]), [str(binary)])

    def test_refresh_removes_missing_app_keys_without_touching_tiling_or_voice(self):
        with patch.object(install, "command_bindings", return_value={"<Super>b": None, "<Super>t": None}), \
                patch.object(install, "xfconf", return_value="old browser") as keys, \
                patch.object(install, "replace_file"):
            install.refresh_shortcuts()
        self.assertEqual([call.args for call in keys.call_args_list], [("<Super>b",), ("<Super>b", None)])

    def test_webapp_desktop_entries_follow_chromium_availability(self):
        with patch("webapps.command_available", return_value=False):
            self.assertIn("NoDisplay=true", desktop_entry(WEB_APPS[0], self.home / "bin"))
        with patch("webapps.command_available", return_value=True):
            self.assertNotIn("NoDisplay=true", desktop_entry(WEB_APPS[0], self.home / "bin"))


if __name__ == "__main__":
    unittest.main()
