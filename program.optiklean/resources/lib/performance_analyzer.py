# SPDX-License-Identifier: MIT
"""Read-only, bounded performance analysis for OptiKlean."""

import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import statistics
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.parsers import expat

MAX_LOG_BYTES = 10 * 1024 * 1024
LOG_SIZE_OPTIONS = {
    "0": 5 * 1024 * 1024,
    "1": MAX_LOG_BYTES,
    "2": 25 * 1024 * 1024,
    "3": 50 * 1024 * 1024,
    "5": 5 * 1024 * 1024,
    "10": MAX_LOG_BYTES,
    "25": 25 * 1024 * 1024,
    "50": 50 * 1024 * 1024,
    "5 MB": 5 * 1024 * 1024,
    "10 MB": MAX_LOG_BYTES,
    "25 MB": 25 * 1024 * 1024,
    "50 MB": 50 * 1024 * 1024,
}
MAX_LINE_BYTES = 8192
MAX_TRACE_LINES = 16
MAX_FINDINGS = 200
MAX_EXAMPLES = 3
PROGRESS_BYTES = 64 * 1024
MAX_DEDUP_EVENTS = 20000
SLOW_INFORMATIONAL_MS = 1000
SLOW_REVIEW_MS = 5000
SLOW_ATTENTION_MS = 10000
MAX_ADDONS = 2000
ADDON_PAGE_SIZE = 100
ADDON_MANIFEST = "addon.xml"
IMPACT_ADDON_TYPES = ("xbmc.python.pluginsource", "xbmc.python.script", "xbmc.service")
MAX_MANIFEST_BYTES = 256 * 1024
MAX_MANIFEST_ITEMS = 200
FOOTPRINT_MAX_FILES = 10000
FOOTPRINT_MAX_DIRECTORIES = 2000
FOOTPRINT_MAX_DEPTH = 20
FOOTPRINT_MAX_SECONDS = 5.0
FOOTPRINT_MAX_EXAMPLES = 3
FOOTPRINT_MAX_SUMMARY_FILES = 200000
MIB = 1024 * 1024
ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")

# Performance Check policy: bounded local measurements, not a benchmark score.
CHECK_STORAGE_DEFAULT = 8 * MIB
CHECK_STORAGE_MIN = 4 * MIB
CHECK_STORAGE_MAX = 16 * MIB
CHECK_FREE_MIN = 100 * MIB
CHECK_FREE_MULTIPLIER = 10
CHECK_CHUNK_BYTES = 256 * 1024
CHECK_PASS_SECONDS = 10.0
CHECK_SAMPLES = 3
CHECK_RPC_REVIEW_MS = 1000
CHECK_RPC_ATTENTION_MS = 5000
CHECK_MAX_RPC_BYTES = 256 * 1024
CHECK_LIBRARY_LIMIT = 1
CHECK_EVIDENCE_EXAMPLES = 3

REPOSITORY_LEGACY_SCHEMA = re.compile(
    r"(?i)\berror\s*<general>:\s*repository add-on "
    r"(repository\.[a-z0-9_.-]{1,245}) uses old schema definition for the repository "
    r"extension point!\s*this is no longer supported\b"
)
REPOSITORY_UNSUPPORTED_VERSION = re.compile(
    r"(?i)\berror\s*<general>:\s*repository add-on "
    r"(repository\.[a-z0-9_.-]{1,245}) does not have any directory matching "
    r"\d+(?:\.\d+)+ and won't be able to update/serve addons!"
)

# Patterns are deliberately limited to explicit failures, not speculative causes.
PATTERNS = (
    ("repository_legacy_schema", REPOSITORY_LEGACY_SCHEMA),
    ("repository_unsupported_version", REPOSITORY_UNSUPPORTED_VERSION),
    (
        "repository_failure",
        re.compile(
            r"(?i)(?:repository.*(?:update|refresh).*(?:fail|error|timeout)|"
            r"(?:fail|error|timeout).*(?:update|refresh).*repository)"
        ),
    ),
    ("network_timeout", re.compile(r"(?i)\b(?:timed?\s*out|timeout)\b")),
    (
        "database_locked",
        re.compile(r"(?i)\b(?:database|sqlite)\b.*\b(?:locked|busy)\b"),
    ),
    ("traceback", re.compile(r"(?i)traceback \(most recent call last\):")),
    (
        "missing_dependency",
        re.compile(
            r"(?i)(?:dependency|dependencies).*(?:missing|not found|unresolved|"
            r"could not be satisfied)|(?:missing|unresolved).*dependenc"
        ),
    ),
    (
        "database_failure",
        re.compile(
            r"(?i)(?:\b(?:unable|failed|cannot|could not)\s+(?:to\s+)?(?:open|connect\s+to)"
            r"\s+(?:the\s+)?(?:database|mysql|mariadb)\b|"
            r"\b(?:failed\s+(?:database|mysql|mariadb)\s+connection|"
            r"database\s+connection\s+(?:failed|failure|refused))\b|"
            r"\b(?:sqlite|sqlite3|mysql|mariadb)\b.*\b(?:error|failed|failure|corrupt|malformed)\b|"
            r"\bsqlite3\.(?:operationalerror|databaseerror|integrityerror|programmingerror)\b|"
            r"\bsqlite_(?:error|corrupt|notadb|cantopen)\b|"
            r"\bdatabase\b.*\b(?:malformed|corrupt(?:ed)?|cannot be opened)\b)"
        ),
    ),
    (
        "inaccessible_source",
        re.compile(
            r"(?i)(?:\b(?:failed|unable|cannot|can't|could not)\s+(?:to\s+)?"
            r"(?:access|open|read|reach|find|stat)\b.*\b(?:source|share|path|file|media|directory)\b|"
            r"\b(?:source|share|path|file|media|directory)\b.*"
            r"\b(?:unavailable|inaccessible|unreachable|not found|does not exist|"
            r"cannot be (?:opened|accessed|read)|could not be (?:opened|accessed|read))\b|"
            r"\bcfile::open\b.*\b(?:failed|unable)\s+to\s+open\b|"
            r"\b(?:cdirectory::)?getdirectory\s*-\s*error getting\b)"
        ),
    ),
    (
        "connection_failure",
        re.compile(
            r"(?i)\b(?:connection refused|host (?:is )?unreachable|network (?:is )?unreachable|"
            r"(?:failed|unable|cannot|could not) (?:to )?(?:establish (?:a )?connection|connect to)|"
            r"name or service not known|temporary failure in name resolution|"
            r"getaddrinfo(?:\(\))? failed|(?:dns|name) (?:resolution|lookup) (?:failed|failure)|"
            r"(?:could not|failed to) resolve host|no route to host)\b"
        ),
    ),
)
TIMEOUT_CONFIGURATION = re.compile(
    r"(?i)\b(?:configur(?:e[ds]?|ation|ing)|setting|set|"
    r"increas(?:e|ed|ing)|chang(?:e|ed|ing))\b.*\btimeout\b|"
    r"\btimeout\b\s*(?:setting|value|configuration|is set|set to|configured|=)|"
    r"\bdefault\s+timeout\b"
)
NEGATED_FINDING = {
    "network_timeout": re.compile(r"(?i)\b(?:no|without)\s+(?:network\s+)?timeouts?\b"),
    "repository_failure": re.compile(
        r"(?i)\b(?:no|without)\s+(?:any\s+)?(?:errors?|failures?)\b"
    ),
    "database_locked": re.compile(
        r"(?i)\bdatabase\s+(?:is\s+)?not\s+(?:locked|busy)\b"
    ),
    "missing_dependency": re.compile(
        r"(?i)\b(?:not|no longer)\s+missing\b|\bno\s+(?:missing|unresolved)\s+dependenc"
    ),
    "database_failure": re.compile(
        r"(?i)\b(?:no|without)\s+(?:database |sqlite )?(?:errors?|failures?)\b"
    ),
    "inaccessible_source": re.compile(
        r"(?i)\b(?:no|without)\s+(?:missing|inaccessible|unavailable)\b"
    ),
    "connection_failure": re.compile(
        r"(?i)\b(?:no|without)\s+(?:connection refusals?|dns failures?)\b"
    ),
}
TIMESTAMP = re.compile(r"^\s*(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?)")
ADDON_PATH = re.compile(
    r"(?i)(?:^|[/\\])addons[/\\]((?:plugin|script|service|repository|"
    r"video|audio|inputstream|skin|resource|program)\.[a-z0-9_.-]+)(?=[/\\\s:'\"),]|$)"
)
ADDON_EXPLICIT = re.compile(
    r"(?i)\b(?:add-?on(?: id)?|addon_id)\s*[:=]\s*['\"]?"
    r"((?:plugin|script|service|repository|video|audio|inputstream|skin|resource|program)"
    r"\.[a-z0-9_.-]+)"
)
URL = re.compile(r"(?i)\b(?:https?|smb|nfs|ftp)://[^\s<>\"']+")
BARE_ENDPOINT = re.compile(
    r"(?i)\b(?P<host>(?:\d{1,3}\.){3}\d{1,3}|"
    r"(?:[a-z0-9-]+\.)+[a-z]{2,}|localhost)(?::(?P<port>\d{1,5}))?\b"
)
SOURCE_LOCATION = re.compile(
    r"(?i)\b(?:https?|smb|nfs|ftp)://|(?<![\w:])(?:[a-z]:[\\/]|\\\\|/(?!/))"
)
SOURCE_CONTEXT = re.compile(
    r"(?i)\b(?:source|share|directory)\b|\bcdirectory::getdirectory\b"
)
DURATION = re.compile(
    r"(?i)\b(?:took|duration|elapsed(?: time)?|completed in|finished in)"
    r"\s*[:=]?\s*(?P<value>\d{1,9}(?:\.\d{1,6})?)\s*"
    r"(?P<unit>milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|min)\b"
)
SLOW_RELEVANT = re.compile(
    r"(?i)\b(?:library|database|source|startup|start-up|scan|load|open|connect|"
    r"query|request|repository|addon|add-on|plugin|update|playback|navigation|directory)\w*\b"
)
SLOW_CONFIGURATION = re.compile(
    r"(?i)\b(?:threshold|limit|setting|configured|configuration|default|"
    r"expected|estimated|target|budget|timeout)\b"
)
AUTH = re.compile(
    r"""(?i)(\bauthorization["']?\s*[:=]\s*["']?)(?:bearer|basic)\s+[^\s,;"'}]+"""
)
SECRET = re.compile(
    r"""(?ix)(\b(?:password|passwd|pwd|token|access[_-]?token|refresh[_-]?token|
    api[_-]?key|secret|authorization)\b["']?\s*[:=]\s*)
    (?:"[^"]*"?|'[^']*'?|[^\s&;,"'}]+)"""
)
QUERY = re.compile(r"([?&][^=\s&#]+)=([^&#\s]*)")
TITLES = {
    "network_timeout": 31296,
    "repository_failure": 31297,
    "repository_legacy_schema": 31544,
    "repository_unsupported_version": 31545,
    "database_locked": 31298,
    "traceback": 31299,
    "missing_dependency": 31300,
    "connection_failure": 31320,
    "database_failure": 31321,
    "inaccessible_source": 31322,
    "slow_operation": 31323,
}


def redact(value):
    """Redact credentials before content becomes evidence or a UI model."""
    text = str(value)
    # A truncated URL can end before its @ or query string; hide it entirely.
    text = URL.sub(
        lambda match: match.group().split(":", 1)[0].lower() + "://[REDACTED]", text
    )
    text = AUTH.sub(r"\1[REDACTED]", text)
    text = SECRET.sub(r"\1[REDACTED]", text)
    # Query parameter names and values may be provider-specific secrets.
    return QUERY.sub(r"\1=[REDACTED]", text)


