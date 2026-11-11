"""Strict checker for the `live` block of a tablet scene (private manifest `scenes.json`).

A scene of the `photo` look may carry an optional `live` object that describes real-time effects drawn by the page's scene stage
(`token_tv/tablet_web/stage-live.js`): rippling water with glints, drifting clouds, twinkling lights, mist, light rain and a few craft or
birds crossing the sky. Every position is a fraction of the PICTURE (0..1, origin top left; craft paths may start and end a little
outside it) and every size a fraction of its HEIGHT, so one preset suits any screen. The server calls `live_info(raw, scene)` for each
catalogue entry and puts the answer under `info[scene]["live"]` of `/api/scenes`; the page checks it once more.

    {"water":  {"regions": [[0, .74, 1, 1]], "amount": 1, "glints": 1},
     "clouds": {"regions": [[[0, 0], [1, 0], [1, .6], [0, .7]]], "amount": 1},
     "lights": {"amount": 1}, "mist": {"regions": [[0, .6, 1, .8]], "amount": .4}, "rain": {"amount": .4},
     "craft":  [{"kind": "gull", "from": [-.1, .2], "to": [1.1, .12], "seconds": 40}],
     "lamps":  {"rows": [{"provider": "codex", "x": [.225, .55], "y": .714, "count": 26, "anchor": "start"}]}}

`lamps` is the one effect that carries DATA: rows of small lamp modules (the small board's Neon City bridge, Tony 2026-11-09) that light with the
provider's weekly quota left, anchored at the row's outer end and retracting as it is spent. The page reads the quota itself; the block only says where.

Rules: numbers only (a bool, NaN or infinity is refused), every value inside its range (nothing is silently clamped, so a typo shows
up), regions inside 0..1, bounded counts, unknown keys dropped. An effect with a bad value is dropped whole and the others stay; a
block that ends up empty, is not an object or is too large answers None (the page then shows the scene as it always did). The checker
is pure: no file, no network, no art.
"""
import json
import math
import re

VERSION = 1
MAX_BYTES = 4800                   # the whole clean block as compact JSON: the private manifest is limited to 64 KiB for twelve scenes
MAX_REGIONS = 8
MAX_POINTS = 24
MAX_CRAFT = 4
KINDS = ('ship', 'drone', 'gull', 'swallow')
_SCENE = re.compile(r'[a-z0-9-]{1,40}')

# name: (low, high, default). The page uses the same numbers (stage-live.js, LIMITS).
SPECS = {
    'water': {'amount': (0, 2, 1), 'speed': (0.25, 3, 1), 'scale': (0.5, 3, 1), 'glints': (0, 2, 1), 'glint_size': (0.1, 2, 1), 'glint_density': (0, 1, 1), 'feather': (0.002, 0.08, 0.02),
              'horizon': (0, 1, None)},
    'clouds': {'amount': (0, 2, 1), 'speed': (0.25, 3, 1), 'direction': (-180, 180, 0), 'breath': (0, 2, 1), 'feather': (0.002, 0.1, 0.03)},
    'lights': {'amount': (0, 2, 1), 'speed': (0.25, 3, 1), 'out': (0, 0.5, 0.25), 'cell': (3, 60, 9)},
    'mist': {'amount': (0, 1, 0.5), 'speed': (0.25, 3, 1), 'scale': (0.5, 3, 1), 'feather': (0.002, 0.15, 0.04)},
    'rain': {'amount': (0, 1, 0.5), 'speed': (0.25, 3, 1), 'angle': (-45, 45, 10)},
}
TINTS = {'water': None, 'mist': (0.70, 0.76, 0.90), 'rain': (0.70, 0.80, 1.0)}      # [r, g, b] 0..1; None: only when given (water takes the picture's own light)
NEEDS_REGIONS = ('water', 'clouds', 'mist')           # lights: optional (the whole picture); rain: always the whole picture
CRAFT_SPECS = {'seconds': (8, 300, 60), 'size': (0.008, 0.12, None), 'bob': (0, 0.05, 0.006), 'flap': (0.3, 2.5, 1.1), 'delay': (0, 900, 0)}
CRAFT_SIZE = {'ship': 0.03, 'drone': 0.012, 'gull': 0.028, 'swallow': 0.013}
CRAFT_COUNT = {'ship': (1, 1), 'drone': (1, 1), 'gull': (1, 6), 'swallow': (1, 2)}
CRAFT_COLOUR = {'ship': (0.35, 0.80, 1.0), 'drone': (1.0, 0.30, 0.25), 'gull': (0.96, 0.97, 1.0), 'swallow': (0.25, 0.31, 0.34)}
MAX_LAMP_ROWS = 4
LAMP_PROVIDERS = ('codex', 'claude')
LAMP_COLOUR = {'codex': (1.0, 0.725, 0.27), 'claude': (0.318, 0.863, 1.0)}      # amber and cyan, as on the small board
LAMP_ANCHORS = ('start', 'end')                                                  # the end of the row where the lit run starts (its outer end)
LAMP_COUNT = (2, 64)
LAMP_HEIGHT = (0.004, 0.05, 0.0125)                                              # of the picture's height
LAMP_AMOUNT = (0, 2, 1)


