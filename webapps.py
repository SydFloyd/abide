#!/usr/bin/python3
"""Launch or focus small Chromium app windows, with persistent private profiles."""
import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


@dataclass(frozen=True)
class WebApp:
    identifier: str
    name: str
    url: str
    icon: str
    shortcut: str
    accelerator: str

    @property
    def window_class(self):
        return "abide-webapp-" + self.identifier

    def command(self, bin_directory):
        return [str(bin_directory / "abide-webapp"), self.identifier]


WEB_APPS = (
    WebApp("x", "X", "https://x.com/", "applications-internet-symbolic", "Super + Shift + X", "<Shift><Super>x"),
    WebApp("gmail", "Gmail", "https://mail.google.com/", "mail-unread-symbolic", "Super + Shift + E", "<Shift><Super>e"),
)
WEB_APP_CLASSES = frozenset(app.window_class for app in WEB_APPS)


def remove_frame(window):
    """Remove the window manager's frame from Abide web apps only."""
    if (window.get_class_group_name() or "").casefold() not in WEB_APP_CLASSES:
        return False
    import gi
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkX11", "3.0")
    gi.require_version("Wnck", "3.0")
    from gi.repository import Gdk, GdkX11, Wnck

    if window.get_window_type() != Wnck.WindowType.NORMAL:
        return False
    display = Gdk.Display.get_default()
    # The browser can close between libwnck's notification and this request.
    display.error_trap_push()
    try:
        foreign = GdkX11.X11Window.foreign_new_for_display(display, window.get_xid())
        if foreign is not None:
            defined, decorations = foreign.get_decorations()
            if not defined or decorations != Gdk.WMDecoration(0):
                foreign.set_decorations(Gdk.WMDecoration(0))
                display.flush()
        return foreign is not None
    finally:
        display.error_trap_pop_ignored()


def browser_command(app, home=None):
    browser = shutil.which("chromium") or shutil.which("chromium-browser")
    if browser is None:
        raise RuntimeError("Install Chromium to use X and Gmail app windows: sudo apt install chromium chromium-sandbox")
    profiles = (home or Path.home()) / ".local/share/abide/webapps"
    profiles.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile = profiles / app.identifier
    profile.mkdir(exist_ok=True, mode=0o700)
    return [browser, "--app=" + app.url, "--class=" + app.window_class,
            "--user-data-dir=" + str(profile), "--no-first-run", "--no-default-browser-check"]


def focus_existing(app):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkX11", "3.0")
    gi.require_version("Wnck", "3.0")
    from gi.repository import Gtk, Gdk, GdkX11, Wnck

    if not Gtk.init_check([])[0] or not isinstance(Gdk.Display.get_default(), GdkX11.X11Display):
        raise RuntimeError("Open web apps from your Xfce X11 desktop.")
    screen = Wnck.Screen.get_default()
    screen.force_update()
    for window in screen.get_windows():
        if (window.get_class_group_name() or "").casefold() != app.window_class:
            continue
        remove_frame(window)
        root = Gdk.get_default_root_window()
        root.set_events(root.get_events() | Gdk.EventMask.PROPERTY_CHANGE_MASK)
        timestamp = GdkX11.x11_get_server_time(root)
        workspace = window.get_workspace()
        if workspace is not None and workspace != screen.get_active_workspace():
            workspace.activate(timestamp)
        if window.is_minimized():
            window.unminimize(timestamp)
        window.activate(timestamp)
        Gdk.Display.get_default().flush()
        return True
    return False


def desktop_entry(app, bin_directory):
    executable = str(bin_directory / "abide-webapp").replace("\\", "\\\\")
    for character in ('"', "`", "$"):
        executable = executable.replace(character, "\\" + character)
    executable = executable.replace("\\", "\\\\").replace("%", "%%")
    return ("[Desktop Entry]\nType=Application\n" + f"Name={app.name}\n"
            + f'Exec="{executable}" {app.identifier}\nIcon={app.icon}\n'
            + f"StartupWMClass={app.window_class}\nTerminal=false\nStartupNotify=false\n"
            + "Categories=Network;\n" + f"Keywords=abide;webapp;{app.identifier};\n"
            + f"Comment=Open {app.name} in its own web app window\n")


def show_error(message):
    print("Abide web apps: " + message, file=sys.stderr)
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    if Gtk.init_check([])[0]:
        dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.CLOSE, text="Could not open the web app")
        dialog.format_secondary_text(message)
        dialog.set_decorated(False)
        dialog.set_keep_above(True)
        dialog.run()
        dialog.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=str.casefold, choices=[app.identifier for app in WEB_APPS])
    args = parser.parse_args()
    app = next(app for app in WEB_APPS if app.identifier == args.app)
    try:
        if os.geteuid() == 0:
            raise RuntimeError("Open web apps as your desktop user, without sudo.")
        if not focus_existing(app):
            command = browser_command(app)
            os.execv(command[0], command)
        return 0
    except (OSError, RuntimeError) as error:
        show_error(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
