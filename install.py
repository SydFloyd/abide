#!/usr/bin/python3
"""Install Abide's dedicated panels and shortcuts, or restore the last install."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from bindings import REMOVED_COMMANDS, WINDOWS, command_bindings
from release import CODE_FILES, maintenance_lock, manifest, verify_installation
from webapps import WEB_APPS, desktop_entry
import window_manager

HOME = Path.home()
SOURCE = Path(__file__).resolve().parent
ROOT = HOME / ".local/share/abide"
STATE = HOME / ".local/state/abide"
BIN = HOME / ".local/bin"
CHANNEL = "xfce4-keyboard-shortcuts"
KEYS = command_bindings(BIN)
WINDOW_KEYS = {key: action for _title, _label, key, action in WINDOWS}
WINDOW_KEYS.update({"<Alt>F4": None, "<Alt>F11": None})
LEGACY_AUTOSTART = HOME / ".config/autostart/abide-super-key.desktop"


def xfconf(key, value=..., section="commands"):
    command = ["xfconf-query", "-c", CHANNEL, "-p", "/" + section + "/custom/" + key]
    if value is not ...:
        if value is None:
            if xfconf(key, section=section) is None:
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
            + "root = Path.home() / '.local/share/abide'\nsys.path.insert(0, str(root))\n"
            + f"runpy.run_path(str(root / '{filename}'), run_name='__main__')\n")


def desktop(name, option=""):
    executable = str(BIN / "abide-guide").replace("\\", "\\\\").replace('"', '\\"')
    return ("[Desktop Entry]\nType=Application\n" + f"Name={name}\n"
            + f'Exec="{executable}"{option}\nIcon=input-keyboard-symbolic\n'
            + "Terminal=false\nStartupNotify=false\nCategories=Utility;\n"
            + "Keywords=abide;keyboard;shortcuts;journal;prayer;\n")


def targets():
    files = {ROOT / name: (SOURCE / name).read_bytes()
             for name in CODE_FILES}
    files[ROOT / "release.json"] = (json.dumps(manifest(SOURCE), indent=2) + "\n").encode()
    for name, filename, extra in [
        ("abide-panels", "app.py", "sys.argv = [sys.argv[0], '--service']\n"),
        ("abide-focus", "focus.py", ""),
        ("abide-update", "updater.py", ""),
        ("abide-webapp", "webapps.py", ""),
        ("abide-wm", "window_manager.py", ""),
        ("abide-addins", "addins.py", ""),
        ("abide-doctor", "install.py", "sys.argv = [sys.argv[0], '--check']\n"),
        ("abide-panels-undo", "install.py", "sys.argv = [sys.argv[0], '--undo']\n"),
    ]:
        files[BIN / name] = wrapper(filename, extra).encode()
    for name in ("abide-guide", "abide"):
        files[BIN / name] = (SOURCE / "launcher.sh").read_bytes()
    applications = HOME / ".local/share/applications"
    for name, title, option in [
        ("abide-guide", "Abide", ""), ("abide-journal", "Abide Journal", " --journal"),
        ("abide-shortcuts", "Abide Shortcuts", " --shortcuts"),
    ]:
        files[applications / (name + ".desktop")] = desktop(title, option).encode()
    for app in WEB_APPS:
        files[applications / ("abide-webapp-" + app.identifier + ".desktop")] = desktop_entry(app, BIN).encode()
    focus_executable = str(BIN / "abide-focus").replace("\\", "\\\\").replace('"', '\\"')
    files[HOME / ".config/autostart/abide-focus.desktop"] = (
        "[Desktop Entry]\nType=Application\nName=Abide window focus\n"
        + f'Exec="{focus_executable}"\n'
        + "OnlyShowIn=XFCE;\nTerminal=false\nStartupNotify=false\n"
        + "Comment=Focus newly opened application windows on the current workspace\n"
    ).encode()
    panels_executable = str(BIN / "abide-panels").replace("\\", "\\\\").replace('"', '\\"')
    files[HOME / ".config/autostart/abide-panels.desktop"] = (
        "[Desktop Entry]\nType=Application\nName=Abide panels\n"
        + f'Exec="{panels_executable}"\n'
        + "OnlyShowIn=XFCE;\nTerminal=false\nStartupNotify=false\n"
        + "Comment=Keep Abide ready for immediate keyboard access\n"
    ).encode()
    files[HOME / ".local/share/dbus-1/services/local.abide.Panels.service"] = (
        "[D-BUS Service]\nName=local.abide.Panels\n" + f'Exec="{panels_executable}"\n'
    ).encode()
    wm_executable = str(BIN / "abide-wm").replace("\\", "\\\\").replace('"', '\\"')
    files[HOME / ".config/autostart/abide-wm.desktop"] = (
        "[Desktop Entry]\nType=Application\nName=Abide window management\n"
        + f'Exec="{wm_executable}" --autostart\n'
        + "OnlyShowIn=XFCE;\nTerminal=false\nStartupNotify=false\n"
        + "Comment=Restore automatic tiling when enabled\n"
    ).encode()
    update_executable = str(BIN / "abide-update").replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    units = HOME / ".config/systemd/user"
    files[units / "abide-update.service"] = (
        "[Unit]\nDescription=Check for stable Abide releases\n\n"
        + '[Service]\nType=oneshot\n' + f'ExecStart="{update_executable}" --background\n'
        + "TimeoutStartSec=90\n"
    ).encode()
    files[units / "abide-update.timer"] = (
        "[Unit]\nDescription=Check Abide updates at login and every six hours\n\n"
        + "[Timer]\nOnStartupSec=2min\nOnCalendar=*-*-* 00,06,12,18:00:00\n"
        + "RandomizedDelaySec=5min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
    ).encode()
    return files


def update_timer_state():
    if os.environ.get("ABIDE_ISOLATED_DESKTOP") == "1" or HOME != Path.home() or shutil.which("systemctl") is None:
        return None
    try:
        if subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, timeout=5).returncode:
            return None
        return {name: subprocess.run(["systemctl", "--user", "is-" + name, "abide-update.timer"],
                                     capture_output=True, timeout=5).returncode == 0
                for name in ("enabled", "active")}
    except (OSError, subprocess.SubprocessError):
        return None


def configure_update_timer(previous=None):
    if previous is None:
        return
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True, timeout=5)
    if previous.get("restore"):
        for action in ("enable" if previous["enabled"] else "disable", "start" if previous["active"] else "stop"):
            subprocess.run(["systemctl", "--user", action, "abide-update.timer"],
                           check=previous["enabled"] or previous["active"], capture_output=True, timeout=5)
    else:
        subprocess.run(["systemctl", "--user", "enable", "--now", "abide-update.timer"],
                       check=True, capture_output=True, timeout=5)


def legacy_files():
    return [HOME / ".local/bin/abide-quiet", HOME / ".local/share/abide/quiet.py"]


def refresh_shortcuts():
    # Only application keys are refreshed; window and voice keys retain their
    # current owners, including bspwm's Super+T binding.
    for key, value in command_bindings(BIN).items():
        if key not in REMOVED_COMMANDS and xfconf(key) != value:
            xfconf(key, value)
    for app in WEB_APPS:
        replace_file(HOME / ".local/share/applications" / ("abide-webapp-" + app.identifier + ".desktop"),
                     desktop_entry(app, BIN).encode())


def replace_file(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".abide-install-tmp")
    temporary.write_bytes(data)
    temporary.chmod(mode)
    temporary.replace(path)


def restore(backup, snapshot):
    stop_panels()
    stop_focus()
    if snapshot.get("update_timer") is not None:
        subprocess.run(["systemctl", "--user", "disable", "--now", "abide-update.timer"],
                       capture_output=True, timeout=5)
    if "tiling_enabled" in snapshot and not snapshot["tiling_enabled"] and (STATE / "window-manager.json").exists():
        window_manager.disable()
    for key, value in snapshot["shortcuts"].items():
        xfconf(key, value)
    # Clear the managed keys before restoring old ones: xfwm allows only one
    # key per action, and assigning an old key can otherwise erase a new key.
    for key in snapshot.get("window_shortcuts", {}):
        xfconf(key, None, section="xfwm4")
    for key, value in snapshot.get("window_shortcuts", {}).items():
        if value is not None:
            xfconf(key, value, section="xfwm4")
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
    if snapshot.get("panels_running"):
        start_panels()
    if snapshot.get("tiling_enabled"):
        window_manager.enable()
    if snapshot.get("update_timer") is not None:
        configure_update_timer({**snapshot["update_timer"], "restore": True})


def stop_focus():
    helper = BIN / "abide-focus"
    if helper.exists():
        subprocess.run([str(helper), "--stop"], check=True, timeout=5)
        deadline = time.monotonic() + 5
        while focus_running():
            if time.monotonic() >= deadline:
                raise RuntimeError("The previous Abide focus helper did not stop.")
            time.sleep(0.02)


def service_running(name):
    result = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                             "--object-path", "/org/freedesktop/DBus",
                             "--method", "org.freedesktop.DBus.NameHasOwner", name],
                            capture_output=True, text=True, check=True, timeout=5)
    return result.stdout.strip() == "(true,)"


def focus_running():
    return service_running("local.abide.Focus")


def panels_running():
    return service_running("local.abide.Panels")


def stop_panels():
    if not panels_running():
        return
    subprocess.run(["gdbus", "call", "--session", "--dest", "local.abide.Panels",
                    "--object-path", "/local/abide/Panels", "--method", "org.gtk.Actions.Activate",
                    "stop", "[]", "{}"], check=True, capture_output=True, timeout=5)
    deadline = time.monotonic() + 5
    while panels_running():
        if time.monotonic() >= deadline:
            raise RuntimeError("Abide could not stop; check for an unsaved journal entry.")
        time.sleep(0.02)


def start_panels():
    process = subprocess.Popen([str(BIN / "abide-panels")], start_new_session=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 5
        while not panels_running():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Abide's panel service did not start; installation will be restored.")
            time.sleep(0.02)
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        raise


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


def window_bindings():
    result = dict(WINDOW_KEYS)
    listing = subprocess.run(["xfconf-query", "-c", CHANNEL, "-lv"], capture_output=True,
                             text=True, check=True, timeout=5).stdout
    actions = {action for action in result.values() if action}
    prefix = "/xfwm4/custom/"
    for line in listing.splitlines():
        pieces = line.split(None, 1)
        if len(pieces) == 2 and pieces[0].startswith(prefix):
            key = pieces[0][len(prefix):]
            if pieces[1].strip() in actions and key not in result:
                result[key] = None
    return result


def check_environment():
    errors = []
    if os.geteuid() == 0:
        errors.append("Run Abide setup as your desktop user, without sudo.")
    for command, package in (("gdbus", "libglib2.0-bin"), ("gapplication", "libglib2.0-bin"),
                             ("xfconf-query", "xfconf"), ("exo-open", "exo-utils"),
                             ("git", "git")):
        if shutil.which(command) is None:
            errors.append(f"Missing {command}; install the Debian package {package}.")
    if not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        errors.append("Log into an Xfce X11 desktop, then run setup there.")
    else:
        probe = '''import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gtk, Gdk, GdkX11, Wnck
if not Gtk.init_check([])[0] or not isinstance(Gdk.Display.get_default(), GdkX11.X11Display):
    raise SystemExit("Cannot connect to an X11 display.")
if Gdk.Screen.get_default().get_window_manager_name().casefold() not in ("xfwm4", "bspwm"):
    raise SystemExit("Abide requires Xfce with xfwm4 or bspwm.")
'''
        try:
            result = subprocess.run(["/usr/bin/python3", "-c", probe], capture_output=True, text=True, timeout=5)
            if result.returncode:
                detail = (result.stderr or result.stdout or "The desktop probe did not finish.").strip().splitlines()[-1]
                errors.append("Xfce/GTK check failed. Run ./setup.sh to install dependencies, in an Xfce X11 session.\n"
                              + detail)
        except subprocess.SubprocessError:
            errors.append("The desktop did not respond to the Xfce/GTK check.")
    if not errors:
        try:
            service_running("org.freedesktop.DBus")
        except (OSError, subprocess.SubprocessError):
            errors.append("Cannot connect to the desktop D-Bus session. Run setup from a desktop terminal.")
    return errors


def install(undo=False, tiling=False):
    pointer = STATE / "latest-panels-install"
    if undo:
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
    windows = window_bindings()
    window_shortcuts = {key: xfconf(key, section="xfwm4") for key in windows}
    backup = STATE / "panel-installs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, mode=0o700)
    tracked = list(files) + [LEGACY_AUTOSTART, STATE / "window-manager.json"] + legacy_files()
    snapshot = {"shortcuts": shortcuts, "files": {}, "super_listener": LEGACY_AUTOSTART.exists(),
                "focus_listener": focus_running(), "window_shortcuts": window_shortcuts,
                "panels_running": panels_running(),
                "tiling_enabled": (STATE / "window-manager.json").exists()}
    snapshot["update_timer"] = update_timer_state()
    for path in tracked:
        relative = str(path.relative_to(HOME))
        snapshot["files"][relative] = path.exists()
        if path.exists():
            original = backup / "files" / relative
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, original)
    (backup / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    # A failed journal save aborts before changing any installed file or key.
    stop_panels()
    try:
        stop_focus()
        helper = BIN / "abide-super-key"
        if helper.exists():
            subprocess.run([str(helper), "--stop"], check=True, timeout=5)
        LEGACY_AUTOSTART.unlink(missing_ok=True)
        for path in legacy_files():
            path.unlink(missing_ok=True)
        for path, data in files.items():
            replace_file(path, data, 0o755 if path.parent == BIN or path.name == "bspwmrc" else 0o644)
        for key, value in KEYS.items():
            xfconf(key, value)
        for key, value in windows.items():
            if value is None:
                xfconf(key, None, section="xfwm4")
        for key, value in windows.items():
            if value is not None:
                xfconf(key, value, section="xfwm4")
        start_focus()
        start_panels()
        if tiling or snapshot["tiling_enabled"]:
            window_manager.enable()
        configure_update_timer(snapshot["update_timer"])
    except Exception:
        restore(backup, snapshot)
        raise
    (backup / "applied").write_text("applied\n")
    pointer.write_text(str(backup) + "\n")
    print("Installed: Super+Space → Abide, Super+J → Journal, Super+K → Shortcuts, Super+Return → Terminal.")
    print("New application windows receive focus across the desktop; the focus helper starts at login.")
    print("One resident process keeps Abide panels ready; it starts at login and on demand.")
    if tiling or snapshot["tiling_enabled"]:
        print("Tiling: Super+arrows focus, Shift swaps, Ctrl resizes; Super+T floats; Super+drag moves windows.")
    print("Undo: ~/.local/bin/abide-panels-undo")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--undo", action="store_true", help="restore the last installation")
    parser.add_argument("--check", action="store_true", help="check requirements without changing anything")
    parser.add_argument("--tiling", action="store_true", help="enable automatic tiling with bspwm")
    parser.add_argument("--refresh-shortcuts", action="store_true", help="refresh shortcuts for installed tools")
    parser.add_argument("--expected-install", help=argparse.SUPPRESS)
    args = parser.parse_args()
    errors = check_environment()
    if errors:
        raise RuntimeError("\n".join(errors))
    if args.tiling and not args.undo:
        missing = [command for command in ("bspwm", "bspc", "xfwm4", "xprop") if window_manager.executable(command) is None]
        if missing:
            raise RuntimeError("Missing tiling dependencies: " + ", ".join(missing) + ". Run ./setup.sh --tiling.")
    if args.check:
        print("Abide is ready: Python/GTK, Xfce X11, desktop D-Bus, and update tools are available.")
        if shutil.which("simplescreenrecorder") is None:
            print("Optional screen recorder: sudo apt install simplescreenrecorder")
        return
    with maintenance_lock(STATE):
        if args.expected_install:
            verify_installation(ROOT, args.expected_install)
        if args.refresh_shortcuts:
            refresh_shortcuts()
        else:
            install(args.undo, tiling=args.tiling)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("Abide: " + str(error), file=sys.stderr)
        raise SystemExit(1)
