#!/usr/bin/python3
"""Focus newly opened application windows across an Xfce X11 desktop."""
import sys

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk, Wnck  # noqa: E402


class NewWindowFocus:
    def __init__(self, screen, root):
        self.screen = screen
        self.root = root
        self.pending = {}
        # Populate the initial window list before subscribing: starting this
        # service must not change focus to an already-open window.
        screen.force_update()
        self.handlers = [screen.connect("window-opened", self.on_opened),
                         screen.connect("window-closed", self.on_closed)]

    def eligible(self, window):
        kind = window.get_window_type()
        if kind not in (Wnck.WindowType.NORMAL, Wnck.WindowType.DIALOG, Wnck.WindowType.UTILITY):
            return False
        # Notifications and other background surfaces can appear as NORMAL to
        # libwnck. Dialogs may legitimately be absent from the task list.
        if kind == Wnck.WindowType.NORMAL and window.is_skip_tasklist():
            return False
        workspace = self.screen.get_active_workspace()
        return not window.is_minimized() and workspace is not None and window.is_visible_on_workspace(workspace)

    def on_opened(self, screen, window):
        xid = window.get_xid()
        if xid not in self.pending:
            # Allow the window manager to finish mapping and reading hints.
            self.pending[xid] = GLib.idle_add(self.focus_window, xid)

    def on_closed(self, screen, window):
        source = self.pending.pop(window.get_xid(), None)
        if source:
            GLib.source_remove(source)

    def focus_window(self, xid):
        self.pending.pop(xid, None)
        self.screen.force_update()
        # Resolve at dispatch time: a window may close before the idle runs.
        # Older libwnck releases also cannot safely retain closed windows.
        window = next((item for item in self.screen.get_windows() if item.get_xid() == xid), None)
        if window is None or not self.eligible(window):
            return False
        active = self.screen.get_active_window()
        if active is None or active.get_xid() != window.get_xid():
            # Reused app servers can inherit an old user time. Use the current
            # X server time rather than the new window's cached timestamp.
            window.activate(GdkX11.x11_get_server_time(self.root))
        return False

    def stop(self):
        for handler in self.handlers:
            self.screen.disconnect(handler)
        for source in self.pending.values():
            GLib.source_remove(source)
        self.pending.clear()


class FocusApplication(Gio.Application):
    def __init__(self):
        super().__init__(application_id="local.abide.Focus", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.watcher = None

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()
        if "--stop" in arguments:
            self.quit()
        elif "--status" in arguments:
            return 0 if self.watcher is not None else 1
        else:
            self.activate()
        return 0

    def do_activate(self):
        if self.watcher is not None:
            return
        Gtk.init([])
        display = Gdk.Display.get_default()
        if not isinstance(display, GdkX11.X11Display):
            raise RuntimeError("Abide window focus requires an X11 session.")
        root = Gdk.get_default_root_window()
        root.set_events(root.get_events() | Gdk.EventMask.PROPERTY_CHANGE_MASK)
        Wnck.set_client_type(Wnck.ClientType.PAGER)
        self.watcher = NewWindowFocus(Wnck.Screen.get_default(), root)
        self.hold()

    def do_shutdown(self):
        if self.watcher is not None:
            self.watcher.stop()
        Gio.Application.do_shutdown(self)


if __name__ == "__main__":
    sys.exit(FocusApplication().run(sys.argv))
