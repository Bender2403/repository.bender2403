from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from zip_intake import quarantine_and_report


class QuarantineReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inbox = self.root / "eingang"
        self.quarantine = self.root / "quarantaene"
        self.inbox.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_report_uses_addon_id_and_zip_is_deleted_after_report(self) -> None:
        archive = self.inbox / "download.zip"
        archive.write_bytes(b"not a real zip")

        report = quarantine_and_report(
            archive, self.quarantine, "plugin.video.sample", "addon.xml fehlt"
        )

        self.assertEqual(report.name, "plugin.video.sample.txt")
        self.assertIn("ZIP-Datei: download.zip", report.read_text(encoding="utf-8"))
        self.assertIn("Fehler: addon.xml fehlt", report.read_text(encoding="utf-8"))
        self.assertFalse(archive.exists())
        self.assertEqual(list(self.quarantine.glob("*.zip")), [])

    def test_falls_back_to_zip_name_when_addon_id_is_unknown(self) -> None:
        archive = self.inbox / "broken-addon.zip"
        archive.write_bytes(b"broken")

        report = quarantine_and_report(archive, self.quarantine, None, "ZIP beschädigt")

        self.assertEqual(report.name, "broken-addon.txt")
        self.assertTrue(report.is_file())
        self.assertFalse(archive.exists())

    def test_multiple_failures_append_to_one_addon_report(self) -> None:
        first = self.inbox / "first.zip"
        second = self.inbox / "second.zip"
        first.write_bytes(b"one")
        second.write_bytes(b"two")

        report = quarantine_and_report(first, self.quarantine, "plugin.video.sample", "Fehler A")
        quarantine_and_report(second, self.quarantine, "plugin.video.sample", "Fehler B")

        content = report.read_text(encoding="utf-8")
        self.assertIn("Fehler A", content)
        self.assertIn("Fehler B", content)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())

    def test_zip_is_kept_if_report_cannot_be_created(self) -> None:
        archive = self.inbox / "broken.zip"
        archive.write_bytes(b"broken")
        self.quarantine.mkdir()
        (self.quarantine / "plugin.video.sample.txt").mkdir()

        with self.assertRaises(IsADirectoryError):
            quarantine_and_report(
                archive, self.quarantine, "plugin.video.sample", "Fehler"
            )

        self.assertTrue((self.quarantine / "broken.zip").is_file())
        self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
