"""The shortcuts Abide installs and describes, shared by setup and the UI."""
from pathlib import Path
from webapps import WEB_APPS
from availability import command_available, executable

WORKSPACES = ((1, "exclam"), (2, "at"), (3, "numbersign"), (4, "dollar"), (5, "percent"))

# Each entry is (description, display text, Xfce accelerators, command).
# Paths to Abide itself are filled in by command_bindings().
APPLICATIONS = [
    ("Abide menu", "Super + Space", ("<Super>space",), ("abide-guide", "--toggle")),
    ("Journal", "Super + J", ("<Super>j",), ("abide-guide", "--journal")),
    ("Shortcuts", "Super + K", ("<Super>k",), ("abide-guide", "--shortcuts")),
    ("Terminal", "Super + Return", ("<Super>Return",), ("abide-guide", "--terminal")),
    ("Browser", "Super + Shift + Return / Super + B", ("<Shift><Super>Return", "<Super>b"), ("exo-open", "--launch", "WebBrowser")),
    ("Files", "Super + Shift + F / Super + E", ("<Shift><Super>f", "<Super>e"), ("thunar",)),
    ("Mousepad", "Super + M", ("<Super>m",), ("mousepad",)),
    ("Find an app", "Alt + F3", ("<Alt>F3",), ("xfce4-appfinder",)),
    ("Run a command", "Super + R", ("<Super>r",), ("xfce4-appfinder", "--collapsed")),
    ("Lock", "Super + Ctrl + L / Super + L", ("<Primary><Super>l", "<Super>l"), ("xflock4",)),
    ("System monitor", "Super + Ctrl + T", ("<Primary><Super>t",), ("xfce4-taskmanager",)),
    ("Screenshot", "Print", ("Print",), ("xfce4-screenshooter", "-f")),
    ("Select a screenshot area", "Shift + Print", ("<Shift>Print",), ("xfce4-screenshooter", "-r")),
    ("Screenshot this window", "Alt + Print", ("<Alt>Print",), ("xfce4-screenshooter", "-w")),
]
APPLICATIONS += [(app.name, app.shortcut, (app.accelerator,), ("abide-webapp", app.identifier))
                 for app in WEB_APPS]
WINDOWS = [
    ("Close window", "Super + W", "<Super>w", "close_window_key"),
    ("Fullscreen", "Super + F", "<Super>f", "fullscreen_key"),
    ("Tile left", "Super + ←", "<Super>Left", "tile_left_key"),
    ("Tile right", "Super + →", "<Super>Right", "tile_right_key"),
    ("Maximize / restore", "Super + ↑", "<Super>Up", "maximize_window_key"),
    ("Show the background", "Super + D", "<Super>d", "show_desktop_key"),
    ("Switch windows", "Alt + Tab", "<Alt>Tab", "cycle_windows_key"),
    ("Previous window", "Alt + Shift + Tab", "<Alt><Shift>Tab", "cycle_reverse_windows_key"),
]
for number, symbol in WORKSPACES:
    WINDOWS += [
        (f"Workspace {number}", f"Super + {number}", f"<Super>{number}", f"workspace_{number}_key"),
        (f"Move to workspace {number}", f"Super + Shift + {number}", f"<Shift><Super>{symbol}", f"move_window_workspace_{number}_key"),
    ]
REMOVED_COMMANDS = ("<Super>q", "<Super>slash", "<Super>t")

# Xfce's settings daemon continues to own hotkeys when bspwm owns windows.
TILING = [
    ("Close window", "Super + W", "<Super>w", ("close",)),
    ("Fullscreen", "Super + F", "<Super>f", ("fullscreen",)),
    ("Float / tile window", "Super + T", "<Super>t", ("float",)),
    ("Maximize / restore workspace", "Super + Alt + F", "<Alt><Super>f", ("monocle",)),
    ("Rotate window split", "Super + Shift + J", "<Shift><Super>j", ("rotate",)),
    ("Balance window sizes", "Super + Shift + B", "<Shift><Super>b", ("balance",)),
    ("Switch windows", "Alt + Tab", "<Alt>Tab", ("cycle", "next")),
    ("Previous window", "Alt + Shift + Tab", "<Alt><Shift>Tab", ("cycle", "prev")),
]
for direction, key, symbol in (("west", "Left", "←"), ("east", "Right", "→"),
                               ("north", "Up", "↑"), ("south", "Down", "↓")):
    TILING += [
        (f"Focus {direction}", f"Super + {symbol}", f"<Super>{key}", ("focus", direction)),
        (f"Swap {direction}", f"Super + Shift + {symbol}", f"<Shift><Super>{key}", ("swap", direction)),
        (f"Resize {direction}", f"Super + Ctrl + {symbol}", f"<Primary><Super>{key}", ("resize", direction)),
    ]
for number, symbol in WORKSPACES:
    TILING += [
        (f"Workspace {number}", f"Super + {number}", f"<Super>{number}", ("workspace", str(number))),
        (f"Move to workspace {number}", f"Super + Shift + {number}", f"<Shift><Super>{symbol}", ("send", str(number))),
    ]


def tiling_bindings(bin_directory):
    import shlex
    return {key: shlex.join([str(bin_directory / "abide-wm"), *arguments])
            for _title, _label, key, arguments in TILING}


def command_bindings(bin_directory):
    import shlex
    result = {key: None for key in REMOVED_COMMANDS}
    for _title, _label, keys, arguments in APPLICATIONS:
        command = list(arguments)
        if command[0] in ("abide-guide", "abide-webapp"):
            command[0] = str(bin_directory / command[0])
        elif (found := executable(command[0])) and Path(found).parent == Path.home() / ".local/bin":
            command[0] = found
        for key in keys:
            result[key] = shlex.join(command) if command_available(command) else None
    return result


def shortcut_rows(launchers, tiling=False, workspace_count=5):
    # Integrations may replace an application's displayed label, or add new
    # rows, while the built-in desktop controls remain available.
    custom = [(title, keys) for title, keys, _icon, command in launchers if keys and command_available(command)]
    titles = {title for title, _keys in custom}
    windows = TILING if tiling else WINDOWS
    if not all(executable(command) for command in (("bspwm", "bspc") if tiling else ("xfwm4",))):
        windows = []
    windows = [row for row in windows if not row[0].startswith(("Workspace ", "Move to workspace "))
               or int(row[0].split()[-1]) <= workspace_count]
    return ([(title, keys) for title, keys, _accels, _command in APPLICATIONS[:3] if title not in titles]
            + custom + [(title, keys) for title, keys, _accels, command in APPLICATIONS[3:]
                        if title not in titles and command_available(command)]
            + [(title, keys) for title, keys, _accel, _action in windows]
            + ([("Move window with mouse", "Super + left drag"),
                ("Resize window with mouse", "Super + right drag")] if tiling and windows else [])
            + [("Search shortcuts", "Ctrl + F"), ("Close Abide panel", "Esc")])
