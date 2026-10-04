#!/usr/bin/python3
"""Three dedicated Xfce panels: apps, a local journal, and searchable shortcuts."""
from datetime import date, timedelta
from pathlib import Path
import os
import shutil
import sys
import time

from bindings import shortcut_rows
from config import load_launchers
from webapps import WEB_APPS

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk, Wnck  # noqa: E402

ROOT = Path.home() / ".local/share/abide"
JOURNAL = ROOT / "journal"
SOURCE = Path(__file__).resolve().parent
# Keep this literal for external integrations that discover the config format.
# Built-in shortcuts live in bindings.py; this list is only for extensions.
DEFAULT_LAUNCHERS = []
MENUS = {
    "Abide": [
        ("Apps", "view-app-grid-symbolic", ["xfce4-appfinder"]),
        ("Settings", "preferences-system-symbolic", "Settings"),
        ("Capture", "camera-photo-symbolic", "Capture"),
        ("Journal", "accessories-text-editor-symbolic", [str(Path.home() / ".local/bin/abide-guide"), "--journal"]),
        ("Shortcuts", "input-keyboard-symbolic", [str(Path.home() / ".local/bin/abide-guide"), "--shortcuts"]),
        ("Session", "system-log-out-symbolic", "Session"),
    ],
    "Settings": [
        ("All settings", "preferences-system-symbolic", ["xfce4-settings-manager"]),
        ("Display", "video-display-symbolic", ["xfce4-display-settings"]),
        ("Appearance", "preferences-desktop-theme-symbolic", ["xfce4-appearance-settings"]),
        ("Notifications", "preferences-system-notifications-symbolic", ["xfce4-notifyd-config"]),
        ("Keyboard", "input-keyboard-symbolic", ["xfce4-keyboard-settings"]),
        ("Mouse", "input-mouse-symbolic", ["xfce4-mouse-settings"]),
        ("Check for updates", "software-update-available-symbolic", [str(Path.home() / ".local/bin/abide-update"), "--gui"]),
    ],
    "Capture": [
        ("Screenshot", "camera-photo-symbolic", ["xfce4-screenshooter"]),
        ("Screenshot area", "edit-select-all-symbolic", ["xfce4-screenshooter", "-r"]),
        ("Screenshot window", "window-symbolic", ["xfce4-screenshooter", "-w"]),
        ("Record screen", "media-record-symbolic", ["simplescreenrecorder"]),
    ],
    "Session": [
        ("Lock", "system-lock-screen-symbolic", ["xflock4"]),
        ("Log out / power", "system-log-out-symbolic", ["xfce4-session-logout"]),
    ],
}


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.get_style_context().add_class(style)
    return widget


def new_terminal(screen, existing):
    screen.force_update()
    return next((window for window in screen.get_windows()
                 if window.get_xid() not in existing
                 and "terminal" in (window.get_class_group_name() or "").casefold()), None)


def open_terminal():
    """Open and focus a preferred terminal without showing an Abide panel."""
    Gtk.init([])
    screen = Wnck.Screen.get_default()
    screen.force_update()
    existing = {window.get_xid() for window in screen.get_windows()}
    root = Gdk.get_default_root_window()
    root.set_events(root.get_events() | Gdk.EventMask.PROPERTY_CHANGE_MASK)
    timestamp = GdkX11.x11_get_server_time(root)
    context = root.get_display().get_app_launch_context()
    context.set_timestamp(timestamp)
    app = Gio.AppInfo.create_from_commandline("exo-open --launch TerminalEmulator", "Terminal",
                                             Gio.AppInfoCreateFlags.SUPPORTS_STARTUP_NOTIFICATION)
    app.launch([], context)
    loop = GLib.MainLoop()
    deadline = time.monotonic() + 5
    focused = False
    def poll():
        nonlocal focused
        candidate = new_terminal(screen, existing)
        if candidate:
            active = screen.get_active_window()
            if active and active.get_xid() == candidate.get_xid():
                focused = True
                loop.quit()
                return False
            candidate.activate(timestamp)
        if time.monotonic() < deadline:
            return True
        loop.quit()
        return False
    GLib.timeout_add(50, poll)
    loop.run()
    return 0 if focused else 1


