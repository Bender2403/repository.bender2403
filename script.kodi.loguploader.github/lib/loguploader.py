# -*- coding: utf-8 -*-
"""Kodi Logfile Uploader with optional Kodi-wide diagnostics."""
import base64
import datetime
import tempfile
import json
import os
import re
import zipfile

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import logfilter

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')


def _s(string_id, fallback=''):
    """Return a translated Kodi string, falling back if unavailable."""
    value = ADDON.getLocalizedString(string_id)
    return value or fallback
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_VERSION = ADDON.getAddonInfo('version')
LOG_DIR = xbmcvfs.translatePath('special://logpath')
LOG_FILE = os.path.join(LOG_DIR, 'kodi.log')
TEMP_DIR = xbmcvfs.translatePath('special://temp')
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE_DIR, 'diagnostic_state.json')
ADDON_SELECTION_FILE = os.path.join(PROFILE_DIR, 'selected_addons.json')
PASTE_URL = 'https://paste.kodi.tv/'
API_ROOT = 'https://api.github.com'
TIMEOUT = 30
MAX_LOG_SIZE = 2 * 1024 * 1024
MAX_LOG_SOURCE_SIZE = 10 * 1024 * 1024
MAX_FILTERED_LOG_SIZE = 2 * 1024 * 1024
MAX_MANIFEST_SIZE = 1024 * 1024
MAX_PACKAGE_SIZE = 20 * 1024 * 1024
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
    content = _read_vfs_file(LOG_FILE, MAX_LOG_SOURCE_SIZE)
    if not content:
        raise RuntimeError(_s(32028, 'kodi.log was not found, is empty or exceeds 10 MB.'))
    sanitized = _clean_log(content)
    if len(sanitized.encode('utf-8')) <= MAX_LOG_SIZE:
        return sanitized
    filtered, stats = logfilter.filter_log(
        sanitized, _selected_addon_tokens(), MAX_FILTERED_LOG_SIZE
    )
    _log(
        'Großes Kodi-Log gefiltert: %d/%d Zeilen, %d Add-on-Treffer, %d Bytes' %
        (stats['kept_lines'], stats['total_lines'],
         stats['matched_addon_lines'], stats['output_bytes'])
    )
    return filtered


def _jsonrpc(method, params=None):
    request = {'jsonrpc': '2.0', 'method': method, 'id': 1}
    if params is not None:
        request['params'] = params
    response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    if 'error' in response:
        raise RuntimeError(response['error'].get('message', _s(32030, 'Kodi JSON-RPC error')))
    return response.get('result')


def _get_debug_state():
    result = _jsonrpc('Settings.GetSettingValue', {'setting': 'debug.showloginfo'})
    if not isinstance(result, dict) or 'value' not in result:
        raise RuntimeError(_s(32029, 'Kodi does not expose the global debug switch.'))
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


def _get_installed_addons():
    """Return all installed Kodi add-ons, including disabled add-ons."""
    result = _jsonrpc('Addons.GetAddons', {
        'type': 'unknown',
        'enabled': 'all',
        'installed': True,
        'properties': ['name', 'enabled', 'installed', 'type'],
        'limits': {'start': 0, 'end': 500},
    })
    addons = result.get('addons', []) if isinstance(result, dict) else []
    cleaned = []
    for addon in addons:
        addon_id = addon.get('addonid')
        if not addon_id or addon_id == ADDON_ID:
            continue
        cleaned.append({
            'addonid': str(addon_id),
            'name': str(addon.get('name') or addon_id),
            'type': str(addon.get('type') or 'unknown'),
            'enabled': bool(addon.get('enabled', False)),
        })
    return sorted(cleaned, key=lambda item: (item['name'].lower(), item['addonid']))


def _load_addon_selection():
    if not xbmcvfs.exists(ADDON_SELECTION_FILE):
        return []
    try:
        handle = xbmcvfs.File(ADDON_SELECTION_FILE)
        try:
            state = json.loads(_decode(handle.read()))
        finally:
            handle.close()
        addons = state.get('addons', []) if isinstance(state, dict) else []
        return [item for item in addons if isinstance(item, dict) and item.get('addonid')]
    except Exception as exc:
        _log('Add-on-Auswahl konnte nicht gelesen werden: %s' % exc, xbmc.LOGWARNING)
        return []


def _save_addon_selection(addons):
    if not xbmcvfs.exists(PROFILE_DIR):
        xbmcvfs.mkdirs(PROFILE_DIR)
    handle = xbmcvfs.File(ADDON_SELECTION_FILE, 'w')
    try:
        handle.write(json.dumps({'addons': addons}, ensure_ascii=False))
    finally:
        handle.close()


