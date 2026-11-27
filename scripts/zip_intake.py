"""Helpers for processing and reporting rejected Kodi add-on ZIP files."""
from __future__ import annotations

import re
import shutil
from pathlib import Path


_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\\Z")


def _report_name(addon_id: str | None, zip_path: Path) -> str:
    """Return a safe report basename, preferring the add-on ID."""
    candidate = addon_id or zip_path.stem
    if candidate in {".", ".."} or not _SAFE_NAME.fullmatch(candidate):
        candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._-")
    return candidate or "unbekannt"


def quarantine_and_report(
    zip_path: Path,
    quarantine_dir: Path,
    addon_id: str | None,
    error: Exception | str,
) -> Path:
    """Move a rejected ZIP, write its report, then delete the ZIP.

    The ZIP is retained in quarantine if report creation fails. Existing reports
    for the same add-on are appended to rather than overwritten.
    """
    zip_path = Path(zip_path)
    quarantine_dir = Path(quarantine_dir)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    quarantined_zip = quarantine_dir / zip_path.name
    counter = 1
    while quarantined_zip.exists():
        quarantined_zip = quarantine_dir / f"{zip_path.stem}-{counter}{zip_path.suffix}"
        counter += 1

    shutil.move(str(zip_path), str(quarantined_zip))

    report_path = quarantine_dir / f"{_report_name(addon_id, zip_path)}.txt"
    report_text = (
        f"Add-on: {addon_id or 'nicht ermittelbar'}\\n"
        f"ZIP-Datei: {zip_path.name}\\n"
        f"Fehler: {error}\\n"
        "----------------------------------------\\n"
    )
    with report_path.open("a", encoding="utf-8", newline="\\n") as report:
        report.write(report_text)

    # Delete only after the report has been successfully written and closed.
    quarantined_zip.unlink()
    return report_path
