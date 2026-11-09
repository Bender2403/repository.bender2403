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
