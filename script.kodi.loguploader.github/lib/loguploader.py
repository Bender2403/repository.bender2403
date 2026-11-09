# -*- coding: utf-8 -*-
"""Kodi Logfile Uploader with optional Kodi-wide diagnostics."""
import base64
import datetime
import io
import json
import os
import re
import zipfile

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
TEMP_DIR = xbmcvfs.translatePath('special://temp')
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE_DIR, 'diagnostic_state.json')
PASTE_URL = 'https://paste.kodi.tv/'
API_ROOT = 'https://api.github.com'
TIMEOUT = 30
MAX_LOG_SIZE = 2 * 1024 * 1024
MAX_MANIFEST_SIZE = 1024 * 1024
MAX_PACKAGE_SIZE = 5 * 1024 * 1024
MAX_MANIFESTS = 8

REDACTIONS = [
    (re.compile(r'(?i)(://)[^/@\s]+:[^/@\s]+@'), r'\1USER:PASSWORD@'),
    (re.compile(r'(?is)<user>.*?</user>'), '<user>USER</user>'),
    (re.compile(r'(?is)<pass>.*?</pass>'), '<pass>PASSWORD</pass>'),
    (re.compile(r'(?i)(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(cookie\s*[:=]\s*)[^\r\n]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(\b(?:access_token|refresh_token|token|api[_-]?key|password|passwd|secret|signature|sig|hdnts|jwt|auth|sessionid|session_id|policy|key-pair-id)\b\s*[=:]\s*)["\']?[^\s&"\']+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)([?&](?:access_token|refresh_token|token|api[_-]?key|password|passwd|secret|signature|sig|hdnts?|hdnea|jwt|auth|sessionid|session_id|policy|key-pair-id|expires|x-amz-[a-z-]+|x-goog-[a-z-]+)=)[^&\s"\']+'), r'\1[REDACTED]'),
]


def _log(message, level=xbmc.LOGINFO):
    xbmc.log('%s: %s' % (ADDON_ID, message), level)


def _clean_log(content):
    for pattern, replacement in REDACTIONS:
        content = pattern.sub(replacement, content)
    return content


def _decode(data):
    if not isinstance(data, str):
        return data.decode('utf-8', 'replace')
    return data


def _read_vfs_file(path, limit):
    if not xbmcvfs.exists(path):
        return None
    handle = xbmcvfs.File(path)
    try:
        size = handle.size()
        if size > limit:
            _log('Datei wegen Größenlimit ausgelassen: %s (%s Bytes)' % (os.path.basename(path), size), xbmc.LOGWARNING)
            return None
        data = handle.read()
    finally:
        handle.close()
    if not data:
        return None
    return _decode(data)


def _read_log():
    content = _read_vfs_file(LOG_FILE, MAX_LOG_SIZE)
    if not content:
        raise RuntimeError('kodi.log wurde nicht gefunden, ist leer oder größer als 2 MB.')
    return _clean_log(content)


def _jsonrpc(method, params=None):
    request = {'jsonrpc': '2.0', 'method': method, 'id': 1}
    if params is not None:
        request['params'] = params
    response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    if 'error' in response:
        raise RuntimeError(response['error'].get('message', 'Kodi-JSON-RPC-Fehler'))
    return response.get('result')


def _get_debug_state():
    result = _jsonrpc('Settings.GetSettingValue', {'setting': 'debug.showloginfo'})
    if not isinstance(result, dict) or 'value' not in result:
        raise RuntimeError('Kodi stellt den globalen Debug-Schalter nicht bereit.')
    return bool(result['value'])


def _set_debug_state(enabled):
    result = _jsonrpc('Settings.SetSettingValue', {
        'setting': 'debug.showloginfo', 'value': bool(enabled)
    })
    if result is not True:
        raise RuntimeError('Kodi hat die Änderung des Debug-Status nicht bestätigt.')


def _load_state():
    if not xbmcvfs.exists(STATE_FILE):
        return None
    handle = xbmcvfs.File(STATE_FILE)
    try:
        raw = handle.read()
    finally:
        handle.close()
    return json.loads(_decode(raw))


def _save_state(state):
    if not xbmcvfs.exists(PROFILE_DIR):
        xbmcvfs.mkdirs(PROFILE_DIR)
    handle = xbmcvfs.File(STATE_FILE, 'w')
    try:
        handle.write(json.dumps(state))
    finally:
        handle.close()


def _delete_state():
    if xbmcvfs.exists(STATE_FILE):
        xbmcvfs.delete(STATE_FILE)


