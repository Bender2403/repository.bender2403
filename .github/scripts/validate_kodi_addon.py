#!/usr/bin/env python3
"""Validate Kodi add-on source directories.

The validator is deliberately conservative: optional Kodi files are checked
when present, but settings and translations are not mandatory for every add-on.
No bytecode or cache files are created.
"""
from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDONS = ROOT / "addons"
QUARANTINE = ROOT / "_quarantine"

ERRORS: list[str] = []
WARNINGS: list[str] = []
NOTES: list[str] = []

ADDON_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SETTING_CALLS = {
    "getSetting", "getSettingInt", "getSettingBool",
    "getSettingString", "getSettingNumber",
}


def error(message: str) -> None:
    ERRORS.append(message)


def warning(message: str) -> None:
    WARNINGS.append(message)


def note(message: str) -> None:
    NOTES.append(message)


def parse_xml(path: Path) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        error(f"{path}: XML kann nicht gelesen werden: {exc}")
        return None


def safe_relative_library(addon_dir: Path, library: str, addon_xml: Path) -> None:
    candidate = Path(library)
    if candidate.is_absolute() or ".." in candidate.parts:
        error(f"{addon_xml}: unsicherer library-Pfad: {library}")
        return
    resolved = (addon_dir / candidate).resolve()
    try:
        resolved.relative_to(addon_dir.resolve())
    except ValueError:
        error(f"{addon_xml}: library liegt außerhalb des Add-ons: {library}")
        return
    if not resolved.is_file():
        error(f"{addon_xml}: library-Datei fehlt: {library}")


def validate_addon_xml(addon_dir: Path) -> tuple[str | None, str | None]:
    path = addon_dir / "addon.xml"
    if not path.is_file():
        error(f"{path}: addon.xml fehlt")
        return None, None

    root = parse_xml(path)
    if root is None:
        return None, None
    if root.tag != "addon":
        error(f"{path}: Wurzelelement muss <addon> sein")
        return None, None

    addon_id = root.attrib.get("id", "").strip()
    version = root.attrib.get("version", "").strip()
    provider = root.attrib.get("provider-name", "").strip()

    if not addon_id:
        error(f"{path}: Add-on-ID fehlt")
    elif not ADDON_ID_RE.fullmatch(addon_id):
        error(f"{path}: ungültige Add-on-ID: {addon_id!r}")
    elif addon_dir.name != addon_id:
        error(f"{path}: Verzeichnisname {addon_dir.name!r} stimmt nicht mit ID {addon_id!r} überein")

    if not version:
        error(f"{path}: Version fehlt")
    elif not re.fullmatch(r"[0-9A-Za-z.+_-]+", version):
        error(f"{path}: ungewöhnliches Versionsformat: {version!r}")
    if not provider:
        warning(f"{path}: provider-name fehlt")

    extensions = root.findall("extension")
    if not extensions:
        error(f"{path}: mindestens ein <extension>-Eintrag wird erwartet")
        return addon_id or None, None

    points = [ext.attrib.get("point", "").strip() for ext in extensions]
    if any(not point for point in points):
        error(f"{path}: mindestens ein extension-Eintrag hat kein point-Attribut")

    addon_type = ", ".join(sorted({p for p in points if p})) or "unknown"

    # Validate Python entry points only where Kodi declares a Python library.
    for ext in extensions:
        point = ext.attrib.get("point", "")
        library = ext.attrib.get("library")
        if point in {
            "xbmc.python.script",
            "xbmc.service",
            "xbmc.python.module",
            "xbmc.python.pluginsource",
        }:
            if not library and point == "xbmc.python.pluginsource":
                library = "default.py"
            if library:
                safe_relative_library(addon_dir, library, path)
            elif point in {"xbmc.python.script", "xbmc.service"}:
                error(f"{path}: {point} benötigt ein library-Attribut")

    requires = root.find("requires")
    if requires is not None:
        for imp in requires.findall("import"):
            dep = imp.attrib.get("addon", "").strip()
            dep_version = imp.attrib.get("version", "").strip()
            if not dep:
                error(f"{path}: dependency import ohne addon-ID")
            if dep == "xbmc.python":
                if not dep_version:
                    warning(f"{path}: xbmc.python-Abhängigkeit ohne Versionsangabe")
                elif not re.match(r"^3\.", dep_version):
                    warning(f"{path}: xbmc.python-Version {dep_version!r}; Python-3-Kompatibilität prüfen")

    return addon_id or None, addon_type


def validate_python(addon_dir: Path) -> set[str]:
    used_ids: set[str] = set()
    py_files = [p for p in addon_dir.rglob("*.py") if "__pycache__" not in p.parts]
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (UnicodeDecodeError, SyntaxError) as exc:
            error(f"{path}: Python-Fehler: {exc}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            method = node.func.attr
            if method in SETTING_CALLS and node.args:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    used_ids.add("setting:" + value.value)
            elif method == "getString" and node.args:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, int):
                    used_ids.add("string:" + str(value.value))
    return used_ids


