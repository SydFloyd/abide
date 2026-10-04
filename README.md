# Abide

Three small GTK overlays for an Xfce desktop: a searchable control menu, a local
journal, and searchable keyboard shortcuts. All are borderless, stay above other
windows, and close when focus moves to another window or workspace. Journal
edits save before closing; if saving fails, the journal remains open to protect
those edits. Written in Python 3 with GTK 3 / PyGObject, using Debian's packages.

| Shortcut | Panel or action |
| --- | --- |
| Super + Space | Abide app menu |
| Super + J | Journal |
| Super + K | Shortcuts |
| Super + Return | New preferred terminal |
| Super + Shift + Return | Browser (Super + B also works) |
| Super + Shift + F | Files (Super + E also works) |
| Super + Shift + X | X web app |
| Super + Shift + E | Gmail web app |
| Super + Ctrl + T | System monitor |
| Super + Ctrl + L | Lock (Super + L also works) |
| Super + F | Fullscreen |
| Super + W | Close active window |
| Esc | Close the current panel |
| Ctrl + F | Focus search in the shortcuts panel |

The menu fits its visible rows and uses larger text; longer submenus expand as
needed, and results scroll when they exceed the screen. It has a search field
and keyboard navigation: Up/Down selects a row,
Enter opens it, and Esc returns from a submenu or closes the menu. Search from
the main menu also finds actions inside Settings, Capture, and Session. Apps
opens Xfce's application finder; Abide has no individual app launcher buttons.
The old quiet-mode control and Super+Q binding are removed; use Xfce's native
Do Not Disturb control in the notification panel.

The panels are separate windows, with no titlebars, window controls, or footer
tips. Shortcuts has a simple search field, a scrollable list, and generous rows
with the keys beside each action. Search accepts action names, key names, and aliases such as Windows or
Enter. The journal shows just its title, date, and entry box. Clicking the date
opens a calendar for revisiting entries. Save errors appear only when needed;
failed saves preserve the open entry. Opening a terminal with Super+Return
explicitly focuses its new window, including when Xfce Terminal reuses an existing server.

One resident Python/GTK process keeps the menu and shortcut controls ready,
and reuses hidden windows when a panel closes. Hotkeys send a small D-Bus
request, so reopening a panel avoids starting Python and GTK again. The service
starts at Xfce login and can also start on demand. The journal loads only when
requested and rereads its saved entry when reopened. Search and menu navigation
reset when reopening a panel; going back within the menu keeps the parent selection.
The launcher retains a standalone fallback if the service cannot be reached.

A small background helper also focuses newly opened application windows across
the desktop. This covers existing shortcuts, including custom terminal commands,
without changing their commands. Reused application servers sometimes supply an
old focus timestamp; the helper requests focus with the current X server time.
It activates each new window once, so switching away afterwards keeps your focus.
It leaves existing windows alone when starting and ignores desktop panels,
menus, splash screens, notifications, minimized windows, and other workspaces.
New background application windows can interrupt typing with this policy.

## Install

Use an **Xfce X11 session on Debian 12 or 13**. Choose Xfce at the login screen;
Abide's desktop shortcuts and focus policy depend on its window manager.
From a terminal as your normal desktop user:

```sh
sudo apt install git
git clone https://github.com/SydFloyd/abide.git
cd abide
./setup.sh
```

Setup installs any missing Debian dependencies using sudo, then installs Abide
under your user's `~/.local`. Abide itself runs without root, pip, a virtual
environment, or a package build. If dependencies are already present, run
`/usr/bin/python3 install.py` directly. `abide --doctor` checks the desktop and
dependencies without changing anything.

The installer adds application entries and login startup for the panel service
and focus helper. Browser, file, editor, lock, capture, tiling, and workspace
shortcuts work on a fresh machine; the UI and installer share their definitions.
It preserves workspace names and voice shortcuts. Xfce permits one binding per
window action, so displaced bindings are backed up along with the installed
files. Super+W replaces Alt+F4; Super+F replaces Alt+F11. Super+/, Super+T,
Super+Q, and the old standalone Super listener are retired.

