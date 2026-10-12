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


def save_renderer_options(library, identifier, options):
    """Freeze an Apply request before starting the renderer, including new fields.

    Older loaded GNOME modules forward only fit/speed/loop. This local snapshot
    preserves background/alpha without reading subsequently edited preferences.
    """
    if library.get(identifier) is None:
        raise ValueError("A animação aplicada não existe no catálogo.")
    with library.lock:
        path = library.root / "desktop-options.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"artwork": identifier, "options": options}), encoding="utf-8")
        temporary.replace(path)


def renderer_options(library, identifier, forwarded):
    options = library.settings.copy()
    path = library.root / "desktop-options.json"
    try:
        if path.stat().st_size <= 65536:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(snapshot, dict) and snapshot.get("artwork") == identifier and isinstance(snapshot.get("options"), dict):
                options.update(snapshot["options"])
    except (OSError, ValueError):
        pass
    options.update(forwarded)
    return options


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
        try:
            save_renderer_options(library, identifier, options)
        except (OSError, ValueError) as error:
            callback(None, error)
            return
        self.call("Apply", GLib.Variant("(ssss)", (str(PROJECT), str(library.root),
                                                  identifier, json.dumps(options))), callback)

    def stop(self, callback):
        self.call("Stop", None, callback)

    def status(self, callback):
        self.call("Status", None, callback)
