"""Launch the installed app through its desktop entry with the checkout hidden.

Run after apt installs the generated .deb, inside an isolated Xvfb/dbus session.
All user data/config/cache and the extension copy go to a temporary directory.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.willdeschepper.MotionWall"
OBJECT = "/io/github/willdeschepper/MotionWall"
UUID = "motionwall@willdeschepper.github.io"


def wait_for(function, description, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = function()
            if value:
                return value
        except GLib.Error:
            pass
        time.sleep(.1)
    raise AssertionError(f"Timed out: {description}")


def main():
    with tempfile.TemporaryDirectory(prefix="motionwall-installed-") as directory:
        directory = Path(directory)
        for name, folder in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache")):
            (directory / folder).mkdir()
            os.environ[name] = str(directory / folder)
        os.chdir(directory)
        hidden = ROOT.with_name(ROOT.name + ".installed-test-hidden")
        assert not hidden.exists(), hidden
        ROOT.rename(hidden)
        bus = None
        try:
            assert subprocess.check_output(["/usr/bin/motionwall", "--version"], text=True).strip() == "0.2.5"
            subprocess.run(["/usr/bin/motionwall", "--doctor"], check=True)
            subprocess.run(["/usr/bin/motionwall", "--install-extension"], check=True)
            extension = directory / "data/gnome-shell/extensions" / UUID
            assert (extension / "extension.js").read_bytes() == Path("/opt/motionwall/extension/extension.js").read_bytes()
            subprocess.run(["/usr/bin/motionwall", "--import", "/opt/motionwall/motionwall/examples/orbit.json"], check=True)
            app = Gio.DesktopAppInfo.new(APP_ID + ".desktop")
            assert app and app.get_name() == "MotionWall", "App not registered in desktop database"
            assert app.get_executable() == "/usr/bin/motionwall", app.get_executable()
            assert app.get_icon().to_string() == APP_ID, app.get_icon()
            assert APP_ID + ".desktop" in {item.get_id() for item in Gio.AppInfo.get_all()}, "App absent from application list"
            Gtk.init()
            assert Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).has_icon(APP_ID), "Installed icon not discoverable"
            context = Gio.AppLaunchContext()
            for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
                context.setenv(name, os.environ[name])
            assert app.launch([], context), "Desktop entry launch failed"
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            def call(destination, path, interface, method, args=None):
                return bus.call_sync(destination, path, interface, method, args, None,
                                     Gio.DBusCallFlags.NONE, 3000, None).unpack()
            pid = wait_for(lambda: call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                           "org.freedesktop.DBus", "GetConnectionUnixProcessID", GLib.Variant("(s)", (APP_ID,)))[0], "installed app registration")
            wait_for(lambda: "quit" in call(APP_ID, OBJECT, "org.gtk.Actions", "List")[0], "installed GTK app startup")
            command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
            assert b"/usr/bin/motionwall" in command, command
            assert not any(str(hidden).encode() in part or str(ROOT).encode() in part for part in command), command
            call(APP_ID, OBJECT, "org.gtk.Actions", "Activate", GLib.Variant("(sava{sv})", ("quit", [], {})))
            wait_for(lambda: not call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                            "org.freedesktop.DBus", "NameHasOwner", GLib.Variant("(s)", (APP_ID,)))[0], "installed app closes cleanly")
            print("INSTALLED PASS: desktop entry, icon, GUI launch, CLI and extension work with source checkout hidden", flush=True)
        finally:
            if bus:
                try:
                    bus.call_sync(APP_ID, OBJECT, "org.gtk.Actions", "Activate",
                                  GLib.Variant("(sava{sv})", ("quit", [], {})), None,
                                  Gio.DBusCallFlags.NONE, 1000, None)
                except GLib.Error:
                    pass
            hidden.rename(ROOT)
            os.chdir(ROOT)


if __name__ == "__main__":
    main()
