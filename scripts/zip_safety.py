"""Safe extraction helpers for third-party Kodi add-on ZIP archives."""
from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

MAX_ARCHIVE_SIZE = 50 * 1024 * 1024
MAX_FILES = 1000
MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_TOTAL_SIZE = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class UnsafeAddonZip(ValueError):
    """Raised when an add-on archive is malformed or unsafe."""


def _validated_member_name(info: zipfile.ZipInfo) -> PurePosixPath:
    raw = info.filename
    if not raw or "\x00" in raw or "\\" in raw:
        raise UnsafeAddonZip(f"Ungültiger ZIP-Eintrag: {raw!r}")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise UnsafeAddonZip(f"Absoluter ZIP-Pfad ist nicht erlaubt: {raw!r}")

    parts = raw.rstrip("/").split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise UnsafeAddonZip(f"Unsicherer ZIP-Pfad: {raw!r}")

    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise UnsafeAddonZip(f"Symlink im ZIP ist nicht erlaubt: {raw!r}")
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise UnsafeAddonZip(f"Spezieller Dateityp im ZIP ist nicht erlaubt: {raw!r}")
    if info.flag_bits & 0x1:
        raise UnsafeAddonZip(f"Verschlüsselter ZIP-Eintrag wird nicht unterstützt: {raw!r}")

    return PurePosixPath(*parts)


def inspect_addon_zip(archive: zipfile.ZipFile, expected_id: str, expected_version: str):
    infos = archive.infolist()
    if not infos:
        raise UnsafeAddonZip("ZIP-Archiv ist leer")
    if len(infos) > MAX_FILES:
        raise UnsafeAddonZip(f"Zu viele ZIP-Einträge: {len(infos)} (Maximum {MAX_FILES})")

    seen: set[str] = set()
    total_size = 0
    files = []
    addon_xml_infos = []

    for info in infos:
        member = _validated_member_name(info)
        normalized = member.as_posix().rstrip("/")
        if normalized in seen:
            raise UnsafeAddonZip(f"Doppelter ZIP-Pfad: {normalized}")
        seen.add(normalized)

        if info.is_dir():
            continue
        if info.file_size > MAX_FILE_SIZE:
            raise UnsafeAddonZip(f"Datei überschreitet Größenlimit: {normalized}")
        total_size += info.file_size
        if total_size > MAX_TOTAL_SIZE:
            raise UnsafeAddonZip("Entpackte Gesamtgröße überschreitet 100 MiB")
        if info.file_size and info.compress_size == 0:
            raise UnsafeAddonZip(f"Ungültige Kompressionsgröße: {normalized}")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise UnsafeAddonZip(f"Kompressionsverhältnis zu hoch: {normalized}")
        files.append((info, member))
        if member.name.lower() == "addon.xml":
            addon_xml_infos.append((info, member))

    if len(addon_xml_infos) != 1:
        raise UnsafeAddonZip("ZIP muss genau eine addon.xml enthalten")

    addon_info, addon_member = addon_xml_infos[0]
    prefix = addon_member.parent
    if prefix == PurePosixPath("."):
        prefix = PurePosixPath()

    selected = []
    for info, member in files:
        if prefix.parts:
            if member.parts[:len(prefix.parts)] != prefix.parts:
                raise UnsafeAddonZip(f"Datei liegt außerhalb des Add-on-Ordners: {member}")
            relative = PurePosixPath(*member.parts[len(prefix.parts):])
        else:
            relative = member
        if not relative.parts or ".." in relative.parts or relative.is_absolute():
            raise UnsafeAddonZip(f"Unsicherer relativer ZIP-Pfad: {member}")
        selected.append((info, relative))

    try:
        addon_root = ET.fromstring(archive.read(addon_info))
    except (ET.ParseError, OSError, RuntimeError) as exc:
        raise UnsafeAddonZip(f"addon.xml ist ungültig: {exc}") from exc

    actual_id = addon_root.attrib.get("id")
    actual_version = addon_root.attrib.get("version")
    if actual_id != expected_id or actual_version != expected_version:
        raise UnsafeAddonZip(
            f"Unerwartete ZIP-Metadaten: erwartet {expected_id} {expected_version}, "
            f"gefunden {actual_id} {actual_version}"
        )
    return addon_root, selected


def extract_addon_zip(archive_bytes: bytes, destination_root: Path,
                      expected_id: str, expected_version: str) -> str:
    """Validate and atomically replace destination_root/expected_id."""
    if len(archive_bytes) > MAX_ARCHIVE_SIZE:
        raise UnsafeAddonZip("Komprimierte ZIP-Datei überschreitet 50 MiB")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", expected_id):
        raise UnsafeAddonZip(f"Ungültige Add-on-ID: {expected_id!r}")
    if not re.fullmatch(r"[0-9A-Za-z.+_-]+", expected_version):
        raise UnsafeAddonZip(f"Ungültige Add-on-Version: {expected_version!r}")
    destination_root = Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    target = destination_root / expected_id
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise UnsafeAddonZip(f"Ungültiges Veröffentlichungsziel: {target}")

    stage = Path(tempfile.mkdtemp(prefix=".addon-stage-", dir=destination_root))
    backup = destination_root / f".{expected_id}.backup-{uuid.uuid4().hex}"
    moved_old = False
    try:
        try:
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
                addon_root, selected = inspect_addon_zip(archive, expected_id, expected_version)
                for info, relative in selected:
                    output = stage.joinpath(*relative.parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as source, output.open("xb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise UnsafeAddonZip(f"ZIP konnte nicht sicher gelesen werden: {exc}") from exc

        archive_name = f"{expected_id}-{expected_version}.zip"
        (stage / archive_name).write_bytes(archive_bytes)

        if target.exists():
            os.replace(target, backup)
            moved_old = True
        try:
            os.replace(stage, target)
        except Exception:
            if moved_old and backup.exists():
                os.replace(backup, target)
                moved_old = False
            raise
        if moved_old:
            shutil.rmtree(backup)
            moved_old = False
        return ET.tostring(addon_root, encoding="unicode")
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if moved_old and backup.exists() and not target.exists():
            os.replace(backup, target)
        elif backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
