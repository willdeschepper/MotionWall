"""Read-only loopback transport, limited to the player and imported files."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import quote, unquote, urlsplit

from .library import Artwork, Library

WEB_ROOT = Path(__file__).parent / "web"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
       "font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


class PreviewServer:
    def __init__(self, library: Library):
        self.library = library
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self._serve(False)

            def do_HEAD(self):
                self._serve(True)

            def _serve(self, head: bool):
                prefix = f"/{owner.token}/"
                path = unquote(urlsplit(self.path).path)
                if not path.startswith(prefix):
                    self.send_error(404)
                    return
                relative = path[len(prefix):]
                parts = relative.split("/")
                if any(p in {"", ".", ".."} or "\\" in p for p in parts):
                    self.send_error(404)
                    return
                if parts[0] == "player":
                    root = WEB_ROOT.resolve()
                    filename = Path(*parts[1:])
                elif len(parts) >= 3 and parts[0] == "assets" and owner.library.get(parts[1]):
                    root = (owner.library.asset_root / parts[1]).resolve()
                    filename = Path(*parts[2:])
                else:
                    self.send_error(404)
                    return
                target = (root / filename).resolve()
                if not target.is_relative_to(root) or not target.is_file():
                    self.send_error(404)
                    return
                try:
                    stream = target.open("rb")
                except OSError:
                    self.send_error(404)
                    return
                with stream:
                    size = target.stat().st_size
                    start, end = 0, size - 1
                    request_range = self.headers.get("Range")
                    if request_range:
                        match = re.fullmatch(r"bytes=(\d*)-(\d*)", request_range)
                        if not match or not any(match.groups()):
                            self._range_error(size)
                            return
                        first, last = match.groups()
                        if first:
                            start = int(first)
                            end = min(int(last), end) if last else end
                        else:
                            start = max(0, size - int(last))
                        if start > end or start >= size or not size or (not first and int(last) == 0):
                            self._range_error(size)
                            return
                    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    self.send_response(206 if request_range else 200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(end - start + 1))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Security-Policy", CSP)
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Cache-Control", "no-store")
                    if request_range:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    if head:
                        return
                    stream.seek(start)
                    remaining = end - start + 1
                    try:
                        while remaining:
                            chunk = stream.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def _range_error(self, size):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.http.server_port}/{self.token}"
        self.url = f"{self.base_url}/player/index.html"
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True, name="motionwall-preview")
        self.thread.start()

    def asset_url(self, artwork: Artwork) -> str:
        return f"{self.base_url}/assets/{artwork.id}/{quote(artwork.filename)}"

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
