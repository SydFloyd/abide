"""Read local integrations without allowing a bad file to break the desktop."""
import json


def load_launchers(path, defaults):
    try:
        with path.open("rb") as source:
            raw = source.read(262145)
    except FileNotFoundError:
        return defaults, None
    except OSError:
        return defaults, "Could not read custom shortcuts. Default shortcuts are available."
    try:
        if len(raw) > 262144:
            raise ValueError("Configuration is too large")
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError("Expected a list")
        for row in rows:
            if not isinstance(row, list) or len(row) != 4:
                raise ValueError("Expected four fields per shortcut")
            title, keys, icon, command = row
            if not all(isinstance(value, str) and "\0" not in value for value in (title, keys, icon)) or not title.strip():
                raise ValueError("Expected shortcut labels")
            if not isinstance(command, list) or not command or not command[0]:
                raise ValueError("Expected a command")
            if not all(isinstance(argument, str) and "\0" not in argument for argument in command):
                raise ValueError("Expected command arguments")
        return rows, None
    except (ValueError, UnicodeError):
        return defaults, "Custom shortcuts need attention. Default shortcuts are available."
