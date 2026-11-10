# -*- coding: utf-8 -*-
"""Kodi Logfile Uploader with optional Kodi-wide diagnostics."""
import base64
import datetime
import tempfile
import json
import os
import re
import shutil
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
DIAGNOSTIC_BASE_DIR = os.path.join(TEMP_DIR, 'kodi_loguploader')
DIAGNOSTIC_PLAYBACK_DIR = os.path.join(DIAGNOSTIC_BASE_DIR, 'diagnose')
PENDING_PACKAGE_PATH = os.path.join(DIAGNOSTIC_BASE_DIR, 'pending-diagnostic-package.zip')
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE_DIR, 'diagnostic_state.json')
ADDON_SELECTION_FILE = os.path.join(PROFILE_DIR, 'selected_addons.json')
PASTE_URL = 'https://paste.kodi.tv/'
API_ROOT = 'https://api.github.com'
TIMEOUT = 30
MAX_LOG_SIZE = 2 * 1024 * 1024
MAX_LOG_SOURCE_SIZE = 10 * 1024 * 1024
MAX_FILTERED_LOG_SIZE = 1536 * 1024
MAX_OLD_FILTERED_LOG_SIZE = 256 * 1024
MAX_MANIFEST_SIZE = 1024 * 1024
MAX_PACKAGE_SIZE = 20 * 1024 * 1024
MAX_MANIFESTS = 8

REDACTIONS = [
    (re.compile(r'(?i)(://)[^/@\s]+:[^/@\s]+@'), r'\1USER:PASSWORD@'),
    (re.compile(r'(?is)<user>.*?</user>'), '<user>USER</user>'),
    (re.compile(r'(?is)<pass>.*?</pass>'), '<pass>PASSWORD</pass>'),
    (re.compile(r'(?i)(authorization\s*[:=]\s*)[^\r\n]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(cookie\s*[:=]\s*)[^\r\n]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(\b(?:proxy-authorization|set-cookie|x-api-key|x-auth-token|x-access-token|x-csrf-token|x-xsrf-token|x-drm-token|x-license-token)\s*:\s*)[^\r\n]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(\b(?:access_token|refresh_token|token|api[_-]?key|password|passwd|secret|signature|sig|hdnts|jwt|auth|sessionid|session_id|policy|key-pair-id)\b\s*[=:]\s*)["\']?[^\s&"\']+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)([?&](?:access_token|refresh_token|token|api[_-]?key|password|passwd|secret|signature|sig|hdnts?|hdnea|jwt|auth|sessionid|session_id|policy|key-pair-id|expires|x-amz-[a-z-]+|x-goog-[a-z-]+)=)[^&\s"\']+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(\b(?:ntlm(?:ssp)?[_ -]?(?:challenge|response)|challenge[_ -]?response)\s*[:=]\s*)[0-9a-f]{16,}'), r'\1[REDACTED]'),
]


def _log(message, level=xbmc.LOGINFO):
    xbmc.log('%s: %s' % (ADDON_ID, message), level)


def _debug(message):
    """Write add-on diagnostics only when its independent setting is enabled."""
    try:
        enabled = ADDON.getSetting('debug_logging').strip().lower() == 'true'
    except Exception:
        enabled = False
    if enabled:
        # LOGINFO keeps this add-on's debug output visible without enabling
        # Kodi-wide debug logging. The setting controls only this add-on.
        xbmc.log('%s [DEBUG]: %s' % (ADDON_ID, message), xbmc.LOGINFO)


def _clean_log(content):
    """Redact credentials and sensitive SMB/NTLMSSP diagnostics."""
    cleaned = []
    for line in content.splitlines(True):
        if 'NTLMSSP' in line.upper():
            cleaned.append('[REDACTED SMB/NTLMSSP diagnostic data]' + ('\n' if line.endswith(('\n', '\r')) else ''))
            continue
        for pattern, replacement in REDACTIONS:
            line = pattern.sub(replacement, line)
        cleaned.append(line)
    return ''.join(cleaned)


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
    _debug('Großes Kodi-Log gefiltert: %d/%d Zeilen, %d Add-on-Treffer, %d Bytes.' %
        (stats['kept_lines'], stats['total_lines'],
         stats['matched_addon_lines'], stats['output_bytes']))
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


