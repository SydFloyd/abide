"""Exercise real bspwm, keyboard/mouse input, updates, and restoration in Xvfb."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import window_manager as wm  # noqa: E402


def run(*arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout.strip()


def main():
    if os.environ.get("ABIDE_ISOLATED_DESKTOP") != "1":
        raise SystemExit("This check requires a disposable HOME, X server, and D-Bus session.")
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkX11", "3.0")
    from gi.repository import GdkX11, GLib, Gtk
    Gtk.init([])
    windows = []
    context = GLib.MainContext.default()
    def wait(predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            try:
                if predicate():
                    return
            except (RuntimeError, ValueError):
                # A client can unmap between the separate IPC queries used
                # by a predicate; retry after bspwm processes that event.
                pass
            time.sleep(0.025)
        raise AssertionError("The tiling desktop did not reach the expected state.")
    def window(title):
        item = Gtk.Window(title=title)
        item.set_default_size(320, 240)
        item.add(Gtk.TextView())
        item.show_all()
        windows.append(item)
        wait(lambda: item.get_window() is not None)
        # Allow libwnck's new-window focus request and the settings daemon's
        # asynchronous key grabs to settle before synthesizing user input.
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.01)
        return hex(GdkX11.X11Window.get_xid(item.get_window()))
    def tree():
        return json.loads(run("bspc", "query", "-T", "-d", "focused"))
    def node(xid):
        return json.loads(run("bspc", "query", "-T", "-n", xid))
    def focused():
        return hex(int(run("bspc", "query", "-N", "-n", "focused"), 16))
    def nodes(desktop):
        return {hex(int(value, 16)) for value in run("bspc", "query", "-N", "-d", desktop).splitlines()}

    x11, xtst = ctypes.CDLL("libX11.so.6"), ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(None)
    assert display
    def key(name, down):
        code = x11.XKeysymToKeycode(display, x11.XStringToKeysym(name.encode()))
        assert code
        xtst.XTestFakeKeyEvent(display, code, down, 0)
    def press(*names):
        for name in names:
            key(name, True)
        for name in reversed(names):
            key(name, False)
        x11.XFlush(display)
    def drag(xid, button, dx, dy):
        rectangle = node(xid)["client"]["floatingRectangle"]
        x, y = rectangle["x"] + 30, rectangle["y"] + 30
        xtst.XTestFakeMotionEvent(display, -1, x, y, 0)
        key("Super_L", True)
        xtst.XTestFakeButtonEvent(display, button, True, 0)
        x11.XFlush(display)
        time.sleep(0.1)
        xtst.XTestFakeMotionEvent(display, -1, x + dx, y + dy, 0)
        x11.XFlush(display)
        time.sleep(0.1)
        xtst.XTestFakeButtonEvent(display, button, False, 0)
        key("Super_L", False)
        x11.XFlush(display)

    wm.set_property("xfce4-panel", "/panels", [1], "int", True)
    wm.set_property("xfce4-panel", "/panels/panel-1/plugin-ids", [1, 2, 3], "int", True)
    wm.set_property("xfce4-panel", "/plugins/plugin-1", "clock")
    wm.set_property("xfce4-panel", "/plugins/plugin-2", "tasklist")
    wm.set_property("xfce4-panel", "/plugins/plugin-3", "pager")
    wm.set_property("xfwm4", "/general/workspace_count", 5, "int")
    wm.set_property("xfwm4", "/general/workspace_names", ["1", "2", "3", "4", "5"], array=True)
    original_session = wm.property_value("xfce4-session", wm.SESSION_KEY, True)
    first = window("Existing window survives the WM switch")
    try:
        run(sys.executable, str(SOURCE / "install.py"), "--tiling")
        assert wm.wm_name() == "bspwm"
        assert node(first)["client"]["state"] == "tiled", node(first)
        assert wm.property_value("xfce4-panel", "/panels/panel-1/plugin-ids", True) == ["1", "3"]
        assert wm.property_value("xfce4-session", wm.SESSION_KEY, True) == [str(wm.BIN / "abide-wm"), "--session"]
        assert run("bspc", "query", "-D", "--names").splitlines() == ["1", "2", "3", "4", "5"]
        second = window("Second golden-ratio tile")
        wait(lambda: focused() == second)
        root = tree()["root"]
        assert abs(root["splitRatio"] - 0.61803398875) < 0.0001, root
        left, right = node(first)["client"]["tiledRectangle"], node(second)["client"]["tiledRectangle"]
        assert left["x"] + left["width"] <= right["x"], (left, right)
        assert abs(left["width"] / (left["width"] + right["width"]) - 0.618) < 0.02
        press("Super_L", "Left")
        wait(lambda: focused() == first)
        press("Super_L", "Shift_L", "Right")
        wait(lambda: node(first)["client"]["tiledRectangle"]["x"] > node(second)["client"]["tiledRectangle"]["x"])
        before = node(first)["client"]["tiledRectangle"]["width"]
        press("Super_L", "Control_L", "Left")
        wait(lambda: node(first)["client"]["tiledRectangle"]["width"] != before)
        third = window("Third recursive tile")
        wait(lambda: focused() == third)
        root = tree()["root"]
        assert any(child["firstChild"] is not None for child in (root["firstChild"], root["secondChild"]))
        press("Super_L", "t")
        wait(lambda: node(third)["client"]["state"] == "floating")
        before = node(third)["client"]["floatingRectangle"].copy()
        drag(third, 1, 80, 40)
        wait(lambda: node(third)["client"]["floatingRectangle"]["x"] == before["x"] + 80)
        before = node(third)["client"]["floatingRectangle"].copy()
        drag(third, 3, -40, -30)
        wait(lambda: node(third)["client"]["floatingRectangle"]["width"] != before["width"])
        press("Super_L", "t")
        wait(lambda: node(third)["client"]["state"] == "tiled")
        press("Super_L", "f")
        wait(lambda: node(third)["client"]["state"] == "fullscreen")
        press("Super_L", "f")
        wait(lambda: node(third)["client"]["state"] == "tiled")
        press("Super_L", "Shift_L", "2")
        wait(lambda: run("bspc", "query", "-D", "-d", "focused") == run("bspc", "query", "-D", "-d", "^2"))
        assert third in nodes("^2")
        press("Super_L", "1")
        wait(lambda: first in nodes("focused"))
        for destination in ("4", "5"):
            press("Super_L", destination)
            wait(lambda: run("bspc", "query", "-D", "-d", "focused") == run("bspc", "query", "-D", "-d", "^" + destination))
            press("Super_L", "1")
            wait(lambda: first in nodes("focused"))
            run("bspc", "node", "-f", first)
            press("Super_L", "Shift_L", destination)
            wait(lambda: first in nodes("^" + destination) and focused() == first)
            press("Super_L", "Shift_L", "1")
            wait(lambda: first in nodes("^1") and focused() == first)
        run(str(wm.BIN / "abide"), "--toggle")
        wait(lambda: any("AbidePanel" in line for line in run("bspc", "query", "-T", "-d", "focused").splitlines()))
        active = node(focused())
        assert active["client"]["className"] == "AbidePanel"
        assert active["client"]["state"] == "floating"
        assert active["client"]["borderWidth"] == 0
        press("Escape")
        wait(lambda: node(focused())["client"]["className"] != "AbidePanel")
        baseline = tree()["root"]
        profile_bytes = wm.PROFILE.read_bytes()
        run(sys.executable, str(SOURCE / "install.py"))
        assert wm.PROFILE.read_bytes() == profile_bytes
        assert tree()["root"] == baseline, "An update rearranged the tiled windows"
        run(str(wm.BIN / "abide-panels-undo"))
        assert wm.wm_name() == "bspwm" and wm.PROFILE.read_bytes() == profile_bytes
        run("bspc", "quit")
        with (wm.STATE / "session-test.log").open("ab") as log:
            subprocess.Popen([str(wm.BIN / "abide-wm"), "--session"],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        wait(lambda: wm.wm_name() == "bspwm" and first in nodes("^1"))
        assert wm.PROFILE.read_bytes() == profile_bytes
        run(str(wm.BIN / "abide-wm"), "--disable")
        assert wm.wm_name() == "xfwm4"
        assert wm.property_value("xfce4-panel", "/panels/panel-1/plugin-ids", True) == ["1", "2", "3"]
        assert wm.property_value("xfce4-session", wm.SESSION_KEY, True) == original_session
        assert not wm.enabled()
        assert all(item.get_visible() for item in windows)
        # The saved first-install undo must also restore the desktop itself.
        run(str(wm.BIN / "abide-wm"), "--enable")
        assert wm.wm_name() == "bspwm"
        backups = sorted((wm.STATE / "panel-installs").iterdir())
        applied = [backup for backup in backups if (backup / "applied").exists()]
        (wm.STATE / "latest-panels-install").write_text(str(applied[-1]) + "\n")
        run(str(wm.BIN / "abide-panels-undo"))
        assert wm.wm_name() == "xfwm4" and not wm.enabled()
        # Force a startup failure after xfwm exits: rollback must leave a
        # functioning window manager, rather than only restoring the files.
        with tempfile.TemporaryDirectory(prefix="abide-broken-wm-") as folder:
            broken = Path(folder) / "bspwm"
            broken.write_text("#!/bin/sh\nexit 23\n")
            broken.chmod(0o755)
            failed = subprocess.run([sys.executable, str(SOURCE / "install.py"), "--tiling"],
                                    env={**os.environ, "PATH": folder + ":" + os.environ["PATH"]},
                                    capture_output=True, text=True, timeout=20)
            assert failed.returncode != 0, failed.stdout
            assert wm.wm_name() == "xfwm4" and not wm.enabled(), failed.stderr
            assert all(item.get_visible() for item in windows)
        print("Tiling: adoption, golden splits, focus/swap/resize keys, headerless mouse movement, floating/fullscreen, workspaces, overlays, updates, session startup, undo, and failed-switch recovery passed.")
    finally:
        if wm.enabled():
            wm.disable()
        x11.XCloseDisplay(display)
        for item in windows:
            item.destroy()


if __name__ == "__main__":
    main()