class Panel:
    def __init__(self, panel, application, reuse_windows=True):
        if panel not in ("menu", "journal", "shortcuts"):
            raise ValueError("Unknown Abide panel: " + panel)
        self.application = application
        self.panel = panel
        self.reuse_windows = reuse_windows
        self.cached_window = None
        self.day = date.today()
        self.dirty = False
        self.save_timer = 0
        self.syncing_date = False
        self.blur_timer = 0
        self.launch_timer = 0
        self.focus_seen = False
        self.launchers = DEFAULT_LAUNCHERS
        self.config_error = None

    def activate(self):
        self.do_activate()

    def get_active_window(self):
        return self.cached_window

    def get_windows(self):
        return [self.cached_window] if self.cached_window else []

    def do_activate(self):
        window = self.cached_window or self.get_active_window()
        reopening = window is not None and not window.get_visible()
        if window is None:
            window = self.build_window()
        elif self.panel == "shortcuts":
            self.reload_shortcuts()
        if self.reuse_windows and reopening:
            self.status.hide()
            if self.panel == "menu":
                rebuild = self.menu_route != "Abide" or bool(self.menu_search.get_text())
                self.menu_route = "Abide"
                self.menu_selections.clear()
                self.menu_search.set_text("")
                if rebuild:
                    self.refresh_menu()
                self.menu_list.select_row(self.menu_list.get_row_at_index(0))
            elif self.panel == "shortcuts":
                self.shortcut_search.set_text("")
                self.shortcut_scroll.get_vadjustment().set_value(0)
            else:
                previous_day = self.day
                self.day = date.today()
                if not self.load_day():
                    self.day = previous_day
        self.present_window(window)
        if self.config_error:
            self.show_error(self.config_error)

    def build_window(self):
        window = Gtk.ApplicationWindow(application=self.application, title={
            "menu": "Abide", "journal": "Abide Journal", "shortcuts": "Abide Shortcuts"}[self.panel])
        window.get_style_context().add_class("abide-guide")
        window.get_style_context().add_class("abide-" + self.panel)
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        window.set_position(Gtk.WindowPosition.CENTER)
        window.set_default_size(*{"menu": (-1, -1), "shortcuts": (820, 600),
                                  "journal": (700, 460)}[self.panel])
        window.connect("key-press-event", self.on_key)
        window.connect("delete-event", self.on_close)
        window.connect("destroy", self.on_destroy)
        self.focus_seen = False
        window.connect("notify::is-active", self.on_active)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_border_width(12 if self.panel == "menu" else 18)
        window.add(body)
        css = SOURCE / "app.css"
        if css.exists() and not getattr(self.application, "abide_css", None):
            provider = Gtk.CssProvider()
            provider.load_from_path(str(css))
            Gtk.StyleContext.add_provider_for_screen(window.get_screen(), provider,
                                                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.application.abide_css = provider
        self.page = {"menu": self.open_page, "journal": self.reflect_page,
                     "shortcuts": self.shortcuts_page}[self.panel]()
        body.pack_start(self.page, True, True, 0)
        # Errors are visible when something needs attention; no permanent tips.
        self.status = label("", "abide-error")
        self.status.set_line_wrap(True)
        self.status.set_no_show_all(True)
        body.pack_end(self.status, False, False, 0)
        if self.panel == "journal":
            self.load_day()
        self.cached_window = window
        return window

    def present_window(self, window):
        self.focus_seen = False
        window.show_all()
        root = Gdk.get_default_root_window()
        root.set_events(root.get_events() | Gdk.EventMask.PROPERTY_CHANGE_MASK)
        window.present_with_time(GdkX11.x11_get_server_time(root))
        if self.panel == "shortcuts":
            self.shortcut_search.grab_focus()
        elif self.panel == "journal":
            self.editor.grab_focus()
        else:
            self.menu_search.grab_focus()

    def show_error(self, message):
        self.status.set_text(message)
        self.status.show()

    def launch(self, button, command):
        window = button.get_toplevel()
        if shutil.which(command[0]) is None:
            self.show_error(f"{button.get_tooltip_text()} is not installed. Install {command[0]} to use it.")
            return
        terminal = command[0] == "xfce4-terminal" or (
            command[0] == "exo-open" and "TerminalEmulator" in command)
        screen = Wnck.Screen.get_default() if terminal else None
        if screen:
            screen.force_update()
        existing = {item.get_xid() for item in screen.get_windows()} if screen else set()
        try:
            # Give the destination the click's activation timestamp, including
            # apps that send the request to an already-running process.
            context = window.get_display().get_app_launch_context()
            context.set_screen(window.get_screen())
            timestamp = Gtk.get_current_event_time()
            if timestamp == Gdk.CURRENT_TIME and isinstance(window.get_window(), GdkX11.X11Window):
                timestamp = GdkX11.x11_get_server_time(window.get_window())
            context.set_timestamp(timestamp)
            app = Gio.AppInfo.create_from_commandline(
                " ".join(GLib.shell_quote(argument) for argument in command),
                button.get_tooltip_text().split(" · ")[0],
                Gio.AppInfoCreateFlags.SUPPORTS_STARTUP_NOTIFICATION)
            if not app.launch([], context):
                raise OSError("The application did not launch")
        except (OSError, GLib.Error) as error:
            self.show_error("Could not open this app: " + str(error))
            return
        if screen:
            # Xfce Terminal can reuse its running server without activating its
            # new window. Wait for that window and explicitly transfer focus.
            if self.launch_timer:
                GLib.source_remove(self.launch_timer)
            self.launch_timer = GLib.timeout_add(
                50, self.focus_terminal, window, screen, existing, timestamp, time.monotonic() + 5)
        else:
            # on_close saves journal edits and retains the window on save failure.
            window.close()

    def focus_terminal(self, window, screen, existing, timestamp, deadline):
        candidate = new_terminal(screen, existing)
        active = screen.get_active_window()
        if candidate:
            if active and active.get_xid() == candidate.get_xid():
                self.launch_timer = 0
                window.close()
                return False
            # This is a user-requested launcher action, like a taskbar click.
            candidate.activate(timestamp)
            return True
        if time.monotonic() < deadline:
            return True
        self.launch_timer = 0
        self.show_error("The terminal window did not appear. Try again or press Esc to close Abide.")
        return False

    def open_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.menu_route = "Abide"
        self.menu_selections = {}
        self.menu_search = Gtk.SearchEntry()
        self.menu_search.set_width_chars(8)
        self.menu_search.set_max_width_chars(8)
        self.menu_search.get_style_context().add_class("abide-search")
        self.menu_search.connect("changed", self.refresh_menu)
        page.pack_start(self.menu_search, False, False, 0)
        self.menu_list = Gtk.ListBox()
        self.menu_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.menu_list.set_activate_on_single_click(True)
        self.menu_list.connect("row-activated", self.activate_menu_row)
        scroll = Gtk.ScrolledWindow()
        self.menu_scroll = scroll
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_propagate_natural_width(True)
        scroll.set_propagate_natural_height(True)
        monitor = Gdk.Display.get_default().get_primary_monitor()
        height = monitor.get_workarea().height if monitor else 800
        scroll.set_max_content_height(max(160, height - 150))
        scroll.add(self.menu_list)
        page.pack_start(scroll, True, True, 0)
        self.menu_empty = label("No matching actions.", "abide-muted")
        self.menu_empty.set_no_show_all(True)
        page.pack_start(self.menu_empty, False, False, 0)
        self.refresh_menu()
        return page

    def refresh_menu(self, *_):
        query = self.menu_search.get_text().casefold().split()
        for row in self.menu_list.get_children():
            self.menu_list.remove(row)
        self.menu_search.set_placeholder_text("Search " + self.menu_route + "…")
        items = list(MENUS[self.menu_route])
        if query and self.menu_route == "Abide":
            items += [item for route, entries in MENUS.items() if route != "Abide" for item in entries]
            items += [(app.name, app.icon, app.command(Path.home() / ".local/bin")) for app in WEB_APPS]
        elif self.menu_route != "Abide" and not query:
            items.insert(0, ("Back", "go-previous-symbolic", "Abide"))
        def searchable(item):
            title, _icon, action = item
            return (title + " " + " ".join(action if isinstance(action, list) else [])).casefold()
        matches = [item for item in items if all(word in searchable(item) for word in query)]
        if query:
            matches.sort(key=lambda item: item[0].casefold() != " ".join(query))
        for title, icon, action in matches:
            row = Gtk.ListBoxRow()
            row.action = action
            row.set_tooltip_text(title)
            row.get_style_context().add_class("abide-menu-row")
            content = Gtk.Box(spacing=12)
            content.set_border_width(8)
            content.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
            content.pack_start(label(title), True, True, 0)
            if isinstance(action, str):
                content.pack_end(label("›", "abide-muted"), False, False, 0)
            row.add(content)
            self.menu_list.add(row)
        self.menu_list.show_all()
        self.menu_empty.set_visible(not matches)
        remembered = self.menu_selections.get(self.menu_route) if not query else None
        selected = next((row for row in self.menu_list.get_children()
                         if row.get_tooltip_text() == remembered), self.menu_list.get_row_at_index(0))
        self.menu_list.select_row(selected)

    def change_menu_route(self, route, selected=None):
        selected = selected or self.menu_list.get_selected_row()
        if selected:
            self.menu_selections[self.menu_route] = selected.get_tooltip_text()
        self.menu_route = route
        self.menu_search.set_text("")
        self.refresh_menu()
        self.menu_search.grab_focus()

    def activate_menu_row(self, _list, row):
        if isinstance(row.action, str):
            self.change_menu_route(row.action, row)
        else:
            self.launch(row, row.action)

    def reflect_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dates = Gtk.Box(spacing=12)
        dates.pack_start(label("Journal", "abide-heading"), True, True, 0)
        self.date_label = label("")
        self.date_button = Gtk.MenuButton()
        self.date_button.set_relief(Gtk.ReliefStyle.NONE)
        self.date_button.add(self.date_label)
        self.calendar = Gtk.Calendar()
        self.calendar.connect("day-selected", self.on_date_selected)
        self.date_popover = Gtk.Popover()
        self.date_popover.add(self.calendar)
        self.calendar.show_all()
        self.date_button.set_popover(self.date_popover)
        dates.pack_end(self.date_button, False, False, 0)
        page.pack_start(dates, False, False, 0)
        self.editor = Gtk.TextView()
        self.editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.editor.set_left_margin(14)
        self.editor.set_right_margin(14)
        self.editor.set_top_margin(12)
        self.editor.set_bottom_margin(12)
        self.editor.get_buffer().connect("changed", self.on_edit)
        scroll = Gtk.ScrolledWindow()
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_min_content_height(130)
        scroll.add(self.editor)
        page.pack_start(scroll, True, True, 0)
        return page

    def on_date_selected(self, calendar):
        if self.syncing_date:
            return
        year, month, day = calendar.get_date()
        target = min(date.today(), date(year, month + 1, day))
        self.change_day((target - self.day).days)
        self.sync_calendar()
        self.date_popover.popdown()

    def sync_calendar(self):
        self.syncing_date = True
        try:
            self.calendar.select_month(self.day.month - 1, self.day.year)
            self.calendar.select_day(self.day.day)
        finally:
            self.syncing_date = False

    def shortcuts_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.shortcut_search = Gtk.SearchEntry()
        self.shortcut_search.set_placeholder_text("Search shortcuts…")
        self.shortcut_search.get_style_context().add_class("abide-search")
        self.shortcut_search.set_tooltip_text("Search by action or key, such as terminal, voice, or Super.")
        self.shortcut_search.connect("changed", self.filter_shortcuts)
        page.pack_start(self.shortcut_search, False, False, 0)
        self.shortcut_list = Gtk.ListBox()
        self.shortcut_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.shortcut_list.set_filter_func(self.shortcut_matches)
        scroll = Gtk.ScrolledWindow()
        self.shortcut_scroll = scroll
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_min_content_height(360)
        scroll.add(self.shortcut_list)
        page.pack_start(scroll, True, True, 0)
        self.shortcut_empty = label("No shortcuts match your search.", "abide-muted")
        self.shortcut_empty.set_no_show_all(True)
        page.pack_start(self.shortcut_empty, False, False, 0)
        self.launchers, self.config_error = load_launchers(ROOT / "launchers.json", DEFAULT_LAUNCHERS)
        self.populate_shortcuts()
        return page

    def reload_shortcuts(self):
        launchers, self.config_error = load_launchers(ROOT / "launchers.json", DEFAULT_LAUNCHERS)
        if launchers != self.launchers:
            self.launchers = launchers
            self.populate_shortcuts()

    def populate_shortcuts(self):
        for row in self.shortcut_list.get_children():
            row.destroy()
        for description, keys in shortcut_rows(self.launchers):
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            row.set_selectable(False)
            row.search_text = (description + " " + keys).casefold()
            if "super" in row.search_text:
                row.search_text += " windows win"
            if "ctrl" in row.search_text:
                row.search_text += " control"
            if "return" in row.search_text:
                row.search_text += " enter"
            content = Gtk.Box(spacing=32)
            content.set_border_width(14)
            row.get_style_context().add_class("abide-shortcut-row")
            content.pack_start(label(description), True, True, 0)
            key = label(keys, "abide-key")
            key.set_halign(Gtk.Align.END)
            key.set_xalign(1)
            key.set_size_request(360, -1)
            content.pack_end(key, False, False, 0)
            row.add(content)
            self.shortcut_list.add(row)
        self.shortcut_list.show_all()
        self.filter_shortcuts()

    def shortcut_matches(self, row):
        query = self.shortcut_search.get_text().casefold().replace("+", " ")
        tokens = row.search_text.replace("+", " ").split()
        return all(word in tokens if len(word) == 1 else word in row.search_text
                   for word in query.split())

    def filter_shortcuts(self, *_):
        self.shortcut_list.invalidate_filter()
        self.shortcut_empty.set_visible(not any(self.shortcut_matches(row)
                                               for row in self.shortcut_list.get_children()))

    def on_active(self, window, *_):
        if self.blur_timer:
            GLib.source_remove(self.blur_timer)
            self.blur_timer = 0
        if not window.get_visible():
            self.focus_seen = False
        elif window.is_active():
            self.focus_seen = True
        elif self.focus_seen:
            self.blur_timer = GLib.timeout_add(150, self.close_if_inactive, window)

    def close_if_inactive(self, window):
        # A date picker or context menu can briefly own the GTK grab.
        if not window.is_active() and Gtk.grab_get_current() is not None:
            return True
        if not window.is_active() and isinstance(window.get_window(), GdkX11.X11Window):
            # Popup grabs can leave GTK inactive even though Xfce still regards
            # Abide as the active window. Wait for actual desktop navigation.
            screen = Wnck.Screen.get_default()
            if screen:
                screen.force_update()
                active = screen.get_active_window()
                if active and active.get_xid() == window.get_window().get_xid():
                    return True
        self.blur_timer = 0
        if not window.is_active():
            window.close()
            if self.dirty:
                window.present()
        return False

    def on_edit(self, _buffer):
        self.dirty = True
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.status.hide()
        self.save_timer = GLib.timeout_add(600, self.save)

    def save(self):
        self.save_timer = 0
        if not self.dirty:
            return False
        buffer = self.editor.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        try:
            JOURNAL.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(JOURNAL, 0o700)
            path = JOURNAL / (self.day.isoformat() + ".txt")
            temporary = path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as output:
                output.write(text)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            self.dirty = False
            self.status.hide()
        except OSError as error:
            self.show_error("Could not save: " + str(error))
        return False

    def load_day(self):
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = 0
        path = JOURNAL / (self.day.isoformat() + ".txt")
        try:
            text = path.read_text() if path.exists() else ""
        except OSError as error:
            self.show_error("Could not open this entry: " + str(error))
            return False
        self.editor.get_buffer().set_text(text)
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = 0
        self.dirty = False
        self.date_label.set_text(self.day.strftime("%a, %b %d, %Y"))
        self.sync_calendar()
        self.status.hide()
        return True

    def change_day(self, offset):
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = 0
        self.save()
        if self.dirty:
            return
        old_day = self.day
        self.day = min(date.today(), self.day + timedelta(days=offset))
        if not self.load_day():
            self.day = old_day

    def on_close(self, window, _event):
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = 0
        self.save()
        if self.reuse_windows and not self.dirty:
            self.clear_timers()
            self.focus_seen = False
            window.hide()
            return True
        return self.dirty

    def on_destroy(self, _window):
        self.cached_window = None
        self.clear_timers()

    def clear_timers(self):
        for timer in (self.save_timer, self.blur_timer, self.launch_timer):
            if timer:
                GLib.source_remove(timer)
        self.save_timer = self.blur_timer = self.launch_timer = 0

    def on_key(self, window, event):
        if self.panel in ("menu", "shortcuts") and event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            search = self.menu_search if self.panel == "menu" else self.shortcut_search
            search.grab_focus()
            search.select_region(0, -1)
            return True
        if self.panel == "menu":
            if event.keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
                current = self.menu_list.get_selected_row()
                step = 1 if event.keyval == Gdk.KEY_Down else -1
                index = current.get_index() if current else -1
                target = self.menu_list.get_row_at_index(max(0, index + step))
                if target:
                    self.menu_list.select_row(target)
                    target.grab_focus()
                    self.menu_search.grab_focus()
                return True
            if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                row = self.menu_list.get_selected_row()
                if row:
                    self.activate_menu_row(self.menu_list, row)
                return True
            if self.menu_route != "Abide" and (event.keyval == Gdk.KEY_Escape or (
                    event.keyval == Gdk.KEY_BackSpace and not self.menu_search.get_text())):
                self.change_menu_route("Abide")
                return True
        if event.keyval == Gdk.KEY_Escape:
            window.close()
            return True
        return False


class Guide(Gtk.Application, Panel):
    """Standalone fallback for sessions without the resident service."""

    def __init__(self, panel="menu"):
        Gtk.Application.__init__(self, application_id="local.abide." + panel.capitalize(),
                                 flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        Panel.__init__(self, panel, self, reuse_windows=False)

    def do_activate(self):
        Panel.do_activate(self)

    def do_command_line(self, command_line):
        window = self.get_active_window()
        if "--toggle" in command_line.get_arguments() and window and window.is_active():
            window.close()
        else:
            self.activate()
        return 0


class Panels(Gtk.Application):
    """One resident process serves lightweight hotkey requests for all panels."""

    def __init__(self):
        super().__init__(application_id="local.abide.Panels", flags=Gio.ApplicationFlags.IS_SERVICE)
        self.guides = {}
        for name, callback in (("show", self.on_show), ("toggle", self.on_toggle)):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", callback)
            self.add_action(action)
        stop = Gio.SimpleAction.new("stop", None)
        stop.connect("activate", self.on_stop)
        self.add_action(stop)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        GLib.idle_add(self.prewarm)

    def guide(self, panel):
        if panel not in ("menu", "journal", "shortcuts"):
            raise ValueError("Unknown panel: " + panel)
        if panel not in self.guides:
            guide = Panel(panel, self)
            self.guides[panel] = guide
        return self.guides[panel]

    def prewarm(self):
        # Build controls without mapping windows or reading journal entries.
        for panel in ("menu", "shortcuts"):
            guide = self.guide(panel)
            if guide.cached_window is None:
                guide.build_window()
        return False

    def on_show(self, _action, parameter):
        self.guide(parameter.get_string()).activate()

    def on_toggle(self, _action, parameter):
        guide = self.guide(parameter.get_string())
        window = guide.cached_window
        if window and window.get_visible() and window.is_active():
            window.close()
        else:
            guide.activate()

    def on_stop(self, _action, _parameter):
        for guide in self.guides.values():
            if guide.cached_window:
                guide.on_close(guide.cached_window, None)
            if guide.dirty:
                guide.cached_window.present()
                return
        for guide in self.guides.values():
            for window in list(guide.get_windows()):
                window.destroy()
        self.quit()


if __name__ == "__main__":
    if "--service" in sys.argv:
        raise SystemExit(Panels().run([sys.argv[0]]))
    if "--terminal" in sys.argv:
        raise SystemExit(open_terminal())
    panel = "shortcuts" if "--shortcuts" in sys.argv else "journal" if any(
        option in sys.argv for option in ("--journal", "--reflect")) else "menu"
    raise SystemExit(Guide(panel).run(sys.argv))