def _select_relevant_addons(dialog, installed=None):
    """Let the user select installed add-ons whose log lines get priority."""
    if installed is None:
        installed = _get_installed_addons()
    if not installed:
        dialog.ok(ADDON_NAME, _s(32037, 'Kodi did not return any installed add-ons.'))
        return False

    previous = set(item.get('addonid') for item in _load_addon_selection())
    options = ['%s  [%s]' % (item['name'], item['addonid']) for item in installed]
    preselected = [
        index for index, item in enumerate(installed)
        if item['addonid'] in previous
    ]
    selected_indices = dialog.multiselect(
        _s(32035, 'Select installed add-ons whose log messages are important.'),
        options,
        preselect=preselected,
    )
    if selected_indices is None:
        return False

    selected = [installed[index] for index in selected_indices
                if 0 <= index < len(installed)]
    _save_addon_selection(selected)
    dialog.ok(
        ADDON_NAME,
        _s(32036, 'Selection saved. {count} add-ons will be prioritized in diagnostic logs.').format(
            count=len(selected)
        ),
    )
    return True


def _selected_addon_tokens():
    tokens = []
    for addon in _load_addon_selection():
        tokens.extend((addon.get('addonid', ''), addon.get('name', '')))
    return [token for token in tokens if token]


def _start_diagnostics(dialog):
    if not dialog.yesno(_s(32015, 'Kodi Logfile Uploader'), _s(32016, 'Enable Kodi-wide debug logging?') + '\n\n' + _s(32017, 'During diagnostics, more technical details and stream addresses may appear in the local Kodi log. Known credentials and URL parameters are sanitized before upload.')):
        return
    state = _load_state()
    if state:
        dialog.ok(ADDON_NAME, _s(32018, 'A diagnostic session is already active. After reproducing the issue, create the diagnostic package or restore the settings.'))
        return
    original = _get_debug_state()
    _save_state({'original_debug': original, 'changed': not original})
    try:
        if not original:
            _set_debug_state(True)
    except Exception:
        _delete_state()
        raise
    dialog.ok(ADDON_NAME, _s(32019, 'Diagnostic mode is active.') + '\n\n' + _s(32020, 'Reproduce the issue now. Then start this add-on again and choose the diagnostic package option.'))


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

    addon_tokens = _selected_addon_tokens()
    selected = _load_addon_selection()
    if selected:
        report.append('Bevorzugte Add-ons: ' + ', '.join(
            item.get('addonid', '') for item in selected
        ))

    for name in sorted(set(candidates))[:6]:
        path = os.path.join(LOG_DIR, name)
        try:
            content = _read_vfs_file(path, MAX_LOG_SOURCE_SIZE)
            if not content:
                report.append('Log ausgelassen oder leer/zu groß: ' + name)
                continue

            sanitized = _clean_log(content)
            source_bytes = sanitized.encode('utf-8')
            if len(source_bytes) <= MAX_LOG_SIZE:
                zf.writestr('logs/' + name, source_bytes)
                report.append('Log aufgenommen: %s (bereinigtes Original)' % name)
            else:
                report.append(
                    'Log aufgenommen: %s (Original mit %d Bytes wegen Größenlimit nicht beigelegt)' %
                    (name, len(source_bytes))
                )

            filtered, stats = logfilter.filter_log(
                sanitized, addon_tokens, MAX_FILTERED_LOG_SIZE
            )
            if filtered:
                filtered_name = 'filtered-' + name
                zf.writestr('logs/' + filtered_name, filtered.encode('utf-8'))
                report.append(
                    'Log aufgenommen: %s; %d/%d Zeilen behalten, %d Add-on-Treffer, %d Bytes' %
                    (filtered_name, stats['kept_lines'], stats['total_lines'],
                     stats['matched_addon_lines'], stats['output_bytes'])
                )
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
    """Build the ZIP on disk so the complete archive is not held in RAM."""
    report = []
    if not os.path.isdir(TEMP_DIR):
        os.makedirs(TEMP_DIR)
    file_descriptor, package_path = tempfile.mkstemp(
        prefix='kodi-diagnostics-', suffix='.zip', dir=TEMP_DIR
    )
    os.close(file_descriptor)
    try:
        with zipfile.ZipFile(
            package_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            _collect_logs(archive, report)
            _collect_manifests(archive, report)
            _collect_license_diagnostics(archive, report)
            _add_text(archive, 'system-info.txt', _system_report())
            _add_text(archive, 'package-report.txt', '\n'.join(report))

        package_size = os.path.getsize(package_path)
        if package_size > MAX_PACKAGE_SIZE:
            raise RuntimeError('Diagnosepaket überschreitet das Upload-Limit von 20 MB.')
        if not any(item.startswith('Log aufgenommen:') for item in report):
            raise RuntimeError('Es konnten keine Kodi-Logdateien in das Diagnosepaket aufgenommen werden.')
        return package_path
    except Exception:
        try:
            os.remove(package_path)
        except OSError:
            pass
        raise


def _github_upload_base64(encoded_content, filename, folder='logs'):
    token = ADDON.getSetting('github_token').strip()
    repo = ADDON.getSetting('github_repo').strip() or 'Bender2403/kodi-rakuten-tv-addon'
    branch = ADDON.getSetting('github_branch').strip() or 'kodi-logs'
    if not token:
        raise RuntimeError(_s(32031, 'GitHub token is missing. Enter it in the add-on settings.'))
    if not re.match(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$', repo):
        raise RuntimeError(_s(32032, 'Invalid repository name. Expected owner/repository.'))
    path = folder + '/' + filename
    url = '%s/repos/%s/contents/%s' % (API_ROOT, repo, path)
    payload = {
        'message': 'Upload Kodi diagnostic %s' % filename,
        'branch': branch,
        'content': encoded_content,
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
        raise RuntimeError(_s(32033, 'GitHub upload failed (HTTP {status}): {detail}').format(status=response.status_code, detail=detail or response.text[:300]))
    return 'https://github.com/%s/blob/%s/%s' % (repo, branch, path)


def _github_upload_bytes(data, filename, folder='logs'):
    encoded_content = base64.b64encode(data).decode('ascii')
    return _github_upload_base64(encoded_content, filename, folder)


def _github_upload_file(file_path, filename, folder='logs'):
    """Base64-encode a local file incrementally before the Contents API upload."""
    file_size = os.path.getsize(file_path)
    if file_size <= 0 or file_size > MAX_PACKAGE_SIZE:
        raise RuntimeError('Diagnosepaket fehlt oder überschreitet das Upload-Limit von 20 MB.')

    file_descriptor, encoded_path = tempfile.mkstemp(
        prefix='kodi-upload-', suffix='.b64', dir=TEMP_DIR
    )
    try:
        with os.fdopen(file_descriptor, 'wb') as encoded_file:
            with open(file_path, 'rb') as source_file:
                while True:
                    chunk = source_file.read(48 * 1024)
                    if not chunk:
                        break
                    encoded_file.write(base64.b64encode(chunk))

        with open(encoded_path, 'r', encoding='ascii') as encoded_file:
            encoded_content = encoded_file.read()
        return _github_upload_base64(encoded_content, filename, folder)
    finally:
        try:
            os.remove(encoded_path)
        except OSError:
            pass


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
    package_path = _build_diagnostic_package()
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    try:
        destination = _github_upload_file(
            package_path, 'diagnosepaket-%s.zip' % stamp
        )
    finally:
        try:
            os.remove(package_path)
        except OSError:
            pass
    return destination, restored


def main():
    dialog = xbmcgui.Dialog()
    choices = [
        _s(32011, 'Upload Kodi log normally'),
        _s(32012, 'Start diagnostics (Kodi-wide debug logging)'),
        _s(32013, 'Create and upload diagnostic package'),
        _s(32014, 'Restore debug settings'),
        _s(32034, 'Select add-ons to prioritize in logs'),
    ]
    try:
        # Refresh the installed add-on list at every launch and let the user
        # confirm or change which add-ons receive priority in the log filter.
        try:
            installed_addons = _get_installed_addons()
            _select_relevant_addons(dialog, installed_addons)
        except Exception as scan_error:
            _log('Installierte Add-ons konnten nicht gelesen werden: %s' % scan_error,
                 xbmc.LOGWARNING)

        choice = dialog.select(ADDON_NAME, choices)
        if choice < 0:
            return
        if choice == 0:
            destination = _upload_normal_log()
            _log('Logdatei erfolgreich hochgeladen: %s' % destination)
            dialog.ok(ADDON_NAME, _s(32022, 'Upload successful.') + '\n\n' + destination)
        elif choice == 1:
            _start_diagnostics(dialog)
        elif choice == 2:
            destination, restored = _upload_diagnostic_package()
            note = _s(32023, 'The original Kodi logging settings have been restored.') + '\n\n' if restored else ''
            _log('Diagnosepaket erfolgreich hochgeladen: %s' % destination)
            dialog.ok(ADDON_NAME, note + _s(32024, 'Diagnostic package uploaded.') + '\n\n' + destination)
        elif choice == 3:
            restored = _restore_diagnostics()
            dialog.ok(ADDON_NAME, _s(32025, 'The original Kodi logging settings have been restored.') if restored else _s(32026, 'There is no active diagnostic session.'))
        elif choice == 4:
            _select_relevant_addons(dialog)
    except Exception as exc:
        _log('Vorgang fehlgeschlagen: %s' % exc, xbmc.LOGERROR)
        dialog.ok(ADDON_NAME, _s(32027, 'Operation failed: {error}').format(error=str(exc)))

