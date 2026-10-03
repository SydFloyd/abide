#!/usr/bin/python3
"""Three dedicated Xfce panels: apps, a local journal, and searchable shortcuts."""
from datetime import date, timedelta
from pathlib import Path
import json
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk, Wnck  # noqa: E402

ROOT = Path.home() / ".local/share/abide"
JOURNAL = ROOT / "journal"
SOURCE = Path(__file__).resolve().parent
VERSES = json.loads(((ROOT / "scripture.json") if (ROOT / "scripture.json").exists()
                     else SOURCE / "scripture.json").read_text())
QUIET = str(Path.home() / ".local/bin/abide-quiet")
DEFAULT_LAUNCHERS = [
    ("Terminal", "Super + Return", "utilities-terminal-symbolic", ["exo-open", "--launch", "TerminalEmulator"]),
    ("Browser", "Super + B", "web-browser-symbolic", ["exo-open", "--launch", "WebBrowser"]),
    ("Files", "Super + E", "system-file-manager-symbolic", ["thunar"]),
    ("Mousepad", "Super + M", "accessories-text-editor-symbolic", ["mousepad"]),
    ("Find an app", "Alt + F3", "system-search-symbolic", ["xfce4-appfinder"]),
]
LAUNCHERS = (json.loads((ROOT / "launchers.json").read_text())
             if (ROOT / "launchers.json").exists() else DEFAULT_LAUNCHERS)
SETTINGS = [
    ("Display", "video-display-symbolic", ["xfce4-display-settings"]),
    ("Appearance", "preferences-system-symbolic", ["xfce4-appearance-settings"]),
    ("Notifications", "preferences-system-notifications-symbolic", ["xfce4-notifyd-config"]),
    ("Screenshot", "camera-photo-symbolic", ["xfce4-screenshooter"]),
]


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