class LiveError(ValueError):
    """One thing wrong with a block; `check_live` collects them, `live_info` swallows them."""


def _number(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise LiveError(f'{name} must be a number from {low} to {high}')
    return round(float(value), 4)


def _point(value, low, high, name):
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise LiveError(f'{name} must be [x, y]')
    return [_number(value[0], low, high, name + ' x'), _number(value[1], low, high, name + ' y')]


def _region(value):
    """A rectangle [x0, y0, x1, y1] or a polygon [[x, y], ...], all inside the picture."""
    if not isinstance(value, (list, tuple)) or not value:
        raise LiveError('a region is a rectangle [x0, y0, x1, y1] or a polygon [[x, y], ...]')
    if all(type(v) in (int, float) for v in value):
        if len(value) != 4:
            raise LiveError('a rectangle has four numbers')
        x0, y0, x1, y1 = (_number(v, 0, 1, 'region') for v in value)
        if not (x0 < x1 and y0 < y1):
            raise LiveError('a rectangle needs x0 < x1 and y0 < y1')
        return [x0, y0, x1, y1]
    if not 3 <= len(value) <= MAX_POINTS:
        raise LiveError(f'a polygon has 3 to {MAX_POINTS} points')
    points = [_point(p, 0, 1, 'polygon point') for p in value]
    area = sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points)))
    if abs(area) / 2 < 1e-5:
        raise LiveError('a polygon needs some area')
    return points


def _regions(value, required):
    if value is None:
        if required:
            raise LiveError('regions are needed')
        return None
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_REGIONS:
        raise LiveError(f'regions: one to {MAX_REGIONS}')
    return [_region(r) for r in value]


def _tint(value, default):
    if value is None:
        return list(default)
    if not (isinstance(value, (list, tuple)) and len(value) == 3):
        raise LiveError('tint is [r, g, b]')
    return [_number(v, 0, 1, 'tint') for v in value]


def _top(regions):
    return min((r[1] if isinstance(r[0], (int, float)) else min(p[1] for p in r)) for r in regions)


def _effect(name, raw):
    if not isinstance(raw, dict):
        raise LiveError('must be an object')
    out = {}
    regions = _regions(raw.get('regions'), name in NEEDS_REGIONS)
    if regions is not None:
        out['regions'] = regions
    for key, (low, high, default) in SPECS[name].items():
        value = raw.get(key)
        if value is None:
            if default is not None:
                out[key] = default
            continue
        out[key] = _number(value, low, high, key)
    if name == 'water' and 'horizon' not in out:
        out['horizon'] = round(_top(regions), 4)
    if name in TINTS and (raw.get('tint') is not None or TINTS[name] is not None):
        out['tint'] = _tint(raw.get('tint'), TINTS[name])
    return out


def _craft(raw):
    if not isinstance(raw, dict):
        raise LiveError('must be an object')
    kind = raw.get('kind')
    if kind not in KINDS:
        raise LiveError('kind is one of ' + ', '.join(KINDS))
    out = {'kind': kind}
    for key in ('from', 'to'):
        out[key] = _point(raw.get(key), -0.3, 1.3, key)
    if out['from'] == out['to']:
        raise LiveError('from and to must differ')
    for key, (low, high, default) in CRAFT_SPECS.items():
        value = raw.get(key)
        out[key] = _number(value, low, high, key) if value is not None else (CRAFT_SIZE[kind] if key == 'size' else default)
    seconds = out['seconds']
    every = raw.get('every')
    out['every'] = _number(every, seconds, 900, 'every') if every is not None else round(seconds * 1.7, 4)
    low, high = CRAFT_COUNT[kind]
    count = raw.get('count', min(3, high))
    if type(count) is not int or not low <= count <= high:
        raise LiveError(f'count must be a whole number from {low} to {high}')
    out['count'] = count
    out['colour'] = _tint(raw.get('colour'), CRAFT_COLOUR[kind])
    return out


