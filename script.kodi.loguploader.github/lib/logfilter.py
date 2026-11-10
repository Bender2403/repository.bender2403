# -*- coding: utf-8 -*-
"""Conservative, size-bounded filtering for Kodi log files."""
import re

_TIMESTAMP = re.compile(r'^\s*\d{4}-\d{2}-\d{2}[ T]+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*(?:T:\d+\s*)?(?:-\s*)?')
_ERROR = re.compile(
    r'\b(error|warning|critical|fatal|exception|traceback|assertionerror|'
    r'failed|failure|timed?\s*out|timeout|ssl|certificate|unauthori[sz]ed|'
    r'forbidden|http[/ ](?:1\.[01] )?[45]\d\d|widevine|drm)\b',
    re.I,
)
_LIFECYCLE = re.compile(r'\b(starting|started|stopping|stopped|shutting down|'
                        r'shut down|initiali[sz]ing|initialized)\b', re.I)
_TRACEBACK_START = re.compile(r'^(?:Traceback \(most recent call last\):|'
                              r'\s*File ".+", line \d+)', re.I)


def _normalise(line):
    return _TIMESTAMP.sub('', line).strip()


def _matches_addon(line, addon_tokens):
    lowered = line.lower()
    for token in addon_tokens:
        token = str(token or '').strip()
        if not token:
            continue
        if token.lower() in lowered:
            return True
    return False


def _priority(line, addon_tokens):
    if _matches_addon(line, addon_tokens):
        return 3
    if _ERROR.search(line):
        return 3
    if _LIFECYCLE.search(line):
        return 2
    return 0


def _collapse_repeats(entries):
    """Collapse adjacent identical messages while preserving occurrence counts."""
    result = []
    index = 0
    while index < len(entries):
        line, priority = entries[index]
        signature = _normalise(line)
        end = index + 1
        while end < len(entries):
            next_line, next_priority = entries[end]
            if next_priority != priority or _normalise(next_line) != signature:
                break
            end += 1
        count = end - index
        result.append(line)
        if count > 1:
            result.append('[Kodi-Logfilter: identische Meldung %d-mal; erste Fundstelle behalten; weitere Wiederholungen zusammengefasst]' % count)
        index = end
    return result


def filter_log(content, addon_tokens=None, max_output_bytes=2 * 1024 * 1024,
               context_lines=3):
    """Return a conservative diagnostic excerpt and line statistics.

    Error-level messages and selected add-on messages are retained with nearby
    context. Repetitive identical adjacent messages are summarized. If no
    signal is found, the last 100 lines are retained as a useful fallback.
    """
    addon_tokens = addon_tokens or []
    lines = content.splitlines()
    priorities = {}
    for index, line in enumerate(lines):
        priority = _priority(line, addon_tokens)
        if priority:
            priorities[index] = max(priorities.get(index, 0), priority)
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            for context_index in range(start, end):
                priorities.setdefault(context_index, 1)

        # Preserve complete Python traceback blocks, not just their first line.
        if _TRACEBACK_START.search(line):
            priorities[index] = 3
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor]
                if candidate.strip() and not candidate[:1].isspace() and not _ERROR.search(candidate):
                    break
                priorities[cursor] = 3
                cursor += 1

    if not priorities and lines:
        for index in range(max(0, len(lines) - 100), len(lines)):
            priorities[index] = 1

    # Reserve room for the explanation header. Select important lines first,
    # then context, but restore chronological order before writing the result.
    header = '[Kodi-Logfilter: gefilterter Auszug; Fehler und ausgewählte Add-ons werden bevorzugt; Heuristik, kein vollständiges Original]\n'
    budget = max(0, int(max_output_bytes) - len(header.encode('utf-8')))
    chosen = set()
    used = 0
    for priority in (3, 2, 1):
        for index in sorted(priorities):
            if priorities[index] != priority:
                continue
            encoded_size = len((lines[index] + '\n').encode('utf-8', 'replace'))
            if used + encoded_size <= budget:
                chosen.add(index)
                used += encoded_size

    selected = [(lines[index], priorities[index]) for index in sorted(chosen)]
    collapsed = _collapse_repeats(selected)
    output = header + ('\n'.join(collapsed) + '\n' if collapsed else '')
    # A repeat summary can make the result larger; enforce the hard byte cap.
    encoded = output.encode('utf-8', 'replace')
    if len(encoded) > max_output_bytes:
        encoded = encoded[:max_output_bytes]
        output = encoded.decode('utf-8', 'ignore')
    return output, {
        'total_lines': len(lines),
        'kept_lines': len(chosen),
        'removed_lines': max(0, len(lines) - len(chosen)),
        'output_bytes': len(output.encode('utf-8')),
        'matched_addon_lines': sum(
            1 for index, line in enumerate(lines)
            if _matches_addon(line, addon_tokens)
        ),
    }




