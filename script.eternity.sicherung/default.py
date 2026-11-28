# Eternity Code-Sicherung
# Version 1.0.9
# - Download zuerst mit requests wie im Original-Addon
# - Alternativ urllib mit eigenem User-Agent
# - Optionaler automatischer Methodenwechsel bei Download-Fehlern
# - Sicherung im eigenen addon_data-Ordner
# - Erstellt nach dem Entpacken eine installierbare Kodi-ZIP
# - Verwendet bei fehlender addon.xml die installierte addon.xml
# - Diagnose-Log ohne vollstaendigen Zugangsschluessel

import os
import sys
import re
import json
import zlib
import zipfile
import traceback
import datetime
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs

A = xbmcaddon.Addon()
TITLE = 'Eternity Code-Sicherung'
TARGET = 'plugin.video.eternity'
REPO_IDS = ('eternityxrepo', 'repository.eternityxrepo')
LIMIT = 20 * 1024 * 1024
EXPANDED = 100 * 1024 * 1024
DATA = xbmcvfs.translatePath(A.getAddonInfo('profile'))
SECRET = ''


def clean(value):
    text = str(value)
    if SECRET:
        text = text.replace(SECRET, '<schluessel>')
    return re.sub(r'/[A-Za-z0-9_-]{24,64}(?=/)', '/<schluessel>', text)


def log(value):
    text = clean(value)
    xbmc.log('[Eternity-Sicherung] ' + text, xbmc.LOGINFO)
    if get_bool('diagnostics', True):
        try:
            os.makedirs(DATA, exist_ok=True)
            path = os.path.join(DATA, 'sicherung_debug.log')
            if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
                os.replace(path, path + '.old')
            with open(path, 'a', encoding='utf-8') as f:
                f.write(datetime.datetime.now().isoformat(timespec='seconds') + ' | ' + text + '\n')
        except Exception:
            pass


def get_int(name, default):
    try:
        value = A.getSettingInt(name)
        return default if value is None else int(value)
    except Exception:
        try:
            return int(A.getSetting(name) or default)
        except Exception:
            return default


def get_bool(name, default):
    try:
        value = A.getSettingBool(name)
        return default if value is None else bool(value)
    except Exception:
        return str(A.getSetting(name)).lower() in ('true', '1', 'yes')


def read_repo():
    global SECRET
    root = xbmcvfs.translatePath('special://home/addons/')
    for folder in REPO_IDS:
        path = os.path.join(root, folder, 'addon.xml')
        if not os.path.isfile(path):
            continue
        try:
            tree = ET.parse(path)
        except Exception as exc:
            log('Repository-XML nicht lesbar (%s): %s' % (path, exc))
            continue
        for node in tree.getroot().iter('info'):
            value = (node.text or '').strip()
            match = re.fullmatch(r'(https?://[^/]+)/([A-Za-z0-9_-]{24,64})/addons\.xml', value)
            if match:
                SECRET = match.group(2)
                log('Repository gefunden: %s' % folder)
                log('Basis-URL: %s' % match.group(1))
                log('Schluessellaenge: %d' % len(SECRET))
                return match.group(1), SECRET
        log('Kein passender info-Eintrag in %s' % path)
    raise RuntimeError('Repository mit passendem Zugang nicht gefunden.')


def get_target_version():
    version = xbmcaddon.Addon(TARGET).getAddonInfo('version')
    if not version or not re.fullmatch(r'[A-Za-z0-9._+-]+', version):
        raise RuntimeError('Version von %s konnte nicht gelesen werden.' % TARGET)
    return version


def download_requests(url):
    import requests
    log('Methode: requests | User-Agent: %s' % requests.utils.default_user_agent())
    with requests.get(url, timeout=30, stream=True) as response:
        log('HTTP-Status: %s' % response.status_code)
        if response.status_code != 200:
            try:
                answer = response.text[:2000]
            except Exception:
                answer = '<Antwort nicht lesbar>'
            log('Serverantwort: %s' % answer)
            raise RuntimeError('Download fehlgeschlagen: HTTP %s' % response.status_code)
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > LIMIT:
                raise RuntimeError('Code-Paket groesser als 20 MiB.')
        log('Download erfolgreich: %d Bytes' % len(data))
        return bytes(data)


