"""The tablet's OWN settings: kept on this PC in the tablet's private folder, never in the board's config.

The small touch board has its own control room and its own night schedule; the tablet has these. Nothing here reads or writes the board's
state. Every field is checked on its own: an unknown key is dropped and an invalid value keeps the previous one, so a damaged file or a bad
request can never leave the page without settings.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path

CLOCK = re.compile(r'([01]\d|2[0-3]):[0-5]\d')
MAX_FILE = 16 * 1024
PARTS = ('dawn', 'day', 'dusk', 'night')      # the parts of the day the automatic scene follows (tablet_web/schedule.js)
MAX_POOL = 24                                  # most scenes one automatic list may hold


def _int(low, high):
    return lambda value: type(value) is int and low <= value <= high


def _float(low, high):
    return lambda value: type(value) in (int, float) and low <= value <= high


def _bool(value):
    return type(value) is bool


def _word(*words):
    return lambda value: value in words


def _names(value, scenes):
    """A list of known scene names (no repeats, in the order given, at most MAX_POOL), or None when `value` is not a list. Unknown or odd entries are dropped; an empty list means "the suggested ones"."""
    if not isinstance(value, list):
        return None
    out = []
    for item in value:
        if isinstance(item, str) and item in scenes and item not in out and len(out) < MAX_POOL:
            out.append(item)
    return out


def _clock(value):
    return isinstance(value, str) and bool(CLOCK.fullmatch(value))


# group -> {field: check}; the order here is also the order of the defaults
GROUPS = {
    'auto': {'mode': _word('daypart', 'rotate'), 'minutes': _int(5, 240)},
    'night': {'enabled': _bool, 'start': _clock, 'end': _clock, 'level': _int(5, 100), 'clock_only': _bool},
    'sound': {'enabled': _bool, 'volume': _int(0, 100), 'at_night': _bool},
    'alerts': {'quota': _int(1, 50), 'disk': _int(1, 30), 'resets': _bool},
    'photos': {'seconds': _int(5, 300)},
    'place': {'lat': _float(-90, 90), 'lon': _float(-180, 180)},
    'weather': {'enabled': _bool},
}


def defaults():
    """What a tablet starts with. The night values copy the board's defaults only as a starting point; they are separate settings."""
    return {
        'version': 1,
        'scene': 'auto',
        'motion': 'auto',
        'auto': {'mode': 'daypart', 'minutes': 20, 'rotate': [], 'parts': {part: [] for part in PARTS}},     # empty list = the suggested scenes
        'night': {'enabled': True, 'start': '23:00', 'end': '07:30', 'level': 25, 'clock_only': False},
        'sound': {'enabled': True, 'volume': 60, 'at_night': False},
        'alerts': {'quota': 10, 'disk': 5, 'resets': True},
        'photos': {'seconds': 20},
        'place': {'lat': 41.39, 'lon': 2.17},     # Barcelona: a starting point, change it in the settings sheet
        'weather': {'enabled': False},            # opt in before the weather service is contacted
    }


def apply(current, patch, scenes):
    """`current` (valid) updated with every valid field of `patch`; a new dict, nothing is modified in place."""
    out = copy.deepcopy(current)
    if not isinstance(patch, dict):
        return out
    scene = patch.get('scene')
    if isinstance(scene, str) and (scene in ('auto', 'photos') or scene in scenes):
        out['scene'] = scene
    if patch.get('motion') in ('auto', 'on', 'off'):
        out['motion'] = patch['motion']
    auto = patch.get('auto')                           # which scenes the automatic modes may show: the rotation and each part of the day
    if isinstance(auto, dict):
        names = _names(auto.get('rotate'), scenes)
        if names is not None:
            out['auto']['rotate'] = names
        if isinstance(auto.get('parts'), dict):
            for part in PARTS:
                names = _names(auto['parts'].get(part), scenes)
                if names is not None:
                    out['auto']['parts'][part] = names
    for group, checks in GROUPS.items():
        values = patch.get(group)
        if not isinstance(values, dict):
            continue
        for key, check in checks.items():
            if key in values and check(values[key]):
                out[group][key] = float(values[key]) if group == 'place' else values[key]
    return out


class Settings:
    """The current settings, loaded once and rewritten (atomically, owner-only) when something changes. `path=None` keeps them in memory only."""

    def __init__(self, path=None, scenes=()):
        self.path = Path(path) if path else None
        self.scenes = tuple(scenes)
        self.lock = threading.Lock()
        self.value = defaults()
        if self.path:
            try:
                with self.path.open('r', encoding='utf-8') as source:
                    raw = json.loads(source.read(MAX_FILE + 1)) if self.path.stat().st_size <= MAX_FILE else None
                self.value = apply(defaults(), raw, self.scenes)
            except (OSError, ValueError, UnicodeError):
                self.value = defaults()

    def get(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def update(self, patch):
        with self.lock:
            new = apply(self.value, patch, self.scenes)
            if new != self.value:
                if self.path:
                    self._write(new)
                self.value = new
            return copy.deepcopy(new)

    def _write(self, value):
        directory = self.path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle, temporary = tempfile.mkstemp(prefix='.settings-', dir=str(directory))
        try:
            os.fchmod(handle, 0o600)
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                stream.write(json.dumps(value, separators=(',', ':')))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
