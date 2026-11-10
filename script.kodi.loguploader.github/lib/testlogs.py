# -*- coding: utf-8 -*-
"""Validation helpers for Kodi Diag test log selection."""
import os


def validate_test_log_paths(paths, temp_dir, exists, size, max_size, max_files=6):
    """Return unique, existing .log files located inside Kodi's temp directory."""
    root = os.path.realpath(temp_dir)
    valid = []
    seen = set()
    for raw_path in paths or []:
        if not isinstance(raw_path, str) or not raw_path.lower().endswith('.log'):
            continue
        path = os.path.realpath(raw_path)
        try:
            if os.path.commonpath((root, path)) != root:
                continue
        except (ValueError, OSError):
            continue
        key = os.path.normcase(path)
        if key in seen or not exists(path):
            continue
        try:
            file_size = size(path)
        except Exception:
            continue
        if file_size <= 0 or file_size > max_size:
            continue
        seen.add(key)
        valid.append(path)
        if len(valid) >= max_files:
            break
    return valid
