# -*- coding: utf-8 -*-
"""Reliable, best-effort system information for Kodi diagnostic packages."""
import platform
import struct
import subprocess
import sys

UNKNOWN = 'Unbekannt'


def _clean(value):
    value = str(value or '').strip()
    if not value or value.lower() in {
        'unknown', 'unbekannt', 'busy', 'beschäftigt', 'system.platform',
        'system.arch', 'system.cpumodel', 'system.osversioninfo',
    }:
        return ''
    if value.lower().startswith('system.'):
        return ''
    return value


def _android_property(name):
    """Read one Android property without invoking a shell."""
    for executable in ('/system/bin/getprop', 'getprop'):
        try:
            value = subprocess.check_output(
                [executable, name], stderr=subprocess.DEVNULL,
                universal_newlines=True, timeout=2,
            )
            value = _clean(value)
            if value:
                return value
        except (OSError, subprocess.SubprocessError):
            continue

    # Some Android builds expose properties in build.prop even when getprop
    # cannot be started from the Kodi Python process.
    for path in ('/system/build.prop', '/vendor/build.prop', '/system/vendor/build.prop'):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as source:
                for line in source:
                    if line.startswith(name + '='):
                        value = _clean(line.split('=', 1)[1])
                        if value:
                            return value
        except OSError:
            continue
    return ''


def _cpu_info_value():
    preferred = ('model name', 'hardware', 'processor')
    found = {}
    try:
        with open('/proc/cpuinfo', 'r', encoding='utf-8', errors='replace') as source:
            for line in source:
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key = key.strip().lower()
                if key in preferred and key not in found:
                    value = _clean(value)
                    if value:
                        found[key] = value
    except OSError:
        pass
    for key in preferred:
        if found.get(key):
            return found[key]
    return ''


def _architecture():
    machine = _clean(platform.machine()).lower()
    try:
        bits = struct.calcsize('P') * 8
    except Exception:
        bits = 0

    if machine in ('aarch64', 'arm64'):
        return 'ARM 64-Bit'
    if machine.startswith(('arm', 'armeabi')):
        return 'ARM %s-Bit' % bits if bits in (32, 64) else 'ARM (Bitbreite unbekannt)'
    if machine in ('x86_64', 'amd64'):
        return 'x86_64 (64-Bit)'
    if machine in ('i386', 'i486', 'i586', 'i686', 'x86'):
        return 'x86 (32-Bit)'
    if machine:
        return '%s (%s-Bit)' % (machine, bits) if bits in (32, 64) else machine
    return '%s-Bit' % bits if bits in (32, 64) else UNKNOWN


def build_system_report(addon_version, kodi_version, android_hint=False):
    """Build the report using Python runtime APIs and Android system properties."""
    try:
        python_version = '.'.join(str(part) for part in sys.version_info[:3])
    except Exception:
        python_version = UNKNOWN

    system_name = _clean(platform.system())
    android = bool(android_hint) or sys.platform == 'android' or system_name.lower() == 'android'
    if android:
        manufacturer = _android_property('ro.product.manufacturer')
        model = _android_property('ro.product.model')
        device = _android_property('ro.product.device')
        release = _android_property('ro.build.version.release')
        os_name = 'Android ' + release if release else 'Android (Version unbekannt)'
        platform_name = (
            'Android / Amazon Fire TV'
            if manufacturer and 'amazon' in manufacturer.lower()
            else 'Android'
        )
        device_parts = [part for part in (manufacturer, model, device) if part]
        device_name = ' / '.join(dict.fromkeys(device_parts)) if device_parts else UNKNOWN
        cpu = _android_property('ro.soc.model') or _cpu_info_value()
    else:
        platform_name = system_name or _clean(sys.platform) or UNKNOWN
        release = _clean(platform.release())
        os_name = (platform_name + ' ' + release).strip() if release else platform_name
        device_name = _clean(platform.node()) or UNKNOWN
        cpu = _clean(platform.processor()) or _cpu_info_value()

    values = {
        'Kodi-Version': _clean(kodi_version) or UNKNOWN,
        'Python-Version': python_version or UNKNOWN,
        'Plattform': platform_name or UNKNOWN,
        'Gerät': device_name,
        'Betriebssystem': os_name or UNKNOWN,
        'Architektur': _architecture(),
        'CPU': cpu or UNKNOWN,
    }
    lines = [
        'Kodi Diag Diagnosepaket',
        'Add-on-Version: ' + (_clean(addon_version) or UNKNOWN),
    ]
    lines.extend('%s: %s' % item for item in values.items())
    return '\n'.join(lines)