def _safe_excerpt(text, hide_paths=False):
    if not hide_paths:
        return redact(text)
    lines = []
    for line in text.split("\n"):
        match = SOURCE_LOCATION.search(line)
        if match:
            marker = match.group()
            marker = (
                marker.lower() + "[REDACTED]"
                if marker.endswith("://")
                else "[REDACTED PATH]"
            )
            line = line[: match.start()] + marker
        lines.append(redact(line))
    return "\n".join(lines)


def _display_log_excerpt(text):
    text = _safe_excerpt(text, hide_paths=True)
    text = re.sub(
        r"""(?i)(\b(?:file|filename|path)\s*[:=]\s*)(?:\[REDACTED FILE\]|"[^"]*"|'[^']*'|[^\s,;]+)""",
        r"\1[REDACTED FILE]",
        text,
    )
    text = re.sub(
        r"""(?i)(\bfile\s+)(?:"[^"]*"|'[^']*')""",
        r"\1[REDACTED FILE]",
        text,
    )
    return re.sub(
        r"(?i)\b[a-z_][a-z0-9_-]*(?:\.[a-z0-9_-]+)+\b",
        "[REDACTED FILE]",
        text,
    )


def _slow_measurement(line):
    match = DURATION.search(line)
    if not match:
        return None
    if SLOW_CONFIGURATION.search(line[: match.start()]):
        return None
    operation = _safe_excerpt(line[: match.start()], hide_paths=True)
    operation = re.sub(
        r"^\s*\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?"
        r"\s*(?:\d+\s+)?(?:debug|info|notice|warning|error|fatal):?\s*",
        "",
        operation,
        flags=re.IGNORECASE,
    ).strip(" :-=")
    operation = re.sub(
        r"^(?:debug|info|notice|warning|error|fatal)(?:\s*:\s*|$)",
        "",
        operation,
        flags=re.IGNORECASE,
    ).strip(" :-=")
    if not operation:
        return None
    unit = match.group("unit").lower()
    if unit.startswith("min"):
        multiplier = 60000
    elif unit.startswith("m"):
        multiplier = 1
    else:
        multiplier = 1000
    milliseconds = float(match.group("value")) * multiplier
    if milliseconds < SLOW_INFORMATIONAL_MS:
        return None
    return {
        "operation": _display_log_excerpt(operation[:160]),
        "duration_ms": milliseconds,
        "relevant": bool(SLOW_RELEVANT.search(operation) or _component(line)),
    }


def _slow_level(milliseconds, relevant):
    if milliseconds >= SLOW_ATTENTION_MS and relevant:
        return "attention"
    if milliseconds >= SLOW_REVIEW_MS:
        return "review"
    return "informational"


def icon_path(addon_path, filename):
    import xbmc

    path = os.path.join(addon_path, "resources", "media", filename)
    if os.path.isfile(path) and os.access(path, os.R_OK):
        return path
    xbmc.log(
        "OptiKlean: Performance Analyzer icon unavailable: " + filename, xbmc.LOGWARNING
    )
    return os.path.join(addon_path, "resources", "media", "icon.jpg")


def _now():
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def new_result(analyzer):
    return {
        "analyzer": analyzer,
        "status": "completed",
        "started_at": _now(),
        "completed_at": None,
        "checks_completed": [],
        "checks_skipped": [],
        "errors": [],
        "findings": [],
        "measurements": {},
        "incomplete": False,
    }


def _log_limit(addon):
    try:
        value = addon.getSetting("performance_max_log_size")
        if type(value) is int:
            value = str(value)
        return LOG_SIZE_OPTIONS.get(value, MAX_LOG_BYTES)
    except Exception:
        return MAX_LOG_BYTES


def _performance_debug(message):
    try:
        import xbmc

        xbmc.log("OptiKlean: " + message, xbmc.LOGDEBUG)
    except Exception:
        pass


def _performance_error_location(error):
    location = ("unknown", 0)
    trace = error.__traceback__
    while trace:
        if trace.tb_frame.f_code.co_filename == __file__:
            location = (trace.tb_frame.f_code.co_name, trace.tb_lineno)
        trace = trace.tb_next
    return "error={} function={} line={}".format(type(error).__name__, *location)


def _show_low_confidence(addon, debug=False):
    try:
        value = addon.getSettingBool("performance_show_low_confidence")
        enabled = value is True
        if debug:
            _performance_debug(
                "low-confidence setting enabled={} value_type={}".format(
                    enabled, type(value).__name__
                )
            )
        return enabled
    except Exception as error:
        if debug:
            _performance_debug(
                "low-confidence setting read failed error={}; enabled=False".format(
                    type(error).__name__
                )
            )
        return False


def _include_previous_log(addon):
    try:
        return addon.getSettingBool("performance_include_previous_log") is True
    except Exception:
        return False


def _component(text):
    text = URL.sub("[URL]", text)
    candidates = {
        value.lower()
        for value in ADDON_PATH.findall(text) + ADDON_EXPLICIT.findall(text)
    }
    for pattern in (REPOSITORY_LEGACY_SCHEMA, REPOSITORY_UNSUPPORTED_VERSION):
        match = pattern.search(text)
        if match and ADDON_ID.fullmatch(match.group(1)):
            candidates.add(match.group(1).lower())
    return next(iter(candidates)) if len(candidates) == 1 else None


def _endpoint(text):
    match = URL.search(text)
    if not match:
        return ""
    try:
        parsed = urlsplit(match.group())
        host = (parsed.hostname or "").lower()
        return "{}://{}{}{}".format(
            parsed.scheme.lower(),
            host,
            ":" + str(parsed.port) if parsed.port else "",
            parsed.path,
        )
    except ValueError:
        return ""


def _connection_endpoint(text):
    match = URL.search(text)
    if match:
        try:
            parsed = urlsplit(match.group())
            host, port = (parsed.hostname or "").lower(), parsed.port
            return "{}://{}{}".format(
                parsed.scheme.lower(),
                host,
                ":" + str(port) if port and port < 49152 else "",
            )
        except ValueError:
            return ""
    text = TIMESTAMP.sub("", text)
    for match in BARE_ENDPOINT.finditer(text):
        if match.start() and text[match.start() - 1] in "/\\@":
            continue
        port = int(match.group("port")) if match.group("port") else 0
        return match.group("host").lower() + (
            ":" + str(port) if port and port < 49152 else ""
        )
    return ""


def _timestamp_key(value):
    try:
        value = value.replace("T", " ").replace(",", ".")
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", value
        ):
            return None
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _record(
    events, category, lines, line_number, source, duplicate=False, measurement=None
):
    text = "\n".join(lines)
    addon_id = _component(text)
    endpoint = (
        _connection_endpoint(text)
        if category == "connection_failure"
        else _endpoint(text)
    )
    # Raw lines and credentials never enter the output or the stable identifier.
    normalized = redact(lines[0]).lower()
    normalized = re.sub(
        r"^\s*\d{4}-\d\d-\d\d[ t]\d\d:\d\d:\d\d(?:[.,]\d+)?"
        r"\s*(?:\d+\s+)?(?:debug|info|notice|warning|error|fatal):?\s*",
        "",
        normalized,
    )
    normalized = URL.sub("<url>", normalized)
    if category == "connection_failure":
        normalized = BARE_ENDPOINT.sub("<endpoint>", normalized)
    if category == "slow_operation":
        normalized = DURATION.sub("<duration>", normalized)
    normalized = re.sub(r"\b\d+\b", "#", normalized)
    if category == "traceback" and len(lines) > 1:
        normalized += "|" + re.sub(r"\b\d+\b", "#", redact(lines[-1]).lower())
    if addon_id and category in (
        "repository_legacy_schema",
        "repository_unsupported_version",
    ):
        normalized = category
    signature = "|".join((category, addon_id or "", endpoint, normalized))
    finding = events.get(signature)
    if finding is None:
        if len(events) >= MAX_FINDINGS:
            return False
        finding = {
            "id": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20],
            "analyzer": "log_analyzer",
            "category": category,
            "title": TITLES[category],
            "summary": TITLES[category],
            "potential_impact": 31306,
            "level": "informational",
            "confidence": "low",
            "evidence": [],
            "recommendations": [
                {
                    "id": "review_evidence",
                    "label": 31312,
                    "description": 31312,
                    "automatic": False,
                    "destructive": False,
                    "confirmation_required": False,
                }
            ],
            "addon_id": addon_id,
            "suppressible": False,
            "metadata": {"count": 0, "first_seen": None, "last_seen": None},
        }
        if category in ("repository_legacy_schema", "repository_unsupported_version"):
            finding["potential_impact"] = 31546
            finding["level"] = "review"
            finding["confidence"] = "high" if addon_id else "medium"
        elif category == "database_failure":
            finding["potential_impact"] = 31331
        elif category == "inaccessible_source":
            location = SOURCE_LOCATION.search(text)
            context = text[: location.start()] if location else text
            if SOURCE_CONTEXT.search(context):
                scope = "source"
            elif re.search(r"(?i)\b(?:media|file)\b", context):
                scope = "media_item"
            else:
                scope = "path"
            finding["metadata"]["scope"] = scope
            finding["potential_impact"] = 31329 if scope == "source" else 31330
        elif category == "slow_operation":
            finding["metadata"]["operation"] = measurement["operation"]
            finding["metadata"]["duration_ms"] = measurement["duration_ms"]
            finding["metadata"]["relevant"] = measurement["relevant"]
        events[signature] = finding
    metadata = finding["metadata"]
    if not duplicate:
        metadata["count"] += 1
    if measurement:
        metadata["duration_ms"] = max(
            metadata["duration_ms"], measurement["duration_ms"]
        )
        metadata["relevant"] |= measurement["relevant"]
    timestamp = TIMESTAMP.match(lines[0])
    if timestamp:
        seen = timestamp.group(1)
        seen_key = _timestamp_key(seen)
        if seen_key is not None:
            if metadata["first_seen"] is None or seen_key < _timestamp_key(
                metadata["first_seen"]
            ):
                metadata["first_seen"] = seen
            if metadata["last_seen"] is None or seen_key > _timestamp_key(
                metadata["last_seen"]
            ):
                metadata["last_seen"] = seen
    evidence = finding["evidence"]
    if len(evidence) < MAX_EXAMPLES or source not in {
        item["source"] for item in evidence
    }:
        excerpt = _display_log_excerpt(text)[:MAX_LINE_BYTES]
        item = {
            "kind": "log_excerpt",
            "summary": excerpt,
            "value": measurement["duration_ms"] if measurement else None,
            "unit": "ms" if measurement else None,
            "source": redact(source),
            "timestamp": timestamp.group(1) if timestamp else None,
            "excerpt": excerpt,
            "line": line_number,
        }
        if len(evidence) < MAX_EXAMPLES:
            evidence.append(item)
        else:
            evidence[-1] = item
    if measurement:
        finding["level"] = _slow_level(metadata["duration_ms"], metadata["relevant"])
        finding["confidence"] = "high"
    elif metadata["count"] > 1 and (
        category != "inaccessible_source" or metadata["scope"] == "source"
    ):
        finding["level"] = "review"
        finding["confidence"] = "high" if addon_id else "medium"
    return True


class _LogReadCancelled(Exception):
    pass