def validate_settings(addon_dir: Path) -> set[str]:
    path = addon_dir / "resources" / "settings.xml"
    if not path.exists():
        note(f"{addon_dir.name}: keine settings.xml (zulässig, wenn das Add-on keine Einstellungen benötigt)")
        return set()

    root = parse_xml(path)
    if root is None:
        return set()
    if root.tag != "settings":
        error(f"{path}: Wurzelelement muss <settings> sein")
        return set()

    version = root.attrib.get("version")
    if version not in (None, "", "1"):
        warning(f"{path}: unbekannte settings-Version {version!r}; Kodi-Kompatibilität manuell prüfen")

    ids: set[str] = set()
    for setting in root.iter("setting"):
        setting_id = setting.attrib.get("id", "").strip()
        if not setting_id:
            error(f"{path}: setting ohne ID")
            continue
        if setting_id in ids:
            error(f"{path}: doppelte Setting-ID {setting_id!r}")
        ids.add(setting_id)
    return {"setting:" + item for item in ids}


def read_po_ids(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        warning(f"{path}: Sprachdatei nicht lesbar: {exc}")
        return set()
    return {
        match.group(1)
        for match in re.finditer(r'^msgid\s+"([0-9]+)"\s*$', text, re.MULTILINE)
    }


def validate_translations(addon_dir: Path, used_ids: set[str]) -> None:
    language_root = addon_dir / "resources" / "language"
    if not language_root.is_dir():
        note(f"{addon_dir.name}: keine Sprachdateien vorhanden")
        return

    english = language_root / "resource.language.en_gb" / "strings.po"
    if not english.is_file():
        warning(f"{english}: englische Fallback-Datei fehlt")
        return

    available = read_po_ids(english)
    missing = {
        item.split(":", 1)[1]
        for item in used_ids
        if item.startswith("string:") and item.split(":", 1)[1] not in available
    }
    if missing:
        warning(f"{english}: verwendete String-IDs fehlen: {', '.join(sorted(missing))}")

    german = language_root / "resource.language.de_de" / "strings.po"
    if german.is_file():
        german_ids = read_po_ids(german)
        missing_de = {
            item.split(":", 1)[1]
            for item in used_ids
            if item.startswith("string:") and item.split(":", 1)[1] not in german_ids
        }
        if missing_de:
            warning(f"{german}: deutsche Übersetzungen fehlen für: {', '.join(sorted(missing_de))}")


def validate_addon(addon_dir: Path) -> bool:
    ERRORS.clear()
    WARNINGS.clear()
    NOTES.clear()
    note(f"Prüfe {addon_dir.name}")
    addon_id, addon_type = validate_addon_xml(addon_dir)
    if addon_id and addon_type:
        note(f"Add-on-ID: {addon_id}; Extension Point(s): {addon_type}")
    python_ids = validate_python(addon_dir)
    settings_ids = validate_settings(addon_dir)
    validate_translations(addon_dir, python_ids | settings_ids)
    return not ERRORS


def quarantine_addon(addon_dir: Path) -> Path | None:
    # Preserve the source directory name; never derive a filesystem path from
    # untrusted addon.xml metadata.
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    target = QUARANTINE / addon_dir.name
    if target.exists():
        error(f"{addon_dir.name}: Quarantäne-Ziel existiert bereits; nichts überschrieben")
        return None
    shutil.move(str(addon_dir), str(target))
    return target


def write_report(path: Path, quarantined: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Kodi Add-on validation report", "",
        f"Errors: {len(ERRORS)}",
        f"Warnings: {len(WARNINGS)}",
        f"Notes: {len(NOTES)}",
        f"Quarantined: {len(quarantined)}", "",
    ]
    for title, items in (("ERRORS", ERRORS), ("WARNINGS", WARNINGS), ("NOTES", NOTES)):
        if items:
            lines += [title, "-" * 60, *[f"- {item}" for item in items], ""]
    if quarantined:
        lines += ["QUARANTINED ADD-ONS", "-" * 60, *[f"- {item}" for item in quarantined], ""]
    lines.append("RESULT: " + ("FAILED" if ERRORS else "PASSED"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="kodi-addon-validation.txt")
    parser.add_argument("--quarantine", action="store_true",
                        help="Move invalid add-on source folders into _quarantine/")
    args = parser.parse_args()
    report = Path(args.report).resolve()
    quarantined: list[str] = []

    if not ADDONS.is_dir():
        note(f"{ADDONS}: addons-Verzeichnis fehlt; nichts zu prüfen")
    else:
        addon_dirs = sorted(p for p in ADDONS.iterdir() if p.is_dir())
        if not addon_dirs:
            note("Keine Add-on-Quellordner vorhanden")
        for addon_dir in addon_dirs:
            passed = validate_addon(addon_dir)
            if not passed and args.quarantine:
                moved = quarantine_addon(addon_dir)
                if moved:
                    quarantined.append(moved.relative_to(ROOT).as_posix())
            # Keep findings from all add-ons in the final report.
            # validate_addon resets the lists, so collect each result below.

    write_report(report, quarantined)
    print(report.read_text(encoding="utf-8"))
    return 1 if ERRORS else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Unerwarteter Validator-Fehler: {exc}", file=sys.stderr)
        raise SystemExit(2)
