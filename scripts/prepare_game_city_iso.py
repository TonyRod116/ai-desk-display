"""Prepare the atlas of the tablet's real-time scene CITY IN THE SKY (`token_tv/tablet_web/game-city-iso.js`), offline.

The scene is a small program (see docs/tablet-games.md and docs/tablet-game-city-iso.md); this script draws the part of it that never moves, once, on the
computer and not on the tablet: an isometric city at four times of day (day, golden hour, blue hour, night) as four pictures that the scene cross-fades
by the real clock, the lights of its windows in ten batches that come on one batch after another at dusk, the sky, and the numbers the scene needs to
make it alive (where the streets, the river, the rail, the beacons, the steam, the screens are; which pixel belongs to which building, so that a car
can drive behind a tower; where every window of the three data buildings is, floor by floor and column by column).

    nice -n 15 ionice -c 3 .venv/bin/python -B scripts/prepare_game_city_iso.py --out DIR [--manifest] [--quick] [--seed N]

writes, owner-only and atomically, `scene-city-iso.png` (the atlas), `scene-city-iso.json` (its frames and the numbers) and `thumb-city-iso.webp` into DIR
(the real private folder is `~/.local/share/ai-desk-display/tablet/`; with --manifest it also adds the scene to its `scenes.json`). Nothing of Tony's
is read: the art is ORIGINAL, drawn here from scratch by code (its approach and many of its architectural ideas are translated from `board_city.py`, the
small board's own isometric city, which is not imported or changed). The only picture files used are the project's two mascots, for the rooftop signs.

How the four times of day are made: the city is painted ONCE into an albedo picture (the colours of the materials, with no light), a class picture (what
every pixel is made of: left wall, right wall, glass, roof, asphalt, water, foliage...) and an id picture (which building owns it). Each time of day is
then LIT from those: a multiplier and an adder per class (the sun on the right walls, the sky on the glass, nothing on the shaded left walls...), the
shadows of the buildings on the ground, the pools of the street lamps, a haze that thickens towards the horizon. Everything is drawn at four times the
size and reduced by averaging, which is what gives the soft, photographic edges of the board's city.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media as media  # noqa: E402
from token_tv.display import ASSETS  # noqa: E402

NAME = 'city-iso'
VIEW = (267, 427)                  # the scene's native size: x3 is 801 x 1281 on the tablet's 800 x 1280 panel (200 x 320 would be x4)
MARGIN = (12, 12)                  # extra pixels all round, for the camera's slow drift
WORLD = (VIEW[0] + 2 * MARGIN[0], VIEW[1] + 2 * MARGIN[1])
HW, HH = 6, 3                      # half width and half height of a ground cell on the picture (the classic 2:1 isometric)
OX, OY = 146, -48                  # where ground cell (0, 0) lands in the world picture
S = 4                              # supersampling: everything is drawn at S times the size and reduced by averaging
SKY_ROWS = 80                      # the sky pictures cover the top of the world
BUCKETS = 10                       # the window lights come on in this many batches
PHASES = ('day', 'gold', 'blue', 'night')
GMIN, GMAX = -14, 104              # the grid that is painted: cells GMIN..GMAX in both directions (land everywhere: the city runs to the top of the picture)
CANAL = (66, 70)                   # a canal across the lower part of the city (cells of gy): under the dock, seen in picture mode
BRIDGES = (13, 16)                 # the streets (gx = 5 m) that cross the canal on a bridge
FLOOR = 4.2                        # a city floor, in pixels
HERO_FLOOR = 9                     # a data tower's floor: two rows of windows
HERO_FLOORS, HERO_LOWER = 10, 7    # ten floors of 10 %, the wide part has seven
HERO_COLS = 5                      # window columns on each face of a data tower: 5 + 5 = ten per floor, one per percent
SMALL_FLOORS, SMALL_COLS, SMALL_FLOOR = 5, 8, 6           # the five-hour building: low (thirty pixels) and quiet, it stands in its block, not above a street
ROW_PIX = ((1, 3), (5, 7))        # two slender, slightly taller windows above each ledge, in world pixels
PLACE = (41.39, 2.17)              # where the sun is computed for (latitude, longitude): Barcelona; --lat/--lon change it
LIT_COLOURS = {'codex': (255, 220, 136), 'claude': (246, 240, 228)}
HEROES = {                         # where the front (bottom) corner of each data building is, in world pixels, and how wide its faces are
    # Front corners are projected from the far corner of their actual lots:
    # (35, 45) and (40, 35), respectively. A face is four grid cells wide,
    # so neither tower straddles a road or a neighbouring block.
    # A slender glass shaft rising from a low podium, distinct from Claude's
    # broad stone tower with its high setbacks. Both still have 100 data cells.
    'codex': dict(front=(86, 192), face=24, upper=16, material='glass'),
    'claude': dict(front=(176, 177), face=24, upper=18, material='stone'),
    'small': dict(front=(236, 177), face=24, upper=24, material='concrete'),   # the whole of the block (8, 5): cells 41 to 45 by 26 to 30, between its four streets
}

# what a pixel is made of: the lighting of each time of day is a multiplier and an adder per class
(NONE, ASPHALT, PAVE, GRASS, STONE, WATER, WALL_L, WALL_R, GLASS_L, GLASS_R, ROOF, METAL, LEAF, SHOP, SIGN, TRACK, LAMP) = range(17)


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def smooth(a, b, x):
    t = clamp((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def proj(gx, gy, z=0.0):
    """A ground point (cell units) and a height (pixels) to a world pixel."""
    return OX + (gx - gy) * HW, OY + (gx + gy) * HH - z


def unproj(x, y):
    u, v = (x - OX) / HW, (y - OY) / HH
    return (u + v) / 2, (v - u) / 2


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def id_colour(n):
    return (n & 255, (n >> 8) & 255, 0)


# ---------------------------------------------------------------------------------------------------------------- the times of day
# (multiplier, adder) per class and phase. The albedo is painted as the colour of a material under a dusk sky (the board's own palettes), so golden hour is
# close to 1 on the sunny walls; day lifts everything, blue hour and night bring it down and make the sky the only light.
def _lit(amb, sun, k, add=(0, 0, 0)):
    return tuple(amb[i] + sun[i] * k for i in range(3)), add


def light_table(phase):
    p = {
        'day': dict(amb=(.62, .68, .82), sun=(.62, .58, .48), refl=(150, 196, 236), rk=.26, ground=.95, leaf=1.1),
        'gold': dict(amb=(.50, .48, .62), sun=(.78, .50, .24), refl=(255, 178, 110), rk=.24, ground=.85, leaf=1.0),
        'blue': dict(amb=(.58, .63, .78), sun=(.14, .14, .16), refl=(110, 130, 190), rk=.22, ground=.9, leaf=.9),
        # Moonlight keeps neighbouring façades and roof silhouettes legible
        # on the tablet while the warm windows still read as night lighting.
        # Preserve the colours of brick, stone, glass and foliage after dark.
        # The former blue-heavy light made adjacent materials look alike on the tablet.
        'night': dict(amb=(.37, .38, .45), sun=(.16, .14, .11), refl=(65, 84, 125), rk=.24, ground=1.05, leaf=1.04),
    }[phase]
    amb, sun, refl, rk = p['amb'], p['sun'], p['refl'], p['rk']
    glass_add = tuple(round(refl[i] * rk) for i in range(3))
    shade = tuple(min(1, a * 1.0) for a in amb)
    t = {
        ASPHALT: _lit(amb, sun, p['ground']), PAVE: _lit(amb, sun, p['ground']), STONE: _lit(amb, sun, p['ground']),
        GRASS: _lit(amb, sun, p['ground'] * p['leaf'], (3, 7, 4) if phase in ('blue', 'night') else (0, 0, 0)), WATER: _lit(amb, sun, .5),
        WALL_L: _lit(amb, sun, 0.0), WALL_R: _lit(amb, sun, 1.0),
        GLASS_L: (tuple(.5 * a for a in shade), glass_add), GLASS_R: (tuple(.55 * (amb[i] + sun[i] * .8) for i in range(3)), glass_add),
        ROOF: _lit(amb, sun, 1.05), METAL: _lit(amb, sun, .8), LEAF: _lit(amb, sun, .85 * p['leaf'], (3, 7, 4) if phase in ('blue', 'night') else (0, 0, 0)), SHOP: ((1.0, 1.0, 1.0), (0, 0, 0)),
        SIGN: ((1.0, 1.0, 1.0), (0, 0, 0)), TRACK: _lit(amb, sun, .9), LAMP: ((1, 1, 1), (0, 0, 0)),
    }
    return t


HAZE = {                           # (tint, amount at the top of the picture) of the thin haze that makes the far rows read as far
    'day': ((176, 206, 232), .27), 'gold': ((206, 156, 150), .31), 'blue': ((110, 92, 134), .30), 'night': ((22, 34, 72), .16),
}
SKY = {                            # (top, middle, horizon, glow) of the sky of each time of day
    'day': ((72, 132, 208), (128, 182, 228), (206, 226, 240), (255, 246, 222)),
    'gold': ((58, 88, 152), (176, 138, 152), (246, 176, 120), (255, 204, 134)),
    'blue': ((12, 24, 62), (42, 58, 112), (176, 112, 112), (255, 148, 96)),
    'night': ((4, 8, 24), (10, 18, 46), (28, 42, 82), (60, 80, 140)),
}
# how much of the lit windows' light each phase shows is decided by the scene; the pictures only hold the windows themselves.


# ----------------------------------------------------------------------------------------------------------------------- the canvas
class Cv:
    """Three pictures drawn at once, at S times the world's size: the albedo (RGB: the colour of each material, no light), the class of every pixel (L: what
    it is made of) and the id of the building that owns it (RGB: only for buildings; what hides what). All coordinates are world pixels (floats)."""

    def __init__(self, size=WORLD, s=S):
        self.s, self.w, self.h = s, size[0], size[1]
        big = (size[0] * s, size[1] * s)
        self.albedo, self.cls, self.ids = Image.new('RGB', big, (0, 0, 0)), Image.new('L', big, 0), Image.new('RGB', big, (0, 0, 0))
        self.da, self.dc, self.di = ImageDraw.Draw(self.albedo), ImageDraw.Draw(self.cls), ImageDraw.Draw(self.ids)
        self.c, self.bid = GRASS, 0

    def _p(self, pts):
        s = self.s
        return [(x * s, y * s) for x, y in pts]

    def _w(self, width):
        return max(1, round(width * self.s))

    def poly(self, pts, fill, c=None):
        p = self._p(pts)
        self.da.polygon(p, fill=tuple(fill))
        self.dc.polygon(p, fill=self.c if c is None else c)
        if self.bid:
            self.di.polygon(p, fill=id_colour(self.bid))

    def line(self, pts, fill, width=1.0, c=None):
        p, w = self._p(pts), self._w(width)
        self.da.line(p, fill=tuple(fill), width=w)
        self.dc.line(p, fill=self.c if c is None else c, width=w)
        if self.bid:
            self.di.line(p, fill=id_colour(self.bid), width=w)

    def ellipse(self, box, fill, c=None):
        (x0, y0), (x1, y1) = box
        p = [x0 * self.s, y0 * self.s, x1 * self.s, y1 * self.s]
        self.da.ellipse(p, fill=tuple(fill))
        self.dc.ellipse(p, fill=self.c if c is None else c)
        if self.bid:
            self.di.ellipse(p, fill=id_colour(self.bid))

    def rect(self, box, fill, c=None):
        (x0, y0), (x1, y1) = box
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill, c)

    def dot(self, p, fill, c=None):
        self.rect(((p[0] - .5, p[1] - .5), (p[0] + .5, p[1] + .5)), fill, c)


# ------------------------------------------------------------------------------------------------------------------------- materials
MATERIALS = {'glass': 34, 'stone': 22, 'brick': 14, 'concrete': 20, 'deco': 10}      # weights
FACADE = {                         # (bottom, top) colour pairs per material: the colour of the wall near the street and high up
    'glass': (((22, 62, 85), (83, 177, 210)), ((20, 72, 59), (70, 171, 140)), ((42, 55, 68), (138, 170, 185)), ((70, 48, 27), (187, 147, 94)),
              ((19, 42, 76), (66, 121, 181)), ((35, 68, 62), (103, 168, 143)), ((45, 61, 72), (172, 192, 200))),
    'stone': (((117, 91, 63), (226, 191, 146)), ((139, 80, 48), (229, 162, 109)), ((104, 105, 99), (204, 204, 189)), ((72, 85, 79), (155, 177, 157)),
              ((111, 94, 70), (195, 174, 126)), ((88, 76, 72), (173, 151, 138)), ((102, 99, 84), (202, 198, 161))),
    'brick': (((133, 43, 28), (215, 80, 52)), ((152, 58, 31), (231, 123, 70)), ((82, 46, 31), (155, 91, 59)), ((112, 78, 46), (195, 145, 88)),
              ((99, 70, 58), (184, 139, 119)), ((114, 91, 65), (205, 174, 126)), ((73, 60, 48), (151, 126, 102))),
    'concrete': (((74, 79, 82), (157, 165, 165)), ((100, 96, 82), (203, 195, 169)), ((64, 81, 79), (136, 163, 153)), ((98, 78, 65), (188, 152, 128)),
                 ((67, 70, 79), (145, 151, 164)), ((110, 104, 91), (208, 200, 181)), ((77, 85, 68), (156, 166, 133))),
    'deco': (((111, 89, 66), (211, 180, 140)), ((132, 83, 54), (222, 157, 112)), ((105, 100, 83), (206, 197, 168)), ((83, 83, 75), (168, 171, 153)),
             ((100, 72, 57), (188, 143, 113)), ((119, 105, 72), (215, 190, 134)), ((72, 88, 78), (153, 179, 156))),
}
ROOFS = (('slate', (65, 103, 134)), ('zinc', (116, 159, 178)), ('clay', (176, 80, 53)), ('copper', (59, 147, 116)), ('gravel', (183, 170, 148)),
         ('tar', (61, 71, 79)), ('ivory', (205, 204, 188)), ('ochre', (186, 137, 80)))
WARM = ((240, 204, 134), (242, 218, 168), (238, 180, 108), (242, 226, 192), (238, 194, 136), (230, 164, 100))


# ------------------------------------------------------------------------------------------------------------------------------ the plan
class Building:
    def __init__(self, x0, y0, x1, y1, h, material='glass', kind='city'):
        self.x0, self.y0, self.x1, self.y1, self.h = x0, y0, x1, y1, h
        self.material, self.kind = material, kind
        self.lit, self.tiers, self.style, self.podium, self.id, self.hero = .3, 1, {}, None, 0, None
        self.z0 = 0.0

    @property
    def order(self):
        return self.x1 + self.y1

    def bbox(self, h=None):
        h = self.h if h is None else h
        pts = [proj(self.x0, self.y1), proj(self.x1, self.y1), proj(self.x1, self.y0), proj(self.x0, self.y0, h), proj(self.x1, self.y0, h),
               proj(self.x0, self.y1, h), proj(self.x1, self.y1, h)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def seed(self):
        return f'{self.x0:.2f}:{self.y0:.2f}:{self.x1:.2f}:{self.y1:.2f}'


class Hero:
    """One of the three data buildings. Geometry in pixels so that every window lands on whole pixels."""

    def __init__(self, name, front, face_w, upper_w, material):
        self.name, self.front, self.face, self.upper, self.material = name, front, face_w, upper_w, material
        self.small = name == 'small'
        self.x1, self.y1 = unproj(*front)
        self.cells = face_w / HW                                     # side of the footprint, in cells
        self.x0, self.y0 = self.x1 - self.cells, self.y1 - self.cells
        if self.small:
            self.floors, self.floor_h, self.lower = SMALL_FLOORS, SMALL_FLOOR, SMALL_FLOORS
        else:
            self.floors, self.floor_h = HERO_FLOORS, HERO_FLOOR
            self.lower = 2 if name == 'codex' else HERO_LOWER
        self.top = self.floors * self.floor_h
        self.kind, self.id = 'hero', 0

    def boxes(self):
        """(x0, y0, x1, y1, z0, z1) of the wide base and of the narrower top (the small building has only the base)."""
        low = (self.x0, self.y0, self.x1, self.y1, 0, self.lower * self.floor_h)
        if self.small:
            return (low,)
        inset = (self.face - self.upper) / 2 / HW
        return low, (self.x0 + inset, self.y0 + inset, self.x1 - inset, self.y1 - inset, low[5], self.top)

    @property
    def order(self):
        return self.x1 + self.y1

    def screen_box(self, pad=3):
        """World pixels round the whole building with its crown and sign: nothing may hide it and nothing animated may cross it."""
        top = self.top + (34 if not self.small else 6)
        pts = [proj(self.x0, self.y1), proj(self.x1, self.y1), proj(self.x1, self.y0), proj(self.x0, self.y1, top), proj(self.x1, self.y1, top),
               proj(self.x1, self.y0, top), proj(self.x0, self.y0, top)]
        return (min(p[0] for p in pts) - pad, min(p[1] for p in pts) - pad, max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad)


def place_heroes():
    return {n: Hero(n, d['front'], d['face'], d['upper'], d['material']) for n, d in HEROES.items()}


def zone_height(bx, by):
    """A smooth height for the whole block, so neighbours are related like the districts of a real city."""
    wave = math.sin(bx * .55 + 1.3) + math.sin(by * .5 - .4) + .6 * math.sin((bx + by) * .35)
    return 30 + 30 * (wave + 2.2) / 4.4


def height_cap(b, heroes, reach=34):
    """How tall a building may be where it stands: the top never reaches into the sky strip (`reach` rows below the top of the world; the towers of the back
    row of the city, which Tony asked to be many and tall, use a smaller one), the very front of the city is low, the first rows in front of the elevated railway
    step up so its street stays in view, and the data buildings stay the tallest and most prominent around them."""
    yb = proj(b.x1, b.y1)[1]
    cap = min(150.0, yb - reach)
    if yb < 300:
        cap = min(cap, 100.0 + (14.0 * clamp((165 - yb) / 60, 0.0, 1.0) if reach < 34 else 0.0))   # downtown: tall; in front it is no taller than the data towers (ninety pixels and a crown)
    if yb > 290:
        cap = min(cap, 112 - (yb - 290) * .42)
    if b.y0 > RAIL_Y:
        cap = min(cap, 9.0 * (b.y0 - RAIL_Y) - 1)                    # the railway's street: low shops and gardens beside it, then the city climbs
    if b.y0 > CANAL[1]:
        cap = min(cap, 9.0 * (b.y0 - CANAL[1]) - 1)                  # and the canal stays in view from the sky
    fx, fy = proj(b.x1, b.y1)
    for hero in heroes.values():
        d = math.hypot(fx - hero.front[0], (fy - hero.front[1]) * 1.6)
        if d < 50:
            cap = min(cap, 62)
        elif d < 100:
            cap = min(cap, 80)
    return max(6.0, cap)


RAIL_Y = 25.5                                             # the elevated railway runs along this street, through the city, behind the data towers
RAIL_X = (-40, 112)                                       # from beyond the left edge of the picture to beyond its right edge
RAIL_Z = 13.2                                             # the height of the track above the street


def make_rail():
    """The viaduct, in bays of four cells, each a long thin box on a pier."""
    out = []
    for x in range(RAIL_X[0], RAIL_X[1], 4):
        b = Building(x, RAIL_Y - .28, x + 4, RAIL_Y + .28, RAIL_Z, kind='rail')
        b.z0 = RAIL_Z - 2.8
        if _out_of_view(b.bbox()):
            continue
        out.append(b)
    return out


CALM = (-10, 192, 172, 292)                               # world pixels under the clock and above the dock: a park, never a wall of windows
PARK_BLOCKS = {(7, 10), (8, 10), (9, 10), (7, 11), (8, 11), (9, 11), (10, 11)}
PLAZA_BLOCKS = set()


def _out_of_view(box):
    return box[2] < -10 or box[0] > WORLD[0] + 10 or box[3] < 30 or box[1] > WORLD[1] + 30


def _flat_bbox(b):
    pts = [proj(b.x0, b.y1), proj(b.x1, b.y1), proj(b.x1, b.y0), proj(b.x0, b.y0)]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def _inside_footprint(b, heroes):
    for h in heroes.values():
        if not (b.x1 <= h.x0 - 0.2 or b.x0 >= h.x1 + 0.2 or b.y1 <= h.y0 - 0.2 or b.y0 >= h.y1 + 0.2):
            return True
    return False


def make_plan(seed=2026):
    """The whole city as a list of Buildings (and lots, parks, promenades), back to front, each with an id, with the three heroes among them."""
    rnd = random.Random(seed)
    heroes = place_heroes()
    keep = [(h.screen_box(), h.order) for h in heroes.values()]
    out = []
    for bx in range(GMIN // 5, GMAX // 5):
        for by in range(GMIN // 5, GMAX // 5):
            gx0, gy0 = bx * 5 + 1, by * 5 + 1
            if _out_of_view(Building(gx0, gy0, gx0 + 4, gy0 + 4, 150).bbox()):
                continue
            if CANAL[0] <= gy0 < CANAL[1]:                              # the canal: water, no building (the ground painter draws it)
                continue
            # A data tower owns its entire lot. Do not put a normal building,
            # trees, or a park on the same ground beneath it.
            if any(h.x0 < gx0 + 4 and h.x1 > gx0 and h.y0 < gy0 + 4 and h.y1 > gy0 for h in heroes.values()):
                continue
            if by == int(RAIL_Y // 5) or gy0 == CANAL[1] + 1:        # along the railway's street and along the canal: a long garden, flat, so the street and the viaduct stay in view
                if not any(h.x0 < gx0 + 4 and h.x1 > gx0 and h.y0 < gy0 + 4 and h.y1 > gy0 for h in heroes.values()):    # (the five-hour building stands in one of these blocks)
                    out.append(Building(gx0, gy0, gx0 + 4, gy0 + 4, 0, kind='promenade'))
                continue
            cx, cy = proj(gx0 + 2, gy0 + 2)
            if (bx, by) in PARK_BLOCKS:
                out.append(Building(gx0, gy0, gx0 + 4, gy0 + 4, 0, kind='park'))
                continue
            if CALM[0] < cx < CALM[2] and CALM[1] < cy < CALM[3]:
                out.append(Building(gx0, gy0, gx0 + 4, gy0 + 4, 0, kind='plaza' if (bx * 7 + by * 3) % 5 == 0 else 'park'))
                continue
            if (bx, by) in PLAZA_BLOCKS:
                out.append(Building(gx0, gy0, gx0 + 4, gy0 + 4, 0, kind='plaza'))
                continue
            cells = [(gx0, gy0, gx0 + 4, gy0 + 4)]
            while len(cells) < 4 and rnd.random() < .6:                  # most blocks are one or two big buildings, some are four
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
            zone = zone_height(bx, by)
            back = clamp((175 - cy) / 120, 0.0, 1.0)                     # 1 at the very back of the city, 0 from the middle of the picture forwards: taller and denser there
            for (x0, y0, x1, y1) in cells:
                material = rnd.choices(list(MATERIALS), list(MATERIALS.values()))[0]
                height = zone * rnd.choice((.6, .8, 1.0, 1.15, 1.4, 1.7)) * (2.1 if rnd.random() < .34 else 1) + rnd.uniform(-3, 5)
                b = Building(x0, y0, x1, y1, max(10.0, min(150.0, height)), material)
                b.lit, b.tiers = rnd.choice((.16, .24, .34, .44, .54, .64)), (rnd.choice((1, 1, 2, 2, 3)) if height > 46 else 1)
                b.h = min(b.h, height_cap(b, heroes))
                if b.h > 78 and ((x1 - x0) >= 3 or (y1 - y0) >= 3):         # a skyscraper is slender: it stands on a podium
                    b.podium = (x0, y0, x1, y1, rnd.choice((7.0, 10.0, 13.0)))
                    sw, sd = min(x1 - x0, rnd.choice((2, 2, 3))), min(y1 - y0, rnd.choice((2, 2, 3)))
                    b.x0 += rnd.randint(0, (x1 - x0) - sw)
                    b.y0 += rnd.randint(0, (y1 - y0) - sd)
                    b.x1, b.y1 = b.x0 + sw, b.y0 + sd
                if b.h < 14:
                    b.tiers = 1
                b.style = style_for(rnd, material, b.h)
                if back > .02:                                                  # the back of the city climbs: taller towers with the crowns and setbacks of tall ones
                    raise_back(b, (x0, y0, x1, y1), height, back, heroes, seed)
                if _out_of_view(b.bbox()):
                    continue
                out.append(b)
    # nothing may stand in front of a data building and hide it (nor on its own ground): it becomes a lawn, or a plaza
    for b in out:
        x0, y0, x1, y1 = b.bbox() if b.kind == 'city' else _flat_bbox(b)
        for (kx0, ky0, kx1, ky1), order in keep:
            overlaps = not (x1 < kx0 or x0 > kx1 or y1 < ky0 or y0 > ky1)
            if overlaps and (b.order > order - 3 or (b.kind == 'city' and _inside_footprint(b, heroes))):
                b.kind, b.h, b.tiers, b.podium = ('plaza' if int(b.x0 + b.y0) % 2 else 'lot'), .6, 1, None
    for b in out:
        if b.kind == 'city':
            b.style = architecture(b)
    out = merge_blocks(out, heroes, seed)
    out = place_landmarks(out, heroes, seed)
    assign_archetypes(out, heroes, seed)
    repair_central_block(out, seed)
    place_civic_blocks(out, seed)
    # Merging lots or choosing a landmark can enlarge its silhouette after the
    # first visibility pass. Check again against each of the data towers.
    for b in out:
        if b.kind != 'city':
            continue
        x0, y0, x1, y1 = b.bbox()
        for (kx0, ky0, kx1, ky1), order in keep:
            if b.order > order - 3 and not (x1 < kx0 or x0 > kx1 or y1 < ky0 or y0 > ky1):
                b.kind, b.h, b.tiers, b.podium = 'lot', .6, 1, None
                break
    # Leave enough unlit wall between windows for neighbouring silhouettes to read at night.
    for b in out:
        if b.kind == 'city':
            b.lit *= .75
    choose_cranes(out, seed)
    everything = out + list(heroes.values()) + make_rail()
    everything.sort(key=lambda b: (b.order, b.x0 + b.y0))
    for i, b in enumerate(everything, 1):
        b.id = i
    return everything, heroes


def raise_back(b, cell, height, back, heroes, seed):
    """Make a building of the back rows taller (the random numbers of the plan are untouched: this has its own, from the building's place), give it a slender
    shaft on a podium when it is a big plot, setbacks, and the crown of a tall building."""
    x0, y0, x1, y1 = cell
    own = random.Random(f'back:{x0}:{y0}:{x1}:{y1}:{seed}')
    want = height * (1 + .8 * back) * (1.5 if own.random() < .3 + .3 * back else 1)
    new = min(150.0, max(b.h, want), height_cap(b, heroes, reach=18))
    if new <= b.h + 2:
        return
    b.h = new
    if b.h > 46 and b.tiers == 1:
        b.tiers = own.choice((1, 2, 2, 3))
    if b.h > 78 and not b.podium and ((x1 - x0) >= 3 or (y1 - y0) >= 3):
        b.podium = (x0, y0, x1, y1, own.choice((7.0, 10.0, 13.0)))
        sw, sd = min(x1 - x0, own.choice((2, 2, 3))), min(y1 - y0, own.choice((2, 2, 3)))
        b.x0 += own.randint(0, (x1 - x0) - sw)
        b.y0 += own.randint(0, (y1 - y0) - sd)
        b.x1, b.y1 = b.x0 + sw, b.y0 + sd
    if b.style.get('crown') in ('flat', 'slant', 'mansard', 'terrace', 'gable', 'sawtooth', 'roof_garden', 'roof_deck', 'penthouse') and b.h > 60:
        b.style['crown'] = crown_for(own, b.material, b.h)


def style_for(rnd, material, height):
    """How one building's facade looks: window rhythm and size, which kinds of light, piers, spandrels, blade signs."""
    return {
        'pitch': rnd.choice((2.6, 3.0, 3.4, 4.0)), 'win_w': rnd.uniform(.5, .72), 'win_h': rnd.uniform(.42, .62),
        'piers': material in ('stone', 'deco', 'brick') or rnd.random() < .35, 'bands': rnd.random() < .6,
        'office': rnd.random() < .5 and material in ('glass', 'concrete'), 'neon': height < 70 and rnd.random() < .4,
        'tone': rnd.uniform(-.14, .16), 'escape': material == 'brick' and rnd.random() < .7, 'crown': crown_for(rnd, material, height),
        'board': 20 < height < 90 and rnd.random() < .24,
    }


def crown_for(rnd, material, height):
    if material == 'deco' and height > 60:
        return 'spire'
    if height > 70:
        return rnd.choice(('spire', 'spire', 'mast', 'mast', 'pyramid', 'dome', 'twin', 'lantern', 'slant'))
    if height > 40:
        return rnd.choice(('flat', 'slant', 'mansard', 'dome', 'lantern', 'pyramid', 'twin', 'terrace', 'terrace'))
    return rnd.choice(('flat', 'mansard', 'slant', 'terrace', 'terrace', 'slant'))


def architecture(b):
    """Choose a coherent facade and roof for one building."""
    rnd = random.Random('architecture:' + b.seed())
    style = dict(b.style)
    style['palette'] = rnd.choice(FACADE[b.material])
    style['roof_material'], style['roof_colour'] = rnd.choice(ROOFS)
    style['setback_scale'] = rnd.choice((.65, 1.0, 1.0, 1.45))
    style['setback_side'] = rnd.choice(('all', 'all', 'near', 'far'))
    kinds = {'glass': ('curtain', 'vertical', 'ribbon'), 'stone': ('classic', 'vertical', 'balcony'), 'brick': ('classic', 'balcony', 'warehouse'),
             'concrete': ('ribbon', 'balcony', 'classic'), 'deco': ('vertical', 'classic', 'balcony')}
    facade = rnd.choice(kinds[b.material])
    style['facade'] = facade
    if facade == 'curtain':
        style.update(pitch=2.6, win_w=.92, win_h=.75, piers=False, bands=True)
    elif facade == 'vertical':
        style.update(pitch=3.6, win_w=.47, win_h=.75, piers=True, bands=False)
    elif facade == 'ribbon':
        style.update(pitch=4.0, win_w=.91, win_h=.44, piers=False, bands=True)
    elif facade == 'balcony':
        style.update(pitch=3.4, win_w=.66, win_h=.60, piers=True, bands=False)
    elif facade == 'warehouse':
        style.update(pitch=4.2, win_w=.84, win_h=.48, piers=True, bands=True)
    detail = random.Random('facade-detail:' + b.seed())
    choice = detail.random()
    broad = b.x1 - b.x0 >= 4 and b.y1 - b.y0 >= 4
    if b.material in ('glass', 'concrete') and b.h >= 55 and (choice < .42 or (broad and choice > .70)):
        style['facade'] = 'braced'
    elif b.material in ('brick', 'stone') and b.h >= 28 and choice < .27:
        style['facade'] = 'bay'
    if style.get('crown') == 'terrace':
        style['crown'] = rnd.choice(('terrace', 'roof_garden', 'roof_garden', 'penthouse', 'roof_deck'))
    elif style.get('crown') == 'slant':
        style['crown'] = rnd.choice(('slant', 'slant', 'gable', 'sawtooth'))
    style.update(facade_extras(random.Random('facade-extras:' + b.seed()), b.material, b.h))
    return style



# ------------------------------------------------------------------------------------------------------------------------------ painting
class Rec:
    """What the painters note down for the scene: where the lights of the windows are, which window belongs to which batch, where things can be animated."""

    def __init__(self):
        self.wins = []          # lit-window candidates: (quad, colour, batch, building id, blind)
        self.poke = []          # every window as (x, y, w, h, building id) for the touch
        self.beacons = []       # (x, y, building id): a red light on a mast
        self.vents = []         # (x, y, building id): steam from a roof
        self.screens = []       # (quad, building id): a lit sign the scene animates
        self.fountains = []     # (x, y)
        self.lamps = []         # (x, y) street lamp bulbs
        self.manholes = []      # (x, y)
        self.poles = []         # (x, y, gx, gy): traffic-light poles
        self.trees = []         # (x, y, r) street and park trees, for the wind
        self.paths = []         # ((gx, gy), (gx, gy)) walks in the parks and plazas
        self.covered = []       # (gx0, gy0, gx1, gy1): street cells that a park or a data building has taken over (no traffic, no walkers there)
        self.regions = []       # the open grounds (parks, plazas, avenues) with what stands on them


def faces_base(x0, y0, x1, y1):
    """Ground endpoints of the left face (towards +y) and of the right face (towards +x), each from its left end to its right end."""
    return (proj(x0, y1), proj(x1, y1)), (proj(x1, y1), proj(x1, y0))


def box_faces(x0, y0, x1, y1, z0, z1):
    (la, lb), (ra, rb) = faces_base(x0, y0, x1, y1)
    left = [(la[0], la[1] - z0), (lb[0], lb[1] - z0), (lb[0], lb[1] - z1), (la[0], la[1] - z1)]
    right = [(ra[0], ra[1] - z0), (rb[0], rb[1] - z0), (rb[0], rb[1] - z1), (ra[0], ra[1] - z1)]
    roof = [proj(x0, y0, z1), proj(x1, y0, z1), proj(x1, y1, z1), proj(x0, y1, z1)]
    return left, right, roof


def lit_window_colour(rnd, colour):
    """A lit window's colour: mostly warm tungsten, some cool LED, a few television blues and fluorescent greens."""
    r = rnd.random()
    if r < .68:
        base = rnd.choice(WARM)
    elif r < .82:
        base = (206, 224, 250)
    elif r < .89:
        base = (122, 156, 226)
    elif r < .93:
        base = (196, 232, 206)
    elif r < .96:
        base = (255, 150, 120)
    elif r < .98:
        base = (230, 140, 220)
    else:
        base = (120, 226, 214)
    return mix(base, colour, rnd.uniform(0, .30))


def paint_face(cv, rec, b, base, z0, z1, floor_h, side, style, rnd, windows=True, shop=False):
    """One face of a box, floor by floor: the colour of the wall (darker near the street, lighter high up), uneven grime in three strips, spandrel bands,
    ledges, piers, sills, windows (all dark: the lit ones are separate pictures), balconies, a fire escape on some brick, and on the ground floor a lit
    shop front with a sign. The light of the sun and the sky is added later, per class."""
    a, bb = base
    mat = b.material
    bottom, top = style.get('palette', FACADE[mat][0])
    floors = max(1, round((z1 - z0) / floor_h))
    fh = (z1 - z0) / floors
    width = abs(bb[0] - a[0])
    columns = max(1, round(width / style.get('pitch', 3.0)))
    key = abs(round(a[0] * 7 + a[1] * 11 + z1 * 3))
    balconies = windows and width >= 8 and floors >= 4 and (style.get('facade') == 'balcony' or (mat in ('stone', 'brick', 'concrete') and key % 5 == 0))
    office = {f for f in range(floors) if style.get('office') and rnd.random() < .12}
    wall, glass = (WALL_L, GLASS_L) if side == 0 else (WALL_R, GLASS_R)
    tone = style.get('tone', 0.0)
    cv.c = wall
    for f in range(floors):
        za, zb = z0 + f * fh, z0 + (f + 1) * fh
        u = (f + .5) / floors
        colour = mix(bottom, top, u ** .8)
        colour = mix(colour, (255, 255, 255) if tone > 0 else (0, 0, 0), abs(tone))
        colour = mix(colour, (rnd.randint(0, 40), rnd.randint(0, 40), rnd.randint(0, 40)), .05)
        if z0 == 0 and f == 0:
            colour = mix(colour, (0, 0, 8), .28)                                          # darker where the street is
        for k in range(3):                                                                # uneven grime across the floor
            p0, p1 = lerp(a, bb, k / 3), lerp(a, bb, (k + 1) / 3 + .002)
            grime = rnd.uniform(-.07, .07)
            strip = mix(colour, (255, 255, 255) if grime > 0 else (0, 0, 0), abs(grime))
            cv.poly([(p0[0], p0[1] - za), (p1[0], p1[1] - za), (p1[0], p1[1] - zb), (p0[0], p0[1] - zb)], strip, wall)
        # A few individual buildings have a recessed end bay or an exposed
        # structural band. These are materials in the facade, not extra lights.
        feature = style.get('facade_feature')
        if windows and f > 0 and width >= 8 and floors >= 4 and feature == 'end_bay':
            u0, u1 = ((.04, .19) if side == 0 else (.81, .96))
            p0, p1 = lerp(a, bb, u0), lerp(a, bb, u1)
            cv.poly([(p0[0], p0[1] - za), (p1[0], p1[1] - za),
                     (p1[0], p1[1] - zb), (p0[0], p0[1] - zb)], mix(colour, (26, 38, 48), .28), wall)
        elif windows and f > 0 and width >= 9 and floors >= 5 and feature == 'setback_band' and f % 4 == 1:
            p0, p1 = lerp(a, bb, .08), lerp(a, bb, .92)
            cv.poly([(p0[0], p0[1] - za), (p1[0], p1[1] - za),
                     (p1[0], p1[1] - za - fh * .36), (p0[0], p0[1] - za - fh * .36)],
                    mix(colour, (38, 50, 56), .36), wall)
        if windows and style.get('facade') == 'bay' and width >= 8:                       # faceted, projecting window bays
            for c in range(columns):
                for lo, hi, target, amount in ((.06, .22, (5, 12, 20), .32), (.78, .94, (244, 222, 192), .30)):
                    p0, p1 = lerp(a, bb, (c + lo) / columns), lerp(a, bb, (c + hi) / columns)
                    cv.poly([(p0[0], p0[1] - za), (p1[0], p1[1] - za), (p1[0], p1[1] - zb), (p0[0], p0[1] - zb)], mix(colour, target, amount), wall)
        if z0 == 0 and f == 0 and style.get('pilotis') and windows and width >= 6:        # a ground floor of pillars with the dark of the recess behind them
            cv.poly([(a[0], a[1] - za), (bb[0], bb[1] - za), (bb[0], bb[1] - zb + .6), (a[0], a[1] - zb + .6)], (18, 20, 26), wall)
            for k in range(0, columns + 1):
                p = lerp(a, bb, k / columns)
                cv.line([(p[0], p[1] - za), (p[0], p[1] - zb + .6)], mix(colour, (255, 255, 255), .25), .8, wall)
            continue
        if style.get('bands'):                                                            # a spandrel band under the windows
            cv.poly([(a[0], a[1] - za), (bb[0], bb[1] - za), (bb[0], bb[1] - za - fh * .2), (a[0], a[1] - za - fh * .2)], mix(colour, (0, 0, 10), .22), wall)
        cv.line([(a[0], a[1] - zb), (bb[0], bb[1] - zb)], mix(colour, (255, 255, 255), .15), .5, wall)
        if windows and mat == 'brick' and width >= 10 and f > 0:                          # mortar courses between the windows
            for k in range(3):
                start = (k + (.12 if f % 2 else .24)) / 3
                p0, p1 = lerp(a, bb, start), lerp(a, bb, min(1, start + .16))
                cv.line([(p0[0], p0[1] - za - fh * .17), (p1[0], p1[1] - za - fh * .17)], mix(colour, (238, 199, 157), .34), .5, wall)
        if not windows or width < 3:
            continue
        if windows and style.get('band') and f == max(1, floors // 2) and floors >= 6 and width >= 6:              # a coloured spandrel band across the face
            cv.poly([(a[0], a[1] - za), (bb[0], bb[1] - za), (bb[0], bb[1] - za - fh * .34), (a[0], a[1] - za - fh * .34)], mix(colour, style['band'], .7), wall)
        for c in range(columns):
            rhythm = style.get('rhythm')
            if rhythm == 'wide' and columns >= 4 and c % 3 == 1:
                continue                                                                          # a wide bay: this window is part of its neighbour
            span = 1.0 + (1.0 if rhythm == 'wide' and columns >= 4 and c % 3 == 0 and c + 1 < columns else 0.0)
            shift = style.get('stagger', 0) * (1 if f % 2 else -1)
            u0 = max(.01, (c + .5 + shift - style.get('win_w', .6) / 2) / columns)
            u1 = min(.99, (c + .5 + shift + (span - 1) + style.get('win_w', .6) / 2) / columns)
            v0, v1 = za + fh * (.5 - style.get('win_h', .5) / 2 + .06), za + fh * (.5 + style.get('win_h', .5) / 2 + .06)
            pa, pb = lerp(a, bb, u0), lerp(a, bb, u1)
            quad = [(pa[0], pa[1] - v0), (pb[0], pb[1] - v0), (pb[0], pb[1] - v1), (pa[0], pa[1] - v1)]
            if z0 == 0 and f == 0 and shop:
                if rnd.random() < .72:
                    cv.poly(quad, mix((255, 188, 108), colour, rnd.uniform(0, .35)), SHOP)
                    if width >= 8 and c % 2 == 0 and 'facade' in style:
                        canopy = [(pa[0], pa[1] - v1), (pb[0], pb[1] - v1), (pb[0] + .35, pb[1] - v1 + 1.0), (pa[0] + .35, pa[1] - v1 + 1.0)]
                        stripes = style.get('awning')
                        if stripes:                                                                  # a striped awning in two colours
                            for k in range(4):
                                t0_, t1_ = k / 4, (k + 1) / 4
                                cv.poly([lerp(canopy[0], canopy[1], t0_), lerp(canopy[0], canopy[1], t1_), lerp(canopy[3], canopy[2], t1_), lerp(canopy[3], canopy[2], t0_)], stripes[k % 2], wall)
                        else:
                            cv.poly(canopy, (168, 72, 55) if key % 2 else (77, 120, 115), wall)
                        cv.line([canopy[3], canopy[2]], (228, 209, 169), .5, wall)
                continue
            if style.get('shutters') and width > 6:                                           # shutters of their own colour on both sides of the window
                gap = .1 / columns
                for lo_, hi_ in ((u0 - gap, u0), (u1, u1 + gap)):
                    qa, qb = lerp(a, bb, lo_), lerp(a, bb, hi_)
                    cv.poly([(qa[0], qa[1] - v0), (qb[0], qb[1] - v0), (qb[0], qb[1] - v1), (qa[0], qa[1] - v1)], mix(style['shutters'], colour, .2), wall)
            if style.get('panel') and f > 0:                                                  # a coloured panel under the window, in turns
                qa, qb = lerp(a, bb, u0 - .02), lerp(a, bb, u1 + .02)
                cv.poly([(qa[0], qa[1] - za - fh * .02), (qb[0], qb[1] - za - fh * .02), (qb[0], qb[1] - v0 + .3), (qa[0], qa[1] - v0 + .3)],
                        mix(colour, style['panel'], .75 if c % 2 == 0 else .4), wall)
            dark = mix(colour, (8, 14, 28), .62 if mat == 'glass' else .5)
            cv.poly(quad, dark, glass)
            if style.get('arched') and width > 5:                                             # a round-headed window
                m = lerp(pa, pb, .5)
                r = abs(pb[0] - pa[0]) / 2
                cv.ellipse(((m[0] - r, m[1] - v1 - r * .8), (m[0] + r, m[1] - v1 + .4)), dark, glass)
            cx, cy = sum(p[0] for p in quad) / 4, sum(p[1] for p in quad) / 4
            rec.poke.append((cx, cy, abs(pb[0] - pa[0]), abs(v1 - v0), b.id))
            if f in office or rnd.random() < b.lit:
                glow = mix((205, 226, 255), colour, rnd.uniform(0, .22)) if f in office else lit_window_colour(rnd, colour)
                rec.wins.append((quad, glow, rnd.randrange(BUCKETS), b.id, rnd.random() < .12 and f not in office))
            if mat == 'glass' and width > 7 and (f + c * 3) % 7 == 0:                      # a small reflected strip, kept to one edge
                p = lerp(pa, pb, .16)
                cv.line([(p[0], p[1] - v0 - .15), (p[0], p[1] - v1 + .15)], mix(colour, (174, 204, 220), .55), .5, wall)
            if mat != 'glass' and width > 5:                                              # a sill under each window
                cv.line([(pa[0], pa[1] - v0 + .2), (pb[0], pb[1] - v0 + .2)], mix(colour, (255, 255, 255), .22), .25, wall)
            if mat in ('brick', 'concrete') and width >= 10 and f > 0 and (f + 3 * c + key) % 9 == 0:   # a small air conditioner under a window
                px, py = lerp(pa, pb, .5)
                py -= v0 - .8
                cv.rect(((px - 1.2, py - .7), (px + 1.2, py + .5)), (177, 185, 179), wall)
                cv.line([(px - .6, py), (px + .6, py)], (88, 104, 102), .25, wall)
        if style.get('brise') and width > 6:                                              # a sunshade along the head of every window
            cv.line([(a[0], a[1] - zb + .4), (bb[0], bb[1] - zb + .4)], mix(colour, style.get('trim', (230, 236, 240)), .5), .5, wall)
        if style.get('piers') and width > 5:                                              # vertical piers between the columns
            for c in range(1, columns):
                p = lerp(a, bb, c / columns)
                cv.line([(p[0], p[1] - za), (p[0], p[1] - zb)], mix(colour, (255, 255, 255), .10), .25, wall)
        elif style.get('rhythm') == 'pairs' and width > 6:                                  # windows in pairs, a broader pier between the pairs
            for c in range(2, columns, 2):
                p = lerp(a, bb, c / columns)
                cv.line([(p[0], p[1] - za), (p[0], p[1] - zb)], mix(colour, (255, 255, 255), .14), .6, wall)
        if balconies and f > 0:                                                           # shallow balcony slabs and railings
            for c in range(0, columns - 1, 2):
                pa, pb = lerp(a, bb, (c + .12) / columns), lerp(a, bb, (c + 1.65) / columns)
                slab = [(pa[0], pa[1] - za - .2), (pb[0], pb[1] - za - .2), (pb[0], pb[1] - za + .7), (pa[0], pa[1] - za + .7)]
                cv.poly(slab, mix(colour, (8, 12, 20), .53), wall)
                cv.line([slab[0], slab[1]], mix(colour, (225, 219, 205), .5), .25, wall)
                cv.line([(pa[0], pa[1] - za - 1.3), (pb[0], pb[1] - za - 1.3)], mix(colour, (199, 205, 201), .43), .25, wall)
                if (f + c + key) % 4 == 0:
                    px, py = lerp(slab[0], slab[1], .5)
                    cv.line([(px - 1, py - .35), (px + 1, py - .35)], (188, 151, 103), .5, wall)
                    cv.line([(px - .7, py - .8), (px + .7, py - .8)], (103, 167, 82), .5, LEAF)
        if width > 8 and f > 0 and (f % (4 if mat in ('stone', 'deco') else 6)) == 0:    # occasional projecting courses
            cv.line([(a[0], a[1] - za - .18), (bb[0], bb[1] - za - .18)], mix(colour, (230, 219, 200), .25), .5, wall)
        if z0 == 0 and f == 0 and shop and width > 5 and rnd.random() < .65:              # a sign over the shop front
            pa = lerp(a, bb, rnd.uniform(.12, .55))
            pb = lerp(pa, bb, rnd.uniform(.18, .3))
            sign = rnd.choice(((220, 70, 60), (70, 140, 230), (80, 200, 120), (240, 240, 250), (240, 170, 60), (200, 80, 200)))
            cv.poly([(pa[0], pa[1] - fh * .84), (pb[0], pb[1] - fh * .84), (pb[0], pb[1] - fh * .97), (pa[0], pa[1] - fh * .97)], sign, SIGN)
    cv.c = wall
    if windows and style.get('streak') is not None and width >= 8 and floors >= 5:         # the sky's reflection slides across a glass face
        u = style['streak']
        p0, p1 = lerp(a, bb, u), lerp(a, bb, min(1, u + .16))
        lift = (z1 - z0) * .8
        q0, q1 = lerp(a, bb, min(1, u + .22)), lerp(a, bb, min(1, u + .22 + .16))
        cv.poly([(p0[0], p0[1] - z0), (p1[0], p1[1] - z0), (q1[0], q1[1] - z0 - lift), (q0[0], q0[1] - z0 - lift)], mix(mix(bottom, top, .6), (214, 232, 240), .16), glass)
    if windows and style.get('banner') and width >= 8 and floors >= 6:                       # banners hang down a grand front
        for u in (.3, .7):
            p = lerp(a, bb, u)
            cv.poly([(p[0] - .45, p[1] - z0 - fh * 1.2), (p[0] + .45, p[1] - z0 - fh * 1.2), (p[0] + .45, p[1] - z0 - fh * 4.4), (p[0] - .45, p[1] - z0 - fh * 4.4)], style['banner'], wall)
    if windows and style.get('facade') == 'vertical' and width > 8:                       # tall continuous fins
        for c in range(columns + 1):
            p = lerp(a, bb, c / columns)
            cv.line([(p[0], p[1] - z0), (p[0], p[1] - z1)], mix(mix(bottom, top, .5), (197, 207, 213), .55 if side else .35), .65, METAL)
    if windows and style.get('facade') == 'curtain' and width > 7 and floors >= 4:
        # A continuous glass skin reads differently from masonry windows:
        # fine mullions and a cool, asymmetric reflection run up the tower.
        for c in range(0, columns + 1, 2):
            p = lerp(a, bb, c / columns)
            cv.line([(p[0], p[1] - z0), (p[0], p[1] - z1)],
                    mix(mix(bottom, top, .55), (190, 211, 220), .48), .45, METAL)
        if key % 2:
            p = lerp(a, bb, .23 if side else .72)
            cv.line([(p[0], p[1] - z0 - fh), (p[0], p[1] - z1 + fh)],
                    mix(top, (222, 238, 244), .32), .65, GLASS_L if side == 0 else GLASS_R)
    if windows and style.get('facade') == 'braced' and width >= 10 and floors >= 6:       # an exposed steel frame spans several floors
        p0, p1 = lerp(a, bb, .10), lerp(a, bb, .90)
        for first in range(0, floors, 4):
            low, high = z0 + first * fh, z0 + min(first + 4, floors) * fh
            if high - low < fh * 2:
                continue
            for line in ([(p0[0], p0[1] - low), (p1[0], p1[1] - high)], [(p1[0], p1[1] - low), (p0[0], p0[1] - high)]):
                cv.line(line, (24, 35, 43), 1.25, METAL)
                cv.line(line, (157, 185, 184) if side else (105, 139, 144), .5, METAL)
    if style.get('escape') and mat == 'brick' and floors >= 3 and width > 5:              # a fire escape zig-zags up the face
        dark = (24, 26, 32)
        x_a, x_b = rnd.uniform(.15, .35), rnd.uniform(.55, .8)
        for f in range(1, floors):
            za, zb = z0 + (f - 0.1) * fh, z0 + (f + 0.9) * fh
            p0, p1 = lerp(a, bb, x_a), lerp(a, bb, x_b)
            cv.line([(p0[0], p0[1] - za), (p1[0], p1[1] - za)], dark, .5, METAL)
            cv.line([(p1[0], p1[1] - za), (p0[0], p0[1] - zb)] if f % 2 else [(p0[0], p0[1] - za), (p1[0], p1[1] - zb)], dark, .25, METAL)


def paint_roof(cv, roof_pts, mat, rnd, tone=0.0, style=None):
    """Roofing catches the sky differently from the walls: material, seams and rims separate neighbouring buildings."""
    style = style or {}
    top = style.get('palette', FACADE[mat][0])[1]
    roofing = style.get('roof_material', 'slate')
    if 'roof_colour' in style:
        base = mix(style['roof_colour'], top, .12)
        base = mix(base, (255, 255, 255) if tone > 0 else (0, 0, 0), abs(tone) * .35)
    else:
        base = mix(mix(top, (136, 152, 178), .36), (255, 255, 255) if tone > 0 else (0, 0, 0), abs(tone) * .6)
        base = mix(base, (0, 0, 0), .16)
    cv.poly(roof_pts, base, ROOF)
    if roofing not in ('gravel', 'tar') and max(p[0] for p in roof_pts) - min(p[0] for p in roof_pts) >= 10:
        for fraction in ((.18, .36, .54, .72, .90) if roofing == 'clay' else (.28, .55, .82)):
            cv.line([lerp(roof_pts[3], roof_pts[2], fraction), lerp(roof_pts[0], roof_pts[1], fraction)], mix(base, (37, 44, 56), .30), .5, ROOF)
        if roofing in ('clay', 'ivory', 'ochre'):
            for fraction in (.24, .50, .76):
                cv.line([lerp(roof_pts[3], roof_pts[0], fraction), lerp(roof_pts[2], roof_pts[1], fraction)], mix(base, (37, 44, 56), .23), .5, ROOF)
    cv.line([roof_pts[3], roof_pts[2], roof_pts[1]], mix(base, (255, 232, 206), .55), .5, ROOF)
    cv.line([roof_pts[3], roof_pts[0], roof_pts[1]], mix(base, (10, 14, 24), .45), .5, ROOF)
    xs, ys = [p[0] for p in roof_pts], [p[1] for p in roof_pts]
    for _ in range(max(2, int((max(xs) - min(xs)) * (max(ys) - min(ys)) / 9))):          # gravel and tar: a speckle on the roof
        u, v = rnd.random(), rnd.random()
        p = lerp(lerp(roof_pts[3], roof_pts[2], u), lerp(roof_pts[0], roof_pts[1], u), v)
        cv.dot(p, mix(base, (28, 30, 40) if rnd.random() < .5 else (220, 220, 226), .2), ROOF)


def paint_box(cv, rec, b, x0, y0, x1, y1, z0, z1, material, rnd, windows=True, shop=False, floor_h=FLOOR, style=None):
    _, _, roof_pts = box_faces(x0, y0, x1, y1, z0, z1)
    (la, lb), (ra, rb) = faces_base(x0, y0, x1, y1)
    style = style or {}
    bottom, top = style.get('palette', FACADE[material][0])
    paint_face(cv, rec, b, (la, lb), z0, z1, floor_h, 0, style, rnd, windows, shop)
    paint_face(cv, rec, b, (ra, rb), z0, z1, floor_h, 1, style, rnd, windows, shop)
    if b.kind == 'city' and z1 - z0 > 12:
        # Subtle metal edges keep adjoining facades apart even under moonlight.
        trim = mix(style.get('trim', top), (180, 204, 210), .22)
        cv.line([(la[0], la[1] - z0), (la[0], la[1] - z1)], mix(trim, (25, 35, 48), .24), .65, METAL)
        cv.line([(rb[0], rb[1] - z0), (rb[0], rb[1] - z1)], trim, .65, METAL)
    cv.line([(ra[0], ra[1] - z0), (ra[0], ra[1] - z1)], mix(top, (255, 190, 140), .45), .5, WALL_R)
    if windows and style.get('cornice') and z1 - z0 > 8:                                  # a projecting cornice in the trim colour, with its shadow under it
        thick = style['cornice']
        trim = style.get('trim', mix(top, (255, 255, 255), .3))
        for (a, c), cls in (((la, lb), WALL_L), ((ra, rb), WALL_R)):
            cv.poly([(a[0], a[1] - z1 + thick), (c[0], c[1] - z1 + thick), (c[0], c[1] - z1), (a[0], a[1] - z1)], trim, cls)
            cv.line([(a[0], a[1] - z1 + thick + .3), (c[0], c[1] - z1 + thick + .3)], mix(bottom, (0, 0, 8), .5), .5, cls)
    elif windows and z1 - z0 > 12:                                                        # a cornice at the top of the wall
        for (a, c), shade, cls in (((la, lb), .0, WALL_L), ((ra, rb), .12, WALL_R)):
            cv.poly([(a[0], a[1] - z1 + .8), (c[0], c[1] - z1 + .8), (c[0], c[1] - z1), (a[0], a[1] - z1)], mix(top, (255, 226, 196), .22 - shade), cls)
            cv.poly([(a[0], a[1] - z1 + 1.8), (c[0], c[1] - z1 + 1.8), (c[0], c[1] - z1 + .8), (a[0], a[1] - z1 + .8)], mix(bottom, (0, 0, 8), .45), cls)
    paint_roof(cv, roof_pts, material, rnd, style.get('tone', 0.0), style)
    edge = mix(bottom, (0, 0, 0), .55)                                                    # the dark outline that parts it from its neighbours
    for (a, c), cls in (((la, lb), WALL_L), ((ra, rb), WALL_R)):
        cv.line([(a[0], a[1] - z0), (a[0], a[1] - z1)], edge, .5, cls)
        cv.line([(c[0], c[1] - z0), (c[0], c[1] - z1)], edge, .5, cls)
        cv.line([(a[0], a[1] - z0), (c[0], c[1] - z0)], edge, 1.0, cls)


def red_light(cv, rec, b, px, py):
    cv.ellipse(((px - .8, py - .8), (px + .8, py + .8)), (255, 74, 74), SIGN)
    rec.beacons.append((px, py, b.id))


def static_board(cv, rec, b, cx, cy, z, plane, rnd, width=1.6, height=6):
    """An advertising board on a roof, in the city's projection: a dark frame on two posts and three bands of colour the scene can animate."""
    half = width / 2
    if plane == 'right':
        (lx, ly), (rx, ry) = proj(cx, cy + half, z), proj(cx, cy - half, z)
    else:
        (lx, ly), (rx, ry) = proj(cx - half, cy, z), proj(cx + half, cy, z)
    lift = 3
    cv.poly([(lx, ly - lift), (rx, ry - lift), (rx, ry - lift - height), (lx, ly - lift - height)], (22, 24, 30), METAL)
    colours = rnd.choice(((240, 90, 70), (80, 160, 255), (250, 200, 70), (120, 220, 150), (240, 240, 250)))
    for k in range(3):
        u0, u1 = .1 + k * .27, .1 + k * .27 + .22
        a, c = lerp((lx, ly), (rx, ry), u0), lerp((lx, ly), (rx, ry), u1)
        quad = [(a[0], a[1] - lift - height * .15), (c[0], c[1] - lift - height * .15), (c[0], c[1] - lift - height * .85), (a[0], a[1] - lift - height * .85)]
        cv.poly(quad, mix(colours, (30, 30, 60), .15 * k), SIGN)
        rec.screens.append((quad, mix(colours, (30, 30, 60), .15 * k), b.id))
    for k in (.2, .8):
        p = lerp((lx, ly), (rx, ry), k)
        cv.line([(p[0], p[1]), (p[0], p[1] - lift)], (90, 92, 100), .5, METAL)


def roof_equipment(cv, rec, b, cell, z):
    """Small, perspective-correct roof plant, laid out independently for each building."""
    x0, y0, x1, y1 = cell
    width, depth = x1 - x0, y1 - y0
    if min(width, depth) < 1.8:
        return
    detail = random.Random(f'{x0:.2f}:{y0:.2f}:{z:.2f}')
    if detail.random() > b.style.get('gear', 1.0):                                       # some roofs are clean: a garden, a terrace, a tank, nothing
        return
    positions = detail.sample(((.23, .27), (.75, .72), (.22, .70), (.72, .25)), detail.choice((1, 1, 2, 3)))
    for index, (u, v) in enumerate(positions):                                            # air handlers along the edges, with their fans and slats
        cx, cy = x0 + width * u, y0 + depth * v
        double_fan = width >= 3 and depth >= 3 and (round(x0 * 7 + y0 * 11) + index) % 3 == 0
        hx, hy = (min(.66, width * .21) if double_fan else min(.48, width * .15)), min(.38, depth * .13)
        h = detail.choice((1.1, 1.4, 1.8))
        left, right, roof = box_faces(cx - hx, cy - hy, cx + hx, cy + hy, z, z + h)
        cv.poly(left, (48, 57, 66), METAL)
        cv.poly(right, (84, 92, 99), METAL)
        cv.poly(roof, (165, 171, 174), METAL)
        cv.line([roof[3], roof[2], roof[1]], (205, 203, 194), .25, METAL)
        for offset in ((-.5, .5) if double_fan else (0,)):
            p = proj(cx + hx * offset, cy, z + h)
            cv.ellipse(((p[0] - 1.35, p[1] - .72), (p[0] + 1.35, p[1] + .72)), (57, 69, 77), METAL)
            cv.line([(p[0] - .85, p[1]), (p[0] + .85, p[1])], (147, 158, 158), .25, METAL)
            cv.line([(p[0], p[1] - .5), (p[0], p[1] + .5)], (147, 158, 158), .25, METAL)
        for fraction in (.25, .50, .75):
            cv.line([lerp(left[0], left[1], fraction), lerp(left[3], left[2], fraction)], (117, 128, 130), .25, METAL)
    if detail.random() < .7:                                                              # a short duct
        u, v = positions[0]
        turn = min(.86, u + .25) if u < .5 else max(.14, u - .25)
        end = min(.86, v + .20) if v < .5 else max(.14, v - .20)
        duct = [proj(x0 + width * a, y0 + depth * c, z + .2) for a, c in ((u, v), (turn, v), (turn, end))]
        cv.line(duct, (48, 56, 66), .75, METAL)
        cv.line(duct, (164, 170, 166), .25, METAL)
    if detail.random() < .6:                                                              # a round exhaust cowl: the steam comes out here
        px, py = proj(x0 + width * .72, y0 + depth * .25, z)
        cv.poly([(px - 1, py), (px + 1, py), (px + 1, py - 2.2), (px - 1, py - 2.2)], (68, 78, 86), METAL)
        cv.ellipse(((px - 1.7, py - 3), (px + 1.7, py - 1.8)), (174, 180, 180), METAL)
        cv.line([(px - .9, py - 2.5), (px + .9, py - 2.5)], (217, 217, 205), .25, METAL)
        rec.vents.append((px, py - 3.2, b.id))
    if width >= 3 and depth >= 3 and detail.random() < .5:                                # a low guard rail
        a, c = proj(x0 + .2, y1 - .2, z), proj(x1 - .2, y1 - .2, z)
        cv.line([(a[0], a[1] - 1.2), (c[0], c[1] - 1.2)], (173, 174, 163), .25, METAL)
        for fraction in (0, .33, .66, 1):
            p = lerp(a, c, fraction)
            cv.line([p, (p[0], p[1] - 1.2)], (143, 149, 147), .25, METAL)
    if width >= 3 and depth >= 3 and detail.random() < .45:
        cx, cy = x0 + width * .48, y0 + depth * .53
        if detail.choice((True, False)):                                                  # a raised glass skylight and its frame
            pts = [proj(cx + u, cy + v, z + 1.1) for u, v in ((-.6, -.35), (.6, -.35), (.6, .35), (-.6, .35))]
            cv.poly(pts, (91, 150, 170), GLASS_R)
            cv.line(pts + [pts[0]], (209, 212, 197), .5, METAL)
            cv.line([lerp(pts[0], pts[1], .5), lerp(pts[3], pts[2], .5)], (196, 211, 207), .25, METAL)
        else:
            px, py = proj(cx, cy, z)
            cv.line([(px, py), (px, py - 3.3)], (195, 199, 190), .5, METAL)
            cv.ellipse(((px - 1.7, py - 4.9), (px + 1.7, py - 2.7)), (118, 146, 147), METAL)
            cv.line([(px - 1, py - 3.8), (px + .8, py - 4.3)], (225, 228, 211), .25, METAL)


def roof_details(cv, rec, b, cell, z, rnd, tall, style):
    x0, y0, x1, y1 = cell
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, depth = x1 - x0, y1 - y0
    for _ in range(rnd.choice((0, 0, 1, 1, 2))):                                          # machinery boxes
        ox, oy = rnd.uniform(-.35, .35) * w, rnd.uniform(-.35, .35) * depth
        s = rnd.uniform(.2, .4)
        paint_box(cv, rec, b, cx + ox - s, cy + oy - s, cx + ox + s, cy + oy + s, z, z + rnd.uniform(1.4, 3.0), 'concrete', rnd, windows=False)
    kind = rnd.random()
    px, py = proj(cx + rnd.uniform(-.3, .3) * w, cy + rnd.uniform(-.3, .3) * depth, z)
    if kind < .18:                                                                        # a water tower on legs
        for dx in (-2.0, 2.0):
            cv.line([(px + dx, py), (px + dx * .8, py - 4.5)], (70, 50, 60), .75, METAL)
        cv.line([(px - 2, py - 1), (px + 2, py - 4), (px + 2, py - 1), (px - 2, py - 4)], (67, 52, 54), .25, METAL)
        cv.rect(((px - 2.8, py - 10), (px + 2.8, py - 4.5)), (120, 82, 70), ROOF)
        for offset in (-1.6, -.5, .6, 1.7):
            cv.line([(px + offset, py - 9.8), (px + offset, py - 4.7)], (89, 62, 57), .25, ROOF)
        for yy in (-8.6, -5.7):
            cv.line([(px - 2.8, py + yy), (px + 2.8, py + yy)], (61, 52, 54), .25, ROOF)
        cv.poly([(px - 3.2, py - 10), (px + 3.2, py - 10), (px, py - 13)], (92, 62, 60), ROOF)
    elif kind < .30 and tall > 60:                                                        # a helipad
        cv.ellipse(((px - 4.6, py - 2.4), (px + 4.6, py + 2.4)), (240, 240, 250), SIGN)
        cv.ellipse(((px - 3.9, py - 2.0), (px + 3.9, py + 2.0)), (52, 56, 66), ROOF)
        cv.line([(px - 1.3, py - 1), (px - 1.3, py + 1), (px - 1.3, py), (px + 1.3, py), (px + 1.3, py - 1), (px + 1.3, py + 1)], (235, 235, 238), .25, SIGN)
    elif kind < .42 and w >= 2:                                                           # solar panels
        for k in range(3):
            qx, qy = px - 3 + k * 2.4, py
            cv.poly([(qx, qy), (qx + 2, qy - .9), (qx + 2, qy - 2.4), (qx, qy - 1.5)], (40, 70, 140), GLASS_R)
            cv.line([(qx + .3, qy - .5), (qx + 1.7, qy - 1.15)], (105, 145, 185), .25, GLASS_R)
    elif kind < .52:                                                                      # a roof garden
        cv.poly([(px - 4, py), (px, py - 2), (px + 4, py), (px, py + 2)], (52, 100, 74), GRASS)
        cv.line([(px - 3.5, py), (px, py + 1.7), (px + 3.5, py)], (166, 170, 148), .25, ROOF)
        for dx, dy in ((-1.7, -.2), (.1, -.6), (1.5, .1)):
            cv.ellipse(((px + dx - .7, py + dy - 1.2), (px + dx + .7, py + dy)), (72, 125, 74), LEAF)
    elif kind < .78 and tall > 34:                                                        # an aerial with its red light
        cv.line([(px, py), (px, py - 8)], (200, 200, 226), .5, METAL)
        red_light(cv, rec, b, px, py - 8)
    if style.get('board') and w >= 2:                                                     # an advertising board on the roof
        static_board(cv, rec, b, cx, cy, z, rnd.choice(('left', 'right')), rnd)


def paint_crown(cv, rec, b, cell, z, mat, rnd, tall, crown, style=None):
    """The top of a building: a spire, a mast, a pyramid, a dome, twin turrets, a glass lantern, a sloped roof, a mansard, a roof terrace with a pool or a
    garden, a penthouse. Tall buildings get the grander ones."""
    x0, y0, x1, y1 = cell
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    size = min(x1 - x0, y1 - y0)
    style = style or {}
    bottom, top = style.get('palette', FACADE[mat][0])
    roof_colour = style.get('roof_colour', mix(top, (136, 152, 178), .36))
    if crown == 'spire':
        base = min(.4 * size, .55)
        paint_box(cv, rec, b, cx - base, cy - base, cx + base, cy + base, z, z + 4, mat, rnd, windows=False)
        px, py = proj(cx, cy, z + 4)
        height = 20 if tall > 70 else 12
        cv.poly([(px - 1.6, py), (px + 1.6, py), (px, py - height)], mix(top, (226, 224, 214), .5), METAL)
        red_light(cv, rec, b, px, py - height)
    elif crown == 'mast':
        px, py = proj(cx, cy, z)
        for k in range(4):                                                                # a lattice mast: two legs and cross bars
            y = py - k * 4.5
            cv.line([(px - 1.2, y), (px + 1.2, y - 4.5)], (196, 198, 206), .25, METAL)
            cv.line([(px + 1.2, y), (px - 1.2, y - 4.5)], (196, 198, 206), .25, METAL)
        cv.line([(px - 1.2, py), (px - 1.2, py - 18)], (210, 212, 220), .5, METAL)
        cv.line([(px + 1.2, py), (px + 1.2, py - 18)], (210, 212, 220), .5, METAL)
        red_light(cv, rec, b, px, py - 19)
    elif crown == 'pyramid':
        apex = proj(cx, cy, z + (11 if tall > 60 else 8))
        cv.poly([proj(x0, y1, z), proj(x1, y1, z), apex], mix(top, (0, 0, 20), .45), WALL_L)
        cv.poly([proj(x1, y1, z), proj(x1, y0, z), apex], mix(top, (255, 190, 140), .22), WALL_R)
        cv.line([apex, (apex[0], apex[1] - 3.5)], (236, 206, 150), .5, METAL)
    elif crown == 'dome':
        px, py = proj(cx, cy, z)
        r = min(7.0, max(3.4, size * HW * .5))
        cv.ellipse(((px - r, py - r * .95), (px + r, py + r * .35)), (70, 122, 108), ROOF)
        cv.ellipse(((px - r * .7, py - r * .9), (px + r * .1, py - r * .35)), (122, 176, 150), ROOF)
        cv.line([(px, py - r * .95), (px, py - r * .95 - 5)], (226, 206, 150), .5, METAL)
    elif crown == 'twin':
        for fx, h in ((.28, 9), (.72, 13)):                                               # two turrets of different height
            sx, sy = x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fx
            q = min(.38, size * .22)
            paint_box(cv, rec, b, sx - q, sy - q, sx + q, sy + q, z, z + h, mat, rnd, windows=True, floor_h=3.0)
            px, py = proj(sx, sy, z + h)
            cv.poly([(px - 1.4, py), (px + 1.4, py), (px, py - 4)], mix(top, (200, 200, 210), .4), METAL)
    elif crown == 'lantern':
        q = max(.5, size * .3)
        paint_box(cv, rec, b, cx - q, cy - q, cx + q, cy + q, z, z + 7, 'glass', rnd, windows=True, floor_h=3.0)
        px, py = proj(cx, cy, z + 7)
        red_light(cv, rec, b, px, py - 3)
        cv.line([(px, py), (px, py - 3)], (200, 200, 210), .5, METAL)
    elif crown == 'slant':
        h = 9 if tall > 60 else 6
        a, c, e, dd = proj(x0, y0, z), proj(x1, y0, z), proj(x1, y1, z), proj(x0, y1, z)
        a2, b2 = (a[0], a[1] - h), (c[0], c[1] - h)
        cv.poly([c, b2, e], mix(bottom, (0, 0, 8), .15), WALL_R)
        cv.poly([a2, b2, e, dd], mix(roof_colour, (170, 186, 210), .18), ROOF)
        for fraction in (.25, .50, .75):
            cv.line([lerp(a2, b2, fraction), lerp(dd, e, fraction)], mix(roof_colour, (42, 58, 77), .38), .25, ROOF)
        cv.line([a2, b2], mix(roof_colour, (255, 236, 214), .6), .5, ROOF)
    elif crown == 'gable':
        rise = 6.0 if size >= 2.5 else 4.5
        roof_gable(cv, x0, y0, x1, y1, z, rise, 'x' if (x1 - x0) >= (y1 - y0) else 'y', roof_colour, mix(bottom, top, .55), rnd)
        detail = random.Random(f'chimney:{x0}:{y0}:{x1}:{y1}')
        if size >= 2 and detail.random() < .6:                                            # a masonry chimney standing on the slope
            kx, ky = x0 + (x1 - x0) * .7, y0 + (y1 - y0) * .25
            paint_box(cv, rec, b, kx - .22, ky - .22, kx + .22, ky + .22, z + rise * .5, z + rise * .5 + 3.2, 'brick', detail, windows=False)
    elif crown == 'hip':
        roof_hip(cv, x0 - .1, y0 - .1, x1 + .1, y1 + .1, z, 6.0 if size >= 2.5 else 4.5, roof_colour)
    elif crown == 'sawtooth':                                                             # the repeating ridges of an old workshop
        for i in range(3):
            ya, yb = y0 + (y1 - y0) * i / 3, y0 + (y1 - y0) * (i + 1) / 3
            back0, back1 = proj(x0, ya, z + 3.4), proj(x1, ya, z + 3.4)
            front0, front1 = proj(x0, yb, z), proj(x1, yb, z)
            cv.poly([proj(x0, ya, z), proj(x1, ya, z), back1, back0], mix(roof_colour, (35, 46, 51), .45), WALL_L)
            cv.poly([back0, back1, front1, front0], mix(roof_colour, (217, 205, 181), .18), ROOF)
            cv.line([back0, back1], mix(roof_colour, (233, 223, 200), .52), .25, ROOF)
    elif crown == 'mansard':
        inner = .3
        lo = [proj(x0, y1, z), proj(x1, y1, z), proj(x1 - inner, y1 - inner, z + 4), proj(x0 + inner, y1 - inner, z + 4)]
        hi = [proj(x1, y1, z), proj(x1, y0, z), proj(x1 - inner, y0 + inner, z + 4), proj(x1 - inner, y1 - inner, z + 4)]
        cv.poly(lo, mix(roof_colour, (19, 23, 30), .38), ROOF)
        cv.poly(hi, mix(roof_colour, (160, 156, 143), .12), ROOF)
        cv.poly([proj(x0 + inner, y0 + inner, z + 4), proj(x1 - inner, y0 + inner, z + 4), proj(x1 - inner, y1 - inner, z + 4),
                 proj(x0 + inner, y1 - inner, z + 4)], mix(roof_colour, (190, 190, 174), .17), ROOF)
        for k in range(1, 4):                                                             # dormers on the near slope
            p = lerp(lo[0], lo[1], k / 4)
            cv.rect(((p[0] - .8, p[1] - 3.2), (p[0] + .8, p[1] - 1.6)), (236, 200, 140) if rnd.random() < .7 else (30, 36, 52), SHOP)
    elif crown in ('roof_garden', 'roof_deck'):                                           # usable roofs rather than machine rooms
        inset = min(.35, size * .12)
        terrace = [proj(x0 + inset, y0 + inset, z + .2), proj(x1 - inset, y0 + inset, z + .2), proj(x1 - inset, y1 - inset, z + .2),
                   proj(x0 + inset, y1 - inset, z + .2)]
        base = (63, 108, 70) if crown == 'roof_garden' else (181, 147, 104)
        cv.poly(terrace, base, GRASS if crown == 'roof_garden' else ROOF)
        for fraction in (.25, .5, .75):
            cv.line([lerp(terrace[0], terrace[1], fraction), lerp(terrace[3], terrace[2], fraction)],
                    mix(base, (221, 204, 170) if crown == 'roof_deck' else (133, 139, 104), .45), .25, ROOF)
        cv.line(terrace + [terrace[0]], mix(base, (230, 222, 196), .6), .25, ROOF)
        if crown == 'roof_garden':
            for u, v, colour in ((.25, .3, (103, 151, 75)), (.72, .32, (65, 128, 79)), (.35, .72, (93, 142, 61)), (.78, .75, (140, 163, 79))):
                px, py = proj(x0 + (x1 - x0) * u, y0 + (y1 - y0) * v, z + .5)
                cv.ellipse(((px - 1.3, py - 2.4), (px + 1.3, py + .4)), colour, LEAF)
        else:
            for u in (.30, .64):
                cv.line([proj(x0 + (x1 - x0) * u, y0 + (y1 - y0) * .40, z + .5), proj(x0 + (x1 - x0) * u, y0 + (y1 - y0) * .62, z + .5)],
                        (237, 225, 197), .5, ROOF)
    elif crown == 'penthouse':
        q = min(.85, size * .28)
        local = random.Random(f'penthouse:{x0}:{y0}:{z}')
        glass_style = {'palette': ((27, 47, 50), (121, 160, 149)), 'pitch': 2.5, 'win_w': .86, 'win_h': .65, 'bands': True}
        paint_box(cv, rec, b, cx - q, cy - q, cx + q, cy + q, z, z + 5, 'glass', local, windows=True, floor_h=3.0, style=glass_style)
    elif crown == 'terrace':
        side = min(1.5, size - .5)                                                        # a pool no bigger than a cell and a half
        px0, py0 = cx - side / 2, cy - side / 2
        pts = [proj(px0, py0, z), proj(px0 + side, py0, z), proj(px0 + side, py0 + side, z), proj(px0, py0 + side, z)]
        cv.poly(pts, (56, 150, 178), GLASS_R)
        for fraction in (.30, .58):
            cv.line([lerp(pts[0], pts[3], fraction), lerp(pts[1], pts[2], fraction)], (131, 205, 215), .25, GLASS_R)
        cv.line(pts + [pts[0]], (214, 226, 232), .5, ROOF)
        cv.line([pts[3], pts[2], pts[1]], (255, 226, 170), .5, ROOF)


def led_wall(cv, rec, b, rnd):
    """A big lit screen on a wall (an advertisement, a news ticker): a dark frame and a bright panel in the wall's own plane that the scene animates."""
    (ra, rb) = faces_base(b.x0, b.y0, b.x1, b.y1)[rnd.choice((0, 1, 1))]
    if abs(rb[0] - ra[0]) < 12:
        return
    u0 = rnd.uniform(.14, .34)
    a, c = lerp(ra, rb, u0), lerp(ra, rb, u0 + rnd.uniform(.34, .5))
    z0 = b.h * rnd.uniform(.5, .7)                                                    # high on the wall, where the neighbours do not hide it
    z1 = min(z0 + rnd.uniform(7, 11), b.h - 2)
    frame = [(a[0] - .4, a[1] - z0 + .4), (c[0] + .4, c[1] - z0 + .4), (c[0] + .4, c[1] - z1 - .4), (a[0] - .4, a[1] - z1 - .4)]
    cv.poly(frame, (18, 20, 28), METAL)
    quad = [(a[0], a[1] - z0), (c[0], c[1] - z0), (c[0], c[1] - z1), (a[0], a[1] - z1)]
    colour = rnd.choice(((240, 90, 70), (80, 160, 255), (250, 200, 70), (120, 220, 150), (230, 120, 220), (240, 240, 250)))
    cv.poly(quad, colour, SIGN)
    rec.screens.append((quad, colour, b.id))


def tower_crane(cv, rec, b, gx, gy, z, own):
    """A tower crane on a roof: a lattice mast, the jib with its trolley and hook, a counter-jib with its weights, a cab, a red light at the top. The jib runs along x
    or along y (whichever it was dealt), so that it keeps the city's own angles."""
    px, py = proj(gx, gy, z)
    height = own.choice((22, 26, 30))
    axis = own.choice(('x', 'y'))
    for dx in (-.9, .9):                                                                  # the mast is two legs with cross braces
        cv.line([(px + dx, py), (px + dx, py - height)], (232, 188, 48), .55, METAL)
    for k in range(0, int(height) - 3, 4):
        cv.line([(px - .9, py - k), (px + .9, py - k - 4)], (214, 170, 40), .3, METAL)
        cv.line([(px + .9, py - k), (px - .9, py - k - 4)], (214, 170, 40), .3, METAL)
    top = (px, py - height)
    forward, back = (3.0, -1.2) if axis == 'x' else (-3.0, 1.2)
    far = proj(gx + (3.2 if axis == 'x' else 0), gy + (3.2 if axis == 'y' else 0), z + height)
    near = proj(gx - (1.3 if axis == 'x' else 0), gy - (1.3 if axis == 'y' else 0), z + height)
    cv.line([near, far], (232, 188, 48), .7, METAL)                                         # the jib and the counter-jib
    cv.line([(top[0], top[1] - 3.0), far], (150, 150, 156), .25, METAL)                      # its tie rod from the tip of the cab
    cv.line([(top[0], top[1] - 3.0), near], (150, 150, 156), .25, METAL)
    cv.line([(top[0], top[1]), (top[0], top[1] - 3.2)], (232, 188, 48), .55, METAL)
    trolley = lerp(top, far, .62)
    cv.line([trolley, (trolley[0], trolley[1] + height * .45)], (60, 60, 66), .22, METAL)       # the cable and the hook with a load
    cv.rect(((trolley[0] - .8, trolley[1] + height * .45), (trolley[0] + .8, trolley[1] + height * .45 + 1.4)), (196, 80, 56), METAL)
    cv.rect(((near[0] - .8, near[1] - .3), (near[0] + .8, near[1] + 1.2)), (120, 124, 130), METAL)  # the counterweights
    red_light(cv, rec, b, top[0], top[1] - 3.6)


def roof_extras(cv, rec, b, cell, z, crown):
    """More of what really stands on a roof, each building with its own set (its own random numbers, so the rest of the city keeps its look): a stair bulkhead with a
    door, a satellite dish, a brick chimney that steams, a cooling tower, a rooftop court, a crane on the two buildings that are being built."""
    x0, y0, x1, y1 = cell
    w, d = x1 - x0, y1 - y0
    if min(w, d) < 1.6 or b.h < 18:
        return
    own = random.Random(f'extras:{b.seed()}:{z:.1f}')
    spots = own.sample(((.18, .5), (.82, .5), (.5, .16), (.5, .84), (.2, .2), (.8, .8), (.2, .8), (.8, .2)), 3)
    wanted = own.sample(('bulkhead', 'dish', 'chimney', 'cooling', 'court', 'greenhouse', 'garden', 'none', 'bulkhead'), 3)
    if b.style.get('crane'):
        tower_crane(cv, rec, b, x0 + w * .72, y0 + d * .3, z, own)
        for ox, oy in ((.15, .15), (.85, .15), (.15, .85), (.85, .85)):                          # the bare columns of the floor that is not built yet
            qx, qy = proj(x0 + w * ox, y0 + d * oy, z)
            cv.line([(qx, qy), (qx, qy - 3.2)], (146, 146, 140), .45, WALL_R)
        return
    if crown in ('spire', 'mast', 'pyramid', 'dome', 'twin', 'lantern', 'penthouse'):
        wanted = [k for k in wanted if k in ('dish', 'bulkhead')][:1]
    for (u, v), kind in zip(spots, wanted):
        gx, gy = x0 + w * u, y0 + d * v
        px, py = proj(gx, gy, z)
        if kind == 'bulkhead' and w * d >= 4:
            lowbox(cv, gx - .3, gy - .24, gx + .3, gy + .24, z, z + 2.4, (156, 156, 150), (92, 96, 100), (128, 132, 134))
            cv.rect(((px + .3, py - 2.0), (px + 1.5, py - .4)), (36, 40, 50), METAL)
        elif kind == 'dish' and b.h > 30:
            cv.line([(px, py), (px, py - 1.8)], (150, 152, 158), .35, METAL)
            cv.ellipse(((px - 1.3, py - 3.5), (px + 1.3, py - 1.5)), (226, 228, 230), METAL)
            cv.ellipse(((px - .7, py - 3.0), (px + .8, py - 2.0)), (120, 124, 132), METAL)
        elif kind == 'chimney' and b.material in ('brick', 'stone', 'concrete'):
            lowbox(cv, gx - .17, gy - .17, gx + .17, gy + .17, z, z + 4.4, (150, 90, 70), (88, 54, 46), (124, 76, 60))
            lowbox(cv, gx - .22, gy - .22, gx + .22, gy + .22, z + 4.4, z + 5.0, (116, 112, 108), (74, 72, 70), (96, 94, 92))
            rec.vents.append((px, py - 5.4, b.id))
        elif kind == 'cooling' and w * d >= 6:
            cv.rect(((px - 1.9, py - 3.2), (px + 1.9, py - .1)), (136, 146, 154), METAL)
            cv.rect(((px + .3, py - 3.2), (px + 1.9, py - .1)), (176, 186, 192), METAL)
            cv.ellipse(((px - 1.9, py - 4.0), (px + 1.9, py - 2.4)), (190, 198, 204), METAL)
            cv.ellipse(((px - 1.2, py - 3.7), (px + 1.2, py - 2.7)), (44, 52, 60), METAL)
            rec.vents.append((px, py - 4.2, b.id))
        elif kind == 'court' and w * d >= 8 and b.h > 24:
            colour = own.choice(((60, 128, 170), (180, 100, 70), (66, 130, 90)))
            pts = [proj(gx - 1.0, gy - .6, z + .2), proj(gx + 1.0, gy - .6, z + .2), proj(gx + 1.0, gy + .6, z + .2), proj(gx - 1.0, gy + .6, z + .2)]
            cv.poly(pts, colour, ROOF)
            cv.line(pts + [pts[0]], (232, 236, 232), .3, ROOF)
            cv.line([lerp(pts[0], pts[1], .5), lerp(pts[3], pts[2], .5)], (232, 236, 232), .3, ROOF)
        elif kind == 'greenhouse' and w * d >= 6:
            # A little glasshouse with a pitched roof and metal glazing bars.
            hx, hy = min(.48, w * min(u, 1 - u) * .8), min(.35, d * min(v, 1 - v) * .8)
            lowbox(cv, gx - hx, gy - hy, gx + hx, gy + hy, z, z + 1.8,
                   (166, 203, 194), (72, 120, 122), (111, 165, 163), (GLASS_R, GLASS_L, GLASS_R))
            ridge_a, ridge_b = proj(gx - hx, gy, z + 2.8), proj(gx + hx, gy, z + 2.8)
            near_a, near_b = proj(gx - hx, gy + hy, z + 1.8), proj(gx + hx, gy + hy, z + 1.8)
            cv.poly([near_a, near_b, ridge_b, ridge_a], (116, 176, 174), GLASS_R)
            cv.line([near_a, near_b, ridge_b, ridge_a, near_a], (210, 221, 205), .3, METAL)
            cv.line([lerp(near_a, near_b, .5), lerp(ridge_a, ridge_b, .5)], (210, 221, 205), .25, METAL)
        elif kind == 'garden' and w * d >= 6:
            # Low planters make a lived-in roof rather than another machine room.
            hx, hy = min(.52, w * min(u, 1 - u) * .8), min(.38, d * min(v, 1 - v) * .8)
            for k, colour in enumerate(((75, 129, 68), (121, 153, 70), (88, 140, 91))):
                ya, yb = gy - hy + 2 * hy * k / 3, gy - hy + 2 * hy * (k + .68) / 3
                lowbox(cv, gx - hx, ya, gx + hx, yb, z, z + .45,
                       colour, (85, 75, 57), (125, 107, 76), (LEAF, WALL_L, WALL_R))


def choose_cranes(buildings, seed):
    """Two buildings in view that are 'under construction': a crane on the roof. Chosen from the mid-height ones in the visible band, far apart."""
    pool = [b for b in buildings if b.kind == 'city' and 40 < b.h < 90 and not b.podium and 60 < proj(b.x1, b.y1)[1] - b.h < 200 and 20 < proj(b.x1, b.y1)[0] < 280
            and min(b.x1 - b.x0, b.y1 - b.y0) >= 2]
    pool.sort(key=lambda b: random.Random(f'crane:{seed}:{b.seed()}').random())
    chosen = []
    for b in pool:
        px = proj(b.x1, b.y1)[0]
        if all(abs(px - c) > 90 for c in chosen):
            chosen.append(px)
            b.style['crane'] = True
        if len(chosen) == 2:
            break


def facade_extras(rnd, material, height):
    """Details of a facade that no earlier version had, decided from the building's own place: a diagonal reflection streak across glass, a coloured band, banners
    on a grand stone front, an arcade on the ground floor, the rhythm of the windows (pairs, a wide bay)."""
    out = {}
    if material == 'glass' and height > 40 and rnd.random() < .45:
        out['streak'] = rnd.uniform(.15, .75)
    if material in ('glass', 'concrete') and height > 36 and rnd.random() < .28:
        out['band'] = rnd.choice(((200, 70, 56), (60, 150, 150), (222, 170, 60), (70, 110, 190)))
    if material in ('stone', 'deco') and height > 44 and rnd.random() < .22:
        out['banner'] = rnd.choice(((176, 48, 52), (48, 86, 160), (200, 160, 60)))
    if material in ('stone', 'deco', 'brick') and rnd.random() < .3:
        out['arcade'] = True
    out['rhythm'] = rnd.choice((None, None, 'pairs', 'pairs', 'wide'))
    return out


# ------------------------------------------------------------------------------------------------------------------- districts, schemes, archetypes
# Tony, 2026-11-10: "the buildings look too alike, in front of and behind the main ones". A building is now one of ARCHETYPES (an old brick tenement, an art-deco
# tower with a stepped crown, a glass slab, a pastel block with balconies and a gabled roof, a warehouse with a sawtooth roof, a flat-iron wedge, a courtyard block,
# a round or twisted tower, a church, a city hall with a dome, a stadium, a station, a hospital, a car park, a mall, silos ...), in one of SCHEMES (a palette), chosen by
# the DISTRICT it stands in (an old town, a glass downtown round the data buildings, residential blocks, a lively commercial strip, the industrial edge by the canal).
SCHEMES = {                          # name: (colour of the wall near the street, colour high up, trim): every colour is as painted, before any light
    # the old town: brick, stone and painted plaster
    'brick_red': ((120, 48, 34), (206, 96, 64), (232, 214, 186)), 'brick_orange': ((140, 70, 40), (222, 132, 80), (240, 226, 196)),
    'brick_brown': ((96, 58, 44), (178, 118, 92), (226, 206, 176)), 'brick_dark': ((72, 44, 44), (140, 92, 88), (206, 186, 160)),
    'sandstone': ((130, 114, 92), (236, 222, 196), (176, 150, 100)), 'limestone': ((110, 108, 100), (214, 210, 196), (150, 144, 130)),
    'ochre': ((140, 112, 56), (236, 204, 116), (244, 236, 208)), 'sage': ((66, 94, 80), (156, 190, 164), (232, 226, 204)),
    'oxblood': ((98, 38, 44), (176, 80, 84), (226, 206, 170)), 'slate_blue': ((64, 80, 106), (150, 170, 200), (226, 224, 214)),
    # the glass downtown: reflective curtain walls
    'glass_blue': ((19, 42, 76), (66, 121, 181), (170, 200, 230)), 'glass_teal': ((20, 72, 70), (70, 171, 160), (170, 230, 220)),
    'glass_bronze': ((70, 48, 27), (187, 147, 94), (236, 206, 150)), 'glass_silver': ((60, 70, 80), (180, 196, 206), (230, 238, 244)),
    'glass_charcoal': ((24, 28, 36), (90, 104, 120), (160, 176, 196)), 'glass_green': ((30, 70, 50), (110, 170, 130), (190, 226, 200)),
    'glass_violet': ((52, 44, 92), (130, 120, 190), (206, 200, 240)),
    # residential: pastels
    'mint': ((110, 150, 128), (206, 236, 214), (246, 244, 236)), 'pink': ((170, 110, 112), (240, 196, 196), (250, 240, 230)),
    'lemon': ((170, 150, 80), (246, 230, 160), (250, 246, 230)), 'sky': ((100, 130, 168), (190, 220, 244), (248, 246, 240)),
    'peach': ((176, 120, 84), (248, 206, 170), (250, 240, 226)), 'lilac': ((120, 104, 150), (214, 200, 236), (246, 240, 246)),
    'whitewash': ((150, 150, 148), (244, 242, 236), (176, 120, 90)),
    # the commercial strip: loud
    'orange': ((170, 80, 30), (250, 150, 60), (250, 230, 190)), 'magenta': ((140, 40, 100), (230, 90, 170), (250, 210, 230)),
    'cyan': ((30, 110, 130), (90, 210, 230), (220, 250, 250)), 'red': ((140, 30, 34), (230, 70, 70), (250, 220, 210)),
    'black': ((30, 30, 36), (96, 96, 110), (230, 190, 70)), 'yellow': ((170, 140, 30), (250, 226, 80), (60, 60, 70)),
    # the industrial edge
    'concrete': ((70, 74, 76), (150, 156, 156), (200, 200, 190)), 'rust': ((100, 50, 34), (170, 100, 64), (214, 170, 110)),
    'corr_green': ((50, 80, 70), (110, 150, 130), (190, 200, 170)), 'corr_blue': ((50, 70, 96), (110, 140, 176), (200, 210, 220)),
    'yellow_brick': ((140, 120, 60), (214, 190, 110), (236, 226, 190)),
    # civic
    'civic_white': ((150, 150, 142), (240, 238, 226), (176, 150, 100)), 'civic_cream': ((140, 124, 96), (236, 220, 184), (96, 140, 120)),
    # Restrained variations in glass, aluminium, limestone, concrete and brick.
    'glass_ice': ((38, 60, 75), (155, 188, 206), (220, 231, 235)),
    'glass_steel': ((46, 58, 69), (140, 164, 178), (213, 223, 226)),
    'glass_smoke': ((30, 38, 49), (104, 123, 140), (186, 198, 206)),
    'glass_pearl': ((82, 95, 102), (193, 205, 207), (231, 233, 226)),
    'glass_navy': ((29, 42, 64), (84, 118, 153), (176, 197, 210)),
    'glass_titanium': ((64, 67, 68), (163, 171, 169), (217, 221, 215)),
    'stone_ivory': ((133, 127, 113), (224, 215, 194), (237, 231, 213)),
    'stone_grey': ((91, 96, 99), (181, 186, 183), (218, 220, 212)),
    'stone_warm': ((121, 112, 99), (210, 198, 178), (231, 219, 196)),
    'stone_pearl': ((132, 132, 128), (223, 220, 210), (229, 229, 220)),
    'stone_taupe': ((104, 94, 87), (189, 174, 159), (218, 207, 188)),
    'concrete_pale': ((110, 114, 115), (201, 205, 200), (223, 226, 218)),
    'concrete_cool': ((72, 83, 90), (159, 172, 176), (207, 216, 214)),
    'concrete_sand': ((113, 109, 98), (202, 196, 178), (228, 218, 198)),
    'concrete_dark': ((58, 62, 67), (133, 143, 150), (192, 199, 201)),
    'brick_taupe': ((105, 80, 69), (173, 142, 124), (213, 199, 181)),
    'brick_ash': ((85, 80, 79), (161, 147, 140), (207, 196, 184)),
    'brick_sand': ((111, 96, 77), (191, 174, 147), (224, 213, 192)),
}
DISTRICT_SCHEMES = {
    'old': ('brick_brown', 'brick_dark', 'brick_taupe', 'brick_ash', 'brick_sand', 'sandstone', 'limestone', 'stone_ivory', 'stone_warm', 'stone_taupe', 'slate_blue'),
    'glass': ('glass_blue', 'glass_bronze', 'glass_silver', 'glass_charcoal', 'glass_ice', 'glass_steel', 'glass_smoke', 'glass_pearl', 'glass_navy', 'glass_titanium', 'stone_grey'),
    'res': ('whitewash', 'limestone', 'sandstone', 'stone_ivory', 'stone_pearl', 'stone_warm', 'stone_taupe', 'concrete_pale', 'concrete_sand', 'brick_taupe', 'slate_blue'),
    'comm': ('glass_silver', 'glass_charcoal', 'glass_blue', 'glass_ice', 'glass_steel', 'glass_navy', 'glass_smoke', 'glass_titanium', 'black', 'concrete_dark', 'stone_grey'),
    'ind': ('concrete', 'concrete_cool', 'concrete_dark', 'concrete_sand', 'corr_blue', 'brick_dark', 'brick_ash', 'brick_brown', 'brick_sand', 'stone_grey'),
}
ROOF_BY_DISTRICT = {'old': ('slate', 'tar', 'brownred', 'copper', 'sand', 'tar', 'bluegrey'), 'glass': ('white', 'tar', 'charcoal', 'bluegrey', 'zinc', 'charcoal', 'membrane'),
                    'res': ('brownred', 'slate', 'membrane', 'white', 'sand', 'bluegrey'), 'comm': ('tar', 'white', 'rust', 'bluegrey', 'charcoal', 'membrane', 'brownred'),
                    'ind': ('tar', 'rust', 'membrane', 'charcoal', 'zinc', 'brownred', 'bluegrey')}
ROOF_COLOURS = {'white': (226, 228, 224), 'bluegrey': (112, 134, 156), 'membrane': (92, 124, 98), 'brownred': (128, 66, 58), 'sand': (196, 176, 138), 'terracotta': (176, 80, 53), 'slate': (65, 103, 134), 'zinc': (116, 159, 178), 'copper': (59, 147, 116), 'gravel': (183, 170, 148), 'tar': (61, 71, 79),
                'ivory': (205, 204, 188), 'rust': (150, 70, 50), 'green': (70, 120, 86), 'charcoal': (58, 62, 70)}


def district_of(b):
    """Which part of the city a building is in, from where it stands: the old town on the left, the glass downtown in the middle (round the data buildings),
    residential blocks on the right and far left, the commercial strip across the front right, the industrial edge along the canal. The borders are bent a little
    by a hash of the block so that a district is a place, not a rectangle."""
    gx, gy = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
    bx, by = int(gx // 5), int(gy // 5)
    u, v = (gx - gy) / 5, (gx + gy) / 5                    # across the picture and into it, in blocks
    wob = (hash_unit(f'district:{bx}:{by}') - .5) * 1.6
    u += wob
    if by in (12, 15, 16):
        return 'ind'
    if u < -2.3:
        return 'old' if v < 25 else 'res'
    if u > 2.4 and v < 17:
        return 'res'
    if u > .6 and v >= 17:
        return 'comm'
    if u < -.9 and v >= 24:
        return 'res'
    return 'glass'


def hash_unit(text):
    """A number in [0, 1) from a string, the same on every run (Python's own hash is not)."""
    return random.Random(text).random()


# ......................................................................................................................................... solids
def prism_faces(poly):
    """The vertical faces of a convex footprint (in cells) that the camera sees: [(left end, right end, side)] in world pixels, side 0 for a face turned mostly
    towards +y (the left walls, in shade) and 1 for one turned mostly towards +x (the right walls, in the sun)."""
    cx, cy = sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)
    out = []
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        ex, ey = q[0] - p[0], q[1] - p[1]
        nx, ny = ey, -ex
        if nx * ((p[0] + q[0]) / 2 - cx) + ny * ((p[1] + q[1]) / 2 - cy) < 0:
            nx, ny = -nx, -ny
        if nx + ny <= 1e-6:
            continue
        a, c = proj(*p), proj(*q)
        if a[0] > c[0]:
            a, c = c, a
        out.append((a, c, 1 if nx > ny else 0))
    return out


def paint_roof_poly(cv, pts, colour, rnd, rim=True):
    """The flat roof of any footprint: the colour, a lit rim along the back edges, a dark one along the front, and a speckle."""
    cv.poly(pts, colour, ROOF)
    if rim:
        lo = min(range(len(pts)), key=lambda i: pts[i][1])
        order = pts[lo:] + pts[:lo]
        cv.line(order[:3], mix(colour, (255, 232, 206), .5), .5, ROOF)
        cv.line(order[-1:] + order[:1], mix(colour, (255, 232, 206), .4), .5, ROOF)
        cv.line([order[2], order[3] if len(order) > 3 else order[0], order[0]], mix(colour, (10, 14, 24), .4), .5, ROOF)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    for _ in range(max(2, int((max(xs) - min(xs)) * (max(ys) - min(ys)) / 12))):
        x, y = rnd.uniform(min(xs), max(xs)), rnd.uniform(min(ys), max(ys))
        if point_in_poly((x, y), pts):
            cv.dot((x, y), mix(colour, (28, 30, 40) if rnd.random() < .5 else (220, 220, 226), .18), ROOF)


def point_in_poly(p, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        if (pts[i][1] > p[1]) != (pts[j][1] > p[1]) and p[0] < (pts[j][0] - pts[i][0]) * (p[1] - pts[i][1]) / (pts[j][1] - pts[i][1] + 1e-12) + pts[i][0]:
            inside = not inside
        j = i
    return inside


def paint_prism(cv, rec, b, poly, z0, z1, rnd, style, windows=True, shop=False, floor_h=FLOOR, roof=True, roof_colour=None):
    """A vertical solid on any convex footprint: every face the camera sees is painted like a wall of a box (floors, windows, the style's details), then the roof."""
    bottom, top = style.get('palette', FACADE[b.material][0])
    edge = mix(bottom, (0, 0, 0), .55)
    for a, c, side in prism_faces(poly):
        if abs(c[0] - a[0]) < .6:
            continue
        paint_face(cv, rec, b, (a, c), z0, z1, floor_h, side, style, rnd, windows and abs(c[0] - a[0]) >= 3, shop)
        cls = WALL_R if side else WALL_L
        cv.line([(a[0], a[1] - z0), (a[0], a[1] - z1)], edge, .5, cls)
        cv.line([(c[0], c[1] - z0), (c[0], c[1] - z1)], edge, .5, cls)
        cv.line([(a[0], a[1] - z0), (c[0], c[1] - z0)], edge, 1.0, cls)
    if roof:
        base = roof_colour or mix(style.get('roof_colour', mix(top, (136, 152, 178), .36)), top, .12)
        paint_roof_poly(cv, [proj(x, y, z1) for x, y in poly], base, rnd)


def paint_cyl(cv, rec, b, cx, cy, rx_px, ry_px, z0, z1, rnd, style, windows=True, floor_h=FLOOR, roof=True, ribbon=False, roof_colour=None):
    """A round tower: the wall in vertical strips (dark on the left, sunlit on the right), a window for every floor and every 16 degrees across the half the camera
    sees (or a ribbon of glass), a round roof. `cx, cy` is the centre on the ground in cells, the radii are on the picture (a circle on the ground is twice as wide as it
    is high)."""
    bottom, top = style.get('palette', FACADE[b.material][0])
    X, Y = proj(cx, cy)
    floors = max(1, round((z1 - z0) / floor_h))
    fh = (z1 - z0) / floors
    n = max(8, int(rx_px * 2))
    for i in range(n):
        xa, xb = X - rx_px + 2 * rx_px * i / n, X - rx_px + 2 * rx_px * (i + 1) / n + .02
        ua, ub = (xa - X) / rx_px, (xb - X) / rx_px
        um = (ua + ub) / 2
        ya, yb = Y + ry_px * math.sqrt(max(0, 1 - ua * ua)), Y + ry_px * math.sqrt(max(0, 1 - ub * ub))
        k = .78 + .36 * (um + 1) / 2
        for f in range(floors):
            za, zb = z0 + f * fh, z0 + (f + 1) * fh
            colour = mix(bottom, top, ((f + .5) / floors) ** .8)
            colour = tuple(min(255, round(c * k)) for c in colour)
            cv.poly([(xa, ya - za), (xb, yb - za), (xb, yb - zb), (xa, ya - zb)], colour, WALL_L if um < -.12 else WALL_R)
    if windows:
        glass = GLASS_L, GLASS_R
        steps = 9 if not ribbon else 3
        for f in range(floors):
            za, zb = z0 + f * fh + fh * .22, z0 + (f + 1) * fh - fh * .24
            colour = mix(bottom, top, ((f + .5) / floors) ** .8)
            for kk in range(steps):
                t0, t1 = -1.28 + kk * 2.56 / steps, -1.28 + (kk + (1.0 if ribbon else .62)) * 2.56 / steps
                xa, xb = X + rx_px * math.sin(t0), X + rx_px * math.sin(t1)
                ya, yb = Y + ry_px * math.cos(t0), Y + ry_px * math.cos(t1)
                quad = [(xa, ya - za), (xb, yb - za), (xb, yb - zb), (xa, ya - zb)]
                cv.poly(quad, mix(colour, (8, 14, 28), .6), glass[0] if (xa + xb) / 2 < X - rx_px * .1 else glass[1])
                rec.poke.append(((xa + xb) / 2, (ya + yb) / 2 - (za + zb) / 2, abs(xb - xa), abs(zb - za), b.id))
                if rnd.random() < b.lit:
                    rec.wins.append((quad, lit_window_colour(rnd, colour), rnd.randrange(BUCKETS), b.id, rnd.random() < .12))
    if roof:
        base = roof_colour or mix(style.get('roof_colour', (136, 152, 178)), top, .1)
        cv.ellipse(((X - rx_px, Y - ry_px - z1), (X + rx_px, Y + ry_px - z1)), base, ROOF)
        cv.ellipse(((X - rx_px * .62, Y - ry_px * .62 - z1 - .2), (X + rx_px * .5, Y + ry_px * .5 - z1 - .2)), mix(base, (255, 240, 220), .12), ROOF)
    edge = mix(bottom, (0, 0, 0), .5)
    cv.line([(X - rx_px, Y - z0), (X - rx_px, Y - z1)], edge, .5, WALL_L)
    cv.line([(X + rx_px, Y - z0), (X + rx_px, Y - z1)], edge, .5, WALL_R)


def roof_gable(cv, x0, y0, x1, y1, z, rise, axis, colour, wall, rnd, tiles=True):
    """A gabled roof over a rectangle: the slope the camera sees, the triangle of wall at the end it sees, tile courses along the slope."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    eave = .12
    if axis == 'x':                                              # the ridge runs along x: slopes face -y (hidden) and +y; the end walls face -x (hidden) and +x
        ridge0, ridge1 = proj(x0 - eave, cy, z + rise), proj(x1 + eave, cy, z + rise)
        cv.poly([proj(x0 - eave, y0 - eave, z), proj(x1 + eave, y0 - eave, z), ridge1, ridge0], mix(colour, (20, 24, 36), .25), ROOF)
        cv.poly([proj(x1, y0, z), proj(x1, y1, z), proj(x1, cy, z + rise)], wall, WALL_R)
        front = [ridge0, ridge1, proj(x1 + eave, y1 + eave, z), proj(x0 - eave, y1 + eave, z)]
        cv.poly(front, colour, ROOF)
        if tiles:
            for k in range(1, 5):
                t = k / 5
                cv.line([lerp(ridge0, front[3], t), lerp(ridge1, front[2], t)], mix(colour, (30, 34, 44), .28), .5, ROOF)
        cv.line([ridge0, ridge1], mix(colour, (255, 236, 214), .55), .6, ROOF)
        cv.line([front[3], front[2]], mix(colour, (10, 14, 22), .5), .5, ROOF)
    else:                                                        # the ridge runs along y: slopes face -x (hidden) and +x; the end walls face -y (hidden) and +y
        ridge0, ridge1 = proj(cx, y0 - eave, z + rise), proj(cx, y1 + eave, z + rise)
        cv.poly([proj(x0 - eave, y0 - eave, z), proj(x0 - eave, y1 + eave, z), ridge1, ridge0], mix(colour, (20, 24, 36), .25), ROOF)
        cv.poly([proj(x0, y1, z), proj(x1, y1, z), proj(cx, y1, z + rise)], wall, WALL_L)
        front = [ridge0, ridge1, proj(x1 + eave, y1 + eave, z), proj(x1 + eave, y0 - eave, z)]
        cv.poly(front, mix(colour, (255, 230, 200), .08), ROOF)
        if tiles:
            for k in range(1, 5):
                t = k / 5
                cv.line([lerp(ridge0, front[3], t), lerp(ridge1, front[2], t)], mix(colour, (30, 34, 44), .28), .5, ROOF)
        cv.line([ridge0, ridge1], mix(colour, (255, 236, 214), .55), .6, ROOF)
        cv.line([front[3], front[2]], mix(colour, (10, 14, 22), .5), .5, ROOF)


def roof_hip(cv, x0, y0, x1, y1, z, rise, colour):
    """A hipped roof: the two slopes the camera sees meeting at a short ridge (a point for a square)."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = max(0.0, (max(x1 - x0, y1 - y0) - min(x1 - x0, y1 - y0)) / 2)
    if x1 - x0 >= y1 - y0:
        a, c = (cx - r, cy), (cx + r, cy)
    else:
        a, c = (cx, cy - r), (cx, cy + r)
    pa, pc = proj(*a, z + rise), proj(*c, z + rise)
    cv.poly([proj(x1, y0, z), proj(x1, y1, z), pc, pa], mix(colour, (255, 230, 200), .12), ROOF)
    cv.poly([proj(x0, y1, z), proj(x1, y1, z), pc, pa], mix(colour, (20, 24, 36), .22), ROOF)
    cv.line([proj(x0, y1, z), proj(x1, y1, z), proj(x1, y0, z)], mix(colour, (10, 14, 22), .5), .5, ROOF)
    cv.line([pa, pc], mix(colour, (255, 236, 214), .5), .5, ROOF)


def roof_barrel(cv, x0, y0, x1, y1, z, rise, colour, glassy=False):
    """A barrel vault along x over a hall: strips of the curved roof from the camera's side, shaded across, with the arched end wall it sees."""
    n = 8
    d = y1 - y0
    prof = lambda t: rise * math.sqrt(max(0.0, 1 - (2 * t - 1) ** 2))
    for k in range(n):
        t0, t1 = k / n, (k + 1) / n
        shade = .74 + .5 * (t0 + t1) / 2
        c = tuple(min(255, round(v * shade)) for v in colour)
        cv.poly([proj(x0, y0 + d * t0, z + prof(t0)), proj(x1, y0 + d * t0, z + prof(t0)), proj(x1, y0 + d * t1, z + prof(t1)), proj(x0, y0 + d * t1, z + prof(t1))], c, GLASS_R if glassy else ROOF)
        if glassy:
            cv.line([proj(x0, y0 + d * t1, z + prof(t1)), proj(x1, y0 + d * t1, z + prof(t1))], mix(c, (24, 40, 56), .4), .25, METAL)
    pts = [proj(x1, y0 + d * k / n, z + prof(k / n)) for k in range(n + 1)] + [proj(x1, y1, z), proj(x1, y0, z)]
    cv.poly(pts, mix(colour, (120, 160, 190), .5) if glassy else mix(colour, (90, 80, 70), .3), GLASS_R if glassy else WALL_R)
    for k in range(1, 4):                                       # the ribs of the arch on the end wall
        t = k / 4
        cv.line([proj(x1, y0 + d * t, z), proj(x1, y0 + d * t, z + prof(t))], (40, 52, 64), .25, METAL)


# ......................................................................................................................................... archetypes
def base_style(scheme, own):
    bottom, top, trim = SCHEMES[scheme]
    return {'palette': (bottom, top), 'trim': trim, 'scheme': scheme, 'pitch': 3.0, 'win_w': .6, 'win_h': .5, 'piers': False, 'bands': False, 'office': False, 'neon': False,
            'tone': own.uniform(-.08, .1), 'escape': False, 'crown': 'flat', 'board': False, 'facade': 'classic', 'roof_material': 'gravel', 'roof_colour': ROOF_COLOURS['gravel'],
            'setback_scale': 1.0, 'setback_side': 'all', 'rhythm': None}


MATERIAL_OF = {'tenement': 'brick', 'deco': 'deco', 'glass_slab': 'glass', 'midcentury': 'concrete', 'pastel': 'concrete', 'warehouse': 'brick', 'loft': 'brick',
               'commercial': 'concrete', 'office': 'concrete', 'L_block': 'brick', 'courtyard': 'brick', 'wedge': 'stone', 'round': 'glass', 'tapered': 'glass',
               'twisted': 'glass', 'ziggurat': 'deco', 'twin': 'glass', 'pyramid_tower': 'glass',
               'terrace_block': 'concrete', 'offset_tower': 'glass'}


def style_for_arch(b, arch, scheme, own, district='glass'):
    """The facade, the roof and the details that make one archetype what it is, in the colours of its scheme."""
    s = base_style(scheme, own)
    tall = b.h >= 56
    if arch == 'tenement':
        s.update(facade=own.choice(('classic', 'classic', 'bay')), pitch=own.choice((3.0, 3.4)), win_w=.52, win_h=.62, piers=True, escape=own.random() < .6, cornice=own.choice((1.6, 2.0, 2.4)),
                 awning=own.choice((((196, 60, 50), (236, 236, 226)), ((60, 110, 70), (236, 232, 214)), ((52, 84, 140), (236, 236, 226)), ((220, 160, 50), (236, 232, 214)))),
                 crown=own.choice(('flat', 'mansard', 'gable', 'flat')), roof_material='slate', roof_colour=ROOF_COLOURS[own.choice(('slate', 'tar', 'terracotta'))], shutters=own.random() < .25 and (36, 70, 60) or None)
    elif arch == 'deco':
        s.update(facade='vertical', pitch=3.6, win_w=.46, win_h=.78, piers=True, cornice=1.6, crown='spire', roof_colour=ROOF_COLOURS[own.choice(('copper', 'green', 'slate'))],
                 setback_scale=1.45, setback_side='all')
        b.tiers = 3 if b.h > 60 else 2
    elif arch == 'glass_slab':
        s.update(facade=own.choice(('curtain', 'curtain', 'braced', 'ribbon', 'vertical')), pitch=2.6, win_w=.92, win_h=.75, bands=True, brise=own.random() < .4, crown=own.choice(('flat', 'mast', 'flat', 'lantern')),
                 roof_colour=ROOF_COLOURS['gravel'], streak=own.uniform(.15, .7) if own.random() < .5 else None)
    elif arch == 'midcentury':
        s.update(facade=own.choice(('ribbon', 'balcony', 'ribbon')), pitch=4.0, win_w=.8, win_h=.5, bands=True, panel=SCHEMES[own.choice(('concrete', 'limestone', 'slate_blue', 'whitewash'))][1], pilotis=own.random() < .5,
                 crown='flat', roof_colour=ROOF_COLOURS['gravel'])
    elif arch == 'pastel':
        s.update(facade='balcony', pitch=3.4, win_w=.6, win_h=.62, piers=False, shutters=own.choice((None, (60, 110, 90), (90, 120, 160), (200, 100, 90))), panel=SCHEMES[scheme][2],
                 crown=own.choice(('gable', 'gable', 'hip', 'hip', 'flat')), roof_colour=ROOF_COLOURS[own.choice(('terracotta', 'terracotta', 'slate', 'terracotta'))],
                 awning=own.choice((None, ((236, 236, 226), (196, 100, 90)), ((236, 236, 226), (60, 120, 130)))))
    elif arch == 'warehouse':
        s.update(facade='warehouse', pitch=4.2, win_w=.84, win_h=.5, piers=True, bands=True, crown='sawtooth', roof_colour=ROOF_COLOURS[own.choice(('tar', 'rust', 'gravel'))], arched=True)
    elif arch == 'loft':
        s.update(facade='warehouse', pitch=3.6, win_w=.8, win_h=.7, piers=True, arched=True, crown=own.choice(('roof_garden', 'penthouse', 'roof_deck')), roof_colour=ROOF_COLOURS['tar'],
                 cornice=1.2)
    elif arch == 'commercial':
        s.update(facade=own.choice(('ribbon', 'curtain', 'braced')), pitch=3.4, win_w=.8, win_h=.5, bands=True, neon=True, board=True, panel=SCHEMES[own.choice(('concrete', 'glass_silver', 'slate_blue', 'limestone'))][1],
                 crown='flat', awning=own.choice((((250, 220, 70), (60, 60, 70)), ((220, 60, 120), (240, 240, 240)))))
    elif arch == 'office':
        s.update(facade=own.choice(('ribbon', 'curtain', 'classic')), pitch=3.0, win_w=.7, win_h=.5, bands=own.random() < .6, office=True, crown=own.choice(('flat', 'flat', 'slant', 'terrace')),
                 roof_colour=ROOF_COLOURS['gravel'])
    elif arch in ('L_block', 'courtyard'):
        s.update(facade=own.choice(('classic', 'balcony')), pitch=3.2, win_w=.56, win_h=.6, piers=True, cornice=1.4, shutters=own.random() < .3 and (60, 100, 80) or None,
                 awning=own.choice((None, ((196, 60, 50), (236, 236, 226)), ((60, 110, 70), (236, 232, 214)))), roof_colour=ROOF_COLOURS[own.choice(('terracotta', 'slate', 'tar'))])
    elif arch == 'wedge':
        s.update(facade='bay', pitch=3.0, win_w=.5, win_h=.64, piers=True, cornice=1.8, awning=((220, 160, 50), (236, 232, 214)), roof_colour=ROOF_COLOURS['copper'])
    elif arch in ('round', 'tapered', 'twisted', 'twin', 'pyramid_tower'):
        s.update(facade='curtain', pitch=2.6, win_w=.9, win_h=.7, bands=True, crown='flat', roof_colour=ROOF_COLOURS['gravel'])
    elif arch == 'ziggurat':
        s.update(facade='vertical', pitch=3.4, win_w=.46, win_h=.7, piers=True, cornice=1.4, crown='spire', roof_colour=ROOF_COLOURS['copper'])
    elif arch == 'terrace_block':
        s.update(facade=own.choice(('balcony', 'classic')), pitch=own.choice((3.2, 3.8)), win_w=.57, win_h=.58,
                 bands=True, crown='flat', roof_colour=ROOF_COLOURS[own.choice(('membrane', 'sand', 'bluegrey'))])
    elif arch == 'offset_tower':
        s.update(facade=own.choice(('braced', 'vertical', 'curtain')), pitch=3.3, win_w=.7, win_h=.68,
                 bands=True, crown=own.choice(('mast', 'flat')), roof_colour=ROOF_COLOURS['zinc'])
    s['gear'] = {'tenement': .35, 'deco': .8, 'glass_slab': .8, 'midcentury': .5, 'pastel': .15, 'warehouse': .5, 'loft': .25, 'commercial': .5, 'office': .7}.get(arch, .8)
    s['arch'] = arch
    s['rhythm'] = own.choice((None, None, 'pairs')) if arch in ('tenement', 'pastel', 'midcentury', 'office') else None
    # Real buildings of the same era still have different bays, proportions,
    # and sometimes offset windows. Keep those differences stable per lot.
    s['pitch'] = round(s['pitch'] * own.uniform(.82, 1.20), 2)
    s['win_w'] = clamp(round(s['win_w'] * own.uniform(.56, .76), 2), .25, .72)
    s['win_h'] = clamp(round(s['win_h'] * own.uniform(.64, .84), 2), .27, .74)
    s['stagger'] = own.choice((0, 0, 0, .12, .18)) if arch in ('pastel', 'tenement', 'office', 'terrace_block') else 0
    identity = random.Random(f'facade-identity:{b.seed()}').choice(('end_bay', 'setback_band', None, None, None))
    s['facade_feature'] = identity
    if s.get('facade') == 'ribbon':
        s['rhythm'] = 'wide'
    if s['crown'] not in ('gable', 'hip', 'sawtooth') and arch not in ('tenement', 'pastel', 'L_block', 'courtyard', 'wedge'):
        s['roof_colour'] = ROOF_COLOURS[own.choice(ROOF_BY_DISTRICT[district])]
    return s


def choose_archetype(b, district, own):
    """Weighted choice of what a building is, from its district, its height and its plot."""
    h = b.h
    w, d = b.x1 - b.x0, b.y1 - b.y0
    if b.podium:
        w, d = b.podium[2] - b.podium[0], b.podium[3] - b.podium[1]
    big = w >= 3.2 and d >= 3.2
    wide = w >= 2.5 and d >= 2.5
    tall, mid, low = h >= 58, 28 <= h < 58, h < 28
    W = {}

    def add(name, weight, ok=True):
        if ok and weight > 0:
            W[name] = weight

    if district == 'old':
        add('deco', 5 if tall else 2, h >= 44)
        add('tenement', 5, h <= 46)
        add('loft', 2, 18 <= h <= 38)
        add('L_block', 2, h <= 46 and big)
        add('courtyard', 2, h <= 38 and big)
        add('wedge', 1.4, 14 <= h <= 52 and wide)
        add('pastel', 1, h <= 38)
        add('midcentury', .8 if tall else .5, h >= 34)
        add('ziggurat', 1.2, tall and wide)
        add('glass_slab', .6, h >= 44)
        add('twin', .8, tall and big)
        add('terrace_block', 1.8, 25 <= h <= 68 and wide)
    elif district == 'glass':
        add('glass_slab', 5 if tall else 4, h >= 34)
        add('round', 3, h >= 44 and wide)
        add('tapered', 2.5, h >= 46 and wide)
        add('twisted', 2.2, h >= 50 and wide)
        add('ziggurat', 1.4, tall and wide)
        add('twin', 1.6, tall and big)
        add('pyramid_tower', 1.2, tall)
        add('deco', 1.6, h >= 50)
        add('office', .8, h <= 62)
        add('midcentury', .3, h >= 30)
        add('commercial', 1, h <= 36)
        add('offset_tower', 3, h >= 44 and wide)
        add('terrace_block', 1.5, 30 <= h <= 76 and wide)
    elif district == 'res':
        add('pastel', 6 if h <= 44 else 4)
        add('midcentury', 1.4 if tall else 1.0, h >= 30)
        add('courtyard', 2.4, h <= 38 and big)
        add('L_block', 2.4, h <= 46 and big)
        add('tenement', 1, h <= 46)
        add('wedge', 1.2, 14 <= h <= 46 and wide)
        add('loft', 1, 18 <= h <= 34)
        add('twin', 1, tall and big)
        add('terrace_block', 2.5, 24 <= h <= 65 and wide)
        add('offset_tower', 1, h >= 48 and wide)
    elif district == 'comm':
        add('commercial', 5 if h <= 62 else 2)
        add('glass_slab', 3, h >= 36)
        add('tenement', 1.6, h <= 46)
        add('midcentury', .6, h >= 30)
        add('wedge', 1.6, 14 <= h <= 52 and wide)
        add('office', .4, h <= 60)
        add('deco', 1, h >= 50)
        add('L_block', 1, h <= 46 and big)
        add('round', 1, h >= 50 and wide)
        add('tapered', .8, h >= 50 and wide)
        add('twisted', .6, h >= 56 and wide)
        add('terrace_block', 1.8, 25 <= h <= 70 and wide)
        add('offset_tower', 2.2, h >= 42 and wide)
    else:
        add('warehouse', 6, h <= 34)
        add('loft', 2, 18 <= h <= 40)
        add('commercial', 1, h <= 40)
        add('office', .4, True)
        add('tenement', 1, h <= 46)
        add('midcentury', .4, h >= 30)
    if not W:
        W['office'] = 1
    return W


def assign_archetypes(buildings, heroes, seed):
    """Give every city building an archetype and a scheme: by its district, so that the city reads as places, and never the same as a neighbour's (a building's
    neighbours are the ones within seven cells). Landmarks were placed before and keep theirs."""
    placed = []
    for b in sorted([b for b in buildings if b.kind == 'city'], key=lambda b: (proj(b.x1, b.y1)[1], b.x0)):
        own = random.Random(f'archetype:{b.seed()}:{seed}')
        if b.style.get('arch') in LANDMARKS:
            placed.append(b)
            continue
        district = district_of(b)
        if district == 'ind' and b.h > 38:                                              # the industrial edge is low: sheds, lofts, workshops
            b.h = own.uniform(16, 38)
            b.tiers = 1
            if b.podium:
                b.x0, b.y0, b.x1, b.y1, _ = b.podium
                b.podium = None
        weights = choose_archetype(b, district, own)
        schemes = DISTRICT_SCHEMES[district]
        cx, cy = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
        near = [p for p in placed if abs((p.x0 + p.x1) / 2 - cx) + abs((p.y0 + p.y1) / 2 - cy) < 8.5]
        best = None
        for attempt in range(14):
            arch = own.choices(list(weights), list(weights.values()))[0]
            scheme = own.choice(schemes)
            clash = sum(1 for p in near if p.style.get('arch') == arch) * 2 + sum(1 for p in near if p.style.get('scheme') == scheme) + \
                sum(3 for p in near if p.style.get('arch') == arch and p.style.get('scheme') == scheme)
            if best is None or clash < best[0]:
                best = (clash, arch, scheme)
            if clash == 0:
                break
        _, arch, scheme = best
        b.material = MATERIAL_OF[arch]
        b.style = style_for_arch(b, arch, scheme, own, district)
        b.style['district'] = district
        b.style['orient'] = own.randrange(4)
        extras = facade_extras(random.Random('facade-extras:' + b.seed()), b.material, b.h)
        if arch in ('glass_slab', 'office', 'round', 'tapered', 'twisted', 'twin', 'pyramid_tower') and b.style.get('streak') is None and 'streak' in extras:
            b.style['streak'] = extras['streak']
        if arch in ('glass_slab', 'midcentury', 'office') and 'band' in extras:
            b.style['band'] = extras['band']
        if arch in ('deco', 'ziggurat', 'tenement') and 'banner' in extras and b.h >= 44:
            b.style['banner'] = extras['banner']
        placed.append(b)
    # The front rows can otherwise get only plain slabs even when the city as a
    # whole has many archetypes. Give a few suitable lots distinct silhouettes.
    forms = {'wedge', 'round', 'twisted', 'tapered', 'ziggurat', 'pyramid_tower', 'twin', 'terrace_block', 'offset_tower', 'L_block', 'courtyard'}
    front = [b for b in placed if 30 <= proj(b.x1, b.y1)[1] <= 270
             and 0 <= proj((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)[0] <= 291
             and proj((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)[1] >= 150]
    unique = sum(b.style.get('landmark') or b.style.get('arch') in forms for b in front)
    for b in front:
        if unique >= 14:
            break
        if b.style.get('landmark') or b.style.get('arch') in forms or b.style.get('arch') not in ('glass_slab', 'midcentury', 'office', 'commercial', 'pastel'):
            continue
        if not (28 <= b.h <= 76 and b.x1 - b.x0 >= 2.5 and b.y1 - b.y0 >= 2.5):
            continue
        district, scheme = b.style['district'], b.style['scheme']
        own = random.Random(f'front-form:{b.seed()}:{seed}')
        options = ['wedge', 'terrace_block', 'L_block', 'courtyard']
        if b.h >= 42:
            options += ['offset_tower', 'round', 'tapered']
        # Prefer a form that is not already next to this lot. Silhouettes,
        # rooflines and footprints matter more here than swapping wall colours.
        neighbours = [p.style.get('arch') for p in front if p is not b
                      and abs(p.x0 - b.x0) + abs(p.y0 - b.y0) < 9]
        own.shuffle(options)
        arch = min(options, key=lambda name: neighbours.count(name))
        b.material = MATERIAL_OF[arch]
        b.style = style_for_arch(b, arch, scheme, own, district)
        b.style.update(district=district, orient=own.randrange(4))
        unique += 1

    # A varied skyline needs different physical forms in every depth band,
    # not just different facade textures. Preserve each district/material
    # palette, landmarks and the low industrial buildings.
    for low, high, share in ((30, 150, .72), (150, 270, .76), (270, 440, .70)):
        band = [b for b in placed if low <= proj(b.x1, b.y1)[1] < high
                and 0 <= proj((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)[0] <= 291]
        target = math.ceil(len(band) * share)
        count = sum(bool(b.style.get('landmark') or b.style.get('arch') in forms) for b in band)
        for b in band:
            if count >= target:
                break
            if b.style.get('landmark') or b.style.get('arch') in forms or b.style.get('district') == 'ind':
                continue
            if b.style.get('arch') not in ('glass_slab', 'midcentury', 'office', 'commercial', 'pastel', 'tenement'):
                continue
            if b.h < 22 or min(b.x1 - b.x0, b.y1 - b.y0) < 1.8:
                continue
            district, scheme = b.style['district'], b.style['scheme']
            own = random.Random(f'band-form:{b.seed()}:{seed}')
            options = ['wedge', 'terrace_block', 'offset_tower']
            if b.h >= 38:
                options += ['round', 'tapered', 'ziggurat', 'twin', 'pyramid_tower']
            if b.h >= 56:
                options.append('twisted')
            own.shuffle(options)
            neighbours = [p.style.get('arch') for p in band if p is not b
                          and abs(p.x0 - b.x0) + abs(p.y0 - b.y0) < 9]
            arch = min(options, key=lambda name: neighbours.count(name))
            b.material = MATERIAL_OF[arch]
            b.style = style_for_arch(b, arch, scheme, own, district)
            b.style.update(district=district, orient=own.randrange(4))
            count += 1

    # Give the most visible part of the skyline a few deliberately different
    # silhouettes. A count of archetypes across the entire map is not enough:
    # many of them can be hidden behind nearer buildings. The coordinates are
    # approximate screen locations, and the lots themselves are unchanged.
    # The references are the varied cylindrical, twisted and faceted towers of
    # Shanghai and the narrow, older stone buildings of Manhattan.
    accents = ((140, 99, 'twisted', 'glass_steel'),
               (212, 129, 'round', 'glass_ice'),
               (236, 147, 'twin', 'glass_silver'),
               (116, 177, 'wedge', 'limestone'),
               (176, 297, 'deco', 'stone_ivory'))
    chosen = set()
    for sx, sy, arch, scheme in accents:
        minimum_side = 1.8 if arch in ('twisted', 'round', 'twin') else .8
        candidates = [b for b in placed if not b.style.get('landmark') and b not in chosen
                      and b.style.get('district') != 'ind' and b.h >= 30
                      and min(b.x1 - b.x0, b.y1 - b.y0) >= minimum_side
                      and (proj(b.x1, b.y1)[0] - sx) ** 2 + (proj(b.x1, b.y1)[1] - sy) ** 2 <= 25 ** 2]
        if not candidates:
            continue
        b = min(candidates, key=lambda p: (proj(p.x1, p.y1)[0] - sx) ** 2 + (proj(p.x1, p.y1)[1] - sy) ** 2)
        chosen.add(b)
        own = random.Random(f'skyline-accent:{b.seed()}:{seed}')
        district = b.style['district']
        b.material = MATERIAL_OF[arch]
        b.style = style_for_arch(b, arch, scheme, own, district)
        b.style.update(district=district, orient=own.randrange(4))


# ......................................................................................................................................... forms
def piece_rect(b):
    """The whole plot of a building, whatever the plan did to its shaft (a tall tower is slim on a podium that fills the plot)."""
    return b.podium[:4] if b.podium else (b.x0, b.y0, b.x1, b.y1)


def wall_style(b, **extra):
    return dict(b.style, **extra)


def top_of(cv, rec, b, rnd, cell, z, crown=None, equipment=True):
    """The roof of a solid: gear for a flat one, or the crown (spire, mast, dome, gable ...); then the extras every roof gets."""
    crown = crown or b.style.get('crown', 'flat')
    x0, y0, x1, y1 = cell
    if equipment and crown not in ('roof_garden', 'roof_deck', 'gable', 'hip', 'sawtooth'):
        roof_equipment(cv, rec, b, cell, z)
    if crown == 'flat' or x1 - x0 < 1.0:
        roof_details(cv, rec, b, cell, z, rnd, b.h, b.style)
    else:
        paint_crown(cv, rec, b, cell, z, b.material, rnd, b.h, crown, b.style)
    roof_extras(cv, rec, b, cell, z, crown)


def paint_podium(cv, rec, b, rnd):
    """The low base of a tower on a plot; returns the height it reaches."""
    if not b.podium:
        return 0.0
    px0, py0, px1, py1, ph = b.podium
    base = 'concrete' if b.material in ('glass', 'concrete') else b.material
    paint_box(cv, rec, b, px0, py0, px1, py1, 0, ph, base, rnd, shop=True, style=dict(b.style, crown='flat', palette=b.style.get('palette')))
    return ph


def paint_L(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    t = rnd.choice((1.4, 1.7))
    orient = b.style.get('orient', 0)
    wings = {0: ((x0, y0, x1, y0 + t), (x0, y0 + t, x0 + t, y1)), 1: ((x0, y1 - t, x1, y1), (x1 - t, y0, x1, y1 - t)),
             2: ((x0, y0, x0 + t, y1), (x0 + t, y1 - t, x1, y1)), 3: ((x1 - t, y0, x1, y1), (x0, y0, x1 - t, y0 + t))}[orient]
    hole = {0: (x0 + t, y0 + t, x1, y1), 1: (x0, y0, x1 - t, y1 - t), 2: (x0 + t, y0, x1, y1 - t), 3: (x0, y0 + t, x1 - t, y1)}[orient]
    g_rect_cells(cv, hole, (150, 142, 124), PAVE)
    g_rect_cells(cv, (hole[0] + .3, hole[1] + .3, hole[2] - .3, hole[3] - .3), (54, 106, 60), GRASS)
    heights = (b.h, b.h * rnd.choice((.62, .75, 1.0)))
    for wing, h in sorted(zip(wings, heights), key=lambda it: (it[0][2] + it[0][3], it[0][0] + it[0][1])):
        paint_box(cv, rec, b, *wing, 0, h, b.material, rnd, shop=True, style=wall_style(b))
        roof_equipment(cv, rec, b, wing, h)
    draw_tree(cv, rec, *proj((hole[0] + hole[2]) / 2, (hole[1] + hole[3]) / 2), 'plane', rnd, 1.0)


def g_rect_cells(cv, rect, colour, cls):
    x0, y0, x1, y1 = rect
    cv.poly([proj(x0, y0), proj(x1, y0), proj(x1, y1), proj(x0, y1)], colour, cls)


def paint_courtyard(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    t = rnd.choice((1.15, 1.35))
    g_rect_cells(cv, (x0 + t, y0 + t, x1 - t, y1 - t), (156, 146, 124), PAVE)
    g_rect_cells(cv, (x0 + t + .25, y0 + t + .25, x1 - t - .25, y1 - t - .25), (56, 110, 62), GRASS)
    wings = [(x0, y0, x1, y0 + t), (x0, y0 + t, x0 + t, y1 - t), (x1 - t, y0 + t, x1, y1 - t), (x0, y1 - t, x1, y1)]
    hs = [b.h * rnd.choice((.9, 1.0)), b.h * rnd.choice((.8, 1.0)), b.h * rnd.choice((.8, 1.0)), b.h * rnd.choice((.7, .85, 1.0))]
    order = sorted(range(4), key=lambda i: (wings[i][2] + wings[i][3], wings[i][0] + wings[i][1]))
    for n, i in enumerate(order):
        if n == 3:                                                                       # the tree in the court stands behind the front wing
            px, py = proj((x0 + x1) / 2, (y0 + y1) / 2)
            draw_tree(cv, rec, px, py, rnd.choice(('plane', 'oak', 'olive')), rnd, 1.3)
        paint_box(cv, rec, b, *wings[i], 0, hs[i], b.material, rnd, shop=(i in (0, 3)), style=wall_style(b))
        roof_equipment(cv, rec, b, wings[i], hs[i])


def paint_wedge(cv, rec, b, rnd):
    """A flat-iron: a long wall with a pointed end, on a corner lot."""
    x0, y0, x1, y1 = piece_rect(b)
    if b.style.get('orient', 0) % 2 == 0:
        poly = [(x1, (y0 + y1) / 2), (x0, y0), (x0, y1)]                              # the point to the right
    else:
        poly = [((x0 + x1) / 2, y1), (x0, y0), (x1, y0)]                              # the point to the left
    paint_prism(cv, rec, b, poly, 0, b.h, rnd, wall_style(b), shop=True, roof_colour=ROOF_COLOURS['copper'])
    cx = sum(p[0] for p in poly) / 3
    cy = sum(p[1] for p in poly) / 3
    px, py = proj(cx, cy, b.h)
    cv.ellipse(((px - 2.2, py - 1.4), (px + 2.2, py + 1.4)), (200, 190, 170), ROOF)
    cv.line([(px, py), (px, py - 6)], (210, 210, 220), .4, METAL)
    red_light(cv, rec, b, px, py - 6)


def shaft_rect(b, inset=.0):
    x0, y0, x1, y1 = b.x0 + inset, b.y0 + inset, b.x1 - inset, b.y1 - inset
    return x0, y0, x1, y1


def paint_round(cv, rec, b, rnd):
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .35)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = min(x1 - x0, y1 - y0) / 2 * .96
    Rx = r * 8.485
    top = b.h
    mid = z0 + (top - z0) * .64
    paint_cyl(cv, rec, b, cx, cy, Rx, Rx / 2, z0, mid, rnd, b.style, floor_h=FLOOR + .3, ribbon=rnd.random() < .5)
    paint_cyl(cv, rec, b, cx, cy, Rx * .74, Rx * .37, mid, top, rnd, b.style, floor_h=FLOOR + .3, ribbon=rnd.random() < .5)
    px, py = proj(cx, cy, top)
    cv.line([(px, py), (px, py - 12)], (210, 212, 224), .5, METAL)
    red_light(cv, rec, b, px, py - 12)
    roof_extras(cv, rec, b, (cx - .5, cy - .5, cx + .5, cy + .5), top, 'spire')


def paint_tapered(cv, rec, b, rnd):
    """A tower that narrows as it climbs, in many slim steps."""
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .3)
    n = 7
    h = (b.h - z0) / n
    for k in range(n):
        inset = k * min(x1 - x0, y1 - y0) * .5 / (n + 1)
        r = (x0 + inset, y0 + inset, x1 - inset, y1 - inset)
        paint_prism(cv, rec, b, [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])], z0 + k * h, z0 + (k + 1) * h, rnd, b.style, floor_h=FLOOR + .6)
    inset = (n - .5) * min(x1 - x0, y1 - y0) * .5 / (n + 1)
    top_of(cv, rec, b, rnd, (x0 + inset, y0 + inset, x1 - inset, y1 - inset), b.h, 'spire', equipment=False)


def rotated_square(cx, cy, half, angle):
    ca, sa = math.cos(angle), math.sin(angle)
    return [(cx + (dx * ca - dy * sa), cy + (dx * sa + dy * ca)) for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half))]


def paint_twisted(cv, rec, b, rnd):
    """A tower whose floors turn a little each time, so that its edges spiral."""
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .3)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = min(x1 - x0, y1 - y0) / 2 / 1.25
    n = 9
    h = (b.h - z0) / n
    turn = rnd.choice((1, -1)) * math.radians(8)
    for k in range(n):
        s = half * (1 - .035 * k)
        paint_prism(cv, rec, b, rotated_square(cx, cy, s, k * turn), z0 + k * h, z0 + (k + 1) * h, rnd, b.style, floor_h=FLOOR + .5, roof=(k == n - 1))
    px, py = proj(cx, cy, b.h)
    cv.line([(px, py), (px, py - 10)], (210, 212, 224), .5, METAL)
    red_light(cv, rec, b, px, py - 10)


def paint_ziggurat(cv, rec, b, rnd):
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .1)
    n = 5
    h = (b.h - z0) / n
    side = min(x1 - x0, y1 - y0)
    step = min(.5, (side - 1.0) / 2 / (n - 1))
    for k in range(n):
        r = (x0 + k * step, y0 + k * step, x1 - k * step, y1 - k * step)
        paint_box(cv, rec, b, *r, z0 + k * h, z0 + (k + 1) * h, b.material, rnd, shop=(k == 0 and not b.podium), style=wall_style(b, cornice=1.2))
    top_of(cv, rec, b, rnd, (x0 + (n - 1) * step, y0 + (n - 1) * step, x1 - (n - 1) * step, y1 - (n - 1) * step), b.h, 'spire', equipment=False)


def paint_twin(cv, rec, b, rnd):
    """Two towers of different height rising from one base."""
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .2)
    along_x = (x1 - x0) >= (y1 - y0)
    a = (x0, y0, x0 + (x1 - x0) * (.46 if along_x else 1), y0 + (y1 - y0) * (1 if along_x else .46))
    c = (x1 - (x1 - x0) * (.46 if along_x else 1), y1 - (y1 - y0) * (1 if along_x else .46), x1, y1)
    for rect, h in sorted(((a, b.h), (c, z0 + (b.h - z0) * .76)), key=lambda it: (it[0][2] + it[0][3])):
        paint_box(cv, rec, b, *rect, z0, h, b.material, rnd, windows=True, style=wall_style(b))
        top_of(cv, rec, b, rnd, rect, h, 'flat' if h < b.h else 'mast')
    mx, my = (a[2] + c[0]) / 2, (a[3] + c[1]) / 2
    cv.line([proj(a[2], a[3], z0 + (b.h - z0) * .55), proj(c[0], c[1], z0 + (b.h - z0) * .55)], (170, 190, 200), 1.2, METAL)   # the sky bridge between them


def paint_pyramid_tower(cv, rec, b, rnd):
    """A glass tower under a great glass pyramid."""
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .3)
    shaft = z0 + (b.h - z0) * .82
    paint_box(cv, rec, b, x0, y0, x1, y1, z0, shaft, b.material, rnd, shop=not b.podium, style=wall_style(b))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    apex = proj(cx, cy, b.h + 7)
    glass = mix(b.style['palette'][1], (200, 230, 245), .4)
    cv.poly([proj(x0, y1, shaft), proj(x1, y1, shaft), apex], mix(glass, (10, 24, 44), .4), GLASS_L)
    cv.poly([proj(x1, y1, shaft), proj(x1, y0, shaft), apex], glass, GLASS_R)
    for k in (1, 2):
        t = k / 3
        cv.line([lerp(proj(x0, y1, shaft), apex, t), lerp(proj(x1, y1, shaft), apex, t)], (214, 232, 240), .3, METAL)
        cv.line([lerp(proj(x1, y0, shaft), apex, t), lerp(proj(x1, y1, shaft), apex, t)], (214, 232, 240), .3, METAL)
    cv.line([apex, (apex[0], apex[1] - 8)], (210, 212, 224), .5, METAL)
    red_light(cv, rec, b, apex[0], apex[1] - 8)


def paint_terrace_block(cv, rec, b, rnd):
    """A residential block with generous, asymmetrical setbacks and planted roof terraces."""
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .10)
    w, d = x1 - x0, y1 - y0
    direction = b.style.get('orient', 0)
    # Recede from one edge, not all four: each tier makes a recognisable terrace.
    for k, (low, high) in enumerate(((0, .43), (.43, .72), (.72, 1))):
        inset = k * min(w, d) * .14
        r = (x0 + (inset if direction in (0, 3) else 0),
             y0 + (inset if direction in (0, 1) else 0),
             x1 - (inset if direction in (1, 2) else 0),
             y1 - (inset if direction in (2, 3) else 0))
        low_z, high_z = z0 + (b.h - z0) * low, z0 + (b.h - z0) * high
        paint_box(cv, rec, b, *r, low_z, high_z, b.material, rnd, shop=(k == 0 and not b.podium), style=wall_style(b))
        if k < 2:
            # A visible parapet and a few planters make the ledge read at tablet size.
            a, c = proj(r[0], r[3], high_z), proj(r[2], r[3], high_z)
            cv.line([a, c], (198, 203, 185), .65, METAL)
            for t in (.18, .42, .68):
                px, py = lerp(a, c, t)
                cv.ellipse(((px - 1, py - 1.8), (px + 1, py - .2)), (69, 146, 87), LEAF)
        else:
            top_of(cv, rec, b, rnd, r, high_z, 'flat')


def paint_offset_tower(cv, rec, b, rnd):
    """Three differently offset volumes and a distinct structural facade, within one lot."""
    z0 = paint_podium(cv, rec, b, rnd)
    x0, y0, x1, y1 = shaft_rect(b, 0 if b.podium else .12)
    w, d = x1 - x0, y1 - y0
    direction = 1 if b.style.get('orient', 0) % 2 else -1
    # The two upper volumes shift in opposite directions while remaining inside the lot.
    for k, (low, high) in enumerate(((0, .36), (.36, .68), (.68, 1))):
        dx = (0, .15 * direction, -.10 * direction)[k] * w
        dy = (0, -.08 * direction, .15 * direction)[k] * d
        pad_x, pad_y = (.02, .16, .19)[k] * w, (.02, .16, .19)[k] * d
        r = (x0 + pad_x + dx, y0 + pad_y + dy, x1 - pad_x + dx, y1 - pad_y + dy)
        low_z, high_z = z0 + (b.h - z0) * low, z0 + (b.h - z0) * high
        paint_box(cv, rec, b, *r, low_z, high_z, b.material, rnd, shop=(k == 0 and not b.podium), style=wall_style(b))
        if k < 2:
            a, c = proj(r[0], r[3], high_z), proj(r[2], r[3], high_z)
            cv.line([a, c], (147, 192, 204), .6, METAL)
        else:
            top_of(cv, rec, b, rnd, r, high_z, b.style.get('crown', 'flat'))


# ......................................................................................................................................... landmarks
def lit_panel(cv, rec, b, quad, colour):
    """A glowing panel: a rose window, a clock face, an atrium: its own light, and the scene's window lights when the sun goes down."""
    cv.poly(quad, colour, SHOP)
    rec.wins.append((quad, colour, 3, b.id, False))


def paint_church(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    st = dict(b.style, facade='vertical', pitch=3.0, win_w=.34, win_h=.8, piers=True, crown='flat', cornice=None, bands=False, shop=False)
    slate = (62, 78, 96)
    wall = mix(st['palette'][1], st['palette'][0], .25)
    paint_box(cv, rec, b, cx - .9, y0 + .2, cx + .9, y1 - .35, 0, 13, 'stone', rnd, windows=True, floor_h=6.5, style=st)             # the nave
    roof_gable(cv, cx - .9, y0 + .2, cx + .9, y1 - .35, 13, 7, 'y', slate, wall, rnd)
    paint_box(cv, rec, b, x0 + .3, cy - .55, x1 - .3, cy + .45, 0, 13, 'stone', rnd, windows=True, floor_h=6.5, style=st)             # the transept
    roof_gable(cv, x0 + .3, cy - .55, x1 - .3, cy + .45, 13, 6, 'x', slate, wall, rnd)
    for tx in (cx - 1.25, cx + .55):                                                                                                  # the two towers
        paint_box(cv, rec, b, tx, y1 - 1.2, tx + .7, y1 - .35, 0, 30, 'stone', rnd, windows=False, style=st)
        left, right, _ = box_faces(tx, y1 - 1.2, tx + .7, y1 - .35, 0, 30)
        for face in (left, right):                                                                                                    # belfry openings, dark
            m = lerp(face[0], face[1], .5)
            cv.rect(((m[0] - .8, m[1] - 25), (m[0] + .8, m[1] - 20)), (24, 28, 38), SHOP)
        roof_hip(cv, tx, y1 - 1.2, tx + .7, y1 - .35, 30, 13, (70, 130, 104))
        px, py = proj(tx + .35, y1 - .78, 43)
        cv.line([(px, py), (px, py - 3.5)], (226, 206, 150), .4, METAL)
    # the rose window and the great door on the front, between the towers
    a = proj(cx - .55, y1 - .35)
    b_ = proj(cx + .55, y1 - .35)
    lit_panel(cv, rec, b, [(a[0] + 1, a[1] - 19), (b_[0] - 1, b_[1] - 19), (b_[0] - 1, b_[1] - 14.5), (a[0] + 1, a[1] - 14.5)], (236, 190, 120))
    cv.rect(((lerp(a, b_, .35)[0], lerp(a, b_, .35)[1] - 7), (lerp(a, b_, .65)[0], lerp(a, b_, .65)[1] - .2)), (46, 34, 30), SHOP)
    px, py = proj(cx, cy, 13 + 7)
    cv.line([(px, py), (px, py - 5)], (226, 206, 150), .4, METAL)


def paint_city_hall(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    st = dict(b.style, facade='classic', pitch=3.2, win_w=.5, win_h=.7, piers=True, cornice=2.0, crown='flat')
    paint_box(cv, rec, b, x0 + .1, y0 + .9, x1 - .1, y1 - .1, 0, 21, 'stone', rnd, windows=True, floor_h=7.0, style=st)
    for sx in (x0 + .1, x1 - 1.0):                                                                                                    # the end pavilions stand a little higher
        paint_box(cv, rec, b, sx, y0 + .9, sx + .9, y1 - .1, 0, 24, 'stone', rnd, windows=True, floor_h=6.0, style=st)
        roof_hip(cv, sx, y0 + .9, sx + .9, y1 - .1, 24, 5, ROOF_COLOURS['copper'])
    left_a, left_b = proj(x0 + 1.2, y1 - .1), proj(x1 - 1.2, y1 - .1)                                                                 # the portico on the front
    for k in range(7):
        p = lerp(left_a, left_b, k / 6)
        cv.line([(p[0], p[1] - .5), (p[0], p[1] - 16)], (244, 240, 226), .8, WALL_L)
    cv.poly([(left_a[0], left_a[1] - 16), (left_b[0], left_b[1] - 16), (left_b[0], left_b[1] - 17.5), (left_a[0], left_a[1] - 17.5)], (236, 232, 218), WALL_L)
    cv.poly([(left_a[0] - 1, left_a[1] - 17.5), (left_b[0] + 1, left_b[1] - 17.5), ((left_a[0] + left_b[0]) / 2, (left_a[1] + left_b[1]) / 2 - 22)], (226, 222, 208), WALL_L)
    for k in range(7):                                                                                                                # the steps
        cv.line([(left_a[0] - 2 - k * .0, left_a[1] + .4 + k * .5), (left_b[0] + 2, left_b[1] + .4 + k * .5)], (214, 208, 190), .5, STONE)
    tx0, ty0, tx1, ty1 = cx - .75, cy - .35, cx + .75, cy + .65                                                                       # the clock tower and its dome
    paint_box(cv, rec, b, tx0, ty0, tx1, ty1, 21, 33, 'stone', rnd, windows=False, style=st)
    left, right, _ = box_faces(tx0, ty0, tx1, ty1, 21, 33)
    for face in (left, right):
        m = lerp(face[0], face[1], .5)
        lit_panel(cv, rec, b, [(m[0] - 2.2, m[1] - 25), (m[0] + 2.2, m[1] - 25), (m[0] + 2.2, m[1] - 29.6), (m[0] - 2.2, m[1] - 29.6)], (240, 230, 190))
        cv.line([(m[0], m[1] - 27.3), (m[0], m[1] - 29)], (40, 40, 48), .3, SHOP)
        cv.line([(m[0], m[1] - 27.3), (m[0] + 1.4, m[1] - 26.6)], (40, 40, 48), .3, SHOP)
    px, py = proj(cx, cy + .15, 33)
    cv.ellipse(((px - 6, py - 9.5), (px + 6, py + 2.5)), (70, 140, 112), ROOF)
    cv.ellipse(((px - 4.4, py - 9), (px + 1.4, py - 3)), (130, 190, 160), ROOF)
    cv.line([(px, py - 9.5), (px, py - 16)], (226, 206, 150), .5, METAL)
    cv.ellipse(((px - .9, py - 17), (px + .9, py - 15)), (236, 214, 150), METAL)
    red_light(cv, rec, b, px, py - 17.5)


def paint_stadium(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    X, Y = proj(cx, cy)
    Rx, Ry = 23.5, 12.0
    st = dict(b.style, palette=((96, 100, 104), (206, 208, 206)), win_w=.4, win_h=.6, pitch=2.0, bands=False)
    z1 = 12.0
    g_rect_cells(cv, (x0 + .1, y0 + .1, x1 - .1, y1 - .1), (112, 112, 108), PAVE)                                                       # the plaza round it
    paint_cyl(cv, rec, b, cx, cy, Rx, Ry, 0, z1, rnd, st, windows=False, floor_h=4.0, roof=False)
    for k, col in enumerate(((210, 207, 195), (126, 136, 140), (179, 172, 159), (115, 130, 137), (186, 179, 161))):
        s = 1.0 - k * .1
        cv.ellipse(((X - Rx * s, Y - Ry * s - z1 + k * 1.4), (X + Rx * s, Y + Ry * s - z1 + k * 1.4)), col, ROOF)
    # Small, varied spectators make the grandstand read as a real place rather
    # than a set of brightly coloured concentric circles.
    for row in range(2):
        radius = .94 - row * .105
        for j in range(34):
            angle = 2 * math.pi * (j + row * .45) / 34
            px = X + Rx * radius * math.cos(angle)
            py = Y + Ry * radius * math.sin(angle) - z1 + row * 1.5
            colour = rnd.choice(((217, 205, 178), (143, 153, 162), (165, 112, 99), (224, 215, 190)))
            cv.rect(((px - .25, py - .2), (px + .25, py + .2)), colour, ROOF)
    # A rectangular football pitch inside the oval stands, drawn on the same
    # isometric ground plane as the rest of the city.
    field_z = z1 - 6.4
    fx0, fy0, fx1, fy1 = x0 + .95, y0 + .95, x1 - .95, y1 - .95
    point = lambda x, y: proj(x, y, field_z)
    field = [(fx0, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1)]
    cv.poly([point(*p) for p in field], (70, 146, 78), GRASS)
    cv.line([point(*p) for p in field + field[:1]], (224, 238, 218), .35, GRASS)
    cv.line([point((fx0 + fx1) / 2, fy0), point((fx0 + fx1) / 2, fy1)], (224, 238, 218), .3, GRASS)
    cv.line([point(*p) for p in ring_pts((fx0 + fx1) / 2, (fy0 + fy1) / 2, .28, .28, 18) + [((fx0 + fx1) / 2 + .28, (fy0 + fy1) / 2)]], (224, 238, 218), .3, GRASS)
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):                                                                                # the floodlight masts
        px, py = X + sx * (Rx + 1.5) * .92, Y + sy * (Ry + .7) * .9
        cv.line([(px, py - z1 + 4), (px, py - z1 - 18)], (210, 212, 218), .5, METAL)
        for dx in (-1.2, 0, 1.2):
            cv.dot((px + dx, py - z1 - 19), (255, 244, 200), LAMP)
        rec.lamps.append((round(px, 1), round(py - z1 - 18, 1)))
    for k in range(10):                                                                                                                 # the arches of the outer wall
        a = -1.2 + k * 2.4 / 9
        mx, my = X + Rx * math.sin(a), Y + Ry * math.cos(a)
        cv.rect(((mx - .5, my - 5.5), (mx + .5, my - .8)), (40, 44, 52), WALL_R if a > 0 else WALL_L)


def paint_market_hall(cv, rec, b, rnd):
    """A low brick market with a glass roof and striped street awnings."""
    x0, y0, x1, y1 = piece_rect(b)
    g_rect_cells(cv, (x0 + .05, y0 + .05, x1 - .05, y1 - .05), (176, 164, 145), PAVE)
    hx0, hy0, hx1, hy1 = x0 + .22, y0 + .48, x1 - .22, y1 - .48
    style = dict(b.style, facade='classic', pitch=2.6, win_w=.7, win_h=.58, cornice=.8, bands=False)
    paint_box(cv, rec, b, hx0, hy0, hx1, hy1, 0, 8, 'brick', rnd, windows=True, shop=True, floor_h=4.2, style=style)
    roof_barrel(cv, hx0, hy0, hx1, hy1, 8, 4.5, (128, 173, 184), glassy=True)
    # Individual canvas panels break up the long facade and hint at shops.
    for i in range(6):
        xa = hx0 + (hx1 - hx0) * i / 6
        xb = hx0 + (hx1 - hx0) * (i + 1) / 6
        colour = (196, 72, 56) if i % 2 == 0 else (235, 219, 184)
        cv.poly([proj(xa, hy1, 4.8), proj(xb, hy1, 4.8), proj(xb, hy1 + .22, 3.8), proj(xa, hy1 + .22, 3.8)], colour, SIGN)
    for gx in (hx0 + .18, hx1 - .18):
        px, py = proj(gx, hy1, 4.5)
        cv.dot((px, py), (255, 224, 152), LAMP)
        rec.lamps.append((round(px, 1), round(py, 1)))


def paint_station(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    st = dict(b.style, facade='vertical', pitch=3.2, win_w=.42, win_h=.75, piers=True, cornice=1.6, crown='flat', shop=False)
    hx0, hx1, hy0, hy1 = x0 + .1, x1 - .1, cy - 1.0, cy + .9
    paint_box(cv, rec, b, hx0, hy0, hx1, hy1, 0, 9, 'brick', rnd, windows=True, floor_h=4.5, style=st)
    roof_barrel(cv, hx0, hy0, hx1, hy1, 9, 8, (120, 168, 190), glassy=True)
    lit_panel(cv, rec, b, [proj(hx1, hy0 + .35, 3), proj(hx1, hy1 - .35, 3), proj(hx1, hy1 - .35, 10), proj(hx1, hy0 + .35, 10)], (232, 214, 170))
    paint_box(cv, rec, b, x0 + .1, hy1 + .15, x0 + .9, hy1 + .95, 0, 28, 'brick', rnd, windows=False, style=st)                         # the clock tower
    left, right, _ = box_faces(x0 + .1, hy1 + .15, x0 + .9, hy1 + .95, 0, 28)
    for face in (left, right):
        m = lerp(face[0], face[1], .5)
        lit_panel(cv, rec, b, [(m[0] - 1.8, m[1] - 21), (m[0] + 1.8, m[1] - 21), (m[0] + 1.8, m[1] - 24.6), (m[0] - 1.8, m[1] - 24.6)], (240, 230, 190))
    roof_hip(cv, x0 + .1, hy1 + .15, x0 + .9, hy1 + .95, 28, 8, ROOF_COLOURS['copper'])
    for k in range(6):                                                                                                                  # the platform canopy with its posts
        px = x0 + 1.2 + k * ((x1 - x0 - 1.6) / 5)
        pa = proj(px, hy1 + .8)
        cv.line([pa, (pa[0], pa[1] - 4.5)], (70, 76, 84), .4, METAL)
    cv.poly([proj(x0 + 1.1, hy1 + .5, 4.5), proj(x1 - .3, hy1 + .5, 4.5), proj(x1 - .3, hy1 + 1.0, 4.5), proj(x0 + 1.1, hy1 + 1.0, 4.5)], (196, 196, 190), ROOF)


def paint_hospital(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    st = dict(b.style, facade='ribbon', pitch=2.8, win_w=.85, win_h=.5, bands=True, crown='flat', cornice=None)
    wings = [(x0 + .2, y0 + .2, x0 + 1.3, y1 - .2, 26), (x1 - 1.3, y0 + .2, x1 - .2, y1 - .2, 22), (x0 + 1.3, cy - .6, x1 - 1.3, cy + .6, 18)]
    for wx0, wy0, wx1, wy1, h in sorted(wings, key=lambda w: (w[2] + w[3], w[0] + w[1])):
        paint_box(cv, rec, b, wx0, wy0, wx1, wy1, 0, h, 'concrete', rnd, windows=True, floor_h=4.2, style=st)
        roof_equipment(cv, rec, b, (wx0, wy0, wx1, wy1), h)
    px, py = proj(cx, cy, 18)                                                                                                           # the red cross on the roof of the middle block
    cv.rect(((px - 1.0, py - 3.0), (px + 1.0, py + 3.0)), (214, 40, 40), SIGN)
    cv.rect(((px - 3.0, py - 1.0), (px + 3.0, py + 1.0)), (214, 40, 40), SIGN)
    hx, hy = proj(x1 - .75, cy + 1.0, 22)                                                                                               # the helipad
    cv.ellipse(((hx - 4.2, hy - 2.2), (hx + 4.2, hy + 2.2)), (236, 236, 240), SIGN)
    cv.ellipse(((hx - 3.6, hy - 1.9), (hx + 3.6, hy + 1.9)), (58, 70, 96), ROOF)
    cv.line([(hx - 1.2, hy - 1), (hx - 1.2, hy + 1), (hx - 1.2, hy), (hx + 1.2, hy), (hx + 1.2, hy - 1), (hx + 1.2, hy + 1)], (236, 236, 240), .3, SIGN)
    ax0, ay0 = proj(cx - .8, y1 - .2)                                                                                                   # the entrance canopy
    cv.poly([(ax0, ay0 - 5), (ax0 + 9, ay0 - 5 + 4.5), (ax0 + 9, ay0 - 3.5 + 4.5), (ax0, ay0 - 3.5)], (60, 150, 190), ROOF)


def paint_garage(cv, rec, b, rnd):
    """A car park: open decks, each a slab and a dark opening with the cars in it, a ramp up one end, the cars on the top deck, a stair tower."""
    x0, y0, x1, y1 = piece_rect(b)
    x0, y0, x1, y1 = x0 + .15, y0 + .15, x1 - .15, y1 - .15
    decks, dh = 5, 4.4
    top = decks * dh
    (la, lb), (ra, rb) = faces_base(x0, y0, x1, y1)
    accent = b.style['palette'][1]
    for side, (a, c), cls in ((0, (la, lb), WALL_L), (1, (ra, rb), WALL_R)):
        cv.poly([(a[0], a[1]), (c[0], c[1]), (c[0], c[1] - top), (a[0], a[1] - top)], (150, 152, 150), cls)
        n = max(2, int(abs(c[0] - a[0]) / 2))
        for k in range(decks):
            za, zb = k * dh, (k + 1) * dh
            cv.poly([(a[0], a[1] - za - .9), (c[0], c[1] - za - .9), (c[0], c[1] - zb + .5), (a[0], a[1] - zb + .5)], (44, 46, 52), cls)
            cv.line([(a[0], a[1] - zb + .5), (c[0], c[1] - zb + .5)], (206, 206, 200), .8, cls)
            for j in range(n):                                                                                                          # a car in some of the bays
                if rnd.random() < .6:
                    p = lerp(a, c, (j + .5) / n)
                    cv.rect(((p[0] - .7, p[1] - za - 2.0), (p[0] + .7, p[1] - za - .9)), rnd.choice(CAR_PAINT), cls)
                if rnd.random() < b.lit * .8:
                    p = lerp(a, c, (j + .5) / n)
                    q = [(p[0] - 1, p[1] - za - 3.4), (p[0] + 1, p[1] - za - 3.4), (p[0] + 1, p[1] - za - 2.6), (p[0] - 1, p[1] - za - 2.6)]
                    rec.wins.append((q, (255, 226, 160), rnd.randrange(BUCKETS), b.id, False))
        for j in range(n + 1):
            p = lerp(a, c, j / n)
            cv.line([(p[0], p[1]), (p[0], p[1] - top)], (190, 190, 184), .5, cls)
    stripe = [proj(x1, y0 + .3, 0), proj(x1, y0 + .9, 0), proj(x1, y0 + .9, top), proj(x1, y0 + .3, top)]
    cv.poly(stripe, accent, WALL_R)
    roof = [proj(x0, y0, top), proj(x1, y0, top), proj(x1, y1, top), proj(x0, y1, top)]
    cv.poly(roof, (170, 172, 170), ROOF)
    for k in range(5):
        px, py = proj(x0 + .5 + rnd.random() * (x1 - x0 - 1), y0 + .5 + rnd.random() * (y1 - y0 - 1), top)
        cv.rect(((px - .7, py - 1.1), (px + .7, py)), rnd.choice(CAR_PAINT), ROOF)
    paint_box(cv, rec, b, x1 - 1.0, y0, x1 - .15, y0 + .9, top, top + 6, 'concrete', rnd, windows=False, style=dict(b.style, palette=((120, 122, 124), (190, 190, 186))))
    px, py = proj(x0 + 1.0, y1 - .6, top)
    cv.rect(((px - 1.6, py - 8), (px + 1.6, py - 4.5)), (40, 110, 220), SIGN)                                                           # a blue sign on a post: no letter
    cv.line([(px, py - 4.5), (px, py)], (80, 84, 92), .4, METAL)


def paint_mall(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    g_rect_cells(cv, (x0 + .1, cy + .9, x1 - .1, y1 - .1), (58, 60, 66), ASPHALT)                                                       # the car park in front, with its bays and cars
    for k in range(1, 9):
        gx = x0 + .1 + k * (x1 - x0 - .2) / 9
        cv.line([proj(gx, cy + 1.0), proj(gx, y1 - .2)], (190, 190, 180), .25, ASPHALT)
    for k in range(14):
        gx, gy = x0 + .35 + rnd.random() * (x1 - x0 - .7), cy + 1.2 + rnd.random() * (y1 - cy - 1.6)
        px, py = proj(gx, gy)
        cv.rect(((px - .8, py - 1.3), (px + .8, py)), rnd.choice(CAR_PAINT), ROOF)
    st = dict(b.style, facade='ribbon', pitch=4.4, win_w=.7, win_h=.4, bands=False, crown='flat', cornice=None, panel=None)
    paint_box(cv, rec, b, x0 + .15, y0 + .35, x1 - .15, cy + .8, 0, 11, 'concrete', rnd, windows=True, shop=True, floor_h=5.5, style=st)
    left_a, left_b = proj(x0 + .15, cy + .8), proj(x1 - .15, cy + .8)                                                                   # a long sign band on the front
    cv.poly([(left_a[0], left_a[1] - 8.2), (left_b[0], left_b[1] - 8.2), (left_b[0], left_b[1] - 10.2), (left_a[0], left_a[1] - 10.2)], b.style['palette'][1], SIGN)
    rec.screens.append(([(left_a[0] + 3, left_a[1] - 8.4), (left_a[0] + 14, left_a[1] - 8.4 + 5.4), (left_a[0] + 14, left_a[1] - 9.8 + 5.4), (left_a[0] + 3, left_a[1] - 9.8)], b.style['palette'][1], b.id))
    ax0, ay0, ax1, ay1 = cx - 1.1, cy - .8, cx + 1.1, cy + .3                                                                           # the glass atrium: a pyramid of glass on the roof
    apex = proj((ax0 + ax1) / 2, (ay0 + ay1) / 2, 11 + 9)
    glass = (150, 210, 236)
    cv.poly([proj(ax0, ay1, 11), proj(ax1, ay1, 11), apex], mix(glass, (20, 50, 84), .35), GLASS_L)
    cv.poly([proj(ax1, ay1, 11), proj(ax1, ay0, 11), apex], glass, GLASS_R)
    for k in (1, 2, 3):
        t = k / 4
        cv.line([lerp(proj(ax0, ay1, 11), apex, t), lerp(proj(ax1, ay1, 11), apex, t)], (226, 240, 248), .3, METAL)
        cv.line([lerp(proj(ax1, ay0, 11), apex, t), lerp(proj(ax1, ay1, 11), apex, t)], (226, 240, 248), .3, METAL)
    lit_panel(cv, rec, b, [lerp(proj(ax0, ay1, 11), apex, .3), lerp(proj(ax1, ay1, 11), apex, .3), lerp(proj(ax1, ay1, 11), apex, .55), lerp(proj(ax0, ay1, 11), apex, .55)], (236, 226, 190))
    roof_equipment(cv, rec, b, (x0 + .15, y0 + .35, ax0, cy + .8), 11)


def paint_silos(cv, rec, b, rnd):
    x0, y0, x1, y1 = piece_rect(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    st = dict(b.style, facade='warehouse', pitch=4.0, win_w=.6, win_h=.4, crown='flat')
    paint_box(cv, rec, b, x0 + .2, cy + .5, x1 - 1.2, y1 - .2, 0, 9, 'concrete', rnd, windows=True, floor_h=4.5, style=st)                  # a low shed
    roof_equipment(cv, rec, b, (x0 + .2, cy + .5, x1 - 1.2, y1 - .2), 9)
    for k in range(4):                                                                                                                   # the silos, in a row
        sx, sy = x0 + .9 + k * .85, y0 + 1.2 + k * .0
        h = rnd.choice((28, 32, 36, 30))
        colour = rnd.choice(((206, 204, 196), (190, 196, 200), (170, 120, 90)))
        sst = dict(st, palette=(mix(colour, (0, 0, 0), .35), colour))
        paint_cyl(cv, rec, b, sx, sy, 6.2, 3.1, 0, h, rnd, sst, windows=False, floor_h=6.0)
        X, Y = proj(sx, sy)
        cv.ellipse(((X - 6.2, Y - 3.1 - h), (X + 6.2, Y + 3.1 - h)), mix(colour, (255, 255, 255), .15), ROOF)
        cv.ellipse(((X - 2.0, Y - 1.4 - h - 2), (X + 2.0, Y + 1.0 - h - 2)), (170, 172, 176), METAL)
    cv.poly([proj(x0 + .6, y0 + 1.0, 36), proj(x0 + 4.0, y0 + 1.0, 36), proj(x0 + 4.0, y0 + 1.3, 36), proj(x0 + .6, y0 + 1.3, 36)], (150, 152, 156), METAL)   # the gallery over the tops
    ch_x, ch_y = x1 - .55, y0 + .9                                                                                                       # a tall chimney, banded red and white
    for k in range(6):
        paint_cyl(cv, rec, b, ch_x, ch_y, 2.6 - k * .06, 1.3 - k * .03, 8 * k, 8 * (k + 1), rnd, dict(st, palette=((150, 40, 36), (214, 70, 60)) if k % 2 else ((190, 188, 184), (244, 242, 236))),
                  windows=False, floor_h=8.0, roof=(k == 5))
    cx_, cy_ = proj(ch_x, ch_y, 48)
    red_light(cv, rec, b, cx_, cy_ - 2)
    rec.vents.append((cx_, cy_ - 3, b.id))


SPECIAL = {'L_block': paint_L, 'courtyard': paint_courtyard, 'wedge': paint_wedge, 'round': paint_round, 'tapered': paint_tapered, 'twisted': paint_twisted,
           'terrace_block': paint_terrace_block, 'offset_tower': paint_offset_tower,
           'ziggurat': paint_ziggurat, 'twin': paint_twin, 'pyramid_tower': paint_pyramid_tower, 'church': paint_church, 'city_hall': paint_city_hall,
           'stadium': paint_stadium, 'market_hall': paint_market_hall, 'station': paint_station, 'hospital': paint_hospital, 'garage': paint_garage, 'mall': paint_mall, 'silos': paint_silos}
LANDMARKS = ('church', 'city_hall', 'stadium', 'market_hall', 'station', 'hospital', 'garage', 'mall', 'silos')
LANDMARK_PLAN = (                      # (archetype, scheme, where on the world picture the block should be, in pixels, height)
    ('church', 'limestone', (56, 135), 62), ('city_hall', 'civic_white', (206, 270), 60), ('station', 'brick_brown', (70, 62), 46), ('hospital', 'whitewash', (258, 312), 46),
    ('mall', 'glass_silver', (214, 300), 36), ('garage', 'concrete_sand', (150, 300), 38), ('stadium', 'concrete', (50, 356), 30), ('silos', 'concrete', (230, 380), 56),
    ('garage', 'concrete_cool', (36, 255), 34),
)


def place_landmarks(out, heroes, seed):
    """Put the landmarks where the eye should find them, one in each part of the picture: for each, the whole block of the plan nearest to its place that is built
    (and not under or in front of a data building) becomes it. Returns the new list."""
    blocks = {}
    for b in out:
        if b.kind == 'city':
            blocks.setdefault((int((b.x0 + .01) // 5), int((b.y0 + .01) // 5)), []).append(b)
    used = set()
    for arch, scheme, (tx, ty), height in LANDMARK_PLAN:
        best = None
        for (bx, by), group in blocks.items():
            if (bx, by) in used or len(group) == 0:
                continue
            gx0, gy0 = bx * 5 + 1, by * 5 + 1
            cx, cy = proj(gx0 + 2, gy0 + 2)
            d = math.hypot(cx - tx, cy - ty)
            probe = Building(gx0, gy0, gx0 + 4, gy0 + 4, height)
            lx0, ly0, lx1, ly1 = probe.bbox(height)
            hidden = 0.0
            for other in out:
                if other.kind == 'city' and other.order >= probe.order - 1 and other.h > height * .85:
                    ox0, oy0, ox1, oy1 = other.bbox()
                    if not (ox1 < lx0 or ox0 > lx1 or oy1 < ly0 or oy0 > ly1):
                        hidden += other.h - height * .85
            d += (hidden * .04 if d < 46 else 400)                        # a block that would hide the landmark behind tall neighbours is a slightly worse place for it (within reach of its place)
            if best is None or d < best[0]:
                best = (d, (bx, by))
        if best is None or best[0] > 150:
            continue
        used.add(best[1])
        bx, by = best[1]
        for old in blocks[best[1]]:
            out.remove(old)
        b = Building(bx * 5 + 1, by * 5 + 1, bx * 5 + 5, by * 5 + 5, height, 'stone')
        own = random.Random(f'landmark:{arch}:{seed}')
        b.lit = .4
        b.h = height
        b.style = base_style(scheme, own)
        b.style.update(arch=arch, district='civic', landmark=True)
        b.material = {'church': 'stone', 'city_hall': 'stone', 'stadium': 'concrete', 'station': 'brick', 'hospital': 'concrete', 'garage': 'concrete', 'mall': 'concrete', 'silos': 'concrete'}[arch]
        blocks[best[1]] = [b]
        out.append(b)
        clear_view(out, b, height)
    return out


def repair_central_block(out, seed):
    """Make the thin wedge and its neighbour read as one solid building."""
    footprints = {(31, 36, 34, 40), (34, 36, 35, 40)}
    pieces = [b for b in out if b.kind == 'city' and (b.x0, b.y0, b.x1, b.y1) in footprints]
    if len(pieces) != 2:
        return
    for b in pieces:
        out.remove(b)
    b = Building(31, 36, 35, 40, 62, 'concrete')
    b.lit = .4
    b.style = style_for_arch(b, 'terrace_block', 'limestone', random.Random(f'central-block:{seed}'), 'res')
    b.style.update(district='res', orient=1)
    out.append(b)


def place_civic_blocks(out, seed):
    """Give open blocks varied, low buildings without hiding data towers."""
    choices = {(9, 8): ('stadium', 'concrete', 'concrete', 30),
               (8, 8): ('market_hall', 'brick_brown', 'brick', 14)}
    for (bx, by), (arch, scheme, material, height) in choices.items():
        x0, y0, x1, y1 = bx * 5 + 1, by * 5 + 1, bx * 5 + 5, by * 5 + 5
        pieces = [b for b in out if b.x0 < x1 and b.x1 > x0 and b.y0 < y1 and b.y1 > y0]
        if not pieces or any(b.kind not in ('lot', 'plaza', 'park') for b in pieces):
            continue  # preserve occupied parcels and, especially, data towers
        for old in pieces:
            out.remove(old)
        if arch == 'market_hall':
            # A compact hall at the back of the plaza leaves the clock's area
            # open; the other half of the block remains public space.
            out.append(Building(x0 + 2, y0, x1, y1, 0, kind='plaza'))
            out.append(Building(x0, y0 + 2, x0 + 2, y1, 0, kind='plaza'))
            x1, y1 = x0 + 2, y0 + 2
        b = Building(x0, y0, x1, y1, height, material)
        b.lit = .4
        b.style = base_style(scheme, random.Random(f'civic:{arch}:{seed}'))
        b.style.update(arch=arch, district='civic', landmark=True)
        out.append(b)
    # Two ordinary neighbourhood blocks diversify the landscaped middle and
    # foreground. Their low roofs leave the usage towers and clock clear.
    neighbourhoods = {
        (10, 7): ((0, 0, 2, 4, 23, 'office', 'stone_taupe'),
                  (2, 0, 4, 4, 17, 'loft', 'brick_brown')),
        (10, 9): ((0, 1, 3, 3, 18, 'commercial', 'concrete_sand'),),
    }
    for (bx, by), buildings in neighbourhoods.items():
        x0, y0, x1, y1 = bx * 5 + 1, by * 5 + 1, bx * 5 + 5, by * 5 + 5
        pieces = [b for b in out if b.x0 < x1 and b.x1 > x0 and b.y0 < y1 and b.y1 > y0]
        if not pieces or any(b.kind not in ('lot', 'plaza', 'park') for b in pieces):
            continue
        for old in pieces:
            out.remove(old)
        for dx0, dy0, dx1, dy1, height, arch, scheme in buildings:
            b = Building(x0 + dx0, y0 + dy0, x0 + dx1, y0 + dy1, height, MATERIAL_OF[arch])
            own = random.Random(f'neighbourhood:{bx}:{by}:{arch}:{seed}')
            b.style = style_for_arch(b, arch, scheme, own, 'comm')
            b.style.update(district='comm', neighbourhood=True)
            b.lit = .4
            out.append(b)


def clear_view(out, landmark, height):
    """Nothing taller than a little over half a landmark stands in front of it or beside it where it would hide it: the city round a landmark is lower, as round a real
    cathedral or a station, so that the eye finds it."""
    lx0, ly0, lx1, ly1 = landmark.bbox(height)
    for b in out:
        if b is landmark or b.kind != 'city' or b.style.get('landmark'):
            continue
        if b.order <= landmark.order + .5 or abs((b.x0 + b.x1) / 2 - (landmark.x0 + landmark.x1) / 2) + abs((b.y0 + b.y1) / 2 - (landmark.y0 + landmark.y1) / 2) > 10:
            continue                                                                   # (only the buildings next to it and in front of it)
        x0, y0, x1, y1 = b.bbox()
        if x1 < lx0 or x0 > lx1 or y1 < ly0 or y0 > ly1:
            continue
        cap = max(30.0, height * .92)
        if b.h > cap:
            b.h = cap
            if b.podium:
                b.x0, b.y0, b.x1, b.y1, _ = b.podium
                b.podium = None
            b.tiers = 1


def merge_blocks(out, heroes, seed):
    """Some blocks of several small buildings become one building on the whole block (a courtyard block, an L, a big slab): more than half the plan's blocks are cut
    into pieces, and no piece is big enough to be a courtyard."""
    groups = {}
    for b in out:
        if b.kind == 'city':
            groups.setdefault((int((b.x0 + .01) // 5), int((b.y0 + .01) // 5)), []).append(b)
    for (bx, by), group in sorted(groups.items()):
        if len(group) < 2 or hash_unit(f'merge:{bx}:{by}:{seed}') > .5 or proj(bx * 5 + 3, by * 5 + 3)[1] < 150:         # (not in the back rows: they stay a skyline)
            continue
        hs = sorted(g.h for g in group)
        b = Building(bx * 5 + 1, by * 5 + 1, bx * 5 + 5, by * 5 + 5, min(hs[-1] if hash_unit(f'merge-tall:{bx}:{by}') < .5 else hs[len(hs) // 2], 64.0), group[0].material)
        b.lit, b.tiers, b.style = group[0].lit, 1, dict(group[0].style)
        b.h = min(b.h, height_cap(b, heroes))
        if b.h < 12:
            continue
        for g in group:
            out.remove(g)
        out.append(b)
    return out



def paint_building(cv, rec, b):
    rnd = random.Random('paint:' + b.seed())
    cv.bid = b.id
    painter = SPECIAL.get(b.style.get('arch'))
    if painter:                                                                           # a form or a landmark with its own painter
        painter(cv, rec, b, rnd)
        cv.bid = 0
        return
    x0, y0, x1, y1 = b.x0, b.y0, b.x1, b.y1
    z0 = 0.0
    if b.podium:                                                                          # a low base fills the whole plot
        px0, py0, px1, py1, ph = b.podium
        base = 'concrete' if b.material in ('glass', 'concrete') else b.material
        paint_box(cv, rec, b, px0, py0, px1, py1, 0, ph, base, rnd, shop=True, style=dict(b.style, crown='flat'))
        z0, b_height = ph, b.h - ph
    else:
        b_height = b.h
    for tier in range(b.tiers):
        share = b_height if b.tiers == 1 else b_height * (.62, .26, .12)[tier]
        paint_box(cv, rec, b, x0, y0, x1, y1, z0, z0 + share, b.material, rnd, shop=(tier == 0 and not b.podium), style=b.style)
        z0 += share
        if tier + 1 < b.tiers or b.style.get('crown') not in ('roof_garden', 'roof_deck', 'gable', 'sawtooth'):
            roof_equipment(cv, rec, b, (x0, y0, x1, y1), z0)
        if tier + 1 < b.tiers:
            inset = rnd.choice((.3, .5, .5)) if min(x1 - x0, y1 - y0) >= 3 else .3
            inset = min(inset * b.style.get('setback_scale', 1), (min(x1 - x0, y1 - y0) - .8) / 2)
            setback = b.style.get('setback_side', 'all')
            if setback == 'near':
                x0, y0 = x0 + inset * 2, y0 + inset * 2
            elif setback == 'far':
                x1, y1 = x1 - inset * 2, y1 - inset * 2
            else:
                x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
            if x1 - x0 < .8 or y1 - y0 < .8:
                break
    if b.style.get('neon'):                                                               # a vertical neon sign at the corner
        corner = proj(b.x1, b.y1)
        colour = rnd.choice(((255, 80, 120), (90, 200, 255), (130, 255, 160), (255, 190, 70)))
        top = min(b.h * .8, 11)
        cv.rect(((corner[0] - 1.6, corner[1] - top), (corner[0] - .6, corner[1] - 3)), colour, SIGN)
        rec.screens.append(([(corner[0] - 1.6, corner[1] - 3), (corner[0] - .6, corner[1] - 3), (corner[0] - .6, corner[1] - top), (corner[0] - 1.6, corner[1] - top)],
                            colour, b.id))
    if 40 < b.h < 120 and not b.podium and b.tiers == 1 and rnd.random() < .6:
        led_wall(cv, rec, b, rnd)
    crown = b.style.get('crown', 'flat')
    if crown == 'flat' or x1 - x0 < 1.0:
        roof_details(cv, rec, b, (x0, y0, x1, y1), z0, rnd, b.h, b.style)
    else:
        paint_crown(cv, rec, b, (x0, y0, x1, y1), z0, b.material, rnd, b.h, crown, b.style)
    roof_extras(cv, rec, b, (x0, y0, x1, y1), z0, crown)
    cv.bid = 0


# --------------------------------------------------------------------------------------------------------------- open ground: parks, plazas, gardens, avenues
# Everything flat (lawns, paving, paths, ponds, courts, flower beds) is painted in the ground pass, before any building; everything that stands up (trees, benches,
# stalls, play equipment, kiosks) is a PROP of the block it stands in, painted just before that block's own buildings, so that what is behind hides behind it
# and what is in front covers it: the painters' order of the city, kept for the trees too.
KEEP = []                                           # world boxes of the data buildings: no tree may stand in front of them


def in_keep(p, pad=2):
    return any(k[0] - pad <= p[0] <= k[2] + pad and k[1] - pad <= p[1] <= k[3] + pad for k in KEEP)


def block_of(gx, gy):
    """The block that owns a ground point: blocks start at 5 b + 1 and the street that leads into a block (5 b to 5 b + 1) belongs to it."""
    return int(math.floor(gx / 5)), int(math.floor(gy / 5))


def g_poly(cv, pts, fill, c=None):
    cv.poly([proj(x, y) for x, y in pts], fill, c)


def g_rect(cv, x0, y0, x1, y1, fill, c=None):
    g_poly(cv, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill, c)


def g_line(cv, pts, fill, width=1.0, c=None):
    cv.line([proj(x, y) for x, y in pts], fill, width, c)


def ring_pts(cx, cy, rx, ry, n=28, turn=0.0):
    ca, sa = math.cos(turn), math.sin(turn)
    out = []
    for i in range(n):
        t = 2 * math.pi * i / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        out.append((cx + ex * ca - ey * sa, cy + ex * sa + ey * ca))
    return out


def g_ellipse(cv, cx, cy, rx, ry, fill, c=None, n=28, turn=0.0):
    g_poly(cv, ring_pts(cx, cy, rx, ry, n, turn), fill, c)


def blob_pts(cx, cy, rx, ry, rnd, wobble=.22, n=26, turn=0.0):
    """An organic outline (a pond, a meadow, a grove): an ellipse whose radius is bent by three low harmonics."""
    harmonics = [(rnd.uniform(.5, 1.0) * wobble / k ** .5, rnd.uniform(0, 6.283), k) for k in (2, 3, 5)]
    ca, sa = math.cos(turn), math.sin(turn)
    out = []
    for i in range(n):
        t = 2 * math.pi * i / n
        r = 1 + sum(a * math.cos(k * t + ph) for a, ph, k in harmonics)
        ex, ey = rx * r * math.cos(t), ry * r * math.sin(t)
        out.append((cx + ex * ca - ey * sa, cy + ex * sa + ey * ca))
    return out


def smooth_path(ctrl, steps=7):
    """A Catmull-Rom curve through the control points: the winding paths of a park."""
    pts = [ctrl[0]] * 1 + list(ctrl) + [ctrl[-1]]
    out = [ctrl[0]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(1, steps + 1):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    return out


def lowbox(cv, x0, y0, x1, y1, z0, z1, top, left, right, classes=(ROOF, WALL_L, WALL_R)):
    """A small box in the city's projection: hedges, planters, counters, benches. Three faces, each its colour and its class (so the sun lights it like a wall)."""
    lf, rt, roof = box_faces(x0, y0, x1, y1, z0, z1)
    cv.poly(lf, left, classes[1])
    cv.poly(rt, right, classes[2])
    cv.poly(roof, top, classes[0])


TREES = {                                           # radius range (px), trunk (px), four greens from the shaded underside to the sunlit top
    'oak': ((2.4, 3.4), 2.0, ((22, 58, 36), (42, 96, 50), (80, 138, 64), (128, 178, 92))),
    'plane': ((1.9, 2.7), 2.4, ((32, 72, 44), (62, 112, 58), (102, 152, 72), (154, 192, 102))),
    'olive': ((1.7, 2.4), 1.2, ((66, 88, 66), (106, 132, 92), (148, 170, 118), (192, 206, 156))),
    'maple': ((2.1, 3.0), 1.8, ((104, 40, 30), (170, 72, 38), (208, 112, 50), (232, 164, 84))),
    'ginkgo': ((1.9, 2.6), 2.0, ((122, 104, 34), (184, 158, 56), (214, 192, 90), (238, 224, 150))),
    'cherry': ((1.8, 2.6), 1.6, ((130, 70, 92), (196, 124, 154), (224, 170, 192), (244, 214, 226))),
    'birch': ((1.6, 2.2), 2.8, ((68, 110, 54), (112, 156, 72), (162, 198, 102), (208, 228, 142))),
    'pine': ((1.7, 2.2), 1.0, ((14, 46, 36), (26, 76, 54), (48, 112, 76), (86, 150, 104))),
    'poplar': ((1.1, 1.5), 1.2, ((24, 64, 36), (50, 106, 50), (90, 148, 68), (134, 180, 96))),
    'palm': ((2.5, 3.1), 5.5, ((28, 82, 48), (54, 122, 60), (98, 164, 80), (162, 202, 120))),
    'shrub': ((.9, 1.3), .2, ((28, 70, 40), (50, 104, 52), (86, 140, 66), (130, 176, 92))),
    'bloom': ((.9, 1.3), .2, ((120, 40, 70), (200, 70, 110), (240, 120, 150), (255, 190, 200))),
}


def draw_tree(cv, rec, px, py, species, rnd, scale=1.0, shadow=True):
    """One tree with the volume of the city's light (sun from the right and above): a trunk, a canopy of lobes whose underside is dark and whose upper right is
    bright, a few leaf speckles. Its shadow and the dark under its canopy are added to the masks later (rec.trees)."""
    (r0, r1), trunk, tones = TREES[species]
    r = rnd.uniform(r0, r1) * scale
    trunk *= scale
    dark, mid, light, hi = tones
    cx, cy = px, py - trunk - r * .85
    if species in ('shrub', 'bloom'):
        for dx, dy, k in ((-.55, .05, .7), (.5, .1, .75), (0, -.35, .85)):
            rr = r * k
            cv.ellipse(((px + dx * r - rr * 1.1, py + dy * r - rr * 1.5), (px + dx * r + rr * 1.1, py + dy * r + rr * .1)), mid if dx else dark, LEAF)
        cv.ellipse(((px - r * .1, py - r * 1.8), (px + r * .8, py - r * .9)), light, LEAF)
        rec.trees.append((px, py, r * 1.1, r * 1.2, 0))
        return r
    if species == 'palm':
        top = (px, py - trunk - r * .2)
        cv.line([(px, py), (px - .3, py - trunk * .5), top], (118, 92, 64), .8, WALL_R)
        for k in range(7):
            ang = k * 2 * math.pi / 7 + rnd.uniform(-.2, .2)
            ex, ey = top[0] + math.cos(ang) * r, top[1] + math.sin(ang) * r * .45 + (r * .35 if abs(math.cos(ang)) > .3 else -r * .1)
            cv.line([top, ((top[0] + ex) / 2, top[1] + (ey - top[1]) * .2 - .5), (ex, ey)], mid if math.cos(ang) < 0 else light, .7, LEAF)
        cv.ellipse(((top[0] - .8, top[1] - .8), (top[0] + .8, top[1] + .5)), dark, LEAF)
        rec.trees.append((px, py, r * .8, trunk + 2, 0))
        return r
    if species == 'pine':
        tiers = 3
        cv.line([(px, py), (px, py - trunk)], (84, 60, 42), .7, WALL_R)
        for k in range(tiers):
            w = r * (1.25 - k * .32)
            yb, yt = py - trunk - k * r * .95 + .2, py - trunk - (k + 1.55) * r * .95
            cv.poly([(px - w, yb), (px, yt), (px, yb + .35)], dark, LEAF)
            cv.poly([(px + w, yb), (px, yt), (px, yb + .35)], mid if k else light, LEAF)
            if k == tiers - 1:
                cv.poly([(px + w * .55, yb - .2), (px, yt), (px, yb - .6)], light, LEAF)
        rec.trees.append((px, py, r * 1.0, trunk + r * 3.2, 0))
        return r
    if species == 'poplar':
        h = r * 3.6
        cv.line([(px, py), (px, py - trunk)], (84, 60, 42), .6, WALL_R)
        cv.ellipse(((px - r, py - trunk - h), (px + r, py - trunk + .3)), dark, LEAF)
        cv.ellipse(((px - r * .35, py - trunk - h * .96), (px + r * .95, py - trunk - h * .12)), mid, LEAF)
        cv.ellipse(((px + r * .1, py - trunk - h * .9), (px + r * .75, py - trunk - h * .45)), light, LEAF)
        rec.trees.append((px, py, r * 1.1, trunk + h * .6, 0))
        return r
    pale = species == 'birch'
    cv.line([(px, py), (px, py - trunk - r * .4)], (214, 212, 200) if pale else (92, 66, 44), .75, WALL_R)
    lobes = ((-.6, .2, .66), (.55, .12, .7), (-.02, -.28, .88))
    for dx, dy, k in lobes:
        rr = r * k
        cv.ellipse(((cx + dx * r - rr * 1.12, cy + dy * r - rr * .92), (cx + dx * r + rr * 1.12, cy + dy * r + rr * .78)), dark, LEAF)
    for dx, dy, k in lobes[1:]:
        rr = r * k * .82
        cv.ellipse(((cx + dx * r - rr * .95 + r * .1, cy + dy * r - rr * .95 - r * .1), (cx + dx * r + rr * 1.05 + r * .1, cy + dy * r + rr * .55 - r * .1)), mid, LEAF)
    cv.ellipse(((cx - r * .15, cy - r * .85), (cx + r * .85, cy + r * .1)), mid, LEAF)
    cv.ellipse(((cx + r * .02, cy - r * .86), (cx + r * .78, cy - r * .22)), light, LEAF)
    for _ in range(3):                                                                   # speckles: leaves catching the sun, gaps in the shade
        cv.dot((cx + rnd.uniform(.0, .8) * r, cy - rnd.uniform(.3, .85) * r), hi, LEAF)
    for _ in range(2):
        cv.dot((cx - rnd.uniform(.2, .9) * r, cy + rnd.uniform(.0, .5) * r), dark, LEAF)
    rec.trees.append((px, py, r * 1.15, trunk + r * 1.7, 0))
    return r


def paint_item(cv, rec, item):
    """One prop of an open block, in screen space; the kinds are the ones the designs below put on the ground."""
    kind, gx, gy = item[0], item[1], item[2]
    arg = item[3:]
    px, py = proj(gx, gy)
    rnd = random.Random(f'{kind}:{gx:.2f}:{gy:.2f}')
    if kind == 'tree':
        if not in_keep((px, py - 4), 3):
            draw_tree(cv, rec, px, py, arg[0], rnd, arg[1] if len(arg) > 1 else 1.0)
    elif kind == 'bench':
        axis = arg[0] if arg else 'x'
        a = (.3, .09) if axis == 'x' else (.09, .3)
        lowbox(cv, gx - a[0], gy - a[1], gx + a[0], gy + a[1], 0, .8, (176, 128, 88), (92, 64, 46), (128, 90, 62))
        if axis == 'x':
            lowbox(cv, gx - a[0], gy - a[1] - .02, gx + a[0], gy - a[1] + .03, .8, 1.7, (150, 108, 74), (88, 62, 44), (120, 86, 58))
        else:
            lowbox(cv, gx - a[0] - .02, gy - a[1], gx - a[0] + .03, gy + a[1], .8, 1.7, (150, 108, 74), (88, 62, 44), (120, 86, 58))
    elif kind == 'lamp':
        if not in_keep((px, py - 3), 2):
            cv.line([(px, py), (px, py - 3.0)], (58, 60, 68), .5, METAL)
            cv.dot((px, py - 3.3), (255, 232, 170), LAMP)
            rec.lamps.append((round(px, 1), round(py - 3.3, 1)))
    elif kind == 'stall':
        axis, c1, c2 = arg
        a = (.46, .2) if axis == 'x' else (.2, .46)
        lowbox(cv, gx - a[0], gy - a[1], gx + a[0], gy + a[1], 0, 1.2, (170, 130, 92), (96, 70, 52), (132, 96, 66))
        for k in range(5):                                                                # goods on the counter
            fx, fy = proj(gx + a[0] * (-.7 + .35 * k) * (1 if axis == 'x' else 0) + (a[0] * .5 if axis == 'y' else 0), gy + a[1] * (-.7 + .35 * k) * (1 if axis == 'y' else 0) + (a[1] * .5 if axis == 'x' else 0), 1.3)
            cv.dot((fx, fy), rnd.choice(((220, 60, 50), (244, 190, 50), (110, 180, 70), (230, 130, 40), (180, 60, 140))), SIGN)
        for ox, oy in ((-a[0], -a[1]), (a[0], -a[1]), (a[0], a[1]), (-a[0], a[1])):
            qx, qy = proj(gx + ox, gy + oy)
            cv.line([(qx, qy), (qx, qy - 3.1)], (76, 62, 52), .35, METAL)
        steps = 4
        for k in range(steps):                                                            # the striped awning
            if axis == 'x':
                x_a, x_b = gx - a[0] + 2 * a[0] * k / steps, gx - a[0] + 2 * a[0] * (k + 1) / steps
                quad = [proj(x_a, gy - a[1] - .08, 3.1), proj(x_b, gy - a[1] - .08, 3.1), proj(x_b, gy + a[1] + .08, 3.1), proj(x_a, gy + a[1] + .08, 3.1)]
            else:
                y_a, y_b = gy - a[1] + 2 * a[1] * k / steps, gy - a[1] + 2 * a[1] * (k + 1) / steps
                quad = [proj(gx - a[0] - .08, y_a, 3.1), proj(gx + a[0] + .08, y_a, 3.1), proj(gx + a[0] + .08, y_b, 3.1), proj(gx - a[0] - .08, y_b, 3.1)]
            cv.poly(quad, c1 if k % 2 == 0 else c2, ROOF)
    elif kind == 'table':
        colour = arg[0]
        cv.line([(px, py), (px, py - 1.4)], (210, 206, 196), .5, METAL)
        cv.ellipse(((px - 1.8, py - 2.7), (px + 1.8, py - 1.1)), colour, SIGN)
        cv.dot((px - 1.5, py + .2), (80, 70, 60), METAL)
        cv.dot((px + 1.4, py + .3), (80, 70, 60), METAL)
    elif kind == 'sculpture':
        # A small abstract public artwork, on a stone plinth, seen from both sides.
        lowbox(cv, gx - .26, gy - .26, gx + .26, gy + .26, 0, 1.2,
               (192, 187, 173), (105, 105, 100), (150, 150, 138))
        cv.line([(px - .5, py - 1.2), (px - 1.4, py - 4.1), (px - .2, py - 5.8),
                 (px + 1.3, py - 4.0), (px + .5, py - 1.2)], (57, 106, 111), .8, METAL)
        cv.line([(px - 1.2, py - 4.1), (px - .15, py - 5.6), (px + 1.15, py - 4.0)],
                (178, 206, 194), .35, METAL)
    elif kind == 'clock':
        cv.line([(px, py), (px, py - 4.8)], (67, 71, 72), .55, METAL)
        cv.ellipse(((px - 1.4, py - 7.0), (px + 1.4, py - 4.3)), (48, 63, 64), METAL)
        cv.ellipse(((px - 1.0, py - 6.6), (px + 1.0, py - 4.7)), (225, 220, 195), STONE)
        cv.line([(px, py - 5.0), (px, py - 5.6), (px + .5, py - 5.9)], (58, 62, 64), .3, METAL)
    elif kind == 'swing':
        for dx in (-.45, .45):
            x0, y0 = proj(gx + dx, gy)
            cv.line([(x0 - .7, y0 + .3), (x0, y0 - 3.0), (x0 + .7, y0 + .3)], (214, 70, 60), .4, METAL)
        a, c = proj(gx - .45, gy, 3.0), proj(gx + .45, gy, 3.0)
        cv.line([a, c], (240, 90, 70), .4, METAL)
        for dx in (-.15, .18):
            x0, y0 = proj(gx + dx, gy, 1.0)
            cv.line([(x0, y0 - 2.0), (x0, y0)], (150, 150, 160), .25, METAL)
            cv.dot((x0, y0 + .1), (60, 100, 200), METAL)
    elif kind == 'slide':
        lowbox(cv, gx - .13, gy - .13, gx + .13, gy + .13, 0, 2.6, (230, 190, 60), (170, 40, 40), (210, 70, 60))
        top, bottom = proj(gx + .15, gy, 2.5), proj(gx + .95, gy, .3)
        cv.poly([top, (top[0] + .9, top[1] + .4), (bottom[0] + .9, bottom[1] + .4), bottom], (250, 210, 70), ROOF)
    elif kind == 'frame':
        lowbox(cv, gx - .3, gy - .3, gx + .3, gy + .3, 0, 1.9, (70, 150, 210), (30, 90, 150), (50, 120, 180))
        cv.line([proj(gx - .3, gy, 1.9), proj(gx + .3, gy, 1.9)], (230, 230, 240), .25, METAL)
        cv.line([proj(gx, gy - .3, 1.9), proj(gx, gy + .3, 1.9)], (230, 230, 240), .25, METAL)
    elif kind == 'goal':
        axis = arg[0]
        lo, hi = ((gx, gy - .55), (gx, gy + .55)) if axis == 'y' else ((gx - .55, gy), (gx + .55, gy))
        a, c = proj(*lo), proj(*hi)
        cv.line([a, (a[0], a[1] - 1.7), (c[0], c[1] - 1.7), c], (244, 244, 244), .45, METAL)
        cv.line([(a[0], a[1] - 1.5), (c[0], c[1] - 1.5)], (190, 200, 205), .25, METAL)
    elif kind == 'net':
        axis = arg[0]
        lo, hi = ((gx, gy - .9), (gx, gy + .9)) if axis == 'y' else ((gx - .9, gy), (gx + .9, gy))
        a, c = proj(*lo), proj(*hi)
        cv.poly([(a[0], a[1] - .3), (c[0], c[1] - .3), (c[0], c[1] - 1.5), (a[0], a[1] - 1.5)], (214, 218, 216), ROOF)
        cv.line([(a[0], a[1] - 1.5), (c[0], c[1] - 1.5)], (250, 250, 250), .3, METAL)
        for q in (a, c):
            cv.line([(q[0], q[1]), (q[0], q[1] - 1.7)], (60, 66, 70), .35, METAL)
    elif kind == 'hoop':
        axis = arg[0]
        cv.line([(px, py), (px, py - 3.4)], (70, 74, 82), .45, METAL)
        cv.line([(px, py - 3.4), (px + (.9 if axis == 'x' else -.9), py - 3.0)], (214, 80, 50), .45, METAL)
    elif kind == 'busstop':
        axis = arg[0]
        a = (.6, .2) if axis == 'x' else (.2, .6)
        for ox, oy in ((-a[0], -a[1]), (a[0], -a[1]), (a[0], a[1]), (-a[0], a[1])):
            qx, qy = proj(gx + ox, gy + oy)
            cv.line([(qx, qy), (qx, qy - 3.0)], (70, 76, 84), .35, METAL)
        lowbox(cv, gx - a[0], gy - a[1], gx + a[0], gy + a[1], 0, .5, (150, 130, 100), (84, 70, 56), (110, 92, 74))
        roof = [proj(gx - a[0] - .06, gy - a[1] - .06, 3.0), proj(gx + a[0] + .06, gy - a[1] - .06, 3.0), proj(gx + a[0] + .06, gy + a[1] + .06, 3.0), proj(gx - a[0] - .06, gy + a[1] + .06, 3.0)]
        cv.poly(roof, (140, 188, 212), GLASS_R)
        cv.line(roof + [roof[0]], (222, 236, 242), .3, METAL)
        sx, sy = proj(gx + (a[0] + .2 if axis == 'x' else 0), gy + (0 if axis == 'x' else a[1] + .2))
        cv.line([(sx, sy), (sx, sy - 3.6)], (70, 76, 84), .3, METAL)
        cv.rect(((sx - .8, sy - 4.6), (sx + .8, sy - 3.4)), (36, 110, 214), SIGN)
    elif kind == 'planter':
        axis, length = arg
        a = (length / 2, .12) if axis == 'x' else (.12, length / 2)
        lowbox(cv, gx - a[0], gy - a[1], gx + a[0], gy + a[1], 0, 1.0, (86, 124, 66), (126, 112, 98), (170, 154, 136), (GRASS, WALL_L, WALL_R))
        for k in range(int(length / .3)):
            fx, fy = proj(gx + (-a[0] + .15 + .3 * k if axis == 'x' else 0), gy + (0 if axis == 'x' else -a[1] + .15 + .3 * k), 1.3)
            cv.dot((fx, fy - .2), rnd.choice(((230, 90, 110), (246, 210, 80), (250, 250, 250), (150, 110, 200), (60, 130, 60))), LEAF)
    elif kind == 'box':                                                                   # a kiosk, a pavilion, a shed
        x0, y0 = gx, gy
        x1, y1, height, wall, roofc = arg
        lowbox(cv, x0, y0, x1, y1, 0, height, roofc, wall, mix(wall, (255, 236, 210), .25))
        left, right, roof = box_faces(x0, y0, x1, y1, 0, height)
        for face, k in ((left, .62), (right, 1.0)):                                       # a door and a window, lit at night by the scene
            mid = lerp(face[0], face[1], .5)
            cv.rect(((mid[0] - .55, mid[1] - height * .7), (mid[0] + .55, mid[1] - .2)), (40, 44, 56) if rnd.random() < .5 else (236, 200, 140), SHOP)
    elif kind == 'gazebo':
        r = arg[0]
        for k in range(6):
            ang = k * math.pi / 3
            qx, qy = proj(gx + math.cos(ang) * r, gy + math.sin(ang) * r)
            cv.line([(qx, qy), (qx, qy - 3.0)], (226, 222, 210), .35, METAL)
        top = proj(gx, gy, 5.4)
        ring = [proj(gx + math.cos(k * math.pi / 3) * r * 1.2, gy + math.sin(k * math.pi / 3) * r * 1.2, 3.0) for k in range(6)]
        for k in range(6):
            cv.poly([ring[k], ring[(k + 1) % 6], top], mix((58, 140, 116), (30, 80, 70), .2 + .1 * (k % 3)), ROOF)
    elif kind == 'obelisk':
        lowbox(cv, gx - .2, gy - .2, gx + .2, gy + .2, 0, 1.0, (196, 190, 176), (140, 134, 120), (176, 170, 156))
        cv.poly([(px - .6, py - 1.0), (px + .6, py - 1.0), (px + .3, py - 6.0), (px - .1, py - 6.4)], (216, 208, 190), WALL_R)
    elif kind == 'topiary':
        draw_tree(cv, rec, px, py, 'shrub', rnd, 1.25)
    elif kind == 'hedge':
        x0, y0, x1, y1 = arg
        lowbox(cv, x0, y0, x1, y1, 0, 1.4, (52, 106, 56), (24, 62, 38), (40, 88, 48))
    elif kind == 'parked':                                                                # a parked car: static, tiny, painted into the street
        axis, body = arg
        a = (.18, .075) if axis == 'x' else (.075, .18)
        lowbox(cv, gx - a[0], gy - a[1], gx + a[0], gy + a[1], 0, 1.0, mix(body, (255, 255, 255), .3), mix(body, (0, 0, 0), .4), body)
        lowbox(cv, gx - a[0] * .5, gy - a[1] * .8, gx + a[0] * .5, gy + a[1] * .8, 1.0, 1.55, mix(body, (140, 170, 200), .5), mix(body, (20, 30, 50), .6), mix(body, (40, 54, 80), .4))


def render_items(cv, rec, items):
    for item in sorted(items, key=lambda it: (it[1] + it[2], it[1])):
        paint_item(cv, rec, item)


class Region:
    """A stretch of open ground: one block, a few blocks with the streets between them, or a strip: what it is (a design), where it is (a rectangle in cells), the
    blocks it covers, and what stands on it (props). A region paints its flat ground at once, and the scene's walkers use the paths it notes."""

    def __init__(self, design, rect, blocks, seed=0):
        self.design, self.rect, self.blocks = design, tuple(rect), list(blocks)
        self.rnd = random.Random(f'region:{design}:{rect}:{seed}')
        self.items, self.occ = [], []

    @property
    def w(self):
        return self.rect[2] - self.rect[0]

    @property
    def d(self):
        return self.rect[3] - self.rect[1]

    def at(self, u, v):
        return self.rect[0] + self.w * u, self.rect[1] + self.d * v

    def add(self, *item):
        self.items.append(item)

    def block(self, bx, by):
        return (bx, by) in self.blocks

    def free(self, gx, gy, r=.3):
        """Is the spot clear of the things that have been laid out (ponds, courts, plazas, paths)?"""
        for o in self.occ:
            if o[0] == 'c':
                if math.hypot(gx - o[1], gy - o[2]) < o[3] + r:
                    return False
            elif o[0] == 'e':
                u, v = (gx - o[1]) / (o[3] + r), (gy - o[2]) / (o[4] + r)
                if u * u + v * v < 1:
                    return False
            elif o[1] - r < gx < o[3] + r and o[2] - r < gy < o[4] + r:
                return False
        return True

    def keep_path(self, pts, r=.34):
        for a, c in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(c[0] - a[0], c[1] - a[1]) / .35))
            for k in range(n + 1):
                self.occ.append(('c', a[0] + (c[0] - a[0]) * k / n, a[1] + (c[1] - a[1]) * k / n, r))

    def scatter(self, count, species, shape=None, gap=.7, scale=(.9, 1.15), margin=.25, tries=40):
        """Trees at random spots of `shape` (a function of a point, default: the whole rectangle), none on anything laid out and none too close to another."""
        x0, y0, x1, y1 = self.rect
        placed = [(it[1], it[2]) for it in self.items if it[0] == 'tree']
        n = 0
        for _ in range(count * tries):
            if n >= count:
                break
            gx, gy = self.rnd.uniform(x0 + margin, x1 - margin), self.rnd.uniform(y0 + margin, y1 - margin)
            if shape and not shape(gx, gy):
                continue
            if not self.free(gx, gy, .15) or any(math.hypot(gx - a, gy - b) < gap for a, b in placed):
                continue
            kind = self.rnd.choices([s[0] for s in species], [s[1] for s in species])[0]
            placed.append((gx, gy))
            self.add('tree', gx, gy, kind, self.rnd.uniform(*scale))
            n += 1
        return n

    def rows(self, a, b, spacing, species, offset=0.0, scale=(.95, 1.1), jitter=.05):
        """A straight row of trees from a to b (an avenue)."""
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(length / spacing))
        for k in range(n):
            t = (k + .5 + offset) / n
            gx, gy = a[0] + (b[0] - a[0]) * t + self.rnd.uniform(-jitter, jitter), a[1] + (b[1] - a[1]) * t + self.rnd.uniform(-jitter, jitter)
            self.add('tree', gx, gy, species[k % len(species)] if len(species) > 1 else species[0], self.rnd.uniform(*scale))


def lawn(cv, region, base, alt, stripes='x', width=.5):
    """The region's lawn: a base colour and, if asked, mown stripes of a second tone across it (along x or along y)."""
    x0, y0, x1, y1 = region.rect
    g_rect(cv, x0, y0, x1, y1, base, GRASS)
    if stripes:
        n = int((x1 - x0 if stripes == 'x' else y1 - y0) / width)
        for k in range(1, n, 2):
            if stripes == 'x':
                g_rect(cv, x0 + k * width, y0, min(x1, x0 + (k + 1) * width), y1, alt, GRASS)
            else:
                g_rect(cv, x0, y0 + k * width, x1, min(y1, y0 + (k + 1) * width), alt, GRASS)


def kerb(cv, region, edge=(150, 146, 138), hedge=None, width=.22):
    """A pavement strip round the region and, on its two near sides, a low hedge or a railing: the line between the park and the street."""
    x0, y0, x1, y1 = region.rect
    for a, c in (((x0, y0 + width / 2), (x1, y0 + width / 2)), ((x1 - width / 2, y0), (x1 - width / 2, y1)), ((x0, y1 - width / 2), (x1, y1 - width / 2)), ((x0 + width / 2, y0), (x0 + width / 2, y1))):
        g_line(cv, [a, c], edge, 1.1, PAVE)
    if hedge:
        for a, c in (((x0 + .3, y1 - .34), (x1 - .3, y1 - .34)), ((x1 - .34, y0 + .3), (x1 - .34, y1 - .3))):
            g_line(cv, [a, c], hedge, 1.2, LEAF)


def path_line(cv, rec, region, pts, width=1.1, colour=(202, 188, 157), edge=(102, 91, 72), walk=True):
    g_line(cv, pts, edge, width + .8, STONE)
    g_line(cv, pts, colour, width, STONE)
    region.keep_path(pts)
    if walk:
        for a, c in zip(pts[::4], pts[4::4]):
            if math.hypot(c[0] - a[0], c[1] - a[1]) > 1.4:
                rec.paths.append((tuple(round(v, 2) for v in a), tuple(round(v, 2) for v in c)))


def flower_bed(cv, x0, y0, x1, y1, rnd, colours=((230, 90, 110), (246, 210, 80), (250, 250, 250), (150, 110, 200)), rows=3):
    g_rect(cv, x0, y0, x1, y1, (96, 70, 52), GRASS)
    for r in range(rows):
        v = y0 + (y1 - y0) * (r + .5) / rows
        colour = colours[r % len(colours)] if rnd.random() < .7 else rnd.choice(colours)
        for k in range(max(2, int((x1 - x0) / .28))):
            u = x0 + (x1 - x0) * (k + .5) / max(2, int((x1 - x0) / .28))
            cv.dot(proj(u, v), colour if rnd.random() < .85 else (86, 140, 70), LEAF)


def paving(cv, region, base, alt, joint, cell=.5, cls=PAVE):
    """Paving: a base tone, a chequer of a second tone and fine joints."""
    x0, y0, x1, y1 = region.rect
    g_rect(cv, x0, y0, x1, y1, base, cls)
    nx, ny = int((x1 - x0) / cell), int((y1 - y0) / cell)
    for i in range(nx):
        for j in range(ny):
            if (i + j) % 2:
                g_rect(cv, x0 + i * cell, y0 + j * cell, min(x1, x0 + (i + 1) * cell), min(y1, y0 + (j + 1) * cell), alt, cls)
    for i in range(1, nx):
        g_line(cv, [(x0 + i * cell, y0), (x0 + i * cell, y1)], joint, .25, cls)
    for j in range(1, ny):
        g_line(cv, [(x0, y0 + j * cell), (x1, y0 + j * cell)], joint, .25, cls)


def fountain(cv, rec, region, gx, gy, r=1.0, water=(70, 156, 196)):
    """A round fountain: a stone rim in two tones, the water with a bright edge, a jet the scene animates."""
    px, py = proj(gx, gy)
    g_ellipse(cv, gx, gy, r * 1.25, r * 1.25, (176, 170, 156), STONE)
    g_ellipse(cv, gx, gy, r, r, (226, 230, 232), STONE)
    g_ellipse(cv, gx, gy, r * .82, r * .82, water, GLASS_R)
    g_ellipse(cv, gx - r * .1, gy - r * .1, r * .45, r * .45, mix(water, (230, 246, 252), .4), GLASS_R)
    cv.line([(px, py), (px, py - 2.0)], (236, 246, 252), .5, GLASS_R)
    rec.fountains.append((round(px, 1), round(py, 1)))
    region.occ.append(('c', gx, gy, r * 1.35))


def ground_ellipse_ring(cv, cx, cy, rx, ry, colour, width=.5, cls=STONE):
    g_line(cv, ring_pts(cx, cy, rx, ry, 32) + [ring_pts(cx, cy, rx, ry, 32)[0]], colour, width, cls)


# ................................................................................................................................................ designs
def design_great_park(cv, rec, R):
    """A big park, Central-Park-like: striped great lawn, woods, a meadow, a pond with a stone bridge, winding paths with benches and lamps, a round fountain plaza,
    a playground, a summer house by the water. Trees of several species and heights, autumn colours among them."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    lawn(cv, R, (46, 108, 66), (63, 133, 77), 'x', .65)
    woods = [R.at(.82, .2) + (2.0, 1.4, .5), R.at(.15, .3) + (1.5, 1.7, -.4), R.at(.7, .9) + (1.6, 1.0, .2)]
    for cx, cy, rx, ry, turn in woods:                                                    # the woods: a darker, rougher floor
        g_poly(cv, blob_pts(cx, cy, rx, ry, rnd, .25, 22, turn), (36, 78, 46), GRASS)
    mx, my = R.at(.2, .86)
    g_poly(cv, blob_pts(mx, my, 1.7, 1.1, rnd, .3, 20, .3), (96, 120, 58), GRASS)         # a meadow gone golden, with wild flowers
    for _ in range(26):
        fx, fy = mx + rnd.uniform(-1.6, 1.6), my + rnd.uniform(-1.0, 1.0)
        if ((fx - mx) / 1.7) ** 2 + ((fy - my) / 1.1) ** 2 < .8:
            cv.dot(proj(fx, fy), rnd.choice(((250, 250, 250), (244, 206, 70), (180, 120, 210), (240, 110, 120))), GRASS)
    R.occ.append(('e', mx, my, 1.5, .9))
    # the pond
    pcx, pcy = R.at(.64, .6)
    pr = (2.4, 1.55)
    g_poly(cv, blob_pts(pcx, pcy, pr[0] + .3, pr[1] + .3, random.Random('pond'), .34, 30, .5), (156, 150, 128), STONE)
    pond = blob_pts(pcx, pcy, pr[0], pr[1], random.Random('pond'), .34, 30, .5)
    g_poly(cv, pond, (78, 128, 134), GLASS_R)
    g_poly(cv, blob_pts(pcx - .1, pcy - .1, pr[0] * .78, pr[1] * .72, random.Random('pond'), .34, 30, .5), (60, 108, 128), GLASS_R)
    g_poly(cv, blob_pts(pcx - .3, pcy - .15, pr[0] * .42, pr[1] * .4, rnd, .25, 20, .5), (46, 88, 112), GLASS_R)
    for _ in range(6):
        sx, sy = proj(pcx + rnd.uniform(-1.9, 1.5), pcy + rnd.uniform(-1.1, 1.1))
        cv.line([(sx - 1.2, sy), (sx + 1.1, sy)], (166, 212, 232), .35, GLASS_R)
    for _ in range(5):
        cv.dot(proj(pcx + rnd.uniform(-2, 1.6), pcy + rnd.uniform(-1.1, 1.1)), (84, 150, 78), LEAF)       # lily pads
    for _ in range(4):
        sx, sy = proj(pcx + rnd.uniform(-2.2, 2.0), pcy + rnd.uniform(-1.3, 1.3))
        cv.dot((sx, sy), (246, 246, 240) if rnd.random() < .6 else (124, 92, 60), SIGN)                      # ducks
    R.occ.append(('e', pcx, pcy, pr[0] + .3, pr[1] + .3))
    # the paths
    junction = R.at(.38, .45)
    main = smooth_path([R.at(0, .1), R.at(.17, .24), R.at(.3, .38), junction, R.at(.52, .26), R.at(.76, .26), R.at(1, .16)])
    sec = smooth_path([R.at(.1, 1), R.at(.22, .78), R.at(.3, .6), junction, R.at(.42, .66), R.at(.52, .78), R.at(.8, .88), R.at(1, .94)])
    loop = [(pcx + math.cos(t / 20 * 6.2832) * (pr[0] + .8), pcy + math.sin(t / 20 * 6.2832) * (pr[1] + .8)) for t in range(21)]
    bridge_a, bridge_b = (pcx - .1, pcy - pr[1] - .6), (pcx - .1, pcy + pr[1] + .6)
    for pts in (main, sec):
        path_line(cv, rec, R, pts)
    path_line(cv, rec, R, loop, .9)
    g_line(cv, [bridge_a, bridge_b], (190, 182, 160), 1.5, STONE)                                         # the stone bridge, with its parapets
    for dx in (-.14, .14):
        g_line(cv, [(bridge_a[0] + dx, bridge_a[1] + .5), (bridge_b[0] + dx, bridge_b[1] - .5)], (118, 110, 96), .45, STONE)
    path_line(cv, rec, R, [R.at(.64, .62 + .35), R.at(.64, .98)], .9)
    # the fountain plaza at the junction
    g_ellipse(cv, junction[0], junction[1], 1.55, 1.55, (196, 186, 164), STONE)
    for k in range(8):
        a = k * math.pi / 4
        g_line(cv, [(junction[0] + math.cos(a) * .6, junction[1] + math.sin(a) * .6), (junction[0] + math.cos(a) * 1.5, junction[1] + math.sin(a) * 1.5)], (170, 160, 138), .35, STONE)
    fountain(cv, rec, R, junction[0], junction[1], .85)
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        R.add('bench', junction[0] + math.cos(a) * 1.7, junction[1] + math.sin(a) * 1.7, 'x' if k % 2 else 'y')
    # Small, individually coloured flower beds and lamps around the plaza.
    # Use their own seed so adding details does not rearrange the whole city.
    flowers = random.Random('great-park-plaza-flowers')
    for k in range(8):
        a = k * math.pi / 4
        x, y = junction[0] + math.cos(a) * 2.3, junction[1] + math.sin(a) * 2.3
        if R.free(x, y, .35):
            flower_bed(cv, x - .24, y - .20, x + .24, y + .20, flowers, rows=2)
            R.occ.append(('c', x, y, .3))
            if k % 2 == 0:
                R.add('lamp', x + .34, y + .34)
    # the playground, with rubber surfacing and sand
    pgx, pgy = R.at(.16, .62)
    g_rect(cv, pgx - 1.4, pgy - 1.0, pgx + 1.5, pgy + 1.1, (176, 70, 60), STONE)
    g_rect(cv, pgx - 1.4, pgy - 1.0, pgx - .2, pgy + 1.1, (60, 110, 170), STONE)
    g_ellipse(cv, pgx + .8, pgy + .3, .6, .5, (226, 204, 150), STONE)
    g_line(cv, [(pgx - 1.5, pgy - 1.1), (pgx + 1.6, pgy - 1.1), (pgx + 1.6, pgy + 1.2), (pgx - 1.5, pgy + 1.2), (pgx - 1.5, pgy - 1.1)], (70, 90, 70), .45, LEAF)
    R.occ.append(('r', pgx - 1.6, pgy - 1.2, pgx + 1.7, pgy + 1.3))
    R.add('swing', pgx - .6, pgy - .5)
    R.add('swing', pgx + .6, pgy - .6)
    R.add('slide', pgx - .9, pgy + .6)
    R.add('frame', pgx + .9, pgy + .55)
    # the summer house on the shore and the benches along the paths
    R.add('gazebo', pcx + pr[0] + 1.0, pcy + .2, .5)
    R.occ.append(('c', pcx + pr[0] + 1.0, pcy + .2, .9))
    for pts, step in ((main, 9), (sec, 9)):
        for k in range(4, len(pts) - 3, step):
            a, c = pts[k], pts[k + 1]
            nx, ny = -(c[1] - a[1]), c[0] - a[0]
            ln = math.hypot(nx, ny) or 1
            R.add('bench', a[0] + nx / ln * .34, a[1] + ny / ln * .34, 'x' if abs(c[0] - a[0]) > abs(c[1] - a[1]) else 'y')
            if k % 2 == 0:
                R.add('lamp', a[0] - nx / ln * .3, a[1] - ny / ln * .3)
    # the trees: groves in the woods, specimens on the lawn, a few along the shore
    inside = lambda cx, cy, rx, ry: (lambda gx, gy: ((gx - cx) / rx) ** 2 + ((gy - cy) / ry) ** 2 < 1)
    for cx, cy, rx, ry, turn in woods:
        R.scatter(10, (('oak', 6), ('pine', 3), ('plane', 3), ('maple', 1), ('birch', 1)), inside(cx, cy, rx * .95, ry * .95), gap=.62)
    R.scatter(14, (('oak', 5), ('plane', 4), ('maple', 1), ('ginkgo', 1), ('olive', 2), ('poplar', 1), ('birch', 1)), gap=.95, scale=(.95, 1.3))
    for k in range(5):
        a = rnd.uniform(0, 6.28)
        R.add('tree', pcx + math.cos(a) * (pr[0] + 1.3), pcy + math.sin(a) * (pr[1] + 1.3), rnd.choice(('plane', 'plane', 'birch', 'oak')), 1.1) if R.free(pcx + math.cos(a) * (pr[0] + 1.3), pcy + math.sin(a) * (pr[1] + 1.3), .2) else None
    kerb(cv, R, hedge=(46, 98, 56))
    for k in range(int(R.w / 1.9)):                                                       # an avenue of plane trees along the front edge
        t = (k + .5) / int(R.w / 1.9)
        R.add('tree', x0 + R.w * t, y1 - .12, 'plane', 1.05)
    for k in range(int(R.d / 1.9)):
        t = (k + .5) / int(R.d / 1.9)
        R.add('tree', x1 - .12, y0 + R.d * t, 'plane', 1.05)


def design_sports(cv, rec, R):
    """Playing fields: a football pitch with stripes and its lines, tennis courts with nets, a basketball court, a running track, lamps for the evening, trees along."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    lawn(cv, R, (70, 128, 67), (70, 128, 67), None)
    long_x = R.w >= R.d
    # the pitch
    if long_x:
        px0, px1, py0, py1 = x0 + .35, x0 + R.w * .5, y0 + .5, y1 - .5
    else:
        px0, px1, py0, py1 = x0 + .5, x1 - .5, y0 + .35, y0 + R.d * .5
    g_rect(cv, px0 - .25, py0 - .25, px1 + .25, py1 + .25, (168, 90, 66), STONE)                    # the running track round it
    g_rect(cv, px0 - .12, py0 - .12, px1 + .12, py1 + .12, (190, 106, 78), STONE)
    g_rect(cv, px0, py0, px1, py1, (58, 128, 62), GRASS)
    n = int(((px1 - px0) if long_x else (py1 - py0)) / .4)
    for k in range(1, n, 2):
        if long_x:
            g_rect(cv, px0 + k * (px1 - px0) / n, py0, px0 + (k + 1) * (px1 - px0) / n, py1, (70, 144, 72), GRASS)
        else:
            g_rect(cv, px0, py0 + k * (py1 - py0) / n, px1, py0 + (k + 1) * (py1 - py0) / n, (70, 144, 72), GRASS)
    white = (236, 240, 232)
    g_line(cv, [(px0, py0), (px1, py0), (px1, py1), (px0, py1), (px0, py0)], white, .45, STONE)
    mid = ((px0 + px1) / 2, (py0 + py1) / 2)
    if long_x:
        g_line(cv, [(mid[0], py0), (mid[0], py1)], white, .35, STONE)
        for end, sgn in ((px0, 1), (px1, -1)):
            g_line(cv, [(end, mid[1] - .7), (end + sgn * .45, mid[1] - .7), (end + sgn * .45, mid[1] + .7), (end, mid[1] + .7)], white, .3, STONE)
            R.add('goal', end, mid[1], 'y')
    else:
        g_line(cv, [(px0, mid[1]), (px1, mid[1])], white, .35, STONE)
        for end, sgn in ((py0, 1), (py1, -1)):
            g_line(cv, [(mid[0] - .7, end), (mid[0] - .7, end + sgn * .45), (mid[0] + .7, end + sgn * .45), (mid[0] + .7, end)], white, .3, STONE)
            R.add('goal', mid[0], end, 'x')
    g_ellipse(cv, mid[0], mid[1], .42, .42, white, STONE)
    g_ellipse(cv, mid[0], mid[1], .34, .34, (58, 128, 62), GRASS)
    R.occ.append(('r', px0 - .3, py0 - .3, px1 + .3, py1 + .3))
    # tennis courts and a basketball court in the rest
    if long_x:
        spots = [(x0 + R.w * .56, y0 + .5, x0 + R.w * .77, y0 + R.d * .5 - .1), (x0 + R.w * .78, y0 + .5, x1 - .3, y0 + R.d * .5 - .1), (x0 + R.w * .56, y0 + R.d * .5 + .2, x0 + R.w * .8, y1 - .5)]
    else:
        spots = [(x0 + .4, y0 + R.d * .55, x0 + R.w * .5 - .1, y1 - .3), (x0 + R.w * .5 + .1, y0 + R.d * .55, x1 - .4, y1 - .3)]
    for i, (ax0, ay0, ax1, ay1) in enumerate(spots):
        basket = i == 2 or (not long_x and i == 1)
        base = (190, 110, 70) if basket else (60, 112, 160) if i % 2 == 0 else (58, 130, 90)
        g_rect(cv, ax0, ay0, ax1, ay1, mix(base, (30, 40, 36), .25), STONE)
        cx0, cy0, cx1, cy1 = ax0 + .15, ay0 + .15, ax1 - .15, ay1 - .15
        g_rect(cv, cx0, cy0, cx1, cy1, base, STONE)
        g_line(cv, [(cx0, cy0), (cx1, cy0), (cx1, cy1), (cx0, cy1), (cx0, cy0)], white, .3, STONE)
        cx, cy = (cx0 + cx1) / 2, (cy0 + cy1) / 2
        if basket:
            g_line(cv, [(cx, cy0), (cx, cy1)] if (cx1 - cx0) < (cy1 - cy0) else [(cx0, cy), (cx1, cy)], white, .3, STONE)
            R.add('hoop', cx0 + .05, cy, 'x')
            R.add('hoop', cx1 - .05, cy, 'x')
        else:
            if (cx1 - cx0) >= (cy1 - cy0):
                g_line(cv, [(cx, cy0), (cx, cy1)], white, .3, STONE)
                R.add('net', cx, cy, 'y')
            else:
                g_line(cv, [(cx0, cy), (cx1, cy)], white, .3, STONE)
                R.add('net', cx, cy, 'x')
            g_line(cv, [(cx0 + (cx1 - cx0) * .25, cy0), (cx0 + (cx1 - cx0) * .25, cy1)], white, .25, STONE)
            g_line(cv, [(cx0 + (cx1 - cx0) * .75, cy0), (cx0 + (cx1 - cx0) * .75, cy1)], white, .25, STONE)
        R.occ.append(('r', ax0 - .1, ay0 - .1, ax1 + .1, ay1 + .1))
        R.add('lamp', ax0 - .05, ay0 - .05)
    R.add('lamp', px0 - .35, py0 - .35)
    R.add('lamp', px1 + .35, py1 + .35)
    kerb(cv, R, hedge=(46, 98, 56))
    for k in range(int(R.w / 1.6)):
        t = (k + .5) / int(R.w / 1.6)
        R.add('tree', x0 + R.w * t, y1 - .14, rnd.choice(('plane', 'plane', 'olive')), 1.0)
    R.scatter(5, (('oak', 2), ('plane', 2), ('pine', 1)), gap=.9)


def design_formal(cv, rec, R):
    """A formal garden: a paved cross of paths with a fountain in the middle, four hedged beds of flowers, topiary at the corners, benches at the ends."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    lawn(cv, R, (37, 94, 64), (51, 113, 76), 'y', .7)
    pave = (196, 184, 160)
    g_rect(cv, cx - .32, y0, cx + .32, y1, pave, STONE)
    g_rect(cv, x0, cy - .32, x1, cy + .32, pave, STONE)
    g_ellipse(cv, cx, cy, 1.15, 1.15, pave, STONE)
    ground_ellipse_ring(cv, cx, cy, 1.05, 1.05, (150, 138, 116), .35)
    fountain(cv, rec, R, cx, cy, .62)
    palettes = (((230, 90, 110), (246, 210, 80)), ((250, 250, 250), (150, 110, 200)), ((240, 130, 50), (246, 210, 80)), ((220, 60, 80), (250, 250, 250)))
    for i, (qx0, qy0, qx1, qy1) in enumerate(((x0 + .35, y0 + .35, cx - .45, cy - .45), (cx + .45, y0 + .35, x1 - .35, cy - .45), (x0 + .35, cy + .45, cx - .45, y1 - .35), (cx + .45, cy + .45, x1 - .35, y1 - .35))):
        flower_bed(cv, qx0 + .1, qy0 + .1, qx1 - .1, qy1 - .1, rnd, palettes[i], 3)
        for a, b in (((qx0, qy0), (qx1, qy0)), ((qx1, qy0), (qx1, qy1)), ((qx1, qy1), (qx0, qy1)), ((qx0, qy1), (qx0, qy0))):
            g_line(cv, [a, b], (36, 84, 46), .9, LEAF)
        R.add('topiary', (qx0 + qx1) / 2, (qy0 + qy1) / 2)
    for gx, gy, axis in ((cx, y0 + .5, 'x'), (cx, y1 - .5, 'x'), (x0 + .5, cy, 'y'), (x1 - .5, cy, 'y')):
        R.add('bench', gx + (.55 if axis == 'x' else 0), gy + (0 if axis == 'x' else .55), axis)
    for gx, gy in ((x0 + .15, y0 + .15), (x1 - .15, y0 + .15), (x0 + .15, y1 - .15), (x1 - .15, y1 - .15)):
        R.add('lamp', gx, gy)
    kerb(cv, R, hedge=(40, 92, 52))


def design_plaza(cv, rec, R):
    """A paved square: a chequer of stone, rings round a fountain, plane trees in pits, benches facing the water, cafe tables under umbrellas, a kiosk."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    paving(cv, R, (176, 166, 146), (186, 176, 154), (140, 130, 112), .5)
    r = min(R.w, R.d) * .3
    for k, col in enumerate(((150, 136, 116), (200, 190, 168), (164, 150, 128))):
        g_ellipse(cv, cx, cy, r * (1.15 - k * .13), r * (1.15 - k * .13), col, STONE)
    if R.w >= 3.5 and R.d >= 3.5 and random.Random(f'plaza-art:{R.rect}').random() < .48:
        R.add('sculpture', cx, cy)
        R.occ.append(('c', cx, cy, .65))
    else:
        fountain(cv, rec, R, cx, cy, min(.85, r * .6))
    for gx, gy in ((x0 + .7, y0 + .7), (x1 - .7, y0 + .7), (x0 + .7, y1 - .7), (x1 - .7, y1 - .7), (cx, y0 + .6), (cx, y1 - .6), (x0 + .6, cy), (x1 - .6, cy)):
        if R.w < 3 and (gx, gy) not in ((x0 + .7, y0 + .7), (x1 - .7, y1 - .7)):
            continue
        g_rect(cv, gx - .26, gy - .26, gx + .26, gy + .26, (70, 56, 46), PAVE)
        R.add('tree', gx, gy, rnd.choice(('plane', 'plane', 'olive', 'palm')), 1.0)
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        R.add('bench', cx + math.cos(a) * (r + .5), cy + math.sin(a) * (r + .5), 'x' if k % 2 else 'y')
    for k in range(4):                                                                  # cafe tables with their umbrellas, between the benches and the trees
        a = k * math.pi / 2 + .38
        gx, gy = cx + math.cos(a) * (r + .55), cy + math.sin(a) * (r + .55)
        if x0 + .4 < gx < x1 - .4 and y0 + .4 < gy < y1 - .4 and all(math.hypot(gx - it[1], gy - it[2]) > .55 for it in R.items):
            R.add('table', gx, gy, rnd.choice(((200, 70, 60), (240, 196, 70), (70, 140, 200), (232, 232, 236), (70, 160, 120))))
    if R.w >= 3.5 and R.d >= 3.5:
        R.add('box', x1 - 1.4, y0 + .35, x1 - .45, y0 + 1.1, 3.0, (236, 224, 200), (176, 70, 56))
    R.add('lamp', x0 + .25, y0 + .25)
    R.add('lamp', x1 - .25, y1 - .25)
    if R.w >= 3.5 and R.d >= 3.5 and random.Random(f'plaza-clock:{R.rect}').random() < .35:
        R.add('clock', x0 + .42, y1 - .42)
    kerb(cv, R)


def design_market(cv, rec, R):
    """A market square: paving, two rows of striped stalls with goods, crates, a few trees at the edge, people moving between the stalls."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    paving(cv, R, (166, 152, 130), (176, 162, 138), (130, 118, 100), .5)
    palettes = (((214, 70, 60), (244, 240, 230)), ((60, 130, 200), (244, 240, 230)), ((240, 180, 50), (244, 240, 230)), ((70, 160, 100), (244, 240, 230)), ((200, 80, 150), (244, 240, 230)))
    long_x = R.w >= R.d
    n = max(2, int((R.w if long_x else R.d) / 1.0))
    for row, off in enumerate((.32, .66)):
        for k in range(n):
            t = (k + .5) / n
            gx, gy = (x0 + R.w * t, y0 + R.d * off) if long_x else (x0 + R.w * off, y0 + R.d * t)
            if k % 3 == 2 and row == 0:
                continue
            c1, c2 = palettes[(k + row * 2) % len(palettes)]
            R.add('stall', gx, gy, 'x' if long_x else 'y', c1, c2)
            R.occ.append(('c', gx, gy, .5))
    aisle = [(x0 + .3, y0 + R.d * .5), (x1 - .3, y0 + R.d * .5)] if long_x else [(x0 + R.w * .5, y0 + .3), (x0 + R.w * .5, y1 - .3)]
    g_line(cv, aisle, (150, 136, 114), 1.2, PAVE)
    rec.paths.append((tuple(aisle[0]), tuple(aisle[1])))
    for _ in range(6):                                                                    # crates and flowers on the ground
        fx, fy = rnd.uniform(x0 + .3, x1 - .3), rnd.uniform(y0 + .3, y1 - .3)
        g_rect(cv, fx, fy, fx + .2, fy + .14, rnd.choice(((150, 100, 60), (220, 90, 70), (240, 200, 70))), PAVE)
    R.scatter(3, (('plane', 1), ('olive', 1)), gap=1.2, margin=.3)
    kerb(cv, R)


def design_pocket(cv, rec, R):
    """A small park: lawn, a curved path, a bench, two or three trees of different kinds, a flower bed or a little fountain."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    palettes = (((42, 124, 65), (62, 151, 83)), ((108, 124, 43), (142, 150, 59)),
                ((30, 111, 101), (47, 141, 122)), ((80, 108, 61), (109, 140, 78)))
    grass, stripe = random.Random(f'pocket-colour:{R.rect}').choice(palettes)
    lawn(cv, R, grass, stripe, 'x' if R.w >= R.d else 'y', .65)
    if R.w >= R.d:
        pts = smooth_path([(x0 + .1, y0 + R.d * .6), (x0 + R.w * .35, y0 + R.d * .35), (x0 + R.w * .65, y0 + R.d * .65), (x1 - .1, y0 + R.d * .4)])
    else:
        pts = smooth_path([(x0 + R.w * .6, y0 + .1), (x0 + R.w * .35, y0 + R.d * .35), (x0 + R.w * .65, y0 + R.d * .65), (x0 + R.w * .4, y1 - .1)])
    path_line(cv, rec, R, pts, 1.0)
    big = R.w >= 2.5 and R.d >= 2.5
    if big and rnd.random() < .5:
        fx, fy = (x0 + x1) / 2, (y0 + y1) / 2
        g_ellipse(cv, fx, fy, .6, .6, (190, 178, 156), STONE)
        fountain(cv, rec, R, fx, fy, .38)
    elif big:
        flower_bed(cv, x0 + R.w * .55, y0 + R.d * .1, x0 + R.w * .9, y0 + R.d * .3, rnd)
    mid = pts[len(pts) // 2]
    R.add('bench', mid[0] + .3, mid[1] - .3, 'x')
    R.scatter(3 if big else 2, (('oak', 3), ('plane', 3), ('maple', 1), ('cherry', 1), ('birch', 2), ('olive', 2)), gap=.85, scale=(.95, 1.2))
    R.add('lamp', x0 + .2, y1 - .2)
    kerb(cv, R, hedge=(46, 98, 56))


def design_garden(cv, rec, R):
    """Community allotments and an orchard: rows of vegetable beds, little sheds, a water butt, fruit trees in a grid."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    lawn(cv, R, (96, 119, 55), (112, 139, 65), 'x', .65)
    plots = [(x0 + .3, y0 + .3, x0 + R.w * .55, y1 - .3), (x0 + R.w * .6, y0 + .3, x1 - .3, y0 + R.d * .5)]
    for px0, py0, px1, py1 in plots:
        g_rect(cv, px0, py0, px1, py1, (110, 84, 60), GRASS)
        rows = int((py1 - py0) / .26)
        for k in range(rows):
            col = rnd.choice(((70, 130, 60), (104, 156, 64), (150, 60, 70), (60, 110, 54), (200, 170, 60)))
            g_line(cv, [(px0 + .08, py0 + (k + .5) * (py1 - py0) / rows), (px1 - .08, py0 + (k + .5) * (py1 - py0) / rows)], col, .5, LEAF)
        R.occ.append(('r', px0, py0, px1, py1))
    R.add('box', x0 + R.w * .58, y0 + R.d * .62, x0 + R.w * .72, y0 + R.d * .76, 2.4, (196, 160, 110), (120, 80, 60))
    R.occ.append(('r', x0 + R.w * .56, y0 + R.d * .6, x0 + R.w * .74, y0 + R.d * .78))
    R.scatter(5, (('cherry', 1), ('olive', 3), ('plane', 1)), lambda gx, gy: gx > x0 + R.w * .58 and gy > y0 + R.d * .55, gap=.8, scale=(.8, 1.0))
    kerb(cv, R, hedge=(46, 98, 56))


def design_boulevard(cv, rec, R):
    """A tree-lined promenade: a wide paved walk down the middle, two rows of trees of alternating kinds, benches and lamps, flower beds, lawn strips at the sides."""
    x0, y0, x1, y1 = R.rect
    rnd = R.rnd
    long_x = R.w >= R.d
    lawn(cv, R, (52, 104, 58), (58, 114, 62), 'x' if long_x else 'y', .5)
    if long_x:
        mid = (y0 + y1) / 2
        g_rect(cv, x0, mid - .5, x1, mid + .5, (176, 168, 150), PAVE)
        g_line(cv, [(x0, mid - .5), (x1, mid - .5)], (140, 132, 116), .4, PAVE)
        g_line(cv, [(x0, mid + .5), (x1, mid + .5)], (140, 132, 116), .4, PAVE)
        rec.paths.append(((x0, mid), (x1, mid)))
        for side in (-.95, .95):
            R.rows((x0 + .2, mid + side), (x1 - .2, mid + side), 1.7, ('plane', 'plane', 'plane', 'ginkgo') if side < 0 else ('plane', 'plane', 'maple', 'plane'), offset=.0 if side < 0 else .5)
        for k in range(int(R.w / 3)):
            gx = x0 + (k + .5) * R.w / int(R.w / 3) + .8
            R.add('bench', gx, mid + .62, 'x')
            R.add('lamp', gx + 1.2, mid - .62)
            if k % 2:
                flower_bed(cv, gx - .5, y0 + .2, gx + .5, y0 + .5, rnd)
        variant = rnd.choice(('avenue', 'gardens', 'kiosk', 'fountain', 'avenue'))                    # no two stretches of the same promenade alike
        cx = (x0 + x1) / 2
        if variant == 'gardens':
            for k in range(3):
                flower_bed(cv, x0 + .3 + k * 1.2, y1 - .62, x0 + 1.3 + k * 1.2, y1 - .22, rnd, rnd.choice((((230, 90, 110), (250, 250, 250)), ((246, 210, 80), (150, 110, 200)), ((240, 130, 50), (246, 210, 80)))), 2)
        elif variant == 'kiosk':
            R.add('box', cx - .4, y1 - .95, cx + .4, y1 - .45, 3.0, rnd.choice(((236, 224, 200), (190, 210, 200), (226, 196, 176))), (176, 70, 56))
            R.add('table', cx - 1.3, y1 - .75, rnd.choice(((200, 70, 60), (70, 140, 200))))
            R.add('table', cx + 1.3, y1 - .75, rnd.choice(((240, 196, 70), (232, 232, 236))))
        elif variant == 'fountain':
            g_ellipse(cv, cx, mid, 1.0, .75, (190, 180, 158), PAVE)
            fountain(cv, rec, R, cx, mid, .5)
    else:
        mid = (x0 + x1) / 2
        g_rect(cv, mid - .5, y0, mid + .5, y1, (176, 168, 150), PAVE)
        rec.paths.append(((mid, y0), (mid, y1)))
        for side in (-.95, .95):
            R.rows((mid + side, y0 + .2), (mid + side, y1 - .2), 1.7, ('plane', 'plane', 'ginkgo'), offset=.0 if side < 0 else .5)
        for k in range(int(R.d / 3)):
            gy = y0 + (k + .5) * R.d / int(R.d / 3) + .8
            R.add('bench', mid + .62, gy, 'y')
            R.add('lamp', mid - .62, gy + 1.2)
    kerb(cv, R)


def design_lawn(cv, rec, R):
    """A plain lawn with a few specimen trees and a path: for odd corners."""
    x0, y0, x1, y1 = R.rect
    lawn(cv, R, (50, 104, 56), (56, 114, 62), 'x' if R.w >= R.d else 'y', .45)
    if min(R.w, R.d) >= 1.2:
        pts = [(x0 + .3, y1 - .35), (x1 - .3, y0 + .35)]
        path_line(cv, rec, R, pts, .9)
    R.scatter(max(1, int(R.w * R.d / 4.5)), (('oak', 3), ('plane', 3), ('maple', 1), ('ginkgo', 1), ('birch', 2)), gap=.9)
    kerb(cv, R, hedge=(46, 98, 56))


DESIGNS = {'great_park': design_great_park, 'sports': design_sports, 'formal': design_formal, 'plaza': design_plaza, 'market': design_market, 'pocket': design_pocket,
           'garden': design_garden, 'boulevard': design_boulevard, 'lawn': design_lawn}


# ......................................................................................................................................... the plan of the open ground
REGION_PLAN = (                                     # the parks of the clock's corner: a design and the blocks it covers (they must all be open blocks in make_plan)
    ('great_park', ((7, 10), (8, 10), (7, 11), (8, 11))),
    ('market', ((9, 10),)),
    ('plaza', ((9, 11),)),
    ('sports', ((7, 9), (8, 9))),
    ('garden', ((10, 11),)),
    ('formal', ((6, 10),)),
    ('boulevard', ((8, 12), (9, 12))),
)
OPEN_KINDS = ('park', 'plaza', 'lot', 'promenade')


def pick_design(b, rnd):
    """A design for one open piece that no plan covers, by what it is and how big: a plaza is a square of one of a few kinds, a promenade an avenue, a small lot a
    pocket park or a lawn."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    area = w * d
    if b.kind == 'promenade':
        return 'boulevard'
    if min(w, d) < 1.4:
        return 'lawn'
    if b.kind == 'plaza' and area >= 12:
        return rnd.choice(('plaza', 'market', 'plaza', 'formal'))
    if b.kind == 'park' and area >= 12:
        return rnd.choice(('pocket', 'garden', 'formal'))
    if area >= 6:
        return rnd.choice(('pocket', 'plaza', 'lawn'))
    return rnd.choice(('lawn', 'pocket'))


def plan_regions(buildings, seed=2026):
    """The open ground of the plan as regions: the planned parks (several blocks and the streets between them become one), then one region for every other open
    piece. Returns the regions and the street cells that a planned park has taken over: [(x0, y0, x1, y1)]."""
    pieces = {}
    for b in buildings:
        if b.kind in OPEN_KINDS:
            pieces.setdefault(block_of(b.x0 + .01, b.y0 + .01), []).append(b)
    regions, used, covered = [], set(), []
    for design, blocks in REGION_PLAN:
        group = [pieces.get(bk) for bk in blocks]
        if not all(g and len(g) == 1 and id(g[0]) not in used and g[0].kind == 'park' and abs(g[0].x1 - g[0].x0 - 4) < 1e-6 and abs(g[0].y1 - g[0].y0 - 4) < 1e-6 for g in group):
            continue
        rect = (min(g[0].x0 for g in group), min(g[0].y0 for g in group), max(g[0].x1 for g in group), max(g[0].y1 for g in group))
        regions.append(Region(design, rect, blocks, seed))
        used.update(id(g[0]) for g in group)
        for (bx, by) in blocks:
            if (bx + 1, by) in blocks:
                covered.append((5 * bx + 5, 5 * by + 1, 5 * bx + 6, 5 * by + 5))
            if (bx, by + 1) in blocks:
                covered.append((5 * bx + 1, 5 * by + 5, 5 * bx + 5, 5 * by + 6))
            if all(k in blocks for k in ((bx + 1, by), (bx, by + 1), (bx + 1, by + 1))):
                covered.append((5 * bx + 5, 5 * by + 5, 5 * bx + 6, 5 * by + 6))
    rnd = random.Random(f'regions:{seed}')
    for bk, group in sorted(pieces.items()):
        for b in group:
            if id(b) in used:
                continue
            regions.append(Region(pick_design(b, rnd), (b.x0, b.y0, b.x1, b.y1), [bk], seed))
    return regions, covered


CAR_PAINT = ((226, 228, 232), (226, 228, 232), (206, 208, 214), (34, 36, 46), (34, 36, 46), (130, 134, 146), (170, 174, 184), (130, 44, 44), (56, 78, 124), (60, 96, 84), (200, 160, 70))
STREET_TREES = ('plane', 'plane', 'plane', 'olive', 'oak', 'oak', 'birch', 'ginkgo', 'maple')


def street_props(buildings, covered, props, seed=2026):
    """What stands along the streets: trees on the far pavement (one kind to a street), bus shelters, planters, parked cars along the kerbs. Each is a prop of the
    block its street leads into, so that it is painted in front of what is behind it and behind what is in front."""
    blocks = {block_of(b.x0 + .01, b.y0 + .01) for b in buildings if b.kind in ('city', 'hero') + OPEN_KINDS}

    def covered_at(gx, gy):
        return any(c[0] - .05 <= gx <= c[2] + .05 and c[1] - .05 <= gy <= c[3] + .05 for c in covered)

    def on_water(axis, n, s):
        return (axis == 'x' and CANAL[0] <= 5 * n < CANAL[1]) or (axis == 'y' and CANAL[0] <= s < CANAL[1])

    def put(item):
        bk = block_of(item[1], item[2])
        if bk in blocks:
            props.setdefault(bk, []).append(item)

    for axis in ('x', 'y'):
        for n in range(GMIN // 5, GMAX // 5):                                            # the street 5 n: gy = 5 n when it runs along x, gx = 5 n when along y
            tone = random.Random(f'street-species:{axis}:{n}:{seed}').choice(STREET_TREES)
            for m in range(GMIN // 5, GMAX // 5):                                        # one block's length of it, from 5 m + 1 to 5 m + 5
                a0 = 5 * m + 1
                cx, cy = proj(a0 + 2, 5 * n + .5) if axis == 'x' else proj(5 * n + .5, a0 + 2)
                if not (-24 < cx < WORLD[0] + 24 and 34 < cy < WORLD[1] + 40):
                    continue
                local = random.Random(f'street:{axis}:{n}:{m}:{seed}')
                trees = local.random() < .78
                s = a0 + .3 + local.uniform(0, .6)
                while s < a0 + 3.8:
                    gx, gy = (s, 5 * n + .13) if axis == 'x' else (5 * n + .13, s)
                    if not covered_at(gx, gy) and not on_water(axis, n, s):
                        if trees:
                            put(('tree', gx, gy, tone if local.random() < .85 else local.choice(STREET_TREES), local.uniform(.78, .98)))
                        elif local.random() < .45:
                            put(('planter', gx, gy, axis, .8))
                    s += local.uniform(1.5, 2.2)
                if trees and local.random() < .2:                                         # a bus shelter on the near pavement
                    s = a0 + local.uniform(1.2, 2.8)
                    gx, gy = (s, 5 * n + .86) if axis == 'x' else (5 * n + .86, s)
                    if not covered_at(gx, gy) and not on_water(axis, n, s):
                        put(('busstop', gx, gy, axis))
                for edge in (.2, .8):                                                     # parked cars along the kerbs, with gaps
                    if local.random() < .5:
                        continue
                    s = a0 + local.uniform(.2, .9)
                    while s < a0 + 3.7:
                        if local.random() < .6:
                            gx, gy = (s, 5 * n + edge) if axis == 'x' else (5 * n + edge, s)
                            if not covered_at(gx, gy) and not on_water(axis, n, s):
                                put(('parked', gx, gy, axis, local.choice(CAR_PAINT)))
                        s += local.uniform(.5, .66)


HERO_WALL = {                       # (street, high) wall colours of the three data buildings; the windows are not painted here: the scene draws them
    'codex': ((16, 34, 76), (64, 108, 190)), 'claude': ((104, 94, 82), (190, 178, 160)), 'small': ((58, 60, 64), (118, 118, 116)),
}


def mascot(name, height):
    im = Image.open(ASSETS / f'{name}-pixel.png').convert('RGBA')
    im = im.crop(im.getbbox())
    return im.resize((max(1, round(im.width * height / im.height)), height), Image.Resampling.NEAREST)


def skewed(layer_size, image, p0, edge, height):
    """`image` stood on a vertical board: its bottom-left corner at `p0`, its bottom edge running along `edge`, its height `height` (all in layer pixels):
    the isometric view of a sign on a roof."""
    iw, ih = image.size
    hx, hy = edge
    coeffs = (iw / hx, 0, -p0[0] * iw / hx, -hy * ih / (hx * height), ih / height, ((height - p0[1]) + hy * p0[0] / hx) * ih / height)
    return image.transform(layer_size, Image.AFFINE, coeffs, resample=Image.NEAREST)


def iso_board(cv, centre, plane, width, height, z_base, accent, image):
    """A lit board on two posts standing on a roof at cell `centre`, in the plane facing +x ('right') or +y ('left'), in the city's own projection, with
    `image` skewed onto it, a bright frame and a little thickness. It is its own light: the SIGN class is not shaded."""
    cx, cy = centre
    half = width / 2
    if plane == 'right':
        (lx, ly), (rx, ry), back = proj(cx, cy + half, z_base), proj(cx, cy - half, z_base), (-1.0, -.55)
    else:
        (lx, ly), (rx, ry), back = proj(cx - half, cy, z_base), proj(cx + half, cy, z_base), (1.0, -.55)
    lift = 4
    for k in (.14, .86):
        px, py = lx + (rx - lx) * k, ly + (ry - ly) * k
        cv.line([(px, py), (px, py - lift)], (138, 140, 152), .75, METAL)
    frame = [(lx, ly - lift), (rx, ry - lift), (rx, ry - lift - height), (lx, ly - lift - height)]
    cv.poly([(x + back[0], y + back[1]) for x, y in frame], (14, 16, 22), SIGN)
    cv.poly(frame, mix(accent, (28, 30, 38), .35), SIGN)
    pad = .1
    a, c = lerp((lx, ly - lift), (rx, ry - lift), pad), lerp((lx, ly - lift), (rx, ry - lift), 1 - pad)
    margin = height * pad
    cv.poly([(a[0], a[1] - margin), (c[0], c[1] - margin), (c[0], c[1] - height + margin), (a[0], a[1] - height + margin)], (12, 14, 22), SIGN)
    inner_h = (height - 2 * margin) * .78
    inner_w = min(abs(c[0] - a[0]) * .84, inner_h * image.width / image.height * .95)
    frac = inner_w / abs(c[0] - a[0])
    start = lerp(a, c, .5 - frac / 2)
    edge = ((c[0] - a[0]) * frac, (c[1] - a[1]) * frac)
    base = (start[0], start[1] - margin - (height - 2 * margin - inner_h) / 2)
    big = image.resize((image.width * 8, image.height * 8), Image.Resampling.NEAREST)
    s = cv.s
    layer = skewed(cv.albedo.size, big, (base[0] * s, base[1] * s), (edge[0] * s, edge[1] * s), inner_h * s)
    alpha = layer.getchannel('A').point(lambda v: 255 if v > 127 else 0)
    cv.albedo.paste(layer.convert('RGB'), mask=alpha)
    cv.cls.paste(SIGN, mask=alpha)
    if cv.bid:
        cv.ids.paste(id_colour(cv.bid), mask=alpha)


def roof_sign_panel(cv, start, end, z, height, accent, image, *, rear=False):
    """A small illuminated panel physically fastened to one roof edge.

    The artwork follows that edge's isometric perspective.  Its bottom is on
    the roof parapet, so four panels can wrap a building without posts or a
    disconnected, floating billboard.
    """
    a, b = proj(*start, z), proj(*end, z)
    if a[0] > b[0]:
        a, b = b, a
    if b[0] - a[0] < 1:
        return
    frame = [a, b, (b[0], b[1] - height), (a[0], a[1] - height)]
    if rear:
        # The back of an outward-facing sign is its metal housing, not a
        # second illuminated logo. Cross braces make its mounting readable.
        cv.poly(frame, (42, 48, 57), METAL)
        cv.line([frame[0], frame[2]], (99, 111, 122), .55, METAL)
        cv.line([frame[1], frame[3]], (99, 111, 122), .55, METAL)
        for t in (.14, .86):
            foot = lerp(a, b, t)
            cv.line([foot, (foot[0], foot[1] - height)], (130, 139, 147), .6, METAL)
        return
    cv.poly(frame, mix(accent, (22, 27, 35), .48), METAL)
    inset = .045
    left, right = lerp(a, b, inset), lerp(a, b, 1 - inset)
    margin = .38
    cv.poly([(left[0], left[1] - margin), (right[0], right[1] - margin),
             (right[0], right[1] - height + margin), (left[0], left[1] - height + margin)],
            (15, 22, 31), METAL)
    cv.line([(left[0], left[1] - height + margin), (right[0], right[1] - height + margin)], accent, .35, SIGN)
    inner_h = height - 1.25
    inner_w = min((right[0] - left[0]) * .75, inner_h * image.width / image.height)
    fraction = inner_w / (right[0] - left[0])
    base = lerp(left, right, .5 - fraction / 2)
    edge = ((right[0] - left[0]) * fraction, (right[1] - left[1]) * fraction)
    base = (base[0], base[1] - .60)
    s = cv.s
    big = image.resize((image.width * 8, image.height * 8), Image.Resampling.NEAREST)
    layer = skewed(cv.albedo.size, big, (base[0] * s, base[1] * s),
                   (edge[0] * s, edge[1] * s), inner_h * s)
    alpha = layer.getchannel('A').point(lambda value: 255 if value > 127 else 0)
    cv.albedo.paste(layer.convert('RGB'), mask=alpha)
    cv.cls.paste(SIGN, mask=alpha)
    if cv.bid:
        cv.ids.paste(id_colour(cv.bid), mask=alpha)


def paint_hero(cv, rec, h):
    """A data building's body: walls, ledges between its floors, pilasters, setbacks, a crown with a red beacon and a lit sign on its roof. Its windows are
    NOT painted: the scene draws every one, dark or lit by the reading, on whole pixels (their positions are in the atlas's numbers)."""
    cv.bid = h.id
    bottom, top = HERO_WALL[h.name]
    rnd = random.Random('hero:' + h.name)
    boxes = h.boxes()
    for index, (x0, y0, x1, y1, z0, z1) in enumerate(boxes):
        (la, lb), (ra, rb) = faces_base(x0, y0, x1, y1)
        floors = round((z1 - z0) / h.floor_h)
        for side, (a, c), cls in ((0, (la, lb), WALL_L), (1, (ra, rb), WALL_R)):
            for f in range(floors):
                za, zb = z0 + f * h.floor_h, z0 + (f + 1) * h.floor_h
                u = za / h.top
                colour = mix(bottom, top, u ** .85)
                if h.small and f % 2:
                    colour = mix(colour, (36, 40, 48), .35)                                   # every other floor a shade darker
                cv.poly([(a[0], a[1] - za), (c[0], c[1] - za), (c[0], c[1] - zb), (a[0], a[1] - zb)], colour, cls)
                # a ledge between floors: its own faint light (the SIGN class is not darkened), so the towers keep their shape at night
                if h.small:
                    ledge = (96, 96, 100)
                elif h.name == 'claude':
                    # Stone courses group the floors of the stepped tower.
                    ledge = mix(colour, (225, 215, 192), .48 if f % 3 == 2 else .15)
                else:
                    # Cooler, slimmer metal bands on the glass tower.
                    ledge = mix(colour, (160, 199, 225), .30 if f % 2 else .18)
                cv.line([(a[0], a[1] - zb), (c[0], c[1] - zb)], ledge, .8, SIGN)
            span = abs(c[0] - a[0])
            cols = SMALL_COLS if h.small else HERO_COLS
            for k in range(cols + 1):                                                           # pilasters between the window columns
                p = lerp(a, c, k / cols)
                mullion = mix(top, (196, 215, 228) if h.name == 'codex' else (225, 212, 188),
                              .52 if (h.name == 'codex' and k % 2 == 0) else .20)
                cv.line([(p[0], p[1] - z0), (p[0], p[1] - z1)], mullion, .65, cls)
            if not h.small and h.name == 'codex':
                # A steel exoskeleton, set into the glass and interrupted by
                # the lit quota windows drawn above it at runtime.
                p0, p1 = lerp(a, c, .08), lerp(a, c, .92)
                for f in range(0, floors - 2, 4):
                    lo, hi = z0 + f * h.floor_h, z0 + min(f + 4, floors) * h.floor_h
                    for line in ([(p0[0], p0[1] - lo), (p1[0], p1[1] - hi)],
                                 [(p1[0], p1[1] - lo), (p0[0], p0[1] - hi)]):
                        cv.line(line, (123, 157, 179), .65, METAL)
        paint_roof(cv, box_faces(x0, y0, x1, y1, z0, z1)[2], 'glass' if h.name == 'codex' else 'concrete', rnd, 0.0,
                   {'palette': (bottom, top), 'roof_material': 'zinc', 'roof_colour': mix(top, (120, 130, 150), .3)})
        edge = mix(bottom, (0, 0, 0), .55)
        for (a, c), cls in (((la, lb), WALL_L), ((ra, rb), WALL_R)):
            cv.line([(a[0], a[1] - z0), (a[0], a[1] - z1)], edge, .5, cls)
            cv.line([(c[0], c[1] - z0), (c[0], c[1] - z1)], edge, .5, cls)
            cv.line([(a[0], a[1] - z0), (c[0], c[1] - z0)], edge, 1.0, cls)
    x0, y0, x1, y1, z0, z1 = boxes[-1]
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if h.small:
        corner = proj(x1, y1)
        for f in range(h.floors):                                                               # a ruler of five marks on the corner
            lo, hi = corner[1] - f * h.floor_h - 1.2, corner[1] - (f + 1) * h.floor_h + 1.2
            cv.rect(((corner[0] - .8, hi), (corner[0] + .8, lo)), (196, 192, 180), WALL_R)
        for ox, oy in ((-1.0, -1.0), (1.0, 1.0)):                                               # rooftop machinery: no sign, no beacon, nothing that calls the eye
            paint_box(cv, rec, h, mx + ox - .35, my + oy - .35, mx + ox + .35, my + oy + .35, z1, z1 + 2.2, 'concrete', rnd, windows=False)
    else:
        accent = (96, 150, 255) if h.name == 'codex' else (232, 128, 84)
        sized = max(.5, (x1 - x0) / 2 - .5)
        icon = mascot(h.name, 10)
        # The two far panels sit behind the rooftop crown; the near panels
        # are drawn afterwards. All four rest directly on the same parapet.
        rear_edges = (((x0, y0), (x1, y0)), ((x0, y0), (x0, y1)))
        front_edges = (((x0, y1), (x1, y1)), ((x1, y0), (x1, y1)))
        for start, end in rear_edges:
            roof_sign_panel(cv, start, end, z1, 8.0, accent, icon, rear=True)
        if h.name == 'claude':
            # A distinct stone pyramidal crown, inspired by stepped Art Deco
            # roofs. It is above, and does not cover, the quota windows.
            apex = proj(mx, my, z1 + 8)
            a, c, d = proj(x0, y1, z1), proj(x1, y1, z1), proj(x1, y0, z1)
            cv.poly([a, c, apex], mix(top, (27, 31, 38), .35), WALL_L)
            cv.poly([c, d, apex], mix(top, (211, 202, 180), .34), WALL_R)
            for edge in ((a, apex), (c, apex), (d, apex)):
                cv.line(list(edge), mix(top, (223, 214, 194), .45), .6, METAL)
        else:
            # A narrow metal-and-glass lantern instead of the stone crown.
            paint_box(cv, rec, h, mx - sized * .55, my - sized * .55, mx + sized * .55, my + sized * .55, z1, z1 + 4, h.material, rnd, windows=False,
                      style={'palette': (bottom, top), 'piers': True})
            paint_box(cv, rec, h, mx - .3, my - .3, mx + .3, my + .3, z1 + 4, z1 + 8, h.material, rnd, windows=False, style={'palette': (bottom, top)})
        px, py = proj(mx, my, z1 + 8)
        cv.line([(px, py), (px, py - 10)], (210, 210, 232), .5, METAL)
        red_light(cv, rec, h, px, py - 10)
        for start, end in front_edges:
            roof_sign_panel(cv, start, end, z1, 8.0, accent, icon)
    cv.bid = 0


# ------------------------------------------------------------------------------------------------------------------------------- the ground
def strip(gx0, gy0, gx1, gy1):
    return [proj(gx0, gy0), proj(gx1, gy0), proj(gx1, gy1), proj(gx0, gy1)]


def paint_ground(cv, rec):
    """The ground of a city that runs to the top of the picture: pavement, the streets with their lane marks and crosswalks, the lamps at the corners of the
    blocks, and one canal across the lower part with its quays and two bridges."""
    lo, hi = GMIN, GMAX
    cv.poly(strip(lo, lo, hi, hi), (74, 76, 82), PAVE)
    for m in range(lo // 5, hi // 5):                                                   # streets along y (gx = 5m) and along x (gy = 5n)
        cv.poly(strip(5 * m, lo, 5 * m + 1, hi), (24, 26, 32), ASPHALT)
    for n in range(lo // 5, hi // 5):
        cv.poly(strip(lo, 5 * n, hi, 5 * n + 1), (24, 26, 32), ASPHALT)
    for m in range(lo // 5, hi // 5):                                                   # dashed centre lines and crosswalks
        for n in range(lo // 5, hi // 5):
            gx, gy = 5 * m, 5 * n
            x0, y0 = proj(gx, gy)
            if not (-30 < x0 < WORLD[0] + 30 and 0 < y0 < WORLD[1] + 30):
                continue
            for k in range(1, 5):
                cv.line([proj(gx + k + .15, gy + .5), proj(gx + k + .55, gy + .5)], (150, 130, 96), .5, ASPHALT)
                cv.line([proj(gx + .5, gy + k + .15), proj(gx + .5, gy + k + .55)], (150, 130, 96), .5, ASPHALT)
            for i in range(5):                                                          # zebra crossings on the four sides of the crossing
                off = .12 + i * .17
                for a, c in (((gx + off, gy - .02), (gx + off, gy - .3)), ((gx + off, gy + 1.02), (gx + off, gy + 1.3)),
                             ((gx - .02, gy + off), (gx - .3, gy + off)), ((gx + 1.02, gy + off), (gx + 1.3, gy + off))):
                    cv.line([proj(*a), proj(*c)], (206, 202, 214), .5, ASPHALT)
            for (a, c) in (((gx - .4, gy + .2), (gx - .4, gy + .44)), ((gx + 1.4, gy + .56), (gx + 1.4, gy + .8)),          # stop lines before the zebras, one per direction
                           ((gx + .2, gy - .4), (gx + .44, gy - .4)), ((gx + .56, gy + 1.4), (gx + .8, gy + 1.4))):
                cv.line([proj(*a), proj(*c)], (212, 208, 198), .6, ASPHALT)
            if (m * 7 + n * 3) % 4 == 0:                                                # a fire hydrant on a corner
                cv.dot(proj(gx + 1.14, gy + .12), (210, 54, 44), METAL)
            for cx, cy in ((gx + .1, gy + .1), (gx + .9, gy + .9)):                      # traffic-light poles at two corners of the crossing
                px, py = proj(cx, cy)
                cv.line([(px, py), (px, py - 3.0)], (66, 68, 76), .5, METAL)
                rec.poles.append((round(px, 1), round(py - 3.0, 1), gx, gy))
            if (m + n) % 3 == 0:                                                        # a manhole in the street: the steam comes out here
                mx, my = proj(gx + 2.5, gy + .5)
                cv.ellipse(((mx - 1.0, my - .5), (mx + 1.0, my + .5)), (10, 11, 14), ASPHALT)
                rec.manholes.append((round(mx, 1), round(my, 1)))
    for gx in range(lo, hi, 5):                                                         # lamps at the corners of every block
        for gy in range(lo, hi, 5):
            if not (-30 < proj(gx + 3, gy + 3)[0] < WORLD[0] + 30 and -20 < proj(gx + 3, gy + 3)[1] < WORLD[1] + 20):
                continue
            for cx, cy in ((gx + .92, gy + .92), (gx + 5.08, gy + .92), (gx + .92, gy + 5.08), (gx + 5.08, gy + 5.08)):
                px, py = proj(cx, cy)
                if -5 < px < WORLD[0] + 5 and 20 < py < WORLD[1] + 5:
                    rec.lamps.append((round(px, 1), round(py - 3.2, 1)))
                    cv.line([(px, py), (px, py - 3.0)], (58, 60, 68), .5, METAL)
                    cv.dot((px, py - 3.2), (255, 232, 170), LAMP)
    # the canal: water between its two quay streets, with stone coping, and a bridge where a street crosses it
    c0, c1 = CANAL
    cv.poly(strip(lo, c0, hi, c1), (20, 58, 82), WATER)
    for gy in (c0, c1):
        cv.line([proj(lo, gy), proj(hi, gy)], (176, 170, 156), .9, STONE)
        cv.line([proj(lo, gy + (.35 if gy == c0 else -.35)), proj(hi, gy + (.35 if gy == c0 else -.35))], (14, 40, 60), 1.4, WATER)
    for m in BRIDGES:
        gx = 5 * m
        cv.poly(strip(gx, c0, gx + 1, c1), (30, 32, 38), ASPHALT)
        for k in range(c1 - c0):
            cv.line([proj(gx + .5, c0 + k + .15), proj(gx + .5, c0 + k + .55)], (150, 130, 96), .5, ASPHALT)
        for off in (0, 1):                                                              # parapets, and the arch of the bridge's side
            cv.line([proj(gx + off, c0), proj(gx + off, c1)], (170, 164, 152), 1.0, STONE)
            cv.line([proj(gx + off, c0 + .3), proj(gx + off, c1 - .3)], (116, 112, 104), .6, STONE)


# ------------------------------------------------------------------------------------------------------------------------ lighting a phase
SUN_X = 206                          # where the sun sets and the moon hangs: world x of the glitter column on the water
GROUND = (ASPHALT, PAVE, GRASS, STONE)


def gradient_rows(size, stops):
    """A vertical gradient picture: `stops` is [(row, colour), ...] in world rows; `size` is in S-times pixels."""
    img = Image.new('RGB', size)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        yy = y / S
        if yy <= stops[0][0]:
            c = stops[0][1]
        elif yy >= stops[-1][0]:
            c = stops[-1][1]
        else:
            for (y0, c0), (y1, c1) in zip(stops, stops[1:]):
                if y0 <= yy <= y1:
                    c = mix(c0, c1, smooth(y0, y1, yy))
                    break
        d.line([(0, y), (size[0], y)], fill=c)
    return img


def relight(cv, phase):
    """Light the albedo for a time of day: for each of the three channels, albedo x multiplier + adder, the multiplier and the adder looked up per class."""
    table = light_table(phase)
    out = []
    for ch, plane in enumerate(cv.albedo.split()):
        mul = [128] * 256
        add = [0] * 256
        for cls, (m, a) in table.items():
            mul[cls] = min(255, round(m[ch] * 127.5))
            add[cls] = clamp(round(a[ch]), 0, 255)
        x = ImageChops.multiply(plane, cv.cls.point(mul))
        x = ImageChops.add(ImageChops.add(x, x), cv.cls.point(add))
        out.append(x)
    return Image.merge('RGB', out)


def hull(points):
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def shadow_masks(buildings, trees=(), scale=2):
    """Two soft masks at `scale` times the world: the cast shadows of the buildings and of the trees on the ground (the sun is low on the right and a little behind,
    so shadows fall to the left across the streets and the lawns) and the dark just at the foot of every wall and under every canopy (ambient occlusion).
    Returns {'day': shadow, 'gold': shadow, 'ao': occlusion}."""
    size = (WORLD[0] * scale, WORLD[1] * scale)
    out = {}
    for phase, k in (('day', 1.15), ('gold', 2.6)):
        img = Image.new('L', size, 0)
        d = ImageDraw.Draw(img)
        for b in buildings:
            if b.kind not in ('city', 'hero'):
                continue
            h = b.top if b.kind == 'hero' else b.h
            length = min(14.0, h * k / 6)
            dx, dy = -.78 * length, .62 * length
            foot = [(b.x0, b.y0), (b.x1, b.y0), (b.x1, b.y1), (b.x0, b.y1)]
            pts = [proj(x, y) for x, y in foot] + [proj(x + dx, y + dy) for x, y in foot]
            d.polygon([(x * scale, y * scale) for x, y in hull(pts)], fill=255)
        for px, py, r, h, _ in trees:                                                   # a tree's shadow: its foot dragged along the light, a little shorter than a wall's
            sx, sy = -1.4 * k * h * .42, -.08 * k * h * .42
            pts = [(px + math.cos(a) * r * .95 + ox, py + math.sin(a) * r * .5 + oy) for a in [i * math.pi / 5 for i in range(10)] for ox, oy in ((0, 0), (sx, sy))]
            d.polygon([(x * scale, y * scale) for x, y in hull(pts)], fill=255)
        out[phase] = img.filter(ImageFilter.GaussianBlur(1.6 * scale))
    occ = Image.new('L', size, 0)
    d = ImageDraw.Draw(occ)
    for b in buildings:
        if b.kind in ('city', 'hero'):
            d.polygon([(x * scale, y * scale) for x, y in (proj(b.x0, b.y0), proj(b.x1, b.y0), proj(b.x1, b.y1), proj(b.x0, b.y1))], fill=255)
    blur = occ.filter(ImageFilter.GaussianBlur(1.8 * scale))
    ao = ImageChops.subtract(blur, occ.filter(ImageFilter.GaussianBlur(.4 * scale)).point(lambda v: v // 2))
    under = Image.new('L', size, 0)
    d = ImageDraw.Draw(under)
    for px, py, r, h, _ in trees:                                                       # the dark under a canopy, at every time of day
        d.ellipse([(px - r * 1.05) * scale, (py - r * .42) * scale, (px + r * 1.05) * scale, (py + r * .52) * scale], fill=255)
    out['ao'] = ImageChops.lighter(ao, under.filter(ImageFilter.GaussianBlur(.7 * scale)).point(lambda v: round(v * .8)))
    return out


def lamp_pools(lamps, strength, scale=2):
    """A soft warm pool of light under every street lamp, as a mask (what the lamps add to the ground)."""
    size = (WORLD[0] * scale, WORLD[1] * scale)
    img = Image.new('L', size, 0)
    d = ImageDraw.Draw(img)
    for x, y in lamps:
        d.ellipse([(x - 5.6) * scale, (y + 3.2 - 2.4) * scale, (x + 5.6) * scale, (y + 3.2 + 2.4) * scale], fill=255)
    return img.filter(ImageFilter.GaussianBlur(1.6 * scale)).point(lambda v: min(255, round(v * strength)))


def water_picture(phase, size, rnd):
    """The canal for a time of day: the sky's colour on the water, ripples, and at dusk the reflections of the city's lights."""
    top, mid, hor, glow = SKY[phase]
    deep = {'day': (46, 104, 132), 'gold': (84, 92, 116), 'blue': (26, 40, 78), 'night': (8, 16, 38)}[phase]
    near = {'day': (30, 78, 108), 'gold': (44, 58, 86), 'blue': (16, 26, 56), 'night': (6, 12, 30)}[phase]
    img = gradient_rows(size, [(0, mix(deep, hor, .3)), (260, mix(deep, hor, .18)), (451, near)])
    d = ImageDraw.Draw(img)
    light = {'day': (176, 214, 236), 'gold': (255, 196, 140), 'blue': (130, 120, 170), 'night': (70, 90, 140)}[phase]
    for _ in range(1400):                                                                 # ripples: short pale dashes
        y = rnd.uniform(250, WORLD[1])
        x = rnd.uniform(-20, WORLD[0] + 20)
        length = rnd.uniform(1.5, 4.5)
        base = img.getpixel((int(min(size[0] - 1, max(0, x * S))), int(min(size[1] - 1, y * S))))
        d.line([(x * S, y * S), ((x + length) * S, y * S)], fill=mix(base, light, rnd.uniform(.10, .28)), width=S // 2)
    count = {'day': 0, 'gold': 60, 'blue': 240, 'night': 420}[phase]
    for _ in range(count):                                                                # the city's lights, broken up on the water
        y = rnd.uniform(250, WORLD[1])
        x = rnd.uniform(0, WORLD[0])
        colour = rnd.choice(WARM + ((206, 224, 250), (255, 120, 90), (120, 220, 180)))
        base = img.getpixel((int(min(size[0] - 1, max(0, x * S))), int(min(size[1] - 1, y * S))))
        d.line([(x * S, y * S), ((x + rnd.uniform(.8, 2.4)) * S, y * S)], fill=mix(base, colour, rnd.uniform(.25, .6)), width=S // 2)
    return img


def hero_pixels(cv, ids):
    """A mask (255 where a pixel belongs to one of the buildings with these ids)."""
    r, g, _ = cv.ids.split()
    mask = Image.new('L', cv.ids.size, 0)
    for i in ids:
        lo, hi = i & 255, (i >> 8) & 255
        same = ImageChops.multiply(r.point(lambda v, lo=lo: 255 if v == lo else 0), g.point(lambda v, hi=hi: 255 if v == hi else 0))
        mask = ImageChops.lighter(mask, same)
    return mask


def render_phase(cv, buildings, rec, phase, masks, seed):
    """One time of day of the whole city as a world-sized RGBA picture (the alpha thins towards the horizon so that the sky shows through)."""
    rnd = random.Random(f'{seed}:{phase}')
    lit = relight(cv, phase)
    size = lit.size
    hero = hero_pixels(cv, [b.id for b in buildings if b.kind == 'hero'])
    if phase == 'night':
        # Moonlight and the colour of nearby streets vary by building. Build the
        # overlay once in the offline atlas, preserving the wall's own texture.
        # The quota towers keep their own colours and percentage semantics.
        palette = ((30, 7, 2), (2, 15, 31), (24, 5, 25), (26, 18, 3),
                   (2, 25, 14), (28, 13, 5), (8, 13, 30), (24, 9, 15))
        ids = cv.ids.getchannel('R')
        tint = Image.merge('RGB', [ids.point([palette[(i * 5 + i // 7) % len(palette)][ch] for i in range(256)]) for ch in range(3)])
        facade = cv.cls.point([255 if v in (WALL_L, WALL_R, GLASS_L, GLASS_R, ROOF) else 0 for v in range(256)])
        facade = ImageChops.subtract(facade, hero)
        lit = Image.composite(ImageChops.add(lit, tint), lit, facade)
        # A very fine rim on the visible outer edge separates adjacent silhouettes
        # without drawing a line through windows or changing the buildings.
        r, g, _ = cv.ids.split()
        delta = ImageChops.lighter(ImageChops.difference(r, ImageChops.offset(r, 2, 0)),
                                   ImageChops.difference(g, ImageChops.offset(g, 2, 0)))
        edge = ImageChops.multiply(delta.point(lambda v: 255 if v else 0), facade)
        lit = Image.composite(ImageChops.add(lit, Image.new('RGB', size, (13, 15, 19))), lit, edge)
    ground = cv.cls.point([255 if v in GROUND else 0 for v in range(256)])
    up = lambda m: m.resize(size, Image.Resampling.BICUBIC)
    # cast shadows on the ground (day and golden hour), darkness at the foot of the walls, light from the lamps
    if phase in masks:
        shade = ImageChops.multiply(up(masks[phase]), ground)
        k = {'day': .42, 'gold': .55}[phase]
        lit = Image.composite(ImageChops.multiply(lit, Image.new('RGB', size, (round(255 * (1 - k * .7)), round(255 * (1 - k * .75)), round(255 * (1 - k * .5))))),
                              lit, shade)
    occ = ImageChops.multiply(up(masks['ao']), ground)
    lit = Image.composite(ImageChops.multiply(lit, Image.new('RGB', size, (178, 182, 196))), lit, occ.point(lambda v: round(v * .8)))
    pool = {'day': 0.0, 'gold': .18, 'blue': .5, 'night': .7}[phase]
    if pool:
        mask = ImageChops.multiply(up(lamp_pools(rec.lamps, pool)), ground)
        warm = (255, 196, 120)
        glow = Image.merge('RGB', [mask.point(lambda v, c=warm[i]: round(v * c / 255 * .8)) for i in range(3)])
        lit = ImageChops.add(lit, glow)
    # the harbour
    water = cv.cls.point([255 if v == WATER else 0 for v in range(256)])
    lit = Image.composite(water_picture(phase, size, rnd), lit, water)
    # depth: a LITTLE haze, so that the far rows read as far, while the colours, the contrast and the windows of the far buildings stay (Tony, 2026-11-10: they
    # were seen through a fog). The tint is the colour of the air at that hour, not the colour of the sky's glow.
    tint, top_amount = HAZE[phase]
    haze = tint
    curve = gradient_rows(size, [(0, (255, 255, 255)), (24, (232, 232, 232)), (60, (150, 150, 150)), (100, (84, 84, 84)), (150, (30, 30, 30)), (210, (0, 0, 0))]).convert('L')
    mask = curve.point(lambda v: round(v * top_amount))
    mask = Image.composite(mask.point(lambda v: round(v * .55)), mask, water)
    # The data buildings stay crisp and solid however high they stand.
    mask = Image.composite(Image.new('L', size, 0), mask, hero)
    rail = hero_pixels(cv, [b.id for b in buildings if b.kind == 'rail'])             # the viaduct stands in front of the far city: it is only a little hazed
    mask = Image.composite(mask.point(lambda v: round(v * .3)), mask, rail)
    lit = Image.composite(Image.new('RGB', size, haze), lit, mask)
    coverage = cv.cls.point([0] + [255] * 255)
    fade = gradient_rows(size, [(4, (0, 0, 0)), (26, (255, 255, 255))]).convert('L')
    alpha = ImageChops.lighter(ImageChops.multiply(coverage, fade), ImageChops.multiply(coverage, hero))
    rgb = lit.resize(WORLD, Image.Resampling.BOX)
    return Image.merge('RGBA', (*rgb.split(), alpha.resize(WORLD, Image.Resampling.BOX)))


def render_sky(phase, rnd):
    """The sky of a time of day for the top rows of the world: a gradient, the glow where the sun goes down, and the far skyline of the city, hazy, along the
    horizon (the city layer fades into it, so the nearest streets are crisp and the farthest are only a silhouette)."""
    top, mid, hor, glow = SKY[phase]
    size = (WORLD[0] * S, SKY_ROWS * S)
    img = gradient_rows(size, [(0, top), (22, mid), (46, hor), (SKY_ROWS, hor)])
    layer = Image.new('RGBA', size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    strength = {'day': 70, 'gold': 220, 'blue': 150, 'night': 40}[phase]
    ld.ellipse([(SUN_X - 70) * S, 20 * S, (SUN_X + 70) * S, 74 * S], fill=glow + (strength,))
    layer = layer.filter(ImageFilter.GaussianBlur(14 * S))
    img = img.convert('RGBA')
    img.alpha_composite(layer)
    img = img.convert('RGB')
    far_skyline(ImageDraw.Draw(img), phase, random.Random(f'skyline:{phase}'))
    return img.resize((WORLD[0], SKY_ROWS), Image.Resampling.BOX)


FAR_TINTS = ((232, 196, 150), (140, 176, 226), (150, 214, 200), (236, 170, 170), (196, 180, 236), (214, 218, 226), (240, 214, 130), (170, 200, 150))


def far_skyline(d, phase, rnd):
    """The farthest part of the city: three rows of towers along the horizon (each nearer row darker and wider). Every tower has its own tint (warm stone, blue glass,
    teal, rose, lilac, silver), its own form (a slab, a tower with setbacks, a stepped pyramid, a spire, a dome, a twin pair with a bridge, a slanted top), its own
    pattern of lit windows (a grid, vertical strips, a ribbon, a scatter), and a sunlit edge. The shapes are the same at every time of day (only the colours and the
    lights change), so the cross-fade between two times of day never moves a tower."""
    top, mid, hor, glow = SKY[phase]
    geo = random.Random('far-skyline')
    dusk = phase in ('blue', 'night')
    lit_chance = {'day': .0, 'gold': .2, 'blue': .46, 'night': .6}[phase]
    for base, tone, (lo, hi), mean_w in ((46, .28, (10, 34), 2.6), (52, .42, (14, 46), 3.4), (59, .58, (12, 52), 4.6)):
        shade = mix(hor, top, tone + (.1 if dusk else 0))
        x = -6.0
        while x < WORLD[0] + 6:
            w = max(2.0, geo.uniform(.6, 1.7) * mean_w)
            h = geo.uniform(lo, hi) * (1.4 if geo.random() < .14 else 1)
            tiers = geo.choice((1, 1, 2, 3))
            crown = geo.choice(('flat', 'spire', 'spire', 'mast', 'pyramid', 'dome', 'slant', 'twin', 'flat', 'stepped'))
            tint = geo.choice(FAR_TINTS)
            pattern = geo.choice(('grid', 'strips', 'ribbon', 'scatter'))
            body = mix(shade, mix(shade, tint, .55), .5 if not dusk else .3)
            edge = mix(body, glow, .5 if phase == 'gold' else .32 if phase == 'day' else .0 if phase == 'night' else .2)
            cx, cum = x + w / 2, 0.0
            for tier in range(tiers):
                share = h * ((.62, .24, .14)[tier] if tiers == 3 else (.7, .3)[tier] if tiers == 2 else 1.0)
                tw = w * (1, .72, .46)[tier]
                y_top = base - cum - share
                d.rectangle([(cx - tw / 2) * S, y_top * S, (cx + tw / 2) * S, (base + 5) * S], fill=body)
                d.rectangle([(cx + tw / 2 - .9) * S, y_top * S, (cx + tw / 2) * S, (base + 5) * S], fill=edge)
                if tier == 0 and geo.random() < .35:                                               # a lighter band across the shaft
                    d.rectangle([(cx - tw / 2) * S, (y_top + share * .3) * S, (cx + tw / 2) * S, (y_top + share * .3 + 1.0) * S], fill=mix(body, edge, .6))
                if phase != 'day' or tier == 0:
                    for k in range(int((share + cum) / 2.2) if tw >= 1.6 else 0):                # lit windows (a few by day, more at dusk), in this tower's pattern
                        wy = y_top + 1.0 + k * 2.2
                        window = mix(body, (255, 214, 140), .7 if phase == 'night' else .5)
                        if pattern == 'grid':
                            for wx in (cx - tw * .25, min(cx + tw * .12, cx + tw / 2 - .8)):
                                if rnd.random() < lit_chance:
                                    d.rectangle([wx * S, wy * S, (wx + .7) * S, (wy + .8) * S], fill=window)
                        elif pattern == 'strips':
                            if k % 2 == 0 and rnd.random() < lit_chance * 1.3:
                                d.rectangle([(cx - tw / 2 + .5) * S, wy * S, max(cx - tw / 2 + .9, cx + tw / 2 - 1.0) * S, (wy + .6) * S], fill=window)
                        elif pattern == 'ribbon':
                            if k % 3 == 0 and rnd.random() < lit_chance * 1.4:
                                d.rectangle([(cx - tw / 2 + .3) * S, wy * S, max(cx - tw / 2 + .6, cx + tw / 2 - .3) * S, (wy + .9) * S], fill=window)
                        elif rnd.random() < lit_chance * .8:
                            wx = min(cx - tw / 2 + .4 + rnd.random() * max(.1, tw - 1.4), cx + tw / 2 - .8)
                            d.rectangle([wx * S, wy * S, (wx + .7) * S, (wy + .8) * S], fill=window)
                cum += share
            y_top = base - cum
            tw = w * (1, .72, .46)[tiers - 1]
            if crown == 'spire':
                d.polygon([((cx - tw * .3) * S, y_top * S), ((cx + tw * .3) * S, y_top * S), (cx * S, (y_top - geo.uniform(4, 10)) * S)], fill=body)
            elif crown == 'mast':
                d.rectangle([(cx - .3) * S, (y_top - geo.uniform(5, 11)) * S, (cx + .3) * S, y_top * S], fill=body)
            elif crown == 'pyramid':
                d.polygon([((cx - tw / 2) * S, y_top * S), ((cx + tw / 2) * S, y_top * S), (cx * S, (y_top - geo.uniform(2.5, 5)) * S)], fill=body)
            elif crown == 'dome':
                d.ellipse([(cx - tw * .42) * S, (y_top - tw * .38) * S, (cx + tw * .42) * S, (y_top + tw * .3) * S], fill=body)
            elif crown == 'slant':
                d.polygon([((cx - tw / 2) * S, y_top * S), ((cx + tw / 2) * S, y_top * S), ((cx + tw / 2) * S, (y_top - geo.uniform(2, 5)) * S)], fill=body)
            elif crown == 'twin':                                                                # a second shaft beside it, a little lower, joined by a bridge
                tw2 = max(1.4, tw * .55)
                h2 = geo.uniform(.55, .85) * (base - y_top)
                d.rectangle([(cx + tw / 2 + .6) * S, (base - h2) * S, (cx + tw / 2 + .6 + tw2) * S, (base + 5) * S], fill=body)
                d.rectangle([(cx + tw / 2) * S, (base - h2 * .6) * S, (cx + tw / 2 + .7) * S, (base - h2 * .6 + .7) * S], fill=edge)
            elif crown == 'stepped':
                for k in range(3):
                    s2 = tw * (.7 - k * .2)
                    d.rectangle([(cx - s2 / 2) * S, (y_top - (k + 1) * 1.6) * S, (cx + s2 / 2) * S, (y_top - k * 1.6) * S], fill=body)
            x += w * geo.choice((.5, .7, .9, 1.0, 1.1)) + geo.choice((-.5, 0, 0, .6, 1.4))


def render_lights(rec, cv):
    """The lit windows, in BUCKETS pictures: a window belongs to one batch, and the scene brings the batches in one after another as the sun goes down.
    Each is a transparent picture of crisp illuminated windows, added to the city. A window hidden by a nearer building is not lit."""
    s = cv.s
    cores = [Image.new('RGBA', cv.albedo.size, (0, 0, 0, 0)) for _ in range(BUCKETS)]
    draws = [ImageDraw.Draw(c) for c in cores]
    ids = cv.ids.load()
    kept = 0
    # Each building has its own coherent lighting. Keep a little variation within
    # it, but use visibly different warm, cool and neutral temperatures next door.
    window_tints = ((255, 177, 88), (255, 232, 178), (139, 199, 255), (164, 239, 210),
                    (255, 164, 143), (215, 197, 255), (239, 242, 223), (242, 205, 108))
    for quad, colour, bucket, bid, blind in rec.wins:
        cx, cy = sum(p[0] for p in quad) / 4, sum(p[1] for p in quad) / 4
        if ids[min(cv.albedo.width - 1, max(0, int(cx * s))), min(cv.albedo.height - 1, max(0, int(cy * s)))] != id_colour(bid):
            continue
        q = quad
        if blind:                                                                          # half-lowered blinds: only the lower half is lit
            mid = ((q[0][0] + q[3][0]) / 2, (q[0][1] + q[3][1]) / 2), ((q[1][0] + q[2][0]) / 2, (q[1][1] + q[2][1]) / 2)
            q = [q[0], q[1], mid[1], mid[0]]
        # Each building has a prevailing light temperature instead of a confetti of unrelated colours.
        colour = mix(colour, window_tints[(bid * 5 + bid // 7) % len(window_tints)], .82)
        draws[bucket].polygon([(x * s, y * s) for x, y in q], fill=tuple(colour) + (255,))
        kept += 1
    out = []
    # the far city is in the haze: its lights are faint, only the near ones are bright
    attenuation = gradient_rows((WORLD[0] * S, WORLD[1] * S), [(0, (170, 170, 170)), (44, (200, 200, 200)), (90, (228, 228, 228)), (140, (250, 250, 250)), (190, (255, 255, 255))]).convert('L').resize(WORLD, Image.Resampling.BOX)
    for core in cores:
        # Avoid overlapping halos: on the tablet they make neighbouring windows look out of focus.
        layer = core.resize(WORLD, Image.Resampling.BOX)
        layer.putalpha(ImageChops.multiply(layer.getchannel('A'), attenuation))
        out.append(layer)
    return out, kept


def paint_rail(cv, rec, b):
    """One bay of the viaduct: a pier, the long concrete deck with its parapet, two rails and a mast for the overhead wire."""
    cv.bid = b.id
    x0, y0, x1, y1, z0, z1 = b.x0, b.y0, b.x1, b.y1, b.z0, b.h
    px = (x0 + x1) / 2
    base = 0
    pl, pr, _ = box_faces(px - .17, y0 + .12, px + .17, y1 - .12, base, z0)
    cv.poly(pl, (96, 94, 90), WALL_L)
    cv.poly(pr, (124, 122, 116), WALL_R)
    left, right, roof = box_faces(x0, y0, x1, y1, z0, z1)
    cv.poly(left, (150, 146, 136), WALL_L)
    cv.poly(right, (176, 172, 162), WALL_R)
    cv.poly(roof, (70, 72, 78), TRACK)
    for yy in (y0 + .17, y0 + .39):
        cv.line([proj(x0, yy, z1), proj(x1, yy, z1)], (178, 180, 188), .4, METAL)
    cv.line([proj(x0, y1, z1), proj(x1, y1, z1)], (176, 174, 166), .6, WALL_L)
    cv.line([proj(x0, y1, z0 + .3), proj(x1, y1, z0 + .3)], (60, 58, 56), .5, WALL_L)
    p = proj(x0 + .5, y0 + .04, z1)
    cv.line([p, (p[0], p[1] - 5.5)], (50, 52, 60), .5, METAL)
    cv.line([(p[0], p[1] - 5.5), (p[0] + 2.6, p[1] - 6.6)], (50, 52, 60), .35, METAL)
    cv.bid = 0


def streets_under(heroes):
    """The pieces of street that a data building's footprint covers (the two towers stand a little across a street): nothing drives or walks there, so that no
    vehicle ever passes under a data building. (The five-hour building stands inside its block and covers none.)"""
    out = []
    for h in heroes.values():
        for m in range(int(h.x0 // 5), int(h.x1 // 5) + 1):                                 # a street along y: gx from 5 m to 5 m + 1
            lo, hi = max(h.x0, 5 * m), min(h.x1, 5 * m + 1)
            if hi - lo > 1e-6:
                out.append((lo, h.y0, hi, h.y1))
        for n in range(int(h.y0 // 5), int(h.y1 // 5) + 1):                                 # a street along x
            lo, hi = max(h.y0, 5 * n), min(h.y1, 5 * n + 1)
            if hi - lo > 1e-6:
                out.append((h.x0, lo, h.x1, hi))
    return out


def paint_world(buildings, heroes, s=None):
    """Paint the ground and every building, back to front, into one canvas; returns it with the notes the painters took."""
    cv = Cv(WORLD, s or S)
    rec = Rec()
    KEEP[:] = [h.screen_box() for h in heroes.values()]
    paint_ground(cv, rec)
    regions, covered = plan_regions(buildings)
    rec.covered.extend(covered)
    rec.covered.extend(streets_under(heroes))
    rec.regions = regions
    props = {}                                                                          # what stands up, by the block that owns the ground it stands on
    for region in regions:
        DESIGNS[region.design](cv, rec, region)                                         # the flat ground of the region now, its props kept for their turn
        for item in region.items:
            props.setdefault(block_of(item[1], item[2]), []).append(item)
    street_props(buildings, covered, props)
    done = set()
    for b in buildings:
        if b.kind != 'rail':
            block = block_of(b.x0 + .01, b.y0 + .01)
            if block not in done:                                                       # a block's props are painted just before its first building
                done.add(block)
                render_items(cv, rec, props.get(block, []))
        if b.kind == 'hero':
            paint_hero(cv, rec, b)
        elif b.kind == 'city':
            paint_building(cv, rec, b)
        elif b.kind == 'rail':
            paint_rail(cv, rec, b)
    return cv, rec



# ----------------------------------------------------------------------------------------------------------- the numbers the scene needs
WIN_W = {'tower': 1, 'small': 1}
WIN_OFFSETS = {          # window x offsets (pixels): on the left face from its left end, on the right face from the corner, by the width of the face
    26: ([2, 7, 12, 17, 22], [1, 6, 11, 16, 21]),
    24: ([1, 6, 11, 16, 20], [1, 6, 11, 16, 20]),
    22: ([2, 6, 10, 14, 18], [1, 5, 9, 13, 17]),
    18: ([0, 3, 7, 10, 14], [0, 3, 7, 10, 14]),
    16: ([1, 4, 7, 10, 13], [1, 4, 7, 10, 13]),
}
SMALL_OFFSETS = ([1 + 3 * k for k in range(SMALL_COLS)], [1 + 3 * k for k in range(SMALL_COLS)])      # eight windows of two pixels on a face of 24
SOCKET = {'codex': (16, 30, 52), 'claude': (40, 36, 36), 'small': (14, 20, 34), 'unknown': (92, 98, 112)}   # a known empty building is dark; an unknown one is a neutral grey
SMALL_LIT = ((226, 220, 207), (150, 142, 126))      # the five-hour building: quota (left face), time (right face)


def hero_geometry(h):
    """Everything the scene needs to draw a data building's windows, dark or lit, on whole pixels. Cells are in reading order: floors from the ground up,
    on each floor the left face from its left end to the corner, then the right face from the corner to its right end (towers: 10 cells per floor, one per
    percent). The small building has two lists, left face (quota) and right face (time), eight cells per floor, five floors."""
    boxes = h.boxes()
    faces = []
    for (x0, y0, x1, y1, z0, z1) in boxes:
        l0, l1, r1 = proj(x0, y1), proj(x1, y1), proj(x1, y0)
        faces.append(dict(left=(round(l0[0]), round(l0[1]), round(l1[0] - l0[0])), right=(round(l1[0]), round(l1[1]), round(r1[0] - l1[0]))))
    out = {}
    if h.small:
        quota, time_ = [], []
        face = faces[0]
        for f in range(h.floors):
            zf = f * h.floor_h
            for k in range(SMALL_COLS):
                xs, ys, _ = face['left']
                xo = SMALL_OFFSETS[0][k]
                quota.append([xs + xo, round(ys + .5 * (xo + .5) - zf, 1), 1])
            for k in range(SMALL_COLS):
                xs, ys, _ = face['right']
                xo = SMALL_OFFSETS[1][k]
                time_.append([xs + xo, round(ys - .5 * (xo + .5) - zf, 1), -1])
        out.update(floors=h.floors, cols=SMALL_COLS, w=WIN_W['small'], rows=[[1, 3]], quota=quota, time=time_)
        out.update(lit_quota=list(SMALL_LIT[0]), lit_time=list(SMALL_LIT[1]), socket=list(SOCKET['small']))
    else:
        cells = []
        for f in range(h.floors):
            part = 0 if f < h.lower else 1
            face = faces[part]
            width = h.face if part == 0 else h.upper
            zf = f * h.floor_h
            left_offsets, right_offsets = WIN_OFFSETS[width]
            for k in range(HERO_COLS):
                xs, ys, _ = face['left']
                xo = left_offsets[k]
                cells.append([xs + xo, round(ys + .5 * (xo + .5) - zf, 1), 1])
            for k in range(HERO_COLS):
                xs, ys, _ = face['right']
                xo = right_offsets[k]
                cells.append([xs + xo, round(ys - .5 * (xo + .5) - zf, 1), -1])
        out.update(floors=h.floors, cols=2 * HERO_COLS, w=WIN_W['tower'], rows=[list(r) for r in ROW_PIX], cells=cells)
        out.update(lit=list(LIT_COLOURS[h.name]), lit_left=list(mix(LIT_COLOURS[h.name], (45, 55, 60), .16)), socket=list(SOCKET[h.name]))
    out['unknown'] = list(SOCKET['unknown'])
    out['box'] = [round(v) for v in h.screen_box()]
    out['front'] = list(h.front)
    return out


def runs(flags, min_len, max_gap):
    """Spans (first, last) of True in `flags`, short gaps bridged, short spans dropped."""
    spans = []
    start = None
    last = None
    for i, f in enumerate(flags):
        if f:
            if start is None:
                start = i
            last = i
        elif start is not None and i - last > max_gap:
            spans.append((start, last))
            start = None
    if start is not None:
        spans.append((start, last))
    return [s for s in spans if s[1] - s[0] + 1 >= min_len]


def derive(buildings, heroes, rec, cv, seed):
    """From the finished painting: which pixel belongs to which building, and where the scene can put its animated things (all only where they can
    actually be seen)."""
    rnd = random.Random(f'derive:{seed}')
    idmap = cv.ids.resize(WORLD, Image.Resampling.NEAREST)
    px = idmap.load()

    def at(x, y):
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < WORLD[0] and 0 <= yi < WORLD[1]):
            return -1
        r, g, _ = px[xi, yi]
        return r + 256 * g

    def seen(x, y, up=1.0):
        return 6 <= x < WORLD[0] - 6 and 36 <= y - up < WORLD[1] - 3 and at(x, y - up) == 0

    boxes = [None]
    for b in buildings:
        if b.kind == 'hero':                                                           # a box is as tall as the building with its crown, mast and sign
            boxes.append([round(b.x0, 2), round(b.y0, 2), round(b.x1, 2), round(b.y1, 2), 0, b.top + (6 if b.small else 34), 3])
        elif b.kind == 'rail':
            boxes.append([round(b.x0, 2), round(b.y0, 2), round(b.x1, 2), round(b.y1, 2), round(b.z0, 2), round(b.h + 6, 2), 1])
        elif b.kind == 'city':
            crown = {'spire': 26, 'mast': 21, 'pyramid': 12, 'dome': 13, 'twin': 17, 'lantern': 12, 'penthouse': 6}.get(b.style.get('crown'), 10)
            crown = 6 if b.style.get('arch') in ('round', 'tapered', 'twisted', 'ziggurat', 'pyramid_tower', 'twin') else (4 if b.style.get('landmark') else crown)
            boxes.append([round(b.x0, 2), round(b.y0, 2), round(b.x1, 2), round(b.y1, 2), 0, round(b.h + crown, 2), 0])
        else:
            boxes.append(None)                                                         # parks, plazas and lawns never hide anything
    lights, light_index = [], {}

    def light(m, n):
        if (m, n) not in light_index:
            light_index[(m, n)] = len(lights)
            lights.append([5 * m, 5 * n])
        return light_index[(m, n)]

    def in_covered(pt):
        return any(c[0] - .05 <= pt[0] <= c[2] + .05 and c[1] - .05 <= pt[1] <= c[3] + .05 for c in rec.covered)

    lanes, walks = [], []
    step = .25
    count = int((GMAX - GMIN) / step)
    for axis in ('x', 'y'):
        for n in range(GMIN // 5, GMAX // 5):
            for lane, offset, sign in ((0, .32, 1), (1, .68, -1), (2, .08, 1), (3, .92, -1)):
                walk = lane >= 2
                coords = [GMIN + 1 + i * step for i in range(count)]                      # along the street
                pts = [((c, 5 * n + offset) if axis == 'x' else (5 * n + offset, c)) for c in coords]
                # a street that crosses the canal without a bridge ends at the quay: nothing drives or walks on the water
                allowed = [not (axis == 'y' and CANAL[0] <= pt[1] < CANAL[1] and (n not in BRIDGES)) and not in_covered(pt) for pt in pts]
                row = 90 if walk else 74                                                  # nothing is animated in the far haze: it would be crisp against it
                flags = [ok and seen(*proj(gx, gy), up=(1.0 if walk else 1.5)) and proj(gx, gy)[1] >= row for ok, (gx, gy) in zip(allowed, pts)]
                stretches, k = [], 0                                                      # a lane never bridges a stretch where it is not allowed (water, a park, a data building)
                while k < len(pts):
                    if allowed[k]:
                        e = k
                        while e + 1 < len(pts) and allowed[e + 1]:
                            e += 1
                        stretches.append((k, e))
                        k = e + 1
                    else:
                        k += 1
                found = []
                for g0, g1 in stretches:
                    for r0, r1 in runs(flags[g0:g1 + 1], 6 if walk else 8, 20):
                        found.append((r0 + g0, r1 + g0, g0, g1))
                for i0, i1, g0, g1 in found:
                    reach = 6 if walk else 14
                    j0, j1 = max(g0, i0 - reach), min(g1, i1 + reach)
                    a, c = pts[j0], pts[j1]
                    if sign < 0:
                        a, c = c, a
                    entry = {'a': [round(a[0], 2), round(a[1], 2)], 'b': [round(c[0], 2), round(c[1], 2)], 'axis': axis, 'sign': sign, 'seen': i1 - i0 + 1}
                    if walk:
                        walks.append(entry)
                        continue
                    crossings = []
                    lo, hi = sorted((a[0 if axis == 'x' else 1], c[0 if axis == 'x' else 1]))
                    for m in range(int(lo // 5), int(hi // 5) + 2):
                        line = 5 * m
                        if sign > 0 and lo + .8 < line < hi:
                            crossings.append([round(line - .45 - lo, 2), light(m, n) if axis == 'x' else light(n, m)])
                        elif sign < 0 and lo < line + 1 < hi - .8:
                            crossings.append([round(hi - (line + 1.45), 2), light(m, n) if axis == 'x' else light(n, m)])
                    entry['cross'] = sorted(crossings)
                    lanes.append(entry)
    lanes = sorted(lanes, key=lambda l: -l['seen'])[:44]                                  # the longest stretches of street that can be seen: the traffic is a fixed, small budget
    walks = sorted(walks, key=lambda l: -l['seen'])[:90]
    for entry in lanes + walks:
        del entry['seen']
    for (a, c) in rec.paths:                                                          # the walks in the parks, plazas and promenades
        pts = [(a[0] + (c[0] - a[0]) * t / 20, a[1] + (c[1] - a[1]) * t / 20) for t in range(21)]
        flags = [seen(*proj(gx, gy), up=1.0) for gx, gy in pts]
        for i0, i1 in runs(flags, 4, 3):
            walks.append({'a': [round(pts[i0][0], 2), round(pts[i0][1], 2)], 'b': [round(pts[i1][0], 2), round(pts[i1][1], 2)], 'axis': 'p', 'sign': 1})
    boats = []
    for a, c, kinds in WATER_LANES:
        pts = [(a[0] + (c[0] - a[0]) * t / 120, a[1] + (c[1] - a[1]) * t / 120) for t in range(121)]
        flags = [4 <= proj(*p)[0] < WORLD[0] - 4 and 40 <= proj(*p)[1] < WORLD[1] and at(proj(*p)[0], proj(*p)[1] - 1.5) in (0, -1) for p in pts]
        for i0, i1 in runs(flags, 10, 12):
            for a2, c2 in ((pts[i0], pts[i1]), (pts[i1], pts[i0])):
                boats.append({'a': [round(a2[0], 2), round(a2[1], 2)], 'b': [round(c2[0], 2), round(c2[1], 2)], 'kinds': kinds})
    bridges = []                                                                        # the screen shape of each bridge: a boat under it is hidden by its deck
    for m in BRIDGES:
        gx = 5 * m
        bridges.append([[round(v, 1) for v in proj(*pt, z)] for pt, z in (((gx, CANAL[0]), 3), ((gx + 1, CANAL[0]), 3), ((gx + 1, CANAL[1]), 3), ((gx, CANAL[1]), 3))])
    width = WORLD[0]
    water = cv.cls.resize(WORLD, Image.Resampling.NEAREST).point([255 if v == WATER else 0 for v in range(256)]).tobytes()
    ids_r, ids_g, _ = idmap.split()
    built = ImageChops.lighter(ids_r, ids_g).point([0] + [255] * 255).tobytes()
    water_rows = [water[y * width:(y + 1) * width].count(255) for y in range(WORLD[1])]       # per row of the world: pixels of water, and pixels of buildings
    building_rows = [built[y * width:(y + 1) * width].count(255) for y in range(WORLD[1])]
    poles = []
    for x, y, gx, gy in rec.poles:
        if seen(x, y, up=0) and at(x, y - 2) in (0, -1) and not in_covered((gx + .5, gy + .5)):
            poles.append([x, y, light(gx // 5, gy // 5), 0 if (round(x) + round(y)) % 2 == 0 else 1])
    if len(poles) > 46:                                                                 # the lights of the crossings that can be seen: a small, fixed budget
        poles = rnd.sample(poles, 46)
    beacons = [[round(x, 1), round(y, 1)] for x, y, bid in rec.beacons if 44 <= y < WORLD[1] and 6 <= x < WORLD[0] - 6 and at(x, y) in (0, bid)]
    vents = [[round(x, 1), round(y, 1)] for x, y, bid in rec.vents if 70 <= y < WORLD[1] - 4 and at(x, y + 3) == bid]
    screens = []
    for quad, colour, bid in rec.screens:
        cx, cy = sum(p[0] for p in quad) / 4, sum(p[1] for p in quad) / 4
        if at(cx, cy) == bid and 60 <= cy < WORLD[1] - 4:
            screens.append({'q': [[round(x, 1), round(y, 1)] for x, y in quad], 'c': list(colour)})
    def clear_of_buildings(x, y):                                                      # nothing built within reach of the glow of a fountain: it may light the ground only
        total = hit = 0
        for yy in range(int(y) - 6, int(y) + 4):
            for xx in range(int(x) - 8, int(x) + 9):
                total += 1
                hit += at(xx, yy) > 0
        return hit / total < .06
    fountains = [[x, y, int(clear_of_buildings(x, y))] for x, y in rec.fountains if seen(x, y, up=0) and 40 <= y]
    manholes = [[x, y] for x, y in rec.manholes if seen(x, y, up=0) and not in_covered(unproj(x, y))]
    pokes = [[round(x), round(y), max(1, round(w)), max(1, round(hh))] for x, y, w, hh, bid in rec.poke if 40 <= y < WORLD[1] - 3 and at(x, y) == bid]
    rnd.shuffle(pokes)
    return dict(idmap=idmap, boxes=boxes, lanes=lanes, walks=walks, boats=boats, bridges=bridges, lights=lights, poles=poles, beacons=beacons, vents=vents[:60],
                screens=screens[:40], fountains=fountains, manholes=manholes[:20], poke=pokes[:2600], waterRows=water_rows, buildingRows=building_rows)


WATER_LANES = (                        # (from, to, kinds) in grid cells: where boats sail in the canal (the scene hides a boat under a bridge's deck)
    ((-14, 67.2), (110, 67.2), 'fts'),
    ((-14, 68.8), (110, 68.8), 'fs'),
)


def render_clouds(phase):
    """Three soft pixel clouds for a time of day (transparent pictures): lit on top by the sun or the moon, darker underneath."""
    top, mid, hor, glow = SKY[phase]
    base = {'day': (255, 255, 255), 'gold': (255, 214, 176), 'blue': (214, 150, 150), 'night': (58, 70, 108)}[phase]
    under = {'day': (190, 204, 226), 'gold': (206, 134, 128), 'blue': (96, 82, 128), 'night': (22, 30, 58)}[phase]
    out = []
    for n, (w, h, blobs) in enumerate(((46, 14, 5), (32, 10, 4), (58, 15, 6))):
        rnd = random.Random(f'cloud:{n}')
        big = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        for k in range(blobs):
            t = k / max(1, blobs - 1)
            cx = (.16 + .68 * t) * w + rnd.uniform(-1.5, 1.5)
            r = h * rnd.uniform(.22, .34) * (1 - .35 * abs(t - .5) * 2)                  # smaller towards the ends: a heap, not a slab
            cy = h * .62 + rnd.uniform(-1, 1) - r * .55
            d.ellipse([(cx - r * 1.25) * S, (cy - r) * S, (cx + r * 1.25) * S, (cy + r * .8) * S], fill=base + (225,))
        d.rectangle([0, int(h * .8) * S, w * S, h * S], fill=(0, 0, 0, 0))
        shade = Image.new('RGBA', big.size, under + (230,))
        mask = big.getchannel('A')
        lower = Image.new('L', big.size, 0)
        ImageDraw.Draw(lower).rectangle([0, int(h * .5) * S, w * S, h * S], fill=255)
        shade.putalpha(ImageChops.multiply(mask, lower).filter(ImageFilter.GaussianBlur(S)))
        big.alpha_composite(shade)
        big = big.filter(ImageFilter.GaussianBlur(.6 * S))
        out.append(big.resize((w, h), Image.Resampling.BOX))
    return out


def pack(items, width=4 * WORLD[0]):
    """Shelf-pack named pictures into one RGBA atlas: (atlas, {name: [x, y, w, h]})."""
    items = sorted(items, key=lambda item: (-item[1].height, item[0]))
    x = y = row = 0
    frames = {}
    for name, image in items:
        if x + image.width > width:
            x, y, row = 0, y + row, 0
        frames[name] = [x, y, image.width, image.height]
        x += image.width
        row = max(row, image.height)
    atlas = Image.new('RGBA', (width, y + row), (0, 0, 0, 0))
    for name, image in items:
        atlas.paste(image.convert('RGBA'), tuple(frames[name][:2]))
    return atlas, frames


def draw_tower(img, tower, lit, mode=None):
    """The scene's rule for drawing a data building's windows, in Python (for the thumbnail and the tests): the first `lit` cells are lit, the others dark.
    A cell is `w` pixel columns, each column a vertical bar per window row whose position follows the slope of its face."""
    px = img.load()
    cells = tower['cells'] if 'cells' in tower else tower[mode]
    colour_left = tower.get('lit_left') or tower.get('lit_quota')
    colour_right = tower.get('lit') or tower.get('lit_time')
    for i, (x, yb, s) in enumerate(cells):
        colour = (colour_left if s > 0 else colour_right) if i < lit else tower['socket']
        if i < lit and 'cells' in tower:
            # Variation changes only a lit window's shade, never its on/off meaning.
            strength = (1, 1, .95, 1, .9, 1, .97, 1)[i % 8]
            colour = [math.floor(channel * strength + .5) for channel in colour]
        for c in range(tower['w']):
            yc = yb + s * .5 * c
            for r0, r1 in tower['rows']:
                top = math.floor(yc - r1 + .5)
                for yy in range(top, top + (r1 - r0)):
                    if 0 <= x + c < img.width and 0 <= yy < img.height:
                        px[x + c, yy] = tuple(colour) + (255,)


def preview(pictures, data, phase, level, week=(72, 58), session=(None, None)):
    """A finished-looking picture of the world (sky, city, lit windows and the data buildings) for the thumbnail and for looking at the art."""
    base = Image.new('RGBA', WORLD, (0, 0, 0, 255))
    base.paste(pictures['sky-' + phase].convert('RGBA'), (0, 0))
    base.alpha_composite(pictures['city-' + phase])
    for k in range(BUCKETS):
        a = clamp(level * BUCKETS - k, 0, 1)
        if a > 0:
            layer = pictures[f'lights-{k}']
            alpha = layer.getchannel('A').point(lambda v, a=a: round(v * a))
            add = Image.merge('RGB', [ImageChops.multiply(c, alpha) for c in layer.split()[:3]])
            base = ImageChops.add(base.convert('RGB'), add).convert('RGBA')
    towers = data['towers']
    draw_tower(base, towers['codex'], week[0])
    draw_tower(base, towers['claude'], week[1])
    if session[0] is not None:
        draw_tower(base, towers['small'], session[0], 'quota')
        draw_tower(base, towers['small'], session[1], 'time')
    else:
        draw_tower(base, towers['small'], 0, 'quota')
        draw_tower(base, towers['small'], 0, 'time')
    return base


def build(seed=2026, quick=False, place=PLACE, log=lambda text: None):
    """Draw everything: (atlas picture, the numbers as a dict, the picker's thumbnail). Nothing is written. `quick` draws at half the supersampling."""
    global S
    previous, S = S, (2 if quick else 4)
    started = time.time()
    try:
        buildings, heroes = make_plan(seed)
        cv, rec = paint_world(buildings, heroes)
        log(f'painted {len(buildings)} blocks and buildings in {time.time() - started:.1f} s')
        masks = shadow_masks(buildings, rec.trees)
        pictures = {}
        for phase in PHASES:
            pictures['city-' + phase] = render_phase(cv, buildings, rec, phase, masks, seed)
            pictures['sky-' + phase] = render_sky(phase, random.Random(f'sky:{phase}')).convert('RGBA')
            for n, cloud in enumerate(render_clouds(phase)):
                pictures[f'cloud-{n}-{phase}'] = cloud
        lights, kept = render_lights(rec, cv)
        for k, layer in enumerate(lights):
            pictures[f'lights-{k}'] = layer
        info = derive(buildings, heroes, rec, cv, seed)
        idmap = info.pop('idmap')
        pictures['idmap'] = idmap.convert('RGBA')
        log(f'{kept} windows can be lit, {len(info["poke"])} can answer a touch, {len(info["lanes"])} traffic lanes, {len(info["beacons"])} beacons ({time.time() - started:.1f} s)')
        atlas, frames = pack(list(pictures.items()))
        data = {
            'version': 1, 'scene': NAME, 'size': list(VIEW), 'world': list(WORLD), 'margin': list(MARGIN), 'proj': {'hw': HW, 'hh': HH, 'ox': OX, 'oy': OY},
            'phases': list(PHASES), 'buckets': BUCKETS, 'skyRows': SKY_ROWS, 'place': {'lat': place[0], 'lon': place[1]}, 'sunX': SUN_X, 'frames': frames,
            'towers': {name: hero_geometry(h) for name, h in heroes.items()}, 'canal': list(CANAL),
        }
        bays = [b for b in buildings if b.kind == 'rail']
        if bays:                                                                          # the track as far as it can be seen
            data['rail'] = {'a': [min(b.x0 for b in bays), RAIL_Y], 'b': [max(b.x1 for b in bays), RAIL_Y], 'z': RAIL_Z}
        data.update(info)
        thumb_source = preview(pictures, data, 'blue', .85)
        crop = thumb_source.convert('RGB').crop((MARGIN[0], MARGIN[1] + 38, MARGIN[0] + VIEW[0], MARGIN[1] + 38 + 178))
        thumb = crop.resize((240, 160), Image.Resampling.LANCZOS)
        return atlas, data, thumb
    finally:
        S = previous


def write_files(out, atlas, data, thumb, manifest=False, log=print):
    """Write the scene's three files into `out`, owner-only and atomically; with `manifest`, add the scene to `out`'s `scenes.json`."""
    out = Path(out)
    png = out / f'scene-{NAME}.png'
    js = out / f'scene-{NAME}.json'
    media._write_atomically(png, lambda target: atlas.save(target, format='PNG', optimize=True), media.MAX_IMAGE_BYTES)
    text = json.dumps(data, separators=(',', ':'))
    media._write_atomically(js, lambda target: target.write_text(text, encoding='utf-8'), 512 * 1024)
    media.save_image(thumb, out / f'thumb-{NAME}.webp', quality=80)
    if manifest:
        media.update_manifest(NAME, media.scene_entry('game', png.name, 'image', atlas.width, atlas.height, data=js.name), directory=out)
    log(f'wrote {png.name} ({png.stat().st_size // 1024} KiB, {atlas.width}x{atlas.height}), {js.name} ({js.stat().st_size // 1024} KiB), thumb-{NAME}.webp'
        + (' and its entry in scenes.json' if manifest else ''))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Draw the atlas of the tablet's CITY IN THE SKY scene (offline, original art).")
    parser.add_argument('--out', required=True, type=Path, help='the folder to write into (the real one is ~/.local/share/ai-desk-display/tablet/)')
    parser.add_argument('--manifest', action='store_true', help='also add the scene to scenes.json in that folder')
    parser.add_argument('--quick', action='store_true', help='half the supersampling: for a look at the layout, not for the tablet')
    parser.add_argument('--seed', type=int, default=2026, help='the city (same seed, same city)')
    parser.add_argument('--lat', type=float, default=PLACE[0], help='latitude the sun is computed for (default Barcelona)')
    parser.add_argument('--lon', type=float, default=PLACE[1], help='longitude the sun is computed for (east is positive)')
    args = parser.parse_args(argv)
    atlas, data, thumb = build(args.seed, args.quick, (args.lat, args.lon), log=print)
    write_files(args.out, atlas, data, thumb, args.manifest)
    return 0


if __name__ == '__main__':
    sys.exit(main())
