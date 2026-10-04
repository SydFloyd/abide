"""Exercise updates with a real local main branch; no network or desktop changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bindings import APPLICATIONS, WINDOWS, command_bindings, shortcut_rows
from config import load_launchers
import install
from release import CODE_FILES, install_identity, maintenance_lock, manifest, verify_installation
from updater import Updater

SOURCE = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def test_bad_custom_config_keeps_defaults(self):
        defaults = [["Terminal", "Super + Return", "terminal", ["exo-open"]]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "launchers.json"
            self.assertEqual(load_launchers(path, defaults), (defaults, None))
            for text in ("{", "null", "{}", '[1]', '[["Voice","V","icon",[]]]',
                         '[["Voice","V","icon",[1]]]', " " * 262145):
                with self.subTest(text=text[:30]):
                    path.write_text(text)
                    rows, error = load_launchers(path, defaults)
                    self.assertEqual(rows, defaults)
                    self.assertTrue(error)
            valid = [["Voice", "Hold Super + V", "audio", ["voice", "listen"]]]
            path.write_text(json.dumps(valid))
            self.assertEqual(load_launchers(path, defaults), (valid, None))

    def test_shortcut_registry_covers_installed_keys_and_integrations(self):
        custom = [["Terminal", "My terminal keys", "icon", ["terminal"]],
                  ["Voice", "Hold Super + V", "icon", ["voice"]]]
        rows = shortcut_rows(custom)
        self.assertEqual([keys for title, keys in rows if title == "Terminal"], ["My terminal keys"])
        self.assertIn(("Voice", "Hold Super + V"), rows)
        commands = command_bindings(Path("/tmp/Father's Desktop/bin"))
        self.assertIn("'/tmp/Father", commands["<Super>space"])
        for _title, _label, keys, _command in APPLICATIONS:
            for key in keys:
                self.assertIsNotNone(commands[key])
        self.assertTrue({action for _title, _label, _key, action in WINDOWS})
        self.assertNotIn("<Super>v", commands)
        self.assertNotIn("<Alt><Super>v", commands)
        self.assertNotIn("<Primary><Super>v", commands)


class MaintenanceTests(unittest.TestCase):
    def test_lock_excludes_concurrent_install_and_releases_after_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            with maintenance_lock(state):
                with self.assertRaisesRegex(RuntimeError, "Another Abide"):
                    with maintenance_lock(state):
                        self.fail("Concurrent install was admitted")
            with self.assertRaisesRegex(RuntimeError, "Test failure"):
                with maintenance_lock(state):
                    raise RuntimeError("Test failure")
            with maintenance_lock(state):
                pass

    def test_preflight_error_changes_nothing(self):
        with patch.object(install, "check_environment", return_value=["Missing GTK"]), \
                patch.object(install, "install") as mutation, \
                patch("sys.argv", ["install.py"]):
            with self.assertRaisesRegex(RuntimeError, "Missing GTK"):
                install.main()
            mutation.assert_not_called()

    def test_window_conflicts_are_backed_up_before_rebinding(self):
        listing = ("/xfwm4/custom/<Primary>F1 workspace_1_key\n"
                   "/xfwm4/custom/<Alt>F10 maximize_window_key\n"
                   "/xfwm4/custom/<Alt>F12 above_key\n"
                   "/commands/custom/<Super>v voice desktop\n")
        with patch.object(install.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, listing)):
            keys = install.window_bindings()
        self.assertIsNone(keys["<Primary>F1"])
        self.assertIsNone(keys["<Alt>F10"])
        self.assertNotIn("<Alt>F12", keys)
        self.assertNotIn("<Super>v", keys)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="abide-updater-test-")
        self.addCleanup(self.folder.cleanup)
        base = Path(self.folder.name)
        self.remote = base / "upstream"
        self.remote.mkdir()
        self.root = base / "installed"
        self.root.mkdir()
        self.state = base / "state"
        self.updater = Updater(self.root, self.state, str(self.remote))
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.name", "Abide test")
        self.git("config", "user.email", "abide-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        for name in CODE_FILES:
            shutil.copy2(SOURCE / name, self.remote / name)
        tests = self.remote / "tests"
        tests.mkdir()
        (tests / "test_panels.py").write_text("import unittest\nclass Smoke(unittest.TestCase):\n def test_release(self): pass\n")
        self.base_revision = self.commit("Initial main")
        self.copy_installed(self.remote)
        (self.root / "journal").mkdir()
        (self.root / "journal/private.txt").write_text("PRIVATE_TEST_ENTRY")
        (self.root / "launchers.json").write_text("PRIVATE_VOICE_CONFIGURATION")

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.remote), *arguments],
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def advance(self):
        with (self.remote / "app.css").open("a") as file:
            file.write("\n/* Test update */\n")
        return self.commit("An update")

    def copy_installed(self, source):
        for name in CODE_FILES:
            shutil.copy2(source / name, self.root / name)
        (self.root / "release.json").write_text(json.dumps(manifest(source)))

    def assert_private_data(self):
        self.assertEqual((self.root / "journal/private.txt").read_text(), "PRIVATE_TEST_ENTRY")
        self.assertEqual((self.root / "launchers.json").read_text(), "PRIVATE_VOICE_CONFIGURATION")

    def test_current_then_available_and_apply_pinned_main(self):
        self.assertEqual(self.updater.check()["state"], "current")
        revision = self.advance()
        self.assertEqual(self.updater.check(), {"state": "available", "revision": revision,
                                             "message": "An Abide update is available."})
        run = self.updater.run
        installed = []
        def execute(arguments, **options):
            if arguments[0] == "/usr/bin/python3" and arguments[1].endswith("/install.py"):
                verify_installation(self.root, arguments[-1])
                candidate = Path(arguments[1]).parent
                self.assertEqual(subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True).strip(), revision)
                installed.append(candidate)
                self.copy_installed(candidate)
                return "Installed"
            return run(arguments, **options)
        with patch.object(self.updater, "run", side_effect=execute):
            self.assertEqual(self.updater.apply(revision)["state"], "installed")
        self.assertEqual(len(installed), 1)
        self.assertFalse(installed[0].exists())
        self.assertEqual(self.updater.check()["state"], "current")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assert_private_data()

    def test_local_code_and_unpublished_builds_are_preserved(self):
        (self.root / "app.css").write_text("My unpublished change")
        with patch.object(self.updater, "fetch") as fetch:
            self.assertEqual(self.updater.check()["state"], "local")
            fetch.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "local code changes"):
                self.updater.apply()
        self.assertEqual((self.root / "app.css").read_text(), "My unpublished change")
        self.copy_installed(self.remote)
        data = json.loads((self.root / "release.json").read_text())
        data["local_changes"] = True
        (self.root / "release.json").write_text(json.dumps(data))
        self.assertEqual(self.updater.check()["state"], "local")
        self.assert_private_data()

    def test_remote_cannot_downgrade_an_installed_build(self):
        self.advance()
        self.copy_installed(self.remote)
        self.git("reset", "--hard", self.base_revision)
        self.assertEqual(self.updater.check()["state"], "local")
        with self.assertRaisesRegex(RuntimeError, "ahead of main"):
            self.updater.apply()
        self.assert_private_data()

    def test_squashed_publication_of_identical_code_can_update(self):
        self.advance()
        self.copy_installed(self.remote)
        tree = self.git("rev-parse", "HEAD^{tree}")
        squashed = self.git("commit-tree", tree, "-m", "Squashed publication")
        self.git("update-ref", "refs/heads/main", squashed)
        checked = self.updater.check()
        self.assertEqual(checked["state"], "available")
        self.assertEqual(checked["revision"], squashed)

    def test_main_changes_after_review_require_another_check(self):
        reviewed = self.advance()
        self.advance()
        with self.assertRaisesRegex(RuntimeError, "newer update appeared"):
            self.updater.apply(reviewed)
        self.assertEqual(json.loads((self.root / "release.json").read_text())["revision"], self.base_revision)

    def test_failed_release_checks_do_not_run_installer(self):
        (self.remote / "tests/test_panels.py").write_text("raise RuntimeError('Broken upstream release')\n")
        self.commit("Broken update")
        with patch.object(self.updater, "run", wraps=self.updater.run) as run:
            with self.assertRaisesRegex(RuntimeError, "Broken upstream release"):
                self.updater.apply()
        self.assertFalse(any(call.args[0][1].endswith("/install.py") for call in run.call_args_list))
        self.assertEqual(json.loads((self.root / "release.json").read_text())["revision"], self.base_revision)
        self.assert_private_data()

    def test_offline_check_leaves_installation_untouched(self):
        with patch.object(self.updater, "fetch", side_effect=RuntimeError("Offline")):
            with self.assertRaisesRegex(RuntimeError, "Offline"):
                self.updater.check()
        self.assertEqual(json.loads((self.root / "release.json").read_text())["revision"], self.base_revision)
        self.assert_private_data()

    def test_install_guard_preserves_changes_made_while_fetching(self):
        identity = install_identity(self.root)
        verify_installation(self.root, identity)
        (self.root / "app.css").write_text("Local edit during fetch")
        with self.assertRaisesRegex(RuntimeError, "local code changes"):
            verify_installation(self.root, identity)
        self.copy_installed(self.remote)
        data = json.loads((self.root / "release.json").read_text())
        data["revision"] = "1" * 40
        (self.root / "release.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "changed while"):
            verify_installation(self.root, identity)


if __name__ == "__main__":
    unittest.main()
