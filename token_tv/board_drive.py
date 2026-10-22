"""TOKEN RUN scenery: an original, Out Run-style daytime coast road on a 160x120 console grid.

The look of the 1986 arcade game, redrawn from scratch (nothing here is a copy of its art): a blue sky with
puffy clouds, pale mountains, a sea strip, sand on the left and grass on the right, a road in perspective
whose bands alternate, red and white kerbs, a dashed centre line, palms that rush past and a red convertible
seen from behind with two people in it.

`scene(phase)` returns the whole 160x120 picture for one of four phases. The road, the kerbs, the palms
and the car are the only things that change between phases; the loop closes because every moving thing
repeats with the same period as the road bands, so nothing jumps when the four stored poses start again.
The caller animates the `WINDOW` rectangle only (the whole road below the far distance). Nothing here depends
on the clock, an account or randomness that changes between calls.
"""
from functools import lru_cache
import math
import random

from PIL import Image, ImageDraw

from token_tv.board_surf import _bands, _frond, _mix

W, H = 160, 120
HORIZON = 52
CENTRE = 80
WINDOW = (46, 53, 115, 120)          # x0, y0, x1, y1 (exclusive): the part that is animated, 34 px each side of the centre
STEP_MS = 160
PHASES = 4
DIALS = ((29, 92), (131, 92))        # the two usage dials set into the bottom corners (see board_dials.py)
DIAL_RADIUS = 28.0

SKY = [(-2, '#2b66cf'), (9, '#3b7de0'), (18, '#5593ea'), (27, '#78b1f1'), (35, '#9fcdf7'), (42, '#c6e6fc'), (47, '#e2f3ff')]
HAZE = '#e2f3ff'
RED, WHITE = '#d9392b', '#f6f4ee'
ASPHALT = ('#565566', '#6c6b7c')      # dark band, light band


# The slow things of the sky. They are NOT in the picture the board stores: each is a small transparent sprite that
# the board moves a little (all at STEP_MS), so the sky is quietly alive. Their restoration boxes are disjoint, stay
# clear of the scoreboard (canvas rows 0-16) and of the road window, and every script starts at offset (0, 0).
def _gull_frames():
    shapes = ('XX.....XX/.XXX.XXX./...XXX.../.........',
              '........./XXXXXXXXX/...XXX.../.........',
              '........./...XXX.../.XXXXXXX./XX.....XX')
    frames = []
    for shape in shapes:
        rows = shape.split('/')
        frame = Image.new('RGBA', (9, 4), (0, 0, 0, 0))
        for y, row in enumerate(rows):
            for x, cell in enumerate(row):
                if cell == 'X':
                    under = y + 1 < 4 and rows[y + 1][x] == 'X'
                    frame.putpixel((x, y), (255, 255, 255, 255) if under or y == 0 else (176, 190, 214, 255))
        frames.append(frame)
    return frames


@lru_cache(maxsize=1)
def ambient():
    """Sprites for the sky: dicts with x, y (final px), frames (RGBA, canvas pixels, unfiltered) and script."""
    out = []
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    _cumulus(layer, 92, 29, 32, 13)
    box = layer.getbbox()
    cloud = layer.crop(box)
    out.append({'name': 'cloud', 'x': box[0] * 2, 'y': box[1] * 2, 'frames': [cloud],
                'script': [(0, 2 * round(4 * math.sin(2 * math.pi * k / 32)), 0) for k in range(32)]})
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    _balloon(ImageDraw.Draw(layer), 40, 26)
    box = layer.getbbox()
    out.append({'name': 'balloon', 'x': box[0] * 2, 'y': box[1] * 2, 'frames': [layer.crop(box)],
                'script': [(0, 2 * round(2 * math.sin(2 * math.pi * k / 16)), -4 * (1 if 4 <= k < 12 else 0))
                           for k in range(16)]})
    out.append({'name': 'gull', 'x': 134 * 2, 'y': 28 * 2, 'frames': _gull_frames(),
                'script': [((0, 1, 2, 1)[k % 4], 2 * round(6 * math.sin(2 * math.pi * k / 32)),
                            4 * round(.5 * (1 - math.cos(2 * math.pi * k / 32)))) for k in range(32)]})
    return out