class _VfsLogStream:
    def __init__(self, stream, cancelled):
        self.stream = stream
        self.cancelled = cancelled
        self.buffer = b""

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, traceback):
        try:
            self.stream.close()
        except Exception:
            if error_type is None:
                raise OSError("Kodi VFS close failed")

    def _fill(self, size):
        if self.cancelled():
            raise _LogReadCancelled()
        try:
            data = self.stream.readBytes(size)
        except Exception as error:
            _performance_debug(
                "log analyzer VFS read failed error={}".format(type(error).__name__)
            )
            raise OSError("Kodi VFS read failed")
        if not isinstance(data, (bytes, bytearray)) or len(data) > size:
            _performance_debug(
                "log analyzer VFS invalid read result_type={} requested_bytes={}".format(
                    type(data).__name__, size
                )
            )
            raise OSError("Invalid Kodi VFS read")
        self.buffer += bytes(data)
        return bool(data)

    def read(self, size):
        while len(self.buffer) < size and self._fill(size - len(self.buffer)):
            pass
        value, self.buffer = self.buffer[:size], self.buffer[size:]
        return value

    def readline(self, size):
        while True:
            newline = self.buffer.find(b"\n", 0, size)
            if newline >= 0 or len(self.buffer) >= size:
                end = newline + 1 if newline >= 0 else size
                value, self.buffer = self.buffer[:end], self.buffer[end:]
                return value
            if not self._fill(size - len(self.buffer)):
                value, self.buffer = self.buffer, b""
                return value


def _open_log_stream(path, source, cancelled, vfs_open):
    try:
        stream = open(path, "rb")
        _performance_debug("log analyzer open file={} method=local".format(source))
        return stream
    except (OSError, ValueError) as error:
        _performance_debug(
            "log analyzer local open failed file={} error={}".format(
                source, type(error).__name__
            )
        )
        if vfs_open is None:
            raise
        try:
            stream = _VfsLogStream(vfs_open(source), cancelled)
            _performance_debug("log analyzer open file={} method=vfs".format(source))
            return stream
        except Exception as vfs_error:
            _performance_debug(
                "log analyzer VFS open failed file={} error={}".format(
                    source, type(vfs_error).__name__
                )
            )
            raise error


def analyze_log(
    path,
    cancelled=None,
    progress=None,
    max_bytes=MAX_LOG_BYTES,
    previous_path=None,
    vfs_open=None,
):
    """Stream each selected log with a per-file bound and shared aggregation."""
    result = new_result("log_analyzer")
    events = {}
    consumed = 0
    limited_findings = False
    dedup_limited = False
    previous_events = {}
    cancelled = cancelled or (lambda: False)
    last_progress = -PROGRESS_BYTES
    paths = []
    if previous_path is not None:
        paths.append(("previous_log", "kodi.old.log", previous_path))
    paths.append(("current_log", "kodi.log", path))
    total_limit = max_bytes * len(paths)
    log_outcomes = {}
    result["measurements"]["logs"] = log_outcomes

    def record(category, lines, line_number, source, is_previous, measurement=None):
        nonlocal limited_findings, dedup_limited
        duplicate = False
        if (
            previous_path is not None
            and TIMESTAMP.match(lines[0])
            and all(len(line.encode("utf-8")) < MAX_LINE_BYTES for line in lines)
        ):
            fingerprint = hashlib.sha256(
                (category + "\0" + "\n".join(lines)).encode("utf-8")
            ).digest()
            if is_previous:
                if (
                    fingerprint in previous_events
                    or len(previous_events) < MAX_DEDUP_EVENTS
                ):
                    previous_events[fingerprint] = (
                        previous_events.get(fingerprint, 0) + 1
                    )
                else:
                    dedup_limited = True
            elif previous_events.get(fingerprint, 0):
                previous_events[fingerprint] -= 1
                duplicate = True
        limited_findings |= not _record(
            events, category, lines, line_number, source, duplicate, measurement
        )

    for check, source, log_path in paths:
        outcome = {"status": "cancelled", "bytes_read": 0, "limit_bytes": max_bytes}
        log_outcomes[check] = outcome
        if result["status"] == "cancelled":
            result["checks_skipped"].append(check + "_cancelled")
            continue
        line_number = 0
        file_bytes = 0
        trace = None
        trace_line = 0
        discarded_line = False
        stage = "open"
        try:
            with _open_log_stream(log_path, source, cancelled, vfs_open) as stream:
                while file_bytes < max_bytes:
                    stage = "read"
                    if cancelled():
                        result["status"] = "cancelled"
                        result["incomplete"] = True
                        break
                    chunk = stream.readline(min(MAX_LINE_BYTES, max_bytes - file_bytes))
                    if not chunk:
                        break
                    consumed += len(chunk)
                    file_bytes += len(chunk)
                    outcome["bytes_read"] = file_bytes
                    if progress and consumed - last_progress >= PROGRESS_BYTES:
                        stage = "progress"
                        progress(consumed, total_limit)
                        last_progress = consumed
                    stage = "process"
                    if discarded_line:
                        discarded_line = not chunk.endswith(b"\n")
                        continue
                    line_number += 1
                    discarded_line = (
                        not chunk.endswith(b"\n") and len(chunk) == MAX_LINE_BYTES
                    )
                    line = chunk.decode("utf-8", "replace").rstrip("\r\n")
                    if trace is not None:
                        if TIMESTAMP.match(line) or len(trace) >= MAX_TRACE_LINES:
                            record(
                                "traceback",
                                trace,
                                trace_line,
                                source,
                                check == "previous_log",
                            )
                            trace = None
                        else:
                            trace.append(line)
                            if re.search(
                                r"\b\w*(?:Error|Exception|Interrupt|Exit)(?::|$)", line
                            ):
                                record(
                                    "traceback",
                                    trace,
                                    trace_line,
                                    source,
                                    check == "previous_log",
                                )
                                trace = None
                            continue
                    for category, pattern in PATTERNS:
                        if pattern.search(line):
                            if (
                                category == "network_timeout"
                                and TIMEOUT_CONFIGURATION.search(line)
                                or category in NEGATED_FINDING
                                and NEGATED_FINDING[category].search(line)
                            ):
                                continue
                            if (
                                category == "inaccessible_source"
                                and not SOURCE_LOCATION.search(line)
                            ):
                                continue
                            if category == "traceback":
                                trace, trace_line = [line], line_number
                            else:
                                record(
                                    category,
                                    [line],
                                    line_number,
                                    source,
                                    check == "previous_log",
                                )
                            break
                    measurement = _slow_measurement(line)
                    if measurement:
                        record(
                            "slow_operation",
                            [line],
                            line_number,
                            source,
                            check == "previous_log",
                            measurement,
                        )
                stage = "finalize"
                if trace:
                    record(
                        "traceback", trace, trace_line, source, check == "previous_log"
                    )
                    trace = None
                truncated = file_bytes >= max_bytes and bool(stream.read(1))
                if truncated:
                    result["incomplete"] = True
                    result["checks_skipped"].append(
                        "previous_log_limit" if check == "previous_log" else "log_limit"
                    )
                    if result["status"] != "cancelled":
                        result["status"] = "completed_with_warnings"
                if result["status"] == "cancelled":
                    result["checks_skipped"].append(check + "_cancelled")
                else:
                    if truncated:
                        outcome["status"] = "truncated"
                    elif file_bytes == 0:
                        outcome["status"] = "empty"
                    else:
                        outcome["status"] = "complete"
                    result["checks_completed"].append(check)
        except _LogReadCancelled:
            if trace:
                record("traceback", trace, trace_line, source, check == "previous_log")
            result.update(status="cancelled", incomplete=True)
            result["checks_skipped"].append(check + "_cancelled")
        except (OSError, ValueError) as error:
            _performance_debug(
                "log analyzer file={} stage={} bytes_read={} lines={} {}".format(
                    check,
                    stage,
                    file_bytes,
                    line_number,
                    _performance_error_location(error),
                )
            )
            if trace:
                record("traceback", trace, trace_line, source, check == "previous_log")
            outcome["status"] = (
                "missing" if isinstance(error, FileNotFoundError) else "unreadable"
            )
            if result["status"] != "cancelled":
                result["status"] = "completed_with_warnings"
            result["incomplete"] = True
            result["checks_skipped"].append(
                "previous_log_unavailable"
                if check == "previous_log"
                else "log_unavailable"
            )
        except Exception as error:
            _performance_debug(
                "log analyzer file={} stage={} bytes_read={} lines={} {}".format(
                    check,
                    stage,
                    file_bytes,
                    line_number,
                    _performance_error_location(error),
                )
            )
            raise
    if limited_findings:
        result["incomplete"] = True
        result["checks_skipped"].append("finding_limit")
        if result["status"] != "cancelled":
            result["status"] = "completed_with_warnings"
    if dedup_limited:
        result["incomplete"] = True
        result["checks_skipped"].append("dedup_limit")
        if result["status"] != "cancelled":
            result["status"] = "completed_with_warnings"
    result["findings"] = list(events.values())
    result["measurements"]["bytes_read"] = consumed
    result["completed_at"] = _now()
    return result


def _inventory(execute, cancelled):
    """Fetch enabled and disabled add-ons using the existing JSON-RPC pattern."""
    entries = {}
    problems = []
    stopped = False
    for enabled in (True, False):
        start = 0
        while start < MAX_ADDONS:
            if cancelled():
                stopped = True
                break
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "Addons.GetAddons",
                "params": {
                    "enabled": enabled,
                    "properties": ["name", "version", "path"],
                    "limits": {
                        "start": start,
                        "end": min(start + ADDON_PAGE_SIZE, MAX_ADDONS),
                    },
                },
            }
            try:
                response = json.loads(execute(json.dumps(request)))
                if "error" in response or not isinstance(response.get("result"), dict):
                    raise ValueError("inventory unavailable")
                data = response["result"]
                batch = data.get("addons", [])
                if not isinstance(batch, list) or len(batch) > ADDON_PAGE_SIZE:
                    raise ValueError("invalid inventory")
                for item in batch:
                    if not isinstance(item, dict):
                        problems.append("inventory_invalid")
                        continue
                    addon_id = item.get("addonid")
                    if not isinstance(addon_id, str) or not ADDON_ID.fullmatch(
                        addon_id
                    ):
                        problems.append("inventory_invalid")
                        continue
                    if enabled and (
                        not isinstance(item.get("type"), str)
                        or not item["type"]
                        or (
                            item["type"] in IMPACT_ADDON_TYPES
                            and (
                                not isinstance(item.get("path"), str)
                                or not item["path"]
                            )
                        )
                    ):
                        problems.append("inventory_invalid")
                    key = addon_id.lower()
                    if key in entries:
                        problems.append("inventory_inconsistent")
                        if entries[key]["enabled"] != enabled:
                            entries[key]["enabled"] = None
                        continue
                    if len(entries) >= MAX_ADDONS:
                        problems.append("inventory_limit")
                        break
                    entries[key] = {
                        "addon_id": key,
                        "name": _safe_excerpt(
                            str(item.get("name") or item.get("label") or "")[:256], True
                        ),
                        "version": _safe_excerpt(
                            str(item.get("version") or "")[:128], True
                        ),
                        "type": _safe_excerpt(str(item.get("type") or "")[:128], True),
                        "enabled": enabled,
                        "_path": (
                            item.get("path")
                            if isinstance(item.get("path"), str)
                            else ""
                        ),
                    }
                if "inventory_limit" in problems:
                    break
                limits = data.get("limits", {})
                total = limits.get("total") if isinstance(limits, dict) else None
                if (
                    not isinstance(total, int)
                    or total < start + len(batch)
                    or limits.get("start", start) != start
                ):
                    problems.append("inventory_inconsistent")
                    break
                if start + len(batch) >= total:
                    break
                if not batch:
                    problems.append("inventory_inconsistent")
                    break
                start += len(batch)
            except Exception:
                problems.append("inventory_unavailable")
                break
        else:
            problems.append("inventory_limit")
        if stopped or "inventory_limit" in problems:
            break
    return entries, list(dict.fromkeys(problems)), stopped


