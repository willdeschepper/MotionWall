"""End-to-end wallpaper test in a disposable, nested GNOME session.

Run via: xvfb-run -a dbus-run-session -- /usr/bin/python3 tests/desktop_smoke.py
No files, extensions or settings are written into the user's desktop session.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait_for(function, description, timeout=35):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = function()
            if value:
                return value
        except Exception as error:
            last = error
        time.sleep(.4)
    raise AssertionError(f"Timed out: {description}; last error: {last}")


def main():
    with tempfile.TemporaryDirectory(prefix="motionwall-desktop-") as temporary:
        temporary = Path(temporary)
        for key, directory in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                               ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
            folder = temporary / directory
            folder.mkdir(mode=0o700)
            os.environ[key] = str(folder)
        os.environ["GSETTINGS_BACKEND"] = "memory"
        os.environ["GDK_BACKEND"] = "wayland"
        from gi.repository import Gio, GLib
        from motionwall.desktop import DesktopBridge, install_extension, UUID, OBJECT, INTERFACE
        from motionwall.library import Library
        install_extension()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def call(interface, method, args=None, path=OBJECT):
            return bus.call_sync("org.gnome.Shell", path, interface, method, args, None,
                                 Gio.DBusCallFlags.NONE, 5000, None).unpack()

        def desktop(method, args=None):
            return json.loads(call(INTERFACE, method, args)[0])

        def asynchronous(start):
            loop = GLib.MainLoop()
            reply = []
            def complete(status, error):
                reply.append((status, error))
                loop.quit()
            timeout = GLib.timeout_add_seconds(8, lambda: (loop.quit(), GLib.SOURCE_REMOVE)[1])
            start(complete)
            loop.run()
            if reply:
                GLib.source_remove(timeout)
            assert reply, "GUI bridge callback timed out"
            status, error = reply[0]
            assert error is None, error
            return status

        def evaluate(script):
            success, result = call("org.gnome.Shell", "Eval", GLib.Variant("(s)", (script,)), "/org/gnome/Shell")
            if not success:
                raise AssertionError(result)
            return json.loads(result)

        help_text = subprocess.run(["gnome-shell", "--help"], capture_output=True, text=True, check=True).stdout
        print(subprocess.run(["gnome-shell", "--version"], capture_output=True, text=True, check=True).stdout.strip(), flush=True)
        mode = ["--nested", "--wayland"] if "--nested" in help_text else ["--headless", "--wayland", "--virtual-monitor=1280x720"]
        output = ROOT / "smoke-output"
        output.mkdir(exist_ok=True)
        with (output / "desktop-shell.log").open("w") as log:
            shell = subprocess.Popen(["gnome-shell", *mode, "--unsafe-mode"], stdout=log, stderr=subprocess.STDOUT)
            fixture = None
            try:
                wait_for(lambda: evaluate("Main.layoutManager.monitors.length") > 0, "GNOME monitors")
                # Extension installation happened before this Shell started.
                wait_for(lambda: UUID in call("org.gnome.Shell.Extensions", "ListExtensions", path="/org/gnome/Shell")[0], "extension discovery")
                enabled = call("org.gnome.Shell.Extensions", "EnableExtension", GLib.Variant("(s)", (UUID,)), "/org/gnome/Shell")
                assert enabled[0], "Extension did not enable"
                wait_for(lambda: desktop("Status"), "MotionWall bridge")
                bridge = DesktopBridge()
                # Avoid startup overview when testing the actual desktop background.
                evaluate("Main.overview.hide(); true")
                evaluate("new Gio.Settings({schema_id: 'org.gnome.mutter'}).set_boolean('dynamic-workspaces', false); "
                         "new Gio.Settings({schema_id: 'org.gnome.desktop.wm.preferences'}).set_int('num-workspaces', 3); true")
                wait_for(lambda: evaluate("global.workspace_manager.n_workspaces") >= 3, "three workspaces")
                socket = wait_for(lambda: next((p for p in (temporary / 'runtime').glob('wayland-*')
                                               if not p.name.endswith('.lock')), None), "Wayland socket")
                fixture_env = os.environ.copy()
                fixture_env["WAYLAND_DISPLAY"] = socket.name
                fixture = subprocess.Popen(["/usr/bin/python3", str(ROOT / "tests/workspace_window.py")],
                                           env=fixture_env, stdout=log, stderr=subprocess.STDOUT)
                fixture_window = "global.get_window_actors().find(a => a.meta_window.get_title() === 'MotionWall Workspace Test')?.meta_window"
                wait_for(lambda: evaluate(f"Boolean({fixture_window})"), "ordinary window")
                evaluate("global.workspace_manager.get_workspace_by_index(0).activate(global.get_current_time()); true")
                evaluate(f"({fixture_window}).change_workspace_by_index(0, false); ({fixture_window}).activate(global.get_current_time()); true")
                evaluate("new Gio.Settings({schema_id: 'org.gnome.desktop.wm.keybindings'}).set_strv('switch-to-workspace-right', ['<Super>Page_Down']); true")
                evaluate("(async () => { const {default: Clutter} = await import('gi://Clutter'); "
                         "const backend = typeof Clutter.get_default_backend === 'function' ? Clutter.get_default_backend() : global.stage.context.get_backend(); "
                         "global._motionwallTestKeyboard = backend.get_default_seat().create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE); return true; })()")
                def next_workspace():
                    evaluate("(async () => { const {default: Clutter} = await import('gi://Clutter'); "
                             "const k = global._motionwallTestKeyboard; const t = GLib.get_monotonic_time(); "
                             "k.notify_keyval(t, Clutter.KEY_Super_L, Clutter.KeyState.PRESSED); "
                             "k.notify_keyval(t + 1, Clutter.KEY_Page_Down, Clutter.KeyState.PRESSED); "
                             "k.notify_keyval(t + 2, Clutter.KEY_Page_Down, Clutter.KeyState.RELEASED); "
                             "k.notify_keyval(t + 3, Clutter.KEY_Super_L, Clutter.KeyState.RELEASED); return true; })()")
                library = Library(temporary / "catalogue")
                for filename in ("aurora.svg", "orbit.json", "pulse.gif", "aurora-video.mp4"):
                    artwork, _ = library.import_file(ROOT / "motionwall/examples" / filename)
                    status = asynchronous(lambda done: bridge.apply(library, artwork.id,
                        {"fit": "native", "speed": 1, "loop": True}, done))
                    assert status["state"] == "starting", status
                    def active():
                        state = desktop("Status")
                        if state["state"] == "error":
                            raise AssertionError(state)
                        return state if state["state"] == "active" else None
                    status = wait_for(active, f"animated {filename}", timeout=30)
                    assert status["surfaces"] >= 1 and status["layers"] >= 1, status
                    before = status["progress"]
                    wait_for(lambda: desktop("Status")["progress"] != before, "animation advances in background")
                    sizes = desktop("Status")["geometry"]
                    assert len(sizes) == status["surfaces"], "Missing wallpaper geometry"
                    for size in sizes.values():
                        assert abs(size["width"] * size["pixelRatio"] - size["nativeWidth"]) < .1, size
                        assert abs(size["height"] * size["pixelRatio"] - size["nativeHeight"]) < .1, size
                        assert abs(size["centerX"] - size["viewportCenterX"]) < .1, size
                        assert abs(size["centerY"] - size["viewportCenterY"]) < .1, size
                    print(f"ORIGINAL DESKTOP PASS: {filename} preserves original size and center", flush=True)
                    # Original renderer is hidden; the background holds a visible clone.
                    hidden = evaluate("global.get_window_actors().filter(a => a.meta_window.get_title()?.startsWith('MotionWallRenderer:')).every(a => !a.visible)")
                    assert hidden, "Renderer was visible as an ordinary window"
                    tabs = evaluate("global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null).map(w => w.get_title())")
                    assert not any(title.startswith("MotionWallRenderer:") for title in tabs), tabs
                    if filename == "aurora.svg":
                        # Switching to an empty workspace must not reactivate the
                        # fixture on workspace 0 through the hidden renderer.
                        next_workspace()
                        time.sleep(.8)
                        assert evaluate("global.workspace_manager.get_active_workspace_index()") == 1, "Workspace jumped back"
                        evaluate("Main.overview.show(); true")
                        time.sleep(1)
                        thumbnails = evaluate("(() => { const box = Main.overview._overview._controls._thumbnailsBox; "
                                              "return {visible: box.visible, width: box.width, height: box.height, count: box._thumbnails.length}; })()")
                        assert thumbnails["visible"] and thumbnails["count"] >= 3 and thumbnails["height"] > 0, thumbnails
                        assert thumbnails["width"] < 1280, thumbnails
                        next_workspace()
                        time.sleep(.8)
                        assert evaluate("global.workspace_manager.get_active_workspace_index()") == 2, "Overview workspace jumped back"
                        evaluate(f"({fixture_window}).change_workspace_by_index(2, false); true")
                        assert evaluate(f"({fixture_window}).get_workspace().index()") == 2, "Window did not move"
                        evaluate("Main.overview.hide(); true")
                        time.sleep(.5)
                        assert evaluate("global.workspace_manager.get_active_workspace_index()") == 2, "Closing overview changed workspace"
                        # Full-size wallpaper layers belong only to the desktop.
                        evaluate("Main.overview.show(); true")
                        time.sleep(.6)
                        screenshot_path = str(output / "overview.png")
                        call("org.gnome.Shell.Screenshot", "Screenshot", GLib.Variant("(bbs)",
                             (False, False, screenshot_path)), "/org/gnome/Shell/Screenshot")
                        print("WORKSPACE PASS: switch, overview thumbnails, move window and return", flush=True)
                        evaluate("Main.overview.hide(); true")
                        time.sleep(.5)
                        call("org.gnome.Shell.Screenshot", "Screenshot", GLib.Variant("(bbs)",
                             (False, False, str(output / "desktop.png"))), "/org/gnome/Shell/Screenshot")
                    status = asynchronous(bridge.stop)
                    assert status["state"] == "stopped" and status["layers"] == 0 and status["surfaces"] == 0, status
                    wait_for(lambda: evaluate("global.get_window_actors().filter(a => a.meta_window.get_title()?.startsWith('MotionWallRenderer:')).length") == 0,
                             "renderer removed")
                    print(f"DESKTOP PASS: {filename} animates behind windows and restores original", flush=True)
                # Verify actual compositor pixels, not just a transparent CSS property.
                from PIL import Image
                evaluate("(() => { const s = new Gio.Settings({schema_id: 'org.gnome.desktop.background'}); "
                         "s.set_string('picture-uri', ''); s.set_string('picture-uri-dark', ''); "
                         "s.set_string('primary-color', '#25406b'); s.set_string('color-shading-type', 'solid'); return true; })()")
                time.sleep(.8)
                def pixels(name):
                    path = output / name
                    call("org.gnome.Shell.Screenshot", "Screenshot", GLib.Variant("(bbs)",
                         (False, False, str(path))), "/org/gnome/Shell/Screenshot")
                    image = Image.open(path).convert("RGB")
                    return image.getpixel((image.width - 20, image.height - 30))
                background = pixels("alpha-baseline.png")
                assert max(abs(a - b) for a, b in zip(background, (37, 64, 107))) < 3, background
                rain, _ = library.import_file(ROOT / "motionwall/examples/chuva-alpha.svg")
                for transparent in (True, False):
                    asynchronous(lambda done: bridge.apply(library, rain.id,
                        {"fit": "native", "speed": 1, "loop": True, "transparent": transparent}, done))
                    wait_for(active, "rain wallpaper")
                    color = pixels(f"alpha-{transparent}.png")
                    expected = background if transparent else (17, 24, 39)
                    assert max(abs(a - b) for a, b in zip(color, expected)) < 3, (transparent, color, expected)
                    asynchronous(bridge.stop)
                    wait_for(lambda: evaluate("global.get_window_actors().filter(a => a.meta_window.get_title()?.startsWith('MotionWallRenderer:')).length") == 0,
                             "alpha renderer removed")
                assert pixels("alpha-restored.png") == background, "Alpha overlay did not restore wallpaper"
                print("ALPHA DESKTOP PASS: transparent rain reveals static wallpaper; opaque option and restore work", flush=True)
                # Disable cleans exported interface and all hooks after use.
                call("org.gnome.Shell.Extensions", "DisableExtension", GLib.Variant("(s)", (UUID,)), "/org/gnome/Shell")
                print("DESKTOP PASS: extension disabled cleanly", flush=True)
            except Exception:
                log.flush()
                print((output / "desktop-shell.log").read_text(), file=sys.stderr, flush=True)
                raise
            finally:
                if fixture:
                    fixture.terminate()
                    try:
                        fixture.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        fixture.kill()
                        fixture.wait()
                shell.terminate()
                try:
                    shell.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    shell.kill()
                    shell.wait()


if __name__ == "__main__":
    main()
