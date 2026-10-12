"""Native GTK4 catalogue; WebKit owns rendering in its web process."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, WebKit  # noqa: E402

from . import __version__
from .library import KINDS, Library
from .server import PreviewServer

EXAMPLES = Path(__file__).parent / "examples"
FORMAT_LABELS = {"gif": "GIF", "svg": "SVG animado", "lottie": "Lottie JSON",
                 "dotlottie": "dotLottie", "video": "Vídeo"}
ICONS = {"gif": "image-x-generic-symbolic", "svg": "applications-graphics-symbolic",
         "lottie": "media-playlist-repeat-symbolic", "dotlottie": "package-x-generic-symbolic",
         "video": "video-x-generic-symbolic"}


class MotionWallWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MotionWall", default_width=1120, default_height=760)
        self.app = app
        self.library = app.library
        self.selected = None
        self.ready = False
        self.playing = False
        self.save_timeout = None
        self.wanted = self.library.settings.get("selected")
        self._building = True

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="MotionWall", subtitle="Sua biblioteca de animações"))
        self.import_button = Gtk.Button(label="Importar", icon_name="document-open-symbolic")
        self.import_button.add_css_class("suggested-action")
        self.import_button.connect("clicked", self._choose_files)
        header.pack_start(self.import_button)
        menu = Gio.Menu()
        menu.append("Importar exemplos", "app.examples")
        menu.append("Sobre o MotionWall", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=280)
        sidebar.set_margin_top(16)
        sidebar.set_margin_bottom(16)
        sidebar.set_margin_start(12)
        sidebar.set_margin_end(12)
        label = Gtk.Label(label="Biblioteca", xalign=0)
        label.add_css_class("title-3")
        sidebar.append(label)
        self.search = Gtk.SearchEntry(placeholder_text="Buscar animação")
        self.search.connect("search-changed", lambda _entry: self.listbox.invalidate_filter())
        sidebar.append(self.search)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_filter_func(lambda row: self.search.get_text().casefold() in row.artwork.title.casefold())
        self.listbox.connect("row-selected", self._select)
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scrolled.set_child(self.listbox)
        sidebar.append(scrolled)
        self.count = Gtk.Label(xalign=0)
        self.count.add_css_class("dim-label")
        sidebar.append(self.count)
        self.remove_button = Gtk.Button(label="Remover da biblioteca", sensitive=False)
        self.remove_button.connect("clicked", self._confirm_remove)
        sidebar.append(self.remove_button)

        manager = WebKit.UserContentManager()
        manager.connect("script-message-received::motionwall", self._message)
        manager.register_script_message_handler("motionwall", None)
        self.view = WebKit.WebView(user_content_manager=manager, hexpand=True, vexpand=True)
        settings = self.view.get_settings()
        settings.set_media_playback_requires_user_gesture(False)
        settings.set_enable_developer_extras(bool(os.environ.get("MOTIONWALL_DEBUG")))
        self.view.connect("decide-policy", self._policy)
        self.view.connect("permission-request", self._deny_permission)
        self.view.connect("web-process-terminated", self._terminated)
        if not os.environ.get("MOTIONWALL_DEBUG"):
            self.view.connect("context-menu", lambda *_args: True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True, vexpand=True)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(20)
        content.set_margin_end(20)
        self.art_title = Gtk.Label(label="Escolha uma animação", xalign=0, ellipsize=3)
        self.art_title.add_css_class("title-2")
        self.art_detail = Gtk.Label(label="GIF · SVG · Lottie · .lottie · MP4 · WebM", xalign=0)
        self.art_detail.add_css_class("dim-label")
        content.append(self.art_title)
        content.append(self.art_detail)
        self.aspect = Gtk.AspectFrame(xalign=.5, yalign=.5, ratio=16 / 9, obey_child=False, vexpand=True)
        self.aspect.set_child(self.view)
        content.append(self.aspect)

        playback = Gtk.Box(spacing=8)
        self.play_button = Gtk.Button(icon_name="media-playback-start-symbolic", sensitive=False, tooltip_text="Reproduzir / pausar")
        self.play_button.connect("clicked", self._toggle_play)
        self.restart_button = Gtk.Button(icon_name="media-skip-backward-symbolic", sensitive=False, tooltip_text="Reiniciar animação")
        self.restart_button.connect("clicked", lambda _button: self.command("restart"))
        playback.append(self.play_button)
        playback.append(self.restart_button)
        self.status = Gtk.Label(label="Prévia em janela", xalign=0, hexpand=True, ellipsize=3)
        self.status.add_css_class("dim-label")
        playback.append(self.status)
        self.ratio = Gtk.DropDown.new_from_strings(["16:9", "32:9 · ultrawide", "4:3"])
        self.ratio.set_tooltip_text("Proporção da área de prévia")
        self.ratio.connect("notify::selected", self._change_ratio)
        playback.append(self.ratio)
        content.append(playback)

        options = Gtk.Box(spacing=12)
        options.append(Gtk.Label(label="Enquadramento"))
        self.fit = Gtk.DropDown.new_from_strings(["Ajustar", "Preencher", "Esticar"])
        self.fit.set_selected(["contain", "cover", "stretch"].index(self.library.settings["fit"]))
        self.fit.connect("notify::selected", self._options_changed)
        options.append(self.fit)
        options.append(Gtk.Label(label="Velocidade"))
        self.speed = Gtk.SpinButton.new_with_range(.25, 3, .25)
        self.speed.set_digits(2)
        self.speed.set_value(self.library.settings["speed"])
        self.speed.set_tooltip_text("1,00 = velocidade original")
        self.speed.connect("value-changed", self._options_changed)
        options.append(self.speed)
        options.append(Gtk.Label(label="Loop", hexpand=True, halign=Gtk.Align.END))
        self.loop = Gtk.Switch(active=self.library.settings["loop"], valign=Gtk.Align.CENTER)
        self.loop.connect("notify::active", self._options_changed)
        options.append(self.loop)
        content.append(options)
        footer = Gtk.Label(label="Prévia local. A integração com o papel de parede será adicionada na próxima etapa.", xalign=0, wrap=True)
        footer.add_css_class("dim-label")
        footer.add_css_class("caption")
        content.append(footer)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(sidebar)
        paned.set_end_child(content)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)
        paned.set_position(300)
        self.overlay = Adw.ToastOverlay(child=paned)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.overlay)
        self.set_content(toolbar)
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect("drop", self._drop)
        self.add_controller(target)
        self.connect("map", lambda _window: self.command("setSuspended", False))
        self.connect("unmap", lambda _window: self.command("setSuspended", True))
        self.connect("close-request", self._close)
        self._building = False
        self.refresh()
        self.view.load_uri(self.app.server.url)

    def command(self, method, value=None, callback=None):
        if not self.ready:
            return
        argument = "" if value is None else json.dumps(value, ensure_ascii=True)
        script = f"MotionWall.{method}({argument})"
        self.view.evaluate_javascript(script, -1, None, None, None, callback, None)

    def _policy(self, _view, decision, decision_type):
        if decision_type in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION or not uri.startswith(self.app.server.base_url + "/"):
                decision.ignore()
                return True
        return False

    def _deny_permission(self, _view, request):
        request.deny()
        return True

    def _terminated(self, _view, _reason):
        self.ready = False
        self._enable_playback(False)
        self.status.set_label("O player foi interrompido. Reabra o MotionWall para reiniciá-lo.")
        if self.app.smoke:
            self.app.smoke_fail("WebKit web process terminated")

    def _message(self, _manager, value):
        try:
            message = json.loads(value.to_string())
        except (ValueError, TypeError):
            return
        event = message.get("type")
        if event == "ready":
            self.ready = True
            if self.selected:
                self._open_selected()
            if self.app.smoke and not self.selected:
                self.app.smoke_fail("No artwork selected")
        elif event == "loaded":
            self._enable_playback(True)
            self.loop.set_sensitive(message.get("capabilities", {}).get("loop", True))
            self.loop.set_tooltip_text("O SVG usa o loop definido no próprio arquivo." if message.get("kind") == "svg" else "Repetir continuamente")
            if self.app.smoke:
                GLib.timeout_add(650, self.app.smoke_check)
        elif event == "state":
            self.playing = message.get("playing", False)
            self.play_button.set_icon_name("media-playback-pause-symbolic" if self.playing else "media-playback-start-symbolic")
            self.status.set_label("Reproduzindo" if self.playing else "Finalizado" if message.get("ended") else "Pausado")
        elif event == "error":
            self._enable_playback(False)
            self.status.set_label(message.get("message", "Falha na reprodução"))
            if self.app.smoke:
                self.app.smoke_fail(message.get("message", "Player error"))

    def _enable_playback(self, enabled):
        self.play_button.set_sensitive(enabled)
        self.restart_button.set_sensitive(enabled)

    def _open_selected(self):
        if not self.selected:
            return
        self._enable_playback(False)
        self.status.set_label("Carregando…")
        self.command("open", {"kind": self.selected.kind, "src": self.app.server.asset_url(self.selected), **self.options()})

    def _select(self, _list, row):
        self.selected = row.artwork if row else None
        self.remove_button.set_sensitive(self.selected is not None)
        self._enable_playback(False)
        if self.selected:
            artwork = self.selected
            self.art_title.set_label(artwork.title)
            dimensions = f" · {artwork.width} × {artwork.height}" if artwork.width and artwork.height else ""
            self.art_detail.set_label(f"{FORMAT_LABELS[artwork.kind]}{dimensions} · {artwork.size / 1024**2:.2f} MiB")
            self.wanted = artwork.id
            self._open_selected()
        else:
            self.art_title.set_label("Escolha uma animação")
            self.art_detail.set_label("GIF · SVG · Lottie · .lottie · MP4 · WebM")
            self.command("clear")
            self.status.set_label("Prévia em janela")

    def refresh(self, selected_id=None):
        wanted = selected_id or self.wanted
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)
        first = selected = None
        for artwork in list(self.library.entries):
            row = Gtk.ListBoxRow()
            row.artwork = artwork
            box = Gtk.Box(spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
            box.append(Gtk.Image(icon_name=ICONS[artwork.kind], pixel_size=28))
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
            labels.append(Gtk.Label(label=artwork.title, xalign=0, ellipsize=3))
            detail = Gtk.Label(label=FORMAT_LABELS[artwork.kind], xalign=0)
            detail.add_css_class("dim-label")
            detail.add_css_class("caption")
            labels.append(detail)
            box.append(labels)
            row.set_child(box)
            self.listbox.append(row)
            first = first or row
            if artwork.id == wanted:
                selected = row
        self.count.set_label(f"{len(self.library.entries)} animações · arraste arquivos para importar")
        self.listbox.select_row(selected or first)

    def options(self):
        return {"fit": ["contain", "cover", "stretch"][self.fit.get_selected()],
                "speed": self.speed.get_value(), "loop": self.loop.get_active()}

    def _options_changed(self, *_args):
        if self._building:
            return
        self.command("configure", self.options())
        if self.save_timeout:
            GLib.source_remove(self.save_timeout)
        self.save_timeout = GLib.timeout_add(300, self._save_options)

    def _save_options(self):
        self.save_timeout = None
        try:
            self.library.set_settings(**self.options(), selected=self.selected.id if self.selected else None)
        except OSError as error:
            self.toast(f"Não foi possível salvar as opções: {error}")
        return GLib.SOURCE_REMOVE

    def _change_ratio(self, *_args):
        self.aspect.set_ratio([16 / 9, 32 / 9, 4 / 3][self.ratio.get_selected()])

    def _toggle_play(self, _button):
        self.command("pause" if self.playing else "play")

    def _choose_files(self, _button):
        dialog = Gtk.FileDialog(title="Importar animações")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        file_filter = Gtk.FileFilter(name="Animações e vídeos")
        for extension in KINDS:
            file_filter.add_pattern("*" + extension)
            file_filter.add_pattern("*" + extension.upper())
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.open_multiple(self, None, self._chosen)

    def _chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        self.import_files([Path(files.get_item(i).get_path()) for i in range(files.get_n_items()) if files.get_item(i).get_path()])

    def _drop(self, _target, files, _x, _y):
        paths = [Path(file.get_path()) for file in files.get_files() if file.get_path()]
        self.import_files(paths)
        return bool(paths)

    def import_files(self, paths):
        if not paths:
            return
        self.import_button.set_sensitive(False)
        self.toast("Importando arquivos…")
        def work():
            imported, errors = [], []
            for path in paths:
                try:
                    imported.append(self.library.import_file(path))
                except (ValueError, OSError) as error:
                    errors.append(f"{path.name}: {error}")
            return imported, errors
        future = self.app.executor.submit(work)
        future.add_done_callback(lambda done: GLib.idle_add(self._imports_finished, done))

    def _imports_finished(self, future):
        if self.app.closing:
            return GLib.SOURCE_REMOVE
        self.import_button.set_sensitive(True)
        imported, errors = future.result()
        if imported:
            self.refresh(imported[-1][0].id)
            self.toast(f"{sum(new for _, new in imported)} adicionadas · {sum(not new for _, new in imported)} já estavam na biblioteca")
        if errors:
            dialog = Adw.MessageDialog(transient_for=self, heading="Alguns arquivos não foram importados", body="\n\n".join(errors[:6]))
            dialog.add_response("close", "Fechar")
            dialog.present()
        return GLib.SOURCE_REMOVE

    def _confirm_remove(self, _button):
        if not self.selected:
            return
        identifier = self.selected.id
        dialog = Adw.MessageDialog(transient_for=self, heading=f"Remover {self.selected.title}?", body="A cópia importada será removida. Seu arquivo original será preservado.")
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("remove", "Remover")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        def respond(_dialog, response):
            if response == "remove":
                try:
                    self.command("clear")
                    self.library.remove(identifier)
                    self.refresh()
                except OSError as error:
                    self.toast(f"Não foi possível remover: {error}")
        dialog.connect("response", respond)
        dialog.present()

    def toast(self, message):
        self.overlay.add_toast(Adw.Toast(title=message))

    def _close(self, _window):
        self._save_options()
        self.command("clear")
        return False


class MotionWallApplication(Adw.Application):
    def __init__(self, library: Library, smoke=False):
        flags = Gio.ApplicationFlags.NON_UNIQUE if smoke else Gio.ApplicationFlags.DEFAULT_FLAGS
        super().__init__(application_id="io.github.willdeschepper.MotionWall", flags=flags)
        self.library = library
        self.server = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="motionwall-import")
        self.window = None
        self.closing = False
        self.smoke = smoke
        self.smoke_exit = 0
        self.smoke_index = 0
        self.smoke_before = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.server = PreviewServer(self.library)
        for name, callback in (("examples", self._examples), ("about", self._about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        if self.smoke:
            GLib.timeout_add_seconds(35, lambda: self.smoke_fail("Smoke test timed out"))

    def do_activate(self):
        if self.window is None:
            self.window = MotionWallWindow(self)
        self.window.present()

    def do_shutdown(self):
        self.closing = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        if self.server:
            self.server.close()
        Adw.Application.do_shutdown(self)

    def _examples(self, *_args):
        self.window.import_files(sorted(EXAMPLES.glob("*")))

    def _about(self, *_args):
        dialog = Adw.AboutWindow(transient_for=self.window, application_name="MotionWall",
                                 application_icon="io.github.willdeschepper.MotionWall",
                                 developer_name="Wiliam De Schepper", version=__version__,
                                 website="https://github.com/willdeschepper/MotionWall",
                                 license_type=Gtk.License.MIT_X11,
                                 comments="Biblioteca e prévia local de animações para GNOME.")
        dialog.present()

    def smoke_fail(self, message):
        print(f"SMOKE FAIL: {message}", file=sys.stderr, flush=True)
        self.smoke_exit = 1
        self.quit()
        return GLib.SOURCE_REMOVE

    def _debug(self, callback):
        def done(view, result, *_args):
            try:
                value = view.evaluate_javascript_finish(result)
                callback(json.loads(value.to_string()))
            except (GLib.Error, ValueError, TypeError) as error:
                self.smoke_fail(str(error))
        self.window.view.evaluate_javascript("JSON.stringify(MotionWall.debug())", -1, None, None, None, done, None)

    def smoke_check(self):
        def check(data):
            if not data.get("loaded") or not data.get("playing") or not (data.get("rendered", 0) > 0 or data.get("time", 0) > 0):
                self.smoke_fail(f"Renderer did not advance: {data}")
                return
            self.window.command("pause")
            GLib.timeout_add(150, self._smoke_paused)
        self._debug(check)
        return GLib.SOURCE_REMOVE

    def _smoke_paused(self):
        def capture(data):
            self.smoke_before = data
            GLib.timeout_add(250, self._smoke_compare)
        self._debug(capture)
        return GLib.SOURCE_REMOVE

    def _smoke_compare(self):
        def check(data):
            before = self.smoke_before
            if data.get("playing") or data.get("rendered") != before.get("rendered") or data.get("time") != before.get("time"):
                self.smoke_fail(f"Pause did not hold: {data}")
                return
            print(f"SMOKE PASS: {data['kind']} advanced and paused", flush=True)
            self.smoke_index += 1
            row = self.window.listbox.get_row_at_index(self.smoke_index)
            if row:
                self.window.listbox.select_row(row)
            else:
                self.quit()
        self._debug(check)
        return GLib.SOURCE_REMOVE