def _parse_manifest(content):
    """Reject DTDs/entities before parsing a bounded manifest."""

    def reject(*args):
        raise ValueError("unsafe XML")

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    try:
        parser.Parse(content, True)
        root = ElementTree.fromstring(content)
    except (ValueError, expat.ExpatError, ElementTree.ParseError):
        return "malformed", None
    if root.tag.split("}")[-1] != "addon":
        return "malformed", None
    manifest_id = root.get("id", "")
    if not ADDON_ID.fullmatch(manifest_id):
        return "malformed", None
    extensions = []
    dependencies = []
    for child in root:
        tag = child.tag.split("}")[-1]
        if tag == "extension":
            extensions.append(
                {
                    "point": _safe_excerpt(child.get("point", "")[:256], True),
                    "library": _safe_excerpt(child.get("library", "")[:256], True),
                }
            )
        elif tag == "requires":
            for dependency in child:
                if dependency.tag.split("}")[-1] != "import":
                    continue
                dependency_id = dependency.get("addon", "")
                if not ADDON_ID.fullmatch(dependency_id):
                    continue
                dependencies.append(
                    {
                        "addon_id": dependency_id.lower(),
                        "version": _safe_excerpt(
                            dependency.get("version", "")[:128], True
                        ),
                        "optional": dependency.get("optional", "").lower() == "true",
                    }
                )
                if len(dependencies) > MAX_MANIFEST_ITEMS:
                    return "oversized", None
        if (
            len(extensions) > MAX_MANIFEST_ITEMS
            or len(dependencies) > MAX_MANIFEST_ITEMS
        ):
            return "oversized", None
    return "ok", {
        "addon_id": manifest_id.lower(),
        "name": _safe_excerpt(root.get("name", "")[:256], True),
        "version": _safe_excerpt(root.get("version", "")[:128], True),
        "provider": _safe_excerpt(root.get("provider-name", "")[:256], True),
        "extensions": extensions,
        "dependencies": dependencies,
    }


def _read_manifest(path, translate, cache):
    if not path or len(path) > 4096:
        return "skipped", None
    try:
        local_path = translate(path) if path.startswith("special://") else path
        if (
            not isinstance(local_path, str)
            or not os.path.isabs(local_path)
            or "://" in local_path
        ):
            return "skipped", None
        manifest_path = os.path.join(local_path, ADDON_MANIFEST)
        if manifest_path in cache:
            return cache[manifest_path]
        if os.path.islink(manifest_path):
            outcome = ("unreadable", None)
        else:
            with open(manifest_path, "rb") as stream:
                content = stream.read(MAX_MANIFEST_BYTES + 1)
            outcome = (
                ("oversized", None)
                if len(content) > MAX_MANIFEST_BYTES
                else _parse_manifest(content)
            )
    except FileNotFoundError:
        outcome = ("missing", None)
    except Exception:
        outcome = ("unreadable", None)
    if "manifest_path" in locals():
        cache[manifest_path] = outcome
    return outcome


def _impact_finding(addon_id, category, level, title, evidence):
    signature = "|".join((addon_id, category, str(evidence.get("value") or "")))
    return {
        "id": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20],
        "analyzer": "addon_impact",
        "category": category,
        "title": title,
        "summary": title,
        "potential_impact": 31362,
        "level": level,
        "confidence": "high" if category == "service" else "medium",
        "addon_id": addon_id,
        "suppressible": False,
        "metadata": {"count": 1},
        "evidence": [evidence],
        "recommendations": [
            {
                "id": "review_evidence",
                "label": 31312,
                "description": 31312,
                "automatic": False,
                "destructive": False,
                "confirmation_required": False,
            }
        ],
    }


def _correlate_logs(log_result):
    correlated = {}
    seen = set()
    if not isinstance(log_result, dict) or log_result.get("analyzer") != "log_analyzer":
        return correlated
    for finding in log_result.get("findings", []):
        addon_id = finding.get("addon_id")
        finding_id = finding.get("id")
        if (
            not isinstance(addon_id, str)
            or not ADDON_ID.fullmatch(addon_id)
            or not isinstance(finding_id, str)
        ):
            continue
        key = (addon_id.lower(), finding_id)
        if key not in seen:
            seen.add(key)
            safe_finding = dict(
                finding,
                evidence=[
                    dict(
                        entry,
                        summary=_safe_excerpt(
                            entry.get("summary", ""), hide_paths=True
                        ),
                        excerpt=_safe_excerpt(entry["excerpt"], hide_paths=True),
                    )
                    for entry in finding.get("evidence", [])
                ],
            )
            correlated.setdefault(key[0], []).append(safe_finding)
    return correlated


def _storage_band(size):
    if size < 10 * MIB:
        return "small"
    if size < 100 * MIB:
        return "moderate"
    if size < 500 * MIB:
        return "notable"
    return "large"


