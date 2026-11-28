import json
import os
import tempfile
import time

import xbmc
import xbmcaddon
import xbmcvfs


ADDON = xbmcaddon.Addon()
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
RESTART_PENDING_PATH = os.path.join(PROFILE_PATH, "update_pending_restart.json")


def _log(message, level=xbmc.LOGINFO):
    xbmc.log(f"OptiKlean: {message}", level)


def _ensure_profile_path():
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)


def _current_pid():
    try:
        return int(os.getpid())
    except Exception:
        return 0


def clear_restart_pending():
    try:
        if xbmcvfs.exists(RESTART_PENDING_PATH):
            return bool(xbmcvfs.delete(RESTART_PENDING_PATH))
    except Exception as exc:
        _log(f"Failed clearing restart-pending marker: {exc}", xbmc.LOGWARNING)
    return False


def set_restart_pending(commit_id="", version="", message=""):
    payload = {
        "pid": _current_pid(),
        "timestamp": int(time.time()),
        "commit_id": commit_id or "",
        "version": version or "",
        "message": message or "",
    }
    temp_path = None
    try:
        if (
            not os.path.isabs(PROFILE_PATH)
            or "://" in PROFILE_PATH
            or PROFILE_PATH.startswith(("//", "\\\\"))
        ):
            raise OSError("Restart marker requires a local profile path")
        _ensure_profile_path()
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".update-pending-", dir=PROFILE_PATH
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, RESTART_PENDING_PATH)
        temp_path = None
        _log("Persisted restart-pending marker", xbmc.LOGINFO)
        return True
    except Exception as exc:
        _log(f"Failed persisting restart-pending marker: {exc}", xbmc.LOGWARNING)
        return False
    finally:
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError as exc:
            _log(f"Failed cleaning restart-pending temporary file: {exc}", xbmc.LOGWARNING)


def get_restart_pending_state():
    try:
        if os.path.isabs(RESTART_PENDING_PATH) and "://" not in RESTART_PENDING_PATH:
            try:
                with open(RESTART_PENDING_PATH, "r", encoding="utf-8") as handle:
                    raw = handle.read()
            except FileNotFoundError:
                return {}
        else:
            if not xbmcvfs.exists(RESTART_PENDING_PATH):
                return {}
            with xbmcvfs.File(RESTART_PENDING_PATH, "r") as handle:
                raw = handle.read()
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict) or not payload:
            raise ValueError("Invalid restart-pending marker")
    except Exception as exc:
        _log(f"Failed reading restart-pending marker: {exc}", xbmc.LOGWARNING)
        return {"invalid": True}

    try:
        marker_pid = int(payload.get("pid", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        _log("Invalid PID in restart-pending marker", xbmc.LOGWARNING)
        return payload
    current_pid = _current_pid()
    if marker_pid and current_pid and marker_pid != current_pid:
        _log("Detected Kodi process restart; clearing restart-pending marker", xbmc.LOGINFO)
        if clear_restart_pending():
            return {}

    return payload
