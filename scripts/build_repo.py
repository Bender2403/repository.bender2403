#!/usr/bin/env python3
"""Build a Kodi-compatible repository in the repository root."""
from pathlib import Path
from xml.etree import ElementTree as ET
import hashlib
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "addons"
all_addons = []
generated_dirs = []

for source in sorted(p for p in SOURCES.iterdir() if p.is_dir()):
    addon_xml = source / "addon.xml"
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
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    files = []
    for file in sorted(source.rglob("*")):
        if not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc":
            continue
        relative = file.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, destination)
        files.append((destination, Path(addon_id) / relative))

    archive = target / f"{addon_id}-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for file, archive_name in files:
            zf.write(file, archive_name)

    all_addons.append(ET.tostring(addon, encoding="unicode"))
    generated_dirs.append(addon_id)

if not all_addons:
    raise SystemExit("Keine Add-ons in addons/ gefunden.")

xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
xml += "\n".join(all_addons) + "\n</addons>\n"
xml_path = ROOT / "addons.xml"
xml_path.write_text(xml, encoding="utf-8")
(ROOT / "addons.xml.md5").write_text(
    hashlib.md5(xml_path.read_bytes()).hexdigest(), encoding="ascii"
)

(ROOT / "generated-addon-dirs.txt").write_text("\n".join(generated_dirs) + "\n", encoding="utf-8")
print(f"Repository gebaut: {len(all_addons)} Add-on(s): {', '.join(generated_dirs)}")