def _open_footprint_root(path):
    if (
        os.name != "posix"
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
        or os.scandir not in os.supports_fd
    ):
        raise NotImplementedError()
    components = path.split(os.sep)
    if any(component == ".." for component in components):
        raise ValueError("path escape")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(os.sep, flags)
    try:
        for component in components:
            if not component or component == ".":
                continue
            info = os.stat(component, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("symbolic link")
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _scan_footprint(path, translate, cancelled, observe, absent_ok=False):
    """Scan only directories opened relative to no-follow directory descriptors."""
    started = time.monotonic()
    result = {
        "status": "skipped",
        "reason": None,
        "bytes": None,
        "files": 0,
        "directories": 0,
        "largest_bytes": None,
        "inaccessible": 0,
        "inaccessible_examples": [],
        "duration_ms": 0,
        "band": None,
        "cancelled": False,
    }

    def finish():
        result["duration_ms"] = max(0, int((time.monotonic() - started) * 1000))
        if result["bytes"] is not None:
            result["band"] = _storage_band(result["bytes"])
        return result

    def partial(reason, inaccessible=False):
        result["status"] = "partial"
        if reason == "cancelled":
            result["cancelled"] = True
        if result["reason"] is None:
            result["reason"] = reason
        if inaccessible:
            result["inaccessible"] += 1
            if len(result["inaccessible_examples"]) < FOOTPRINT_MAX_EXAMPLES:
                result["inaccessible_examples"].append("[REDACTED]")

    if cancelled():
        result["reason"] = "cancelled"
        result["cancelled"] = True
        return finish()
    if not isinstance(path, str) or not path or len(path) > 4096:
        result["reason"] = "unsupported"
        return finish()
    try:
        local = translate(path) if path.startswith("special://") else path
        if not isinstance(local, str) or not os.path.isabs(local) or "://" in local:
            result["reason"] = "unsupported"
            return finish()
        root = _open_footprint_root(local)
    except FileNotFoundError:
        result["status"] = "absent" if absent_ok else "unavailable"
        result["reason"] = "missing"
        return finish()
    except NotImplementedError:
        result["reason"] = "unsupported"
        return finish()
    except ValueError as error:
        result["reason"] = {
            "symbolic link": "symbolic_link",
            "path escape": "path_escape",
        }.get(str(error), "unsupported")
        return finish()
    except OSError:
        result["status"] = "unavailable"
        result["reason"] = "unreadable"
        result["inaccessible"] = 1
        result["inaccessible_examples"] = ["[REDACTED]"]
        return finish()
    except Exception:
        result["status"] = "unavailable"
        result["reason"] = "unreadable"
        return finish()

    result.update(status="complete", bytes=0, directories=1)
    stack = []
    try:
        try:
            root_info = os.fstat(root)
            visited = {(root_info.st_dev, root_info.st_ino)}
            iterator = os.scandir(root)
        except OSError:
            partial("unreadable", True)
            os.close(root)
            return finish()
        stack.append((root, iterator, 0))
        while stack:
            if cancelled():
                partial("cancelled")
                break
            if time.monotonic() - started >= FOOTPRINT_MAX_SECONDS:
                partial("time_limit")
                break
            fd, iterator, depth = stack[-1]
            try:
                entry = next(iterator)
            except StopIteration:
                iterator.close()
                os.close(fd)
                stack.pop()
                continue
            except OSError:
                partial("unreadable", True)
                iterator.close()
                os.close(fd)
                stack.pop()
                continue
            name = entry.name
            if not isinstance(name, str) or name in (".", "..") or os.sep in name:
                partial("path_escape", True)
                continue
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except OSError:
                partial("unreadable", True)
                continue
            if stat.S_ISLNK(info.st_mode):
                partial("symbolic_link")
            elif stat.S_ISREG(info.st_mode):
                if result["files"] >= FOOTPRINT_MAX_FILES:
                    partial("file_limit")
                    break
                result["files"] += 1
                size = max(0, info.st_size)
                result["bytes"] += size
                result["largest_bytes"] = max(result["largest_bytes"] or 0, size)
                observe(info, size)
            elif stat.S_ISDIR(info.st_mode):
                if result["directories"] >= FOOTPRINT_MAX_DIRECTORIES:
                    partial("directory_limit")
                    break
                result["directories"] += 1
                if depth + 1 > FOOTPRINT_MAX_DEPTH:
                    partial("depth_limit")
                    continue
                try:
                    child = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                    try:
                        child_info = os.fstat(child)
                    except OSError:
                        os.close(child)
                        raise
                    identity = (child_info.st_dev, child_info.st_ino)
                    if (child_info.st_dev, child_info.st_ino) != (
                        info.st_dev,
                        info.st_ino,
                    ):
                        os.close(child)
                        partial("changed", True)
                    elif not child_info.st_ino:
                        os.close(child)
                        partial("unsupported_entry", True)
                    elif identity in visited:
                        os.close(child)
                        partial("cycle")
                    else:
                        try:
                            child_iterator = os.scandir(child)
                        except OSError:
                            os.close(child)
                            raise
                        visited.add(identity)
                        stack.append((child, child_iterator, depth + 1))
                except OSError:
                    partial("unreadable", True)
            else:
                partial("unsupported_entry")
    finally:
        for fd, iterator, _ in reversed(stack):
            iterator.close()
            os.close(fd)
    return finish()


def _measure_footprints(items, roots, translate, cancelled):
    summary = {
        "installation_bytes": 0,
        "addon_data_bytes": 0,
        "statuses": {
            "complete": 0,
            "partial": 0,
            "skipped": 0,
            "unavailable": 0,
            "absent": 0,
        },
        "scanned": {"installation": 0, "addon_data": 0},
        "bands": {
            "installation": dict.fromkeys(("small", "moderate", "notable", "large"), 0),
            "addon_data": dict.fromkeys(("small", "moderate", "notable", "large"), 0),
        },
        "observed": False,
        "summary_limit": False,
        "identity_unavailable": False,
        "cancelled": False,
    }
    seen = set()
    unknown_roots = {"installation": False, "addon_data": False}

    def should_cancel():
        if not summary["cancelled"] and cancelled():
            summary["cancelled"] = True
        return summary["cancelled"]

    ordered = sorted(items, key=lambda value: value["addon_id"])
    for item in ordered:
        item["footprints"] = {}
    for kind in ("installation", "addon_data"):
        for item in ordered:
            path = (
                roots[item["addon_id"]]
                if kind == "installation"
                else "special://profile/addon_data/" + item["addon_id"]
            )

            def observe(info, size):
                if not info.st_ino:
                    summary["identity_unavailable"] = True
                    return
                identity = (info.st_dev, info.st_ino)
                if identity in seen:
                    return
                if len(seen) >= FOOTPRINT_MAX_SUMMARY_FILES:
                    summary["summary_limit"] = True
                    return
                seen.add(identity)
                summary[kind + "_bytes"] += size

            footprint = _scan_footprint(
                path, translate, should_cancel, observe, kind == "addon_data"
            )
            item["footprints"][kind] = footprint
            summary["statuses"][footprint["status"]] += 1
            if footprint["status"] in ("skipped", "unavailable"):
                unknown_roots[kind] = True
            if footprint["status"] in ("complete", "partial"):
                summary["scanned"][kind] += 1
                summary["bands"][kind][footprint["band"]] += 1
    summary["observed"] = (
        summary["summary_limit"]
        or summary["identity_unavailable"]
        or any(
            summary["statuses"][status]
            for status in ("partial", "skipped", "unavailable")
        )
    )
    for kind in ("installation", "addon_data"):
        if not summary["scanned"][kind] and unknown_roots[kind]:
            summary[kind + "_bytes"] = None
    return summary


def analyze_addons(execute, translate, log_result=None, cancelled=None, progress=None):
    """Assess active user-facing add-ons using the full dependency inventory."""
    cancelled = cancelled or (lambda: False)
    result = new_result("addon_impact")
    inventory, problems, stopped = _inventory(execute, cancelled)
    inventory_complete = not problems and not stopped
    result["checks_skipped"].extend(problems)
    if problems:
        result.update(status="completed_with_warnings", incomplete=True)
    if stopped:
        result.update(status="cancelled", incomplete=True)
    logs = _correlate_logs(log_result)
    cache = {}
    inspected = []
    roots = {}
    try:
        system_root = translate("special://xbmc/addons")
        if not isinstance(system_root, str) or not os.path.isabs(system_root):
            system_root = ""
        else:
            system_root = os.path.normcase(os.path.normpath(system_root))
    except Exception:
        system_root = ""

    def bundled(path):
        if path.lower().startswith("special://xbmc/addons/"):
            return True
        if not system_root or not os.path.isabs(path) or "://" in path:
            return False
        try:
            return (
                os.path.commonpath(
                    (system_root, os.path.normcase(os.path.normpath(path)))
                )
                == system_root
            )
        except ValueError:
            return False

    candidates = [
        (addon_id, item)
        for addon_id, item in inventory.items()
        if item["enabled"] is True
        and item["type"] in IMPACT_ADDON_TYPES
        and item["_path"]
        and addon_id not in ("program.optiklean", "service.xbmc.versioncheck")
        and not bundled(item["_path"])
    ]
    for index, (addon_id, item) in enumerate(candidates):
        if stopped or cancelled():
            result.update(status="cancelled", incomplete=True)
            stopped = True
        if progress and not stopped and (index == 0 or index % 20 == 0):
            progress(index, len(candidates))
        raw_path = item.pop("_path")
        roots[addon_id] = raw_path
        status, manifest = (
            ("cancelled", None)
            if stopped
            else _read_manifest(raw_path, translate, cache)
        )
        if status == "ok" and manifest["addon_id"] != addon_id:
            status, manifest = "mismatch", None
        safe_special_path = re.fullmatch(
            r"special://(?:home|xbmc)/addons/" + re.escape(addon_id) + r"/?",
            raw_path,
            re.IGNORECASE,
        )
        if safe_special_path:
            item["path"] = raw_path
        elif raw_path:
            item["path"] = "[REDACTED PATH]"
        else:
            item["path"] = ""
        item["manifest_status"] = status
        item["provider"] = manifest["provider"] if manifest else ""
        item["extensions"] = manifest["extensions"] if manifest else []
        item["dependencies"] = manifest["dependencies"] if manifest else []
        if manifest:
            item["name"] = item["name"] or manifest["name"] or addon_id
            item["version"] = item["version"] or manifest["version"]
        else:
            item["name"] = item["name"] or addon_id
        item["service"] = any(
            extension["point"] == "xbmc.service" for extension in item["extensions"]
        )
        item["related_logs"] = logs.get(addon_id, [])
        item["findings"] = []
        if status not in ("ok", "cancelled"):
            result.update(status="completed_with_warnings", incomplete=True)
            level = "review" if status in ("malformed", "mismatch") else "informational"
            item["findings"].append(
                _impact_finding(
                    addon_id,
                    "manifest",
                    level,
                    31352,
                    {
                        "kind": "manifest",
                        "summary": status,
                        "value": status,
                        "source": ADDON_MANIFEST,
                    },
                )
            )
        if item["service"]:
            service = next(
                extension
                for extension in item["extensions"]
                if extension["point"] == "xbmc.service"
            )
            item["findings"].append(
                _impact_finding(
                    addon_id,
                    "service",
                    "informational",
                    31350,
                    {
                        "kind": "extension",
                        "summary": service["point"],
                        "value": service["library"],
                        "source": ADDON_MANIFEST,
                    },
                )
            )
        dependency_issues = []
        for dependency in item["dependencies"]:
            installed = inventory.get(dependency["addon_id"])
            if installed is not None:
                dependency["installed"] = True
            elif inventory_complete:
                dependency["installed"] = False
            else:
                dependency["installed"] = None
            dependency["installed_version"] = installed["version"] if installed else ""
            dependency["enabled"] = installed["enabled"] if installed else None
            dependency["implicit_runtime"] = dependency["addon_id"].startswith("xbmc.")
            if dependency["optional"] or dependency["implicit_runtime"]:
                continue
            if (installed is None and inventory_complete) or (
                installed and installed["enabled"] is False
            ):
                dependency["issue"] = "missing" if installed is None else "disabled"
                dependency_issues.append(dependency)
        if dependency_issues:
            finding = _impact_finding(
                addon_id,
                "dependency",
                "review",
                31351,
                {
                    "kind": "dependency",
                    "summary": dependency_issues[0]["issue"],
                    "value": dependency_issues[0]["addon_id"],
                    "source": ADDON_MANIFEST,
                },
            )
            finding["evidence"] = [
                {
                    "kind": "dependency",
                    "summary": dependency["issue"],
                    "value": dependency["addon_id"],
                    "source": ADDON_MANIFEST,
                }
                for dependency in dependency_issues[:MAX_EXAMPLES]
            ]
            item["findings"].append(finding)
        recurring = [
            finding
            for finding in item["related_logs"]
            if finding.get("category") in ("network_timeout", "traceback")
            and finding.get("metadata", {}).get("count", 0) >= 2
            and finding.get("confidence") != "low"
        ]
        if item["service"] and recurring:
            finding = _impact_finding(
                addon_id,
                "service_runtime",
                "review",
                31363,
                {
                    "kind": "related_log",
                    "summary": "related_log",
                    "value": recurring[0]["id"],
                    "source": "log_analyzer",
                },
            )
            finding["potential_impact"] = 31364
            finding["metadata"]["log_ids"] = [
                entry["id"] for entry in recurring[:MAX_EXAMPLES]
            ]
            item["findings"].append(finding)
        inspected.append(item)
        result["findings"].extend(item["findings"])
    result["measurements"]["addons"] = inspected
    result["measurements"]["footprints"] = _measure_footprints(
        inspected, roots, translate, lambda: stopped or cancelled()
    )
    if not inventory_complete:
        result["measurements"]["footprints"]["observed"] = True
    footprint_summary = result["measurements"]["footprints"]
    if footprint_summary["cancelled"]:
        result.update(status="cancelled", incomplete=True)
    elif (
        footprint_summary["statuses"]["partial"]
        or footprint_summary["statuses"]["unavailable"]
        or footprint_summary["summary_limit"]
        or footprint_summary["identity_unavailable"]
    ):
        result.update(status="completed_with_warnings", incomplete=True)
    result["measurements"]["logs_available"] = (
        isinstance(log_result, dict) and log_result.get("analyzer") == "log_analyzer"
    )
    result["measurements"]["logs_incomplete"] = result["measurements"][
        "logs_available"
    ] and log_result.get("incomplete", False)
    result["measurements"]["inventory_complete"] = inventory_complete
    result["measurements"]["counts"] = {
        "inspected": sum(item["manifest_status"] != "cancelled" for item in inspected),
        "discovered": len(inspected),
        "enabled": sum(item["enabled"] is True for item in inspected),
        "disabled": sum(item["enabled"] is False for item in inspected),
        "unknown": sum(item["enabled"] is None for item in inspected),
        "services": sum(item["service"] for item in inspected),
        "dependency_issues": sum(
            any(f["category"] == "dependency" for f in item["findings"])
            for item in inspected
        ),
        "correlated": sum(bool(item["related_logs"]) for item in inspected),
        "manifest_unavailable": sum(
            item["manifest_status"] != "ok" for item in inspected
        ),
    }
    if inventory_complete:
        result["checks_completed"].append("addon_inventory")
    result["completed_at"] = _now()
    return result


def _check_path(path, translate):
    try:
        local = translate(path) if path.startswith("special://") else path
        if (
            not isinstance(local, str)
            or not os.path.isabs(local)
            or "://" in local
            or local.startswith(("//", "\\\\"))
        ):
            return None
        return local
    except Exception:
        return None


def _elapsed_ms(start, end):
    try:
        value = (end - start) * 1000.0
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _throughput(size, elapsed):
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        return None
    if (
        not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed <= 0
    ):
        return None
    try:
        value = size / MIB / (elapsed / 1000.0)
    except (OverflowError, ZeroDivisionError):
        return None
    return value if math.isfinite(value) else None


def _storage_size(value):
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and CHECK_STORAGE_MIN <= value <= CHECK_STORAGE_MAX
    ):
        return value
    return CHECK_STORAGE_DEFAULT


def _storage_check(
    profile, cancelled, clock=time.monotonic, size=CHECK_STORAGE_DEFAULT
):
    size = _storage_size(size)
    result = {
        "status": "skipped",
        "reason": "unsupported",
        "selected_size": size,
        "free_bytes": None,
        "bytes_written": 0,
        "write_ms": None,
        "write_mib_s": None,
        "bytes_read": 0,
        "read_ms": None,
        "read_mib_s": None,
        "cleanup_ok": True,
    }
    if cancelled():
        result.update(status="cancelled", reason="cancelled")
        return result
    if not profile:
        return result
    try:
        free = shutil.disk_usage(profile).free
        if not isinstance(free, int) or free < 0:
            raise ValueError("invalid free space")
        result["free_bytes"] = free
        if free <= max(CHECK_FREE_MIN, CHECK_FREE_MULTIPLIER * size):
            result["reason"] = "insufficient_space"
            return result
    except (OSError, ValueError, TypeError):
        result["reason"] = "free_space_unavailable"
        return result

    fd = None
    path = None
    try:
        fd, path = tempfile.mkstemp(prefix="optiklean-performance-", dir=profile)
        stream = os.fdopen(fd, "w+b")
        fd = None
        with stream:
            block = bytes(CHECK_CHUNK_BYTES)
            start = clock()
            while result["bytes_written"] < size:
                if cancelled():
                    result.update(status="cancelled", reason="cancelled")
                    return result
                elapsed = _elapsed_ms(start, clock())
                if elapsed is None or elapsed >= CHECK_PASS_SECONDS * 1000:
                    result.update(status="failed", reason="write_timeout")
                    return result
                chunk = block[: min(CHECK_CHUNK_BYTES, size - result["bytes_written"])]
                written = stream.write(chunk)
                if not isinstance(written, int) or written != len(chunk):
                    if isinstance(written, int) and written > 0:
                        result["bytes_written"] += min(written, len(chunk))
                    result.update(status="failed", reason="write_failed")
                    return result
                result["bytes_written"] += written
            stream.flush()
            result["write_ms"] = _elapsed_ms(start, clock())
            if (
                result["write_ms"] is None
                or result["write_ms"] > CHECK_PASS_SECONDS * 1000
            ):
                result.update(status="failed", reason="write_timeout")
                return result
            result["write_mib_s"] = _throughput(size, result["write_ms"])
            stream.seek(0)
            start = clock()
            while result["bytes_read"] < size:
                if cancelled():
                    result.update(status="cancelled", reason="cancelled")
                    return result
                elapsed = _elapsed_ms(start, clock())
                if elapsed is None or elapsed >= CHECK_PASS_SECONDS * 1000:
                    result.update(status="failed", reason="read_timeout")
                    return result
                data = stream.read(min(CHECK_CHUNK_BYTES, size - result["bytes_read"]))
                if not isinstance(data, bytes) or not data:
                    result.update(status="failed", reason="read_failed")
                    return result
                result["bytes_read"] += len(data)
            result["read_ms"] = _elapsed_ms(start, clock())
            if (
                result["read_ms"] is None
                or result["read_ms"] > CHECK_PASS_SECONDS * 1000
            ):
                result.update(status="failed", reason="read_timeout")
                return result
            result["read_mib_s"] = _throughput(size, result["read_ms"])
            result.update(status="completed", reason=None)
    except Exception:
        result.update(status="failed", reason="io_failed")
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                result["cleanup_ok"] = False
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                result["cleanup_ok"] = False
        if not result["cleanup_ok"] and result["status"] != "cancelled":
            result.update(status="failed", reason="cleanup_failed")
    return result


