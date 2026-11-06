# -*- coding: utf-8 -*-
"""Kodi Logfile Uploader: GitHub by default, paste.kodi.tv as fallback."""
import base64
import datetime
import os
import re

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_VERSION = ADDON.getAddonInfo('version')
LOG_DIR = xbmcvfs.translatePath('special://logpath')
LOG_FILE = os.path.join(LOG_DIR, 'kodi.log')
PASTE_URL = 'https://paste.kodi.tv/'
API_ROOT = 'https://api.github.com'
TIMEOUT = 30
MAX_LOG_SIZE = 2_000_000

REDACTIONS = [
    (re.compile(r'(?i)(://)[^/@\s]+:[^/@\s]+@'), r'\1USER:PASSWORD@'),
    (re.compile(r'(?is)<user>.*?</user>'), '<user>USER</user>'),
    (re.compile(r'(?is)<pass>.*?</pass>'), '<pass>PASSWORD</pass>'),
    (re.compile(r'(?i)(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(cookie\s*[:=]\s*)[^\r\n]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(\b(?:access_token|refresh_token|token|api[_-]?key|password|passwd|secret)\b\s*[=:]\s*)["\']?[^\s&"\']+'), r'\1[REDACTED]'),
]

def _log(message, level=xbmc.LOGINFO):
    xbmc.log('%s: %s' % (ADDON_ID, message), level)

def _clean_log(content):
    for pattern, replacement in REDACTIONS:
        content = pattern.sub(replacement, content)
    return content

def _read_log():
    if not xbmcvfs.exists(LOG_FILE):
        raise RuntimeError('kodi.log wurde nicht gefunden.')
    handle = xbmcvfs.File(LOG_FILE)
    try:
        if handle.size() > MAX_LOG_SIZE:
            raise RuntimeError('Die Logdatei ist größer als 2 MB.')
        data = handle.read()
    finally:
        handle.close()
    if not data:
        raise RuntimeError('Die Logdatei ist leer.')
    if not isinstance(data, str):
        data = data.decode('utf-8', 'replace')
    return _clean_log(data)

def _github_upload(content):
    token = ADDON.getSetting('github_token').strip()
    repo = ADDON.getSetting('github_repo').strip() or 'Bender2403/kodi-rakuten-tv-addon'
    branch = ADDON.getSetting('github_branch').strip() or 'kodi-logs'
    if not token:
        raise RuntimeError('GitHub-Token fehlt. Bitte in den Add-on-Einstellungen eintragen.')
    if not re.match(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$', repo):
        raise RuntimeError('Ungültiger Repository-Name. Erwartet wird owner/repository.')
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    filename = 'kodi-%s.log' % stamp
    path = 'logs/' + filename
    url = '%s/repos/%s/contents/%s' % (API_ROOT, repo, path)
    payload = {
        'message': 'Upload Kodi log %s' % stamp,
        'branch': branch,
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii'),
    }
    headers = {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': '%s/%s' % (ADDON_ID, ADDON_VERSION),
    }
    response = requests.put(url, json=payload, headers=headers, timeout=TIMEOUT)
    if response.status_code not in (200, 201):
        try:
            detail = response.json().get('message', '')
        except Exception:
            detail = ''
        raise RuntimeError('GitHub-Upload fehlgeschlagen (HTTP %s): %s' % (response.status_code, detail or response.text[:300]))
    return 'https://github.com/%s/blob/%s/%s' % (repo, branch, path)

def _paste_upload(content):
    headers = {'User-Agent': '%s: %s' % (ADDON_ID, ADDON_VERSION)}
    response = requests.post(PASTE_URL + 'documents', data=content.encode('utf-8'), headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    result = response.json()
    if 'key' not in result:
        raise RuntimeError(result.get('message', 'paste.kodi.tv hat keine Paste-ID zurückgegeben.'))
    return PASTE_URL + result['key']

def main():
    dialog = xbmcgui.Dialog()
    try:
        content = _read_log()
        target = ADDON.getSetting('upload_target') or 'github'
        destination = _paste_upload(content) if target == 'paste' else _github_upload(content)
        _log('Logdatei erfolgreich hochgeladen: %s' % destination)
        dialog.ok(ADDON_NAME, 'Upload erfolgreich.\n\n%s' % destination)
    except Exception as exc:
        _log('Upload fehlgeschlagen: %s' % exc, xbmc.LOGERROR)
        dialog.ok(ADDON_NAME, 'Upload fehlgeschlagen:\n\n%s' % str(exc))
