from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from motionwall.library import ImportFailure, Library, validate_lottie

EXAMPLES = Path(__file__).resolve().parents[1] / "motionwall/examples"


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.library = Library(self.root / "catalogue")

    def tearDown(self):
        self.temporary.cleanup()

    def package(self, version="2", members=None, initial=None):
        path = self.root / "sample.lottie"
        manifest = {"version": version, "animations": [{"id": "first"}, {"id": "second"}]}
        if initial:
            if version == "2":
                manifest["initial"] = {"animation": initial}
            else:
                manifest["activeAnimationId"] = initial
        directory = "a" if version == "2" else "animations"
        data = json.loads((EXAMPLES / "orbit.json").read_text())
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr(f"{directory}/first.json", json.dumps(data))
            data["nm"] = "Second animation"
            archive.writestr(f"{directory}/second.json", json.dumps(data))
            for name, content in (members or {}).items():
                archive.writestr(name, content)
        return path

    def test_copies_source_and_catalogue_survives_restart(self):
        source = self.root / "Minha aurora.svg"
        source.write_bytes((EXAMPLES / "aurora.svg").read_bytes())
        artwork, new = self.library.import_file(source)
        source.unlink()
        restarted = Library(self.library.root)
        self.assertTrue(new)
        self.assertEqual(restarted.entries, [artwork])
        self.assertEqual((artwork.width, artwork.height), (1920, 540))
        self.assertTrue((restarted.asset_root / artwork.id / artwork.filename).is_file())

    def test_duplicate_does_not_create_another_copy(self):
        first, _ = self.library.import_file(EXAMPLES / "pulse.gif")
        second, new = self.library.import_file(EXAMPLES / "pulse.gif")
        self.assertFalse(new)
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.library.asset_root.iterdir())), 1)

    def test_json_must_be_a_real_lottie_animation(self):
        source = self.root / "plain.json"
        for data in ({"hello": "world"}, {"layers": []}, {"layers": [], "w": float("nan")}):
            source.write_text(json.dumps(data))
            with self.assertRaises(ImportFailure):
                self.library.import_file(source)
        self.assertEqual(list(self.library.asset_root.iterdir()), [])

    def test_lottie_copies_adjacent_images_and_detects_changed_images(self):
        source = self.root / "with-image.json"
        data = json.loads((EXAMPLES / "orbit.json").read_text())
        data["assets"] = [{"id": "image", "w": 1, "h": 1, "u": "images/", "p": "local.gif"}]
        source.write_text(json.dumps(data))
        images = self.root / "images"
        images.mkdir()
        (images / "local.gif").write_bytes((EXAMPLES / "pulse.gif").read_bytes())
        first, _ = self.library.import_file(source)
        duplicate, new = self.library.import_file(source)
        self.assertFalse(new)
        self.assertEqual(first.id, duplicate.id)
        (images / "local.gif").write_bytes(b"another image")
        changed, new = self.library.import_file(source)
        self.assertTrue(new)
        self.assertNotEqual(first.id, changed.id)
        imported = json.loads((self.library.asset_root / first.id / first.filename).read_text())
        self.assertEqual(imported["assets"][0]["u"], "")
        self.assertTrue((self.library.asset_root / first.id / imported["assets"][0]["p"]).is_file())

    def test_external_assets_and_javascript_expressions_are_rejected(self):
        data = json.loads((EXAMPLES / "orbit.json").read_text())
        data["assets"] = [{"p": "https://example.com/image.png"}]
        source = self.root / "remote.json"
        source.write_text(json.dumps(data))
        with self.assertRaises(ImportFailure):
            self.library.import_file(source)
        data["assets"] = []
        data["layers"][0]["ks"]["r"]["x"] = "alert('expression')"
        with self.assertRaisesRegex(ImportFailure, "Expressões"):
            validate_lottie(data)

    def test_dotlottie_v1_v2_and_initial_animation(self):
        for version in ("1", "2"):
            with self.subTest(version=version):
                artwork, _ = self.library.import_file(self.package(version, initial="second"))
                data = json.loads((self.library.asset_root / artwork.id / artwork.filename).read_text())
                self.assertEqual(data["nm"], "Second animation")
                self.assertEqual(artwork.kind, "dotlottie")

    def test_dotlottie_bundled_images_are_copied(self):
        data = json.loads((EXAMPLES / "orbit.json").read_text())
        data["assets"] = [{"id": "image", "u": "../i/", "p": "local.gif"}]
        package = self.package(members={"a/first.json": json.dumps(data), "i/local.gif": (EXAMPLES / "pulse.gif").read_bytes()})
        # Do not write a duplicate ZIP member; build a valid package separately.
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"version": "2", "animations": [{"id": "first"}]}))
            archive.writestr("a/first.json", json.dumps(data))
            archive.writestr("i/local.gif", (EXAMPLES / "pulse.gif").read_bytes())
        artwork, _ = self.library.import_file(package)
        copied = json.loads((self.library.asset_root / artwork.id / artwork.filename).read_text())
        self.assertTrue((self.library.asset_root / artwork.id / copied["assets"][0]["p"]).is_file())

    def test_zip_traversal_is_rejected_before_writing_outside_catalogue(self):
        package = self.package(members={"../../escaped.txt": "No"})
        with self.assertRaises(ImportFailure):
            self.library.import_file(package)
        self.assertFalse((self.library.root / "escaped.txt").exists())
        self.assertEqual(list(self.library.asset_root.iterdir()), [])

    def test_zip_symlinks_and_oversized_packages_are_rejected(self):
        package = self.package()
        with zipfile.ZipFile(package, "a") as archive:
            link = zipfile.ZipInfo("i/symlink.png")
            link.create_system = 3
            link.external_attr = (0o120777 << 16)
            archive.writestr(link, "/etc/passwd")
        with self.assertRaises(ImportFailure):
            self.library.import_file(package)
        package = self.package()
        with patch("motionwall.library.MAX_UNPACKED", 10):
            with self.assertRaises(ImportFailure):
                self.library.import_file(package)

    def test_svg_scripts_events_and_foreignobjects_are_rejected(self):
        source = self.root / "script.svg"
        for content in ("<script>alert(1)</script>", '<rect onclick="alert(1)"/>', "<foreignObject/>", '<image href="file:///etc/passwd"/>', '<set attributeName="href" to="https://example.com"/>'):
            source.write_text(f'<svg xmlns="http://www.w3.org/2000/svg">{content}</svg>')
            with self.assertRaises(ImportFailure):
                self.library.import_file(source)

    def test_invalid_media_signatures_are_rejected(self):
        for suffix in ("gif", "mp4", "webm"):
            source = self.root / f"invalid.{suffix}"
            source.write_bytes(b"This is not an animation")
            with self.assertRaises(ImportFailure):
                self.library.import_file(source)

    def test_failed_catalogue_write_rolls_back_import_and_remove(self):
        with patch.object(self.library, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(ImportFailure):
                self.library.import_file(EXAMPLES / "aurora.svg")
        self.assertEqual(self.library.entries, [])
        self.assertEqual(list(self.library.asset_root.iterdir()), [])
        artwork, _ = self.library.import_file(EXAMPLES / "aurora.svg")
        with patch.object(self.library, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.library.remove(artwork.id)
        self.assertEqual(self.library.entries, [artwork])
        self.assertTrue((self.library.asset_root / artwork.id / artwork.filename).exists())

    def test_removal_preserves_original_and_persists(self):
        artwork, _ = self.library.import_file(EXAMPLES / "aurora.svg")
        self.library.remove(artwork.id)
        self.assertTrue((EXAMPLES / "aurora.svg").exists())
        self.assertEqual(Library(self.library.root).entries, [])

    def test_corrupt_catalogue_is_preserved(self):
        self.library.index.write_text('{"broken": true}')
        with self.assertRaises(ImportFailure):
            Library(self.library.root)
        self.assertEqual(self.library.index.read_text(), '{"broken": true}')

    def test_preferences_are_persisted(self):
        self.library.set_settings(fit="cover", speed=1.5, loop=False)
        restored = Library(self.library.root)
        self.assertEqual(restored.settings["fit"], "cover")
        self.assertEqual(restored.settings["speed"], 1.5)
        self.assertFalse(restored.settings["loop"])


if __name__ == "__main__":
    unittest.main()
