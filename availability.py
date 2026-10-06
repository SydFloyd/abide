"""Check launchers and their optional backends without launching applications."""
import configparser
import os
from pathlib import Path
import re
import shlex
import shutil


def executable(command):
    found = shutil.which(os.path.expanduser(command))
    if found is None and "/" not in command:
        local = Path.home() / ".local/bin" / command
        if local.is_file() and os.access(local, os.X_OK):
            found = str(local)
    return found


def data_directories():
    return [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")),
            *[Path(value) for value in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if value]]


def preferred_helper_available(category):
    directories = [Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")),
                   *[Path(value) for value in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":") if value]]
    helper = None
    for directory in directories:
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read_string("[Helpers]\n" + (directory / "xfce4/helpers.rc").read_text())
            helper = config.get("Helpers", category, fallback=None)
        except (OSError, UnicodeError, configparser.Error):
            continue
        if helper:
            break
    if not helper or not re.fullmatch(r"[A-Za-z0-9_-]+", helper):
        return False
    # The sensible-browser script exists even on desktops with no browser.
    if helper == "debian-sensible-browser":
        return bool(executable("x-www-browser") or executable("gnome-www-browser"))
    for directory in data_directories():
        path = directory / "xfce4/helpers" / (helper + ".desktop")
        if not path.is_file():
            continue
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read(path)
            entry = config["Desktop Entry"]
            binaries = entry.get("X-XFCE-Binaries", "").split(";")
            if any(binary and shutil.which(binary) for binary in binaries):
                return True
            # Custom helpers can specify an executable directly instead of %B.
            for command in entry.get("X-XFCE-Commands", "").split(";"):
                arguments = shlex.split(command)
                if arguments and "%" not in arguments[0] and shutil.which(arguments[0]):
                    return True
        except (OSError, UnicodeError, ValueError, KeyError, configparser.Error):
            pass
        return False
    return False


def command_available(arguments):
    if not arguments:
        return False
    name = Path(arguments[0]).name
    if name in ("abide-guide", "abide", "abide-panels"):
        return "--terminal" not in arguments or (
            bool(executable("exo-open")) and preferred_helper_available("TerminalEmulator"))
    if name in ("abide-update", "abide-addins"):
        return True
    if name == "abide-webapp":
        return bool(executable("chromium") or executable("chromium-browser"))
    if name == "abide-wm":
        from window_manager import enabled
        tiling = "--enable" in arguments or ("--toggle" in arguments and not enabled())
        dependencies = ("bspwm", "bspc", "xfwm4", "xprop") if tiling else ("xfwm4",)
        return all(executable(command) for command in dependencies)
    if not executable(arguments[0]):
        return False
    if name == "exo-open" and "--launch" in arguments:
        index = arguments.index("--launch") + 1
        return index < len(arguments) and preferred_helper_available(arguments[index])
    if name == "xflock4":
        return any(executable(command) for command in (
            "xfce4-screensaver-command", "light-locker-command", "xscreensaver-command",
            "gnome-screensaver-command", "mate-screensaver-command", "slock", "i3lock"))
    return True