def _get_setting_value(setting):
    result = _jsonrpc('Settings.GetSettingValue', {'setting': setting})
    if not isinstance(result, dict) or 'value' not in result:
        raise RuntimeError('Kodi stellt die Einstellung %s nicht bereit.' % setting)
    return result['value']


def _set_setting_value(setting, value):
    result = _jsonrpc('Settings.SetSettingValue', {
        'setting': setting, 'value': value
    })
    if result is not True:
        raise RuntimeError('Kodi hat die Änderung der Einstellung %s nicht bestätigt.' % setting)


def _get_debug_state():
    return bool(_get_setting_value('debug.showloginfo'))


def _set_debug_state(enabled):
    _set_setting_value('debug.showloginfo', bool(enabled))


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
    """Return installed and enabled Kodi add-ons only."""
    result = _jsonrpc('Addons.GetAddons', {
        'type': 'unknown',
        'enabled': True,
        'installed': True,
        'properties': ['name', 'enabled', 'installed'],
        'limits': {'start': 0, 'end': 500},
    })
    addons = result.get('addons', []) if isinstance(result, dict) else []
    cleaned = []
    for addon in addons:
        addon_id = addon.get('addonid')
        if not addon_id or addon_id == ADDON_ID:
            continue
        # Keep only enabled add-ons, even if Kodi returns an unexpected entry.
        if not addon.get('enabled', False):
            continue
        cleaned.append({
            'addonid': str(addon_id),
            'name': str(addon.get('name') or addon_id),
            'type': str(addon.get('type') or 'unknown'),
            'enabled': bool(addon.get('enabled', False)),
        })
    cleaned = sorted(cleaned, key=lambda item: (item['name'].lower(), item['addonid']))
    _debug('Kodi meldet %d installierte Add-ons.' % len(cleaned))
    return cleaned


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
    _debug('Add-on-Auswahl gespeichert: %d Add-ons.' % len(selected))
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


def _setting_enabled(setting_id):
    try:
        return ADDON.getSetting(setting_id).strip().lower() == 'true'
    except Exception:
        return False


def _start_diagnostics(dialog):
    http_enabled = _setting_enabled('http_logging')
    drm_enabled = _setting_enabled('drm_logging')
    state = _load_state()
    if state:
        if dialog is not None:
            dialog.ok(ADDON_NAME, _s(32018, 'A diagnostic session is already active. After reproducing the issue, create the diagnostic package or restore the settings.'))
        return False

    original_debug = _get_debug_state()
    state = {
        'original_debug': original_debug,
        'changed_debug': bool((http_enabled or drm_enabled) and not original_debug),
        'http_logging': http_enabled,
        'drm_logging': drm_enabled,
        'changed_extralogging': False,
        'changed_components': False,
    }

    components = None
    if http_enabled:
        state['original_extralogging'] = bool(_get_setting_value('debug.extralogging'))
        current_components = _get_setting_value('debug.setextraloglevel')
        if not isinstance(current_components, list):
            raise RuntimeError('Kodi hat keine gültige Liste der zusätzlichen Logging-Komponenten geliefert.')
        components = list(current_components)
        state['original_components'] = list(current_components)
        if 64 not in components:
            components.append(64)
            state['changed_components'] = True
        state['changed_extralogging'] = not state['original_extralogging']

    _save_state(state)
    try:
        if state['changed_debug']:
            _set_debug_state(True)
        if http_enabled:
            # Enable the component selector before writing its integer-list value.
            if state['changed_extralogging']:
                _set_setting_value('debug.extralogging', True)
            if state['changed_components']:
                _set_setting_value('debug.setextraloglevel', components)
    except Exception:
        try:
            _restore_diagnostics()
        except Exception as restore_error:
            _log('Wiederherstellung nach Startfehler fehlgeschlagen: %s' % restore_error, xbmc.LOGERROR)
        raise

    if not http_enabled and not drm_enabled:
        detail = 'Keine zusätzliche HTTP-/HTTPS- oder DRM-Protokollierung aktiviert. Kodi-Logging bleibt unverändert.'
    else:
        enabled = []
        if http_enabled:
            enabled.append('HTTP/HTTPS (cURL)')
        if drm_enabled:
            enabled.append('DRM / InputStream Adaptive')
        detail = 'Aktiviert: ' + ', '.join(enabled)
    if dialog is not None:
        dialog.ok(ADDON_NAME, _s(32019, 'Diagnostic mode is active.') + '\n\n' + detail + '\n\n' + _s(32020, 'Reproduce the issue now. Then start this add-on again and choose the diagnostic package option.'))
    return True


