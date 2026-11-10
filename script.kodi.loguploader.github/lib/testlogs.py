# -*- coding: utf-8 -*-
"""Validation helpers for Kodi Diag test log selection."""
import os


def list_test_log_paths(test_dir, listdir, exists, size, max_size):
    """List valid .log files in the dedicated test folder, sorted by filename."""
    root = os.path.realpath(test_dir)
    try:
        names = listdir(test_dir)
    except (OSError, IOError):
        return []

    valid = []
    seen = set()
    for name in names:
        if not isinstance(name, str) or not name.lower().endswith('.log'):
            continue
        path = os.path.realpath(os.path.join(test_dir, name))
        try:
            if os.path.commonpath((root, path)) != root or path == root:
                continue
        except (ValueError, OSError):
            continue
        key = os.path.normcase(path)
        if key in seen or not os.path.isfile(path) or not exists(path):
            continue
        try:
            file_size = size(path)
        except Exception:
            continue
        if file_size <= 0 or file_size > max_size:
            continue
        seen.add(key)
        valid.append(path)

    return sorted(valid, key=lambda item: os.path.basename(item).lower())


def validate_test_log_paths(paths, test_dir, exists, size, max_size, max_files=6):
    """Return unique, existing .log files located inside the dedicated test directory."""
    root = os.path.realpath(test_dir)
    valid = []
    seen = set()
    for raw_path in paths or []:
        if not isinstance(raw_path, str) or not raw_path.lower().endswith('.log'):
            continue
        path = os.path.realpath(raw_path)
        try:
            if os.path.commonpath((root, path)) != root or path == root:
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
