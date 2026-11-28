# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Simone Bianchelli
# OptiKlean - Kodi Cleaning and Optimization Addon

import os
import json
import urllib.request
import urllib.parse
import urllib.error
import re
import shutil
import zipfile
import hashlib
import stat
import tempfile
from datetime import datetime, timedelta
from xml.etree import ElementTree
from xml.parsers import expat

import xbmc
import xbmcaddon
import xbmcvfs
import xbmcgui

from resources.lib.update_state import (
    clear_restart_pending,
    get_restart_pending_state,
    set_restart_pending,
)


def _parse_version(v):
    """Parse numeric dotted versions without discarding components."""
    if not isinstance(v, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", v):
        raise ValueError("Unsupported addon version")
    parts = [int(part) for part in v.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _try_restart_kodi():
    try:
        xbmc.executebuiltin("RestartApp")
        return
    except Exception:
        pass
    try:
        xbmc.executebuiltin("Quit")
    except Exception:
        pass

class AutoUpdater:
    # 1. Configurazione GitLab
    GITLAB_PROJECT_PATH = "personal4143605/optiklean"  # Formato: "user_or_group/repo"
    GITLAB_BRANCH = "main"                            # Branch di default
    GITLAB_ACCESS_TOKEN = ""  # nosec B105 - Empty string for public repos, not a hardcoded password
    ADDON_ZIP_NAME = "program.optiklean.zip"          # nome dello zip dell'addon
    
    # 2. Costanti derivate (NON MODIFICARE MANUALMENTE)
    GITLAB_API_BASE = "https://gitlab.com/api/v4"
    GITLAB_PROJECT_URL = f"{GITLAB_API_BASE}/projects/{urllib.parse.quote(GITLAB_PROJECT_PATH, safe='')}"
    
    # 3. Configurazione aggiornamenti
    MAX_DOWNLOAD_RETRY = 3      # Numero massimo di tentativi di download
    @property
    def update_check_interval(self):
        """Restituisce l'intervallo di controllo aggiornamenti (in ore) scelto dall'utente"""
        try:
            interval = int(self.addon.getSetting("update_check_interval"))
            if interval < 1:
                return 24  # fallback di sicurezza
            return interval
        except Exception as e:
            xbmc.log(f"OptiKlean: Errore lettura update_check_interval: {str(e)}", xbmc.LOGWARNING)
            return 24  # fallback di sicurezza

    def __init__(self):
        # Configurazione addon
        self.addon = xbmcaddon.Addon()
        self.addon_id = self.addon.getAddonInfo('id')
        self.current_version = self.addon.getAddonInfo('version')
        
        # Percorsi file system
        self.addon_path = xbmcvfs.translatePath(self.addon.getAddonInfo('path'))
        self.profile_path = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        self.commit_file = os.path.join(self.profile_path, 'last_commit.json')
        self.temp_dir = os.path.join(self.profile_path, 'temp')

        # Configurazione logo
        media_path = os.path.join(self.addon_path, 'resources', 'media')
        self.logo_path = os.path.join(media_path, 'logo.png')

        # Crea cartelle se non esistono
        self._ensure_directories()
            
        # Log di verifica configurazione
        xbmc.log(f"OptiKlean: GitLab project: {self.GITLAB_PROJECT_PATH}", xbmc.LOGDEBUG)
        xbmc.log(f"OptiKlean: Addon path: {self.addon_path}", xbmc.LOGDEBUG)
        xbmc.log(f"OptiKlean: Current version: {self.current_version}", xbmc.LOGDEBUG)

    def _ensure_directories(self):
        """Assicura che tutte le directory necessarie esistano"""
        for path in [self.profile_path, self.temp_dir]:
            if not xbmcvfs.exists(path):
                xbmcvfs.mkdirs(path)
                xbmc.log(f"OptiKlean: Created directory {path}", xbmc.LOGDEBUG)

    def _is_auto_update_enabled(self):
        """Safe getter for update setting with fallback"""
        try:
            return self.addon.getSettingBool("enable_auto_updates")
        except Exception as e:
            xbmc.log(f"OptiKlean: Settings error, using default (True): {str(e)}", xbmc.LOGERROR)
            return True  # Default safe value

    def _extract_version(self, message):
        """Estrae la versione dal commit message"""
        patterns = [
            r'\[?v\.?(\d+(?:\.\d+){2,})\]?',
            r'\b(\d+(?:\.\d+){2,})\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match
        return None

    def _load_commit_data(self):
        """Carica i dati del commit dal file JSON"""
        try:
            if os.path.exists(self.commit_file):
                with open(self.commit_file, 'r', encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            return {}
        except Exception as e:
            xbmc.log(f"OptiKlean: Error loading commit data: {str(e)}", xbmc.LOGERROR)
            return {}

    def _save_commit_data(self, commit_id, gitlab_version, local_version=None, package_checked=False):
        """Salva i nuovi dati del commit"""
        data = {
            "commit_id": commit_id,
            "local_version": self.current_version if local_version is None else local_version,
            "gitlab_version": gitlab_version,
            "package_checked": package_checked,
            "last_check": datetime.now().isoformat(),
            "kodi_version": xbmc.getInfoLabel('System.BuildVersion')
        }
        
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.profile_path, delete=False
            ) as f:
                temp_path = f.name
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.commit_file)
            return True
        except Exception as e:
            xbmc.log(f"OptiKlean: Error saving commit data: {str(e)}", xbmc.LOGERROR)
            return False
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError as e:
                    xbmc.log(f"OptiKlean: Commit temp cleanup failed: {str(e)}", xbmc.LOGWARNING)

    def _get_latest_commit(self):
        """Recupera l'ultimo commit che ha modificato program.optiklean.zip da GitLab"""
        try:
            url = (
                f"{self.GITLAB_PROJECT_URL}/repository/commits"
                f"?ref_name={self.GITLAB_BRANCH}&per_page=1&path={self.ADDON_ZIP_NAME}"
            )
            
            # Validate URL scheme for security
            if not url.startswith('https://'):
                xbmc.log("OptiKlean: Invalid URL scheme, only HTTPS allowed", xbmc.LOGERROR)
                return None

            headers = {}
            if self.GITLAB_ACCESS_TOKEN:
                headers["Private-Token"] = self.GITLAB_ACCESS_TOKEN

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310
                commits = json.loads(response.read().decode('utf-8'))

                if not commits:
                    xbmc.log(f"OptiKlean: No commits found for {self.ADDON_ZIP_NAME}", xbmc.LOGWARNING)
                    return None

                commit = commits[0]
                return {
                    'id': commit['id'],
                    'message': commit.get('message', ''),
                    'date': commit['committed_date']
                }
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            xbmc.log(f"OptiKlean: GitLab API error: {str(e)}", xbmc.LOGERROR)
            return None

    def _should_update(self, gitlab_commit, local_data):
        xbmc.log("OptiKlean: _should_update() chiamata", xbmc.LOGDEBUG)
        """Determina se è necessario aggiornare"""
        
        # Estrazione versione dal commit remoto
        version_match = self._extract_version(gitlab_commit['message'])
        gitlab_version = version_match.group(1) if version_match else None
        local_version = self.current_version

        # Log di debug: messaggio commit e versione estratta
        xbmc.log(f"OptiKlean: Commit message: {gitlab_commit['message']}", xbmc.LOGDEBUG)
        xbmc.log(f"OptiKlean: Remote version extracted: {gitlab_version}", xbmc.LOGDEBUG)

        # Primo avvio: se la versione coincide, NON aggiornare
        if not local_data.get('commit_id'):
            if gitlab_version and gitlab_version == local_version:
                xbmc.log("OptiKlean: Prima esecuzione, versione già aggiornata", xbmc.LOGINFO)
                return False
            xbmc.log("OptiKlean: No previous commit data, considering update", xbmc.LOGINFO)
            return True

        # A known commit does not require reinstalling an unchanged version.
        if local_data['commit_id'] == gitlab_commit['id']:
            xbmc.log("OptiKlean: Commit ID unchanged", xbmc.LOGDEBUG)
            return False

        if not gitlab_version:
            xbmc.log("OptiKlean: No version in commit message, updating for safety", xbmc.LOGWARNING)
            return True

        xbmc.log(f"OptiKlean: Version comparison - Remote: {gitlab_version}, Local: {local_version}", xbmc.LOGINFO)

        try:
            is_newer = _parse_version(gitlab_version) > _parse_version(local_version)
            if is_newer:
                xbmc.log("OptiKlean: New version found, ignoring time limits for update", xbmc.LOGINFO)
            return is_newer
        except Exception as e:
            xbmc.log(f"OptiKlean: Version comparison error: {str(e)}, updating for safety", xbmc.LOGWARNING)
            return True

    def _should_skip_check(self, local_data):
        """Determina se saltare il controllo per limiti di frequenza"""
        if not local_data.get('last_check'):
            xbmc.log("OptiKlean: No previous check time, not skipping", xbmc.LOGDEBUG)
            return False

        try:
            last_check = datetime.fromisoformat(local_data['last_check'])
            time_diff = datetime.now() - last_check

            # Usa il valore parametrico invece della costante
            if time_diff < timedelta(hours=self.update_check_interval):
                xbmc.log(f"OptiKlean: Skipping check, last one was {time_diff.total_seconds()/3600:.1f} hours ago (interval: {self.update_check_interval}h)", xbmc.LOGDEBUG)
                return True
            else:
                xbmc.log(f"OptiKlean: Time limit passed ({time_diff.total_seconds()/3600:.1f}h > {self.update_check_interval}h), check allowed", xbmc.LOGDEBUG)

        except Exception as e:
            xbmc.log(f"OptiKlean: Error calculating check interval: {str(e)}", xbmc.LOGWARNING)

        return False

    def _calculate_file_hash(self, file_path):
        """Calcola l'hash SHA256 di un file"""
        if not os.path.exists(file_path):
            return None
            
        try:
            sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            xbmc.log(f"OptiKlean: Hash calculation error: {str(e)}", xbmc.LOGWARNING)
            return None

    @staticmethod
    def _validate_archive_entries(entries):
        paths = {}
        if len(entries) > 20000 or sum(item.file_size for item in entries) > 512 * 1024 * 1024:
            raise ValueError("Update archive exceeds extraction limits")
        for entry in entries:
            name = entry.filename
            parts = name.rstrip("/").split("/")
            if (
                not name or "\\" in name or name.startswith("/")
                or any(
                    not part or part in (".", "..") or ":" in part
                    or part.endswith((" ", "."))
                    or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.IGNORECASE)
                    for part in parts
                )
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError("Unsafe update archive path")
            for index in range(1, len(parts) + 1):
                path = "/".join(parts[:index])
                key = path.casefold()
                is_dir = index < len(parts) or entry.is_dir()
                if key in paths:
                    old_dir, old_path = paths[key]
                    if old_path != path or not old_dir or not is_dir:
                        raise ValueError("Conflicting update archive path")
                paths[key] = (is_dir, path)

    def _extract_update(self, zip_path, extract_path):
        with zipfile.ZipFile(zip_path) as archive:
            self._validate_archive_entries(archive.infolist())
            archive.extractall(extract_path)

        candidates = []
        for root, _, files in os.walk(extract_path):
            if "addon.xml" in files:
                with open(os.path.join(root, "addon.xml"), "rb") as stream:
                    content = stream.read(256 * 1024 + 1)
                if len(content) > 256 * 1024:
                    raise ValueError("Update manifest is too large")

                def reject(*args):
                    raise ValueError("Unsafe update manifest")

                parser = expat.ParserCreate()
                parser.StartDoctypeDeclHandler = reject
                parser.EntityDeclHandler = reject
                parser.Parse(content, True)
                manifest = ElementTree.fromstring(content)
                version = manifest.get("version")
                if manifest.tag == "addon" and manifest.get("id") == self.addon_id and version:
                    candidates.append((root, version))
        if len(candidates) != 1:
            raise ValueError("Update archive must contain exactly one matching addon")
        root, version = candidates[0]
        for required in ("default.py", "service.py", "autoupdater.py",
                         "resources/lib/update_state.py", "resources/settings.xml"):
            if not os.path.isfile(os.path.join(root, *required.split("/"))):
                raise ValueError("Update archive is missing a required addon file")
        return root, version

    def _install_update(self, zip_path, workspace, allow_same_version=True):
        extracted, version = self._extract_update(zip_path, os.path.join(workspace, "extracted"))
        package_version = _parse_version(version)
        current_version = _parse_version(self.current_version)
        if package_version < current_version:
            raise ValueError("Update package is older than the installed addon")
        if package_version == current_version and not allow_same_version:
            return None

        self._backup_user_data()
        staged = os.path.join(workspace, "staged")
        shutil.copytree(self.addon_path, staged, symlinks=True)
        for item in os.listdir(extracted):
            if item.lower() == "userdata":
                continue
            src = os.path.join(extracted, item)
            dst = os.path.join(staged, item)
            if os.path.lexists(dst):
                if os.path.isdir(dst) and not os.path.islink(dst):
                    shutil.rmtree(dst)
                else:
                    os.remove(dst)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        os.rename(self.addon_path, os.path.join(workspace, "backup"))
        try:
            os.rename(staged, self.addon_path)
        except Exception:
            self._rollback_update(workspace)
            raise
        return version

    def _rollback_update(self, workspace):
        try:
            if os.path.lexists(self.addon_path):
                os.rename(self.addon_path, os.path.join(workspace, "failed"))
            os.rename(os.path.join(workspace, "backup"), self.addon_path)
            return True
        except OSError as error:
            xbmc.log(
                f"OptiKlean: Rollback failed: {error}. Restore the backup at "
                f"{os.path.join(workspace, 'backup')} with Kodi stopped.",
                xbmc.LOGERROR,
            )
            return False

    def _backup_user_data(self):
        """Backup dei file di configurazione dell'utente"""
        try:
            # Salva settings.xml se esiste
            settings_file = os.path.join('special://profile', 'userdata', 'addon_data', self.addon_id, 'settings.xml')
            settings_path = xbmcvfs.translatePath(settings_file)
            
            if xbmcvfs.exists(settings_path):
                backup_path = os.path.join(self.profile_path, 'settings_backup.xml')
                xbmcvfs.copy(settings_path, backup_path)
                xbmc.log(f"OptiKlean: Settings backup created at {backup_path}", xbmc.LOGINFO)
                
        except Exception as e:
            xbmc.log(f"OptiKlean: Settings backup error: {str(e)}", xbmc.LOGWARNING)

    def _localized(self, string_id, fallback=""):
        try:
            return self.addon.getLocalizedString(string_id) or fallback
        except Exception:
            return fallback

    @staticmethod
    def _build_update_summary(version, commit_id):
        if version and version.lower() != "unknown":
            return version
        if commit_id:
            return commit_id[:8]
        return ""

    def _build_restart_pending_message(self, summary):
        parts = [
            self._localized(31283, "OptiKlean has been updated. Restart Kodi before using the addon."),
        ]
        if summary:
            parts.append(
                self._localized(31285, "Installed update: {summary}").format(summary=summary)
            )
        parts.append(self._localized(31173, "Would you like to restart Kodi now?"))
        return "[CR][CR]".join(part for part in parts if part)

    def _show_restart_pending_notice(self):
        xbmcgui.Dialog().notification(
            self.addon.getAddonInfo("name"),
            self._localized(
                31284,
                "Restart postponed. OptiKlean will stay unavailable until Kodi is restarted.",
            ),
            xbmcgui.NOTIFICATION_WARNING,
            4000,
        )

    def _show_update_notification(self, commit_info, version):
        """Mostra notifica e dialog all'utente"""
        short_id = commit_info['id'][:8]
        summary = self._build_update_summary(version, commit_info.get('id', ''))
        commit_message = commit_info['message'].replace('\n', '[CR]')
        
        xbmcgui.Dialog().notification(
            self._localized(31236, "OptiKlean update"),
            self._localized(31285, "Installed update: {summary}").format(
                summary=summary or short_id
            ),
            self.logo_path, 
            4000
        )
        
        try:
            xbmcgui.Dialog().ok(
                f"{self._localized(31236, 'OptiKlean update')} {summary or short_id}",
                f"{commit_message}\n\n{self._localized(31283, 'OptiKlean has been updated. Restart Kodi before using the addon.')}"
            )
            if xbmcgui.Dialog().yesno(
                self._localized(31282, "Restart required"),
                self._build_restart_pending_message(summary or short_id),
            ):
                xbmc.log("OptiKlean: User accepted restart prompt after addon update", xbmc.LOGINFO)
                _try_restart_kodi()
            else:
                xbmc.log("OptiKlean: User deferred restart after addon update", xbmc.LOGINFO)
                self._show_restart_pending_notice()
        except Exception as e:
            xbmc.log(f"OptiKlean: Dialog error: {str(e)}", xbmc.LOGERROR)

    def _build_request_headers(self):
        headers = {}
        if self.GITLAB_ACCESS_TOKEN:
            headers["Private-Token"] = self.GITLAB_ACCESS_TOKEN
        return headers

    @staticmethod
    def _log_download_progress(downloaded, file_size):
        if file_size <= 0:
            return
        percent = downloaded * 100 / file_size
        if percent % 10 == 0:
            xbmc.log(f"OptiKlean: Download {percent:.1f}% complete", xbmc.LOGDEBUG)

    def _download_once(self, url, destination):
        req = urllib.request.Request(url, headers=self._build_request_headers())
        with urllib.request.urlopen(req, timeout=30) as response, open(destination, 'wb') as out_file:  # nosec B310
            file_size = int(response.info().get('Content-Length', 0))
            downloaded = 0
            block_size = 8192
            if file_size > 256 * 1024 * 1024:
                raise ValueError("Update download exceeds size limit")

            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break

                downloaded += len(buffer)
                if downloaded > 256 * 1024 * 1024:
                    raise ValueError("Update download exceeds size limit")
                out_file.write(buffer)
                self._log_download_progress(downloaded, file_size)
            if file_size and downloaded != file_size:
                raise ValueError("Incomplete update download")

        xbmc.log(f"OptiKlean: Download complete: {downloaded} bytes", xbmc.LOGINFO)
        return True

    def _notify_download_failed(self):
        xbmcgui.Dialog().notification(
            self.addon.getLocalizedString(30998),
            self.addon.getLocalizedString(30220),
            xbmcgui.NOTIFICATION_ERROR,
            3000,
        )

    @staticmethod
    def _cleanup_download_artifacts(temp_extract, zip_path):
        try:
            if os.path.exists(temp_extract):
                shutil.rmtree(temp_extract, ignore_errors=True)
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception as error:
            xbmc.log(f"OptiKlean: Cleanup error: {str(error)}", xbmc.LOGWARNING)

    def _build_update_zip_url(self, commit_info):
        return (
            f"{self.GITLAB_PROJECT_URL}/repository/files/"
            f"{urllib.parse.quote(self.ADDON_ZIP_NAME, safe='')}/raw"
            f"?ref={commit_info['id']}"
        )

    def _download_with_retry(self, url, destination, max_retries=MAX_DOWNLOAD_RETRY):
        """Scarica un file con gestione dei tentativi"""
        # Validate URL scheme for security
        if not url.startswith('https://'):
            xbmc.log("OptiKlean: Invalid URL scheme, only HTTPS allowed", xbmc.LOGERROR)
            return False

        for attempt in range(1, max_retries + 1):
            try:
                return self._download_once(url, destination)
            except urllib.error.URLError as error:
                xbmc.log(f"OptiKlean: Download attempt {attempt} failed: {str(error)}", xbmc.LOGWARNING)
                if attempt < max_retries:
                    xbmc.sleep(2000)  # Attendi prima di riprovare

        xbmc.log("OptiKlean: Download failed after maximum retries", xbmc.LOGERROR)
        return False

    def _validate_update_paths(self):
        addon_path = os.path.abspath(self.addon_path)
        profile_path = os.path.abspath(self.profile_path)
        if (
            not os.path.isabs(self.addon_path)
            or not os.path.isabs(self.profile_path)
            or "://" in self.addon_path
            or "://" in self.profile_path
            or self.addon_path.startswith(("//", "\\\\"))
            or self.profile_path.startswith(("//", "\\\\"))
            or os.path.basename(addon_path).lower() != self.addon_id.lower()
            or os.path.islink(addon_path)
            or not os.path.isdir(addon_path)
        ):
            raise OSError("Addon and profile require separate local paths")
        try:
            profile_inside_addon = os.path.commonpath(
                [os.path.realpath(addon_path), os.path.realpath(profile_path)]
            ) == os.path.realpath(addon_path)
        except ValueError:
            profile_inside_addon = False
        if profile_inside_addon:
            raise OSError("Addon and profile require separate local paths")
        return addon_path, profile_path

    def _perform_update(self, commit_info, allow_same_version=True):
        """Install a verified package while retaining a recoverable old addon."""
        workspace = None
        lock_path = None
        lock_acquired = False
        marker_written = False
        committed = False
        installed_version = None
        try:
            self.addon_path, self.profile_path = self._validate_update_paths()
            parent = os.path.dirname(self.addon_path)
            lock_path = os.path.join(parent, f".{os.path.basename(self.addon_path)}-update-lock")
            os.mkdir(lock_path)
            lock_acquired = True
            if get_restart_pending_state():
                raise OSError("An update is already pending a Kodi restart")
            workspace = tempfile.mkdtemp(
                prefix=f".{os.path.basename(self.addon_path)}-update-", dir=parent
            )
            zip_path = os.path.join(workspace, "update.zip")
            if not self._download_with_retry(self._build_update_zip_url(commit_info), zip_path):
                self._notify_download_failed()
                return False

            match = self._extract_version(commit_info["message"])
            gitlab_version = match.group(1) if match else "unknown"
            installed_version = self._install_update(zip_path, workspace, allow_same_version)
            if installed_version is None:
                if not self._save_commit_data(commit_info["id"], gitlab_version, package_checked=True):
                    raise OSError("Failed to persist verified update commit")
                return False
            if not set_restart_pending(
                commit_id=commit_info.get("id", ""),
                version=installed_version,
                message=commit_info.get("message", ""),
            ):
                raise OSError("Failed to persist restart-pending marker")
            marker_written = True
            if not self._save_commit_data(
                commit_info["id"], gitlab_version, installed_version, package_checked=True
            ):
                raise OSError("Failed to persist update commit")
            committed = True
            xbmc.log(f"OptiKlean: Update installed. Backup: {os.path.join(workspace, 'backup')}", xbmc.LOGINFO)
            return True
        except Exception as e:
            backup = os.path.join(workspace, "backup") if workspace else None
            if backup and os.path.isdir(backup) and not committed:
                if self._rollback_update(workspace) and marker_written:
                    if not clear_restart_pending():
                        xbmc.log("OptiKlean: Failed to clear restart marker after rollback", xbmc.LOGERROR)
            recovery = f" Backup: {backup}" if backup and os.path.isdir(backup) and not committed else ""
            xbmc.log(f"OptiKlean: Update failed: {str(e)}.{recovery}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification(
                self.addon.getLocalizedString(30998),
                f"{self.addon.getLocalizedString(30221)}: {str(e)}.{recovery}",
                xbmcgui.NOTIFICATION_ERROR,
                5000,
            )
            return False
        finally:
            backup = os.path.join(workspace, "backup") if workspace else None
            recovery_needed = bool(backup and os.path.exists(backup) and not committed)
            if workspace and not recovery_needed:
                try:
                    if committed:
                        self._cleanup_download_artifacts(
                            os.path.join(workspace, "extracted"),
                            os.path.join(workspace, "update.zip"),
                        )
                    else:
                        shutil.rmtree(workspace)
                except OSError as error:
                    xbmc.log(f"OptiKlean: Update cleanup failed: {error}", xbmc.LOGWARNING)
            if lock_acquired and not recovery_needed:
                try:
                    os.rmdir(lock_path)
                except OSError as error:
                    xbmc.log(f"OptiKlean: Update lock cleanup failed: {error}", xbmc.LOGWARNING)
            if committed and installed_version is not None and self._is_auto_update_enabled():
                try:
                    self._show_update_notification(commit_info, installed_version)
                except Exception as error:
                    xbmc.log(f"OptiKlean: Update notification failed: {error}", xbmc.LOGWARNING)

    def check_and_update(self):
        """Controlla gli aggiornamenti e li installa se necessario"""
        update_status = "ENABLED" if self._is_auto_update_enabled() else "DISABLED"
        xbmc.log(f"OptiKlean: Auto-update status - Setting: {self.addon.getSetting('enable_auto_updates')}, Effective: {update_status}", xbmc.LOGDEBUG)
        xbmc.log(f"OptiKlean: Auto-updates are currently {update_status}", xbmc.LOGINFO)
        
        if not self._is_auto_update_enabled():
            xbmc.log("OptiKlean: Auto-updates disabled in settings", xbmc.LOGDEBUG)
            return False

        try:
            local_data = self._load_commit_data()
            if self._should_skip_check(local_data):
                return False
            gitlab_commit = self._get_latest_commit()
            
            xbmc.log(f"OptiKlean: gitlab_commit = {gitlab_commit}", xbmc.LOGDEBUG)

            if not gitlab_commit:
                xbmc.log("OptiKlean: Failed to retrieve commit information", xbmc.LOGWARNING)
                # Save last_check even on API failure so the rate-limit is respected
                # and we don't hammer the API every cycle when the repo is empty or unreachable.
                self._save_commit_data(
                    local_data.get('commit_id', ''),
                    local_data.get('gitlab_version', self.current_version),
                    local_data.get('local_version', self.current_version),
                    package_checked=local_data.get('package_checked') is True,
                )
                return False
            version_match = self._extract_version(gitlab_commit['message'])
            if version_match:
                try:
                    remote_is_older = _parse_version(version_match.group(1)) < _parse_version(self.current_version)
                except ValueError:
                    remote_is_older = False
                if remote_is_older:
                    xbmc.log(
                        f"OptiKlean: Remote version {version_match.group(1)} is older than installed version {self.current_version}; skipping download",
                        xbmc.LOGINFO,
                    )
                    self._save_commit_data(
                        local_data.get('commit_id', ''),
                        local_data.get('gitlab_version', self.current_version),
                        local_data.get('local_version', self.current_version),
                        package_checked=local_data.get('package_checked') is True,
                    )
                    return False
            if local_data.get('commit_id') == gitlab_commit['id']:
                xbmc.log("OptiKlean: Commit unchanged; skipping download", xbmc.LOGDEBUG)
                version_match = self._extract_version(gitlab_commit['message'])
                gitlab_version = version_match.group(1) if version_match else local_data.get('gitlab_version', self.current_version)
                self._save_commit_data(
                    gitlab_commit['id'], gitlab_version,
                    local_data.get('local_version', self.current_version),
                    package_checked=local_data.get('package_checked') is True,
                )
                return False
            return self._perform_update(
                gitlab_commit, allow_same_version=self._should_update(gitlab_commit, local_data)
            )
                
        except Exception as e:
            xbmc.log(f"OptiKlean: Critical update error: {str(e)}", xbmc.LOGERROR)
            # 30221: "Update failed"
            xbmcgui.Dialog().notification(
                self.addon.getLocalizedString(30998),  # "Error"
                self.addon.getLocalizedString(30221), 
                xbmcgui.NOTIFICATION_ERROR, 
                5000
            )
        return False
