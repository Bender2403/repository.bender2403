from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def make_addon_zip(path: Path, addon_id: str, version: str = "1.0.0") -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{addon_id}/addon.xml",
            f'<addon id="{addon_id}" version="{version}" name="Test"/>',
        )
        archive.writestr(f"{addon_id}/default.py", "def run():\n    return True\n")


class BuildRepoZipIntakeIntegrationTests(unittest.TestCase):
    def test_build_processes_valid_zip_and_quarantines_bad_and_duplicate_zips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "scripts").mkdir()
            (project / "addons" / "repository.test").mkdir(parents=True)
            (project / "arbeitsordner" / "eingang").mkdir(parents=True)

            shutil.copy2(SCRIPTS / "build_repo.py", project / "scripts" / "build_repo.py")
            shutil.copy2(SCRIPTS / "zip_safety.py", project / "scripts" / "zip_safety.py")
            shutil.copy2(SCRIPTS / "zip_intake.py", project / "scripts" / "zip_intake.py")

            (project / "addons" / "repository.test" / "addon.xml").write_text(
                '<addon id="repository.test" version="1.0.0" name="Test repository"/>',
                encoding="utf-8",
            )

            inbox = project / "arbeitsordner" / "eingang"
            make_addon_zip(inbox / "valid.zip", "plugin.video.valid")
            (inbox / "broken-archive.zip").write_bytes(b"not a zip archive")
            make_addon_zip(inbox / "duplicate-one.zip", "plugin.video.duplicate")
            make_addon_zip(inbox / "duplicate-two.zip", "plugin.video.duplicate")

            completed = subprocess.run(
                [sys.executable, str(project / "scripts" / "build_repo.py")],
                cwd=project,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"Build fehlgeschlagen.\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}",
            )

            self.assertTrue((project / "plugin.video.valid" / "addon.xml").is_file())
            self.assertTrue(
                (project / "plugin.video.valid" / "plugin.video.valid-1.0.0.zip").is_file()
            )
            self.assertTrue((project / "repository.test" / "repository.test-1.0.0.zip").is_file())

            self.assertFalse(any(inbox.glob("*.zip")))
            quarantine = project / "arbeitsordner" / "quarantaene"
            self.assertFalse(any(quarantine.glob("*.zip")))

            broken_report = quarantine / "broken-archive.txt"
            duplicate_report = quarantine / "plugin.video.duplicate.txt"
            self.assertTrue(broken_report.is_file())
            self.assertIn("File is not a zip file", broken_report.read_text(encoding="utf-8"))
            self.assertTrue(duplicate_report.is_file())
            duplicate_content = duplicate_report.read_text(encoding="utf-8")
            self.assertIn("duplicate-one.zip", duplicate_content)
            self.assertIn("duplicate-two.zip", duplicate_content)
            self.assertEqual(duplicate_content.count("Fehler:"), 2)

            self.assertTrue((project / "addons.xml").is_file())
            self.assertTrue((project / "addons.xml.md5").is_file())
            self.assertTrue((project / "_site" / "addons.xml").is_file())


if __name__ == "__main__":
    unittest.main()