def download_urllib(url):
    user_agent = (A.getSetting('user_agent') or '').strip() or 'EternityCodeSicherung/1.0.9'
    log('Methode: urllib | User-Agent: %s' % user_agent)
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': user_agent,
            'Accept': '*/*'
        }
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            log('HTTP-Status: %s' % response.status)
            data = response.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise RuntimeError('Code-Paket groesser als 20 MiB.')
            log('Download erfolgreich: %d Bytes' % len(data))
            return data
    except urllib.error.HTTPError as exc:
        log('HTTP-Status: %s' % exc.code)
        try:
            answer = exc.read(2048).decode('utf-8', 'replace')
        except Exception:
            answer = '<Antwort nicht lesbar>'
        log('Serverantwort: %s' % answer)
        raise


def download(url, mode):
    if mode == 0:
        return download_requests(url)
    return download_urllib(url)


def unpack(blob, version, root):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(blob, EXPANDED + 1)
    if len(raw) > EXPANDED or not decoder.eof:
        raise RuntimeError('Paket beschaedigt oder entpackt groesser als 100 MiB.')
    bundle = json.loads(raw.decode('utf-8'))
    if not isinstance(bundle, dict):
        raise RuntimeError('Paket enthaelt kein gueltiges JSON.')
    if bundle.get('format') != 1:
        raise RuntimeError('Unbekanntes Paketformat: %s' % bundle.get('format'))
    if bundle.get('addon') != TARGET:
        raise RuntimeError('Paket gehoert nicht zu %s.' % TARGET)
    if bundle.get('version') != version:
        raise RuntimeError('Paketversion %s passt nicht zur Addon-Version %s.' % (bundle.get('version'), version))
    files = bundle.get('files')
    if not isinstance(files, dict) or not files:
        raise RuntimeError('Paket enthaelt keine Dateien.')
    checked = []
    root = os.path.realpath(root)
    for name, source in files.items():
        if not isinstance(name, str) or not isinstance(source, str):
            raise RuntimeError('Ungueltiger Dateieintrag im Paket.')
        parts = name.replace('\\', '/').split('/')
        if any(part in ('', '.', '..') or ':' in part or '\x00' in part for part in parts):
            raise RuntimeError('Unsicherer Dateipfad: %s' % name)
        path = os.path.realpath(os.path.join(root, *parts))
        if os.path.commonpath([root, path]) != root:
            raise RuntimeError('Dateipfad ausserhalb des Zielordners: %s' % name)
        checked.append((path, source))
    for path, source in checked:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(source)
    log('Entpackte Dateien: %d' % len(checked))
    return len(checked)


def read_installed_addon_xml(version):
    installed_root = xbmcvfs.translatePath('special://home/addons/%s/' % TARGET)
    addon_xml = os.path.join(installed_root, 'addon.xml')
    if not os.path.isfile(addon_xml):
        raise RuntimeError('Die installierte addon.xml von %s wurde nicht gefunden.' % TARGET)
    try:
        tree = ET.parse(addon_xml)
        addon_id = tree.getroot().attrib.get('id', '').strip()
        addon_version = tree.getroot().attrib.get('version', '').strip()
    except Exception as exc:
        raise RuntimeError('Die installierte addon.xml von %s ist ungueltig: %s' % (TARGET, exc))
    if addon_id != TARGET:
        raise RuntimeError('Die installierte addon.xml enthaelt die falsche Add-on-ID: %s' % addon_id)
    if addon_version != version:
        raise RuntimeError('Die installierte addon.xml-Version %s passt nicht zur Eternity-Version %s.' % (addon_version, version))
    log('Installierte addon.xml wird fuer die Kodi-ZIP verwendet: %s' % addon_xml)
    return addon_xml


