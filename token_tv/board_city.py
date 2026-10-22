"""Page 8 of the touch board: the countdown as Manhattan seen from above at dusk (320x240).

the reference idea (2026-10-19, after finding the old four-ring page "super lioso"): a dense city seen a little from the sky,
toward the street, where only THREE buildings are data and the rest is just city. His reference photos were an aerial
view of Manhattan at blue hour and a sunset skyline; nothing is copied from them, the city is drawn from scratch. He
then asked for much more realism, isometric rooftop signs, a clearer small building and, last, "casi una foto": less
haze, many more details and data buildings that do not stand out so much.

- Two towers carry the WEEK: Codex's and Claude's, each a stepped tower of twenty floors. The floors lit from the
  ground up are the quota left (5 % a floor, at least one while any is left, none when unknown). Codex's windows are
  warm amber, Claude's stone-white, both about as bright as the city's own lights so they sit in the picture. Each has a
  rooftop sign on posts, drawn in the city's isometric projection, with its own mascot (Codex's blue cloud with `>_`,
  Claude Code's orange critter).
- One small building, beside Claude's tower, is Claude's five hours: five tall floors set apart by ledges and a ruler of
  five marks on its corner, eight windows across each face. The LEFT face is the quota left (20 % a floor) and the RIGHT
  face the time left (an hour a floor); both turn off floor by floor from the top and, inside the floor that is
  changing, window by window in quarter steps. It stays a dark building unless the reading is fresh, so an unknown
  session never reads as empty. It has a "5H" sign.
- All the other buildings are fixed scenery, a few hundred of them, in glass, stone, brick, concrete and Art Deco: window
  grids of several rhythms with warm, cool, television-blue and half-blinded windows, piers and spandrels, setbacks,
  ledges, lit shop fronts with blade signs, neon, roof gravel, machinery, solar panels, roof gardens, water tanks,
  helipads, aerials, rooftop advertising boards, parks, street trees, lamp posts with pools of light, traffic lights,
  cars, light streaks, shadows at the feet of the blocks, a clear air (no haze at all), a bloom around every light and a light
  vignette. Nothing there changes with a reading.
- Two translucent cards at the bottom hold, for each provider, its mascot, the quota number, the weekly reset and the
  saved resets as three hearts (no count; `?`, `+` and OLD behave as everywhere). Unknown is `--`, never zero.

No sky is left to twinkle, so this page carries no star trailer.
"""
import functools
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from token_tv import board_anim
from token_tv.board_art import CLAUDE, CODEX, RAMP, SS, H, W, Scene, _resets, _row
from token_tv.display import ASSETS
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

S = 4                                               # internal drawing scale: final pixels -> S pixels (reduced to SS)
HW, HH = 6, 3                                       # half width and half height of a ground cell on screen
OX, OY = 160, -22                                   # screen position of ground cell (0, 0)
FLOOR = 3.8                                         # height of a floor in pixels
SMALL_FLOOR = 6.4                                   # the five-hour building has taller floors so each one reads
LABEL = '#a9c5e1'
STONE_QUOTA, STONE_TIME = '#e2dccf', '#968e7e'
SKY = (('#0b2a52', 0), ('#1d4d7c', 18), ('#4f7fa0', 36), ('#e29a6a', 52), ('#f6c58a', 70))
FOG = (138, 150, 172)
HEROES = {'codex': (21, 32), 'claude': (32, 21)}    # south-west corner cell (x0, y0) of each tower's 3x3 footprint
SMALL = (36, 16)                                    # the five-hour building's 4x4 footprint corner
SMALL_SIZE = 4
TOWER_FLOORS = 10                                   # ten floors of 10 %: each can be part-lit, window by window
LOWER_FLOORS = 7                                    # the tower's wide part; the narrower top has the other three
HERO_FLOOR = 7.6                                    # a tower's floor is two city floors tall, with two rows of windows
SMALL_COLUMNS = 8                                   # windows across each face of the five-hour building
LIT = {'codex': (255, 220, 136), 'claude': (246, 240, 228)}       # the data towers' lit windows: clearly brighter than the city's
WARM = ((240, 204, 134), (242, 218, 168), (238, 180, 108), (242, 226, 192), (238, 194, 136), (230, 164, 100))
MATERIALS = {                                       # (bottom, top) colours of a facade under the dusk sky, and a weight
    'glass': ((20, 34, 58), (84, 118, 152), 34),
    'stone': ((84, 78, 74), (160, 148, 136), 22),
    'brick': ((92, 50, 42), (150, 92, 72), 14),
    'concrete': ((68, 72, 80), (138, 144, 152), 20),
    'deco': ((96, 84, 70), (176, 156, 130), 10),
}


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rgb(colour):
    if isinstance(colour, str):
        return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(colour[:3])


def proj(gx, gy, z=0.0):
    return OX + (gx - gy) * HW, OY + (gx + gy) * HH - z


def _q(points, k=S):
    return [(x * k, y * k) for x, y in points]


def _faces_base(x0, y0, x1, y1):
    """Ground endpoints (start, end) of the left face (towards +y) and of the right face (towards +x), left to right."""
    return (proj(x0, y1), proj(x1, y1)), (proj(x1, y1), proj(x1, y0))


def _box_faces(x0, y0, x1, y1, z0, z1):
    """The two visible side faces and the roof of a box: each a list of four corners."""
    (la, lb), (ra, rb) = _faces_base(x0, y0, x1, y1)
    left = [(la[0], la[1] - z0), (lb[0], lb[1] - z0), (lb[0], lb[1] - z1), (la[0], la[1] - z1)]
    right = [(ra[0], ra[1] - z0), (rb[0], rb[1] - z0), (rb[0], rb[1] - z1), (ra[0], ra[1] - z1)]
    roof = [proj(x0, y0, z1), proj(x1, y0, z1), proj(x1, y1, z1), proj(x0, y1, z1)]
    return left, right, roof


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _window_quads(face_points, columns, floor_from, floor_to, pitch_floor=FLOOR):
    """Window quads on a face: one per column and floor. `face_points` = bottom-start, bottom-end, top-end, top-start."""
    p0, p1 = face_points[0], face_points[1]
    out = []
    for f in range(floor_from, floor_to):
        for c in range(columns):
            u0, u1 = (c + .2) / columns, (c + .8) / columns
            v0, v1 = (f + .2) * pitch_floor, (f + .78) * pitch_floor
            a, b = _lerp(p0, p1, u0), _lerp(p0, p1, u1)
            out.append(((a[0], a[1] - v0), (b[0], b[1] - v0), (b[0], b[1] - v1), (a[0], a[1] - v1)))
    return out


def _fog(colour, t):
    """The air is clear (the user asked for no haze at all): a colour stays as it is. Kept so every call site reads the same."""
    return _rgb(colour)


def _depth(x, y):
    """0 for the farthest ground row of the picture, 1 for the nearest."""
    return max(0.0, min(1.0, ((x + y) - 14) / 70))


