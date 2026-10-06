# Abide

Three small GTK overlays for an Xfce desktop: a searchable control menu, a local
journal, and searchable keyboard shortcuts, with optional automatic window tiling.
All panels are borderless, stay above other
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
Abide supports Xfce's floating window manager and optional bspwm tiling.
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

Setup installs Abide's core only: Python/GTK, libwnck, Xfce integration, and update
tools. Open **Super+Space → Add-ins** to see the suggested software behind each
optional feature, its installation status, and an Install button. The catalog
includes Firefox ESR, bspwm tiling, Chromium web apps, screen capture, screen
recording, and desktop tools. Installation uses Debian's package manager and
the normal desktop authentication prompt. Installed tiling also has a button
to switch between floating and tiled windows. Existing software and local
integrations are retained.

For terminal setup, combine any of `--tiling`, `--webapps`, `--capture`,
`--recording`, and `--desktop-tools`. Without these flags, suggested tools remain
optional. For example, `./setup.sh --tiling --desktop-tools` adds tiling and the
terminal/file/editor/monitor tools. `abide-addins --list` reports their status.

The installer adds application entries and login startup for the panel service
and focus helper. Browser, file, editor, lock, capture, tiling, and workspace
shortcuts are shared by the UI and installer. Only available tools appear in
menus and the shortcut guide; missing applications have no active Abide hotkey.
This checks the actual backend, including Chromium for X/Gmail and the configured
preferred browser or terminal. Add-in installation refreshes hotkeys and app
entries immediately. Reopening Abide also refreshes shortcuts after software is
installed or removed outside the manager. Workspace shortcuts are listed only
for existing workspaces.
It preserves workspace names and voice shortcuts. Xfce permits one binding per
window action, so displaced bindings are backed up along with the installed
files. Super+W replaces Alt+F4; Super+F replaces Alt+F11. Super+/, Super+Q,
and the old standalone Super listener are retired. Super+T toggles floating
windows when automatic tiling is enabled.

## Window management

Run `./setup.sh --tiling` to install and enable bspwm. Add `--webapps` to also
install Chromium: `./setup.sh --tiling --webapps`. Existing installations can
enable tiling the same way; `install.py --tiling` works when dependencies are
already available. Ordinary installs and updates retain the current mode.

Omarchy uses Hyprland's dwindle layout on Wayland. Abide keeps Xfce/X11 and uses
[bspwm](https://github.com/baskerville/bspwm), an existing small window manager,
for a similar recursive layout. Each new window splits the focused tile along
its longest side at approximately 62/38, the golden ratio. A single window fills
the workspace; closing a window gives its space back to its sibling. bspwm
handles layout, monitor changes, focus, dragging, and resizing directly.

Windows have a thin border showing focus and no window-manager titlebar. Apps
with their own header controls retain those controls. Dialogs and Abide's
overlays float above the tiles. The Xfce panel keeps workspaces, clock, and tray,
and removes its active-app tabs. Existing applications stay open during the
switch, and workspace names and voice bindings are preserved.

| Shortcut | Action in tiling mode |
| --- | --- |
| Super + arrows | Focus neighboring window |
| Super + Shift + arrows | Swap neighboring windows |
| Super + Ctrl + arrows | Resize window |
| Super + left drag | Move or rearrange a window without a titlebar |
| Super + right drag | Resize a window without a titlebar |
| Super + T | Float / tile the focused window |
| Super + F | Fullscreen / restore |
| Super + Alt + F | Maximize workspace / restore tiles |
| Super + Shift + J | Rotate the current split |
| Super + Shift + B | Balance sizes in the workspace |
| Alt + Tab / Alt + Shift + Tab | Next / previous window in this workspace |
| Super + 1–5 | Switch workspace |
| Super + Shift + 1–5 | Move window to a workspace and follow it |
| Super + W | Close focused window |

Super+J still opens Journal and Super+K still opens Shortcuts. Shortcuts shows
the controls for the current mode. Switch modes from **Super+Space → Settings →
Windows** using the **Floating / Tiled** toggle, or run `abide-wm --toggle`.
The switch shows the current mode; turning it on selects tiled windows and
turning it off selects floating windows. `abide-wm --enable` / `abide-wm --disable`
still select a mode explicitly. Tiling starts at
future Xfce logins. Disabling it restores xfwm4, the previous keyboard bindings,
panel tabs, and session command. The installation's undo also restores the
previous window-management mode; a failed first switch restores the desktop.

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

Abide checks the official repository's published stable GitHub releases at login
and every six hours. A user systemd timer runs the checks; the resident panels
provide a fallback when a user timer is unavailable. Checks run off the UI
thread, cache their result, and leave a known update visible while offline.

When a release is available, **Super+Space** gains an **Update** item with a small
notification dot. It opens the update panel; click **Install update** to apply
the checked release. The row disappears after installation. **Settings → Check
for updates** remains available for a manual check, including connection errors
or local-build information.
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

Installation remains a user action. Local code edits, unpublished builds, and
builds ahead of the latest stable release are protected from replacement. Checks
compare numeric versions and pin the release's exact commit before validation
and installation. Install a clean published release to use stable updates.
Development users can explicitly check `abide-update --check --channel main`.

`VERSION` is the canonical release version. Maintainers update it, commit the
release, and push a matching tag such as `v0.1.0`. GitHub Actions runs the Debian
12 and 13 desktop checks before publishing that tag as a stable GitHub release
with generated notes. Drafts, prereleases, and untagged main commits do not
trigger the stable update notice. Until the first release is published, a clean
installation reports that no stable release is available.

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
sudo apt install xvfb xauth xfwm4 bspwm x11-utils desktop-file-utils libxtst6
tests/run_desktop.sh
```

Desktop checks use their own X server, D-Bus session, and temporary home with
spaces in its path. They exercise real keyboard shortcuts, fresh installation,
development and tagged-release updates, menu update dots, optional add-ins,
service activation, voice preservation, journal save failures,
and undo without opening windows on your desktop. Tiling checks also exercise
golden-ratio splits, real focus/swap/resize keys, titlebar-free mouse movement,
workspaces, floating overlays, updates, and restoration. GitHub Actions runs the same
checks on Debian 12 and 13; see [.github/workflows/debian.yml](.github/workflows/debian.yml).

The desktop integration and explicit terminal focus handoff target Xfce on X11.
Wayland needs compositor-specific shortcut and activation support.

## License

MIT for the application code. GTK, PyGObject, and libwnck retain their respective
upstream licenses.