def _shows_cleanly(box):
    """True if a roadside object may be drawn: every pixel of its box that lies outside the animated window is
    under a dial (hidden anyway) or off the screen. Anything else would be cut by the window's edge and leave a
    frozen piece in the static picture."""
    wx0, wy0, wx1, wy1 = WINDOW
    for y in range(max(0, box[1]), min(H - 1, box[3]) + 1):
        for x in range(max(0, box[0]), min(W - 1, box[2]) + 1):
            if wx0 <= x < wx1 and wy0 <= y < wy1:
                continue
            if not any(math.hypot(x - cx, y - cy) <= DIAL_RADIUS for cx, cy in DIALS):
                return False
    return True


def _palm_box(x, base, size):
    reach = round(size * .55) + 3 if size >= 10 else max(3, size // 2 + 1) + 2
    return (x - reach, _palm_top(base, size), x + reach, base + 1)


def _depth(w):
    """Rows below the horizon of world position w (anything behind the viewer is far below the screen)."""
    return 70 / w - 4 if w > .1 else 999


def _half(t):
    """Half the road's width at depth t; the kerbs must end inside the window on the last row (checked by a test)."""
    return 1.6 + t * 0.42


def _cumulus(im, cx, cy, width, height):
    """A puffy white cloud: round tops, a flat bottom and a blue-grey underside (flat tones, no gradient)."""
    d = ImageDraw.Draw(im)
    rnd = random.Random(cx * 31 + cy)
    puffs = []
    x = cx - width // 2
    while x < cx + width // 2:
        r = rnd.randint(height // 3, height // 2 + 1)
        puffs.append((x, cy - r // 2 + rnd.randint(-1, 1), r))
        x += max(3, r)
    mask = Image.new('L', im.size, 0)
    md = ImageDraw.Draw(mask)
    for x, y, r in puffs:
        md.ellipse((x - r, y - r, x + r, y + r), fill=255)
    md.rectangle((cx - width // 2, cy - 1, cx + width // 2, cy + 2), fill=255)
    mask = mask.crop((0, 0, im.width, im.height))
    px = mask.load()
    out = im.load()
    for y in range(im.height):
        for x in range(im.width):
            if not px[x, y]:
                continue
            if y > cy + 1:
                out[x, y] = (154, 190, 232)           # the flat shaded bottom
            elif y > cy - 2:
                out[x, y] = (206, 226, 248)           # the soft underside edge
            else:
                out[x, y] = (255, 255, 255)
    d.line((cx - width // 2 + 2, cy + 3, cx + width // 2 - 3, cy + 3), fill='#8fb2e0')


def _ridge(d, base, seed, amplitude, colour, edge, step=5):
    """A mountain range as a jagged silhouette, with a lighter ridge line along its crest."""
    rnd = random.Random(seed)
    heights = [rnd.uniform(.25, 1) for _ in range(W // step + 3)]
    prev = None
    tops = []
    for x in range(W):
        i, f = divmod(x, step)
        h = heights[i] + (heights[i + 1] - heights[i]) * f / step
        top = base - round(amplitude * (.35 + .65 * h))
        d.line((x, top, x, base), fill=colour)
        d.point((x, top), fill=edge)
        if prev is not None and abs(top - prev) > 1:
            d.line((x, min(top, prev), x, max(top, prev)), fill=edge)
        prev = top
        tops.append(top)
    return tops


def _snow(d, tops, depth=4):
    """White caps on the highest peaks of a range, with a pale blue shaded side."""
    limit = min(tops) + depth
    for x, top in enumerate(tops):
        if top >= limit:
            continue
        for k, y in enumerate(range(top, min(limit, top + 4))):
            d.point((x, y), fill='#ffffff' if k < 2 else '#cfe0f6')
        if x + 1 < len(tops) and tops[x + 1] < top:                       # the lee side of a peak is in shade
            d.point((x, top + 1), fill='#cfe0f6')


def _balloon(d, cx, cy):
    """A hot-air balloon with striped panels, a lit left side, ropes and a basket."""
    stripes = ('#d9392b', '#f6f4ee', '#2f6fd0', '#f6f4ee')
    for y in range(cy - 6, cy + 6):
        reach = round(5 * math.sqrt(max(0.0, 1 - ((y - cy + .5) / 6.2) ** 2)) + (0 if y < cy + 3 else -(y - cy - 2) * .6))
        for x in range(cx - reach, cx + reach + 1):
            colour = stripes[((x - cx + 5) // 2) % 4]
            if x - cx > 2:
                colour = _mix(colour, '#1b2a5c', .28)
            elif x - cx < -2 and y < cy:
                colour = _mix(colour, '#ffffff', .25)
            d.point((x, y), fill=colour)
    d.line((cx - 2, cy + 6, cx - 1, cy + 8), fill='#4a3320')
    d.line((cx + 2, cy + 6, cx + 1, cy + 8), fill='#4a3320')
    d.rectangle((cx - 1, cy + 8, cx + 1, cy + 9), fill='#9a6a38')


def _plane(d, x, y):
    """A little propeller plane flying left and towing a striped banner."""
    d.line((x, y, x + 7, y), fill='#d9392b')                       # fuselage
    d.line((x + 1, y + 1, x + 6, y + 1), fill='#f6f4ee')
    d.rectangle((x + 7, y - 2, x + 8, y), fill='#d9392b')           # tail fin
    d.line((x + 2, y - 2, x + 5, y - 2), fill='#2f6fd0')            # upper wing
    d.line((x + 2, y + 2, x + 5, y + 2), fill='#2f6fd0')            # lower wing
    d.line((x + 3, y - 1, x + 3, y + 1), fill='#8a8aa0')            # strut
    d.line((x - 1, y - 1, x - 1, y + 1), fill='#bfc7d8')            # the propeller disc
    d.line((x + 8, y + 1, x + 11, y + 1), fill='#8a8aa0')           # the tow line
    for k in range(18):                                             # banner: alternating red and cream blocks
        d.rectangle((x + 12 + k, y - 1, x + 12 + k, y + 3), fill='#d9392b' if (k // 3) % 2 == 0 else '#f6f4ee')
    d.line((x + 12, y - 1, x + 29, y - 1), fill='#8f2a22')
    d.line((x + 12, y + 3, x + 29, y + 3), fill='#a8a49a')


def _boat(d, x, y, size):
    """A sailboat seen side-on: hull, two sails and a pennant."""
    d.line((x - size, y, x + size, y), fill='#8a2b2b')
    d.line((x - size + 1, y + 1, x + size - 1, y + 1), fill='#5c1c1c')
    d.line((x, y - 2 * size - 1, x, y - 1), fill='#4a3a2a')
    d.polygon([(x + 1, y - 2 * size), (x + 1, y - 1), (x + size + 1, y - 1)], fill='#ffffff')
    d.polygon([(x - 1, y - 2 * size + 1), (x - 1, y - 1), (x - size, y - 1)], fill='#d6e2f2')
    d.point((x, y - 2 * size - 1), fill='#d9392b')


def _lighthouse(d, cx, base):
    """A small rocky islet with a striped lighthouse and a lamp."""
    d.ellipse((cx - 9, base - 3, cx + 9, base + 1), fill='#6c7a72')
    d.ellipse((cx - 8, base - 4, cx + 8, base - 1), fill='#4f8a4f')
    d.line((cx - 7, base - 3, cx - 2, base - 4), fill='#79b36c')
    for y in range(base - 11, base - 3):
        width = 1 if y < base - 9 else 2
        d.line((cx - width + 1, y, cx + width - 1 + (1 if width == 2 else 0), y),
               fill='#d9392b' if (y - base) % 4 in (0, 1) else '#f6f4ee')
    d.rectangle((cx - 1, base - 13, cx + 1, base - 12), fill='#2b2b3a')
    d.point((cx, base - 13), fill='#ffe98a')
    d.point((cx - 2, base - 13), fill='#fff6c8')
    d.point((cx + 2, base - 13), fill='#fff6c8')


def _tree(d, x, base, r):
    """A round-topped tree: a short trunk, a dark canopy and a lit upper left."""
    d.rectangle((x, base - r, x, base), fill='#6a421f')
    d.ellipse((x - r, base - 2 * r - 1, x + r, base - 1), fill='#2a7a38')
    d.ellipse((x - r, base - 2 * r - 1, x + r - 1, base - r - 1), fill='#4cb04c')


def _bird(d, x, y):
    for dx, dy in ((0, 0), (1, 1), (2, 0), (3, 1), (4, 0)):
        d.point((x + dx, y + dy), fill='#33415f')


def _streak(d, x, y, width):
    """A thin wisp of high cloud: two pale lines that taper at both ends."""
    d.line((x + 2, y, x + width - 3, y), fill='#f2f9ff')
    d.line((x, y + 1, x + width // 2, y + 1), fill='#d4e8fb')
    d.line((x + width // 3, y - 1, x + width - 6, y - 1), fill='#e4f2fe')


SEA_HORIZON = 40


@lru_cache(maxsize=1)
def _backdrop():
    """Everything that never moves: sky, clouds, mountains, sea, the two roadsides and their texture."""
    im = Image.new('RGB', (W, H), HAZE)
    d = ImageDraw.Draw(im)
    _bands(d, SKY, 0, HORIZON, 0.9, seed=4)
    _streak(d, 4, 20, 26)
    _streak(d, 118, 18, 30)
    _streak(d, 66, 33, 22)
    for cx, cy, w, h in ((22, 38, 26, 10), (146, 40, 22, 8), (60, 43, 16, 6), (126, 24, 18, 7)):
        _cumulus(im, cx, cy, w, h)
    far = _ridge(d, HORIZON, 2, 20, '#86a9d6', '#a9c6ea', 6)         # far range, hazy, with snow
    _snow(d, far)
    _ridge(d, HORIZON, 5, 11, '#5f89c4', '#86abdb', 4)               # near range
    # The bay on the left: a high horizon, three tones of water, glints, boats and an islet with a lighthouse.
    bay = [(0, SEA_HORIZON), (56, SEA_HORIZON), (66, 46), (76, HORIZON), (0, HORIZON)]
    d.polygon(bay, fill='#2a9fc0')
    d.polygon([(0, 44), (60, 44), (68, 47), (76, HORIZON), (0, HORIZON)], fill='#27b3c9')
    d.polygon([(0, 48), (68, 48), (76, HORIZON), (0, HORIZON)], fill='#44d1d8')
    d.line((0, SEA_HORIZON, 56, SEA_HORIZON), fill='#8fe4ee')
    rnd = random.Random(11)
    for _ in range(40):
        x, y = rnd.randint(0, 66), rnd.randint(SEA_HORIZON + 1, HORIZON - 1)
        if (x, y) in {(a, b) for a, b in ()} or x > 56 + (y - SEA_HORIZON) * 1.4:
            continue
        d.line((x, y, x + rnd.randint(1, 4), y), fill='#c4f6fb')
    _lighthouse(d, 30, SEA_HORIZON + 1)
    _boat(d, 12, 47, 3)
    _boat(d, 46, 44, 2)
    _boat(d, 52, 49, 3)
    for x, y in ((8, 28), (14, 31), (56, 19)):
        _bird(d, x, y)
    _plane(d, 118, 20)
    d.polygon([(100, HORIZON), (110, HORIZON - 6), (124, HORIZON - 8), (140, HORIZON - 5), (160, HORIZON - 7),
               (160, HORIZON)], fill='#3f9a4a')                          # green hills on the right
    d.line([(100, HORIZON), (110, HORIZON - 6), (124, HORIZON - 8), (140, HORIZON - 5), (160, HORIZON - 7)], fill='#6fc766')
    for hx, hy in ((116, HORIZON - 7), (128, HORIZON - 8), (146, HORIZON - 6), (154, HORIZON - 7)):
        _tree(d, hx, hy + 4, 2)                                           # a row of tiny round trees on the crest
    d.rectangle((134, HORIZON - 6, 138, HORIZON - 3), fill='#f6f4ee')    # a white villa with a red roof
    d.rectangle((133, HORIZON - 8, 139, HORIZON - 7), fill='#c8442f')
    d.point((136, HORIZON - 4), fill='#2f6fd0')
    # The two roadsides: pale sand with the sea behind it on the left, bright grass on the right.
    d.rectangle((0, HORIZON + 1, W - 1, H - 1), fill='#5cb73e')
    d.polygon([(0, HORIZON + 1), (CENTRE - 2, HORIZON + 1), (CENTRE - 2, H - 1), (0, H - 1)], fill='#ecd08a')
    rnd = random.Random(23)
    for _ in range(190):                                                 # sand grain and grass speckle, all static
        x, y = rnd.randint(0, W - 1), rnd.randint(HORIZON + 2, H - 1)
        if x < CENTRE:
            d.point((x, y), fill=rnd.choice(('#dcb870', '#f6e2a8', '#d4ae66')))
        else:
            d.point((x, y), fill=rnd.choice(('#4aa433', '#74cd54', '#439a2e')))
    return im


PALM_TONES = ('#1d6a2c', '#35a043', '#7ad86e')


def _palm_top(base, size):
    """The highest row a palm of this size touches, used to keep every moving object below the window's top."""
    return base - size - (2 if size < 10 else round(size * .6) + 2)


def _palm(d, x, base, size):
    """A roadside palm: a ringed, tapering trunk, a coconut cluster and a crown of drooping fronds (`size` = trunk height)."""
    top = base - size
    width = 1 if size < 8 else 2 if size < 15 else 3
    left = x - width // 2
    for i in range(size):
        narrow = width > 2 and i > size * .7
        ring = '#8a5a34' if (i // 2) % 2 else '#b0793f'
        for k in range(width - (1 if narrow else 0)):
            colour = '#6a421f' if k == width - 1 - (1 if narrow else 0) and width > 1 else ring
            d.point((left + k, base - i), fill=colour)
    d.ellipse((left - 2, base - 1, left + width + 1, base + 1), fill='#c4a45e')            # a little sand heap at the foot
    if size < 5:
        d.rectangle((x - 1, top - 1, x + 1, top), fill=PALM_TONES[1])
        return
    if size < 10:
        reach = max(3, size // 2 + 1)
        for dx, dy in ((-reach, 2), (-reach + 1, 0), (-reach // 2, -1), (reach // 2, -1), (reach - 1, 0), (reach, 2)):
            d.line((x, top, x + dx, top + dy), fill=PALM_TONES[1])
            d.line((x + dx, top + dy, x + dx + (1 if dx > 0 else -1), top + dy + 2), fill=PALM_TONES[0])
        d.line((x - reach + 2, top - 1, x + reach - 2, top - 1), fill=PALM_TONES[2])
        return
    length = round(size * .55)
    for angle in (-172, -140, -108, -72, -40, -8):
        _frond(d, x, top, angle, length, length * .55, PALM_TONES)
    for angle in (172, 8):                                                              # two low fronds hanging to the sides
        _frond(d, x, top, angle, max(3, length - 2), length * .9, PALM_TONES)
    d.rectangle((x - 1, top + 1, x + 1, top + 2), fill='#5a3a1c')                       # coconuts under the crown
    d.point((x, top + 3), fill='#4a2e14')


def _road(d, phase):
    """The road in perspective: bands that alternate in depth, red and white kerbs and a dashed centre line.

    A row at depth t has world position w = 70 / (t + 4); the band colour flips every half unit of w and
    shifting w by a quarter per phase makes the bands run towards the viewer. Four phases close the loop."""
    for y in range(HORIZON + 1, H):
        t = y - HORIZON
        p = phase if y >= WINDOW[1] else 0                                   # the far strip is the same in every pose
        dark = ((70 / (t + 4) + p / PHASES) % 1.0) < .5
        half = _half(t)
        x0, x1 = round(CENTRE - half), round(CENTRE + half)
        haze = max(0.0, 1 - t / 24) * .65                                    # distance fades into the sky's haze
        tarmac = _mix(ASPHALT[0] if dark else ASPHALT[1], HAZE, haze)
        d.line((x0, y, x1, y), fill=tarmac)
        kerb = max(1, round(1 + t * 0.045))
        colour = _mix(RED if dark else WHITE, HAZE, haze)
        d.line((x0 - kerb, y, x0 - 1, y), fill=colour)
        d.line((x1 + 1, y, x1 + kerb, y), fill=colour)
        if not dark:
            dash = max(1, round(t * 0.03))
            d.line((CENTRE - dash // 2, y, CENTRE + (dash - 1) // 2, y), fill=_mix('#f0f0e8', HAZE, haze))
        edge = _mix('#f4f4ec', HAZE, haze)
        d.point((x0 + 1, y), fill=edge)                                       # a thin white line inside each kerb
        d.point((x1 - 1, y), fill=edge)


def _roadside(d, phase):
    """Palms on the sand (left), bushes and round trees on the grass (right), all coming at the viewer.

    World positions w = 1.5, 2.5, 3.5 ... slide a quarter per phase, so after four phases each object takes its
    neighbour's place and the loop never jumps. Nothing may touch a row above the animated window (that strip is
    the static picture), so an object only appears once its whole outline is below it; that depends on its world
    position alone and therefore repeats with the loop."""
    top_row = WINDOW[1]
    for k in range(-1, 11):                                                      # k = -1 is the nearest, at the bottom edge
        w = 1.5 + k - phase / PHASES
        t = _depth(w)
        y = round(HORIZON + t)
        half = _half(t)
        size = max(2, round(2 + t * 0.34))
        px = round(CENTRE - half - 6 - t * 0.14)
        if _palm_top(y, size) >= top_row and y <= H + 8 and _shows_cleanly(_palm_box(px, y, size)):
            _palm(d, px, y, size)
        w2 = w + .5                                                              # half a unit apart from the palms
        t2 = _depth(w2)
        y2 = round(HORIZON + t2)
        half2 = _half(t2)
        r = max(1, round(1 + t2 * 0.07))
        bx = round(CENTRE + half2 + 5 + t2 * 0.14)
        if y2 - 2 * r >= top_row and y2 <= H + 6 and _shows_cleanly((bx - 2 * r, y2 - 2 * r, bx + 2 * r, y2)):
            d.ellipse((bx - r * 2, y2 - r * 2, bx + r * 2, y2), fill='#2f8a3c')
            d.ellipse((bx - r * 2 + 1, y2 - r * 2, bx + r, y2 - r), fill='#56bf55')
            size2 = max(2, round(2 + t2 * 0.34))                                 # a second palm further out on the sand
            px2 = round(CENTRE - half2 - 13 - t2 * 0.22)
            if _palm_top(y2, size2) >= top_row and _shows_cleanly(_palm_box(px2, y2, size2)):
                _palm(d, px2, y2, size2)
        w3 = w + .25                                                             # taller round trees on the far grass
        t3 = _depth(w3)
        y3 = round(HORIZON + t3)
        rt = max(2, round(1 + t3 * 0.1))
        tx = round(CENTRE + _half(t3) + 12 + t3 * 0.4)
        if y3 - 3 * rt >= top_row and y3 <= H + 6 and _shows_cleanly((tx - rt, y3 - 2 * rt - 1, tx + rt, y3)):
            _tree(d, tx, y3, rt)


def _rival(d, cx, by, width, body, light, lift):
    """Another car seen from behind, further up the road: tyres, a lit body, a dark rear window and taillights."""
    half = width // 2
    by -= lift
    d.line((cx - half, by + 1, cx + half, by + 1), fill='#40404e')
    d.rectangle((cx - half, by - 2, cx - half + 1, by), fill='#16161e')
    d.rectangle((cx + half - 1, by - 2, cx + half, by), fill='#16161e')
    d.rectangle((cx - half + 1, by - 5, cx + half - 1, by - 1), fill=body)
    d.line((cx - half + 1, by - 5, cx + half - 1, by - 5), fill=light)
    d.rectangle((cx - half + 3, by - 8, cx + half - 3, by - 5), fill=body)
    d.line((cx - half + 3, by - 8, cx + half - 3, by - 8), fill=light)
    d.rectangle((cx - half + 4, by - 7, cx + half - 4, by - 6), fill='#1d2640')
    d.rectangle((cx - half + 1, by - 4, cx - half + 2, by - 3), fill='#ff4332')
    d.rectangle((cx + half - 2, by - 4, cx + half - 1, by - 3), fill='#ff4332')


def _traffic(d, phase):
    """Two cars ahead in their own lanes. They hold their place on the road (they run at our speed), so only
    their bounce changes, and they sit inside the animated window."""
    _rival(d, CENTRE - 4, 67, 9, '#2f6fd0', '#7aa8ee', phase % 2)
    _rival(d, CENTRE + 8, 82, 15, '#f2c230', '#ffe79a', 1 - phase % 2)


def _car(d, phase):
    """An original red convertible seen from behind, with a blonde passenger and a dark-haired driver.

    Wide low body, black tail panel with slats, taillights, a plate, two headrests and the occupants' heads.
    The body rises a pixel on the odd phases and the tyre treads alternate, so the car feels alive."""
    cx, by = CENTRE, 114
    lift = 1 if phase % 2 else 0
    d.ellipse((cx - 19, by - 1, cx + 19, by + 4), fill='#40404e')              # the shadow on the road
    for side in (-1, 1):                                                       # tyres with alternating tread
        x0 = cx + side * 14 - 3
        d.rectangle((x0, by - 9, x0 + 6, by), fill='#16161e')
        for k in range(0, 10, 2):
            if (k // 2 + phase) % 2:
                d.line((x0 + 1, by - 9 + k, x0 + 5, by - 9 + k), fill='#2f2f3a')
    y = by - lift
    d.polygon([(cx - 18, y - 11), (cx + 18, y - 11), (cx + 19, y - 5), (cx + 17, y - 1), (cx - 17, y - 1), (cx - 19, y - 5)], fill='#e03121')
    d.line((cx - 17, y - 11, cx + 17, y - 11), fill='#ff7a5c')                  # light catching the rear deck
    d.line((cx - 18, y - 10, cx - 18, y - 6), fill='#ff5a3c')
    d.line((cx - 17, y - 2, cx + 17, y - 2), fill='#a31a17')                    # the shaded lower edge
    d.rectangle((cx - 16, y - 1, cx + 16, y), fill='#1b1b24')                   # black bumper
    d.rectangle((cx - 10, y - 9, cx + 10, y - 4), fill='#17171f')               # the tail panel with red slats
    for yy in (y - 8, y - 6):
        d.line((cx - 9, yy, cx + 9, yy), fill='#e03121')
    for side in (-1, 1):                                                       # taillights
        x0 = cx + side * 14
        d.rectangle((x0 - 3, y - 9, x0 + 3, y - 6), fill='#ff4332')
        d.line((x0 - 2, y - 8, x0 + 2, y - 8), fill='#ffd8b0')
    d.rectangle((cx - 3, y - 5, cx + 3, y - 3), fill='#f6f2dc')                 # the plate
    d.point((cx - 1, y - 4), fill='#3a3a48'); d.point((cx + 1, y - 4), fill='#3a3a48')
    # the cockpit: a dark inside, two headrests, shoulders and heads
    d.polygon([(cx - 14, y - 12), (cx + 14, y - 12), (cx + 12, y - 17), (cx - 12, y - 17)], fill='#2a1a1c')
    for side, hair, top in ((-1, '#f4cc58', '#f6f0dc'), (1, '#4a2f1c', '#2c68c8')):
        hx = cx + side * 6
        d.rectangle((hx - 3, y - 15, hx + 3, y - 12), fill=top)                  # shoulders
        d.rectangle((hx - 2, y - 20, hx + 2, y - 16), fill='#ffd4a0')            # head
        d.rectangle((hx - 3, y - 21, hx + 3, y - 18), fill=hair)                 # hair
        d.point((hx + (1 if side > 0 else -1), y - 18), fill='#2a2438')          # a side glance
    d.line((cx - 13, y - 12, cx + 13, y - 12), fill='#8a1d18')
    if phase % 2 == 0:                                                         # exhaust puffs, alternating
        for dx, dy in ((-8, 3), (-9, 4), (8, 3), (9, 4)):
            d.point((cx + dx, by + dy), fill='#a9a9b8')
    else:
        for dx, dy in ((-9, 3), (-10, 3), (9, 3), (10, 3)):
            d.point((cx + dx, by + dy), fill='#c8c8d6')


@lru_cache(maxsize=PHASES)
def scene(phase):
    """The whole scene for `phase` (0..3) as a 160x120 RGB image."""
    im = _backdrop().copy()
    d = ImageDraw.Draw(im)
    _road(d, phase)
    _roadside(d, phase)
    _traffic(d, phase)
    _car(d, phase)
    return im
