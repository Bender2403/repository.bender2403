from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import check_kodi_versions as compatibility


class KodiVersionCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addons = self.root / "addons"
        self.addons.mkdir()
        self.reports = self.root / "reports"
        self.addon = self.addons / "plugin.video.sample"
        self.addon.mkdir()
        (self.addon / "addon.xml").write_text(
            '<addon id="plugin.video.sample" name="Sample" version="1.0.0" provider-name="Test"/>',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch.object(compatibility.subprocess, "run")
    def test_runs_official_checker_for_all_three_kodi_branches(self, run) -> None:
        run.return_value = SimpleNamespace(returncode=0, stdout="INFO: clean")
        result = compatibility.run_checks(self.addons, self.reports, "kodi-addon-checker")

        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 3)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual([commands[i][commands[i].index("--branch") + 1] for i in range(3)],
                         ["nexus", "omega", "piers"])
        for branch in compatibility.KODI_BRANCHES:
            report = self.reports / f"kodi-compatibility-{branch}.txt"
            self.assertTrue(report.is_file())
            self.assertIn("RESULT: PASSED", report.read_text(encoding="utf-8"))

    @patch.object(compatibility.subprocess, "run")
    def test_checker_error_fails_only_the_affected_version_report(self, run) -> None:
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout="Nexus clean"),
            SimpleNamespace(returncode=1, stdout="Omega API problem"),
            SimpleNamespace(returncode=0, stdout="Piers clean"),
        ]
        result = compatibility.run_checks(self.addons, self.reports, "kodi-addon-checker")

        self.assertEqual(result, 1)
        self.assertIn("RESULT: PASSED", (self.reports / "kodi-compatibility-nexus.txt").read_text())
        self.assertIn("RESULT: FAILED", (self.reports / "kodi-compatibility-omega.txt").read_text())
        self.assertIn("RESULT: PASSED", (self.reports / "kodi-compatibility-piers.txt").read_text())

    @patch.object(compatibility.subprocess, "run")
    def test_no_addons_creates_reports_without_failing(self, run) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        result = compatibility.run_checks(empty, self.reports, "kodi-addon-checker")

        self.assertEqual(result, 0)
        run.assert_not_called()
        for branch in compatibility.KODI_BRANCHES:
            self.assertTrue((self.reports / f"kodi-compatibility-{branch}.txt").is_file())


if __name__ == "__main__":
    unittest.main()
