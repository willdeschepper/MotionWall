"""Build a native-runtime .deb without pip, root, or network access."""
from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionwall import __version__

APP_ID = "io.github.willdeschepper.MotionWall"
DEPENDENCIES = (
    "python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.10), gir1.2-adw-1, "
    "gir1.2-webkit-6.0, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, "
    "gstreamer1.0-libav, desktop-file-utils, hicolor-icon-theme"
)


def build(output_dir: Path) -> Path:
    if not shutil.which("dpkg-deb"):
        raise RuntimeError("Instale dpkg para gerar o pacote Debian.")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"motionwall_{__version__}_all.deb"
    with tempfile.TemporaryDirectory(prefix="motionwall-deb-") as directory:
        stage = Path(directory)
        stage.chmod(0o755)
        runtime = stage / "opt/motionwall"
        runtime.mkdir(parents=True)
        for name in ("motionwall", "extension"):
            shutil.copytree(ROOT / name, runtime / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        files = {
            "packaging/motionwall": "usr/bin/motionwall",
            f"packaging/{APP_ID}.desktop": f"usr/share/applications/{APP_ID}.desktop",
            f"packaging/{APP_ID}.svg": f"usr/share/icons/hicolor/scalable/apps/{APP_ID}.svg",
            "LICENSE": "usr/share/doc/motionwall/copyright",
            "packaging/postinst": "DEBIAN/postinst",
            "packaging/postrm": "DEBIAN/postrm",
        }
        for source, target in files.items():
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, destination)
        (stage / "usr/share/doc/motionwall/README.md.gz").write_bytes(
            gzip.compress((ROOT / "README.md").read_bytes(), mtime=0))
        # Fix permissions instead of inheriting checkout umask or executable bits.
        for path in stage.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        for target in ("usr/bin/motionwall", "DEBIAN/postinst", "DEBIAN/postrm"):
            (stage / target).chmod(0o755)
        size = sum(path.stat().st_size for path in stage.rglob("*") if path.is_file())
        control = (
            f"Package: motionwall\nVersion: {__version__}\nArchitecture: all\n"
            "Section: graphics\nPriority: optional\n"
            "Maintainer: Wiliam De Schepper <info@4rweb.net>\n"
            f"Installed-Size: {(size + 1023) // 1024}\nDepends: {DEPENDENCIES}\n"
            "Homepage: https://github.com/willdeschepper/MotionWall\n"
            "Description: Animated wallpapers and transparent overlays for GNOME\n"
            " Native GTK4/WebKit library for SVG, Lottie, GIF and video wallpapers.\n"
            " Includes desktop launcher, icon and the per-user GNOME integration.\n"
        )
        (stage / "DEBIAN/control").write_text(control)
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)], check=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    arguments = parser.parse_args()
    print(build(arguments.output_dir))