def _start_diagnostics(dialog):
    if not dialog.yesno(ADDON_NAME, 'Kodi-weites Debug-Logging aktivieren?\n\nWährend der Diagnose können mehr technische Details und Stream-Adressen im lokalen Kodi-Log erscheinen. Vor dem Upload werden bekannte Zugangsdaten und URL-Parameter bereinigt.'):
        return
    state = _load_state()
    if state:
        dialog.ok(ADDON_NAME, 'Eine Diagnose ist bereits aktiv. Nach der Fehler-Reproduktion bitte das Diagnosepaket erstellen oder die Einstellungen wiederherstellen.')
        return
    original = _get_debug_state()
    _save_state({'original_debug': original, 'changed': not original})
    try:
        if not original:
            _set_debug_state(True)
    except Exception:
        _delete_state()
        raise
    dialog.ok(ADDON_NAME, 'Diagnosemodus ist aktiv.\n\nReproduziere jetzt den Fehler. Danach dieses Add-on erneut starten und „Diagnosepaket erstellen und hochladen“ wählen.')


def _restore_diagnostics():
    state = _load_state()
    if not state:
        return False
    if state.get('changed'):
        _set_debug_state(bool(state.get('original_debug', False)))
    _delete_state()
    return True


def _add_text(zf, name, content):
    zf.writestr(name, _clean_log(content).encode('utf-8'))


def _collect_logs(zf, report):
    try:
        names = os.listdir(LOG_DIR)
    except Exception:
        names = ['kodi.log']
    candidates = []
    for name in names:
        if re.match(r'^kodi(?:\.old(?:\(\d+\))?)?\.log$', name, re.I):
            candidates.append(name)
    if 'kodi.log' not in candidates:
        candidates.append('kodi.log')
    for name in sorted(set(candidates))[:6]:
        path = os.path.join(LOG_DIR, name)
        try:
            content = _read_vfs_file(path, MAX_LOG_SIZE)
            if content:
                _add_text(zf, 'logs/' + name, content)
                report.append('Log aufgenommen: ' + name)
        except Exception as exc:
            report.append('Log ausgelassen: %s (%s)' % (name, exc))


def _collect_manifests(zf, report):
    count = 0
    total = 0
    for root_name, root in (('temp', TEMP_DIR), ('log', LOG_DIR)):
        try:
            names = os.listdir(root)
        except Exception:
            continue
        for name in sorted(names):
            if count >= MAX_MANIFESTS:
                break
            if not name.lower().endswith(('.mpd', '.m3u8')):
                continue
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
                if size <= 0 or size > MAX_MANIFEST_SIZE or total + size > 3 * MAX_MANIFEST_SIZE:
                    report.append('Manifest ausgelassen (Größenlimit): ' + name)
                    continue
                with open(path, 'rb') as stream:
                    content = _decode(stream.read(MAX_MANIFEST_SIZE + 1))
                if len(content.encode('utf-8')) > MAX_MANIFEST_SIZE:
                    continue
                _add_text(zf, 'manifests/' + root_name + '-' + name, content)
                count += 1
                total += size
                report.append('Manifest aufgenommen: ' + name)
            except Exception as exc:
                report.append('Manifest ausgelassen: %s (%s)' % (name, exc))



def _collect_license_diagnostics(zf, report):
    """Collect only small, text-based DRM/license diagnostics with matching filenames."""
    count = 0
    total = 0
    allowed_extensions = ('.log', '.txt', '.json', '.xml')
    name_pattern = re.compile(r'(?:drm|license|widevine|cdm)', re.I)
    for root_name, root in (('temp', TEMP_DIR), ('log', LOG_DIR)):
        try:
            names = os.listdir(root)
        except Exception:
            continue
        for name in sorted(names):
            if count >= 6:
                break
            if not name_pattern.search(name) or not name.lower().endswith(allowed_extensions):
                continue
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
                if size <= 0 or size > 512 * 1024 or total + size > 1024 * 1024:
                    report.append('DRM-/Lizenzdiagnose ausgelassen (Größenlimit): ' + name)
                    continue
                content = _read_vfs_file(path, 512 * 1024)
                if content:
                    _add_text(zf, 'license-diagnostics/' + root_name + '-' + name, content)
                    count += 1
                    total += size
                    report.append('DRM-/Lizenzdiagnose aufgenommen: ' + name)
            except Exception as exc:
                report.append('DRM-/Lizenzdiagnose ausgelassen: %s (%s)' % (name, exc))


def _system_report():
    labels = {
        'Kodi-Version': 'System.BuildVersion',
        'Plattform': 'System.Platform',
        'Betriebssystem': 'System.OSVersionInfo',
        'Architektur': 'System.Arch',
        'CPU': 'System.CPUModel',
    }
    lines = ['Kodi Logfile Uploader Diagnosepaket', 'Add-on-Version: ' + ADDON_VERSION]
    for label, info in labels.items():
        try:
            value = xbmc.getInfoLabel(info)
        except Exception:
            value = ''
        if value:
            lines.append('%s: %s' % (label, value))
    lines.extend([
        '', 'Hinweis: Das Paket enthält bereinigte Kodi-Logs und – sofern im Kodi-Temp-/Log-Ordner vorhanden – HLS-/DASH-Manifeste.',
        'DRM-/Lizenzfehler werden aus den Logs dokumentiert. Das Paket enthält keine Widevine-CDM-Dateien, DRM-Schlüssel oder rohen Lizenzantworten.'
    ])
    return '\n'.join(lines)