def filter_log_stream(lines, addon_tokens=None, max_output_bytes=2 * 1024 * 1024,
                      context_lines=3):
    """Filter a line iterator while bounding retained candidates by output size."""
    addon_tokens = addon_tokens or []
    header = '[Kodi-Logfilter: gefilterter Auszug; Fehler und ausgewählte Add-ons werden bevorzugt; Heuristik, kein vollständiges Original]\n'
    budget = max(0, int(max_output_bytes) - len(header.encode('utf-8')))
    candidates = {}
    max_candidate_lines = 20000
    bucket_bytes = {1: 0, 2: 0, 3: 0}
    ring = []
    pending_context = 0
    traceback_active = False
    total_lines = 0
    matched_addon_lines = 0
    recent = []

    def add(index, line, priority):
        old = candidates.get(index)
        if old and old[0] >= priority:
            return
        if old is None and len(candidates) >= max_candidate_lines:
            return
        encoded_size = len((line + '\n').encode('utf-8', 'replace'))
        previous_size = len((old[1] + '\n').encode('utf-8', 'replace')) if old else 0
        available = bucket_bytes[priority]
        if encoded_size <= budget and available + encoded_size <= budget:
            if old:
                bucket_bytes[old[0]] -= previous_size
            candidates[index] = (priority, line)
            bucket_bytes[priority] += encoded_size

    for raw in lines:
        line = raw.rstrip('\r\n')
        total_lines += 1
        recent.append((total_lines - 1, line))
        if len(recent) > 100:
            recent.pop(0)
        priority = _priority(line, addon_tokens)
        if _matches_addon(line, addon_tokens):
            matched_addon_lines += 1
        if priority:
            for previous_index, previous in ring:
                add(previous_index, previous, 1)
            add(total_lines - 1, line, priority)
            pending_context = context_lines
        elif pending_context:
            add(total_lines - 1, line, 1)
            pending_context -= 1
        if _TRACEBACK_START.search(line):
            traceback_active = True
            add(total_lines - 1, line, 3)
        elif traceback_active:
            if line.strip() and not line[:1].isspace() and not _ERROR.search(line):
                traceback_active = False
            else:
                add(total_lines - 1, line, 3)
        ring.append((total_lines - 1, line))
        if len(ring) > context_lines:
            ring.pop(0)

    if not candidates and total_lines:
        for index, line in recent:
            encoded_size = len((line + '\n').encode('utf-8', 'replace'))
            if bucket_bytes[1] + encoded_size > budget:
                break
            candidates[index] = (1, line)
            bucket_bytes[1] += encoded_size

    selected = []
    used = 0
    for priority in (3, 2, 1):
        for index in sorted(candidates):
            candidate_priority, line = candidates[index]
            if candidate_priority != priority:
                continue
            encoded_size = len((line + '\n').encode('utf-8', 'replace'))
            if used + encoded_size <= budget:
                selected.append((index, line, priority))
                used += encoded_size
    selected.sort(key=lambda item: item[0])
    collapsed = _collapse_repeats([(line, priority) for _, line, priority in selected])
    output = header + ('\n'.join(collapsed) + '\n' if collapsed else '')
    encoded = output.encode('utf-8', 'replace')
    if len(encoded) > max_output_bytes:
        output = encoded[:max_output_bytes].decode('utf-8', 'ignore')
    return output, {
        'total_lines': total_lines,
        'kept_lines': len(selected),
        'removed_lines': max(0, total_lines - len(selected)),
        'output_bytes': len(output.encode('utf-8')),
        'matched_addon_lines': matched_addon_lines,
    }


def filter_protocol_logs(content, http_enabled=True, drm_enabled=True):
    """Remove protocol-specific debug lines disabled in the add-on settings.

    Kodi uses its global debug level for InputStream Adaptive messages and a
    separate CURL component mask for HTTP headers/status lines. This filter
    keeps the uploaded package consistent with the user's two independent
    protocol switches.
    """
    if http_enabled and drm_enabled:
        return content, {"http_removed": 0, "drm_removed": 0}

    kept = []
    http_removed = 0
    drm_removed = 0
    for line in content.splitlines(True):
        if not http_enabled and re.search(
                r'(?:Curl::Debug|HEADER_(?:IN|OUT):|<[^>]*curl[^>]*>)',
                line, re.I):
            http_removed += 1
            continue
        if not drm_enabled and re.search(
                r'(?:inputstream\.adaptive|AddOnLog:\s*inputstream\.adaptive)',
                line, re.I):
            drm_removed += 1
            continue
        kept.append(line)

    return ''.join(kept), {
        "http_removed": http_removed,
        "drm_removed": drm_removed,
    }
