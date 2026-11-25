#!/usr/bin/env python3
"""Validate Kodi addon sources and write a human-readable report.

The script never raises an unhandled exception. All findings are collected,
printed and written to a report file. Exit code 1 means at least one error
was found, but the GitHub workflow can choose to ignore that exit code.
"""

from __future__ import annotations

import argparse
import ast
import compileall
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDONS = ROOT / 'addons'
errors: list[str] = []
warnings: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def note(message: str) -> None:
    notes.append(message)


def parse_xml(path: Path):
    try:
        return ET.parse(path)
    except ET.ParseError as exc:
        fail(f'{path}: invalid XML: {exc}')
        return None


def validate_addon_xml(addon_dir: Path) -> str | None:
    path = addon_dir / 'addon.xml'
    if not path.is_file():
        fail(f'{path}: missing addon.xml')
        return None

    tree = parse_xml(path)
    if tree is None:
        return None

    root = tree.getroot()
    addon_id = root.attrib.get('id', '')
    version = root.attrib.get('version', '')

    if not addon_id:
        fail(f'{path}: missing addon id')
    if not version:
        fail(f'{path}: missing addon version')
    if root.attrib.get('provider-name') is None:
        fail(f'{path}: missing provider-name')

    requires = root.find('requires')
    if requires is None:
        fail(f'{path}: missing requires element')
    else:
        imports = {
            item.attrib.get('addon')
            for item in requires.findall('import')
        }
        if 'xbmc.python' not in imports:
            fail(f'{path}: missing xbmc.python dependency')

    extension = root.find("extension[@point='xbmc.python.script']")
    if extension is None:
        fail(f'{path}: missing xbmc.python.script extension')
    else:
        library = extension.attrib.get('library', '')
        if not library:
            fail(f'{path}: script extension has no library')
        elif not (addon_dir / library).is_file():
            fail(f'{path}: script library does not exist: {library}')

    return addon_id or None


def validate_python(addon_dir: Path, addon_id: str | None) -> set[str]:
    py_files = list(addon_dir.rglob('*.py'))
    if not py_files:
        fail(f'{addon_dir}: no Python files found')
        return set()

    if not compileall.compile_dir(
        str(addon_dir),
        quiet=2,
        force=True,
        rx=re.compile(r'.*\.py$'),
    ):
        fail(f'{addon_dir}: Python compilation failed')

    setting_ids: set[str] = set()
    label_ids: set[str] = set()

    for path in py_files:
        try:
            source = path.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(path))
        except (UnicodeDecodeError, SyntaxError) as exc:
            fail(f'{path}: Python syntax error: {exc}')
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                method = node.func.attr
                if method in {
                    'getSetting',
                    'getSettingInt',
                    'getSettingBool',
                    'getSettingString',
                    'getSettingNumber',
                } and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        setting_ids.add(first.value)
                if method == 'getString' and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, int):
                        label_ids.add(str(first.value))

    if addon_id:
        settings_path = addon_dir / 'resources' / 'settings.xml'
        if settings_path.is_file():
            content = settings_path.read_text(encoding='utf-8', errors='replace')
            if f'id="{addon_id}"' not in content:
                warn(
                    f'{settings_path}: section id does not match addon id '
                    f'({addon_id})'
                )

    return setting_ids | label_ids


def validate_settings(addon_dir: Path, addon_id: str | None) -> set[str]:
    path = addon_dir / 'resources' / 'settings.xml'
    if not path.is_file():
        fail(f'{path}: missing settings.xml')
        return set()

    tree = parse_xml(path)
    if tree is None:
        return set()

    root = tree.getroot()
    if root.tag != 'settings':
        fail(f'{path}: root element must be settings')

    version = root.attrib.get('version', '')
    if version != '1':
        fail(f'{path}: settings version must be 1 for the modern Kodi format')

    sections = root.findall('section')
    if not sections:
        fail(f'{path}: missing section element')

    ids: set[str] = set()
    for section in sections:
        section_id = section.attrib.get('id', '')
        if not section_id:
            fail(f'{path}: section without id')
        elif addon_id and section_id != addon_id:
            warn(
                f'{path}: section id {section_id!r} does not match addon id '
                f'{addon_id!r}'
            )

        categories = section.findall('category')
        if not categories:
            fail(f'{path}: section {section_id!r} has no category')

        for category in categories:
            category_id = category.attrib.get('id', '')
            if not category_id:
                fail(f'{path}: category without id')

            groups = category.findall('group')
            if not groups:
                fail(f'{path}: category {category_id!r} has no group')

            for setting in category.iter('setting'):
                setting_id = setting.attrib.get('id', '')
                if not setting_id:
                    fail(f'{path}: setting without id')
                    continue
                ids.add(setting_id)

                if setting.find('default') is None:
                    fail(f'{path}: setting {setting_id!r} has no default element')
                if setting.find('control') is None:
                    fail(f'{path}: setting {setting_id!r} has no control element')

    return ids


