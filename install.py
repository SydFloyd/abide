#!/usr/bin/python3
"""Install Abide's dedicated panels and shortcuts, or restore the last install."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

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
             for name in ("app.py", "app.css", "quiet.py", "focus.py", "install.py")}
    for name, filename, extra in [
        ("abide-guide", "app.py", ""), ("abide", "app.py", ""),
        ("abide-quiet", "quiet.py", ""),
        ("abide-focus", "focus.py", ""),
        ("abide-panels-undo", "install.py", "sys.argv = [sys.argv[0], '--undo']\n"),
    ]:
        files[BIN / name] = wrapper(filename, extra).encode()
    applications = HOME / ".local/share/applications"
    for name, title, option in [
        ("abide-guide", "Abide", ""), ("abide-journal", "Abide Journal", " --journal"),
        ("abide-shortcuts", "Abide Shortcuts", " --shortcuts"),
    ]:
        files[applications / (name + ".desktop")] = desktop(title, option).encode()
    focus_executable = str(BIN / "abide-focus").replace("\\", "\\\\").replace('"', '\\"')
    files[HOME / ".config/autostart/abide-focus.desktop"] = (
        "[Desktop Entry]\nType=Application\nName=Abide window focus\n"
        + f'Exec="{focus_executable}"\n'
        + "OnlyShowIn=XFCE;\nTerminal=false\nStartupNotify=false\n"
        + "Comment=Focus newly opened application windows on the current workspace\n"
    ).encode()
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
    stop_focus()
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
    if snapshot.get("focus_listener") and (BIN / "abide-focus").exists():
        start_focus()


def stop_focus():
    helper = BIN / "abide-focus"
    if helper.exists():
        subprocess.run([str(helper), "--stop"], check=True, timeout=5)
        deadline = time.monotonic() + 5
        while focus_running():
            if time.monotonic() >= deadline:
                raise RuntimeError("The previous Abide focus helper did not stop.")
            time.sleep(0.02)


def focus_running():
    result = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                             "--object-path", "/org/freedesktop/DBus",
                             "--method", "org.freedesktop.DBus.NameHasOwner", "local.abide.Focus"],
                            capture_output=True, text=True, check=True, timeout=5)
    return result.stdout.strip() == "(true,)"


def start_focus():
    # The desktop session, rather than the installer process group, owns this
    # singleton. Redirect output so it never holds the installer's pipes open.
    process = subprocess.Popen([str(BIN / "abide-focus")], start_new_session=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 5
        while not focus_running():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Abide's focus helper did not start; installation will be restored.")
            time.sleep(0.02)
        subprocess.run([str(BIN / "abide-focus"), "--status"], check=True, timeout=5)
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        raise


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
    snapshot = {"shortcuts": shortcuts, "files": {}, "super_listener": LEGACY_AUTOSTART.exists(),
                "focus_listener": focus_running()}
    for path in tracked:
        relative = str(path.relative_to(HOME))
        snapshot["files"][relative] = path.exists()
        if path.exists():
            original = backup / "files" / relative
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, original)
    (backup / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    try:
        stop_focus()
        helper = BIN / "abide-super-key"
        if helper.exists():
            subprocess.run([str(helper), "--stop"], check=True, timeout=5)
        LEGACY_AUTOSTART.unlink(missing_ok=True)
        for path, data in files.items():
            replace_file(path, data, 0o755 if path.parent == BIN else 0o644)
        for key, value in KEYS.items():
            xfconf(key, value)
        start_focus()
    except Exception:
        restore(backup, snapshot)
        raise
    (backup / "applied").write_text("applied\n")
    pointer.write_text(str(backup) + "\n")
    print("Installed: Super+Space → Abide, Super+J → Journal, Super+K → Shortcuts, Super+Return → Terminal.")
    print("New application windows receive focus across the desktop; the focus helper starts at login.")
    print("Undo: ~/.local/bin/abide-panels-undo")


if __name__ == "__main__":
    main()
