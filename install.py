#!/usr/bin/python3
"""Install Abide's dedicated panels and shortcuts, or restore the last install."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess

HOME = Path.home()
SOURCE = Path(__file__).resolve().parent
ROOT = HOME / ".local/share/abide"
STATE = HOME / ".local/state/abide"
BIN = HOME / ".local/bin"
CHANNEL = "xfce4-keyboard-shortcuts"
KEYS = {
    "<Super>space": str(BIN / "abide-guide") + " --toggle",
    "<Super>j": str(BIN / "abide-guide") + " --journal",
    "<Super>k": str(BIN / "abide-guide") + " --shortcuts",
    "<Super>Return": str(BIN / "abide-guide") + " --terminal",
    "<Super>slash": None,
    "<Super>t": None,
}
LEGACY_AUTOSTART = HOME / ".config/autostart/abide-super-key.desktop"


def xfconf(key, value=...):
    command = ["xfconf-query", "-c", CHANNEL, "-p", "/commands/custom/" + key]
    if value is not ...:
        if value is None:
            if xfconf(key) is None:
                return
            command += ["-r"]
        else:
            command += ["-n", "-t", "string", "-s", value]
    result = subprocess.run(command, capture_output=True, text=True,
                            env={**os.environ, "LC_ALL": "C"}, timeout=5)
    if result.returncode:
        if value is ... and "does not exist" in (result.stdout + result.stderr):
            return None
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def wrapper(filename, extra=""):
    return ("#!/usr/bin/python3\nimport runpy, sys\nfrom pathlib import Path\n" + extra
            + f"runpy.run_path(str(Path.home() / '.local/share/abide/{filename}'), run_name='__main__')\n")


def desktop(name, option=""):
    executable = str(BIN / "abide-guide").replace("\\", "\\\\").replace('"', '\\"')
    return ("[Desktop Entry]\nType=Application\n" + f"Name={name}\n"
            + f'Exec="{executable}"{option}\nIcon=input-keyboard-symbolic\n'
            + "Terminal=false\nStartupNotify=true\nCategories=Utility;\n"
            + "Keywords=abide;keyboard;shortcuts;journal;prayer;\n")


def targets():
    files = {ROOT / name: (SOURCE / name).read_bytes()
             for name in ("app.py", "app.css", "quiet.py", "install.py")}
    for name, filename, extra in [
        ("abide-guide", "app.py", ""), ("abide", "app.py", ""),
        ("abide-quiet", "quiet.py", ""),
        ("abide-panels-undo", "install.py", "sys.argv = [sys.argv[0], '--undo']\n"),
    ]:
        files[BIN / name] = wrapper(filename, extra).encode()
    applications = HOME / ".local/share/applications"
    for name, title, option in [
        ("abide-guide", "Abide", ""), ("abide-journal", "Abide Journal", " --journal"),
        ("abide-shortcuts", "Abide Shortcuts", " --shortcuts"),
    ]:
        files[applications / (name + ".desktop")] = desktop(title, option).encode()
    if not (ROOT / "scripture.json").exists():
        files[ROOT / "scripture.json"] = (SOURCE / "scripture.json").read_bytes()
    return files


def replace_file(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".abide-install-tmp")
    temporary.write_bytes(data)
    temporary.chmod(mode)
    temporary.replace(path)


def restore(backup, snapshot):
    for key, value in snapshot["shortcuts"].items():
        xfconf(key, value)
    for name, existed in snapshot["files"].items():
        destination = HOME / name
        if existed:
            original = backup / "files" / name
            replace_file(destination, original.read_bytes(), original.stat().st_mode & 0o777)
        else:
            destination.unlink(missing_ok=True)
    if snapshot.get("super_listener") and (BIN / "abide-super-key").exists():
        subprocess.run([str(BIN / "abide-super-key"), "--start"], check=True, timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--undo", action="store_true")
    args = parser.parse_args()
    pointer = STATE / "latest-panels-install"
    if args.undo:
        if not pointer.exists():
            print("No panel installation to undo.")
            return
        backup = Path(pointer.read_text().strip())
        if not (backup / "applied").exists():
            print("This panel installation is already undone.")
            return
        restore(backup, json.loads((backup / "snapshot.json").read_text()))
        (backup / "applied").unlink()
        print("Restored the previous Abide panels and shortcuts. Journal entries are retained.")
        return
    files = targets()
    shortcuts = {key: xfconf(key) for key in KEYS}
    backup = STATE / "panel-installs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, mode=0o700)
    tracked = list(files) + [LEGACY_AUTOSTART]
    snapshot = {"shortcuts": shortcuts, "files": {}, "super_listener": LEGACY_AUTOSTART.exists()}
    for path in tracked:
        relative = str(path.relative_to(HOME))
        snapshot["files"][relative] = path.exists()
        if path.exists():
            original = backup / "files" / relative
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, original)
    (backup / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    try:
        helper = BIN / "abide-super-key"
        if helper.exists():
            subprocess.run([str(helper), "--stop"], check=True, timeout=5)
        LEGACY_AUTOSTART.unlink(missing_ok=True)
        for path, data in files.items():
            replace_file(path, data, 0o755 if path.parent == BIN else 0o644)
        for key, value in KEYS.items():
            xfconf(key, value)
    except Exception:
        restore(backup, snapshot)
        raise
    (backup / "applied").write_text("applied\n")
    pointer.write_text(str(backup) + "\n")
    print("Installed: Super+Space → Abide, Super+J → Journal, Super+K → Shortcuts, Super+Return → Terminal.")
    print("Undo: ~/.local/bin/abide-panels-undo")


if __name__ == "__main__":
    main()
