// SPDX-License-Identifier: MIT
// Only trusted renderer surfaces are cloned; animations run outside the Shell.
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import {Extension, InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import * as Workspace from 'resource:///org/gnome/shell/ui/workspace.js';
import * as WorkspaceThumbnail from 'resource:///org/gnome/shell/ui/workspaceThumbnail.js';

const XML = `<node><interface name="io.github.willdeschepper.MotionWall.Desktop">
<method name="Apply"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
<method name="Stop"><arg type="s" direction="out"/></method>
<method name="Status"><arg type="s" direction="out"/></method>
</interface></node>`;

export default class MotionWallDesktop extends Extension {
    enable() {
        this._layers = new Map();
        this._surfaces = new Map();
        this._signals = [];
        this._injections = new InjectionManager();
        this._state = 'stopped';
        this._error = '';
        this._generation = 0;
        this._connect(global.window_manager, 'map', (_wm, actor) => this._consider(actor));
        this._connect(Main.layoutManager, 'monitors-changed', () => this._monitorChange());
        this._connect(global.display, 'notify::focus-window', () => {
            const focused = global.display.focus_window;
            if (!this._process)
                return;
            if (!this._owns(focused)) {
                if (focused) this._previousFocus = focused;
            } else {
                this._returnFocus();
            }
        });
        this._connect(Main.sessionMode, 'updated', () => {
            if (Main.sessionMode.isLocked)
                this.Stop();
        });

        const owner = this;
        this._injections.overrideMethod(Background.BackgroundManager.prototype, '_createBackgroundActor', original => function (...args) {
            const actor = original.apply(this, args);
            owner._attach(actor, this);
            return actor;
        });
        for (const type of [Workspace.Workspace, WorkspaceThumbnail.WorkspaceThumbnail]) {
            if (typeof type.prototype._isOverviewWindow !== 'function')
                continue;
            this._injections.overrideMethod(type.prototype, '_isOverviewWindow', original => function (window, ...args) {
                return owner._owns(window) ? false : original.call(this, window, ...args);
            });
        }
        this._injections.overrideMethod(Meta.Display.prototype, 'get_tab_list', original => function (...args) {
            return original.apply(this, args).filter(window => !owner._owns(window));
        });
        this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._dbus.export(Gio.DBus.session, '/io/github/willdeschepper/MotionWall');
    }

    _connect(object, signal, callback) {
        this._signals.push([object, object.connect(signal, callback)]);
    }

    _owns(value) {
        // Workspace receives Meta.Window, while WorkspaceThumbnail receives
        // Meta.WindowActor. Never pass an actor to Mutter's owns_window().
        const window = value instanceof Meta.WindowActor ? value.meta_window : value;
        return Boolean(this._client && window instanceof Meta.Window && this._client.owns_window(window));
    }

    _returnFocus() {
        const previous = this._previousFocus;
        // activate() can switch workspaces and dismiss desktop/overview states.
        // Focus only a live window on the workspace the user has chosen.
        if (!previous?.get_compositor_private() || Main.overview.visible)
            return;
        const current = global.workspace_manager.get_active_workspace();
        if (previous.is_on_all_workspaces() || previous.get_workspace() === current)
            previous.focus(global.get_current_time());
    }

    Status() {
        return JSON.stringify({state: this._state, error: this._error,
            artwork: this._request?.id ?? null, surfaces: this._surfaces.size,
            layers: [...this._layers.values()].filter(layer => layer.clone).length,
            progress: this._progress ?? {}, geometry: this._geometry ?? {}, renderSize: this._monitors ?? []});
    }

    Apply(root, data, id, optionsJSON) {
        // GNOME 50 is Wayland-only and removed is_wayland_compositor().
        if (typeof Meta.is_wayland_compositor === 'function' && !Meta.is_wayland_compositor())
            throw new Error('A integração do MotionWall requer GNOME Wayland.');
        if (!GLib.path_is_absolute(root) || !GLib.path_is_absolute(data) || !/^[0-9a-f]{32}$/.test(id))
            throw new Error('Pedido de wallpaper inválido.');
        if (!Gio.File.new_for_path(GLib.build_filenamev([root, 'motionwall', 'renderer.py'])).query_exists(null))
            throw new Error('A pasta do MotionWall não contém o renderer.');
        const values = JSON.parse(optionsJSON);
        const options = {fit: ['contain', 'cover', 'stretch', 'native'].includes(values.fit) ? values.fit : 'cover',
            speed: Number.isFinite(values.speed) && values.speed >= 0.25 && values.speed <= 3 ? values.speed : 1,
            loop: values.loop !== false,
            fps: [15, 30, 60].includes(values.fps) ? values.fps : 30,
            transparent: values.transparent !== false,
            background: typeof values.background === 'string' && /^#[0-9a-f]{6}$/i.test(values.background)
                ? values.background.toLowerCase() : '#111827',
            quality: values.quality === 'native' ? 'native' : 'balanced'};
        this.Stop();
        this._request = {root, data, id, options};
        this._start();
        return this.Status();
    }

    _start() {
        const {root, data, id, options} = this._request;
        const monitors = Main.layoutManager.monitors.map(({width, height}, index) => {
            // Rasterize a bounded surface, then let the background clone scale it.
            // Original pixel dimensions must retain the full-resolution surface.
            const scale = global.display.get_monitor_scale(index);
            const ratio = options.quality === 'native' || options.fit === 'native' ? 1
                : Math.min(1, 1920 / (width * scale), 1080 / (height * scale));
            return {width: Math.max(1, Math.round(width * ratio)),
                height: Math.max(1, Math.round(height * ratio))};
        });
        if (!monitors.length || Main.sessionMode.isLocked)
            throw new Error('Nenhum monitor disponível para aplicar o fundo.');
        this._generation++;
        const generation = this._generation;
        this._state = 'starting';
        this._error = '';
        this._progress = {};
        this._geometry = {};
        this._monitors = monitors;
        this._previousFocus = global.display.focus_window;
        const launcher = new Gio.SubprocessLauncher({flags: Gio.SubprocessFlags.STDOUT_PIPE});
        launcher.set_cwd(root);
        launcher.setenv('GDK_BACKEND', 'wayland', true);
        const argv = ['/usr/bin/python3', '-m', 'motionwall', '--renderer', id,
            '--data-dir', data, '--renderer-options', JSON.stringify(options),
            '--renderer-monitors', JSON.stringify(monitors)];
        try {
            // Mutter 50 replaced new()/spawnv() with new_subprocess().
            if (typeof Meta.WaylandClient.new_subprocess === 'function') {
                this._client = Meta.WaylandClient.new_subprocess(global.context, launcher, argv);
                this._process = this._client.get_subprocess();
            } else {
                this._client = Meta.WaylandClient.new(global.context, launcher);
                this._process = this._client.spawnv(global.display, argv);
            }
            launcher.close();
            this._cancel = new Gio.Cancellable();
            this._read(Gio.DataInputStream.new(this._process.get_stdout_pipe()), generation);
            const process = this._process;
            process.wait_async(null, (object, result) => {
                try { object.wait_finish(result); } catch (error) { console.error(error); }
                if (generation !== this._generation)
                    return;
                this._fail('O player do fundo foi encerrado. Aplique a animação novamente.');
            });
            this._deadline = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 20000, () => {
                this._deadline = 0;
                if (generation === this._generation && this._state !== 'active')
                    this._fail('O fundo não começou a animar. Verifique as dependências do WebKit.');
                return GLib.SOURCE_REMOVE;
            });
        } catch (error) {
            launcher.close();
            this._fail(error.message);
            throw error;
        }
    }

    _read(stream, generation) {
        stream.read_line_async(GLib.PRIORITY_DEFAULT, this._cancel, (object, result) => {
            if (generation !== this._generation)
                return;
            try {
                const [line] = object.read_line_finish_utf8(result);
                if (line === null)
                    return;
                if (line.startsWith('MOTIONWALL ')) {
                    const message = JSON.parse(line.slice(11));
                    if (message.event === 'error') {
                        this._fail(message.message);
                        return;
                    }
                    if (message.event === 'frame') {
                        const previous = this._progress[message.monitor];
                        this._progress[message.monitor] = message.progress;
                        if (message.geometry) this._geometry[message.monitor] = message.geometry;
                        if (this._surfaces.size === this._monitors.length &&
                            previous !== undefined && message.progress !== previous)
                            this._state = 'active';
                    }
                }
            } catch (error) {
                if (!this._cancel?.is_cancelled())
                    console.error(error);
                return;
            }
            this._read(stream, generation);
        });
    }

    _consider(actor) {
        const window = actor.meta_window;
        if (!this._owns(window))
            return;
        const title = window.get_title() ?? '';
        const match = /^MotionWallRenderer:(\d+)$/.exec(title);
        if (!match)
            return;
        const index = Number(match[1]);
        const monitor = Main.layoutManager.monitors[index];
        if (!monitor || this._surfaces.has(index))
            return;
        const size = this._monitors[index];
        window.move_resize_frame(false, monitor.x, monitor.y, size.width, size.height);
        window.stick();
        window.lower();
        if (typeof this._client.hide_from_window_list === 'function')
            this._client.hide_from_window_list(window);
        const hideId = actor.connect('notify::visible', () => {
            if (actor.visible && this._owns(window))
                actor.hide();
        });
        const destroyId = actor.connect('destroy', () => {
            this._surfaces.delete(index);
            for (const layer of this._layers.values()) {
                if (layer.index === index) this._releaseClone(layer);
            }
        });
        this._surfaces.set(index, {actor, hideId, destroyId});
        for (const manager of Main.layoutManager._bgManagers ?? [])
            this._attach(manager.backgroundActor, manager);
        for (const layer of this._layers.values()) {
            if (layer.index === index) this._clone(layer);
        }
        actor.hide();
        if (this._owns(global.display.focus_window))
            this._returnFocus();
    }

    _attach(background, manager) {
        if (!background || this._layers.has(background) || !this._process)
            return;
        // Overview and workspace thumbnails have their own allocation rules.
        // A full-size renderer clone must never affect those actors' size hints.
        if (!(Main.layoutManager._bgManagers ?? []).includes(manager))
            return;
        const index = background.monitor;
        if (!Main.layoutManager.monitors[index])
            return;
        const overlay = new Clutter.Actor({reactive: false, clip_to_allocation: true});
        background.add_child(overlay);
        const layer = {background, overlay, index, clone: null};
        layer.allocationId = background.connect('notify::allocation', () => this._size(layer));
        layer.destroyId = background.connect('destroy', () => {
            this._releaseClone(layer);
            this._layers.delete(background);
        });
        this._layers.set(background, layer);
        this._clone(layer);
    }

    _clone(layer) {
        if (layer.clone)
            return;
        const source = this._surfaces.get(layer.index)?.actor;
        if (!source)
            return;
        layer.clone = new Clutter.Clone({source, reactive: false});
        layer.overlay.add_child(layer.clone);
        layer.sourceAllocationId = source.connect('notify::allocation', () => this._size(layer));
        layer.source = source;
        this._size(layer);
    }

    _size(layer) {
        const {background, overlay, clone, source} = layer;
        const width = background.width, height = background.height;
        if (!(width > 0 && height > 0))
            return;
        overlay.set_size(width, height);
        if (clone && source.width > 0 && source.height > 0) {
            clone.set_size(source.width, source.height);
            clone.set_scale(width / source.width, height / source.height);
        }
    }

    _releaseClone(layer) {
        if (layer.sourceAllocationId) {
            layer.source.disconnect(layer.sourceAllocationId);
            layer.sourceAllocationId = 0;
        }
        if (layer.clone) {
            layer.clone.set_source(null);
            layer.clone.destroy();
            layer.clone = null;
        }
        layer.source = null;
    }

    _monitorChange() {
        if (!this._request)
            return;
        // Avoid all geometry calls during monitor reconfiguration; stop first.
        const request = this._request;
        this.Stop();
        if (Main.layoutManager.monitors.length) {
            this._request = request;
            try { this._start(); } catch (error) { console.error(error); }
        }
    }

    _fail(message) {
        this.Stop();
        this._state = 'error';
        this._error = String(message);
    }

    Stop() {
        this._generation++;
        if (this._deadline) {
            GLib.source_remove(this._deadline);
            this._deadline = 0;
        }
        this._cancel?.cancel();
        this._cancel = null;
        for (const layer of this._layers.values()) {
            this._releaseClone(layer);
            layer.background.disconnect(layer.allocationId);
            layer.background.disconnect(layer.destroyId);
            layer.overlay.destroy();
        }
        this._layers.clear();
        for (const {actor, hideId, destroyId} of this._surfaces.values()) {
            actor.disconnect(hideId);
            actor.disconnect(destroyId);
        }
        this._surfaces.clear();
        this._process?.force_exit();
        this._process = this._client = this._request = null;
        this._previousFocus = null;
        this._progress = {};
        this._geometry = {};
        this._state = 'stopped';
        this._error = '';
        return this.Status();
    }

    disable() {
        this._dbus?.unexport();
        this._dbus = null;
        this.Stop();
        this._signals.forEach(([object, id]) => object.disconnect(id));
        this._signals = [];
        this._injections.clear();
        this._injections = null;
    }
}
