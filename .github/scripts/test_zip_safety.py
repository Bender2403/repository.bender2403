from __future__ import annotations

import ast
import io
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import zip_safety  # noqa: E402
from zip_safety import UnsafeAddonZip, extract_addon_zip


ADDON_ID = "plugin.video.sample"
ADDON_XML = (
    f'<addon id="{ADDON_ID}" name="Sample" version="1.0.0" '
    'provider-name="Tests"><extension point="xbmc.python.pluginsource" '
    'library="default.py"/></addon>'
)


def make_zip(entries: list[tuple[str, bytes | str, int | None]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value, mode in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, value)
    return output.getvalue()


class SafeZipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def valid_archive(self) -> bytes:
        return make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML, None),
            (f"{ADDON_ID}/default.py", "print('ok')\n", None),
        ])

    def test_valid_addon_is_extracted_and_archived(self) -> None:
        xml = extract_addon_zip(self.valid_archive(), self.root, ADDON_ID, "1.0.0")
        target = self.root / ADDON_ID
        self.assertIn(ADDON_ID, xml)
        self.assertEqual((target / "default.py").read_text(), "print('ok')\n")
        self.assertTrue((target / f"{ADDON_ID}-1.0.0.zip").is_file())

    def test_path_traversal_is_rejected_without_writing_outside_target(self) -> None:
        archive = make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML, None),
            (f"{ADDON_ID}/../../outside.txt", "bad", None),
        ])
        with self.assertRaises(UnsafeAddonZip):
            extract_addon_zip(archive, self.root, ADDON_ID, "1.0.0")
        self.assertFalse((self.root / "outside.txt").exists())
        self.assertFalse((self.root / ADDON_ID).exists())

    def test_symlink_is_rejected(self) -> None:
        archive = make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML, None),
            (f"{ADDON_ID}/link", "target", stat.S_IFLNK | 0o777),
        ])
        with self.assertRaises(UnsafeAddonZip):
            extract_addon_zip(archive, self.root, ADDON_ID, "1.0.0")

    def test_files_outside_addon_root_are_rejected(self) -> None:
        archive = make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML, None),
            ("unrelated/payload.txt", "bad", None),
        ])
        with self.assertRaises(UnsafeAddonZip):
            extract_addon_zip(archive, self.root, ADDON_ID, "1.0.0")

    def test_metadata_mismatch_is_rejected(self) -> None:
        archive = make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML.replace('version="1.0.0"', 'version="9.9.9"'), None),
        ])
        with self.assertRaises(UnsafeAddonZip):
            extract_addon_zip(archive, self.root, ADDON_ID, "1.0.0")


    def test_build_script_has_valid_python_syntax(self) -> None:
        source = (ROOT / "scripts" / "build_repo.py").read_text(encoding="utf-8")
        ast.parse(source, filename="scripts/build_repo.py")

    def test_file_size_limit_is_enforced(self) -> None:
        archive = make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML, None),
            (f"{ADDON_ID}/payload.bin", "12345", None),
        ])
        with patch.object(zip_safety, "MAX_FILE_SIZE", 4):
            with self.assertRaises(UnsafeAddonZip):
                extract_addon_zip(archive, self.root, ADDON_ID, "1.0.0")

    def test_entry_count_limit_is_enforced(self) -> None:
        with patch.object(zip_safety, "MAX_FILES", 1):
            with self.assertRaises(UnsafeAddonZip):
                extract_addon_zip(self.valid_archive(), self.root, ADDON_ID, "1.0.0")

    def test_compression_ratio_limit_is_enforced(self) -> None:
        archive = make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML, None),
            (f"{ADDON_ID}/payload.txt", "A" * 10000, None),
        ])
        with patch.object(zip_safety, "MAX_COMPRESSION_RATIO", 2):
            with self.assertRaises(UnsafeAddonZip):
                extract_addon_zip(archive, self.root, ADDON_ID, "1.0.0")

    def test_failed_replacement_preserves_existing_target(self) -> None:
        target = self.root / ADDON_ID
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_text("keep")
        bad = make_zip([
            (f"{ADDON_ID}/addon.xml", ADDON_XML, None),
            (f"{ADDON_ID}/../escape.txt", "bad", None),
        ])
        with self.assertRaises(UnsafeAddonZip):
            extract_addon_zip(bad, self.root, ADDON_ID, "1.0.0")
        self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
