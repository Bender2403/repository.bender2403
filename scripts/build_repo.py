#!/usr/bin/env python3
"""Build Kodi repository metadata and add-on ZIP archives."""
from pathlib import Path
from xml.etree import ElementTree as ET
import hashlib
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "addons"
SITE = ROOT / "_site"

if SITE.exists():
    shutil.rmtree(SITE)
SITE.mkdir(parents=True)

all_addons = []
for addon_dir in sorted(p for p in ADDONS.iterdir() if p.is_dir()):
    addon_xml = addon_dir / "addon.xml"
    if not addon_xml.is_file():
        continue
    addon = ET.parse(addon_xml).getroot()
    addon_id = addon.attrib.get("id")
    version = addon.attrib.get("version")
    if not addon_id or not version:
        raise SystemExit(f"Ungültige addon.xml: {addon_xml}")
    all_addons.append(ET.tostring(addon, encoding="unicode"))

    zip_dir = SITE / "zips" / addon_id
    zip_dir.mkdir(parents=True, exist_ok=True)
    archive = zip_dir / f"{addon_id}-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(addon_dir.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                zf.write(file, Path(addon_id) / file.relative_to(addon_dir))

if not all_addons:
    raise SystemExit("Keine Add-ons in addons/ gefunden.")

xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
xml += "\n".join(all_addons) + "\n</addons>\n"
xml_path = SITE / "addons.xml"
xml_path.write_text(xml, encoding="utf-8")
digest = hashlib.md5(xml_path.read_bytes()).hexdigest()
(SITE / "addons.xml.md5").write_text(digest, encoding="ascii")
(SITE / "index.html").write_text(
    "<!doctype html><html lang='de'><meta charset='utf-8'>"
    "<title>Bender2403 Kodi-Repository</title>"
    "<h1>Bender2403 Kodi-Repository</h1>"
    "<p>Offizielles Add-on-Repository für Kodi.</p></html>",
    encoding="utf-8",
)
print(f"Repository gebaut: {len(all_addons)} Add-on(s)")