def _rpc_request(execute, method, params=None):
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        request["params"] = params
    try:
        raw = execute(json.dumps(request))
        if not isinstance(raw, (str, bytes)) or len(raw) > CHECK_MAX_RPC_BYTES:
            return "malformed", None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return "malformed", None
        if "error" in payload:
            error = payload["error"]
            return (
                "unavailable"
                if isinstance(error, dict) and error.get("code") == -32601
                else "rpc_error"
            ), None
        if "result" not in payload:
            return "malformed", None
        return "ok", payload["result"]
    except (ValueError, TypeError):
        return "malformed", None
    except Exception:
        return "rpc_error", None


def _latency_level(values):
    valid = [
        value
        for value in values
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ]
    if len(valid) < 2:
        return None
    median = statistics.median(valid)
    if (
        median >= CHECK_RPC_ATTENTION_MS
        and sum(v >= CHECK_RPC_ATTENTION_MS for v in valid) >= 2
    ):
        return "attention"
    if (
        median >= CHECK_RPC_REVIEW_MS
        and sum(v >= CHECK_RPC_REVIEW_MS for v in valid) >= 2
    ):
        return "review"
    return "informational"


def _sample_rpc(execute, method, params, validate, cancelled, clock=time.monotonic):
    samples, errors = [], []
    empty = False
    stopped = False
    for _ in range(CHECK_SAMPLES):
        if cancelled():
            stopped = True
            break
        start = clock()
        state, value = _rpc_request(execute, method, params)
        elapsed = _elapsed_ms(start, clock())
        if state == "ok":
            try:
                valid, is_empty = validate(value)
            except Exception:
                valid, is_empty = False, False
            if not valid or elapsed is None:
                state = "malformed"
            else:
                samples.append(elapsed)
                empty = empty or is_empty
        if state != "ok":
            errors.append(state)
            if state == "unavailable":
                break
    if stopped:
        status = "cancelled"
    elif len(samples) == CHECK_SAMPLES:
        status = "completed"
    elif samples:
        status = "incomplete"
    elif errors and all(error == "unavailable" for error in errors):
        status = "unavailable"
    else:
        status = "failed"
    return {
        "status": status,
        "samples_ms": samples,
        "errors": errors,
        "valid_samples": len(samples),
        "empty": empty,
        "min_ms": min(samples) if samples else None,
        "median_ms": statistics.median(samples) if samples else None,
        "max_ms": max(samples) if samples else None,
        "level": _latency_level(samples),
    }


def _memory_bytes(value):
    match = re.fullmatch(
        r"\s*(\d+(?:[.,]\d+)?)\s*(B|KB|KIB|MB|MIB|GB|GIB)\s*", str(value), re.IGNORECASE
    )
    if not match:
        return None
    unit = match.group(2).upper()
    multiplier = {
        "B": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": MIB,
        "MIB": MIB,
        "GB": 1024 * MIB,
        "GIB": 1024 * MIB,
    }[unit]
    try:
        number = float(match.group(1).replace(",", ".")) * multiplier
        return int(number) if math.isfinite(number) and number >= 0 else None
    except (ValueError, OverflowError):
        return None


def _system_os():
    try:
        from .backup_restore import get_current_os

        return get_current_os()
    except Exception:
        return platform.system()


def _cpu_percent(value):
    match = (
        re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%?\s*", value)
        if len(value) <= 128
        else None
    )
    number = float(match.group(1).replace(",", ".")) if match else -1
    return number if math.isfinite(number) and 0 <= number <= 100 else None


def _cpu_cores(value):
    if not value.startswith("#") or len(value) > 4096:
        return []
    parts = value.split()
    if not parts or len(parts) % 2 or len(parts) > 256:
        return []
    cores = []
    seen = set()
    for core, usage in zip(parts[::2], parts[1::2]):
        if not re.fullmatch(r"#[0-9]{1,3}:", core) or not usage.endswith("%"):
            return []
        number = int(core[1:-1])
        percent = _cpu_percent(usage)
        if number in seen or percent is None:
            return []
        seen.add(number)
        cores.append({"id": number, "percent": percent})
    return cores


def _system_snapshot(get_info, profile):
    snapshot = {
        "kodi_version": None,
        "os": None,
        "architecture": None,
        "python_version": None,
        "profile_free_bytes": None,
        "profile_total_bytes": None,
        "profile_free_percent": None,
        "memory_total_bytes": None,
        "memory_free_bytes": None,
        "cpu_percent": None,
        "cpu_cores": [],
    }
    for key, call in (
        ("os", _system_os),
        ("architecture", platform.machine),
        ("python_version", platform.python_version),
    ):
        try:
            snapshot[key] = _safe_excerpt(str(call())[:128], True) or None
        except Exception:
            pass
    for key, label in (
        ("kodi_version", "System.BuildVersion"),
        ("memory_total_bytes", "System.Memory(total)"),
        ("memory_free_bytes", "System.Memory(free)"),
        ("cpu_percent", "System.CpuUsage"),
    ):
        try:
            value = get_info(label)
            if key.startswith("memory_"):
                snapshot[key] = _memory_bytes(value)
            elif key == "cpu_percent":
                value = str(value)
                snapshot[key] = _cpu_percent(value)
                if snapshot[key] is None and len(value) <= 4096:
                    snapshot["cpu_cores"] = _cpu_cores(value.strip())
            else:
                snapshot[key] = _safe_excerpt(str(value)[:128], True) if value else None
        except Exception:
            pass
    if profile:
        try:
            usage = shutil.disk_usage(profile)
            free, total = usage.free, getattr(usage, "total", None)
            if isinstance(free, int) and free >= 0:
                snapshot["profile_free_bytes"] = free
            if isinstance(total, int) and total > 0:
                snapshot["profile_total_bytes"] = total
                if isinstance(free, int) and 0 <= free <= total:
                    snapshot["profile_free_percent"] = 100 * (free / total)
        except Exception:
            pass
    return {"status": "completed", "values": snapshot}


def _performance_finding(category, title, level, count, value):
    return {
        "id": category,
        "analyzer": "performance_check",
        "category": category,
        "title": title,
        "summary": title,
        "potential_impact": 31473,
        "level": level,
        "confidence": "medium",
        "addon_id": None,
        "suppressible": False,
        "metadata": {"count": count},
        "evidence": [
            {
                "kind": "measurement",
                "summary": category,
                "value": value,
                "unit": "ms",
            }
        ],
        "recommendations": [],
    }


def analyze_performance(
    execute,
    translate,
    get_info,
    cancelled=None,
    progress=None,
    clock=time.monotonic,
    storage_size=CHECK_STORAGE_DEFAULT,
):
    cancelled = cancelled or (lambda: False)
    started = clock()
    result = new_result("performance_check")
    measurements = result["measurements"]
    profile = _check_path("special://profile/", translate)
    checks = ("system", "storage", "rpc", "library")
    for index, check in enumerate(checks):
        if cancelled():
            result.update(status="cancelled", incomplete=True)
            result["checks_skipped"].extend(checks[index:])
            break
        if progress:
            progress(index, len(checks))
        try:
            if check == "system":
                value = _system_snapshot(get_info, profile)
            elif check == "storage":
                value = _storage_check(profile, cancelled, clock, storage_size)
            elif check == "rpc":
                ping = _sample_rpc(
                    execute,
                    "JSONRPC.Ping",
                    None,
                    lambda v: (v == "pong", False),
                    cancelled,
                    clock,
                )
                app = (
                    _sample_rpc(
                        execute,
                        "Application.GetProperties",
                        {"properties": ["version"]},
                        lambda v: (
                            isinstance(v, dict) and isinstance(v.get("version"), dict),
                            False,
                        ),
                        cancelled,
                        clock,
                    )
                    if ping["status"] != "cancelled"
                    else {"status": "cancelled"}
                )
                methods = {"ping": ping, "application": app}
                statuses = [item["status"] for item in methods.values()]
                if "cancelled" in statuses:
                    status = "cancelled"
                elif "failed" in statuses:
                    status = "failed"
                elif any(s in ("incomplete", "unavailable") for s in statuses):
                    status = "incomplete"
                else:
                    status = "completed"
                value = {"status": status, "methods": methods}
                for name, sample in methods.items():
                    if sample.get("level") in ("review", "attention"):
                        result["findings"].append(
                            _performance_finding(
                                "rpc_" + name,
                                31451,
                                sample["level"],
                                sample["valid_samples"],
                                sample["median_ms"],
                            )
                        )
            elif check == "library":
                methods = {}
                for name, method, field in (
                    ("movies", "VideoLibrary.GetMovies", "movies"),
                    ("tvshows", "VideoLibrary.GetTVShows", "tvshows"),
                    ("albums", "AudioLibrary.GetAlbums", "albums"),
                ):

                    def library_valid(payload):
                        if not isinstance(payload, dict):
                            return False, False
                        items = payload.get(field, [])
                        limits = payload.get("limits", {})
                        total = (
                            limits.get("total") if isinstance(limits, dict) else None
                        )
                        valid = (
                            isinstance(items, list)
                            and isinstance(total, int)
                            and not isinstance(total, bool)
                            and 0 <= len(items) <= min(total, CHECK_LIBRARY_LIMIT)
                            and (total == 0 or bool(items))
                        )
                        return valid, valid and total == 0

                    sample = _sample_rpc(
                        execute,
                        method,
                        {"limits": {"start": 0, "end": CHECK_LIBRARY_LIMIT}},
                        library_valid,
                        cancelled,
                        clock,
                    )
                    methods[name] = sample
                    if sample["level"] in ("review", "attention"):
                        result["findings"].append(
                            _performance_finding(
                                "library_" + name,
                                31453,
                                sample["level"],
                                sample["valid_samples"],
                                sample["median_ms"],
                            )
                        )
                    if sample["status"] == "cancelled":
                        break
                statuses = [sample["status"] for sample in methods.values()]
                if "cancelled" in statuses:
                    status = "cancelled"
                elif "failed" in statuses:
                    status = "failed"
                elif all(item == "unavailable" for item in statuses):
                    status = "skipped"
                elif any(item in ("incomplete", "unavailable") for item in statuses):
                    status = "incomplete"
                else:
                    status = "completed"
                value = {
                    "status": status,
                    "method": "movies",
                    "sample": methods["movies"],
                    "methods": methods,
                }
        except Exception:
            value = {"status": "failed", "reason": "unavailable"}
        measurements[check] = value
        if check == "storage" and not value.get("cleanup_ok", True):
            result["errors"].append({"check": check, "code": "cleanup_failed"})
            result["incomplete"] = True
        status = value["status"]
        if status == "completed":
            result["checks_completed"].append(check)
        elif status == "failed":
            result["errors"].append(
                {"check": check, "code": value.get("reason") or "failed"}
            )
            result.update(status="completed_with_warnings", incomplete=True)
        elif status == "cancelled":
            result.update(status="cancelled", incomplete=True)
            result["checks_skipped"].extend(checks[index:])
            break
        else:
            result["checks_skipped"].append(check)
            if status == "incomplete":
                result.update(status="completed_with_warnings", incomplete=True)
    measurements["elapsed_ms"] = _elapsed_ms(started, clock())
    result["completed_at"] = _now()
    return result


