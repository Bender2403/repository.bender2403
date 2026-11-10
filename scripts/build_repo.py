#!/usr/bin/env python3
"""Build the Kodi repository in the root and a compatibility GitHub Pages site."""
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
import hashlib
import base64
import json
import urllib.parse
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "addons"
SITE = ROOT / "_site"

# Third-party repository installers hosted in the user's original-addons branch.
# The ZIPs are fetched during every build, inspected, and published as normal
# Kodi repository entries. They are not unpacked into the source repository.
EXTERNAL_ZIPS = [
    {
        "url": "https://raw.githubusercontent.com/Bender2403/kodi-rakuten-tv-addon/original-addons/repository.heptamers.stuff-1.0.0.zip",
        "addon_id": "repository.heptamers.stuff",
        "version": "1.0.0",
    },
    {
        "url": "https://raw.githubusercontent.com/Bender2403/kodi-rakuten-tv-addon/original-addons/repository.jurialmunkey-3.5.zip",
        "addon_id": "repository.jurialmunkey",
        "version": "3.5",
    },
    {
        "url": "https://raw.githubusercontent.com/Bender2403/kodi-rakuten-tv-addon/original-addons/repository.xvault-1.0.3.zip",
        "addon_id": "repository.xvault",
        "version": "1.0.3",
    },
    {
        "repository": "Bender2403/kodi-rakuten-tv-addon",
        "ref": "original-addons",
        "path": "plugin.video.rakuten.de-1.0.4+matrix.1.zip",
        "addon_id": "plugin.video.rakuten.de",
        "version": "1.0.4+matrix.1",
    },
    {
        "repository": "Bender2403/kodi-rakuten-tv-addon",
        "ref": "kodi-logs",
        "path": "dist/script.kodi.loguploader.github-0.1.3.zip",
        "addon_id": "script.kodi.loguploader.github",
        "version": "0.1.3",
    },
]

if SITE.exists():
    shutil.rmtree(SITE)
SITE.mkdir(parents=True)

all_addons = []
generated_dirs = []


def publish_external_zip(item):
    source_repo = item.get("repository", "Bender2403/kodi-rakuten-tv-addon")
    source_ref = item.get("ref", "original-addons")
    source_path = item.get("path") or item.get("url", "").rsplit("/", 1)[-1]
    if not source_path:
        raise SystemExit(f"Quellpfad für {item['addon_id']} fehlt")
    filename = source_path.rsplit("/", 1)[-1]
    api_url = (
        "https://api.github.com/repos/" + source_repo + "/contents/"
        + urllib.parse.quote(source_path, safe="/")
        + "?ref=" + urllib.parse.quote(source_ref, safe="")
    )
    token = __import__("os").environ.get("SOURCE_REPO_TOKEN")
    if not token:
        raise SystemExit("GitHub-Secret SOURCE_REPO_TOKEN fehlt. Bitte einen Token mit Leserechten auf das private Quell-Repository hinterlegen.")
    request = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Bender2403-Kodi-Repository",
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("encoding") != "base64" or not payload.get("content"):
        raise SystemExit(f"GitHub hat keinen Base64-Dateiinhalt für {filename} geliefert")
    archive_bytes = base64.b64decode(payload["content"])

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_path = Path(temp_dir) / "source.zip"
        archive_path.write_bytes(archive_bytes)
        with zipfile.ZipFile(archive_path) as zf:
            members = [name for name in zf.namelist() if name.lower().endswith("/addon.xml") or name.lower() == "addon.xml"]
            if len(members) != 1:
                raise SystemExit(f"{item['addon_id']}: ZIP enthält nicht genau eine addon.xml")
            addon_member = members[0]
            prefix = addon_member[:-len("addon.xml")]
            addon_root = ET.fromstring(zf.read(addon_member))
            actual_id = addon_root.attrib.get("id")
            actual_version = addon_root.attrib.get("version")
            if actual_id != item["addon_id"] or actual_version != item["version"]:
                raise SystemExit(
                    f"Unerwartete ZIP-Metadaten: erwartet {item['addon_id']} {item['version']}, "
                    f"gefunden {actual_id} {actual_version}"
                )

            target = ROOT / actual_id
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True)

            # Copy the add-on files from the ZIP while stripping its top-level folder.
            for info in zf.infolist():
                if info.is_dir():
                    continue
                member_path = PurePosixPath(info.filename)
                if not info.filename.startswith(prefix):
                    continue
                relative = member_path.relative_to(PurePosixPath(prefix.rstrip("/"))) if prefix else member_path
                if not relative.parts or ".." in relative.parts:
                    raise SystemExit(f"Unsicherer ZIP-Pfad in {item['addon_id']}: {info.filename}")
                destination = target.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(zf.read(info.filename))

        archive_name = f"{item['addon_id']}-{item['version']}.zip"
        (target / archive_name).write_bytes(archive_bytes)

    legacy_zip_dir = SITE / "zips" / item["addon_id"]
    legacy_zip_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target / archive_name, legacy_zip_dir / archive_name)
    all_addons.append(ET.tostring(addon_root, encoding="unicode"))
    generated_dirs.append(item["addon_id"])


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

    legacy_zip_dir = SITE / "zips" / addon_id
    legacy_zip_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(archive, legacy_zip_dir / archive.name)

    all_addons.append(ET.tostring(addon, encoding="unicode"))
    generated_dirs.append(addon_id)

for item in EXTERNAL_ZIPS:
    publish_external_zip(item)

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
