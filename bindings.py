"""The shortcuts Abide installs and describes, shared by setup and the UI."""
from webapps import WEB_APPS

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
for number, symbol in ((1, "exclam"), (2, "at"), (3, "numbersign")):
    WINDOWS += [
        (f"Workspace {number}", f"Super + {number}", f"<Super>{number}", f"workspace_{number}_key"),
        (f"Move to workspace {number}", f"Super + Shift + {number}", f"<Shift><Super>{symbol}", f"move_window_workspace_{number}_key"),
    ]
REMOVED_COMMANDS = ("<Super>q", "<Super>slash", "<Super>t")


def command_bindings(bin_directory):
    import shlex
    result = {key: None for key in REMOVED_COMMANDS}
    for _title, _label, keys, arguments in APPLICATIONS:
        command = list(arguments)
        if command[0] in ("abide-guide", "abide-webapp"):
            command[0] = str(bin_directory / command[0])
        for key in keys:
            result[key] = shlex.join(command)
    return result


def shortcut_rows(launchers):
    # Integrations may replace an application's displayed label, or add new
    # rows, while the built-in desktop controls remain available.
    custom = [(title, keys) for title, keys, _icon, _command in launchers if keys]
    titles = {title for title, _keys in custom}
    return ([(title, keys) for title, keys, _accels, _command in APPLICATIONS[:3] if title not in titles]
            + custom + [(title, keys) for title, keys, _accels, _command in APPLICATIONS[3:] if title not in titles]
            + [(title, keys) for title, keys, _accel, _action in WINDOWS]
            + [("Search shortcuts", "Ctrl + F"), ("Close Abide panel", "Esc")])
