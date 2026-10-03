# Abide

Three small GTK panels for an Xfce desktop: an app launcher, a local prayer
journal, and searchable keyboard shortcuts. Each panel closes when focus moves
to another window or workspace. Journal edits save before closing; if saving
fails, the journal remains open to protect those edits.

| Shortcut | Panel or action |
| --- | --- |
| Super + Space | Abide app menu |
| Super + J | Journal |
| Super + K | Shortcuts |
| Super + Return | New preferred terminal |
| Esc | Close the current panel |
| Ctrl + F | Focus search in the shortcuts panel |

The panels are separate windows, with no shared tab bar. Shortcuts has a simple
search field, a scrollable list, and generous rows with the keys beside each
action. Search accepts action names, key names, and aliases such as Windows or
Enter. Opening a terminal from the menu explicitly focuses its new window,
including when Xfce Terminal reuses an existing server.

A small background helper also focuses newly opened application windows across
the desktop. This covers existing shortcuts, including custom terminal commands,
without changing their commands. Reused application servers sometimes supply an
old focus timestamp; the helper requests focus with the current X server time.
It activates each new window once, so switching away afterwards keeps your focus.
It leaves existing windows alone when starting and ignores desktop panels,
menus, splash screens, notifications, minimized windows, and other workspaces.
New background application windows can interrupt typing with this policy.

## Install

Requires Python 3, GTK 3 / PyGObject, libwnck 3, Xfce, and an X11 session. On Debian:

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-wnck-3.0 libglib2.0-bin xfconf exo-utils xfce4-terminal
python3 install.py
```

The installer writes under `~/.local`, adds application entries for the three
panels, adds the focus helper to Xfce login startup, and updates only the listed
keyboard bindings. Super+Space replaces
Xfce's app finder shortcut; app finder remains available from the menu and
Alt+F3. The old Super+/ and Super+T bindings are removed. The old standalone
Super listener, if installed, is stopped and removed from login startup.

Run `abide`, `abide --journal`, or `abide --shortcuts` directly. `--reflect` is
also accepted for existing launchers. Close any already-running old Abide window
before installing an update.

To restore the files and keyboard bindings from the latest installation:

```sh
~/.local/bin/abide-panels-undo
```

Backups stay in `~/.local/state/abide/panel-installs`. Undo retains journal entries
and any local launcher configuration.

The focus helper starts immediately on installation and at future Xfce logins.
Run `~/.local/bin/abide-focus --stop` to stop it for the current session. Undo also
stops it and restores the previous startup entry and helper files.

## Local data and customization

Voice is provided by a separately installed application.
Its engine and speech models are not bundled in Abide. From an installed voice
checkout, run `.venv/bin/python scripts/install_abide.py --autostart` to add local
launchers and enable the listener at Xfce login. Hold Super+V to talk, use
Super+Alt+V for Voice control, and Super+Ctrl+V for Voice diagnostics. Diagnostics
remain available when the engine cannot start. The integration preserves other
launchers and keeps installation-specific commands out of this repository.

Journal files stay in `~/.local/share/abide/journal/YYYY-MM-DD.txt`. The directory
uses mode 0700 and entries use mode 0600. Saving writes a temporary file, flushes
it, and replaces the entry atomically. Nothing uploads entries or connects to a
remote service.

Optional `~/.local/share/abide/launchers.json` contains an array of launcher rows:

```json
[
  ["Terminal", "Super + Return", "utilities-terminal-symbolic", ["exo-open", "--launch", "TerminalEmulator"]]
]
```

Each row holds its title, shortcut label, icon name, and command argument array.
This file changes menu entries and labels; it does not register extra global
shortcuts. Keep private commands in that local file. The repository excludes
journals, local launcher settings, logs, caches, screenshots, and backups.

Existing `scripture.json` is preserved during installation. Fresh installations
receive a short [World English Bible](https://ebible.org/eng-web/copr.htm)
public-domain excerpt. Add entries with `title`, `reference`, `text`, and
`translation` fields to customize the chooser.

## Checks

```sh
python3 -m unittest discover -s tests -v
ABIDE_GUI_TEST=1 dbus-run-session -- python3 -m unittest discover -s tests -v
```

GUI checks temporarily open verification windows and a terminal on the current
desktop. They use a temporary journal and close the test terminal afterwards.

The desktop integration and explicit terminal focus handoff target Xfce on X11.
Wayland needs compositor-specific shortcut and activation support.

## License

MIT for the application code. The bundled World English Bible excerpt is public
domain; the translation name is a trademark of eBible.org. GTK, PyGObject, and
libwnck retain their respective upstream licenses.
