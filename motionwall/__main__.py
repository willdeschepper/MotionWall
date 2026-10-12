from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlencode
import zipfile

from . import __version__
from .library import ImportFailure, Library
from .server import PreviewServer

DEPENDENCIES = "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav"


def doctor():
    try:
        import gi
        for name, version in (("Gtk", "4.0"), ("Adw", "1"), ("WebKit", "6.0")):
            gi.require_version(name, version)
            print(f"OK: {name} {version}")
    except (ImportError, ValueError) as error:
        print(f"Dependência ausente: {error}\n\nUbuntu:\n{DEPENDENCIES}", file=sys.stderr)
        return 1
    print(f"MotionWall {__version__} · dependências disponíveis")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="MotionWall · biblioteca e prévia de animações para GNOME")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--doctor", action="store_true", help="Verificar dependências nativas")
    parser.add_argument("--data-dir", type=Path, help="Usar um catálogo separado")
    parser.add_argument("--import", dest="imports", type=Path, nargs="+", help="Importar arquivos sem abrir a interface")
    parser.add_argument("--list", action="store_true", help="Listar o catálogo em JSON")
    parser.add_argument("--serve", metavar="ID", help="Servir uma prévia local para desenvolvimento")
    parser.add_argument("--smoke-test", action="store_true", help="Verificar GTK e reprodução real em um catálogo temporário")
    args = parser.parse_args(argv)
    if args.doctor:
        return doctor()
    with tempfile.TemporaryDirectory(prefix="motionwall-smoke-") if args.smoke_test else _NoTemporaryDirectory() as temporary:
        try:
            library = Library(Path(temporary) / "library" if temporary else args.data_dir)
            if args.imports:
                for source in args.imports:
                    artwork, new = library.import_file(source)
                    print(f"{'Importado' if new else 'Já importado'}: {artwork.title} · {artwork.id}")
            if args.list:
                from dataclasses import asdict
                print(json.dumps([asdict(a) for a in library.entries], ensure_ascii=False, indent=2))
            if args.imports or args.list:
                return 0
            if args.serve:
                artwork = library.get(args.serve)
                if not artwork:
                    raise ImportFailure("ID não encontrado no catálogo.")
                server = PreviewServer(library)
                print(server.url + "?" + urlencode({"kind": artwork.kind, "src": server.asset_url(artwork)}), flush=True)
                print("Ctrl+C para encerrar.", flush=True)
                try:
                    server.thread.join()
                except KeyboardInterrupt:
                    pass
                finally:
                    server.close()
                return 0
            if args.smoke_test:
                examples = Path(__file__).parent / "examples"
                for source in sorted(examples.glob("*")):
                    library.import_file(source)
                package = Path(temporary) / "sample.lottie"
                with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", json.dumps({"version": "2", "animations": [{"id": "orbit"}]}))
                    archive.write(examples / "orbit.json", "a/orbit.json")
                library.import_file(package)
            try:
                from .app import MotionWallApplication
            except (ImportError, ValueError) as error:
                print(f"Dependência nativa ausente: {error}\n\n{DEPENDENCIES}", file=sys.stderr)
                return 1
            app = MotionWallApplication(library, smoke=args.smoke_test)
            result = app.run([sys.argv[0]])
            return app.smoke_exit if args.smoke_test else result
        except (ImportFailure, OSError) as error:
            print(str(error), file=sys.stderr)
            return 1


class _NoTemporaryDirectory:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
