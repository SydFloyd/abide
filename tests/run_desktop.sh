#!/bin/sh
# Own the entire test desktop: HOME, X11 display, and D-Bus are disposable.
set -eu
test_script=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/run_desktop.sh
cd "$(dirname -- "$test_script")/.."
if [ "${1:-}" = --inside ]; then
  xfwm4 --compositor=off > "$HOME/xfwm-test.log" 2>&1 &
  wm_pid=$!
  trap 'kill "$wm_pid" 2>/dev/null || true' EXIT
  /usr/bin/python3 - <<'PY'
import time
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Gtk, Gdk, GLib
Gtk.init([])
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)
    if Gdk.Screen.get_default().get_window_manager_name().casefold() == 'xfwm4':
        break
    time.sleep(0.02)
else:
    raise SystemExit('The test window manager did not start.')
PY
  /usr/bin/python3 tests/desktop_fixture.py > "$HOME/desktop-test.log" 2>&1 &
  desktop_pid=$!
  xfsettingsd --no-daemon > "$HOME/settings-test.log" 2>&1 &
  settings_pid=$!
  trap 'kill "$settings_pid" "$desktop_pid" "$wm_pid" 2>/dev/null || true' EXIT
  attempts=0
  while [ ! -f "$HOME/desktop-ready" ]; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 50 ]; then
      cat "$HOME/desktop-test.log" >&2
      echo 'The test desktop did not start.' >&2
      exit 1
    fi
    sleep 0.1
  done
  ABIDE_GUI_TEST=1 /usr/bin/python3 -m unittest discover -s tests -v
  /usr/bin/python3 tests/install_smoke.py
  exit 0
fi
for command in xvfb-run xfwm4 xfsettingsd dbus-run-session desktop-file-validate; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo 'Install test dependencies: sudo apt install xvfb xauth xfwm4 desktop-file-utils libxtst6' >&2
    exit 1
  fi
done
test_profile=$(mktemp -d /tmp/abide-desktop-test.XXXXXX)
cleanup() {
  # Portal mounts can outlive the exiting session bus by a few moments.
  cleanup_attempts=0
  until rm -rf -- "$test_profile" 2>/dev/null; do
    cleanup_attempts=$((cleanup_attempts + 1))
    if [ "$cleanup_attempts" -ge 50 ]; then
      rm -rf -- "$test_profile"
      return
    fi
    sleep 0.1
  done
}
trap cleanup EXIT
mkdir -p "$test_profile/Father Desktop/run"
chmod 700 "$test_profile/Father Desktop/run"
unset DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER XAUTHORITY DESKTOP_STARTUP_ID XDG_ACTIVATION_TOKEN
export HOME="$test_profile/Father Desktop"
export XDG_DATA_HOME="$HOME/.local/share" XDG_CONFIG_HOME="$HOME/.config" XDG_CACHE_HOME="$HOME/.cache"
export XDG_RUNTIME_DIR="$HOME/run" XDG_CURRENT_DESKTOP=XFCE XDG_SESSION_TYPE=x11 GDK_BACKEND=x11
export ABIDE_ISOLATED_DESKTOP=1
xvfb-run -a -s '-screen 0 1280x800x24 -nolisten tcp' dbus-run-session -- "$test_script" --inside