def _lamp_row(raw):
    if not isinstance(raw, dict):
        raise LiveError('a row must be an object')
    provider = raw.get('provider')
    if provider not in LAMP_PROVIDERS:
        raise LiveError('provider is one of ' + ', '.join(LAMP_PROVIDERS))
    span = raw.get('x')
    if not (isinstance(span, (list, tuple)) and len(span) == 2):
        raise LiveError('x must be [left, right]')
    left, right = _number(span[0], 0, 1, 'x left'), _number(span[1], 0, 1, 'x right')
    if right - left < 0.02:
        raise LiveError('x needs left < right with some length')
    count = raw.get('count', 26)
    if type(count) is not int or not LAMP_COUNT[0] <= count <= LAMP_COUNT[1]:
        raise LiveError(f'count must be a whole number from {LAMP_COUNT[0]} to {LAMP_COUNT[1]}')
    height = raw.get('height')
    anchor = raw.get('anchor', 'start' if provider == 'codex' else 'end')
    if anchor not in LAMP_ANCHORS:
        raise LiveError('anchor is start or end')
    return {'provider': provider, 'x': [left, right], 'y': _number(raw.get('y'), 0, 1, 'y'), 'count': count,
            'height': _number(height, LAMP_HEIGHT[0], LAMP_HEIGHT[1], 'height') if height is not None else LAMP_HEIGHT[2],
            'anchor': anchor, 'colour': _tint(raw.get('colour'), LAMP_COLOUR[provider])}


def _lamps(raw):
    """Rows of lamp modules that follow the weekly quota; one bad row drops the whole effect (half a circuit would read as a half-empty quota)."""
    if not isinstance(raw, dict):
        raise LiveError('must be an object')
    rows = raw.get('rows')
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= MAX_LAMP_ROWS:
        raise LiveError(f'rows: one to {MAX_LAMP_ROWS}')
    amount = raw.get('amount')
    return {'amount': _number(amount, LAMP_AMOUNT[0], LAMP_AMOUNT[1], 'amount') if amount is not None else LAMP_AMOUNT[2], 'rows': [_lamp_row(r) for r in rows]}


def check_live(raw, scene='scene'):
    """(clean block or None, list of problems in plain words). The problems are for people (the offline tool); the page never sees them."""
    problems = []
    if not isinstance(scene, str) or not _SCENE.fullmatch(scene):
        return None, ['the scene name is not a valid name']
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ['live must be an object']
    clean = {}
    known = set(SPECS) | {'craft', 'lamps', 'version'}
    problems.extend(f'unknown key "{k}" dropped' for k in raw if k not in known)
    for name in SPECS:
        if raw.get(name) is None:
            continue
        try:
            clean[name] = _effect(name, raw[name])
        except LiveError as error:
            problems.append(f'{name}: {error}; the effect is dropped')
    craft = raw.get('craft')
    if craft is not None:
        if not isinstance(craft, (list, tuple)):
            problems.append('craft must be a list; dropped')
        else:
            if len(craft) > MAX_CRAFT:
                problems.append(f'craft: only the first {MAX_CRAFT} are kept')
            kept = []
            for index, item in enumerate(craft[:MAX_CRAFT]):
                try:
                    kept.append(_craft(item))
                except LiveError as error:
                    problems.append(f'craft {index + 1}: {error}; dropped')
            if kept:
                clean['craft'] = kept
    if raw.get('lamps') is not None:
        try:
            clean['lamps'] = _lamps(raw['lamps'])
        except LiveError as error:
            problems.append(f'lamps: {error}; the effect is dropped')
    if not clean:
        return None, problems
    clean = {'version': VERSION, **clean}
    if len(json.dumps(clean, separators=(',', ':'))) > MAX_BYTES:
        return None, problems + [f'the block is larger than {MAX_BYTES} bytes']
    return clean, problems


def live_info(raw, scene):
    """What the server puts under `live` for one scene: the clean block, or None."""
    return check_live(raw, scene)[0]
