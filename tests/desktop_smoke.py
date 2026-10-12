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
        from motionwall.desktop import install_extension, UUID, OBJECT, INTERFACE
        from motionwall.library import Library
        install_extension()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def call(interface, method, args=None, path=OBJECT):
            return bus.call_sync("org.gnome.Shell", path, interface, method, args, None,
                                 Gio.DBusCallFlags.NONE, 5000, None).unpack()

        def desktop(method, args=None):
            return json.loads(call(INTERFACE, method, args)[0])

        def evaluate(script):
            success, result = call("org.gnome.Shell", "Eval", GLib.Variant("(s)", (script,)), "/org/gnome/Shell")
            if not success:
                raise AssertionError(result)
            return json.loads(result)

        help_text = subprocess.run(["gnome-shell", "--help"], capture_output=True, text=True, check=True).stdout
        mode = ["--nested", "--wayland"] if "--nested" in help_text else ["--headless", "--wayland", "--virtual-monitor=1280x720"]
        output = ROOT / "smoke-output"
        output.mkdir(exist_ok=True)
        with (output / "desktop-shell.log").open("w") as log:
            shell = subprocess.Popen(["gnome-shell", *mode, "--unsafe-mode"], stdout=log, stderr=subprocess.STDOUT)
            try:
                wait_for(lambda: evaluate("Main.layoutManager.monitors.length") > 0, "GNOME monitors")
                # Extension installation happened before this Shell started.
                enabled = call("org.gnome.Shell.Extensions", "EnableExtension", GLib.Variant("(s)", (UUID,)), "/org/gnome/Shell/Extensions")
                assert enabled[0], "Extension did not enable"
                wait_for(lambda: desktop("Status"), "MotionWall bridge")
                # Avoid startup overview when testing the actual desktop background.
                evaluate("Main.overview.hide(); true")
                library = Library(temporary / "catalogue")
                for filename in ("aurora.svg", "orbit.json", "pulse.gif"):
                    artwork, _ = library.import_file(ROOT / "motionwall/examples" / filename)
                    request = GLib.Variant("(ssss)", (str(ROOT), str(library.root), artwork.id,
                                                      json.dumps({"fit": "cover", "speed": 1, "loop": True})))
                    status = desktop("Apply", request)
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
                    # Original renderer is hidden; the background holds a visible clone.
                    hidden = evaluate("global.get_window_actors().filter(a => a.meta_window.get_title()?.startsWith('MotionWallRenderer:')).every(a => !a.visible)")
                    assert hidden, "Renderer was visible as an ordinary window"
                    tabs = evaluate("global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null).map(w => w.get_title())")
                    assert not any(title.startswith("MotionWallRenderer:") for title in tabs), tabs
                    if filename == "aurora.svg":
                        evaluate("Main.overview.hide(); true")
                        time.sleep(.5)
                        call("org.gnome.Shell.Screenshot", "Screenshot", GLib.Variant("(bbs)",
                             (False, False, str(output / "desktop.png"))), "/org/gnome/Shell/Screenshot")
                    status = desktop("Stop")
                    assert status["state"] == "stopped" and status["layers"] == 0 and status["surfaces"] == 0, status
                    wait_for(lambda: evaluate("global.get_window_actors().filter(a => a.meta_window.get_title()?.startsWith('MotionWallRenderer:')).length") == 0,
                             "renderer removed")
                    print(f"DESKTOP PASS: {filename} animates behind windows and restores original", flush=True)
                # Disable cleans exported interface and all hooks after use.
                call("org.gnome.Shell.Extensions", "DisableExtension", GLib.Variant("(s)", (UUID,)), "/org/gnome/Shell/Extensions")
                print("DESKTOP PASS: extension disabled cleanly", flush=True)
            finally:
                shell.terminate()
                try:
                    shell.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    shell.kill()
                    shell.wait()


if __name__ == "__main__":
    main()
