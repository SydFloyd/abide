#!/usr/bin/python3
"""A reversible Xfce integration for bspwm; bspwm owns all tiling and input."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from bindings import WORKSPACES, tiling_bindings
from release import maintenance_lock

HOME = Path.home()
ROOT = HOME / ".local/share/abide"
STATE = HOME / ".local/state/abide"
PROFILE = STATE / "window-manager.json"
BIN = HOME / ".local/bin"
KEYBOARD = "xfce4-keyboard-shortcuts"
SESSION_KEY = "/sessions/Failsafe/Client0_Command"


def executable(name):
    found = shutil.which(name)
    if found is None and name in ("bspwm", "bspc"):
        local = BIN / name
        if local.is_file() and os.access(local, os.X_OK):
            found = str(local)
    return found


def run(*arguments, check=True):
    arguments = (executable(arguments[0]) or arguments[0], *arguments[1:])
    result = subprocess.run(arguments, capture_output=True, text=True,
                            env={**os.environ, "LC_ALL": "C"}, timeout=5)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{' '.join(arguments)} failed.")
    return result


def property_value(channel, key, array=False):
    result = run("xfconf-query", "-c", channel, "-p", key, check=False)
    if result.returncode:
        if "does not exist" in result.stderr + result.stdout:
            return None
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    if array:
        lines = result.stdout.splitlines()
        return [line for line in lines[1:] if line] if lines[0].startswith("Value is an array") else [result.stdout.strip()]
    return result.stdout.strip()


def set_property(channel, key, value, kind="string", array=False):
    if value is None:
        if property_value(channel, key) is not None:
            run("xfconf-query", "-c", channel, "-p", key, "-r")
        return
    arguments = ["xfconf-query", "-c", channel, "-p", key, "-n"]
    if array:
        arguments.append("-a")
        for item in value:
            arguments += ["-t", kind, "-s", str(item)]
    else:
        arguments += ["-t", kind, "-s", str(value)]
    run(*arguments)


def profile():
    try:
        return json.loads(PROFILE.read_text())
    except FileNotFoundError:
        return None


def enabled():
    return PROFILE.is_file()


def save_profile(data):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = PROFILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(PROFILE)


def wm_name():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
    if not Gtk.init_check([])[0]:
        raise RuntimeError("Cannot connect to the X11 desktop.")
    # GDK refreshes this property through its event loop after a WM switch.
    from gi.repository import GLib
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)
    return Gdk.Screen.get_default().get_window_manager_name().casefold()


def wait_for_wm(name, process=None):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if wm_name() == name:
            return
        if process is not None and process.poll() is not None:
            break
        time.sleep(0.025)
    raise RuntimeError(f"The {name} window manager did not start; see {STATE / 'window-manager.log'}.")


def spawn(*arguments):
    arguments = (executable(arguments[0]) or arguments[0], *arguments[1:])
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "window-manager.log").open("ab") as log:
        return subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)


def snapshot():
    commands = tiling_bindings(BIN)
    saved = {"properties": [], "workspaces": [], "windows": [], "active_workspace": 0,
             "active_window": None}
    def remember(channel, key, value, kind="string", array=False):
        saved["properties"].append({"channel": channel, "key": key, "kind": kind,
                                    "array": array, "value": property_value(channel, key, array),
                                    "tiling": value})
    for key, command in commands.items():
        remember(KEYBOARD, "/commands/custom/" + key, command)
        remember(KEYBOARD, "/xfwm4/custom/" + key, None)
    remember("xfce4-session", SESSION_KEY, [str(BIN / "abide-wm"), "--session"], array=True)
    # Remove active-app tabs while retaining their definitions for restoration.
    panels = property_value("xfce4-panel", "/panels", array=True) or []
    for panel in panels:
        key = f"/panels/panel-{panel}/plugin-ids"
        ids = property_value("xfce4-panel", key, array=True) or []
        kept = [item for item in ids if property_value("xfce4-panel", f"/plugins/plugin-{item}") != "tasklist"]
        if kept != ids:
            remember("xfce4-panel", key, kept or None, kind="int", array=True)
    import gi
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
    screen = Wnck.Screen.get_default()
    screen.force_update()
    saved["workspaces"] = [workspace.get_name() for workspace in screen.get_workspaces()]
    workspace = screen.get_active_workspace()
    if workspace:
        saved["active_workspace"] = workspace.get_number()
    active = screen.get_active_window()
    if active is not None:
        saved["active_window"] = active.get_xid()
    saved["windows"] = [[window.get_xid(), window.get_workspace().get_number()]
                        for window in screen.get_windows() if window.get_workspace() is not None]
    return saved


def apply_properties(data, restore=False, commands=None):
    items = [item for item in data["properties"] if commands is None or
             (item["channel"] == KEYBOARD and item["key"].startswith("/commands/")) == commands]
    # Release grabs before transferring them between xfwm and xfsettingsd.
    # An unchanged value emits no notification and cannot retry a failed grab.
    for item in items:
        if item["channel"] == KEYBOARD and item["key"].startswith("/commands/"):
            set_property(item["channel"], item["key"], None)
    for item in items:
        set_property(item["channel"], item["key"], item["value" if restore else "tiling"],
                     item["kind"], item["array"])


def update_shortcuts(data):
    # Existing tiling profiles retain their original restore values while
    # upgrades add newly supported shortcuts to the running desktop.
    saved = {(item["channel"], item["key"]): item for item in data["properties"]}
    changed = False
    for key, command in tiling_bindings(BIN).items():
        for section, value in (("commands", command), ("xfwm4", None)):
            path = f"/{section}/custom/{key}"
            item = saved.get((KEYBOARD, path))
            if item is None:
                item = {"channel": KEYBOARD, "key": path, "kind": "string", "array": False,
                        "value": property_value(KEYBOARD, path), "tiling": value}
                data["properties"].append(item)
                changed = True
            elif item["tiling"] != value:
                item["tiling"] = value
                changed = True
    if changed:
        save_profile(data)


def configure():
    data = profile()
    if data is None:
        raise RuntimeError("Tiling has not been enabled.")
    settings = {
        "split_ratio": "0.61803398875", "automatic_scheme": "longest_side",
        "initial_polarity": "second_child", "window_gap": "10", "border_width": "2",
        "normal_border_color": "#383c4a", "active_border_color": "#686f7d",
        "focused_border_color": "#a5b68d", "presel_feedback_color": "#a5b68d",
        "pointer_modifier": "mod4", "pointer_action1": "move", "pointer_action3": "resize_corner",
        "focus_follows_pointer": "false", "pointer_follows_focus": "true",
        "honor_size_hints": "false", "remove_unplugged_monitors": "true",
        "remove_disabled_monitors": "true", "merge_overlapping_monitors": "true",
    }
    for key, value in settings.items():
        # Debian's bspwm returns failure when this setting is already equal.
        if key == "focus_follows_pointer" and run("bspc", "config", key).stdout.strip() == value:
            continue
        run("bspc", "config", key, value)
    monitors = run("bspc", "query", "-M", "--names").stdout.splitlines()
    for index, monitor in enumerate(monitors):
        desktops = run("bspc", "query", "-D", "-m", monitor, "--names").stdout.splitlines()
        if desktops == ["Desktop"]:
            names = data["workspaces"] or ["1", "2", "3"]
            if index:
                names = [f"{monitor}-{number}" for number in range(1, 4)]
            run("bspc", "monitor", monitor, "-d", *names)
    for pattern, consequences in {
        "AbidePanel": ("state=floating", "layer=above", "center=on", "border=off"),
        "Xfce4-appfinder": ("state=floating", "center=on"),
        "Xfce4-taskmanager": ("state=floating", "center=on"),
        "Pavucontrol": ("state=floating", "center=on"),
        "Pinentry": ("state=floating", "center=on"),
    }.items():
        run("bspc", "rule", "-r", pattern, check=False)
        run("bspc", "rule", "-a", pattern, *consequences)
    # bspwm normally ignores pre-existing windows; adopting keeps apps alive.
    run("bspc", "wm", "--adopt-orphans")


def start():
    name = wm_name()
    if name == "bspwm":
        configure()
        return
    if name != "xfwm4":
        raise RuntimeError("Enable tiling from an Xfce desktop using xfwm4.")
    supporting = run("xprop", "-root", "_NET_SUPPORTING_WM_CHECK").stdout
    match = re.search(r"0x[0-9a-fA-F]+", supporting)
    if not match:
        raise RuntimeError("Cannot identify the current window manager.")
    pid_text = run("xprop", "-id", match[0], "_NET_WM_PID").stdout
    match = re.search(r"=\s*(\d+)", pid_text)
    if not match:
        raise RuntimeError("The current window manager did not publish its process ID.")
    os.kill(int(match[1]), signal.SIGTERM)
    # Only stop the WM, never its client applications or the desktop session.
    deadline = time.monotonic() + 3
    while wm_name() == "xfwm4" and time.monotonic() < deadline:
        time.sleep(0.025)
    process = spawn("bspwm", "-c", str(ROOT / "bspwmrc"))
    try:
        wait_for_wm("bspwm", process)
        configure()
        data = profile()
        for xid, workspace in data["windows"]:
            run("bspc", "node", hex(xid), "-d", f"^{workspace + 1}", check=False)
        run("bspc", "desktop", "-f", f"^{data['active_workspace'] + 1}")
        if data.get("active_window"):
            run("bspc", "node", "-f", hex(data["active_window"]), check=False)
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        raise


def enable():
    for command in ("bspwm", "bspc", "xfwm4", "xprop"):
        if executable(command) is None:
            raise RuntimeError("Install the tiling dependencies with ./setup.sh --tiling.")
    data = profile()
    fresh = data is None
    if fresh:
        if wm_name() != "xfwm4":
            raise RuntimeError("Enable tiling from an Xfce desktop using xfwm4.")
        data = snapshot()
        save_profile(data)
    try:
        update_shortcuts(data)
        apply_properties(data, commands=False)
        start()
        apply_properties(data, commands=True)
    except Exception:
        if fresh:
            disable()
        raise


def disable():
    data = profile()
    if data is None:
        return
    apply_properties(data, restore=True)
    PROFILE.unlink()
    name = wm_name()
    if name != "xfwm4":
        if name == "bspwm":
            run("bspc", "quit", check=False)
        process = spawn("xfwm4", "--replace")
        wait_for_wm("xfwm4", process)


def action(name, argument=None):
    commands = {
        "close": ("node", "-c"), "fullscreen": ("node", "-t", "~fullscreen"),
        "float": ("node", "-t", "~floating"), "monocle": ("desktop", "-l", "next"),
        "rotate": ("node", "@parent", "-R", "90"), "balance": ("node", "@/", "-B"),
    }
    if name in commands:
        return run("bspc", *commands[name], check=False).returncode
    if name in ("focus", "swap", "resize"):
        if argument not in ("west", "east", "north", "south"):
            raise ValueError("Unknown direction")
        if name == "resize":
            edge, x, y = {"west": ("left", -40, 0), "east": ("right", 40, 0),
                          "north": ("top", 0, -40), "south": ("bottom", 0, 40)}[argument]
            result = run("bspc", "node", "-z", edge, str(x), str(y), check=False)
            if result.returncode:
                opposite = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[edge]
                result = run("bspc", "node", "-z", opposite, str(x), str(y), check=False)
            return result.returncode
        return run("bspc", "node", "-f" if name == "focus" else "-s", argument + ".local.!hidden.window", check=False).returncode
    if name == "cycle" and argument in ("next", "prev"):
        return run("bspc", "node", "-f", argument + ".local.!hidden.window", check=False).returncode
    if name in ("workspace", "send") and argument in {str(number) for number, _symbol in WORKSPACES}:
        if name == "workspace":
            return run("bspc", "desktop", "-f", "^" + argument, check=False).returncode
        return run("bspc", "node", "-d", "^" + argument, "--follow", check=False).returncode
    raise ValueError("Unknown window action")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    for name in ("enable", "disable", "status", "configure", "session", "autostart"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--gui", action="store_true", help="show errors in a desktop dialog")
    parser.add_argument("action", nargs="?")
    parser.add_argument("argument", nargs="?")
    args = parser.parse_args()
    if args.status:
        print("Tiling enabled (bspwm)." if enabled() else "Xfce window management (xfwm4).")
    elif args.configure:
        configure()
    elif args.session:
        binary = executable("bspwm")
        if enabled() and binary is not None:
            os.execv(binary, [binary, "-c", str(ROOT / "bspwmrc")])
        os.execvp("xfwm4", ["xfwm4"])
    elif args.action:
        return action(args.action, args.argument)
    elif args.autostart and not enabled():
        return 0
    else:
        with maintenance_lock(STATE):
            if args.disable:
                disable()
            elif args.enable or args.autostart:
                enable()
            else:
                parser.print_help()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Abide windows: " + str(error), file=sys.stderr)
        if "--gui" in sys.argv:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            Gtk.init([])
            dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR,
                                       buttons=Gtk.ButtonsType.CLOSE,
                                       text="Window management could not change")
            dialog.format_secondary_text(str(error))
            dialog.run()
            dialog.destroy()
        raise SystemExit(1)
