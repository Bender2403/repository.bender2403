from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import validate_kodi_addon as validator
import restore_kodi_addon as restore


def write_plugin(folder: Path, *, library: str = "default.py", source: str = "pass\n") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "addon.xml").write_text(
        f'<addon id="{folder.name}" name="Test" version="1.0.0" provider-name="Test">'
        '<requires><import addon="xbmc.python" version="3.0.0"/></requires>'
        f'<extension point="xbmc.python.pluginsource" library="{library}"><provides>video</provides></extension>'
        '</addon>',
        encoding="utf-8",
    )
    if library and ".." not in library:
        target = folder / library
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")


class ValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_plugin_without_settings_or_translations_is_valid(self) -> None:
        addon = self.root / "plugin.video.sample"
        write_plugin(addon)
        self.assertTrue(validator.validate_addon(addon), validator.ERRORS)

    def test_non_python_resource_addon_is_valid(self) -> None:
        addon = self.root / "resource.images.sample"
        addon.mkdir()
        (addon / "addon.xml").write_text(
            '<addon id="resource.images.sample" name="Images" version="1.0" provider-name="Test">'
            '<extension point="kodi.resource.images"/></addon>',
            encoding="utf-8",
        )
        self.assertTrue(validator.validate_addon(addon), validator.ERRORS)

    def test_python_syntax_error_fails(self) -> None:
        addon = self.root / "plugin.video.syntax"
        write_plugin(addon, source="def broken(:\n")
        self.assertFalse(validator.validate_addon(addon))
        self.assertTrue(any("Python-Fehler" in item for item in validator.ERRORS))

    def test_library_path_traversal_fails(self) -> None:
        addon = self.root / "plugin.video.traversal"
        write_plugin(addon, library="../outside.py")
        self.assertFalse(validator.validate_addon(addon))
        self.assertTrue(any("unsicherer library-Pfad" in item for item in validator.ERRORS))

    def test_quarantine_moves_folder_without_overwriting(self) -> None:
        addons = self.root / "addons"
        quarantine = self.root / "_quarantine"
        addon = addons / "plugin.video.bad"
        addon.mkdir(parents=True)
        with patch.object(validator, "QUARANTINE", quarantine):
            moved = validator.quarantine_addon(addon)
        self.assertEqual(moved, quarantine / addon.name)
        self.assertTrue(moved.is_dir())
        self.assertFalse(addon.exists())

    def test_restore_succeeds_after_revalidation(self) -> None:
        addons = self.root / "addons"
        quarantine = self.root / "_quarantine"
        addon = quarantine / "plugin.video.fixed"
        write_plugin(addon)
        with (
            patch.object(restore, "ROOT", self.root),
            patch.object(restore, "ADDONS", addons),
            patch.object(restore, "QUARANTINE", quarantine),
        ):
            ok, message = restore.restore_one(addon)
        self.assertTrue(ok, message)
        self.assertTrue((addons / addon.name / "addon.xml").is_file())
        self.assertFalse(addon.exists())

    def test_restore_never_overwrites_existing_addon(self) -> None:
        addons = self.root / "addons"
        quarantine = self.root / "_quarantine"
        addon = quarantine / "plugin.video.fixed"
        write_plugin(addon)
        existing = addons / addon.name
        existing.mkdir(parents=True)
        marker = existing / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with (
            patch.object(restore, "ROOT", self.root),
            patch.object(restore, "ADDONS", addons),
            patch.object(restore, "QUARANTINE", quarantine),
        ):
            ok, message = restore.restore_one(addon)
        self.assertFalse(ok)
        self.assertIn("existiert bereits", message)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertTrue(addon.is_dir())


if __name__ == "__main__":
    unittest.main()
