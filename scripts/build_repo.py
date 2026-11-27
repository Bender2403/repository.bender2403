#!/usr/bin/env python3
"""Build the Kodi repository in the root and a compatibility GitHub Pages site."""
from pathlib import Path
from xml.etree import ElementTree as ET
import hashlib
import os
import base64
import json
import urllib.parse
import shutil
import tempfile
import uuid
import urllib.request
import zipfile

from zip_safety import UnsafeAddonZip, extract_addon_zip

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "addons"
SITE = ROOT / "_site"

# ZIP intake is handled from arbeitsordner/eingang/ below.

if SITE.exists():
    shutil.rmtree(SITE)
SITE.mkdir(parents=True)

all_addons = []
generated_dirs = []


for source in sorted(p for p in SOURCES.iterdir() if p.is_dir()):
    if source.is_symlink():
        raise SystemExit(f"Symlink als Add-on-Quellordner ist nicht erlaubt: {source}")
    addon_xml = source / "addon.xml"
    if addon_xml.is_symlink():
        raise SystemExit(f"Symlink als addon.xml ist nicht erlaubt: {addon_xml}")
    if not addon_xml.is_file():
        continue

    addon = ET.parse(addon_xml).getroot()
    addon_id = addon.attrib.get("id")
    version = addon.attrib.get("version")
    if not addon_id or not version:
        raise SystemExit(f"Ungültige addon.xml: {addon_xml}")
    if source.name != addon_id:
        raise SystemExit(f"Ordnername {source.name} stimmt nicht mit Add-on-ID {addon_id} überein")

    target = ROOT / addon_id
    if target == SOURCES or target == ROOT / ".github":
        raise SystemExit(f"Ungültiger Ausgabeordner: {target}")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise SystemExit(f"Ungültiges Veröffentlichungsziel: {target}")

    stage = Path(tempfile.mkdtemp(prefix=".addon-build-", dir=ROOT))
    backup = ROOT / f".{addon_id}.backup-{uuid.uuid4().hex}"
    moved_old = False
    try:
        files = []
        for file in sorted(source.rglob("*")):
            if file.is_symlink():
                raise SystemExit(f"Symlink im Add-on-Quellordner ist nicht erlaubt: {file}")
            if not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc":
                continue
            relative = file.relative_to(source)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
            files.append((destination, Path(addon_id) / relative))

        archive = stage / f"{addon_id}-{version}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for file, archive_name in files:
                zf.write(file, archive_name)

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
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if moved_old and backup.exists() and not target.exists():
            os.replace(backup, target)
        elif backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    legacy_zip_dir = SITE / "zips" / addon_id
    legacy_zip_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(archive, legacy_zip_dir / archive.name)

    all_addons.append(ET.tostring(addon, encoding="unicode"))
    generated_dirs.append(addon_id)


# Process ZIP files supplied through the repository's inbox. Invalid archives
# are quarantined individually; one bad ZIP must not stop the remaining files.
INBOX = ROOT / "arbeitsordner" / "eingang"
QUARANTINE = ROOT / "arbeitsordner" / "quarantaene"
INBOX.mkdir(parents=True, exist_ok=True)
QUARANTINE.mkdir(parents=True, exist_ok=True)

source_ids = set(generated_dirs)
incoming = []
for zip_path in sorted(INBOX.glob("*.zip")):
    try:
        archive_bytes = zip_path.read_bytes()
        if len(archive_bytes) > 50 * 1024 * 1024:
            raise UnsafeAddonZip("Komprimierte ZIP-Datei überschreitet 50 MiB")
        from io import BytesIO
        with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
            addon_xml_files = [i for i in archive.infolist()
                               if i.filename.rstrip("/").split("/")[-1].lower() == "addon.xml"
                               and not i.is_dir()]
            if len(addon_xml_files) != 1:
                raise UnsafeAddonZip("ZIP muss genau eine addon.xml enthalten")
            root = ET.fromstring(archive.read(addon_xml_files[0]))
            addon_id, version = root.attrib.get("id"), root.attrib.get("version")
            if not addon_id or not version:
                raise UnsafeAddonZip("addon.xml enthält keine Add-on-ID oder Version")
            # Full path, metadata, size and ZIP safety validation before extraction.
            from zip_safety import inspect_addon_zip
            inspect_addon_zip(archive, addon_id, version)
        incoming.append((zip_path, archive_bytes, addon_id, version))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        destination = QUARANTINE / zip_path.name
        counter = 1
        while destination.exists():
            destination = QUARANTINE / f"{zip_path.stem}-{counter}{zip_path.suffix}"
            counter += 1
        shutil.move(str(zip_path), destination)
        (destination.with_suffix(destination.suffix + ".reason.txt")).write_text(
            f"Datei: {zip_path.name}\\nFehler: {exc}\\n", encoding="utf-8"
        )
        print(f"QUARANTÄNE: {zip_path.name}: {exc}")
        
# Reject all ZIPs involved in an ID collision (including collisions with addons/).
from collections import Counter
counts = Counter(item[2] for item in incoming)
colliding = {addon_id for addon_id, count in counts.items() if count > 1}
colliding.update(set(counts) & source_ids)

for zip_path, archive_bytes, addon_id, version in incoming:
    try:
        if addon_id in colliding:
            raise UnsafeAddonZip(
                f"Doppelte Add-on-ID {addon_id}: Konflikt mit anderem Eingangs-ZIP "
                "oder einem Quellordner unter addons/"
            )
        addon_xml = extract_addon_zip(archive_bytes, ROOT, addon_id, version)
        archive_name = f"{addon_id}-{version}.zip"
        published_zip = ROOT / addon_id / archive_name
        legacy_zip_dir = SITE / "zips" / addon_id
        legacy_zip_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(published_zip, legacy_zip_dir / archive_name)
        all_addons.append(addon_xml)
        generated_dirs.append(addon_id)
        zip_path.unlink()
        print(f"ZIP übernommen: {zip_path.name} -> {addon_id} {version}")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        destination = QUARANTINE / zip_path.name
        counter = 1
        while destination.exists():
            destination = QUARANTINE / f"{zip_path.stem}-{counter}{zip_path.suffix}"
            counter += 1
        shutil.move(str(zip_path), destination)
        (destination.with_suffix(destination.suffix + ".reason.txt")).write_text(
            f"Datei: {zip_path.name}\\nFehler: {exc}\\n", encoding="utf-8"
        )
        print(f"QUARANTÄNE: {zip_path.name}: {exc}")

if not all_addons:
    raise SystemExit("Keine Add-ons in addons/ gefunden.")

xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
xml += "\n".join(all_addons) + "\n</addons>\n"
xml_bytes = xml.encode("utf-8")
digest = hashlib.md5(xml_bytes).hexdigest()

(ROOT / "addons.xml").write_bytes(xml_bytes)
(ROOT / "addons.xml.md5").write_text(digest, encoding="ascii")
(SITE / "addons.xml").write_bytes(xml_bytes)
(SITE / "addons.xml.md5").write_text(digest, encoding="ascii")
(SITE / "index.html").write_text(
    "<!doctype html><html lang='de'><meta charset='utf-8'>"
    "<title>Bender2403 Kodi-Repository</title>"
    "<h1>Bender2403 Kodi-Repository</h1>"
    "<p>Kodi-Repository-Metadaten und ZIP-Dateien.</p></html>",
    encoding="utf-8",
)

(ROOT / "generated-addon-dirs.txt").write_text("\n".join(generated_dirs) + "\n", encoding="utf-8")
print(f"Repository gebaut: {len(all_addons)} Add-on(s): {', '.join(generated_dirs)}")
