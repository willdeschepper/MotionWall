"""Bake our Aurora example into an 18-second, 30 fps H.264 loop.

Development dependencies: Inkscape, FFmpeg, Pillow. No runtime dependency.
The SVG's 9-second translation and 6-second opacity cycles meet at 18 seconds.
"""
from pathlib import Path
import copy
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "motionwall/examples/aurora.svg"
OUTPUT = ROOT / "motionwall/examples/aurora-video.mp4"


def build():
    source = ET.parse(SVG).getroot()
    with tempfile.TemporaryDirectory(prefix="aurora-video-") as directory:
        directory = Path(directory)
        layers = {}
        for name in ("background", "ribbon", "foreground"):
            root = copy.deepcopy(source)
            for child in list(root):
                tag = child.tag.split("}")[-1]
                if tag == "defs":
                    continue
                ribbon = child.get("filter") == "url(#blur)"
                mountain = tag == "path" and child.get("fill") == "#070f1c"
                keep = (name == "ribbon" and ribbon or name == "foreground" and mountain
                        or name == "background" and not ribbon and not mountain)
                if not keep:
                    root.remove(child)
            for parent in root.iter():
                for child in list(parent):
                    if child.tag.split("}")[-1] in {"animate", "animateTransform"}:
                        parent.remove(child)
            path = directory / f"{name}.svg"
            ET.ElementTree(root).write(path)
            png = path.with_suffix(".png")
            subprocess.run(["inkscape", str(path), "--export-area-page", "--export-width=1920",
                            f"--export-filename={png}"], check=True)
            layers[name] = Image.open(png).convert("RGBA")
        encoder = subprocess.Popen([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", "1920x540", "-r", "30", "-i", "pipe:0", "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(OUTPUT)], stdin=subprocess.PIPE)
        try:
            for frame in range(18 * 30):
                time = frame / 30
                translate = 65 * (1 - abs(2 * ((time % 9) / 9) - 1))
                opacity = .65 + .35 * (1 - abs(2 * ((time % 6) / 6) - 1))
                ribbon = layers["ribbon"].copy()
                ribbon.putalpha(ribbon.getchannel("A").point(lambda alpha: round(alpha * opacity)))
                image = layers["background"].copy()
                image.alpha_composite(ribbon, (0, round(translate)))
                image.alpha_composite(layers["foreground"])
                encoder.stdin.write(image.tobytes())
        finally:
            encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("FFmpeg failed")
        print(f"Created {OUTPUT.name}: {OUTPUT.stat().st_size} bytes")


if __name__ == "__main__":
    build()
