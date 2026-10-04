#!/bin/sh
# Install distro packages as root; install Abide as the desktop user.
set -eu
if [ "$(id -u)" -eq 0 ]; then
  echo 'Run ./setup.sh as your desktop user, without sudo.' >&2
  exit 1
fi
if [ ! -f /etc/debian_version ]; then
  echo 'This setup script requires Debian or a Debian-based distribution.' >&2
  exit 1
fi
if [ -z "${DISPLAY:-}" ] || [ "${XDG_SESSION_TYPE:-x11}" = wayland ]; then
  echo 'Log into an Xfce X11 desktop, then run ./setup.sh there.' >&2
  exit 1
fi
case ":$(printf '%s' "${XDG_CURRENT_DESKTOP:-}" | tr '[:upper:]' '[:lower:]'):" in
  *:xfce:*) ;;
  *) echo 'Choose the Xfce desktop at login before running ./setup.sh.' >&2; exit 1 ;;
esac
setup_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
packages='python3 python3-gi gir1.2-gtk-3.0 gir1.2-wnck-3.0 libglib2.0-bin xfconf exo-utils xfce4-terminal xfce4-settings xfce4-session xfce4-appfinder xfce4-taskmanager xfce4-screenshooter thunar mousepad git'
if [ "${1:-}" = --webapps ]; then
  packages="$packages chromium chromium-sandbox"
  shift
fi
missing=''
for package in $packages; do
  if [ "$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)" != installed ]; then
    missing="$missing $package"
  fi
done
if [ -n "$missing" ]; then
  echo 'Installing missing Debian dependencies (sudo may ask for your password).'
  sudo apt-get update
  # The package names are fixed above, rather than supplied by user input.
  sudo apt-get install -y $missing
fi
exec /usr/bin/python3 "$setup_directory/install.py" "$@"