def _restore_diagnostics():
    state = _load_state()
    if not state:
        return False

    # Restore component selection before disabling its parent setting.
    if state.get('changed_components'):
        _set_setting_value('debug.setextraloglevel', state.get('original_components', []))
    if state.get('changed_extralogging'):
        _set_setting_value('debug.extralogging', bool(state.get('original_extralogging', False)))
    if state.get('changed_debug') or ('changed_debug' not in state and state.get('changed')):
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
    _debug('Diagnosepaket: %d Add-ons für bevorzugte Logeinträge ausgewählt.' % len(selected))
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
            protocol_content, protocol_stats = logfilter.filter_protocol_logs(
                sanitized,
                http_enabled=_setting_enabled('http_logging'),
                drm_enabled=_setting_enabled('drm_logging'),
            )
            sanitized = protocol_content
            if protocol_stats['http_removed'] or protocol_stats['drm_removed']:
                report.append(
                    'Protokollzeilen gemäß Add-on-Einstellungen ausgelassen: HTTP/HTTPS=%d, DRM=%d' %
                    (protocol_stats['http_removed'], protocol_stats['drm_removed'])
                )
            source_bytes = sanitized.encode('utf-8')
            if len(source_bytes) <= MAX_LOG_SIZE:
                zf.writestr('logs/' + name, source_bytes)
                report.append('Log aufgenommen: %s (bereinigtes Original)' % name)
            else:
                report.append(
                    'Log aufgenommen: %s (Original mit %d Bytes wegen Größenlimit nicht beigelegt)' %
                    (name, len(source_bytes))
                )

            filter_limit = (MAX_FILTERED_LOG_SIZE if name.lower() == 'kodi.log'
                            else MAX_OLD_FILTERED_LOG_SIZE)
            filtered, stats = logfilter.filter_log(
                sanitized, addon_tokens, filter_limit
            )
            _debug('%s: %d/%d Zeilen behalten; %d Add-on-Treffer; %d Bytes.' %
                   (name, stats['kept_lines'], stats['total_lines'],
                    stats['matched_addon_lines'], stats['output_bytes']))
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



