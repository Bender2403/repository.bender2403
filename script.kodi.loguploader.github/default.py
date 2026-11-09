# -*- coding: utf-8 -*-
"""Kodi script entry point."""
from lib import loguploader
from lib.systeminfo import build_system_report


def _system_report():
    """Collect Kodi and device information using platform-appropriate APIs."""
    try:
        android = bool(loguploader.xbmc.getCondVisibility('System.Platform.Android'))
    except Exception:
        android = False
    try:
        kodi_version = loguploader.xbmc.getInfoLabel('System.BuildVersion')
    except Exception:
        kodi_version = ''
    return build_system_report(loguploader.ADDON_VERSION, kodi_version, android)


# Keep the uploader's existing package/upload flow and replace only its
# system-information provider.
loguploader._system_report = _system_report

if __name__ == '__main__':
    loguploader.main()