def read_po_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    try:
        content = path.read_text(encoding='utf-8')
    except UnicodeDecodeError as exc:
        fail(f'{path}: invalid UTF-8: {exc}')
        return ids

    msgid_pattern = re.compile(r'^msgid\s+"([^"]*)"\s*$', re.MULTILINE)
    for match in msgid_pattern.finditer(content):
        value = match.group(1)
        if value.isdigit():
            ids.add(value)

    if not ids:
        fail(f'{path}: no numeric msgid entries found')

    return ids


def validate_translations(addon_dir: Path, used_ids: set[str]) -> None:
    language_dir = addon_dir / 'resources' / 'language'
    if not language_dir.is_dir():
        fail(f'{language_dir}: missing language directory')
        return

    english = language_dir / 'resource.language.en_gb' / 'strings.po'
    german = language_dir / 'resource.language.de_de' / 'strings.po'

    if not english.is_file():
        fail(f'{english}: missing English fallback language file')
    else:
        english_ids = read_po_ids(english)
        missing = used_ids - english_ids
        if missing:
            fail(
                f'{english}: missing labels used by Python: '
                f'{", ".join(sorted(missing))}'
            )

    if not german.is_file():
        warn(f'{german}: German translation is missing')
    else:
        german_ids = read_po_ids(german)
        missing = used_ids - german_ids
        if missing:
            warn(
                f'{german}: missing labels used by Python: '
                f'{", ".join(sorted(missing))}'
            )


def validate_kodi_compatibility(addon_dir: Path) -> None:
    path = addon_dir / 'addon.xml'
    if not path.is_file():
        return

    content = path.read_text(encoding='utf-8', errors='replace')
    if 'xbmc.python' not in content:
        return

    match = re.search(
        r'<import\s+addon="xbmc.python"\s+version="([^"]+)"',
        content,
    )
    if not match:
        fail(f'{path}: xbmc.python dependency has no version')
        return

    version = match.group(1)
    if not version.startswith('3.'):
        fail(
            f'{path}: xbmc.python version {version!r} is not compatible with '
            'Kodi 21 or 22; use 3.0.0 or newer'
        )
    else:
        note(
            f'{path}: xbmc.python {version} is compatible with Kodi 21 Omega '
            'and Kodi 22 Piers'
        )


def write_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'Kodi addon validation report',
        '',
        f'Errors: {len(errors)}',
        f'Warnings: {len(warnings)}',
        f'Notes: {len(notes)}',
        '',
    ]

    if errors:
        lines.extend(['ERRORS', '-' * 60])
        lines.extend(f'- {item}' for item in errors)
        lines.append('')

    if warnings:
        lines.extend(['WARNINGS', '-' * 60])
        lines.extend(f'- {item}' for item in warnings)
        lines.append('')

    if notes:
        lines.extend(['NOTES', '-' * 60])
        lines.extend(f'- {item}' for item in notes)
        lines.append('')

    lines.append('RESULT: ' + ('FAILED' if errors else 'PASSED'))
    path.write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--report',
        default='kodi-addon-validation.txt',
        help='Path of the validation report file',
    )
    args = parser.parse_args()
    report_path = Path(args.report).resolve()

    if not ADDONS.is_dir():
        fail(f'{ADDONS}: addons directory not found')
    else:
        addon_dirs = [item for item in ADDONS.iterdir() if item.is_dir()]
        if not addon_dirs:
            fail(f'{ADDONS}: no addon directories found')

        for addon_dir in sorted(addon_dirs):
            note(f'Validating {addon_dir.name} ...')
            addon_id = validate_addon_xml(addon_dir)
            used_ids = validate_python(addon_dir, addon_id)
            setting_ids = validate_settings(addon_dir, addon_id)
            used_ids |= setting_ids
            validate_translations(addon_dir, used_ids)
            validate_kodi_compatibility(addon_dir)

    write_report(report_path)
    print(report_path.read_text(encoding='utf-8'))
    return 1 if errors else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        report_path = Path(sys.argv[sys.argv.index('--report') + 1]) if '--report' in sys.argv else Path('kodi-addon-validation.txt')
        report_path.write_text(
            'Kodi addon validation report\n\n'
            'UNEXPECTED SCRIPT ERROR\n'
            f'{exc}\n',
            encoding='utf-8',
        )
        print(f'Unexpected validation error: {exc}', file=sys.stderr)
        raise SystemExit(1)
