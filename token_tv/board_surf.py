"""TIDAL RUSH: original pocket-console surf art, animated locally by Build 7."""
from functools import lru_cache
import math
import random

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

from token_tv import board_anim, board_reset_icons as icons, board_surf_rider as rider, board_surf_wave as wave
from token_tv.board_surf_wave import ORIGIN, flow_overlay, wave_layer
from token_tv.board_art import _row
from token_tv.personal_faces import remaining_reading, banked_hearts, session_pace
from pathlib import Path

INK = '#102747'
CREAM = '#fff1c7'
YELLOW = '#ffd55e'
STONE = '#e9d9b9'
STEP_MS = 150


@lru_cache(maxsize=16)
def font(size):
    return ImageFont.truetype(str(Path(__file__).with_name('web') / 'press-start-2p.ttf'), size)


def text(d, xy, value, color, size=8):
    d.text(xy, value, font=font(size), fill=color, stroke_width=0)


def _mix(a, b, t):
    """Blend two '#rrggbb' colours: t=0 -> a, t=1 -> b."""
    pa, pb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


def _bands(d, edges, top, bottom, amplitude=1.4, seed=0):
    """Flat colour bands whose edges undulate a little (no dithering: the panel shimmers on fine patterns).

    `edges` is [(first_row, colour), ...]; each boundary wanders by up to `amplitude` rows, so the sky and sea
    read as hand-painted instead of ruled."""
    rnd = random.Random(seed)
    phases = [rnd.uniform(0, 6.28) for _ in edges]
    waves = [rnd.uniform(0.045, 0.11) for _ in edges]
    for x in range(160):
        rows = [row + round(amplitude * math.sin(x * waves[i] + phases[i]) +
                            (0.6 if rnd.random() < 0.12 else 0)) for i, (row, _) in enumerate(edges)]
        for i, (_, colour) in enumerate(edges):
            y0 = max(top, rows[i])
            y1 = min(bottom, rows[i + 1] - 1) if i + 1 < len(edges) else bottom
            if y1 >= y0:
                d.line((x, y0, x, y1), fill=colour)