class Building:
    def __init__(self, x0, y0, x1, y1, height, lit, material='glass', kind='city'):
        self.x0, self.y0, self.x1, self.y1, self.h, self.lit = x0, y0, x1, y1, height, lit
        self.material, self.kind, self.tiers, self.style, self.podium = material, kind, 1, {}, None

    def depth(self):
        return _depth((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def bbox(self):
        pts = [proj(self.x0, self.y1), proj(self.x1, self.y1), proj(self.x1, self.y0), proj(self.x0, self.y0, self.h),
               proj(self.x1, self.y0, self.h), proj(self.x0, self.y1, self.h), proj(self.x1, self.y1, self.h)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def _hero_boxes(name):
    """The two stacked boxes of a tower: a wide base and a narrower top (cell coordinates and heights)."""
    x0, y0 = HEROES[name]
    low = LOWER_FLOORS * HERO_FLOOR
    top = TOWER_FLOORS * HERO_FLOOR
    return (x0, y0, x0 + 3, y0 + 3, 0, low), (x0 + .5, y0 + .5, x0 + 2.5, y0 + 2.5, low, top)


def _small_box():
    x0, y0 = SMALL
    return (x0, y0, x0 + SMALL_SIZE, y0 + SMALL_SIZE, 0, 5 * SMALL_FLOOR)


def tower_columns(name):
    """The windows of a tower floor by floor from the ground up. Each floor is a list of COLUMNS, ordered round the
    building as the eye reads it (the left face from its left end to the corner, then the right face from the corner
    to its end), and each column is two window quads (two rows). A floor that is part-lit lights its first columns."""
    plan = []
    for f in range(TOWER_FLOORS):
        x0, y0, x1, y1, z0, z1 = _hero_boxes(name)[0 if f < LOWER_FLOORS else 1]
        left, right, _ = _box_faces(x0, y0, x1, y1, z0, z1)
        columns = int((x1 - x0) * 2)
        local = f - (0 if f < LOWER_FLOORS else LOWER_FLOORS)
        ordered = []
        for face_points in (left, right):
            p0, p1 = face_points[0], face_points[1]
            for c in range(columns):
                a, b = _lerp(p0, p1, (c + .22) / columns), _lerp(p0, p1, (c + .78) / columns)
                column = []
                for lo, hi in ((.10, .46), (.54, .90)):
                    v0, v1 = (local + lo) * HERO_FLOOR, (local + hi) * HERO_FLOOR
                    column.append(((a[0], a[1] - v0), (b[0], b[1] - v0), (b[0], b[1] - v1), (a[0], a[1] - v1)))
                ordered.append(tuple(column))
        plan.append(ordered)
    return plan


def tower_windows(name):
    """Every window quad of a tower by floor, as (left face quads, right face quads): the columns of `tower_columns`."""
    plan = []
    for columns in tower_columns(name):
        half = len(columns) // 2
        plan.append(([q for column in columns[:half] for q in column], [q for column in columns[half:] for q in column]))
    return plan


def lit_columns(floor, floors_lit, columns):
    """How many columns of floor `floor` (from the ground, 0-based) are lit when `floors_lit` floors are lit (a float): a
    floor below is fully lit, the one being reached lights its first columns in proportion (at least one), the rest none."""
    if floors_lit >= floor + 1:
        return columns
    if floors_lit <= floor:
        return 0
    return max(1, round((floors_lit - floor) * columns))


def small_windows():
    """The five-hour building: five floors of (left face quads = quota, right face quads = time), eight across."""
    x0, y0, x1, y1, z0, z1 = _small_box()
    left, right, _ = _box_faces(x0, y0, x1, y1, z0, z1)
    return [(_window_quads(left, SMALL_COLUMNS, f, f + 1, SMALL_FLOOR), _window_quads(right, SMALL_COLUMNS, f, f + 1, SMALL_FLOOR))
            for f in range(5)]


def _special_footprints():
    boxes = [(HEROES[n][0], HEROES[n][1], HEROES[n][0] + 3, HEROES[n][1] + 3) for n in HEROES]
    boxes.append((SMALL[0], SMALL[1], SMALL[0] + SMALL_SIZE, SMALL[1] + SMALL_SIZE))
    return boxes


def _pick_material(rnd):
    names = list(MATERIALS)
    return rnd.choices(names, [MATERIALS[n][2] for n in names])[0]


def _crown(rnd, material, height):
    """The top of a building: a spire, a mast, a pyramid, a dome, twin turrets, a glass lantern, a sloped roof, a mansard, a
    roof terrace with a pool, or a plain flat roof with machinery. Tall buildings get the grander ones."""
    if material == 'deco' and height > 60:
        return 'spire'
    if height > 70:
        return rnd.choice(('spire', 'spire', 'mast', 'mast', 'pyramid', 'dome', 'twin', 'lantern', 'slant'))
    if height > 40:
        return rnd.choice(('flat', 'slant', 'mansard', 'dome', 'lantern', 'pyramid', 'twin', 'terrace', 'terrace'))
    return rnd.choice(('flat', 'mansard', 'slant', 'terrace', 'terrace', 'slant'))


def _style(rnd, material, height):
    """How one building's facade looks: window rhythm and size, which kinds of light, piers, spandrels, blade signs."""
    return {
        'pitch': rnd.choice((2.4, 2.8, 3.2, 3.8)),
        'win_w': rnd.uniform(.5, .72), 'win_h': rnd.uniform(.42, .62),
        'piers': material in ('stone', 'deco', 'brick') or rnd.random() < .35,
        'bands': rnd.random() < .6,
        'office': rnd.random() < .5 and material in ('glass', 'concrete'),
        'neon': height < 46 and rnd.random() < .28,
        'tone': rnd.uniform(-.14, .16),
        'escape': material == 'brick' and rnd.random() < .7,
        'crown': _crown(rnd, material, height),
        'board': 26 < height < 72 and rnd.random() < .14,
    }


def _zone_height(bx, by):
    """A smooth height for the whole block, so neighbours are related like the districts of a real city: a tall middle
    band, lower ground towards the front and the sides."""
    wave = math.sin(bx * .55 + 1.3) + math.sin(by * .5 - .4) + .6 * math.sin((bx + by) * .35)
    return 30 + 30 * (wave + 2.2) / 4.4


@functools.lru_cache(maxsize=1)
def _city():
    """The fixed scenery: a list of Buildings, from a seeded generator, with room kept clear in front of the three
    that carry data (anything in front of them that would hide their faces becomes a car park). The grid reaches beyond the
    picture on every side, so no sky shows at the top corners."""
    rnd = random.Random(2026)
    special = _special_footprints()
    buildings = []
    for bx in range(-12, 16):
        for by in range(-12, 16):
            gx0, gy0 = bx * 5 + 1, by * 5 + 1                                      # a 4x4 block between streets
            touches = any(not (gx0 + 4 <= s[0] or gx0 >= s[2] or gy0 + 4 <= s[1] or gy0 >= s[3]) for s in special)
            if rnd.random() < .06 and not touches:
                buildings.append(Building(gx0, gy0, gx0 + 4, gy0 + 4, 0, 0, kind='park'))
                continue
            cells = [(gx0, gy0, gx0 + 4, gy0 + 4)]
            while len(cells) < 3 and rnd.random() < .5:                            # most blocks are one or two big buildings
                c = rnd.choice([c for c in cells if (c[2] - c[0]) >= 2 and (c[3] - c[1]) >= 2] or cells)
                if (c[2] - c[0]) < 3 and (c[3] - c[1]) < 3:
                    break
                cells.remove(c)
                if (c[2] - c[0]) >= (c[3] - c[1]):
                    cut = c[0] + rnd.randint(1, (c[2] - c[0]) - 1)
                    cells += [(c[0], c[1], cut, c[3]), (cut, c[1], c[2], c[3])]
                else:
                    cut = c[1] + rnd.randint(1, (c[3] - c[1]) - 1)
                    cells += [(c[0], c[1], c[2], cut), (c[0], cut, c[2], c[3])]
            zone = _zone_height(bx, by)
            for (x0, y0, x1, y1) in cells:
                material = _pick_material(rnd)
                height = zone * rnd.choice((.55, .75, .9, 1.0, 1.15, 1.4)) * (2.3 if rnd.random() < .3 else 1) + rnd.uniform(-3, 5)
                height = max(10.0, min(150.0, height))
                lit = rnd.choice((.08, .14, .22, .32, .42))
                tiers = rnd.choice((1, 1, 2, 2, 3)) if height > 46 else 1
                if any(not (x1 <= s[0] or x0 >= s[2] or y1 <= s[1] or y0 >= s[3]) for s in special):
                    continue
                if ((x0 + x1 + y0 + y1) / 2) > 74:
                    height = min(height, rnd.choice((10, 14, 20, 26)))             # lower buildings in front
                podium = None
                if height > 78 and ((x1 - x0) >= 3 or (y1 - y0) >= 3):             # a skyscraper is slender: it stands on a podium
                    podium = (x0, y0, x1, y1, rnd.choice((7.0, 10.0, 13.0)))
                    sw, sd = min(x1 - x0, rnd.choice((2, 2, 3))), min(y1 - y0, rnd.choice((2, 2, 3)))
                    x0 += rnd.randint(0, (x1 - x0) - sw)
                    y0 += rnd.randint(0, (y1 - y0) - sd)
                    x1, y1 = x0 + sw, y0 + sd
                b = Building(x0, y0, x1, y1, height, lit, material)
                b.podium = podium
                b.tiers, b.style = tiers, _style(rnd, material, height)
                bb = b.bbox()
                if bb[2] < -10 or bb[0] > W + 10 or bb[3] < -4 or bb[1] > H + 4:
                    continue                                                      # entirely off the picture
                buildings.append(b)
    # Two avenues kept open so traffic can be seen driving along them. Seen from this height a building k cells in front of
    # an avenue hides it unless it is lower than 6 pixels per cell, so the ground beside each avenue climbs like a ramp.
    for b in buildings:
        if b.kind == 'city':
            cap = min(6.0 * (b.x0 - AVENUES[0]) - 2 if b.x0 > AVENUES[0] else 999.0,
                      6.0 * (b.y0 - AVENUES[1]) - 2 if b.y0 > AVENUES[1] else 999.0)
            if cap < b.h:
                b.h, b.tiers, b.podium = max(6.0, cap), 1, None
                b.style = dict(b.style, crown=random.Random(b.x0 * 131 + b.y0).choice(('flat', 'mansard', 'slant', 'terrace', 'terrace')),
                               neon=False, board=False)
    # clear room in front of the three data buildings: nothing may hide their faces
    keep = []
    for name, (x0, y0) in list(HEROES.items()) + [('small', SMALL)]:
        size = 3 if name != 'small' else SMALL_SIZE
        top = (TOWER_FLOORS * HERO_FLOOR if name != 'small' else 5 * SMALL_FLOOR) + 6
        pts = [proj(x0, y0 + size), proj(x0 + size, y0 + size), proj(x0 + size, y0), proj(x0, y0 + size, top),
               proj(x0 + size, y0 + size, top), proj(x0 + size, y0, top)]
        keep.append((min(p[0] for p in pts) - 2, min(p[1] for p in pts) - 2, max(p[0] for p in pts) + 2, max(p[1] for p in pts) + 2,
                     x0 + y0))
    _KEEP[:] = [k[:4] for k in keep]
    for b in buildings:
        if b.kind not in ('city', 'park'):
            continue
        for kx0, ky0, kx1, ky1, order in keep:
            if b.x0 + b.y0 > order:                                                # drawn after (in front of) the tower
                bx0, by0, bx1, by1 = b.bbox()
                if b.kind == 'park':
                    bx0, by0, bx1, by1 = min(proj(b.x0, b.y1)[0], proj(b.x0, b.y0)[0]), proj(b.x0, b.y0)[1], max(proj(b.x1, b.y0)[0], proj(b.x1, b.y1)[0]), proj(b.x1, b.y1)[1]
                if not (bx1 < kx0 or bx0 > kx1 or by1 < ky0 or by0 > ky1):
                    b.kind, b.h, b.tiers = 'lot', .6, 1                               # a garden instead: it hides nothing
    return tuple(buildings)


# --------------------------------------------------------------------------------------------------- painting
AVENUES = (40, 35)                                   # (gx of an avenue running along y, gy of one running along x): kept open to view
_KEEP = []                                           # screen boxes of the data buildings: nothing tall may stand in front of them
_REC = None                                          # while a city building is painted: a list that gets each of its windows


def _lit_window(rnd, colour):
    """A lit window's colour: mostly warm tungsten, some cool LED, a few television blues and fluorescent greens."""
    r = rnd.random()
    if r < .84:
        base = rnd.choice(WARM)
    elif r < .94:
        base = (206, 224, 250)
    elif r < .98:
        base = (122, 156, 226)
    else:
        base = (196, 232, 206)
    return mix(base, colour, rnd.uniform(0, .36))


def _paint_face(d, base, z0, z1, floor_h, mat, t, side, style, rnd, lit, windows, shop):
    """One face of a box, floor by floor: a facade colour that brightens with height (sky reflected in the upper
    floors, street darkness below), uneven grime in three strips, spandrel bands and ledges, piers, sills, dark or lit
    windows (some half-blinded), a fire escape on some brick, and on the ground floor a lit shop front with a sign."""
    a, b = base
    bottom, top = MATERIALS[mat][0], MATERIALS[mat][1]
    floors = max(1, round((z1 - z0) / floor_h))
    fh = (z1 - z0) / floors
    width = abs(b[0] - a[0])
    columns = max(1, round(width / style.get('pitch', 3.0)))
    office = {f for f in range(floors) if style.get('office') and rnd.random() < .12}
    tint = (255, 150, 110) if side == 1 else None
    for f in range(floors):
        za, zb = z0 + f * fh, z0 + (f + 1) * fh
        u = (f + .5) / floors
        colour = mix(bottom, top, u ** .8)
        tone = style.get('tone', 0.0)                                                      # each building a little lighter or darker
        colour = mix(colour, (255, 255, 255) if tone > 0 else (0, 0, 0), abs(tone))
        colour = mix(colour, (0, 0, 6), .30 + (.30 if side == 0 else 0))                  # dusk: the light has gone from the walls
        colour = mix(colour, tint, .12) if tint else colour
        colour = mix(colour, (rnd.randint(0, 40), rnd.randint(0, 40), rnd.randint(0, 40)), .05)           # no two floors alike
        if z0 == 0 and f == 0:
            colour = mix(colour, (0, 0, 8), .28)                                          # darker where the street is
        for k in range(3):                                                                # uneven grime across the floor
            p0, p1 = _lerp(a, b, k / 3), _lerp(a, b, (k + 1) / 3 + .002)
            grime = rnd.uniform(-.07, .07)
            strip = mix(colour, (255, 255, 255) if grime > 0 else (0, 0, 0), abs(grime))
            d.polygon(_q([(p0[0], p0[1] - za), (p1[0], p1[1] - za), (p1[0], p1[1] - zb), (p0[0], p0[1] - zb)]), fill=strip)
        if style.get('bands'):                                                            # a spandrel band under the windows
            d.polygon(_q([(a[0], a[1] - za), (b[0], b[1] - za), (b[0], b[1] - za - fh * .2), (a[0], a[1] - za - fh * .2)]),
                      fill=mix(colour, (0, 0, 10), .22))
        d.line(_q([(a[0], a[1] - zb), (b[0], b[1] - zb)]), fill=mix(colour, (255, 255, 255), .15), width=max(1, S // 2))
        if not windows or width < 3:
            continue
        for c in range(columns):
            u0, u1 = (c + .5 - style.get('win_w', .6) / 2) / columns, (c + .5 + style.get('win_w', .6) / 2) / columns
            v0, v1 = za + fh * (.5 - style.get('win_h', .5) / 2 + .06), za + fh * (.5 + style.get('win_h', .5) / 2 + .06)
            pa, pb = _lerp(a, b, u0), _lerp(a, b, u1)
            quad = [(pa[0], pa[1] - v0), (pb[0], pb[1] - v0), (pb[0], pb[1] - v1), (pa[0], pa[1] - v1)]
            if z0 == 0 and f == 0 and shop:
                if rnd.random() < .72:
                    d.polygon(_q(quad), fill=mix((255, 188, 108), colour, rnd.uniform(0, .35)))
                continue
            sky = mix((8, 14, 28), (96, 126, 160), .30 * u) if mat == 'glass' else (8, 14, 28)
            dark = mix(colour, sky, .36)
            if f in office or rnd.random() < lit:
                glow = mix((205, 226, 255), colour, rnd.uniform(0, .22)) if f in office else _lit_window(rnd, colour)
                drawn = glow
                if rnd.random() < .12 and f not in office:                                # half-lowered blinds
                    drawn = None
                    mid = [(pa[0], pa[1] - (v0 + v1) / 2), (pb[0], pb[1] - (v0 + v1) / 2)]
                    d.polygon(_q(quad), fill=mix(colour, (8, 14, 28), .5))
                    d.polygon(_q([(pa[0], pa[1] - v0), (pb[0], pb[1] - v0), mid[1], mid[0]]), fill=glow)
                else:
                    d.polygon(_q(quad), fill=glow)
            else:
                d.polygon(_q(quad), fill=dark)
                drawn = dark
            if _REC is not None:
                _REC.append((quad, drawn, dark))
            if mat != 'glass' and width > 5:                                              # a sill under each window
                d.line(_q([(pa[0], pa[1] - v0 + .2), (pb[0], pb[1] - v0 + .2)]), fill=mix(colour, (255, 255, 255), .22), width=max(1, S // 3))
        if style.get('piers') and width > 5:                                              # vertical piers between the columns
            for c in range(1, columns):
                p = _lerp(a, b, c / columns)
                d.line(_q([(p[0], p[1] - za), (p[0], p[1] - zb)]), fill=mix(colour, (255, 255, 255), .10), width=max(1, S // 3))
        if z0 == 0 and f == 0 and shop and width > 5 and rnd.random() < .65:              # a sign over the shop front
            pa = _lerp(a, b, rnd.uniform(.12, .55))
            pb = _lerp(pa, b, rnd.uniform(.18, .3))
            sign = rnd.choice(((220, 70, 60), (70, 140, 230), (80, 200, 120), (240, 240, 250), (240, 170, 60), (200, 80, 200)))
            d.polygon(_q([(pa[0], pa[1] - fh * .84), (pb[0], pb[1] - fh * .84), (pb[0], pb[1] - fh * .97), (pa[0], pa[1] - fh * .97)]),
                      fill=sign)
    if style.get('escape') and mat == 'brick' and floors >= 3 and width > 5:             # a fire escape zig-zags up the face
        dark = (24, 26, 32)
        x_a, x_b = rnd.uniform(.15, .35), rnd.uniform(.55, .8)
        for f in range(1, floors):
            za, zb = z0 + (f - 0.1) * fh, z0 + (f + 0.9) * fh
            p0, p1 = _lerp(a, b, x_a), _lerp(a, b, x_b)
            d.line(_q([(p0[0], p0[1] - za), (p1[0], p1[1] - za)]), fill=dark, width=max(1, S // 2))
            d.line(_q([(p1[0], p1[1] - za), (p0[0], p0[1] - zb)] if f % 2 else [(p0[0], p0[1] - za), (p1[0], p1[1] - zb)]),
                   fill=dark, width=max(1, S // 3))


def _paint_roof(d, roof_pts, mat, t, rnd, tone=0.0):
    """A roof catches the last of the sky, so it is lighter than the walls under it: that is what tells one building from
    the next. A bright rim along the two front edges, a dark one along the back, gravel speckle."""
    top = MATERIALS[mat][1]
    base = mix(mix(top, (136, 152, 178), .36), (255, 255, 255) if tone > 0 else (0, 0, 0), abs(tone) * .6)
    base = mix(base, (0, 0, 0), .16)
    d.polygon(_q(roof_pts), fill=base)
    d.line(_q([roof_pts[3], roof_pts[2], roof_pts[1]]), fill=mix(base, (255, 232, 206), .55), width=max(1, S // 2))
    d.line(_q([roof_pts[3], roof_pts[0], roof_pts[1]]), fill=mix(base, (10, 14, 24), .45), width=max(1, S // 2))
    xs, ys = [p[0] for p in roof_pts], [p[1] for p in roof_pts]
    for _ in range(max(2, int((max(xs) - min(xs)) * (max(ys) - min(ys)) / 9))):          # gravel and tar: a speckle on the roof
        u, v = rnd.random(), rnd.random()
        p = _lerp(_lerp(roof_pts[3], roof_pts[2], u), _lerp(roof_pts[0], roof_pts[1], u), v)
        d.point(_q([p])[0], fill=mix(base, (28, 30, 40) if rnd.random() < .5 else (220, 220, 226), .2))


def _paint_box(d, x0, y0, x1, y1, z0, z1, material, t, rnd, lit, windows=True, shop=False, floor_h=FLOOR, style=None):
    _, _, roof_pts = _box_faces(x0, y0, x1, y1, z0, z1)
    (la, lb), (ra, rb) = _faces_base(x0, y0, x1, y1)
    style = style or {}
    _paint_face(d, (la, lb), z0, z1, floor_h, material, t, 0, style, rnd, lit, windows, shop)
    _paint_face(d, (ra, rb), z0, z1, floor_h, material, t, 1, style, rnd, lit, windows, shop)
    d.line(_q([(ra[0], ra[1] - z0), (ra[0], ra[1] - z1)]), fill=mix(MATERIALS[material][1], (255, 190, 140), .45), width=max(1, S // 2))
    if windows and z1 - z0 > 12:                                                          # a cornice at the top of the wall
        for (a, b), shade in (((la, lb), .0), ((ra, rb), .12)):
            band = mix(MATERIALS[material][1], (255, 226, 196), .22 - shade)
            d.polygon(_q([(a[0], a[1] - z1 + .8), (b[0], b[1] - z1 + .8), (b[0], b[1] - z1), (a[0], a[1] - z1)]), fill=band)
            d.polygon(_q([(a[0], a[1] - z1 + 1.8), (b[0], b[1] - z1 + 1.8), (b[0], b[1] - z1 + .8), (a[0], a[1] - z1 + .8)]),
                      fill=mix(MATERIALS[material][0], (0, 0, 8), .45))
    _paint_roof(d, roof_pts, material, t, rnd, style.get('tone', 0.0))
    edge = mix(MATERIALS[material][0], (0, 0, 0), .55)                                   # the dark outline that parts it from its neighbours
    for (a, b) in ((la, lb), (ra, rb)):
        d.line(_q([(a[0], a[1] - z0), (a[0], a[1] - z1)]), fill=edge, width=max(1, S // 2))
        d.line(_q([(b[0], b[1] - z0), (b[0], b[1] - z1)]), fill=edge, width=max(1, S // 2))
        d.line(_q([(a[0], a[1] - z0), (b[0], b[1] - z0)]), fill=edge, width=S)


def _red_light(d, px, py):
    d.ellipse(_q([(px - .8, py - .8), (px + .8, py + .8)]), fill=(255, 74, 74))


def _static_board(d, cx, cy, z, plane, t, rnd, width=1.6, height=6):
    """A generic advertising board on a roof, in the city's projection: a bright frame and three bands of colour."""
    half = width / 2
    if plane == 'right':
        (lx, ly), (rx, ry) = proj(cx, cy + half, z), proj(cx, cy - half, z)
    else:
        (lx, ly), (rx, ry) = proj(cx - half, cy, z), proj(cx + half, cy, z)
    lift = 3
    d.polygon(_q([(lx, ly - lift), (rx, ry - lift), (rx, ry - lift - height), (lx, ly - lift - height)]), fill=_fog((22, 24, 30), t))
    colours = rnd.choice(((240, 90, 70), (80, 160, 255), (250, 200, 70), (120, 220, 150), (240, 240, 250)))
    for k in range(3):
        u0, u1 = .1 + k * .27, .1 + k * .27 + .22
        a, b = _lerp((lx, ly), (rx, ry), u0), _lerp((lx, ly), (rx, ry), u1)
        d.polygon(_q([(a[0], a[1] - lift - height * .15), (b[0], b[1] - lift - height * .15), (b[0], b[1] - lift - height * .85),
                      (a[0], a[1] - lift - height * .85)]), fill=_fog(mix(colours, (30, 30, 60), .15 * k), max(t, .5)))
    for k in (.2, .8):
        p = _lerp((lx, ly), (rx, ry), k)
        d.line(_q([(p[0], p[1]), (p[0], p[1] - lift)]), fill=_fog((90, 92, 100), t), width=max(1, S // 2))


def _roof_details(d, cell, z, t, rnd, tall, style):
    x0, y0, x1, y1 = cell
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, depth = x1 - x0, y1 - y0
    for _ in range(rnd.choice((0, 0, 1, 1, 2))):                                      # machinery boxes
        ox, oy = rnd.uniform(-.35, .35) * w, rnd.uniform(-.35, .35) * depth
        s = rnd.uniform(.2, .4)
        _paint_box(d, cx + ox - s, cy + oy - s, cx + ox + s, cy + oy + s, z, z + rnd.uniform(1.4, 3.0), 'concrete', t, rnd, 0,
                   windows=False)
    kind = rnd.random()
    px, py = proj(cx + rnd.uniform(-.3, .3) * w, cy + rnd.uniform(-.3, .3) * depth, z)
    if kind < .18:                                                                    # a water tower on legs
        for dx in (-2.0, 2.0):
            d.line(_q([(px + dx, py), (px + dx * .8, py - 4.5)]), fill=_fog((70, 50, 60), t), width=S // 2 + 1)
        d.rectangle(_q([(px - 2.8, py - 10), (px + 2.8, py - 4.5)]), fill=_fog((120, 82, 70), t))
        d.polygon(_q([(px - 3.2, py - 10), (px + 3.2, py - 10), (px, py - 13)]), fill=_fog((92, 62, 60), t))
    elif kind < .30 and tall > 60:                                                    # a helipad
        d.ellipse(_q([(px - 4.6, py - 2.4), (px + 4.6, py + 2.4)]), outline=_fog((240, 240, 250), t), width=S // 2 + 1)
    elif kind < .42 and w >= 2:                                                       # solar panels
        for k in range(3):
            qx, qy = px - 3 + k * 2.4, py
            d.polygon(_q([(qx, qy), (qx + 2, qy - .9), (qx + 2, qy - 2.4), (qx, qy - 1.5)]), fill=_fog((40, 70, 140), t))
    elif kind < .52:                                                                  # a roof garden
        d.polygon(_q([(px - 4, py), (px, py - 2), (px + 4, py), (px, py + 2)]), fill=_fog((52, 100, 74), t))
    elif kind < .78 and tall > 34:                                                    # an aerial with its red light
        d.line(_q([(px, py), (px, py - 8)]), fill=_fog((200, 200, 226), t), width=max(1, S // 2))
        _red_light(d, px, py - 8)
    if style.get('board') and w >= 2:                                                 # an advertising board on the roof
        _static_board(d, cx, cy, z, rnd.choice(('left', 'right')), t, rnd)


def _paint_crown(d, cell, z, mat, t, rnd, tall, crown):
    """The top of a building (see `_crown`), standing on the roof at height `z` over `cell` (cell coordinates)."""
    x0, y0, x1, y1 = cell
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    size = min(x1 - x0, y1 - y0)
    top = MATERIALS[mat][1]
    if crown == 'spire':
        base = min(.4 * size, .55)
        _paint_box(d, cx - base, cy - base, cx + base, cy + base, z, z + 4, mat, t, rnd, 0, windows=False)
        px, py = proj(cx, cy, z + 4)
        height = 20 if tall > 70 else 12
        d.polygon(_q([(px - 1.6, py), (px + 1.6, py), (px, py - height)]), fill=mix(top, (226, 224, 214), .5))
        _red_light(d, px, py - height)
    elif crown == 'mast':
        px, py = proj(cx, cy, z)
        for k in range(4):                                                            # a lattice mast: two legs and cross bars
            y = py - k * 4.5
            d.line(_q([(px - 1.2, y), (px + 1.2, y - 4.5)]), fill=(196, 198, 206), width=max(1, S // 3))
            d.line(_q([(px + 1.2, y), (px - 1.2, y - 4.5)]), fill=(196, 198, 206), width=max(1, S // 3))
        d.line(_q([(px - 1.2, py), (px - 1.2, py - 18)]), fill=(210, 212, 220), width=max(1, S // 2))
        d.line(_q([(px + 1.2, py), (px + 1.2, py - 18)]), fill=(210, 212, 220), width=max(1, S // 2))
        _red_light(d, px, py - 19)
    elif crown == 'pyramid':
        apex = proj(cx, cy, z + (11 if tall > 60 else 8))
        d.polygon(_q([proj(x0, y1, z), proj(x1, y1, z), apex]), fill=mix(top, (0, 0, 20), .45))
        d.polygon(_q([proj(x1, y1, z), proj(x1, y0, z), apex]), fill=mix(top, (255, 190, 140), .22))
        d.line(_q([apex, (apex[0], apex[1] - 3.5)]), fill=(236, 206, 150), width=max(1, S // 2))
    elif crown == 'dome':
        px, py = proj(cx, cy, z)
        r = min(7.0, max(3.4, size * HW * .5))
        d.ellipse(_q([(px - r, py - r * .95), (px + r, py + r * .35)]), fill=(70, 122, 108))
        d.ellipse(_q([(px - r * .7, py - r * .9), (px + r * .1, py - r * .35)]), fill=(122, 176, 150))
        d.line(_q([(px, py - r * .95), (px, py - r * .95 - 5)]), fill=(226, 206, 150), width=max(1, S // 2))
    elif crown == 'twin':
        for fx, h in ((.28, 9), (.72, 13)):                                           # two turrets of different height
            sx, sy = x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fx
            q = min(.38, size * .22)
            _paint_box(d, sx - q, sy - q, sx + q, sy + q, z, z + h, mat, t, rnd, .6, windows=True, floor_h=3.0)
            px, py = proj(sx, sy, z + h)
            d.polygon(_q([(px - 1.4, py), (px + 1.4, py), (px, py - 4)]), fill=mix(top, (200, 200, 210), .4))
    elif crown == 'lantern':
        q = max(.5, size * .3)
        _paint_box(d, cx - q, cy - q, cx + q, cy + q, z, z + 7, 'glass', t, rnd, .9, windows=True, floor_h=3.0)
        px, py = proj(cx, cy, z + 7)
        _red_light(d, px, py - 3)
        d.line(_q([(px, py), (px, py - 3)]), fill=(200, 200, 210), width=max(1, S // 2))
    elif crown == 'slant':
        h = 9 if tall > 60 else 6
        a, b, c, dd = proj(x0, y0, z), proj(x1, y0, z), proj(x1, y1, z), proj(x0, y1, z)
        a2, b2 = (a[0], a[1] - h), (b[0], b[1] - h)
        d.polygon(_q([b, b2, c]), fill=mix(MATERIALS[mat][0], (0, 0, 8), .15))              # the end wall of the wedge
        d.polygon(_q([a2, b2, c, dd]), fill=mix(top, (170, 186, 210), .45))
        d.line(_q([a2, b2]), fill=mix(top, (255, 236, 214), .6), width=max(1, S // 2))
    elif crown == 'mansard':
        inner = .3
        lo = [proj(x0, y1, z), proj(x1, y1, z), proj(x1 - inner, y1 - inner, z + 4), proj(x0 + inner, y1 - inner, z + 4)]
        hi = [proj(x1, y1, z), proj(x1, y0, z), proj(x1 - inner, y0 + inner, z + 4), proj(x1 - inner, y1 - inner, z + 4)]
        d.polygon(_q(lo), fill=(46, 52, 64))
        d.polygon(_q(hi), fill=(78, 86, 100))
        d.polygon(_q([proj(x0 + inner, y0 + inner, z + 4), proj(x1 - inner, y0 + inner, z + 4), proj(x1 - inner, y1 - inner, z + 4),
                      proj(x0 + inner, y1 - inner, z + 4)]), fill=mix((90, 100, 116), (0, 0, 0), .1))
        for k in range(1, 4):                                                          # dormers lit on the near slope
            p = _lerp(lo[0], lo[1], k / 4)
            d.rectangle(_q([(p[0] - .8, p[1] - 3.2), (p[0] + .8, p[1] - 1.6)]), fill=(236, 200, 140) if rnd.random() < .7 else (30, 36, 52))
    elif crown == 'terrace':
        side = min(1.5, size - .5)                                                    # a pool no bigger than a cell and a half
        px0, py0 = cx - side / 2, cy - side / 2
        pts = [proj(px0, py0, z), proj(px0 + side, py0, z), proj(px0 + side, py0 + side, z), proj(px0, py0 + side, z)]
        d.polygon(_q(pts), fill=(56, 150, 178))
        d.line(_q(pts + [pts[0]]), fill=(214, 226, 232), width=max(1, S // 2))
        d.line(_q([pts[3], pts[2], pts[1]]), fill=(255, 226, 170), width=max(1, S // 2))   # a warm rail along the front edges


def _paint_building(d, b, rnd):
    t = b.depth()
    x0, y0, x1, y1 = b.x0, b.y0, b.x1, b.y1
    z0 = 0.0
    if b.podium:                                                                       # a low base fills the whole plot
        px0, py0, px1, py1, ph = b.podium
        base = 'concrete' if b.material in ('glass', 'concrete') else b.material
        _paint_box(d, px0, py0, px1, py1, 0, ph, base, t, rnd, b.lit, shop=True, style=dict(b.style, crown='flat'))
        z0 = ph
        b_height = b.h - ph
    else:
        b_height = b.h
    for tier in range(b.tiers):
        share = b_height if b.tiers == 1 else b_height * (.62, .26, .12)[tier]
        _paint_box(d, x0, y0, x1, y1, z0, z0 + share, b.material, t, rnd, b.lit, shop=(tier == 0 and not b.podium), style=b.style)
        z0 += share
        if tier + 1 < b.tiers:
            inset = rnd.choice((.3, .5, .5)) if min(x1 - x0, y1 - y0) >= 3 else .3
            x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
            if x1 - x0 < .8 or y1 - y0 < .8:
                break
    if b.style.get('neon'):                                                           # a vertical neon sign at the corner
        corner = proj(b.x1, b.y1)
        colour = rnd.choice(((255, 80, 120), (90, 200, 255), (130, 255, 160), (255, 190, 70)))
        top = min(b.h * .8, 11)
        d.rectangle(_q([(corner[0] - 1.6, corner[1] - top), (corner[0] - .6, corner[1] - 3)]), fill=colour)
    crown = b.style.get('crown', 'flat')
    if crown == 'flat' or x1 - x0 < 1.0:
        _roof_details(d, (x0, y0, x1, y1), z0, t, rnd, b.h, b.style)
    else:
        _paint_crown(d, (x0, y0, x1, y1), z0, b.material, t, rnd, b.h, crown)


def _paint_tower(d, name):
    """A data building as a dark body with its dark windows: lit floors are drawn per reading on top."""
    size = 3 if name in HEROES else SMALL_SIZE
    t = _depth(*[a + size / 2 for a in (HEROES[name] if name in HEROES else SMALL)])
    if name in HEROES:
        material = 'glass' if name == 'codex' else 'stone'
        rnd = random.Random(name)
        style = {'piers': True, 'bands': True}
        for box in _hero_boxes(name):
            _paint_box(d, *box, material, t, rnd, 0, windows=False, style=style, floor_h=HERO_FLOOR)
        for left_quads, right_quads in tower_windows(name):
            for quad in left_quads + right_quads:
                d.polygon(_q(quad), fill=_fog((16, 30, 52) if name == 'codex' else (44, 46, 54), t))
        x0, y0 = HEROES[name]
        top = TOWER_FLOORS * HERO_FLOOR
        for f in range(1, TOWER_FLOORS):                                                   # a ledge between the ten floors
            x0f, y0f, x1f, y1f = _hero_boxes(name)[0 if f < LOWER_FLOORS else 1][:4]
            for a, b in _faces_base(x0f, y0f, x1f, y1f):
                d.line(_q([(a[0], a[1] - f * HERO_FLOOR), (b[0], b[1] - f * HERO_FLOOR)]), fill=(150, 152, 158), width=S)
        _paint_box(d, x0 + 1.0, y0 + 1.0, x0 + 2.0, y0 + 2.0, top, top + 4, material, t, rnd, 0, windows=False, style=style)   # a crown
        _paint_box(d, x0 + 1.25, y0 + 1.25, x0 + 1.75, y0 + 1.75, top + 4, top + 7, material, t, rnd, 0, windows=False, style=style)
        px, py = proj(x0 + 1.5, y0 + 1.5, top + 7)
        d.line(_q([(px, py), (px, py - 9)]), fill=_fog((210, 210, 232), t), width=max(1, S // 2))
        _red_light(d, px, py - 9)
    else:
        x0, y0, x1, y1, z0, z1 = _small_box()
        _paint_box(d, x0, y0, x1, y1, z0, z1, 'concrete', t, random.Random('small'), 0, windows=False, floor_h=SMALL_FLOOR,
                   style={'piers': False, 'bands': False})
        for f in range(5):                                                                 # every other floor a shade darker
            if f % 2:
                for a, b in _faces_base(x0, y0, x1, y1):
                    za, zb = f * SMALL_FLOOR, (f + 1) * SMALL_FLOOR
                    d.polygon(_q([(a[0], a[1] - za), (b[0], b[1] - za), (b[0], b[1] - zb), (a[0], a[1] - zb)]), fill=_fog((50, 54, 62), t))
        for left_quads, right_quads in small_windows():
            for quad in left_quads + right_quads:
                d.polygon(_q(quad), fill=_fog((14, 20, 34), t))
        for f in range(1, 6):                                                              # a bright ledge between the five floors
            for a, b in _faces_base(x0, y0, x1, y1):
                d.line(_q([(a[0], a[1] - f * SMALL_FLOOR), (b[0], b[1] - f * SMALL_FLOOR)]), fill=_fog((176, 174, 170), t), width=S + 1)
        corner = proj(x1, y1)
        for f in range(5):                                                                 # a ruler of five marks on the corner
            lo, hi = corner[1] - f * SMALL_FLOOR - 1.2, corner[1] - (f + 1) * SMALL_FLOOR + 1.2
            d.rectangle(_q([(corner[0] - .8, hi), (corner[0] + .8, lo)]), fill=_fog((244, 238, 222), t))
        for ox, oy in ((-1.1, -1.1), (1.1, 1.1), (-1.1, 1.1)):                             # rooftop machinery
            cx, cy = x0 + SMALL_SIZE / 2 + ox, y0 + SMALL_SIZE / 2 + oy
            _paint_box(d, cx - .35, cy - .35, cx + .35, cy + .35, z1, z1 + 2.4, 'concrete', t, random.Random('machine'), 0, windows=False)


def _paint_park(d, b, rnd):
    t = b.depth()
    d.polygon(_q([proj(b.x0, b.y0), proj(b.x1, b.y0), proj(b.x1, b.y1), proj(b.x0, b.y1)]), fill=_fog((30, 54, 38), t))
    for _ in range(rnd.randint(18, 30)):
        px, py = proj(rnd.uniform(b.x0 + .2, b.x1 - .2), rnd.uniform(b.y0 + .2, b.y1 - .2))
        r = rnd.uniform(1.3, 2.3)
        d.ellipse(_q([(px - r, py - r * 1.5), (px + r, py + r * .3)]), fill=_fog((26, 64, 40), t))
        d.ellipse(_q([(px - r * .6, py - r * 1.6), (px + r * .3, py - r * .8)]), fill=_fog((58, 106, 60), t))


def _in_keep(point):
    return any(k[0] <= point[0] <= k[2] and k[1] <= point[1] <= k[3] for k in _KEEP)


def _paint_lot(d, b, rnd):
    """A small park in front of a data building: lawn with mown stripes, gravel paths, a fountain, flower beds, hedges, benches
    and a few trees. It is nearly flat and keeps trees out of the way of the data building's lowest windows."""
    t = b.depth()
    z = b.h
    corners = [proj(b.x0, b.y0, z), proj(b.x1, b.y0, z), proj(b.x1, b.y1, z), proj(b.x0, b.y1, z)]
    d.polygon(_q(corners), fill=(46, 92, 56))
    for k in range(1, int((b.x1 - b.x0) * 3)):                                           # mown stripes
        x = b.x0 + k / 3
        d.line(_q([proj(x, b.y0, z), proj(x, b.y1, z)]), fill=(56, 106, 64) if k % 2 else (40, 82, 50), width=max(1, S // 2))
    cx, cy = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
    for end in ((b.x0, b.y0), (b.x1, b.y0), (b.x1, b.y1), (b.x0, b.y1)):                 # gravel paths to a round middle
        d.line(_q([proj(cx, cy, z), proj(*end, z)]), fill=(168, 156, 128), width=S)
    ring = _q([(proj(cx, cy, z)[0] - 5.2, proj(cx, cy, z)[1] - 2.6), (proj(cx, cy, z)[0] + 5.2, proj(cx, cy, z)[1] + 2.6)])
    d.ellipse(ring, fill=(168, 156, 128))
    px, py = proj(cx, cy, z)
    if rnd.random() < .6:                                                                # a fountain
        d.ellipse(_q([(px - 3.4, py - 1.7), (px + 3.4, py + 1.7)]), fill=(222, 226, 230))
        d.ellipse(_q([(px - 2.7, py - 1.3), (px + 2.7, py + 1.3)]), fill=(70, 156, 196))
        d.line(_q([(px, py), (px, py - 2.2)]), fill=(236, 246, 252), width=max(1, S // 2))
    else:                                                                                # a round flower bed
        d.ellipse(_q([(px - 3, py - 1.5), (px + 3, py + 1.5)]), fill=(122, 78, 58))
        for _ in range(7):
            fx, fy = px + rnd.uniform(-2.4, 2.4), py + rnd.uniform(-1.0, 1.0)
            d.point(_q([(fx, fy)])[0], fill=rnd.choice(((230, 90, 110), (246, 210, 80), (250, 250, 250), (200, 120, 220))))
    for k in range(4):                                                                   # hedges along the two front edges
        for end_a, end_b in (((b.x0, b.y1), (b.x1, b.y1)), ((b.x1, b.y0), (b.x1, b.y1))):
            u = .12 + k * .26
            a = proj(end_a[0] + (end_b[0] - end_a[0]) * u, end_a[1] + (end_b[1] - end_a[1]) * u, z)
            d.ellipse(_q([(a[0] - 1.5, a[1] - 1.2), (a[0] + 1.5, a[1] + .4)]), fill=(30, 70, 44))
    for _ in range(rnd.randint(8, 14)):                                                  # flower beds and benches, all flat
        fx, fy = proj(rnd.uniform(b.x0 + .3, b.x1 - .3), rnd.uniform(b.y0 + .3, b.y1 - .3), z)
        d.rectangle(_q([(fx - .6, fy - .3), (fx + .6, fy + .3)]), fill=rnd.choice(((230, 90, 110), (246, 210, 80), (250, 250, 250), (150, 100, 70))))
    for _ in range(rnd.randint(4, 7)):                                                   # trees, only clear of the data building
        tx, ty = proj(rnd.uniform(b.x0 + .25, b.x1 - .25), rnd.uniform(b.y0 + .25, b.y1 - .25), z)
        if _in_keep((tx, ty - 3)):
            continue
        r = rnd.uniform(1.4, 2.2)
        d.ellipse(_q([(tx - r, ty - r * 1.6), (tx + r, ty + .2)]), fill=(26, 70, 42))
        d.ellipse(_q([(tx - r * .6, ty - r * 1.6), (tx + r * .3, ty - r * .9)]), fill=(70, 126, 66))


def _gradient_sky(size):
    image = Image.new('RGB', size)
    px = image.load()
    for y in range(size[1]):
        yy = y / S
        row = _rgb(SKY[-1][0])
        for (c0, y0), (c1, y1) in zip(SKY, SKY[1:]):
            if y0 <= yy <= y1:
                row = mix(_rgb(c0), _rgb(c1), (yy - y0) / (y1 - y0))
                break
        for x in range(size[0]):
            px[x, y] = row
    return image


def _paint_ground(img, rnd):
    """Asphalt, pavement, lane marks, crosswalks, shadows at the foot of the blocks, lamps with their pools of light,
    street trees, traffic lights, cars and the long streaks of their lights."""
    d = ImageDraw.Draw(img)
    asphalt, pavement = (24, 26, 32), (74, 76, 82)
    cells = [(gx, gy) for gx in range(-60, 80) for gy in range(-60, 80) if -20 < proj(gx, gy)[0] < W + 20 and -10 < proj(gx, gy)[1] < H + 10]
    for gx, gy in cells:
        street = gx % 5 == 0 or gy % 5 == 0
        d.polygon(_q([proj(gx, gy), proj(gx + 1, gy), proj(gx + 1, gy + 1), proj(gx, gy + 1)]),
                  fill=_fog(asphalt if street else pavement, _depth(gx, gy)))
    light = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(light)
    trails = Image.new('RGBA', img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(trails)
    for gx, gy in cells:
        t = _depth(gx, gy)
        on_x = gy % 5 == 0 and gx % 5 != 0                                              # a street running along x
        on_y = gx % 5 == 0 and gy % 5 != 0                                              # a street running along y
        if on_x or on_y:                                                                # dashed centre line
            a, b = ((gx + .15, gy + .5), (gx + .45, gy + .5)) if on_x else ((gx + .5, gy + .15), (gx + .5, gy + .45))
            d.line(_q([proj(*a), proj(*b)]), fill=_fog((150, 130, 96), t), width=max(1, S // 2))
            for _ in range(rnd.choice((0, 1, 1, 2))):                                   # lanes of lights: long streaks
                lane = rnd.choice((.3, .7))
                start = rnd.uniform(0, .5)
                length = rnd.uniform(.35, .8)
                a, b = ((proj(gx + start, gy + lane), proj(gx + start + length, gy + lane)) if on_x
                        else (proj(gx + lane, gy + start), proj(gx + lane, gy + start + length)))
                colour = (255, 70, 60) if lane > .5 else (255, 238, 190)
                td.line(_q([a, b]), fill=colour + (230,), width=max(1, round(S * .7)))
        if gx % 5 == 0 and gy % 5 == 0:                                                 # an intersection: crosswalks, signals
            for i in range(5):
                off = .12 + i * .17
                d.line(_q([proj(gx + off, gy + .02), proj(gx + off, gy + .2)]), fill=_fog((214, 210, 224), t), width=max(1, S // 2))
                d.line(_q([proj(gx + .02, gy + off), proj(gx + .2, gy + off)]), fill=_fog((214, 210, 224), t), width=max(1, S // 2))
            for k, (cx, cy) in enumerate(((gx + .1, gy + .1), (gx + .9, gy + .9))):
                px, py = proj(cx, cy)
                colour = (255, 70, 60) if (gx + gy + k) % 3 else (110, 255, 140)
                d.ellipse(_q([(px - .6, py - 2.2), (px + .6, py - 1.0)]), fill=colour)
                ld.ellipse(_q([(px - 3, py - 3.4), (px + 3, py + .4)]), fill=colour + (60,))
    for gx in range(-60, 80, 5):                                                         # the feet of the blocks
        for gy in range(-60, 80, 5):
            if not (-30 < proj(gx + 1, gy + 1)[0] < W + 30 and -10 < proj(gx + 1, gy + 1)[1] < H + 10):
                continue
            ld.polygon(_q([proj(gx + 1, gy + 5), proj(gx + 5, gy + 5), proj(gx + 5, gy + 5.5), proj(gx + 1, gy + 5.5)]), fill=(0, 0, 14, 90))
            ld.polygon(_q([proj(gx + 5, gy + 1), proj(gx + 5.5, gy + 1), proj(gx + 5.5, gy + 5.5), proj(gx + 5, gy + 5)]), fill=(0, 0, 14, 70))
            for cx, cy in ((gx + .75, gy + .75), (gx + 5.25, gy + .75), (gx + .75, gy + 5.25), (gx + 5.25, gy + 5.25)):       # lamps
                px, py = proj(cx, cy)
                if -5 < px < W + 5 and -5 < py < H + 5:
                    ld.ellipse(_q([(px - 6, py - 2.6), (px + 6, py + 2.6)]), fill=(255, 190, 110, 70))
                    d.ellipse(_q([(px - .6, py - 1.4), (px + .6, py - .2)]), fill=(255, 230, 170))
            for k in range(1, 8):                                                       # street trees along the pavement
                for cx, cy in ((gx + 1 + k * .5, gy + .85), (gx + .85, gy + 1 + k * .5)):
                    if rnd.random() < .55:
                        px, py = proj(cx, cy)
                        if 0 < px < W and 0 < py < H:
                            r = rnd.uniform(1.0, 1.6)
                            d.ellipse(_q([(px - r, py - r * 1.7), (px + r, py)]), fill=_fog((26, 62, 40), _depth(cx, cy)))
                            d.ellipse(_q([(px - r * .5, py - r * 1.7), (px + r * .4, py - r * .9)]), fill=_fog((56, 104, 60), _depth(cx, cy)))
    img.alpha_composite(light.filter(ImageFilter.GaussianBlur(2.0 * S)))
    img.alpha_composite(trails.filter(ImageFilter.GaussianBlur(.55 * S)))
    img.alpha_composite(trails)
    d = ImageDraw.Draw(img)
    for _ in range(130):                                                                # cars, buses and vans with lit ends
        gx, gy = rnd.randint(-25, 66), rnd.randint(-25, 66)
        if gx % 5 and gy % 5:
            continue
        along_x = gy % 5 == 0 and gx % 5 != 0
        px, py = proj(gx + rnd.uniform(.2, .8), gy + rnd.choice((.3, .7))) if along_x else proj(gx + rnd.choice((.3, .7)), gy + rnd.uniform(.2, .8))
        if not (0 < px < W and 0 < py < H):
            continue
        kind = rnd.random()
        if kind < .1:                                                                   # a bus: long, tall, a lit strip of windows
            colour, length, height = rnd.choice(((230, 230, 236), (40, 90, 160), (230, 130, 40))), 3.4, 2.2
        elif kind < .2:                                                                 # a van
            colour, length, height = rnd.choice(((220, 220, 226), (60, 60, 70))), 2.4, 1.8
        else:
            colour, length, height = rnd.choice(((240, 190, 40), (30, 30, 40), (220, 220, 230), (150, 40, 40), (240, 190, 40), (60, 80, 140))), 1.8, 1.1
        d.polygon(_q([(px - length, py - height), (px + length, py - height), (px + length, py + .5), (px - length, py + .5)]), fill=colour)
        d.polygon(_q([(px - length + .5, py - height - .9), (px + length - .4, py - height - .9), (px + length, py - height), (px - length, py - height)]),
                  fill=mix(colour, (255, 255, 255), .3))
        if kind < .1:
            d.line(_q([(px - length + .6, py - height * .55), (px + length - .6, py - height * .55)]), fill=(255, 226, 160), width=max(1, S // 2))
        d.point(_q([(px - length, py - .2)])[0], fill=(255, 245, 200))
        d.point(_q([(px + length, py - .2)])[0], fill=(255, 80, 70))


def _bloom(img, strength=.20):
    """A soft glow around every bright light (windows, lamps, streaks), as a night photograph has."""
    rgb = img.convert('RGB')
    bright = rgb.point([min(255, max(0, v - 150) * 3) for v in range(256)] * 3)
    glow = bright.filter(ImageFilter.GaussianBlur(1.4 * S))
    wide = bright.filter(ImageFilter.GaussianBlur(4.0 * S))
    glow = ImageChops.add(glow.point(lambda v: round(v * strength)), wide.point(lambda v: round(v * strength * .7)))
    return Image.merge('RGBA', (*ImageChops.add(rgb, glow).split(), img.getchannel('A')))


def _vignette(img):
    """A gentle darkening towards the edges, as a lens gives."""
    w, h = img.size
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * .18, -h * .24, w * 1.18, h * 1.24), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w * .12))
    dark = Image.new('RGBA', (w, h), (4, 6, 12, 255))
    return Image.composite(img, dark, mask.point(lambda v: round(160 + v * .37)))


GLOW_REACH = 5.0                                     # the bloom of a lit window changes pixels up to ~4 px past the wall (measured)
ANIM_STEP_MS = 160                                 # every sprite steps at the same pace (the engine test replays them together)
ANIM_STEPS = 32
ASPHALT = (24, 26, 32)
_PLAN = {}                                           # filled by city_backdrop(): where things move


def _data_regions():
    """Boxes round the three data buildings (with their signs) and the cards: nothing animated may be painted there."""
    regions = []
    for name in HEROES:
        pts = [p for box in _hero_boxes(name) for face in _box_faces(*box)[:2] for p in face]
        pts += [proj(HEROES[name][0] + 1.5, HEROES[name][1] + 1.5, TOWER_FLOORS * HERO_FLOOR + 34)]
        regions.append((min(x for x, _ in pts) - 12, min(y for _, y in pts) - 12, max(x for x, _ in pts) + 12, max(y for _, y in pts) + 12))
    pts = [p for face in _box_faces(*_small_box())[:2] for p in face]
    pts += [proj(SMALL[0] + SMALL_SIZE / 2, SMALL[1] + SMALL_SIZE / 2, 5 * SMALL_FLOOR + 24)]
    regions.append((min(x for x, _ in pts) - 12, min(y for _, y in pts) - 12, max(x for x, _ in pts) + 12, max(y for _, y in pts) + 12))
    regions.append((0, 166, 320, 240))
    return regions


def _body_polygons():
    """The faces of the three data buildings (a few pixels wider) and the cards: what a car must not drive over."""
    polys = []
    for name in HEROES:
        for box in _hero_boxes(name):
            for face in _box_faces(*box)[:2]:
                polys.append(face)
    for face in _box_faces(*_small_box())[:2]:
        polys.append(face)
    return polys


def _inside(point, poly, margin=3.0):
    """True if `point` is inside the convex quad `poly` or within `margin` pixels of it."""
    x, y = point
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    if not (min(xs) - margin <= x <= max(xs) + margin and min(ys) - margin <= y <= max(ys) + margin):
        return False
    sign = 0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        cross = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)
        length = math.hypot(x1 - x0, y1 - y0) or 1.0
        if cross / length < -margin:
            sign |= 1
        elif cross / length > margin:
            sign |= 2
    return sign != 3


def _body_regions():
    """Boxes for the cards only (the data buildings are tested face by face with `_body_polygons`)."""
    return [(0, 170, 320, 240)]


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _sprite_image(width, height, pixels):
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    for (i, j), colour in pixels.items():
        image.putpixel((i, j), tuple(colour) + (255,))
    return image


def _gull_sprite():
    """A gull crossing the top-right corner: it comes in over the right edge and leaves over the top, flapping, so the
    loop restarts out of sight. Three wing positions on a 5x3 grid."""
    shapes = (('X...X', '.XXX.', '..X..'), ('.....', 'XXXXX', '..X..'), ('.....', '.XXX.', 'X...X'))
    frames = []
    for shape in shapes:
        pixels = {}
        for j, row in enumerate(shape):
            for i, cell in enumerate(row):
                if cell == 'X':
                    pixels[(i, j)] = (176, 188, 206) if (j == 2 or (j == 1 and i in (0, 4))) else (246, 246, 250)
        frames.append(_sprite_image(5, 3, pixels))
    x_start, y_start, x_end, y_end = 326, 34, 214, -9
    script = []
    for step in range(ANIM_STEPS):
        t = step / (ANIM_STEPS - 1)
        script.append(((0, 1, 2, 1)[step % 4], round((x_end - x_start) * t), round((y_end - y_start) * t + math.sin(step * .7) * 1.6)))
    return {'name': 'gull', 'x': x_start, 'y': y_start, 'frames': frames, 'script': script, 'step_ms': ANIM_STEP_MS}


def _flock_sprite():
    """A flock of five birds that flies in over the left edge, crosses the sky and climbs out over the top, so the loop
    restarts out of sight. A V of two sizes (two near ones like the gull, three smaller far ones), each bird at its own
    point of the wingbeat; four poses of the whole flock on a 13x12 canvas, moving as one. A sprite can travel at most 127
    pixels, so the flock is kept compact and stays in the upper left, clear of the gull's corner and of both towers."""
    near = (('X...X', '.XXX.', '..X..'), ('.....', 'XXXXX', '..X..'), ('.....', '.XXX.', 'X...X'))
    far = (('X.X', '.X.'), ('XXX', '...'), ('...', 'XXX'))
    birds = ((near, 8, 4), (far, 4, 0), (near, 4, 7), (far, 0, 4), (far, 1, 10))
    frames = []
    for pose in range(4):
        pixels = {}
        for k, (shapes, bx, by) in enumerate(birds):
            for j, row in enumerate(shapes[(0, 1, 2, 1)[(pose + k) % 4]]):
                for i, cell in enumerate(row):
                    if cell == 'X':
                        pixels[(bx + i, by + j)] = ((176, 188, 206) if (j == 2 or (j == 1 and i in (0, 4))) else (246, 246, 250)) \
                            if shapes is near else (190, 200, 218)
        frames.append(_sprite_image(13, 12, pixels))
    x_start, y_start, rise = -26, 12, 38
    script = []
    for step in range(ANIM_STEPS):
        t = min(1.0, max(0.0, (step - 5) / 22))                       # out of sight for a moment at both ends of the loop
        climb = max(0.0, (t - .55) / .45) ** 1.6
        script.append((step % 4, round(127 * t), round(math.sin(step * .6) * 1.4 * (1 - climb) - rise * climb)))
    return {'name': 'flock', 'x': x_start, 'y': y_start, 'frames': frames, 'script': script, 'step_ms': ANIM_STEP_MS}


def _car_sprite(path, colour, visible):
    """One car, two lights and a dark body (3x2 sprite pixels), that drives along `path` (start, end in page pixels) and is
    only shown on the steps where `visible` says that stretch of street is open to view: it slips behind a building and
    comes out again, as it would. Four brightnesses give it a soft edge (full, half, a glimmer, none)."""
    (x0, y0), (x1, y1) = path
    frames = []
    for level in (1.0, .6, .3, None):
        pixels = {}
        if level is not None:
            shade = mix((8, 10, 14), (222, 222, 228), level * .55)
            lit = mix((40, 40, 46), colour, level)
            for i in range(3):
                pixels[(i, 0)] = shade
            pixels[(0, 1)], pixels[(1, 1)], pixels[(2, 1)] = lit, shade, lit
        frames.append(_sprite_image(3, 2, pixels))
    script = []
    for step in range(ANIM_STEPS):
        move = min(1.0, max(0.0, (step - 2) / 27))
        here = visible[step]
        near = visible[step - 1] and visible[(step + 1) % ANIM_STEPS]
        frame = 3 if not here else (0 if near else 2)
        script.append((frame, round((x1 - x0) * move), round((y1 - y0) * move)))
    return {'x': round(x0) - 3, 'y': round(y0) - 2, 'frames': frames, 'script': script, 'step_ms': ANIM_STEP_MS}


def _street_runs(img, ground, bodies):
    polys = _body_polygons()
    """Candidate drives: a long stretch of street (8 to 5 blocks, along either axis) and, for each of the 32 steps of a car
    that crosses it, whether the car's spot is open to view (asphalt, nothing built over it, clear of the data buildings)."""
    found = []
    for length in (8, 6, 5):
        for along in ('x', 'y'):
            for line in range(-30, 70, 5):
                for start in range(-30, 68):
                    for lane in (.3, .7):
                        if along == 'x':
                            a, b = proj(start, line + lane), proj(start + length, line + lane)
                        else:
                            a, b = proj(line + lane, start), proj(line + lane, start + length)
                        if not (-10 < a[0] < 330 and -10 < b[0] < 330 and 20 < min(a[1], b[1]) and max(a[1], b[1]) < 170):
                            continue
                        visible = []
                        for step in range(ANIM_STEPS):
                            move = min(1.0, max(0.0, (step - 2) / 27))
                            px, py = a[0] + (b[0] - a[0]) * move, a[1] + (b[1] - a[1]) * move
                            spots = [(round((px + dx) * S), round((py + dy) * S)) for dx, dy in ((-2.2, -.5), (0, -.5), (2.2, -.5), (0, .8))]
                            ok = 0 < px < 320 and 0 < py < 170 and not any(_inside((px, py), poly, GLOW_REACH) for poly in polys)
                            if ok:
                                for spot in spots:
                                    if not (0 <= spot[0] < img.width and 0 <= spot[1] < img.height):
                                        ok = False
                                        break
                                    c, g = img.getpixel(spot)[:3], ground.getpixel(spot)[:3]
                                    ok = ok and c == g and all(abs(g[i] - ASPHALT[i]) < 22 for i in range(3))
                            visible.append(bool(ok))
                        run = best = 0
                        for flag in visible + visible:                                     # the longest unbroken view, wrapping round
                            run = run + 1 if flag else 0
                            best = max(best, run)
                        best = min(best, ANIM_STEPS)
                        if best >= 5:
                            centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                            score = best * 10 + sum(visible) * 2 + (centre[1] - 60) * .3 - abs(centre[0] - 160) * .15
                            found.append((score, (a, b), visible, along))
    return sorted(found, key=lambda c: -c[0])


def _plan_animation(img, rec, rnd, ground):
    """Choose what moves, from the finished picture: two cars on streets that stay in view, ten of its own windows that
    turn on and off, and a gull. The chosen windows are painted dark here, so the sprite lights them."""
    regions = _data_regions()
    gull = _gull_sprite()
    xs = [gull['x'] + dx for _, dx, _ in gull['script']]
    ys = [gull['y'] + dy for _, _, dy in gull['script']]
    taken = [(min(xs), min(ys), max(xs) + 10, max(ys) + 6)]
    flock = _flock_sprite()
    fx = [flock['x'] + dx for _, dx, _ in flock['script']]
    fy = [flock['y'] + dy for _, _, dy in flock['script']]
    taken.append((min(fx), min(fy), max(fx) + 26, max(fy) + 24))
    plan = {'gull': gull, 'flock': flock, 'cars': [], 'windows': None}
    drives = _street_runs(img, ground, _body_regions())
    for colour, toward in (((255, 244, 210), True),):                 # one car: the board has four sprites and the birds need three
        for score, (a, b), visible, along in drives:
            path = (a, b) if (a[1] < b[1]) == toward else (b, a)
            car = _car_sprite(path, colour, visible)
            cx = [car['x'] + dx for _, dx, _ in car['script']]
            cy = [car['y'] + dy for _, _, dy in car['script']]
            real = (min(cx), min(cy), max(cx) + 6, max(cy) + 4)
            if not any(_overlap(real, t) for t in taken):
                plan['cars'].append(car)
                taken.append(real)
                break
    # ten visible windows of the city to turn on and off, from the best patch of facade
    visible = []
    for quad, drawn, dark in rec:
        if drawn is None:
            continue
        cx, cy = sum(x for x, _ in quad) / 4, sum(y for _, y in quad) / 4
        if not (6 < cx < 314 and 14 < cy < 160):
            continue
        c = img.getpixel((round(cx * S), round(cy * S)))[:3]
        if all(abs(c[i] - drawn[i]) < 24 for i in range(3)):
            visible.append((cx, cy, quad, dark))
    best = None
    for bx in range(6, 260, 8):
        for by in range(14, 130, 8):
            box = (bx, by, bx + 52, by + 34)
            if any(_overlap(box, r) for r in regions + taken):
                continue
            inside = [v for v in visible if box[0] <= v[0] < box[2] and box[1] <= v[1] < box[3]]
            chosen = []
            for v in sorted(inside, key=lambda v: (v[1], v[0])):
                if all(abs(v[0] - c[0]) >= 5 or abs(v[1] - c[1]) >= 5 for c in chosen):
                    chosen.append(v)
            if len(chosen) >= 10 and (best is None or len(inside) > best[0]):
                best = (len(inside), chosen[:10], box)
    if best:
        chosen = best[1]
        x0 = int(min(c[0] for c in chosen)) - 1
        y0 = int(min(c[1] for c in chosen)) - 1
        width = int((max(c[0] for c in chosen) - x0) // 2) + 2
        height = int((max(c[1] for c in chosen) - y0) // 2) + 2
        spots = [(int((c[0] - x0) // 2), int((c[1] - y0) // 2)) for c in chosen]
        draw = ImageDraw.Draw(img)
        for c in chosen:
            draw.polygon(_q(c[2]), fill=c[3])
        warm = [rnd.choice(WARM) for _ in chosen]
        frames = []
        for off in (5, 2, 7, 0):                                   # each frame has one window off: lights come and go
            pixels = {spot: warm[k] for k, spot in enumerate(spots) if k != off}
            frames.append(_sprite_image(width, height, pixels))
        script = [((step // 4) % 4, 0, 0) for step in range(ANIM_STEPS)]            # a light changes every 0.64 s, calmly
        plan['windows'] = {'name': 'windows', 'x': x0, 'y': y0, 'frames': frames, 'script': script, 'step_ms': ANIM_STEP_MS}
    _PLAN.clear()
    _PLAN.update(plan)


@functools.lru_cache(maxsize=1)
def city_backdrop():
    """The sunset glow and the whole fixed city drawn back to front, at drawing scale; the three data buildings are dark
    bodies here and light up per reading in `render_countdown`."""
    size = (W * S, H * S)
    img = _gradient_sky(size).convert('RGBA')
    glow = Image.new('RGBA', size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-60 * S, 14 * S, 380 * S, 84 * S), fill=(255, 150, 80, 110))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18 * S)))
    _paint_ground(img, random.Random(7))
    ground = img.copy()
    rnd = random.Random(11)
    items = [(b.x1 + b.y1, 'b', b) for b in _city()]
    items += [(HEROES[n][0] + 3 + HEROES[n][1] + 3, 't', n) for n in HEROES]
    items += [(SMALL[0] + SMALL[1] + 2 * SMALL_SIZE, 't', 'small')]
    items.sort(key=lambda item: item[0])
    draw = ImageDraw.Draw(img)
    global _REC
    rec = []
    for key, kind, item in items:
        if kind == 't':
            _paint_tower(draw, item)
        elif item.kind == 'park':
            _paint_park(draw, item, rnd)
        elif item.kind == 'lot':
            _paint_lot(draw, item, rnd)
        else:
            _REC = rec
            _paint_building(draw, item, rnd)
            _REC = None
    _plan_animation(img, rec, random.Random(5), ground)
    return _vignette(_bloom(img).resize((W * SS, H * SS), Image.Resampling.LANCZOS))


# ------------------------------------------------------------------------------------------- dynamic overlays
def _mascot(name, height):
    im = Image.open(ASSETS / f'{name}-pixel.png').convert('RGBA')
    im = im.crop(im.getbbox())
    scale = height / im.height
    return im.resize((max(1, round(im.width * scale)), height), Image.Resampling.NEAREST)


def _text_image(text, size, colour):
    font = face('press-start-2p.ttf', size)
    box = font.getbbox(text)
    image = Image.new('RGBA', (box[2] - box[0] + 2, box[3] - box[1] + 2), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((1 - box[0], 1 - box[1]), text, font=font, fill=colour)
    return image


def _skewed(layer_size, image, p0, edge, height):
    """`image` stood on a vertical board: its bottom-left corner at `p0`, its bottom edge running along `edge` and its
    height `height` on screen (all in layer pixels): the isometric view of a sign on a roof."""
    iw, ih = image.size
    hx, hy = edge
    coeffs = (iw / hx, 0, -p0[0] * iw / hx,
              -hy * ih / (hx * height), ih / height, ((height - p0[1]) + hy * p0[0] / hx) * ih / height)
    return image.transform(layer_size, Image.AFFINE, coeffs, resample=Image.NEAREST)


def _iso_board(scene, centre, plane, width, height, z_base, accent, image):
    """A lit board on two posts standing on a roof at cell `centre`, in the plane facing +x ('right') or +y ('left'), in the
    city's own isometric projection, with `image` skewed onto it, a frame, a little glow and a little thickness."""
    cx, cy = centre
    half = width / 2
    if plane == 'right':                                    # the plane x = cx runs along y, down-left on screen
        (lx, ly), (rx, ry) = proj(cx, cy + half, z_base), proj(cx, cy - half, z_base)
        back = (-1.0, -.55)
    else:                                                   # the plane y = cy runs along x, down-right on screen
        (lx, ly), (rx, ry) = proj(cx - half, cy, z_base), proj(cx + half, cy, z_base)
        back = (1.0, -.55)
    lift = 4                                                # the posts lift the board above the roof
    colour = _rgb(accent)
    for k in (.14, .86):
        px, py = lx + (rx - lx) * k, ly + (ry - ly) * k
        scene.line((px, py), (px, py - lift), '#8a8c98', 1)
    frame = [(lx, ly - lift), (rx, ry - lift), (rx, ry - lift - height), (lx, ly - lift - height)]
    slab = [(x + back[0], y + back[1]) for x, y in frame]
    scene.d.polygon(_q(slab, SS), fill=(14, 16, 22, 255))
    scene.g.polygon(_q(frame, SS), fill=colour + (110,))
    scene.d.polygon(_q(frame, SS), fill=mix(colour, (28, 30, 38), .35) + (255,))
    pad = .1
    a, b = _lerp((lx, ly - lift), (rx, ry - lift), pad), _lerp((lx, ly - lift), (rx, ry - lift), 1 - pad)
    margin = height * pad
    scene.d.polygon(_q([(a[0], a[1] - margin), (b[0], b[1] - margin), (b[0], b[1] - height + margin), (a[0], a[1] - height + margin)], SS),
                    fill=(12, 14, 22, 255))
    inner_h = (height - 2 * margin) * .74
    inner_w = min(abs(b[0] - a[0]) * .8, inner_h * image.width / image.height * .92)
    frac = inner_w / abs(b[0] - a[0])
    start = _lerp(a, b, .5 - frac / 2)
    edge = ((b[0] - a[0]) * frac, (b[1] - a[1]) * frac)
    base = (start[0], start[1] - margin - (height - 2 * margin - inner_h) / 2)
    scale = 8
    big = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    scene.ink.alpha_composite(_skewed(scene.ink.size, big, (base[0] * SS, base[1] * SS), (edge[0] * SS, edge[1] * SS), inner_h * SS))


def city_animation():
    """The sprites that move over the page: a gull, a flock, a car and ten windows, as dicts (x, y, frames, script, step_ms)."""
    city_backdrop()
    return [s for s in [_PLAN['gull'], _PLAN['flock'], *_PLAN['cars'], _PLAN['windows']] if s]


def week_floors(value):
    """Floors lit for a weekly quota left, as a float: a tenth of a floor per percent (75 % = 7.5), at least one percent
    while anything is left, none when unknown."""
    if value is None or value <= 0:
        return 0.0
    return max(1, round(value)) / 10


def _light(scene, quads, colour, glow=150):
    for quad in quads:
        scene.d.polygon(_q(quad, SS), fill=_rgb(colour) + (255,))
        scene.g.polygon(_q(quad, SS), fill=_rgb(colour) + (glow,))


def _light_small(scene, parts_left, parts_right):
    """Light the five-hour building: floors from the ground up, the floor that is changing window by window."""
    plan = small_windows()
    for side, parts, colour in ((0, parts_left, STONE_QUOTA), (1, parts_right, STONE_TIME)):
        for f, quads in enumerate(plan):
            share = max(0.0, min(1.0, parts - f))
            if share > 0:
                _light(scene, quads[side][:max(1, round(share * len(quads[side])))], colour)


def _card(scene, x, y, accent, name, value, reset, banked):
    """A translucent card: mascot and name, the quota number, the weekly reset and the saved resets."""
    w, h = 150, 52
    scene.rect((x - 1, y - 1, x + w + 1, y + h + 1), fill=mix(_rgb('#0a0f18'), _rgb(accent), .5) + (255,), radius=7)
    scene.rect((x, y, x + w, y + h), fill=(12, 16, 26, 226), radius=6)
    icon = _mascot(name.lower(), 14)
    layer = Image.new('RGBA', scene.ink.size, (0, 0, 0, 0))
    big = icon.resize((icon.width * SS, icon.height * SS), Image.Resampling.NEAREST)
    layer.paste(big, (round((x + 9) * SS), round((y + 6) * SS)), big)
    scene.ink.alpha_composite(layer)
    scene.text((x + 9 + icon.width + 6, y + 13), name.upper(), 'orbitron.ttf', 10, accent, anchor='lm', glow=True)
    number = '--' if value is None else f'{round(value)}'
    width = face('oxanium.woff2', 28 * SS).getlength(number) / SS
    scene.text((x + 9, y + 36), number, 'oxanium.woff2', 28, '#eaf4ff', anchor='lm', glow=True)
    scene.text((x + 9 + width + 3, y + 40), '%' if value is not None else '?', 'oxanium.woff2', 13, accent, anchor='lm')
    scene.text((x + 88, y + 29), 'RESET', 'press-start-2p.ttf', 4, LABEL, anchor='lm')
    scene.text((x + 88, y + 41), reset.upper(), 'oxanium.woff2', 14, '#eaf4ff', anchor='lm')
    count, old = banked
    _resets(scene, x + 119, y + 8, count, old, accent, LABEL, 'house')


def _first_pose(image, sprites):
    """A board that cannot animate gets each sprite as it is at step zero, drawn as the board would (2x2 blocks)."""
    pixels = image.load()
    for sprite in sprites:
        frame, dx, dy = sprite['script'][0]
        for j in range(sprite['frames'][frame].height):
            for i in range(sprite['frames'][frame].width):
                r, g, b, a = sprite['frames'][frame].getpixel((i, j))
                if a < 128:
                    continue
                for ky in range(2):
                    for kx in range(2):
                        x, y = sprite['x'] + dx + i * 2 + kx, sprite['y'] + dy + j * 2 + ky
                        if 0 <= x < W and 0 <= y < H:
                            pixels[x, y] = (r, g, b)


def render_countdown(snapshot, animated=False):
    scene = Scene(city_backdrop)
    rows = {provider: _row(snapshot, provider) for provider in ('codex', 'claude')}
    pace = session_pace(rows['claude'])
    for provider, accent, plane in (('codex', CODEX, 'right'), ('claude', CLAUDE, 'left')):
        value, _, _, reset = remaining_reading(rows[provider])
        floors_lit = week_floors(value)
        for f, columns in enumerate(tower_columns(provider)):
            for column in columns[:lit_columns(f, floors_lit, len(columns))]:
                _light(scene, column, '#%02x%02x%02x' % LIT[provider])
        x0, y0 = HEROES[provider]
        _iso_board(scene, (x0 + 1.5, y0 + 1.5), plane, 2.4, 12, TOWER_FLOORS * HERO_FLOOR + 12, accent, _mascot(provider, 16))
    sx, sy = SMALL
    _iso_board(scene, (sx + SMALL_SIZE / 2, sy + SMALL_SIZE / 2), 'left', 2.0, 8, 5 * SMALL_FLOOR + 3, STONE_QUOTA,
               _text_image('5H', 12, (244, 239, 228, 255)))
    if pace is not None:                                                       # only from a fresh reading
        quota, hours = pace
        _light_small(scene, math.ceil(quota / 5) / 4, round(hours * 4) / 4)
    for provider, accent, x in (('codex', CODEX, 6), ('claude', CLAUDE, 164)):
        value, _, _, reset = remaining_reading(rows[provider])
        _card(scene, x, 174, accent, provider, value, reset, banked_hearts(rows[provider]))
    image = scene.finish()
    sprites = city_animation()
    if not animated:
        _first_pose(image, sprites)
        return image
    return image, board_anim.encode(sprites)