class Guide(Gtk.Application):
    def __init__(self, panel="menu"):
        if panel not in ("menu", "journal", "shortcuts"):
            raise ValueError("Unknown Abide panel: " + panel)
        super().__init__(application_id="local.abide." + panel.capitalize(), flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.panel = panel
        self.day = date.today()
        self.dirty = False
        self.save_timer = 0
        self.quiet_timer = 0
        self.syncing_quiet = False
        self.blur_timer = 0
        self.launch_timer = 0
        self.focus_seen = False

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()
        window = self.get_active_window()
        if "--toggle" in arguments and window and window.is_active():
            window.close()
            return 0
        self.activate()
        return 0

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        window = Gtk.ApplicationWindow(application=self, title={
            "menu": "Abide", "journal": "Abide Journal", "shortcuts": "Abide Shortcuts"}[self.panel])
        window.get_style_context().add_class("abide-guide")
        window.set_position(Gtk.WindowPosition.CENTER)
        window.set_default_size(940 if self.panel == "shortcuts" else 820, 640)
        window.connect("key-press-event", self.on_key)
        window.connect("delete-event", self.on_close)
        window.connect("destroy", self.on_destroy)
        self.focus_seen = False
        window.connect("notify::is-active", self.on_active)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_border_width(26)
        window.add(body)
        css = SOURCE / "app.css"
        if css.exists():
            provider = Gtk.CssProvider()
            provider.load_from_path(str(css))
            Gtk.StyleContext.add_provider_for_screen(window.get_screen(), provider,
                                                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        header = Gtk.Box(spacing=20)
        title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title.pack_start(label({"menu": "ABIDE", "journal": "JOURNAL", "shortcuts": "SHORTCUTS"}[self.panel],
                               "abide-heading"), False, False, 0)
        title.pack_start(label("Faith · Hope · Love", "abide-muted"), False, False, 0)
        header.pack_start(title, True, True, 0)
        if self.panel == "menu":
            self.quiet = Gtk.ToggleButton(label="Quiet mode · Super + Q")
            self.quiet.set_valign(Gtk.Align.CENTER)
            self.quiet.set_tooltip_text("Toggle Do Not Disturb for desktop notifications.")
            self.quiet.connect("toggled", self.on_quiet)
            header.pack_end(self.quiet, False, False, 0)
        body.pack_start(header, False, False, 0)
        self.page = {"menu": self.open_page, "journal": self.reflect_page,
                     "shortcuts": self.shortcuts_page}[self.panel]()
        body.pack_start(self.page, True, True, 0)
        self.status = label({
            "menu": "Super + J · Journal    Super + K · Shortcuts    Esc · Close",
            "journal": "Entries stay on this computer. Esc · Close",
            "shortcuts": "Super is the Windows key. Esc · Close"}[self.panel], "abide-muted")
        self.status.set_line_wrap(True)
        body.pack_end(self.status, False, False, 0)
        if self.panel == "journal":
            self.load_day()
        elif self.panel == "menu":
            self.sync_quiet()
            self.quiet_timer = GLib.timeout_add_seconds(2, self.sync_quiet)
        window.show_all()
        if self.panel == "shortcuts":
            self.shortcut_search.grab_focus()
        elif self.panel == "journal":
            self.editor.grab_focus()

    def launch(self, button, command):
        window = button.get_toplevel()
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
            self.status.set_text("Opened " + button.get_tooltip_text().split(" · ")[0] + ".")
        except (OSError, GLib.Error) as error:
            self.status.set_text("Could not open this app: " + str(error))
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
        self.status.set_text("The terminal window did not appear. Try again or press Esc to close Abide.")
        return False

    def app_button(self, title, key, icon, command):
        button = Gtk.Button()
        button.set_tooltip_text(title + (" · " + key if key else ""))
        row = Gtk.Box(spacing=14)
        row.set_border_width(12)
        row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        texts.pack_start(label(title), False, False, 0)
        if key:
            texts.pack_start(label(key, "abide-muted"), False, False, 0)
        row.pack_start(texts, True, True, 0)
        button.add(row)
        button.connect("clicked", self.launch, command)
        return button

    def open_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.pack_start(label("YOUR APPS", "abide-section"), False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        self.launcher_grid = grid
        for i, item in enumerate(LAUNCHERS):
            grid.attach(self.app_button(*item), i % 3, i // 3, 1, 1)
        page.pack_start(grid, False, False, 0)
        page.pack_start(label("TOOLS & SETTINGS", "abide-section"), False, False, 0)
        tools = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        for i, (title, icon, command) in enumerate(SETTINGS):
            tools.attach(self.app_button(title, "", icon, command), i % 2, i // 2, 1, 1)
        page.pack_start(tools, False, False, 0)
        return page

    def reflect_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scripture = Gtk.ComboBoxText()
        self.scripture = scripture
        for verse in VERSES:
            scripture.append_text(verse["title"] + " · " + verse["reference"])
        self.verse = label("")
        self.verse.set_line_wrap(True)
        self.verse.set_max_width_chars(70)
        self.verse.set_selectable(True)
        self.verse.get_style_context().add_class("abide-scripture")
        self.verse_source = label("", "abide-muted")
        def choose_verse(combo):
            verse = VERSES[combo.get_active()]
            self.verse.set_text(verse["text"])
            self.verse_source.set_text("Scripture excerpts · " + verse.get("translation", "ESV"))
        scripture.connect("changed", choose_verse)
        scripture.set_active(date.today().toordinal() % len(VERSES))
        page.pack_start(scripture, False, False, 0)
        page.pack_start(self.verse, False, False, 0)
        page.pack_start(self.verse_source, False, False, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)
        dates = Gtk.Box(spacing=12)
        previous = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        previous.set_tooltip_text("Previous day")
        previous.connect("clicked", lambda _: self.change_day(-1))
        following = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        following.set_tooltip_text("Next day")
        following.connect("clicked", lambda _: self.change_day(1))
        self.next_day = following
        self.date_label = label("")
        today = Gtk.Button(label="Today")
        today.connect("clicked", lambda _: self.change_day((date.today() - self.day).days))
        dates.pack_start(previous, False, False, 0)
        dates.pack_start(self.date_label, True, True, 0)
        dates.pack_start(today, False, False, 0)
        dates.pack_start(following, False, False, 0)
        page.pack_start(dates, False, False, 0)
        page.pack_start(label("PRAYER & REFLECTION", "abide-section"), False, False, 0)
        prompt = label("Give thanks. Bring what is weighing on you to God. Choose one act of love.", "abide-muted")
        prompt.set_line_wrap(True)
        page.pack_start(prompt, False, False, 0)
        self.editor = Gtk.TextView()
        self.editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.editor.set_left_margin(14)
        self.editor.set_right_margin(14)
        self.editor.set_top_margin(12)
        self.editor.set_bottom_margin(12)
        self.editor.get_buffer().connect("changed", self.on_edit)
        scroll = Gtk.ScrolledWindow()
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.set_min_content_height(130)
        scroll.add(self.editor)
        page.pack_start(scroll, True, True, 0)
        self.save_status = label("Saved on this computer.", "abide-muted")
        page.pack_start(self.save_status, False, False, 0)
        return page

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
        rows = [("Abide menu", "Super + Space"), ("Journal", "Super + J"),
                ("Shortcuts", "Super + K")]
        rows += [(title, keys) for title, keys, _icon, _command in LAUNCHERS if keys] + [
            ("Quiet mode", "Super + Q"), ("Search shortcuts", "Ctrl + F"),
            ("Close Abide panel", "Esc"), ("Run a command", "Super + R"),
            ("Faith / Hope / Love", "Super + 1 / 2 / 3"),
            ("Move window there", "Super + Shift + 1–3"),
            ("Tile left / right", "Super + ← / →"),
            ("Maximize / restore", "Super + ↑"),
            ("Show the background", "Super + D"), ("Lock", "Super + L"),
            ("Switch windows", "Alt + Tab"), ("Previous window", "Alt + Shift + Tab"),
            ("Close window", "Alt + F4"),
            ("Screenshot", "Print"), ("Select a screenshot area", "Shift + Print"),
            ("Screenshot this window", "Alt + Print"),
        ]
        for description, keys in rows:
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
            key.set_size_request(280, -1)
            content.pack_end(key, False, False, 0)
            row.add(content)
            self.shortcut_list.add(row)
        scroll = Gtk.ScrolledWindow()
        self.shortcut_scroll = scroll
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(360)
        scroll.add(self.shortcut_list)
        page.pack_start(scroll, True, True, 0)
        self.shortcut_empty = label("No shortcuts match your search.", "abide-muted")
        self.shortcut_empty.set_no_show_all(True)
        page.pack_start(self.shortcut_empty, False, False, 0)
        return page

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
        if window.is_active():
            self.focus_seen = True
        elif self.focus_seen:
            self.blur_timer = GLib.timeout_add(150, self.close_if_inactive, window)

    def close_if_inactive(self, window):
        # A Scripture chooser or context menu can briefly own the GTK grab.
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
                self.status.set_text("Abide stayed open because your journal could not be saved.")
                window.present()
        return False

    def on_edit(self, _buffer):
        self.dirty = True
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_status.set_text("Saving…")
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
            self.save_status.set_text("Saved on this computer.")
        except OSError as error:
            self.save_status.set_text("Could not save: " + str(error))
        return False

    def load_day(self):
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = 0
        path = JOURNAL / (self.day.isoformat() + ".txt")
        try:
            text = path.read_text() if path.exists() else ""
        except OSError as error:
            self.save_status.set_text("Could not open this entry: " + str(error))
            return False
        self.editor.get_buffer().set_text(text)
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = 0
        self.dirty = False
        self.date_label.set_text(self.day.strftime("%A, %B %d, %Y"))
        self.next_day.set_sensitive(self.day < date.today())
        self.save_status.set_text("Saved on this computer." if path.exists() else "Write here. Your entry saves automatically.")
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

    def sync_quiet(self):
        try:
            result = subprocess.run([QUIET, "--status"], capture_output=True, text=True, check=True, timeout=3)
            self.syncing_quiet = True
            self.quiet.set_active(result.stdout.strip() == "true")
            self.quiet.set_sensitive(True)
        except (OSError, subprocess.SubprocessError):
            self.quiet.set_sensitive(False)
        finally:
            self.syncing_quiet = False
        return True

    def on_quiet(self, button):
        if self.syncing_quiet:
            return
        try:
            subprocess.run([QUIET, "--on" if button.get_active() else "--off"], check=True,
                           capture_output=True, timeout=3)
            self.status.set_text("Quiet mode on." if button.get_active() else "Quiet mode off.")
        except (OSError, subprocess.SubprocessError):
            self.status.set_text("Could not change notification settings.")
            self.sync_quiet()

    def on_close(self, _window, _event):
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = 0
        self.save()
        return self.dirty

    def on_destroy(self, _window):
        for timer in (self.save_timer, self.quiet_timer, self.blur_timer, self.launch_timer):
            if timer:
                GLib.source_remove(timer)
        self.save_timer = self.quiet_timer = self.blur_timer = self.launch_timer = 0

    def on_key(self, window, event):
        if self.panel == "shortcuts" and event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.shortcut_search.grab_focus()
            self.shortcut_search.select_region(0, -1)
            return True
        if event.keyval == Gdk.KEY_Escape:
            window.close()
            return True
        return False


if __name__ == "__main__":
    if "--terminal" in sys.argv:
        raise SystemExit(open_terminal())
    panel = "shortcuts" if "--shortcuts" in sys.argv else "journal" if any(
        option in sys.argv for option in ("--journal", "--reflect")) else "menu"
    raise SystemExit(Guide(panel).run(sys.argv))
