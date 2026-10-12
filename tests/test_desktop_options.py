from pathlib import Path
import tempfile
import unittest

from motionwall.desktop import renderer_options, save_renderer_options
from motionwall.library import Library

ROOT = Path(__file__).resolve().parents[1]


class DesktopOptionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.library = Library(Path(self.temporary.name))
        self.rain, _ = self.library.import_file(ROOT / "motionwall/examples/chuva-alpha.svg")

    def test_apply_snapshot_survives_legacy_forwarding_and_later_preference_edits(self):
        save_renderer_options(self.library, self.rain.id,
                              {"background": "#c52a52", "transparent": False, "fps": 15})
        self.library.set_settings(background="#008844", transparent=True, fps=60)
        options = renderer_options(Library(self.library.root), self.rain.id,
                                   {"fit": "cover", "speed": 1, "loop": True})
        self.assertEqual(options["background"], "#c52a52")
        self.assertFalse(options["transparent"])
        self.assertEqual(options["fps"], 15)
        self.assertEqual(options["fit"], "cover")
        explicit = renderer_options(self.library, self.rain.id, {"background": "#ffffff", "transparent": True})
        self.assertEqual(explicit["background"], "#ffffff")
        self.assertTrue(explicit["transparent"])

    def test_snapshot_for_another_artwork_does_not_leak(self):
        save_renderer_options(self.library, self.rain.id, {"background": "#c52a52", "transparent": False})
        other, _ = self.library.import_file(ROOT / "motionwall/examples/pulse.gif")
        options = renderer_options(self.library, other.id, {})
        self.assertEqual(options["background"], "#111827")
        self.assertTrue(options["transparent"])


if __name__ == "__main__":
    unittest.main()
