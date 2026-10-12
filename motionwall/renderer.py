"""Standalone Wayland surfaces. The GNOME bridge clones these into backgrounds."""

from __future__ import annotations

import json
import sys
from urllib.parse import urlencode

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, GLib, Gtk, WebKit  # noqa: E402

from .server import PreviewServer


class WallpaperRenderer(Gtk.Application):
    def __init__(self, library, identifier, options, monitors):
        super().__init__(application_id="io.github.willdeschepper.MotionWall.Renderer",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.library = library
        self.artwork = library.get(identifier)
        if self.artwork is None:
            raise ValueError("A animação aplicada não existe no catálogo.")
        self.options = options
        self.monitors = monitors
        self.server = None
        self.views = []
        self.loaded = set()
        self.probe_id = 0
        self.failed = False

    def emit_status(self, **values):
        print("MOTIONWALL " + json.dumps(values), flush=True)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.server = PreviewServer(self.library)

    def do_activate(self):
        if self.views:
            return
        for index, monitor in enumerate(self.monitors):
            window = Gtk.ApplicationWindow(application=self, title=f"MotionWallRenderer:{index}",
                                          decorated=False, default_width=monitor["width"],
                                          default_height=monitor["height"])
            window.set_focusable(False)
            manager = WebKit.UserContentManager()
            manager.register_script_message_handler("motionwall", None)
            manager.connect("script-message-received::motionwall", self.message, index)
            view = WebKit.WebView(user_content_manager=manager)
            view.get_settings().set_media_playback_requires_user_gesture(False)
            view.connect("permission-request", lambda _view, request: (request.deny(), True)[1])
            view.connect("context-menu", lambda *_args: True)
            view.connect("decide-policy", self.policy)
            view.connect("web-process-terminated", lambda *_args: self.fail("O player do fundo foi interrompido."))
            window.set_child(view)
            self.views.append(view)
            window.present()
            params = {"desktop": "1", "kind": self.artwork.kind,
                      "src": self.server.asset_url(self.artwork)}
            view.load_uri(self.server.url + "?" + urlencode(params))
        self.probe_id = GLib.timeout_add_seconds(1, self.probe)

    def policy(self, _view, decision, kind):
        if kind in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION or not uri.startswith(self.server.base_url + "/"):
                decision.ignore()
                return True
        return False

    def message(self, _manager, value, index):
        try:
            message = json.loads(value.to_string())
        except (ValueError, TypeError):
            return
        if message.get("type") == "ready":
            self.views[index].evaluate_javascript("MotionWall.configure(" + json.dumps(self.options) + ")",
                                                  -1, None, None, None, None, None)
        elif message.get("type") == "loaded":
            self.loaded.add(index)
            self.views[index].evaluate_javascript("MotionWall.configure(" + json.dumps(self.options) + ")",
                                                  -1, None, None, None, None, None)
            self.emit_status(event="loaded", monitor=index)
        elif message.get("type") == "error":
            self.fail(message.get("message", "Falha na reprodução do fundo."))

    def probe(self):
        for index in self.loaded:
            def done(view, result, *_args, index=index):
                try:
                    value = json.loads(view.evaluate_javascript_finish(result).to_string())
                    self.emit_status(event="frame", monitor=index,
                                     progress=value.get("rendered", value.get("time", 0)),
                                     playing=value.get("playing", False))
                except (GLib.Error, ValueError, TypeError):
                    pass
            self.views[index].evaluate_javascript("JSON.stringify(MotionWall.debug())", -1,
                                                  None, None, None, done, None)
        return GLib.SOURCE_CONTINUE

    def fail(self, message):
        self.failed = True
        self.emit_status(event="error", message=message)
        self.quit()

    def do_shutdown(self):
        if self.probe_id:
            GLib.source_remove(self.probe_id)
        if self.server:
            self.server.close()
        Gtk.Application.do_shutdown(self)


def run_renderer(library, identifier, options, monitors):
    if not isinstance(monitors, list) or not 1 <= len(monitors) <= 16:
        raise ValueError("Lista de monitores inválida.")
    for monitor in monitors:
        if not isinstance(monitor, dict) or any(not isinstance(monitor.get(k), int)
                                               or not 1 <= monitor[k] <= 16384 for k in ("width", "height")):
            raise ValueError("Dimensões de monitor inválidas.")
    app = WallpaperRenderer(library, identifier, options, monitors)
    result = app.run([sys.argv[0]])
    return 1 if app.failed else result