Screen recording is optional. Install it with `sudo apt install simplescreenrecorder`;
the Capture menu already includes it. Missing optional applications show a
message while leaving the menu usable.

X and Gmail run in borderless Chromium app windows, without tabs, an address
bar, or title-bar controls. Use `./setup.sh --webapps` to include Chromium, or
install it later with `sudo apt install chromium chromium-sandbox`. Firefox
remains your normal browser. Find X and Gmail under Apps or search for them in
Abide; Super+Shift+X opens X and Super+Shift+E opens Gmail, following Omarchy's
X/email bindings.
Repeating a shortcut focuses the existing app window, including on another
workspace, rather than opening another copy. Super+W closes it normally.

Run `abide-webapp x` or `abide-webapp gmail` from a terminal. Each app has its own
private, persistent browser profile under `~/.local/share/abide/webapps`; sign in
once in each app. Abide's updates and undo preserve these profiles. Web apps are
ordinary desktop windows, so they stay open when you switch to another window.

Run `abide`, `abide --journal`, or `abide --shortcuts` directly. `--reflect` is
also accepted for existing launchers. Close any already-running old Abide window
before installing an update. The installer stops the resident service normally,
saving journal edits first, and restarts it after the update.

To restore the files and keyboard bindings from the latest installation:

```sh
~/.local/bin/abide-panels-undo
```

Backups stay in `~/.local/state/abide/panel-installs`. Undo retains journal entries
and any local launcher configuration. Concurrent installations are rejected;
failed service startup restores the previous files, bindings, and service state.

The focus helper starts immediately on installation and at future Xfce logins.
Run `~/.local/bin/abide-focus --stop` to stop it for the current session. Undo also
stops it and restores the previous startup entry and helper files. It also stops
the panel service and restores its previous state.

For local code edits, stop the resident service before opening a panel again:

```sh
gapplication action local.abide.Panels stop
```

The next panel request starts it again through D-Bus.

## Updates

Open **Super+Space → Settings → Check for updates**. Abide checks the official
repository's `main` branch; click **Install update** when one is available.
The same operations work from a terminal:

```sh
abide --check-updates
abide --update
```

Updates fetch into a separate cache, validate the selected revision, run its
checks, and use the same backed-up installer. Your original checkout is untouched
and can be deleted after installing. Journals, custom launchers, voice services,
and voice bindings are not update targets. Installation saves any open journal
first and aborts if it cannot save. Undo restores the previous installation.

There are no scheduled network checks or unattended installations. Local code
edits, unpublished builds, and builds ahead of main are protected from replacement.
Publish a development build to main, or install a clean main checkout, to enable
ordinary updates.

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
This file supplies shortcut labels; it does not register extra global
shortcuts. Keep private commands in that local file. The repository excludes
journals, local launcher settings, logs, caches, screenshots, and backups.
Abide rereads the file when Shortcuts opens, so voice integration changes do not
require a restart. Invalid configuration falls back to the default shortcuts
and displays a recoverable error instead of stopping the panels.

Existing `scripture.json` files are preserved for users of earlier versions,
although the journal no longer displays Scripture excerpts.

## Checks

```sh
/usr/bin/python3 -m unittest discover -s tests -v
sudo apt install xvfb xauth xfwm4 desktop-file-utils libxtst6
tests/run_desktop.sh
```

Desktop checks use their own X server, D-Bus session, and temporary home with
spaces in its path. They exercise real keyboard shortcuts, fresh installation,
main updates, service activation, voice preservation, journal save failures,
and undo without opening windows on your desktop. GitHub Actions runs the same
checks on Debian 12 and 13; see [.github/workflows/debian.yml](.github/workflows/debian.yml).

The desktop integration and explicit terminal focus handoff target Xfce on X11.
Wayland needs compositor-specific shortcut and activation support.

## License

MIT for the application code. GTK, PyGObject, and libwnck retain their respective
upstream licenses.