def _localized(addon, string_id):
    return addon.getLocalizedString(string_id)


def _log_finding_lines(addon, finding):
    info = finding["metadata"]
    sections = [
        "\n{}: {}".format(
            _localized(
                addon,
                {"attention": 31324, "review": 31314, "informational": 31315}[
                    finding["level"]
                ],
            ),
            _localized(addon, finding["title"]),
        ),
        "{}: {}  |  {}: {}  |  {}: {}".format(
            _localized(addon, 31301),
            info["count"],
            _localized(addon, 31302),
            info["first_seen"] or "-",
            _localized(addon, 31303),
            info["last_seen"] or "-",
        ),
        "{}: {}".format(
            _localized(addon, 31307),
            _localized(
                addon,
                {"low": 31308, "medium": 31309, "high": 31310}[finding["confidence"]],
            ),
        ),
    ]
    if finding.get("addon_id"):
        sections.append("{}: {}".format(_localized(addon, 31354), finding["addon_id"]))
    evidence = finding["evidence"]
    if evidence:
        sources = list(
            dict.fromkeys(
                _safe_excerpt(item["source"], hide_paths=True) for item in evidence
            )
        )
        sections.append(_localized(addon, 31541).format(sources=", ".join(sources)))
        example = _display_log_excerpt(evidence[0]["excerpt"])
        if len(example) > 512:
            example = example[:512] + "..."
        sections.append(
            _localized(addon, 31542).format(
                source=_safe_excerpt(evidence[0]["source"], hide_paths=True),
                line=evidence[0]["line"],
                excerpt=example,
            )
        )
    sections.append(_localized(addon, finding["potential_impact"]))
    recommendations = [
        action
        for action in finding["recommendations"]
        if not action.get("automatic")
        and not action.get("destructive")
        and not action.get("configuration_changing")
    ]
    if recommendations:
        sections.append(
            "{}\n{}".format(
                _localized(addon, 31311),
                _localized(addon, recommendations[0]["description"]),
            )
        )
    if finding["category"] == "slow_operation":
        sections.insert(
            1,
            "{}: {}\n{}: {} ms".format(
                _localized(addon, 31325),
                _display_log_excerpt(info["operation"]),
                _localized(addon, 31326),
                info["duration_ms"],
            ),
        )
    elif finding["category"] == "inaccessible_source":
        sections.insert(
            1, _localized(addon, 31327 if info["scope"] == "source" else 31328)
        )
    return sections


def _show_results(addon, result):
    import xbmcgui

    if result["analyzer"] == "addon_impact":
        _show_impact_results(addon, result)
        return
    if result["analyzer"] == "performance_check":
        _show_performance_results(addon, result)
        return
    summary = [_localized(addon, 31506), _localized(addon, 31538)]
    warnings = {
        "log_unavailable": 31292,
        "log_limit": 31293,
        "finding_limit": 31313,
        "previous_log_unavailable": 31317,
        "previous_log_limit": 31318,
        "dedup_limit": 31319,
    }
    if result["status"] == "cancelled":
        summary.append(_localized(addon, 31294))
    elif result["incomplete"]:
        summary.append(_localized(addon, 31465))
    outcomes = result["measurements"].get("logs", {})
    for warning in result["checks_skipped"]:
        if warning in warnings:
            status_ids = {
                ("log_unavailable", "missing"): 31338,
                ("log_unavailable", "unreadable"): 31339,
                ("previous_log_unavailable", "missing"): 31340,
                ("previous_log_unavailable", "unreadable"): 31341,
            }
            log_key = (
                "previous_log" if warning.startswith("previous_") else "current_log"
            )
            status = outcomes.get(log_key, {}).get("status")
            summary.append(
                _localized(addon, status_ids.get((warning, status), warnings[warning]))
            )
    for check, outcome in outcomes.items():
        if outcome["status"] == "empty":
            summary.append(
                _localized(addon, 31342 if check == "current_log" else 31343)
            )
    show_low = _show_low_confidence(addon, debug=True)
    findings = [
        (
            dict(
                finding,
                level="informational",
                recommendations=[
                    action
                    for action in finding["recommendations"]
                    if not action.get("automatic")
                ],
            )
            if finding["confidence"] == "low"
            else finding
        )
        for finding in result["findings"]
        if show_low or finding["confidence"] != "low"
    ]
    _performance_debug(
        "log analyzer findings total={} visible={} low_confidence_enabled={}".format(
            len(result["findings"]), len(findings), show_low
        )
    )
    if len(findings) < len(result["findings"]):
        summary.append(_localized(addon, 31337 if findings else 31528))
    if not findings:
        if (
            not result["incomplete"]
            and not result["findings"]
            and not any(outcome["status"] == "empty" for outcome in outcomes.values())
        ):
            summary.append(_localized(addon, 31539))
    else:
        summary.append(
            _localized(addon, 31540).format(
                attention=sum(f["level"] == "attention" for f in findings),
                review=sum(f["level"] == "review" for f in findings),
                informational=sum(f["level"] == "informational" for f in findings),
            )
        )
        order = {"attention": 0, "review": 1, "informational": 2}
        for finding in sorted(findings, key=lambda entry: order[entry["level"]]):
            summary.extend(_log_finding_lines(addon, finding))
    xbmcgui.Dialog().textviewer(_localized(addon, 31288), "\n".join(summary))


def _performance_status(addon, status):
    return _localized(
        addon,
        {
            "completed": 31481,
            "skipped": 31482,
            "unavailable": 31466,
            "failed": 31483,
            "incomplete": 31484,
            "cancelled": 31485,
            "not_tested": 31504,
        }.get(status, 31466),
    )


def _display_number(value):
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return "{:.2f}".format(value)
    return "-"


def _show_performance_results(addon, result):
    import xbmcgui

    measurements = result["measurements"]
    checks = ("system", "storage", "rpc", "library")
    labels = {
        "system": 31448,
        "storage": 31449,
        "rpc": 31450,
        "library": 31453,
    }
    failed_checks = {
        check
        for check in checks
        if measurements.get(check, {}).get("status") == "failed"
    }
    failed_checks.update(error.get("check") for error in result["errors"])
    lines = [
        _localized(addon, 31506),
        _localized(addon, 31455).format(
            completed=len(result["checks_completed"]),
            skipped=len(result["checks_skipped"]),
            failed=len(failed_checks),
        ),
        _localized(addon, 31456).format(
            ms=_display_number(measurements.get("elapsed_ms"))
        ),
    ]
    if result["incomplete"]:
        lines.append(
            _localized(addon, 31477 if result["status"] == "cancelled" else 31465)
        )
    for check in checks:
        value = measurements.get(check)
        lines.append(
            "\n{}: {}".format(
                _localized(addon, labels[check]),
                _performance_status(
                    addon, value.get("status", "skipped") if value else "skipped"
                ),
            )
        )
        if not value:
            continue
        if check == "system":
            fields = (
                ("kodi_version", 31492),
                ("os", 31493),
                ("architecture", 31494),
                ("python_version", 31495),
                ("profile_free_bytes", 31491),
                ("profile_total_bytes", 31522),
                ("profile_free_percent", 31523),
                ("memory_total_bytes", 31488),
                ("memory_free_bytes", 31489),
                ("cpu_percent", 31490),
            )
            for key, label in fields:
                field = value.get("values", {}).get(key)
                if key == "cpu_percent" and value.get("values", {}).get("cpu_cores"):
                    cores = value["values"]["cpu_cores"]
                    text = ", ".join(
                        "#{}: {}%".format(core["id"], _display_number(core["percent"]))
                        for core in cores
                    )
                    lines.append("{}: {}".format(_localized(addon, 31524), text))
                    continue
                if key.endswith("_bytes") and field is not None:
                    text = "{} MiB".format(_display_number(field / MIB))
                elif (
                    key in ("cpu_percent", "profile_free_percent") and field is not None
                ):
                    text = "{}%".format(_display_number(field))
                else:
                    text = str(field) if field is not None else _localized(addon, 31466)
                lines.append("{}: {}".format(_localized(addon, label), text))
        elif check == "storage":
            lines.append(
                _localized(addon, 31474).format(
                    size=_display_number(value.get("selected_size", 0) / MIB)
                )
            )
            for prefix, label in (("write", 31458), ("read", 31459)):
                lines.append(
                    _localized(addon, label).format(
                        size=value.get(
                            "bytes_written" if prefix == "write" else "bytes_read", 0
                        ),
                        ms=_display_number(value.get(prefix + "_ms")),
                        rate=_display_number(value.get(prefix + "_mib_s")),
                    )
                )
            lines.append(_localized(addon, 31460))
            if value.get("reason") == "insufficient_space":
                lines.append(_localized(addon, 31467))
            elif value.get("reason") == "unsupported":
                lines.append(_localized(addon, 31468))
            if not value.get("cleanup_ok", True):
                lines.append(_localized(addon, 31502))
        elif check in ("rpc", "library"):
            methods = value.get("methods", {})
            if check == "library":
                methods = methods or {"movies": value.get("sample", {})}
                lines.append(_localized(addon, 31527))
            for name, sample in methods.items():
                lines.append(
                    "{}: {} | {}".format(
                        _localized(
                            addon,
                            {
                                "ping": 31479,
                                "application": 31480,
                                "movies": 31497,
                                "tvshows": 31525,
                                "albums": 31526,
                            }[name],
                        ),
                        _performance_status(addon, sample.get("status", "skipped")),
                        _localized(addon, 31461).format(
                            count=sample.get("valid_samples", 0)
                        ),
                    )
                )
                if sample.get("valid_samples"):
                    lines.append(
                        _localized(addon, 31462).format(
                            minimum=_display_number(sample.get("min_ms")),
                            median=_display_number(sample.get("median_ms")),
                            maximum=_display_number(sample.get("max_ms")),
                        )
                    )
                for error, label in (
                    ("malformed", 31499),
                    ("rpc_error", 31500),
                    ("unavailable", 31501),
                ):
                    count = sample.get("errors", []).count(error)
                    if count:
                        lines.append("{}: {}".format(_localized(addon, label), count))
                if sample.get("empty"):
                    lines.append(_localized(addon, 31472))
    lines.append("\n" + _localized(addon, 31471))
    history = [
        item
        for item in measurements.get("source_history", [])
        if _show_low_confidence(addon) or item["confidence"] != "low"
    ]
    if history:
        lines.append(
            _localized(addon, 31505).format(
                count=sum(item["count"] for item in history)
            )
        )
    for level, label in (
        ("attention", 31324),
        ("review", 31314),
        ("informational", 31315),
    ):
        findings = [
            finding for finding in result["findings"] if finding["level"] == level
        ]
        lines.append("{}: {}".format(_localized(addon, label), len(findings)))
        for finding in findings:
            title = _localized(addon, finding["title"])
            library_label = {
                "library_movies": 31497,
                "library_tvshows": 31525,
                "library_albums": 31526,
            }.get(finding["category"])
            if library_label is not None:
                title += ": " + _localized(addon, library_label)
            lines.append(title)
    if not result["findings"]:
        lines.append(_localized(addon, 31464))
    xbmcgui.Dialog().textviewer(_localized(addon, 31287), "\n".join(lines))


