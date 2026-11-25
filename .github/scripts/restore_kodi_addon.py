#!/usr/bin/env python3
"""Restore repaired Kodi addons from _quarantine to addons.

Each quarantined addon is validated again. Only addons without validation
errors are moved back to addons/. Broken addons remain in _quarantine.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.github' / 'scripts'))

import validate_kodi_addon as validator

ADDONS = ROOT / 'addons'
QUARANTINE = ROOT / '_quarantine'


def validate_quarantined_addon(addon_dir: Path) -> tuple[bool, str | None]:
    validator.errors.clear()
    validator.warnings.clear()
    validator.notes.clear()

    validator.note(f'Validating quarantined addon {addon_dir.name} ...')
    addon_id = validator.validate_addon_xml(addon_dir)
    used_ids = validator.validate_python(addon_dir, addon_id)
    setting_ids = validator.validate_settings(addon_dir, addon_id)
    used_ids |= setting_ids
    validator.validate_translations(addon_dir, used_ids)
    validator.validate_kodi_compatibility(addon_dir)

    passed = not validator.errors
    return passed, addon_id


def restore(addon_dir: Path, addon_id: str | None) -> Path:
    target = ADDONS / (addon_id or addon_dir.name)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(addon_dir), str(target))
    validator.note(
        f'{addon_dir.name}: restored to {target.relative_to(ROOT)}'
    )
    return target


def write_report(path: Path, restored: list[str], still_broken: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'Kodi addon restore report',
        '',
        f'Restored addons: {len(restored)}',
        f'Still broken addons: {len(still_broken)}',
        f'Warnings: {len(validator.warnings)}',
        f'Notes: {len(validator.notes)}',
        '',
    ]

    if restored:
        lines.extend(['RESTORED ADDONS', '-' * 60])
        lines.extend(f'- {item}' for item in restored)
        lines.append('')

    if still_broken:
        lines.extend(['STILL BROKEN ADDONS', '-' * 60])
        lines.extend(f'- {item}' for item in still_broken)
        lines.append('')

    if validator.errors:
        lines.extend(['ERRORS', '-' * 60])
        lines.extend(f'- {item}' for item in validator.errors)
        lines.append('')

    if validator.warnings:
        lines.extend(['WARNINGS', '-' * 60])
        lines.extend(f'- {item}' for item in validator.warnings)
        lines.append('')

    if validator.notes:
        lines.extend(['NOTES', '-' * 60])
        lines.extend(f'- {item}' for item in validator.notes)
        lines.append('')

    path.write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--report',
        default='kodi-addon-restore-report.txt',
        help='Path of the restore report file',
    )
    args = parser.parse_args()
    report_path = Path(args.report).resolve()

    restored: list[str] = []
    still_broken: list[str] = []

    if not QUARANTINE.is_dir():
        validator.note(f'{QUARANTINE}: no quarantine directory found')
    else:
        addon_dirs = [item for item in QUARANTINE.iterdir() if item.is_dir()]
        if not addon_dirs:
            validator.note(f'{QUARANTINE}: no quarantined addons found')

        for addon_dir in sorted(addon_dirs):
            passed, addon_id = validate_quarantined_addon(addon_dir)
            if passed:
                target = restore(addon_dir, addon_id)
                restored.append(target.relative_to(ROOT).as_posix())
            else:
                still_broken.append(addon_dir.relative_to(ROOT).as_posix())

    write_report(report_path, restored, still_broken)
    print(report_path.read_text(encoding='utf-8'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        report_path = Path(sys.argv[sys.argv.index('--report') + 1]) if '--report' in sys.argv else Path('kodi-addon-restore-report.txt')
        report_path.write_text(
            'Kodi addon restore report\n\n'
            'UNEXPECTED SCRIPT ERROR\n'
            f'{exc}\n',
            encoding='utf-8',
        )
        print(f'Unexpected restore error: {exc}', file=sys.stderr)
        raise SystemExit(1)
