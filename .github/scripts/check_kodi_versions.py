#!/usr/bin/env python3
"""Run the official Kodi add-on checker against Nexus, Omega and Piers."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KODI_BRANCHES = ("nexus", "omega", "piers")


def run_checks(addons_dir: Path, report_dir: Path, checker: str) -> int:
    addon_dirs = sorted(
        path for path in addons_dir.iterdir()
        if path.is_dir() and (path / "addon.xml").is_file()
    ) if addons_dir.is_dir() else []

    report_dir.mkdir(parents=True, exist_ok=True)
    if not addon_dirs:
        for branch in KODI_BRANCHES:
            (report_dir / f"kodi-compatibility-{branch}.txt").write_text(
                f"Kodi {branch.title()} compatibility report\n"
                "No add-on source directories with addon.xml were found.\n",
                encoding="utf-8",
            )
        print("No add-on source directories found; compatibility check skipped.")
        return 0

    failures = 0
    for branch in KODI_BRANCHES:
        report_path = report_dir / f"kodi-compatibility-{branch}.txt"
        lines = [
            f"Kodi {branch.title()} compatibility report",
            f"Target Kodi branch: {branch}",
            f"Add-ons checked: {len(addon_dirs)}",
            "",
        ]
        branch_failures = 0

        for addon_dir in addon_dirs:
            lines.extend([f"=== {addon_dir.name} ===", ""])
            with tempfile.TemporaryDirectory(prefix=f"kodi-check-{branch}-") as workdir:
                command = [
                    checker,
                    str(addon_dir.resolve()),
                    "--branch",
                    branch,
                    "--enable-debug-log",
                ]
                try:
                    result = subprocess.run(
                        command,
                        cwd=workdir,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    output = result.stdout or ""
                    debug_log = Path(workdir) / "kodi-addon-checker.log"
                    if debug_log.is_file():
                        log_text = debug_log.read_text(encoding="utf-8", errors="replace")
                        if log_text and log_text not in output:
                            output += "\n--- kodi-addon-checker.log ---\n" + log_text
                    lines.append(output.rstrip() or "(Checker produced no output.)")
                    if result.returncode:
                        branch_failures += 1
                        lines.append(f"CHECK RESULT: FAILED (exit {result.returncode})")
                    else:
                        lines.append("CHECK RESULT: PASSED (no checker errors)")
                except OSError as exc:
                    branch_failures += 1
                    lines.append(f"CHECK RESULT: FAILED (could not start checker: {exc})")
            lines.append("")

        failures += branch_failures
        lines.extend([
            "",
            f"Add-ons with checker errors: {branch_failures}",
            "RESULT: " + ("FAILED" if branch_failures else "PASSED"),
        ])
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{branch.title()}: {branch_failures} add-on(s) with checker errors; report: {report_path}")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addons-dir", type=Path, default=Path("addons"))
    parser.add_argument("--report-dir", type=Path, default=Path("kodi-compatibility-reports"))
    parser.add_argument("--checker", default="kodi-addon-checker")
    args = parser.parse_args()
    return run_checks(args.addons_dir.resolve(), args.report_dir.resolve(), args.checker)


if __name__ == "__main__":
    raise SystemExit(main())
