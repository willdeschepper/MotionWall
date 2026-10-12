"""Session-bus client and explicit installation of the GNOME bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

UUID = "motionwall@willdeschepper.github.io"
BUS = "org.gnome.Shell"
OBJECT = "/io/github/willdeschepper/MotionWall"
INTERFACE = "io.github.willdeschepper.MotionWall.Desktop"
PROJECT = Path(__file__).resolve().parent.parent


def install_extension():
    source = PROJECT / "extension"
    if not (source / "extension.js").is_file():
        raise OSError("A extensão não foi encontrada. Execute a cópia clonada do projeto.")
    target = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "gnome-shell/extensions" / UUID
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("extension.js", "metadata.json"):
        shutil.copyfile(source / filename, target / filename)
    return target


class DesktopBridge:
    def __init__(self):
        from gi.repository import Gio
        self.Gio = Gio
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, method, arguments, callback):
        def done(connection, result):
            try:
                reply = connection.call_finish(result)
                status = json.loads(reply.unpack()[0])
            except Exception as error:
                callback(None, error)
                return
            callback(status, None)
        self.bus.call(BUS, OBJECT, INTERFACE, method, arguments, None,
                      self.Gio.DBusCallFlags.NONE, 5000, None, done)

    def apply(self, library, identifier, options, callback):
        from gi.repository import GLib
        self.call("Apply", GLib.Variant("(ssss)", (str(PROJECT), str(library.root),
                                                  identifier, json.dumps(options))), callback)

    def stop(self, callback):
        self.call("Stop", None, callback)

    def status(self, callback):
        self.call("Status", None, callback)
