from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from motionwall.library import Library
from motionwall.server import PreviewServer

EXAMPLES = Path(__file__).resolve().parents[1] / "motionwall/examples"


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.library = Library(Path(self.temporary.name))
        self.artwork, _ = self.library.import_file(EXAMPLES / "pulse.gif")
        self.server = PreviewServer(self.library)
        self.asset = self.server.asset_url(self.artwork)

    def tearDown(self):
        self.server.close()
        self.temporary.cleanup()

    def test_serves_only_imported_assets_and_player(self):
        with urlopen(self.server.url) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        with urlopen(self.asset) as response:
            self.assertEqual(response.headers["Content-Type"], "image/gif")
            self.assertEqual(response.read(), (EXAMPLES / "pulse.gif").read_bytes())
        for path in ("/wrong-token/player/index.html", f"/{self.server.token}/library.json", f"/{self.server.token}/assets/unknown/file", f"/{self.server.token}/player/%2e%2e/%2e%2e/library.json"):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.server.base_url.split(f"/{self.server.token}")[0] + path)
            self.assertEqual(error.exception.code, 404)

    def test_video_byte_ranges_and_head(self):
        original = (EXAMPLES / "pulse.gif").read_bytes()
        for header, start, end in (("bytes=0-9", 0, 10), ("bytes=10-", 10, len(original)), ("bytes=-8", len(original) - 8, len(original))):
            with urlopen(Request(self.asset, headers={"Range": header})) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), original[start:end])
                self.assertEqual(response.headers["Content-Length"], str(end - start))
                self.assertEqual(response.headers["Content-Range"], f"bytes {start}-{end - 1}/{len(original)}")
        with urlopen(Request(self.asset, method="HEAD")) as response:
            self.assertEqual(response.read(), b"")
            self.assertEqual(int(response.headers["Content-Length"]), len(original))

    def test_invalid_ranges_fail_without_file_content(self):
        for header in ("bytes=999999-", "bytes=5-2", "bytes=-0", "bytes=", "bytes=0-1,5-6"):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.asset, headers={"Range": header}))
            self.assertEqual(error.exception.code, 416)

    def test_symlink_cannot_serve_unrelated_file(self):
        external = self.library.root / "private.txt"
        external.write_text("private")
        link = self.library.asset_root / self.artwork.id / "leak.txt"
        link.symlink_to(external)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.asset.rsplit("/", 1)[0] + "/leak.txt")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