def _build_diagnostic_package():
    output = io.BytesIO()
    report = []
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        _collect_logs(archive, report)
        _collect_manifests(archive, report)
        _collect_license_diagnostics(archive, report)
        _add_text(archive, 'system-info.txt', _system_report())
        _add_text(archive, 'package-report.txt', '\n'.join(report))
    data = output.getvalue()
    if len(data) > MAX_PACKAGE_SIZE:
        raise RuntimeError('Diagnosepaket überschreitet das Upload-Limit von 5 MB.')
    if not any(item.startswith('Log aufgenommen:') for item in report):
        raise RuntimeError('Es konnten keine Kodi-Logdateien in das Diagnosepaket aufgenommen werden.')
    return data


def _github_upload_bytes(data, filename, folder='logs'):
    token = ADDON.getSetting('github_token').strip()
    repo = ADDON.getSetting('github_repo').strip() or 'Bender2403/kodi-rakuten-tv-addon'
    branch = ADDON.getSetting('github_branch').strip() or 'kodi-logs'
    if not token:
        raise RuntimeError('GitHub-Token fehlt. Bitte in den Add-on-Einstellungen eintragen.')
    if not re.match(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$', repo):
        raise RuntimeError('Ungültiger Repository-Name. Erwartet wird owner/repository.')
    path = folder + '/' + filename
    url = '%s/repos/%s/contents/%s' % (API_ROOT, repo, path)
    payload = {
        'message': 'Upload Kodi diagnostic %s' % filename,
        'branch': branch,
        'content': base64.b64encode(data).decode('ascii'),
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


def _github_upload_log(content):
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    return _github_upload_bytes(content.encode('utf-8'), 'kodi-%s.log' % stamp)


def _paste_upload(content):
    headers = {'User-Agent': '%s: %s' % (ADDON_ID, ADDON_VERSION)}
    response = requests.post(PASTE_URL + 'documents', data=content.encode('utf-8'), headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    result = response.json()
    if 'key' not in result:
        raise RuntimeError(result.get('message', 'paste.kodi.tv hat keine Paste-ID zurückgegeben.'))
    return PASTE_URL + result['key']


def _upload_normal_log():
    content = _read_log()
    target = ADDON.getSetting('upload_target') or 'github'
    destination = _paste_upload(content) if target == 'paste' else _github_upload_log(content)
    return destination


def _upload_diagnostic_package():
    # Restore the original Kodi logging state before collecting and uploading.
    restored = _restore_diagnostics()
    package = _build_diagnostic_package()
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    destination = _github_upload_bytes(package, 'diagnosepaket-%s.zip' % stamp)
    return destination, restored


def main():
    dialog = xbmcgui.Dialog()
    choices = [
        'Kodi-Log normal hochladen',
        'Diagnosemodus starten (Kodi-weites Debug-Logging)',
        'Diagnosepaket erstellen und hochladen',
        'Debug-Einstellungen wiederherstellen',
    ]
    try:
        choice = dialog.select(ADDON_NAME, choices)
        if choice < 0:
            return
        if choice == 0:
            destination = _upload_normal_log()
            _log('Logdatei erfolgreich hochgeladen: %s' % destination)
            dialog.ok(ADDON_NAME, 'Upload erfolgreich.\n\n' + destination)
        elif choice == 1:
            _start_diagnostics(dialog)
        elif choice == 2:
            destination, restored = _upload_diagnostic_package()
            note = 'Die ursprünglichen Kodi-Logging-Einstellungen wurden wiederhergestellt.\n\n' if restored else ''
            _log('Diagnosepaket erfolgreich hochgeladen: %s' % destination)
            dialog.ok(ADDON_NAME, note + 'Diagnosepaket hochgeladen.\n\n' + destination)
        elif choice == 3:
            restored = _restore_diagnostics()
            dialog.ok(ADDON_NAME, 'Ursprüngliche Kodi-Logging-Einstellungen wurden wiederhergestellt.' if restored else 'Es ist keine aktive Diagnose gespeichert.')
    except Exception as exc:
        _log('Vorgang fehlgeschlagen: %s' % exc, xbmc.LOGERROR)
        dialog.ok(ADDON_NAME, 'Vorgang fehlgeschlagen:\n\n%s' % str(exc))