def create_addon_zip(unpack_dir, version):
    addon_xml = os.path.join(unpack_dir, 'addon.xml')
    addon_xml_source = 'entpackt'
    if not os.path.isfile(addon_xml):
        addon_xml = read_installed_addon_xml(version)
        addon_xml_source = 'installiert'
    else:
        try:
            tree = ET.parse(addon_xml)
            addon_id = tree.getroot().attrib.get('id', '').strip()
            addon_version = tree.getroot().attrib.get('version', '').strip()
        except Exception as exc:
            raise RuntimeError('addon.xml im entpackten Paket ist ungueltig: %s' % exc)
        if addon_id != TARGET:
            raise RuntimeError('addon.xml enthaelt die falsche Add-on-ID: %s' % addon_id)
        if addon_version != version:
            raise RuntimeError('addon.xml-Version %s passt nicht zur Eternity-Version %s.' % (addon_version, version))

    output_dir = os.path.join(DATA, 'fertig')
    os.makedirs(output_dir, exist_ok=True)
    zip_name = '%s-%s.zip' % (TARGET, version)
    zip_path = os.path.join(output_dir, zip_name)

    if os.path.exists(zip_path):
        os.remove(zip_path)

    file_count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(addon_xml, '%s/addon.xml' % TARGET)
        file_count += 1
        for base, folders, names in os.walk(unpack_dir):
            folders.sort()
            for name in sorted(names):
                source = os.path.join(base, name)
                relative = os.path.relpath(source, unpack_dir)
                relative = relative.replace(os.sep, '/')
                if relative == 'addon.xml':
                    continue
                archive.write(source, '%s/%s' % (TARGET, relative))
                file_count += 1

    if file_count <= 1:
        os.remove(zip_path)
        raise RuntimeError('Im entpackten Paket wurden keine zusaetzlichen Dateien gefunden.')

    log('Fertige Kodi-ZIP erstellt: %s | addon.xml-Quelle: %s | Dateien: %d' % (
        zip_path,
        addon_xml_source,
        file_count
    ))
    return zip_path


def run():
    dialog = xbmcgui.Dialog()
    choice = dialog.select(
        TITLE,
        ['Herunterladen, entpacken und Kodi-ZIP erstellen', 'Einstellungen', 'Diagnose-Log anzeigen']
    )
    if choice == 1:
        A.openSettings()
        return
    if choice == 2:
        path = os.path.join(DATA, 'sicherung_debug.log')
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                dialog.textviewer('Diagnose', f.read()[-100000:])
        else:
            dialog.ok(TITLE, 'Noch keine Diagnose-Datei vorhanden.')
        return
    if choice != 0:
        return

    progress = None
    error = None
    message = ''
    try:
        os.makedirs(DATA, exist_ok=True)
        log('Start 1.0.9 | Kodi %s | Python %s' % (
            xbmc.getInfoLabel('System.BuildVersion'),
            sys.version.replace('\n', ' ')
        ))
        base_url, key = read_repo()
        version = get_target_version()
        url = '%s/%s/code/%s-%s.bin' % (base_url, key, TARGET, version)
        log('Download-URL: %s' % url)

        progress = xbmcgui.DialogProgress()
        progress.create(TITLE, 'Code-Paket wird heruntergeladen ...')
        progress.update(20)

        mode = get_int('download_mode', 0)
        try:
            blob = download(url, mode)
        except Exception:
            log(traceback.format_exc())
            if not get_bool('fallback', False):
                raise
            other = 1 if mode == 0 else 0
            log('Automatischer Wechsel auf Methode %d.' % other)
            blob = download(url, other)

        progress.update(50, 'Paket wird gespeichert ...')
        backup_root = os.path.join(DATA, 'backup', version)
        os.makedirs(backup_root, exist_ok=True)
        bundle_path = os.path.join(backup_root, 'bundle.bin')
        with open(bundle_path, 'wb') as f:
            f.write(blob)
        log('bundle.bin gespeichert: %d Bytes' % len(blob))

        progress.update(75, 'Paket wird geprueft und entpackt ...')
        unpack_dir = os.path.join(backup_root, 'entpackt')
        count = unpack(blob, version, unpack_dir)

        progress.update(90, 'Fertige Kodi-ZIP wird erstellt ...')
        zip_path = create_addon_zip(unpack_dir, version)
        message = '%d Dateien entpackt.\n\nFertige Kodi-ZIP:\n%s\n\nSicherung:\n%s' % (
            count,
            zip_path,
            backup_root
        )
    except Exception as exc:
        log(traceback.format_exc())
        error = clean(exc)
    finally:
        if progress:
            progress.close()

    if error:
        dialog.ok(
            TITLE,
            'Fehler:\n%s\n\nDiagnose-Datei:\n%s' % (
                error,
                os.path.join(DATA, 'sicherung_debug.log')
            )
        )
    else:
        dialog.ok(TITLE, message)


if __name__ == '__main__':
    run()
