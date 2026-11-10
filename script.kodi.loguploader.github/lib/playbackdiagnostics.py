# -*- coding: utf-8 -*-
"""Automatic, disk-backed capture of Kodi video playback log sections."""
import datetime
import os
import re
import time

VIDEO_PLUGIN = re.compile(r'^plugin://([^/?#]+)', re.I)
MAX_CAPTURE_LOG_SIZE = 8 * 1024 * 1024
READ_CHUNK_SIZE = 64 * 1024
PRE_ROLL_BYTES = 256 * 1024
MAX_PENDING_LINE = 256 * 1024


def addon_id_from_path(path):
    """Return the Kodi plugin id for plugin:// playback, or video.local."""
    match = VIDEO_PLUGIN.match(str(path or ''))
    if match:
        return re.sub(r'[^A-Za-z0-9_.-]', '_', match.group(1))
    return 'video.local'


def _safe_name(value):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', str(value or 'video.local'))[:100] or 'video.local'


class PlaybackRecorder:
    """Copies appended kodi.log bytes incrementally to a sanitized session file."""

    def __init__(self, log_file, output_root, cleaner, temp_dir=None, log_dir=None):
        self.log_file = log_file
        self.output_root = output_root
        self.cleaner = cleaner
        self.temp_dir = temp_dir
        self.log_dir = log_dir
        self.folder = None
        self.output = None
        self.offset = 0
        self.started_at = 0
        self.pending = ''
        self.discard_long_line = False
        self.written = 0
        self.truncated = False

    @property
    def active(self):
        return self.output is not None

    def start(self, playing_file):
        if self.active:
            self.finish()
        addon_id = _safe_name(addon_id_from_path(playing_file))
        stamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        if not os.path.isdir(self.output_root):
            os.makedirs(self.output_root)
        base = '%s_%s' % (addon_id, stamp)
        folder = os.path.join(self.output_root, base)
        suffix = 1
        while os.path.exists(folder):
            suffix += 1
            folder = os.path.join(self.output_root, '%s_%d' % (base, suffix))
        os.makedirs(folder)
        self.folder = folder
        self.output = open(os.path.join(folder, 'kodi.log'), 'wb')
        self.started_at = time.time()
        try:
            size = os.path.getsize(self.log_file)
        except OSError:
            size = 0
        self.offset = max(0, size - PRE_ROLL_BYTES)
        self.pending = ''
        self.discard_long_line = False
        self.written = 0
        self.truncated = False
        self.poll(drain=True)
        return folder

    def _write_line(self, line):
        if self.output is None or self.truncated:
            return
        cleaned = self.cleaner(line.replace('\x00', ''))
        data = cleaned.encode('utf-8', 'replace')
        remaining = MAX_CAPTURE_LOG_SIZE - self.written
        if remaining <= 0:
            self.truncated = True
            return
        if len(data) > remaining:
            data = data[:remaining]
            self.truncated = True
        if data:
            self.output.write(data)
            self.written += len(data)

    def _consume_text(self, text, final=False):
        if self.truncated:
            return
        self.pending += text
        while self.pending:
            if self.discard_long_line:
                newline = self.pending.find('\n')
                if newline < 0:
                    self.pending = ''
                    return
                self.pending = self.pending[newline + 1:]
                self.discard_long_line = False
                continue
            newline = self.pending.find('\n')
            if newline >= 0:
                line = self.pending[:newline + 1]
                self.pending = self.pending[newline + 1:]
                self._write_line(line)
                if self.truncated:
                    return
                continue
            if len(self.pending) > MAX_PENDING_LINE:
                self.pending = ''
                self.discard_long_line = True
                self._write_line('[Kodi Diag: überlange Logzeile ausgelassen]\n')
                return
            break
        if final and self.pending and not self.discard_long_line:
            self._write_line(self.pending)
            self.pending = ''

    def poll(self, drain=False):
        if not self.active or self.truncated:
            return
        try:
            size = os.path.getsize(self.log_file)
            if size < self.offset:
                self.offset = 0
                self._consume_text('\n[Kodi Diag: Kodi-Log wurde während der Wiedergabe rotiert]\n')
            with open(self.log_file, 'rb') as source:
                source.seek(self.offset)
                while True:
                    chunk = source.read(READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    self.offset += len(chunk)
                    self._consume_text(chunk.decode('utf-8', 'replace'))
                    if self.truncated or not drain:
                        break
        except OSError:
            return

    def _collect_manifests(self):
        if not self.folder:
            return
        roots = [root for root in (self.temp_dir, self.log_dir) if root and os.path.isdir(root)]
        count = 0
        seen = set()
        for root in roots:
            for current, dirs, names in os.walk(root):
                depth = os.path.relpath(current, root).count(os.sep)
                dirs[:] = [d for d in dirs if d.lower() not in (
                    'cdm', 'license', 'licenses', 'widevine', 'kodi_loguploader'
                ) and not os.path.islink(os.path.join(current, d))]
                if depth > 2:
                    dirs[:] = []
                    continue
                for name in names:
                    if count >= 4:
                        return
                    if not name.lower().endswith(('.mpd', '.m3u8')):
                        continue
                    path = os.path.join(current, name)
                    if path in seen or os.path.islink(path):
                        continue
                    seen.add(path)
                    try:
                        stat = os.stat(path)
                        if stat.st_mtime < self.started_at - 2 or stat.st_size <= 0 or stat.st_size > 1024 * 1024:
                            continue
                        with open(path, 'rb') as stream:
                            content = stream.read(1024 * 1024 + 1)
                        if len(content) > 1024 * 1024:
                            continue
                        text = content.decode('utf-8', 'replace').replace('\x00', '')
                        text = self.cleaner(text)
                        extension = os.path.splitext(name)[1].lower()
                        target = os.path.join(self.folder, 'manifest-%d%s' % (count + 1, extension))
                        with open(target, 'wb') as output:
                            output.write(text.encode('utf-8', 'replace'))
                        count += 1
                    except OSError:
                        continue

    def finish(self):
        if not self.active:
            return None
        self.poll(drain=True)
        self._consume_text('', final=True)
        if self.truncated:
            try:
                self.output.write('\n[Kodi Diag: Log-Aufzeichnung auf 8 MiB begrenzt]\n'.encode('utf-8'))
            except Exception:
                pass
        try:
            self.output.flush()
            self.output.close()
        finally:
            self.output = None
        self._collect_manifests()
        folder = self.folder
        self.folder = None
        return folder


def run():
    """Kodi service entry point. The setting is off by default."""
    import xbmc
    import xbmcaddon
    import xbmcvfs
    from . import loguploader

    addon = xbmcaddon.Addon()
    temp_dir = xbmcvfs.translatePath('special://temp')
    log_dir = xbmcvfs.translatePath('special://logpath')
    base_dir = os.path.join(temp_dir, 'kodi_loguploader')
    diagnose_dir = os.path.join(base_dir, 'diagnose')
    marker_path = os.path.join(base_dir, 'auto_mode_active')
    if not os.path.isdir(base_dir):
        os.makedirs(base_dir)

    recorder = PlaybackRecorder(
        loguploader.LOG_FILE, diagnose_dir, loguploader._clean_log,
        temp_dir=temp_dir, log_dir=log_dir
    )

    class VideoPlayer(xbmc.Player):
        def __init__(self):
            super(VideoPlayer, self).__init__()
            self.owns_logging_state = False

        def start_capture(self):
            if addon.getSetting('auto_diagnostics').lower() != 'true' or not self.isPlayingVideo():
                return
            if recorder.active:
                self.stop_capture()
            try:
                self.owns_logging_state = bool(loguploader._start_diagnostics(None))
                recorder.start(self.getPlayingFile())
                xbmc.log('[Kodi Diag] Video-Diagnose gestartet: %s' % os.path.basename(recorder.folder), xbmc.LOGINFO)
            except Exception as exc:
                if self.owns_logging_state:
                    loguploader._restore_diagnostics()
                self.owns_logging_state = False
                xbmc.log('[Kodi Diag] Start der Video-Diagnose fehlgeschlagen: %s' % exc, xbmc.LOGERROR)

        def stop_capture(self):
            try:
                if recorder.active:
                    folder = recorder.finish()
                    xbmc.log('[Kodi Diag] Video-Diagnose gespeichert: %s' % os.path.basename(folder or ''), xbmc.LOGINFO)
            except Exception as exc:
                xbmc.log('[Kodi Diag] Fehler beim Abschließen der Video-Aufzeichnung: %s' % exc, xbmc.LOGERROR)
            finally:
                if self.owns_logging_state:
                    try:
                        loguploader._restore_diagnostics()
                    except Exception as exc:
                        xbmc.log('[Kodi Diag] Kodi-Logging konnte nicht wiederhergestellt werden: %s' % exc, xbmc.LOGERROR)
                self.owns_logging_state = False

        def onAVStarted(self):
            try:
                if self.isPlayingVideo():
                    self.start_capture()
            except Exception as exc:
                xbmc.log('[Kodi Diag] Fehler in onAVStarted: %s' % exc, xbmc.LOGERROR)

        def onPlayBackEnded(self):
            self.stop_capture()

        def onPlayBackStopped(self):
            self.stop_capture()

        def onPlayBackError(self):
            self.stop_capture()

    player = VideoPlayer()
    monitor = xbmc.Monitor()
    previous_enabled = addon.getSetting('auto_diagnostics').lower() == 'true'
    if previous_enabled:
        with open(marker_path, 'w', encoding='utf-8') as marker:
            marker.write('active')
    elif os.path.exists(marker_path):
        loguploader.finish_automatic_diagnostics()
        os.remove(marker_path)

    xbmc.log('[Kodi Diag] Hintergrunddienst gestartet.', xbmc.LOGINFO)
    while not monitor.abortRequested():
        enabled = addon.getSetting('auto_diagnostics').lower() == 'true'
        if enabled:
            if not os.path.exists(marker_path):
                with open(marker_path, 'w', encoding='utf-8') as marker:
                    marker.write('active')
            if player.isPlayingVideo() and not recorder.active:
                player.start_capture()
            recorder.poll()
        elif previous_enabled or os.path.exists(marker_path):
            player.stop_capture()
            loguploader.finish_automatic_diagnostics()
            try:
                os.remove(marker_path)
            except OSError:
                pass
        previous_enabled = enabled
        if monitor.waitForAbort(1):
            break

    player.stop_capture()
    xbmc.log('[Kodi Diag] Hintergrunddienst beendet.', xbmc.LOGINFO)
