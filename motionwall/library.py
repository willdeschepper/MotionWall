"""GTK-independent catalogue and bounded, transactional local imports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
import uuid
import xml.etree.ElementTree as ET
import zipfile

KINDS = {".gif": "gif", ".svg": "svg", ".json": "lottie", ".lottie": "dotlottie",
         ".mp4": "video", ".webm": "video"}
MAX_JSON = 32 * 1024 * 1024
MAX_TEXT = 16 * 1024 * 1024
MAX_UNPACKED = 256 * 1024 * 1024
MAX_PIXELS = 16_000_000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2"}
DATA_IMAGE = re.compile(r"^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=\s]+$")


class ImportFailure(ValueError):
    """An import failure that can be presented directly in the UI."""


@dataclass(frozen=True)
class Artwork:
    id: str
    title: str
    kind: str
    filename: str
    source_name: str
    width: int | None
    height: int | None
    added_at: str
    fingerprint: str
    size: int


def default_data_dir() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return root / "motionwall"


def _relative_name(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ImportFailure("Caminho de recurso inválido.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value:
        raise ImportFailure("O arquivo referencia um recurso fora da pasta da animação.")
    return path


def _read_json(path: Path, limit: int = MAX_JSON):
    if path.stat().st_size > limit:
        raise ImportFailure("JSON maior que o limite de 32 MiB.")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ImportFailure("O arquivo não contém JSON válido.") from error


def validate_lottie(data) -> tuple[int, int]:
    if not isinstance(data, dict) or not isinstance(data.get("layers"), list):
        raise ImportFailure("Este JSON não é uma animação Lottie.")
    for key in ("w", "h", "fr", "ip", "op"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ImportFailure(f"Campo Lottie inválido: {key}.")
    if not (1 <= data["w"] <= 16384 and 1 <= data["h"] <= 16384):
        raise ImportFailure("Dimensões Lottie inválidas.")
    if not (0 < data["fr"] <= 240 and data["op"] > data["ip"]):
        raise ImportFailure("Duração ou taxa de quadros Lottie inválida.")
    if not isinstance(data.get("assets", []), list):
        raise ImportFailure("Lista de recursos Lottie inválida.")
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get("x"), str):
                raise ImportFailure("Expressões JavaScript do After Effects não são suportadas nesta versão.")
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return int(data["w"]), int(data["h"])


def validate_svg(path: Path) -> tuple[int | None, int | None]:
    if path.stat().st_size > MAX_TEXT:
        raise ImportFailure("SVG maior que o limite de 16 MiB.")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ImportFailure("SVG com DTD ou entidades externas não é suportado.")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError) as error:
        raise ImportFailure("SVG inválido.") from error
    local = lambda name: name.split("}")[-1].lower()
    if local(root.tag) != "svg":
        raise ImportFailure("O documento não contém uma raiz SVG.")
    for node in root.iter():
        tag = local(node.tag)
        if tag in {"script", "foreignobject", "iframe", "object", "embed"}:
            raise ImportFailure("Use SVG com CSS ou SMIL; scripts e conteúdo HTML não são suportados.")
        for key, value in node.attrib.items():
            attribute = local(key)
            if attribute.startswith("on"):
                raise ImportFailure("Eventos JavaScript em SVG não são suportados.")
            if attribute in {"href", "src"} and not (value.startswith("#") or DATA_IMAGE.fullmatch(value)):
                raise ImportFailure("O SVG precisa ser independente, sem links ou imagens externas.")
            if tag in {"animate", "set", "animatetransform", "animatemotion"} and attribute == "attributename":
                if value.lower() in {"href", "xlink:href", "src", "style"} or value.lower().startswith("on"):
                    raise ImportFailure("SVG tenta animar um atributo de execução ou recurso externo.")
    viewbox = root.get("viewBox", "").replace(",", " ").split()
    if len(viewbox) == 4:
        try:
            width, height = float(viewbox[2]), float(viewbox[3])
            if not (0 < width <= 16384 and 0 < height <= 16384):
                raise ValueError
            return int(width), int(height)
        except ValueError as error:
            raise ImportFailure("viewBox SVG inválido.") from error
    return None, None


def _copy_resource(reference: str, source_root: Path, destination: Path,
                   allowed: set[str], budget: list[int]) -> str:
    relative = _relative_name(reference)
    source = (source_root / str(relative)).resolve()
    if not source.is_relative_to(source_root.resolve()) or not source.is_file():
        raise ImportFailure(f"Recurso local ausente ou fora da pasta: {reference}")
    suffix = source.suffix.lower()
    if suffix not in allowed:
        raise ImportFailure(f"Tipo de recurso não suportado: {suffix or reference}")
    size = source.stat().st_size
    budget[0] += size
    if budget[0] > MAX_UNPACKED:
        raise ImportFailure("Os recursos da animação excedem 256 MiB.")
    target = destination / "resources" / f"{uuid.uuid4().hex}{suffix}"
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, target)
    return target.relative_to(destination).as_posix()


def _prepare_lottie(source: Path, destination: Path, resource_root: Path | None = None):
    data = _read_json(source)
    dimensions = validate_lottie(data)
    root = resource_root or source.parent
    budget = [source.stat().st_size]
    for asset in data.get("assets", []):
        if not isinstance(asset, dict):
            raise ImportFailure("Recurso Lottie inválido.")
        if "p" not in asset:
            continue  # A precomposition, rather than an image.
        path = asset.get("p")
        if not isinstance(path, str):
            raise ImportFailure("Referência de imagem Lottie inválida.")
        if path.startswith("data:"):
            if not DATA_IMAGE.fullmatch(path):
                raise ImportFailure("Imagem embutida Lottie não suportada.")
            continue
        prefix = asset.get("u", "")
        if not isinstance(prefix, str):
            raise ImportFailure("Pasta de imagem Lottie inválida.")
        reference = prefix + path
        # dotLottie commonly uses ../i/ relative to a/ (v2), or ../images/
        # relative to animations/ (v1). Resolve only inside the unpacked root.
        if resource_root is not None:
            candidate = (source.parent / reference).resolve()
            if not candidate.is_relative_to(root.resolve()) or ":" in reference or "\\" in reference:
                raise ImportFailure("Recurso dotLottie fora do pacote.")
            if not candidate.is_file():
                candidate = (root / reference).resolve()
            if not candidate.is_relative_to(root.resolve()):
                raise ImportFailure("Recurso dotLottie fora do pacote.")
            reference = candidate.relative_to(root.resolve()).as_posix()
        asset["p"] = _copy_resource(reference, root, destination, IMAGE_EXTENSIONS, budget)
        asset["u"] = ""
        asset["e"] = 0
    fonts = data.get("fonts", {}).get("list", []) if isinstance(data.get("fonts", {}), dict) else []
    for font in fonts:
        if font.get("fPath"):
            reference = font["fPath"]
            if resource_root is not None:
                candidate = (source.parent / reference).resolve()
                if not candidate.is_relative_to(root.resolve()):
                    raise ImportFailure("Fonte dotLottie fora do pacote.")
                reference = candidate.relative_to(root.resolve()).as_posix()
            font["fPath"] = _copy_resource(reference, root, destination, FONT_EXTENSIONS, budget)
    (destination / "animation.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return dimensions


def _unpack_dotlottie(source: Path, unpacked: Path) -> Path:
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > 1024 or sum(m.file_size for m in members) > MAX_UNPACKED:
                raise ImportFailure("Pacote .lottie excede os limites de 1024 arquivos ou 256 MiB.")
            seen = set()
            for member in members:
                relative = _relative_name(member.filename)
                if relative in seen or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1:
                    raise ImportFailure("Pacote .lottie contém links, duplicatas ou arquivos criptografados.")
                seen.add(relative)
                target = unpacked / str(relative)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst, length=64 * 1024)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise ImportFailure("Pacote .lottie inválido ou não suportado.") from error
    manifest = _read_json(unpacked / "manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("animations"), list) or not manifest["animations"]:
        raise ImportFailure("Manifesto .lottie sem animações.")
    version = str(manifest.get("version", "1"))
    if version not in {"1", "1.0", "2", "2.0"}:
        raise ImportFailure(f"Versão dotLottie não suportada: {version}")
    initial = manifest.get("initial", {})
    selected = initial.get("animation") if isinstance(initial, dict) else None
    selected = selected or manifest.get("activeAnimationId") or manifest["animations"][0].get("id")
    if not isinstance(selected, str) or not re.fullmatch(r"[A-Za-z0-9._ -]+", selected) or selected in {".", ".."}:
        raise ImportFailure("ID de animação .lottie inválido.")
    if selected not in [a.get("id") for a in manifest["animations"] if isinstance(a, dict)]:
        raise ImportFailure("A animação inicial não existe no manifesto.")
    directory = "a" if version.startswith("2") else "animations"
    animation = unpacked / directory / f"{selected}.json"
    if not animation.is_file():
        raise ImportFailure("O pacote não contém o JSON da animação inicial.")
    return animation


def _digest(directory: Path) -> str:
    digest = hashlib.sha256()
    # Resource names are random to prevent filename collisions; hash content,
    # not those names. Include normalized JSON with names mapped to content SHA.
    files = sorted(directory.rglob("*"))
    hashes = {}
    for path in files:
        if path.is_file():
            checksum = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(chunk)
            hashes[path.relative_to(directory).as_posix()] = checksum.hexdigest()
    animation = directory / "animation.json"
    if animation.exists():
        content = animation.read_text(encoding="utf-8")
        for filename, checksum in hashes.items():
            if filename != "animation.json":
                content = content.replace(filename, checksum)
        digest.update(content.encode())
    else:
        for checksum in sorted(hashes.values()):
            digest.update(checksum.encode())
    return digest.hexdigest()


class Library:
    def __init__(self, directory: Path | None = None):
        self.root = (directory or default_data_dir()).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.asset_root = self.root / "artworks"
        self.asset_root.mkdir(exist_ok=True)
        self.index = self.root / "library.json"
        self.lock = threading.RLock()
        self.entries: list[Artwork] = []
        self.settings = {"fit": "contain", "speed": 1.0, "loop": True, "selected": None,
                         "fps": 30, "transparent": True}
        if self.index.exists():
            data = _read_json(self.index)
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ImportFailure("Catálogo incompatível. Preserve library.json e verifique sua versão.")
            try:
                self.entries = [Artwork(**entry) for entry in data["artworks"]]
                for entry in self.entries:
                    if not re.fullmatch(r"[0-9a-f]{32}", entry.id) or entry.kind not in KINDS.values():
                        raise ValueError("Invalid catalogue entry")
                    _relative_name(entry.filename)
                settings = data.get("settings", {})
                if settings.get("fit") in {"contain", "cover", "stretch", "native"}:
                    self.settings["fit"] = settings["fit"]
                speed = settings.get("speed", 1)
                if isinstance(speed, (float, int)) and 0.25 <= speed <= 3:
                    self.settings["speed"] = speed
                self.settings["loop"] = settings.get("loop", True) is not False
                if settings.get("fps") in {15, 30, 60}:
                    self.settings["fps"] = settings["fps"]
                self.settings["transparent"] = settings.get("transparent", True) is not False
                self.settings["selected"] = settings.get("selected")
            except (TypeError, KeyError, ValueError) as error:
                raise ImportFailure("Catálogo corrompido. Preserve library.json antes de restaurar um backup.") from error

    def _save(self):
        temporary = self.index.with_suffix(".tmp")
        data = {"version": 1, "artworks": [asdict(a) for a in self.entries], "settings": self.settings}
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.index)

    def set_settings(self, **values):
        with self.lock:
            previous = self.settings.copy()
            self.settings.update(values)
            try:
                self._save()
            except OSError:
                self.settings = previous
                raise

    def get(self, identifier: str) -> Artwork | None:
        with self.lock:
            return next((a for a in self.entries if a.id == identifier), None)

    def import_file(self, source: Path) -> tuple[Artwork, bool]:
        """Return (artwork, is_new); copy sources without modifying originals."""
        source = source.expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in KINDS:
            raise ImportFailure("Escolha GIF, SVG, JSON Lottie, .lottie, MP4 ou WebM.")
        kind = KINDS[source.suffix.lower()]
        maximum = {"video": 2 * 1024**3, "gif": 64 * 1024**2,
                   "dotlottie": 128 * 1024**2, "svg": MAX_TEXT, "lottie": MAX_JSON}[kind]
        if not 0 < source.stat().st_size <= maximum:
            raise ImportFailure("Arquivo vazio ou maior que o limite deste formato.")
        identifier = uuid.uuid4().hex
        staging = self.asset_root / f".incoming-{identifier}"
        staging.mkdir()
        width = height = None
        filename = "animation.json" if kind in {"lottie", "dotlottie"} else "artwork" + source.suffix.lower()
        try:
            if kind == "svg":
                width, height = validate_svg(source)
                shutil.copyfile(source, staging / filename)
            elif kind == "lottie":
                width, height = _prepare_lottie(source, staging)
            elif kind == "dotlottie":
                unpacked = staging / ".unpacked"
                unpacked.mkdir()
                animation = _unpack_dotlottie(source, unpacked)
                width, height = _prepare_lottie(animation, staging, unpacked)
                shutil.rmtree(unpacked)
            else:
                with source.open("rb") as stream:
                    header = stream.read(32)
                if kind == "gif":
                    if header[:6] not in {b"GIF87a", b"GIF89a"} or len(header) < 10:
                        raise ImportFailure("Cabeçalho GIF inválido.")
                    width, height = int.from_bytes(header[6:8], "little"), int.from_bytes(header[8:10], "little")
                    if not width or not height or width * height > MAX_PIXELS:
                        raise ImportFailure("GIF excede o limite de 16 milhões de pixels por quadro.")
                elif (source.suffix.lower() == ".mp4" and header[4:8] != b"ftyp") or (
                    source.suffix.lower() == ".webm" and header[:4] != b"\x1aE\xdf\xa3"
                ):
                    raise ImportFailure("Cabeçalho de vídeo inválido.")
                shutil.copyfile(source, staging / filename)
            fingerprint = _digest(staging)
            size = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
            artwork = Artwork(identifier, source.stem, kind, filename, source.name, width, height,
                              datetime.now(timezone.utc).isoformat(), fingerprint, size)
            with self.lock:
                existing = next((a for a in self.entries if a.fingerprint == fingerprint and a.kind == kind), None)
                if existing:
                    return existing, False
                target = self.asset_root / identifier
                staging.replace(target)
                self.entries.append(artwork)
                try:
                    self._save()
                except OSError:
                    self.entries.remove(artwork)
                    shutil.rmtree(target)
                    raise
            return artwork, True
        except (OSError, zipfile.BadZipFile, AttributeError, TypeError, ValueError) as error:
            if isinstance(error, ImportFailure):
                raise
            raise ImportFailure(f"Não foi possível importar {source.name}: {error}") from error
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def remove(self, identifier: str):
        with self.lock:
            artwork = self.get(identifier)
            if artwork is None:
                return
            original = self.asset_root / identifier
            trash = self.asset_root / f".deleted-{identifier}"
            moved = original.exists()
            if moved:
                original.replace(trash)
            index = self.entries.index(artwork)
            self.entries.remove(artwork)
            try:
                self._save()
            except OSError:
                self.entries.insert(index, artwork)
                if moved:
                    trash.replace(original)
                raise
            if moved:
                shutil.rmtree(trash)