def _visible_related(addon, item):
    show_low = _show_low_confidence(addon)
    return [
        finding
        for finding in item["related_logs"]
        if show_low or finding["confidence"] != "low"
    ]


def _impact_level(item, related):
    if any(
        finding["level"] == "review" and finding["category"] != "service_runtime"
        for finding in item["findings"]
    ):
        return "review"
    if item["service"] and any(
        finding["category"] in ("network_timeout", "traceback")
        and finding["metadata"]["count"] >= 2
        and finding["confidence"] != "low"
        for finding in related
    ):
        return "review"
    return "informational"


def _impact_size(size):
    if size is None:
        return "-"
    if size < 1024:
        return "{} B".format(size)
    if size < MIB:
        return "{} KiB".format(_display_number(size / 1024))
    return "{} MiB".format(_display_number(size / MIB))


def _impact_priority(item, related):
    if any(f["confidence"] != "low" and f["level"] == "attention" for f in related):
        return 0
    if _impact_level(item, related) == "review" or any(
        f["confidence"] != "low" and f["level"] == "review" for f in related
    ):
        return 1
    if item["manifest_status"] != "ok":
        return 2
    return 3


def _impact_item_lines(addon, item, related):
    priority = _impact_priority(item, related)
    lines = [
        "\n{}: {} ({})".format(
            _localized(addon, (31324, 31314, 31484, 31315)[priority]),
            item["name"],
            item["addon_id"],
        )
    ]
    status = item["manifest_status"]
    if status != "ok":
        state = {
            "missing": 31386,
            "skipped": 31387,
            "unreadable": 31391,
            "malformed": 31392,
            "mismatch": 31393,
            "oversized": 31394,
            "cancelled": 31485,
        }.get(status, 31358)
        lines.append(_localized(addon, 31531).format(state=_localized(addon, state)))
    issues = [d for d in item.get("dependencies", []) if d.get("issue")]
    for dependency in issues:
        state = 31386 if dependency["issue"] == "missing" else 31357
        lines.append(
            _localized(addon, 31530).format(
                addon=dependency["addon_id"], state=_localized(addon, state)
            )
        )
    if status == "ok" and not issues and not related:
        lines.append(_localized(addon, 31464))
    if item["service"]:
        lines.append(_localized(addon, 31535))
    for finding in related:
        lines.append(
            _localized(addon, 31532).format(
                title=_localized(addon, finding["title"]),
                count=finding["metadata"]["count"],
                confidence=_localized(
                    addon,
                    {"low": 31308, "medium": 31309, "high": 31310}[
                        finding["confidence"]
                    ],
                ),
            )
        )
    if (
        item["service"]
        and _impact_level(item, related) == "review"
        and any(
            finding["category"] in ("network_timeout", "traceback")
            and finding["metadata"]["count"] >= 2
            and finding["confidence"] != "low"
            for finding in related
        )
    ):
        lines.append(_localized(addon, 31364))
    return lines


def _show_impact_results(addon, result):
    import xbmcgui

    items = result["measurements"].get("addons", [])
    counts = result["measurements"].get("counts", {})
    statuses = [item["manifest_status"] for item in items]
    related = {item["addon_id"]: _visible_related(addon, item) for item in items}
    items = sorted(
        items,
        key=lambda item: (
            _impact_priority(item, related[item["addon_id"]]),
            item["addon_id"],
        ),
    )
    correlated = sum(bool(findings) for findings in related.values())
    summary = [
        _localized(addon, 31506),
        _localized(addon, 31346).format(count=counts.get("inspected", 0)),
        _localized(addon, 31543).format(
            review=sum(
                _impact_priority(item, related[item["addon_id"]]) < 2 for item in items
            ),
            incomplete=sum(item["manifest_status"] != "ok" for item in items),
        ),
        _localized(addon, 31348).format(
            services=counts.get("services", 0),
            dependency_issues=counts.get("dependency_issues", 0),
        ),
        _localized(addon, 31349).format(count=correlated),
    ]
    footprint_summary = result["measurements"].get("footprints")
    if footprint_summary:
        summary.append(
            _localized(addon, 31536).format(
                installation=_impact_size(footprint_summary["installation_bytes"]),
                data=_impact_size(footprint_summary["addon_data_bytes"]),
            )
        )
        summary.append(_localized(addon, 31439))
        if footprint_summary["observed"]:
            summary.append(_localized(addon, 31442))
        if footprint_summary["summary_limit"]:
            summary.append(_localized(addon, 31440))
        if footprint_summary["identity_unavailable"]:
            summary.append(_localized(addon, 31444))
    if "cancelled" in statuses:
        summary.append(
            _localized(addon, 31397).format(count=statuses.count("cancelled"))
        )
    if result["incomplete"]:
        summary.append(_localized(addon, 31368))
    if result["checks_skipped"]:
        summary.append(_localized(addon, 31345))
    if not result["measurements"].get("logs_available"):
        summary.append(_localized(addon, 31388))
    elif result["measurements"].get("logs_incomplete"):
        summary.append(_localized(addon, 31396))
    if any(
        len(related[item["addon_id"]]) < len(item["related_logs"]) for item in items
    ):
        summary.append(_localized(addon, 31337))
    if not items:
        summary.append(_localized(addon, 31367))
    if correlated:
        summary.append(_localized(addon, 31537))
    for item in items:
        summary.extend(_impact_item_lines(addon, item, related[item["addon_id"]]))
    xbmcgui.Dialog().textviewer(_localized(addon, 31289), "\n".join(summary))


def _run_log(addon):
    import xbmc
    import xbmcgui
    import xbmcvfs

    progress = xbmcgui.DialogProgress()
    try:
        progress.create(_localized(addon, 31288), _localized(addon, 31291))
        monitor = xbmc.Monitor()

        def log_path(name):
            special = "special://logpath/" + name
            try:
                return xbmcvfs.translatePath(special) or special
            except Exception:
                return special

        def open_vfs(name):
            special = "special://logpath/" + name
            if not xbmcvfs.exists(special):
                raise FileNotFoundError()
            return xbmcvfs.File(special)

        path = log_path("kodi.log")
        include_previous = _include_previous_log(addon)
        previous_path = log_path("kodi.old.log") if include_previous else None
        max_bytes = _log_limit(addon)
        _performance_debug(
            "log analyzer start include_previous={} per_file_limit_bytes={}".format(
                include_previous, max_bytes
            )
        )
        result = analyze_log(
            path,
            lambda: progress.iscanceled() or monitor.abortRequested(),
            lambda done, total: progress.update(int(done * 100 / total)),
            max_bytes=max_bytes,
            previous_path=previous_path,
            vfs_open=open_vfs,
        )
    except Exception as error:
        _performance_debug(
            "log analyzer unexpected {}".format(_performance_error_location(error))
        )
        xbmc.log("OptiKlean: performance-log-analysis failed", xbmc.LOGERROR)
        result = new_result("log_analyzer")
        result.update(status="failed", incomplete=True, completed_at=_now())
        result["checks_skipped"].append("log_unavailable")
    finally:
        progress.close()
    outcomes = result["measurements"].get("logs", {})
    for name in ("current_log", "previous_log"):
        if name in outcomes:
            outcome = outcomes[name]
            _performance_debug(
                "log analyzer file={} status={} bytes_read={} limit_bytes={}".format(
                    name,
                    outcome["status"],
                    outcome["bytes_read"],
                    outcome["limit_bytes"],
                )
            )
    findings = result["findings"]
    _performance_debug(
        "log analyzer result status={} incomplete={} low={} medium={} high={}".format(
            result["status"],
            result["incomplete"],
            *(
                sum(item["confidence"] == level for item in findings)
                for level in ("low", "medium", "high")
            ),
        )
    )
    _show_results(addon, result)
    return result


def _run_performance(addon, log_result=None):
    import xbmc
    import xbmcgui
    import xbmcvfs

    progress = xbmcgui.DialogProgress()
    try:
        progress.create(_localized(addon, 31287), _localized(addon, 31447))
        monitor = xbmc.Monitor()
        result = analyze_performance(
            xbmc.executeJSONRPC,
            xbmcvfs.translatePath,
            xbmc.getInfoLabel,
            cancelled=lambda: progress.iscanceled() or monitor.abortRequested(),
            progress=lambda done, total: progress.update(
                int(done * 100 / max(total, 1))
            ),
        )
    except Exception:
        xbmc.log("OptiKlean: performance-check failed", xbmc.LOGERROR)
        result = new_result("performance_check")
        result.update(status="failed", incomplete=True, completed_at=_now())
        result["checks_skipped"].extend(("system", "storage", "rpc", "library"))
        result["errors"].append({"check": "performance_check", "code": "unavailable"})
    finally:
        progress.close()
    if log_result:
        result["measurements"]["source_history"] = [
            {"count": finding["metadata"]["count"], "confidence": finding["confidence"]}
            for finding in log_result.get("findings", [])
            if finding.get("category") == "inaccessible_source"
            and finding.get("metadata", {}).get("scope") == "source"
        ]
    _show_results(addon, result)
    return result


def _run_impact(addon, log_result):
    import xbmc
    import xbmcgui
    import xbmcvfs

    progress = xbmcgui.DialogProgress()
    try:
        progress.create(_localized(addon, 31289), _localized(addon, 31344))
        monitor = xbmc.Monitor()
        result = analyze_addons(
            xbmc.executeJSONRPC,
            xbmcvfs.translatePath,
            log_result,
            lambda: progress.iscanceled() or monitor.abortRequested(),
            lambda done, total: progress.update(int(done * 100 / max(total, 1))),
        )
    except Exception:
        xbmc.log("OptiKlean: addon-impact-analysis failed", xbmc.LOGERROR)
        result = new_result("addon_impact")
        result.update(status="failed", incomplete=True, completed_at=_now())
        result["checks_skipped"].append("inventory_unavailable")
    finally:
        progress.close()
    _show_results(addon, result)
    return result


def show_menu(addon, addon_path):
    """Show tool selection without running any analysis."""
    import xbmcgui

    entries = [
        (31287, "clipboard-pulse-outline.png"),
        (31288, "file-search-outline.png"),
        (31289, "puzzle-outline.png"),
    ]
    items = []
    for string_id, filename in entries:
        item = xbmcgui.ListItem(label=_localized(addon, string_id))
        icon = icon_path(addon_path, filename)
        item.setArt({"icon": icon, "thumb": icon})
        items.append(item)
    log_result = None
    while True:
        selected = xbmcgui.Dialog().select(
            _localized(addon, 31286), items, useDetails=True
        )
        if selected < 0:
            break
        if selected == 1:
            log_result = _run_log(addon)
        elif selected == 2:
            _run_impact(addon, log_result)
        elif selected == 0:
            if log_result is None:
                _run_performance(addon)
            else:
                _run_performance(addon, log_result)