def _glow(im, centre, radius, colour, strength):
    """Tint a disc of the picture towards `colour` (a soft halo made of flat steps, no gradient)."""
    px = im.load()
    cx, cy = centre
    target = ImageColor.getrgb(colour)
    for y in range(max(0, cy - radius), min(120, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(160, cx + radius + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                px[x, y] = tuple(round(c + (t - c) * strength) for c, t in zip(px[x, y], target))


def _cloud(d, cx, cy, w, body, rim, under):
    """A flat streaky cloud lit from below: a darker body, a bright underside and a thin cool top edge."""
    h = max(2, w // 7)
    for i in range(h + 1):
        half = round(w / 2 * math.sqrt(max(0, 1 - ((i - h / 2) / (h / 2 + .5)) ** 2)))
        d.line((cx - half, cy + i, cx + half, cy + i), fill=body)
    d.line((cx - w // 2 + 2, cy + h, cx + w // 2 - 2, cy + h), fill=under)
    d.line((cx - w // 3, cy + h + 1, cx + w // 4, cy + h + 1), fill=under)
    d.line((cx - w // 4, cy, cx + w // 5, cy), fill=rim)
    d.point((cx - w // 2 + 1, cy + h // 2), fill=under)


SKY = [(48, '#2a2760'), (52, '#42347a'), (56, '#6a3d8d'), (60, '#9d4a92'), (64, '#cf5f90'),
       (67, '#ee7f89'), (70, '#ffa285'), (73, '#ffc795'), (75, '#ffe3b0')]
# Tony, 2026-11-03: the weekly panels shrank from about 94 px to about 58 and "the wave and sky gain the space". The sky now runs
# to the top of the page, deepening into the night above the old top band (the panels cover most of it; no title any more).
SKY_HIGH = [(0, '#080a26'), (18, '#0c0e32'), (27, '#121340'), (34, '#1a1a4e'), (41, '#222158')]
SEA = [(76, '#ffd49b'), (77, '#7fbdc0'), (80, '#52a6b3'), (85, '#318ba6'), (91, '#217198'),
       (98, '#185a84'), (106, '#124a73'), (114, '#0f3e66')]
HORIZON = 76
SUN = (33, 69)


@lru_cache(maxsize=1)
def _coast():
    """Sky, sun, far islands, sea and the glitter path. The animated wave and the shore are painted over it."""
    im = Image.new('RGB', (160, 120), INK)
    d = ImageDraw.Draw(im)
    _bands(d, SKY_HIGH, 0, 52, 1.0, seed=5)          # its last band runs under the old top band, whose wavy edge shows it
    _bands(d, SKY, 48, HORIZON - 1, 1.1, seed=3)
    _bands(d, SEA, HORIZON, 119, 0.9, seed=9)
    # Sun: a pale halo, a disc shaded in rings, cut by two retro stripes and sunk into the horizon.
    cx, cy = SUN
    _glow(im, (cx, cy), 23, '#ffb98d', .13)
    _glow(im, (cx, cy), 18, '#ffc995', .18)
    _glow(im, (cx, cy), 15, '#ffd49b', .22)
    for r, colour in ((12, '#ffd77c'), (11, '#ffe28f'), (9, '#ffeba8'), (6, '#fff4c7'), (3, '#fffbe6')):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
    for y, w in ((72, 1), (74, 2)):
        d.rectangle((cx - 13, y, cx + 13, y + w - 1), fill=im.getpixel((cx - 16, y)))
    d.rectangle((cx - 14, HORIZON, cx + 14, HORIZON), fill='#ffd49b')
    for y in range(HORIZON + 1, HORIZON + 4):                    # the sun's wet reflection right under the horizon
        d.line((cx - 12 + (y - HORIZON), y, cx + 12 - (y - HORIZON), y), fill='#ffd8a0' if y % 2 else '#f9b88c')
    for x, y, colour in ((4, 49, '#8f86d6'), (13, 52, '#b8b0f0'), (27, 50, '#8f86d6'), (41, 53, '#cfc8ff'),
                         (52, 49, '#8f86d6'), (150, 50, '#b8b0f0'), (156, 54, '#8f86d6'), (141, 52, '#8f86d6'),
                         # the new sky under the panels: a few more, fewer and fainter towards the dark top
                         (9, 34, '#6f68b4'), (31, 41, '#8f86d6'), (66, 36, '#8f86d6'), (88, 44, '#b8b0f0'), (104, 38, '#6f68b4'),
                         (123, 46, '#8f86d6'), (137, 40, '#cfc8ff'), (152, 33, '#6f68b4'), (47, 31, '#6f68b4'), (79, 32, '#8f86d6')):
        d.point((x, y), fill=colour)
    # Clouds lit from below by the low sun, kept clear of the title.
    _cloud(d, 134, 61, 34, '#a14c93', '#c9709a', '#ff9d86')
    _cloud(d, 108, 67, 26, '#d4618e', '#f08a95', '#ffbd90')
    _cloud(d, 14, 57, 22, '#7a4390', '#a35f9a', '#ff8f88')
    _cloud(d, 60, 71, 20, '#f08489', '#ffa890', '#ffd2a0')
    _cloud(d, 148, 71, 16, '#f58f89', '#ffb393', '#ffd5a0')
    # Distant islands with tiny palms, hazy against the glow, and a small sailing boat.
    for pts, colour in (([(44, 76), (47, 73), (52, 72), (57, 73), (61, 76)], '#b9759a'),
                        ([(0, 76), (4, 70), (10, 67), (16, 69), (22, 72), (30, 76)], '#8a5898'),
                        ([(0, 76), (3, 72), (9, 70), (15, 73), (19, 76)], '#6c4682')):
        d.polygon(pts, fill=colour)
    for x, y in ((49, 72), (55, 72)):
        d.point((x, y - 1), fill='#6c4682'); d.point((x - 1, y - 2), fill='#6c4682'); d.point((x + 1, y - 2), fill='#6c4682')
    d.line((68, 75, 72, 75), fill='#8a3f62'); d.line((70, 71, 70, 74), fill='#8a3f62')
    d.polygon([(71, 71), (71, 74), (74, 74)], fill='#fff0cf'); d.polygon([(69, 72), (69, 74), (67, 74)], fill='#ffc7a0')
    # Birds, loosely grouped, against the pink band.
    for x, y, big in ((84, 62, True), (95, 60, False), (99, 66, True), (73, 66, False)):
        shape = ((1, 0), (2, 0), (4, 0), (5, 0), (0, 1), (3, 1), (6, 1)) if big else ((1, 0), (3, 0), (0, 1), (2, 1), (4, 1))
        for dx, dy in shape:
            d.point((x + dx, y + dy), fill='#5a2f6a')
    # Sea texture: swells that get longer and brighter towards the viewer, and the sun's glitter path.
    rnd = random.Random(21)
    for y in range(HORIZON + 2, 120):
        depth = (y - HORIZON) / 44
        for _ in range(int(2 + depth * 5)):
            x = rnd.randrange(0, 160)
            w = 2 + round(depth * 9) + rnd.randrange(0, 3)
            d.line((x, y, x + w, y), fill=_mix('#6fc4c6', '#9fe2da', depth * .6))
            d.line((x + 1, y + 1, x + w - 1, y + 1), fill=_mix('#17537c', '#0b3558', depth))
    for y in range(HORIZON + 2, 112, 2):
        depth = (y - HORIZON) / 36
        half = round(2 + depth * 9)
        for k in range(1 + int(depth * 3)):
            x = cx + rnd.randrange(-half, half + 1)
            w = 1 + round(depth * 5) + rnd.randrange(0, 2)
            d.line((x, y, x + w, y), fill='#ffe6a8' if k % 2 else '#ffcb7f')
    return im


def _frond(d, cx, cy, angle, length, droop, tones):
    """One palm frond: a curved spine with a feathered leaf blade hanging from it, lit on its upper edge."""
    dark, mid, light = tones
    rad = math.radians(angle)
    steps = max(6, length)
    pts = []
    for i in range(steps + 1):
        t = i / steps
        pts.append((cx + math.cos(rad) * length * t, cy + math.sin(rad) * length * t + droop * t * t))
    for i, (x, y) in enumerate(pts):
        t = i / steps
        blade = max(1, round(1 + 3 * math.sin(math.pi * min(1, t * 1.05)) * (1 - t * .35)))
        for k in range(blade):
            yy = round(y) + k
            colour = light if k == 0 else (mid if k < blade - 1 or blade < 3 else dark)
            d.point((round(x), yy), fill=colour)
        if i % 2 == 0 and blade > 1:                     # notched leaflets along the lower edge
            d.point((round(x) + (1 if math.cos(rad) >= 0 else -1), round(y) + blade), fill=dark)
    return pts


def _palm(d, base, crown, lean, tones, trunk, size=1.0, seed=0):
    """A curved, ringed trunk, a coconut cluster and a crown of eight fronds."""
    bx, by = base
    cx, cy = crown
    n = by - cy
    for i in range(n + 1):
        t = i / n
        x = round(bx + (cx - bx) * (1 - (1 - t) ** 2) + lean * math.sin(math.pi * t))
        y = by - i
        width = 3 if i < n * .55 else 2
        ring = (i // 2) % 2
        d.line((x, y, x + width - 1, y), fill=trunk[0] if ring else trunk[1])
        d.point((x + width - 1, y), fill=trunk[2])              # the sun-lit edge (the sun is to the right)
        d.point((x, y), fill=trunk[3])
    d.ellipse((cx - 1, cy - 1, cx + 3, cy + 2), fill='#2b1b1b')
    for x, y in ((cx - 1, cy + 1), (cx + 1, cy + 2), (cx + 3, cy + 1)):
        d.rectangle((x, y, x + 1, y + 1), fill='#6b3f26')
        d.point((x + 1, y), fill='#b57b4a')
    rnd = random.Random(seed)
    for angle, length, droop in ((-168, 15, 13), (-150, 14, 9), (-120, 12, 4), (-85, 11, 3), (-45, 13, 8),
                                 (-12, 15, 12), (24, 11, 9), (162, 11, 9)):
        _frond(d, cx + 1, cy, angle + rnd.randint(-5, 5), round(length * size), round(droop * size), tones)


def _shore(im):
    """The beach on the left: layered sand, wet edge and foam lace, rocks, shells, footprints, a board stuck in the
    sand, beach grass and two palms."""
    d = ImageDraw.Draw(im)
    line = [(0, 90), (7, 93), (14, 97), (20, 102), (26, 108), (32, 113), (38, 118), (42, 120)]

    def edge(x):                                            # the waterline's row at column x
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            if x0 <= x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return 120
    sand = ('#fff0c6', '#ffdca4', '#f4c490', '#e2a577', '#c98a6c')
    rnd = random.Random(8)
    for x in range(0, 44):
        y0 = round(edge(x))
        for y in range(y0, 120):
            depth = y - y0
            if depth < 2:
                colour = '#fff9e6'
            elif depth < 5:
                colour = '#e3a692' if depth % 2 == 0 else '#f0bcab'      # wet sand mirroring the sky
            elif depth < 9:
                colour = sand[0] if depth == 5 else sand[1]
            elif depth < 17:
                colour = sand[1]
            elif depth < 25:
                colour = sand[2]
            elif depth < 33:
                colour = sand[3]
            else:
                colour = sand[4]
            if depth > 6 and rnd.random() < .035 and colour in sand:     # grain: one step darker
                colour = sand[min(4, sand.index(colour) + 1)]
            d.point((x, y), fill=colour)
    for x in range(0, 43):                                  # foam lace: a scalloped crest and a thinner echo
        y = round(edge(x))
        d.point((x, y - 1 - ((x // 3) % 2)), fill='#ffffff')
        if x % 4:
            d.point((x, y - 2 - ((x // 3) % 2)), fill='#d8fbf2')
        if x % 5 == 2:
            d.point((x, y - 4), fill='#bdf2e8')
    for x in range(1, 40, 7):                               # a thin echo of foam further out
        y = round(edge(x)) - 5
        d.line((x, y, x + 3, y), fill='#a8e8e0')
    # ripples in the sand, parallel to the waterline
    for x, y, w in ((4, 99, 5), (11, 103, 6), (17, 108, 5), (4, 108, 4), (9, 113, 7), (22, 116, 5), (1, 117, 6)):
        d.line((x, y, x + w, y + w // 3), fill='#d99a73')
    # rocks at the water's edge
    for x, y, w, h in ((27, 107, 8, 5), (35, 112, 5, 3)):
        d.ellipse((x, y, x + w, y + h), fill='#3b2848')
        d.ellipse((x, y, x + w - 2, y + h - 1), fill='#5f4466')
        d.line((x + 1, y + 1, x + w - 3, y + 1), fill='#a47fa0')
        d.point((x + 1, y + 2), fill='#cfa7b8')
        d.line((x + 1, y + h + 1, x + w, y + h + 1), fill='#9ee6e0')
        d.point((x - 1, y + h), fill='#ffffff'); d.point((x + w + 1, y + h), fill='#ffffff')
    # starfish, shells, footprints
    for dx, dy in ((0, -1), (-1, 0), (0, 0), (1, 0), (0, 1)):
        d.point((13 + dx, 108 + dy), fill='#ff8a5c')
    d.point((13, 108), fill='#ffc08a')
    for x, y in ((6, 111), (19, 112), (30, 118)):
        d.point((x, y), fill='#ffb7b0'); d.point((x + 1, y), fill='#e08a8a')
    for x, y in ((22, 107), (20, 105), (22, 103), (19, 101)):
        d.rectangle((x, y, x + 1, y), fill='#d6976f')
        d.point((x + 1, y + 1), fill='#c98466')
    # a surfboard stuck in the sand, leaning on the palm side
    board = '#35c0c1'
    d.polygon([(4, 103), (2, 92), (3, 88), (5, 92), (7, 103)], fill=board)
    d.line((3, 89, 5, 102), fill='#f4ffee')
    d.line((2, 93, 2, 102), fill='#1c8e9c')
    d.point((3, 88), fill='#9af4e8')
    d.line((3, 101, 7, 103), fill='#1c8e9c')
    # beach grass at the foot of the palm
    for x, y in ((14, 99), (16, 100), (3, 100), (1, 98), (21, 106)):
        d.line((x, y, x - 1, y - 3), fill='#4a8c56'); d.line((x + 1, y, x + 2, y - 4), fill='#6fae5e'); d.point((x + 2, y - 4), fill='#d8e07a')
    # palms: a tall one in front, a smaller hazy one behind
    _palm(d, (23, 109), (21, 88), -1, ('#173f48', '#27695a', '#6fb06a'), ('#4a2c28', '#6b4330', '#b27f55', '#33201f'), .75, 5)
    _palm(d, (10, 104), (7, 66), -2, ('#173f48', '#2c7860', '#a8d870'), ('#5a3526', '#7b4d36', '#c18a5c', '#3b2420'), 1.0, 2)


@lru_cache(maxsize=1)
def _scenery():
    """Sky, sun, far islands, sea, shore and palms on the 160 x 120 logical canvas: everything that never moves and is not the wave."""
    im = _coast().copy()
    _shore(im)
    return im.convert('RGBA')


@lru_cache(maxsize=1)
def _shore_foreground():
    """Keep the beach and palms in front of the wave's distant shoulder."""
    foreground = Image.new('RGBA', (160, 120))
    _shore(foreground)
    return foreground


@lru_cache(maxsize=None)
def _scene(pose=0, phase=None):
    """The whole logical scene with the wave in one pose of its lip and, if `phase` is not None, the current at that phase."""
    im = _scenery().copy()
    im.alpha_composite(wave_layer(pose), ORIGIN)
    if phase is not None:
        im.alpha_composite(flow_overlay(phase), ORIGIN)
    im.alpha_composite(_shore_foreground())
    return im


@lru_cache(maxsize=1)
def beach():
    """The page's picture below the panels, at screen size: the calm wave, no current and no surfer."""
    return _scene(0).convert('RGB').resize((320, 240), Image.Resampling.NEAREST)


# ---- the animation: four sprites that never overlap (logical pixels, x0 y0 x1 y1) -----------------------------------------
# Tony, 2026-11-03: a leading surfer who climbs and drops along the face, a lip that really falls and a moment of action every few
# seconds. The surfer is one sprite with transparent pictures that the engine moves; the three tiles around his reach hold the
# wave's own motion, each exactly the page's pixels outside what moves. Nothing here reaches the panels (y < 62).
FACE = (128, 62, 160, 116)      # right-hand face and foam, moving every two beats
CREST = (36, 60, 128, 73)       # crest above the barrel and the lip's root
LIP = (36, 73, 74, 116)         # breaking lip and splash on the left
RIDER = (74, 73, 128, 116)      # everything the surfer's sprite can ever touch
HOME = (102, 106)               # board centre, clear of the falling lip
RING = 2                        # logical pixels around a tile that always equal the page: no seam where it meets still water
BEATS = 32                      # one loop is 32 beats of STEP_MS: 4.8 s


def _tile(box, source, free=()):
    """The tile's pictures: the scene crop with its outer RING pixels forced back to the page, except along the edges in `free`
    (a side shared with another moving tile, which the two draw as one picture)."""
    base = _scene(0).crop(box)
    frames = []
    for image in source:
        frame = image.crop(box)
        keep = Image.new('L', frame.size, 0)
        kd = ImageDraw.Draw(keep)
        w, h = frame.size
        for name, rect in (('left', (0, 0, RING - 1, h - 1)), ('right', (w - RING, 0, w - 1, h - 1)),
                           ('top', (0, 0, w - 1, RING - 1)), ('bottom', (0, h - RING, w - 1, h - 1))):
            spans = [span for edge, span in free if edge == name]
            if name == 'right' and box[2] >= 160:
                continue                                         # the page's own edge: there is no still water beyond it to meet
            if not spans:
                kd.rectangle(rect, fill=255)
                continue
            along = 1 if name in ('left', 'right') else 0
            lo, hi = rect[along], rect[along + 2]
            cursor = lo
            for a, b in sorted(spans):                       # ring everywhere along the edge except the free spans
                if a > cursor:
                    r = list(rect); r[along], r[along + 2] = cursor, a - 1
                    kd.rectangle(tuple(r), fill=255)
                cursor = max(cursor, b + 1)
            if cursor <= hi:
                r = list(rect); r[along] = cursor
                kd.rectangle(tuple(r), fill=255)
        frame.paste(base, (0, 0), keep)
        frames.append(frame)
    return frames


def _trim_tile(box, frames):
    """Omit unchanged borders without changing any animated pixel."""
    background = _scene(0).crop(box).convert('RGB')
    changes = [ImageChops.difference(frame.convert('RGB'), background).getbbox() for frame in frames]
    changes = [bounds for bounds in changes if bounds is not None]
    if not changes:
        return box, frames
    left = max(0, min(b[0] for b in changes) - RING)
    top = max(0, min(b[1] for b in changes) - RING)
    right = min(background.width, max(b[2] for b in changes) + RING)
    bottom = min(background.height, max(b[3] for b in changes) + RING)
    return ((box[0] + left, box[1] + top, box[0] + right, box[1] + bottom),
            [frame.crop((left, top, right, bottom)) for frame in frames])


# The original Tidal Rush gulls, recoloured slightly for the darker sky of
# the current scene. Their three wing shapes are the ones Tony liked.
GULL_A = (('X.........X', '.X.......X.', '..XX...XX..', '....XXX....', '...........'),
          ('...........', '.XXX...XXX.', 'X...XXX...X', '...........', '...........'),
          ('...........', '...XXXXX...', '.XXX...XXX.', 'XX.......XX', '...........'))
GULL_B = (('X.......X', '.X.....X.', '..XXXXX..', '.........'),
          ('.........', '.XX...XX.', 'X..XXX..X', '.........'),
          ('.........', '..XXXXX..', '.XX...XX.', 'X.......X'))


def _gull_frames(shapes):
    def paint(rows, colour, rim):
        im = Image.new('RGBA', (len(rows[0]), len(rows)), (0, 0, 0, 0))
        for y, row in enumerate(rows):
            for x, cell in enumerate(row):
                if cell == 'X':
                    im.putpixel((x, y), ImageColor.getrgb(rim if y == 0 and x % 2 == 0 else colour) + (255,))
        return im

    frames = [paint(rows, '#a66787', '#ffd2b0') for rows in shapes]
    frames += [paint(shapes[1], '#3d345e', '#574569'), paint(shapes[1], '#714d72', '#aa758f')]
    frames.append(Image.new('RGBA', frames[0].size, (0, 0, 0, 0)))
    return frames


def _gull_sprite(shapes, y, offset):
    """Glide left, leave the screen and reappear softly after the wrap."""
    script = []
    for i in range(128):
        k = (i + offset) % 128
        frame = 5 if k == 0 else 3 if k == 1 else 4 if k == 2 else (0, 1, 2, 1)[k % 4]
        script.append((frame, 126 - 2 * k, 2 if k % 4 == 2 else 0))
    return {'x': 100, 'y': y, 'frames': _gull_frames(shapes), 'script': script, 'step_ms': STEP_MS}


# What the 32 beats show: (surfer picture, dx, dy in logical pixels, lip pose). The surfer climbs and drops, crouches and skims
# the water with a hand; at beat 16 the lip is cocked back and falls, he tucks under it, bursts out in foam and stands up, and
# calm returns with him where he began: beat 31 is one pixel below beat 0 and the same picture, so nothing jumps at the loop.
PLAN = (
    (0, 0, 0, 0), (0, 0, -1, 0), (1, 1, -2, 0), (1, 1, -3, 0), (1, 2, -4, 0), (1, 2, -5, 0), (0, 2, -4, 0), (0, 1, -2, 0),
    (2, 1, 0, 0), (2, 0, 2, 0), (3, 0, 3, 0), (3, -1, 3, 0), (3, -1, 3, 0), (2, 0, 2, 0), (0, 0, 0, 0), (1, 1, -2, 0),
    (2, 2, -1, 1), (4, 3, 0, 2), (4, 3, 1, 2), (4, 3, 1, 3), (5, 3, 1, 4), (5, 3, 0, 5), (6, 3, 0, 5), (6, 3, -1, 6),
    (7, 3, -2, 6), (7, 2, -3, 7), (7, 2, -3, 7), (1, 2, -3, 0), (1, 1, -2, 0), (0, 1, -1, 0), (0, 0, 0, 0), (0, 0, 1, 0),
)
# boards that hold four pictures per sprite: the same story with the surfer's and the lip's four most telling pictures
FOUR_RIDER = {0: 0, 1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 2, 7: 0}
FOUR_LIP = {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 0}


@lru_cache(maxsize=4)
def animation(frames=8, extended=False):
    """The surfer and wave; boards with extended animation also get the two gulls."""
    full = frames >= 8
    extended = extended and full
    pictures = rider.pictures() if full else tuple(rider.pictures()[i] for i in (0, 1, 2, 3))
    # The last row is transparent in every pose; omit it so the moved sprite
    # never restores over the page markers in the bottom-right corner.
    pictures = tuple(im.crop((0, 0, im.width, im.height - 1)) for im in pictures)
    lip_poses = tuple(range(wave.POSES)) if full else (0, 2, 4, 6)
    face = _tile(FACE, [_scene(0, q) for q in range(wave.FLOW_PHASES)], free=(('left', (0, 72 - FACE[1])),))
    crest = _tile(CREST, [_scene(0, q) for q in range(wave.FLOW_PHASES)],
                  free=(('right', (FACE[1] - CREST[1], CREST[3] - CREST[1] - 1)), ('bottom', (LIP[0] - CREST[0], LIP[2] - CREST[0] - 1))))
    lip = _tile(LIP, [_scene(p) for p in lip_poses], free=(('top', (0, LIP[2] - LIP[0] - 1)),))
    face_box, crest_box, lip_box = FACE, CREST, LIP
    if extended:
        face_box, face = _trim_tile(face_box, face)
        crest_box, crest = _trim_tile(crest_box, crest)
        lip_box, lip = _trim_tile(lip_box, lip)
    two = [(q, 0, 0) for q in range(wave.FLOW_PHASES)] * 4              # a current phase lasts two beats: 16 steps of 300 ms
    script = []
    for picture, dx, dy, pose in PLAN:
        script.append((picture if full else FOUR_RIDER[picture], -dx * 2, dy * 2, pose if full else FOUR_LIP[pose]))
    sprites = (
        {'x': (HOME[0] - rider.ANCHOR[0]) * 2, 'y': (HOME[1] - rider.ANCHOR[1]) * 2, 'frames': list(pictures),
         'script': [(p, dx, dy) for p, dx, dy, _ in script], 'step_ms': STEP_MS},
        {'x': face_box[0] * 2, 'y': face_box[1] * 2, 'frames': face, 'script': two, 'step_ms': 2 * STEP_MS},
        {'x': crest_box[0] * 2, 'y': crest_box[1] * 2, 'frames': crest, 'script': two, 'step_ms': 2 * STEP_MS},
        {'x': lip_box[0] * 2, 'y': lip_box[1] * 2, 'frames': lip, 'script': [(lip_poses.index(p) if full else p, 0, 0) for _, _, _, p in script],
         'step_ms': STEP_MS},
    )
    if extended:
        sprites += (_gull_sprite(GULL_A, 92, 0), _gull_sprite(GULL_B, 108, 64))
    return sprites, board_anim.encode(sprites, extended=extended)


PANELS = (('codex', 3), ('claude', 164))                       # the two compact panels: provider, left edge (they start at y=2)
PANEL_BOTTOM = {'codex': 53, 'claude': 60}                     # last row of each: Claude's carries its two five-hour rows
PANEL_TOP = 2
RESET_INK = '#91b8c6'


def panel(d, provider, x0):
    """A compact instrument panel (Tony, 2026-11-03: about 58 px, like Paradise's film panels, instead of 94: the wave and the
    sky gain the space). Codex's stops where its content does, Claude's is a little taller for its two five-hour rows."""
    bottom = PANEL_BOTTOM[provider]
    d.rounded_rectangle((x0, PANEL_TOP, x0 + 152, bottom), radius=4, fill='#102a4c', outline='#2c5a86')
    d.line((x0 + 4, PANEL_TOP + 1, x0 + 148, PANEL_TOP + 1), fill='#3d78a8')            # light catching the top edge
    d.line((x0 + 4, bottom - 1, x0 + 148, bottom - 1), fill='#0a1c36')


def instrument(d, row, provider, x):
    """One provider's compact panel: the name and the three palm icons on one row, the big number beside the reset, then the
    week's bar and, for Claude, its two five-hour rows. Nothing here ever depends on the animation below it."""
    color = YELLOW if provider == 'codex' else STONE
    value, _, old, reset = remaining_reading(row)
    count, old_bank = banked_hearts(row)
    panel(d, provider, x - 6)
    text(d, (x, 5), provider.upper(), color, 10)
    have = count if count is not None else 0
    for i in range(3):                  # one palm tree per saved reset (was a heart)
        hx = x + 83 + i * 13
        if have > i:
            for xx, yy, tone, _ in icons.cells('palm'):
                d.point((hx + xx, 5 + yy), fill=_mix(color, '#000000', -icons.DETAIL['palm']) if tone == 'o' else color)
        else:
            for xx, yy in icons.hollow('palm'):
                d.point((hx + xx, 5 + yy), fill='#4a6590')
    if icons.marked(count, old_bank):    # unknown or old: one faint dot at the end of the row, no ? and no OLD
        d.rectangle((x + 121, 9, x + 122, 10), fill='#4a6590')
    mark = icons.mark(count, old_bank)
    if mark:
        text(d, (x + 126, 6), mark, CREAM, 6)
    figure = '--' if value is None else str(round(value))
    text(d, (x, 16), figure, CREAM, 24)
    right = x + len(figure) * 24
    if value is not None:
        text(d, (right + 3, 28), '%', color, 12)
        right += 15
    if old:
        text(d, (right + 3, 29), 'OLD', color, 6)
        right += 21
    # The reset sits at the right of the number: a small label over the time, the time as big as the room left allows.
    room = x + 141 - right - 4
    stamp, size = next(((s, k) for s, k in ((reset.upper(), 10), (reset.upper().replace(' ', ''), 10),
                                            (reset.upper().replace(' ', ''), 8)) if len(s) * k <= room),
                       (reset.upper().replace(' ', ''), 8))
    left = x + 141 - len(stamp) * size
    text(d, (left, 17), 'RST', RESET_INK, 6)
    text(d, (left, 27), stamp, CREAM, size)
    d.rectangle((x - 3, 42, x + 141, 50), fill='#0a182f', outline='#2d557f')
    lit_hi, lit_lo = _mix(color, '#ffffff', .38), _mix(color, '#000000', .32)
    for j in range(20):
        on = value is not None and j < math.ceil(value / 5)
        d.rectangle((x + j * 7, 44, x + j * 7 + 4, 48), fill=color if on else '#2f435f')
        d.line((x + j * 7, 44, x + j * 7 + 4, 44), fill=lit_hi if on else '#41587a')
        d.line((x + j * 7, 48, x + j * 7 + 4, 48), fill=lit_lo if on else '#1d2d46')
    pace = session_pace(row) if provider == 'claude' else None
    if pace:
        for line, units in enumerate((math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)):
            for j in range(5):
                left = x + j * 28
                top = 52 + line * 4
                d.rectangle((left, top, left + 23, top + 2), fill='#2f435f')
                d.line((left, top + 2, left + 23, top + 2), fill='#1d2d46')
                amount = max(0, min(1, units - j))
                if amount:
                    d.rectangle((left, top, left + max(0, round(23 * amount)), top + 2), fill=color)
                    d.line((left, top, left + max(0, round(23 * amount)), top), fill=_mix(color, '#ffffff', .38))


def render_surf(snapshot, animated=False, anim_frames=8, extended_anim=False):
    """The page: sky to the top, two compact panels, the wave and the surfer. `animated` adds the animation payload (and leaves the
    sprites out of the picture); otherwise the first pose of each sprite is drawn in, so the still equals step 0 exactly."""
    image = beach().copy()
    d = ImageDraw.Draw(image)
    instrument(d, _row(snapshot, 'codex'), 'codex', 9)
    instrument(d, _row(snapshot, 'claude'), 'claude', 170)
    sprites, payload = animation(8 if anim_frames >= 8 else 4, extended=extended_anim)
    if not animated:
        for sprite in sprites:                       # the first pose, exactly where step 0 of its script puts it
            frame, dx, dy = sprite['script'][0]
            first = sprite['frames'][frame]
            first = first.resize((first.width * 2, first.height * 2), Image.Resampling.NEAREST)
            image.paste(first, (sprite['x'] + dx, sprite['y'] + dy), first)
    return (image, payload) if animated else image