def _collect_playback_sessions(zf, report):
    """Add sanitized per-video capture files without loading them into RAM."""
    if not os.path.isdir(DIAGNOSTIC_PLAYBACK_DIR):
        return
    total_bytes = 0
    for session in sorted(os.listdir(DIAGNOSTIC_PLAYBACK_DIR)):
        folder = os.path.join(DIAGNOSTIC_PLAYBACK_DIR, session)
        if not os.path.isdir(folder) or os.path.islink(folder):
            continue
        try:
            names = sorted(os.listdir(folder))
        except Exception:
            continue
        for name in names:
            if name != 'kodi.log' and name != 'capture-info.txt' and not name.lower().endswith(('.mpd', '.m3u8')):
                continue
            path = os.path.join(folder, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            try:
                size = os.path.getsize(path)
                limit = 8 * 1024 * 1024 if name == 'kodi.log' else MAX_MANIFEST_SIZE
                if size <= 0 or size > limit or total_bytes + size > 12 * 1024 * 1024:
                    report.append('Wiedergabe-Datei ausgelassen (Größenlimit): %s/%s' % (session, name))
                    continue
                zf.write(path, 'playbacks/%s/%s' % (session, name))
                total_bytes += size
                report.append('Wiedergabe-Datei aufgenommen: %s/%s (%d Bytes)' % (session, name, size))
            except Exception as exc:
                report.append('Wiedergabe-Datei ausgelassen: %s/%s (%s)' % (session, name, exc))


def _remove_diagnostic_data():
    try:
        if os.path.isdir(DIAGNOSTIC_PLAYBACK_DIR):
            shutil.rmtree(DIAGNOSTIC_PLAYBACK_DIR)
    except Exception as exc:
        _log('Diagnoseordner konnte nicht vollständig gelöscht werden: %s' % exc, xbmc.LOGWARNING)
    try:
        if os.path.exists(PENDING_PACKAGE_PATH):
            os.remove(PENDING_PACKAGE_PATH)
    except Exception as exc:
        _log('Gespeichertes Diagnosepaket konnte nicht gelöscht werden: %s' % exc, xbmc.LOGWARNING)


def _offer_diagnostic_upload(dialog):
    restored = _restore_diagnostics()
    package_path = _build_diagnostic_package()
    try:
        if not dialog.yesno(ADDON_NAME, _s(32048, 'Diagnosepaket wurde erstellt. Möchtest du es jetzt hochladen?')):
            os.remove(package_path)
            _remove_diagnostic_data()
            dialog.notification(ADDON_NAME, _s(32049, 'Diagnosepaket und temporäre Dateien wurden gelöscht.'), xbmcgui.NOTIFICATION_INFO, 5000)
            return False
        stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        try:
            destination = _github_upload_file(package_path, 'diagnosepaket-%s.zip' % stamp)
        except Exception as exc:
            _log('Diagnosepaket-Upload fehlgeschlagen: %s' % exc, xbmc.LOGERROR)
            dialog.notification(ADDON_NAME, _s(32050, 'Upload fehlgeschlagen.'), xbmcgui.NOTIFICATION_ERROR, 7000)
            if dialog.yesno(ADDON_NAME, _s(32051, 'Upload fehlgeschlagen. Soll das Diagnosepaket gelöscht werden? Wenn du Nein wählst, bleibt es zum späteren Versuch erhalten.')):
                os.remove(package_path)
                _remove_diagnostic_data()
                dialog.notification(ADDON_NAME, _s(32049, 'Diagnosepaket und temporäre Dateien wurden gelöscht.'), xbmcgui.NOTIFICATION_INFO, 5000)
            else:
                if not os.path.isdir(DIAGNOSTIC_BASE_DIR):
                    os.makedirs(DIAGNOSTIC_BASE_DIR)
                if os.path.exists(PENDING_PACKAGE_PATH):
                    os.remove(PENDING_PACKAGE_PATH)
                os.replace(package_path, PENDING_PACKAGE_PATH)
                dialog.notification(ADDON_NAME, _s(32052, 'Diagnosepaket bleibt für einen späteren Upload gespeichert.'), xbmcgui.NOTIFICATION_INFO, 7000)
            return False
        try:
            os.remove(package_path)
        except OSError:
            pass
        _remove_diagnostic_data()
        note = _s(32023, 'The original Kodi logging settings have been restored.') + '\n\n' if restored else ''
        dialog.ok(ADDON_NAME, note + _s(32024, 'Diagnostic package uploaded.') + '\n\n' + destination)
        return True
    except Exception:
        try:
            if os.path.exists(package_path):
                os.remove(package_path)
        except OSError:
            pass
        raise


def finish_automatic_diagnostics():
    """Build the final package and ask for upload immediately after disabling the setting."""
    try:
        if not os.path.isdir(DIAGNOSTIC_PLAYBACK_DIR):
            return False
        sessions = [name for name in os.listdir(DIAGNOSTIC_PLAYBACK_DIR)
                    if os.path.isdir(os.path.join(DIAGNOSTIC_PLAYBACK_DIR, name))]
        if not sessions:
            return False
        _offer_diagnostic_upload(xbmcgui.Dialog())
        return True
    except Exception as exc:
        _log('Automatisches Diagnosepaket konnte nicht erstellt werden: %s' % exc, xbmc.LOGERROR)
        try:
            xbmcgui.Dialog().notification(ADDON_NAME, _s(32053, 'Diagnosepaket konnte nicht erstellt werden. Die Diagnose-Dateien bleiben erhalten.'), xbmcgui.NOTIFICATION_ERROR, 7000)
        except Exception:
            pass
        return False


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
    report = [
        'HTTP-/HTTPS-Protokollierung: ' + ('aktiv' if _setting_enabled('http_logging') else 'inaktiv'),
        'DRM-Protokollierung: ' + ('aktiv' if _setting_enabled('drm_logging') else 'inaktiv'),
    ]
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
            _collect_playback_sessions(archive, report)
            _collect_manifests(archive, report)
            _add_text(archive, 'system-info.txt', _system_report())
            _add_text(archive, 'package-report.txt', '\n'.join(report))

        package_size = os.path.getsize(package_path)
        _debug('Diagnosepaket erstellt: %d Bytes.' % package_size)
        if package_size > MAX_PACKAGE_SIZE:
            raise RuntimeError('Diagnosepaket überschreitet das Upload-Limit von 20 MB.')
        if not any(item.startswith(('Log aufgenommen:', 'Wiedergabe-Datei aufgenommen:')) for item in report):
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



def _upload_pending_package(dialog):
    if not os.path.isfile(PENDING_PACKAGE_PATH):
        dialog.ok(ADDON_NAME, _s(32055, 'Es ist kein gespeichertes Diagnosepaket vorhanden.'))
        return False
    if not dialog.yesno(ADDON_NAME, _s(32056, 'Gespeichertes Diagnosepaket jetzt erneut hochladen?')):
        return False
    try:
        stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        destination = _github_upload_file(PENDING_PACKAGE_PATH, 'diagnosepaket-%s.zip' % stamp)
        _remove_diagnostic_data()
        dialog.ok(ADDON_NAME, _s(32024, 'Diagnostic package uploaded.') + '\n\n' + destination)
        return True
    except Exception as exc:
        _log('Erneuter Upload des Diagnosepakets fehlgeschlagen: %s' % exc, xbmc.LOGERROR)
        dialog.notification(ADDON_NAME, _s(32050, 'Upload fehlgeschlagen.'), xbmcgui.NOTIFICATION_ERROR, 7000)
        if dialog.yesno(ADDON_NAME, _s(32051, 'Upload fehlgeschlagen. Soll das Diagnosepaket gelöscht werden? Wenn du Nein wählst, bleibt es zum späteren Versuch erhalten.')):
            _remove_diagnostic_data()
            dialog.notification(ADDON_NAME, _s(32049, 'Diagnosepaket und temporäre Dateien wurden gelöscht.'), xbmcgui.NOTIFICATION_INFO, 5000)
        return False


def _upload_diagnostic_package(dialog):
    return _offer_diagnostic_upload(dialog)


def main():
    dialog = xbmcgui.Dialog()
    choices = [
        _s(32011, 'Upload Kodi log normally'),
        _s(32012, 'Start diagnostics (configured protocol logging)'),
        _s(32013, 'Create and upload diagnostic package'),
        _s(32014, 'Restore debug settings'),
        _s(32034, 'Select add-ons to prioritize in logs'),
        _s(32054, 'Gespeichertes Diagnosepaket erneut hochladen'),
    ]
    try:
        _debug('Uploader gestartet; Add-on-Version %s.' % ADDON_VERSION)
        # Keep the main menu open after the add-on selection dialog returns.
        # Other actions retain their existing one-shot behavior.
        while True:
            choice = dialog.select(ADDON_NAME, choices)
            if choice < 0:
                return
            if choice == 4:
                _select_relevant_addons(dialog)
                continue
            break

        if choice == 0:
            destination = _upload_normal_log()
            _log('Logdatei erfolgreich hochgeladen: %s' % destination)
            dialog.ok(ADDON_NAME, _s(32022, 'Upload successful.') + '\n\n' + destination)
        elif choice == 1:
            _start_diagnostics(dialog)
        elif choice == 2:
            _upload_diagnostic_package(dialog)
        elif choice == 3:
            restored = _restore_diagnostics()
            dialog.ok(ADDON_NAME, _s(32025, 'The original Kodi logging settings have been restored.') if restored else _s(32026, 'There is no active diagnostic session.'))
        elif choice == 5:
            _upload_pending_package(dialog)
    except Exception as exc:
        _log('Vorgang fehlgeschlagen: %s' % exc, xbmc.LOGERROR)
        dialog.ok(ADDON_NAME, _s(32027, 'Operation failed: {error}').format(error=str(exc)))

