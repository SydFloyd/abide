"""Optional package selection, status, and the barebones installation contract."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from addins import ADDINS, available, find_addin, install_command

SOURCE = Path(__file__).resolve().parents[1]


class AddInTests(unittest.TestCase):
    def test_only_a_known_addin_can_request_package_installation(self):
        with patch("addins.shutil.which", return_value="/usr/bin/pkexec"):
            for addin in ADDINS:
                command = install_command(addin.identifier)
                self.assertEqual(command[:2], ["pkexec", "/usr/bin/apt-get"])
                self.assertEqual(command[-len(addin.packages):], list(addin.packages))
            for value in ("unknown", "bspwm; echo unsafe", "--remove"):
                with self.assertRaises(ValueError):
                    install_command(value)

    def test_status_detects_user_local_tools_and_missing_components(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("addins.Path.home", return_value=Path(folder)), \
                patch("addins.shutil.which", return_value=None):
            tiling = find_addin("tiling")
            self.assertFalse(available(tiling))
            binary = Path(folder) / ".local/bin"
            binary.mkdir(parents=True)
            for name in tiling.commands:
                (binary / name).write_text("#!/bin/sh\nexit 0\n")
                (binary / name).chmod(0o755)
            self.assertTrue(available(tiling))
            (binary / "bspc").unlink()
            self.assertFalse(available(tiling))

    def test_setup_keeps_addins_optional_and_combines_selected_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            shutil.copy2(SOURCE / "setup.sh", source / "setup.sh")
            (source / "install.py").write_text("import sys\nfrom pathlib import Path\nPath('arguments').write_text(' '.join(sys.argv[1:]))\n")
            tools = source / "tools"
            tools.mkdir()
            log = source / "packages"
            query = tools / "dpkg-query"
            query.write_text("#!/usr/bin/python3\nfrom pathlib import Path\nimport sys\n"
                             + f"with Path({str(log)!r}).open('a') as output: output.write(sys.argv[-1] + '\\n')\n"
                             + "print('installed')\n")
            query.chmod(0o755)
            env = {**os.environ, "PATH": str(tools) + ":" + os.environ["PATH"],
                   "DISPLAY": ":99", "XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "XFCE"}
            for flags in ([], ["--webapps", "--capture", "--tiling", "--recording", "--desktop-tools"]):
                subprocess.run([str(source / "setup.sh"), *flags, "--check"], cwd=source,
                               env=env, check=True, capture_output=True, timeout=10)
                packages = set(log.read_text().splitlines())
                for identifier in ("tiling", "webapps", "capture", "recording", "desktop-tools"):
                    for package in find_addin(identifier).packages:
                        self.assertEqual(package in packages, bool(flags), package)
                self.assertEqual((source / "arguments").read_text(), "--tiling --check" if flags else "--check")
                log.unlink()


if __name__ == "__main__":
    unittest.main()
