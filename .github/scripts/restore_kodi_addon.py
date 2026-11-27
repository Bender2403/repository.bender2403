#!/usr/bin/env python3
"""Restore repaired add-on sources from _quarantine after revalidation."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
import validate_kodi_addon as validator  # noqa: E402

ADDONS = ROOT / "addons"
QUARANTINE = ROOT / "_quarantine"


def restore_one(addon_dir: Path) -> tuple[bool, str]:
    passed = validator.validate_addon(addon_dir)
    errors = list(validator.ERRORS)
    warnings = list(validator.WARNINGS)
    notes = list(validator.NOTES)

    if not passed:
        return False, f"{addon_dir.relative_to(ROOT)}: validation failed: " + "; ".join(errors)

    # Read the ID from the validated XML; never use an unchecked value as a path.
    root = validator.parse_xml(addon_dir / "addon.xml")
    addon_id = root.attrib.get("id", "").strip() if root is not None else ""
    if not addon_id or addon_id != addon_dir.name:
        return False, f"{addon_dir.relative_to(ROOT)}: Add-on-ID fehlt oder passt nicht zum Quarantäneordner"

    target = ADDONS / addon_id
    if target.exists():
        return False, f"{addon_dir.relative_to(ROOT)}: Ziel {target.relative_to(ROOT)} existiert bereits; nichts überschrieben"

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(addon_dir), str(target))
    return True, f"{addon_dir.relative_to(ROOT)} -> {target.relative_to(ROOT)}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="kodi-addon-restore-report.txt")
    args = parser.parse_args()
    report = Path(args.report).resolve()

    restored: list[str] = []
    remaining: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    if not QUARANTINE.is_dir():
        notes.append("Kein _quarantine-Verzeichnis vorhanden.")
    else:
        for addon_dir in sorted(p for p in QUARANTINE.iterdir() if p.is_dir()):
            ok, message = restore_one(addon_dir)
            (restored if ok else remaining).append(message)
            errors.extend(validator.ERRORS)
            warnings.extend(validator.WARNINGS)
            notes.extend(validator.NOTES)
            if not ok and not validator.ERRORS:
                errors.append(message)

    lines = [
        "Kodi Add-on restore report", "",
        f"Restored: {len(restored)}",
        f"Remaining in quarantine: {len(remaining)}",
        f"Errors: {len(errors)}",
        f"Warnings: {len(warnings)}", "",
    ]
    for title, items in (
        ("RESTORED", restored), ("REMAINING", remaining),
        ("ERRORS", errors), ("WARNINGS", warnings), ("NOTES", notes),
    ):
        if items:
            lines += [title, "-" * 60, *[f"- {item}" for item in items], ""]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report.read_text(encoding="utf-8"))
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Unerwarteter Restore-Fehler: {exc}", file=sys.stderr)
        raise SystemExit(2)
