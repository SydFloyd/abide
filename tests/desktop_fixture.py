"""Keep a desktop surface alive while tests open and close every other window."""
from pathlib import Path
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gdk, GLib, Gtk, Wnck

window = Gtk.Window(title="Abide test desktop")
window.set_decorated(False)
window.set_skip_taskbar_hint(True)
window.set_skip_pager_hint(True)
window.set_default_size(1280, 800)
window.show_all()
# xfwm publishes its stacking list after a second surface appears. A regular
# Xfce session has both xfdesktop and a panel, even with no applications open.
panel = Gtk.Window(title="Abide test panel")
panel.set_decorated(False)
panel.set_accept_focus(False)
panel.set_skip_taskbar_hint(True)
panel.set_skip_pager_hint(True)
panel.set_type_hint(Gdk.WindowTypeHint.DOCK)
panel.set_default_size(1280, 1)
panel.move(0, 0)
panel.show_all()
screen = Wnck.Screen.get_default()
def ready():
    screen.force_update()
    if any(item.get_xid() == window.get_window().get_xid() for item in screen.get_windows()):
        (Path.home() / "desktop-ready").write_text("ready\n")
        return False
    return True
GLib.timeout_add(20, ready)
Gtk.main()
