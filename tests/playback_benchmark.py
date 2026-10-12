"""Measure the same Aurora at 3840x1080 in WebKitGTK, then compare baked video.

Run in an isolated Xvfb/dbus session. Reports process-tree CPU (100% = one CPU).
Requires --baseline-player pointing to the unmodified 0.2.2 player for comparison.
GPU acceleration is deliberately disabled by CI; hardware results may differ.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, GLib, Gtk, WebKit
from motionwall.library import Library
from motionwall import server


def cpu_tree():
    processes = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            processes[int(path.parent.name)] = (int(fields[1]), int(fields[11]) + int(fields[12]))
        except (OSError, ValueError, IndexError):
            pass
    included = {os.getpid()}
    while True:
        children = {pid for pid, (parent, _) in processes.items() if parent in included}
        updated = included | children
        if updated == included:
            return {pid: processes[pid][1] for pid in included if pid in processes}
        included = updated


class Benchmark(Gtk.Application):
    def __init__(self, library, baseline, output):
        super().__init__(application_id="io.github.willdeschepper.MotionWall.Benchmark",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.library, self.baseline, self.output = library, baseline, output
        self.results, self.index, self.failed = [], 0, False
        self.current_web = server.WEB_ROOT
        self.cases = [("svg-original", "aurora.svg", 60, True),
                      ("svg-30fps", "aurora.svg", 30, False),
                      ("svg-15fps", "aurora.svg", 15, False),
                      ("video-30fps", "aurora-video.mp4", 30, False)]

    def do_activate(self):
        self.window = Gtk.ApplicationWindow(application=self, default_width=3840, default_height=1080)
        self.transport = server.PreviewServer(self.library)
        self.window.present()
        GLib.timeout_add_seconds(65, self.timeout)
        self.next_case()

    def timeout(self):
        self.failed = True
        print("BENCHMARK FAILED: timeout", flush=True)
        self.quit()
        return GLib.SOURCE_REMOVE

    def debug(self, callback):
        def done(view, result, *_args):
            try:
                callback(json.loads(view.evaluate_javascript_finish(result).to_string()))
            except Exception as error:
                self.failed = True
                print(f"BENCHMARK FAILED: {error}", flush=True)
                self.quit()
        self.view.evaluate_javascript("JSON.stringify(MotionWall.debug())", -1, None, None, None, done, None)

    def next_case(self):
        if self.index == len(self.cases):
            self.output.parent.mkdir(exist_ok=True)
            self.output.write_text(json.dumps(self.results, indent=2))
            self.quit()
            return
        name, filename, fps, old = self.cases[self.index]
        server.WEB_ROOT = self.baseline if old else self.current_web
        self.artwork = next(a for a in self.library.entries if a.source_name == filename)
        manager = WebKit.UserContentManager()
        manager.register_script_message_handler("motionwall", None)
        manager.connect("script-message-received::motionwall", self.message)
        self.view = WebKit.WebView(user_content_manager=manager)
        self.view.get_settings().set_media_playback_requires_user_gesture(False)
        self.window.set_child(self.view)
        self.view.load_uri(self.transport.url)

    def message(self, _manager, value):
        message = json.loads(value.to_string())
        if message["type"] == "ready":
            options = {"kind": self.artwork.kind, "src": self.transport.asset_url(self.artwork),
                       "fit": "cover", "speed": 1, "loop": True, "fps": self.cases[self.index][2]}
            self.view.evaluate_javascript("MotionWall.open(" + json.dumps(options) + ")", -1,
                                          None, None, None, None, None)
        elif message["type"] == "loaded":
            GLib.timeout_add_seconds(2, self.start_sample)
        elif message["type"] == "error":
            self.failed = True
            print(f"BENCHMARK FAILED: {message}", flush=True)
            self.quit()

    def start_sample(self):
        def start(debug):
            self.before_debug = debug
            self.before = cpu_tree()
            self.started = time.monotonic()
            GLib.timeout_add_seconds(7, self.end_sample)
        self.debug(start)
        return GLib.SOURCE_REMOVE

    def end_sample(self):
        def end(debug):
            duration = time.monotonic() - self.started
            after = cpu_tree()
            ticks = sum(max(0, value - self.before.get(pid, value)) for pid, value in after.items())
            cpu = 100 * ticks / os.sysconf("SC_CLK_TCK") / duration
            assert debug["loaded"] and debug["playing"], debug
            assert debug["geometry"]["viewportCenterX"] >= 1900, debug
            frames = debug.get("rendered", 0) - self.before_debug.get("rendered", 0)
            actual_fps = frames / duration if "rendered" in debug else None
            if self.cases[self.index][0] in {"svg-30fps", "svg-15fps"}:
                target = self.cases[self.index][2]
                assert target * .65 < actual_fps < target + 3, actual_fps
                delta = debug["time"] - self.before_debug["time"]
                assert abs(delta - duration) < .5, (delta, duration)
            else:
                assert frames > 0 or debug.get("time") != self.before_debug.get("time"), debug
            result = {"case": self.cases[self.index][0], "cpu_percent": round(cpu, 2),
                      "observed_fps": round(actual_fps, 2) if actual_fps is not None else None,
                      "seconds": round(duration, 2), "viewport": "3840x1080", "software_rendering": True}
            self.results.append(result)
            print("BENCHMARK " + json.dumps(result), flush=True)
            self.view.evaluate_javascript("MotionWall.clear()", -1, None, None, None, None, None)
            self.window.set_child(None)
            self.index += 1
            GLib.timeout_add(500, lambda: (self.next_case(), GLib.SOURCE_REMOVE)[1])
        self.debug(end)
        return GLib.SOURCE_REMOVE

    def do_shutdown(self):
        self.transport.close()
        server.WEB_ROOT = self.current_web
        Gtk.Application.do_shutdown(self)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-player", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="motionwall-benchmark-") as temporary:
        temporary = Path(temporary)
        library = Library(temporary / "library")
        for name in ("aurora.svg", "aurora-video.mp4"):
            library.import_file(ROOT / "motionwall/examples" / name)
        baseline = temporary / "web"
        shutil.copytree(server.WEB_ROOT, baseline)
        shutil.copyfile(args.baseline_player, baseline / "player.js")
        app = Benchmark(library, baseline, ROOT / "smoke-output/playback-benchmark.json")
        result = app.run([sys.argv[0]])
        return 1 if app.failed else result


if __name__ == "__main__":
    raise SystemExit(main())
