"""Original coastal arcade scenery, drawn locally on a 160x120 console grid.

Sea, beach and a three-lane bend share one horizon. Four stored road poses carry
the advancing scenery; separate small sprites move resort palms and a gull. No game
assets, live account data, wall-clock animation or new firmware are needed.
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
STEP_MS = 120
PHASES = 4
DIALS = ((29, 92), (131, 92))        # the two usage dials set into the bottom corners (see board_dials.py)
DIAL_RADIUS = 28.0

SKY = [(-2, '#075bd1'), (16, '#087de8'), (29, '#159cf0'), (41, '#53c3f4'), (50, '#a3e4f5')]
HAZE = '#bedfe3'
RED, WHITE = '#ef3939', '#fff3d8'
ASPHALT = ('#555d6d', '#687184')


# The resort palms and gull are NOT in the picture the board stores: each is a transparent sprite that
# the board moves a little (all at STEP_MS). Their restoration boxes are disjoint, stay
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
    """Ambient sprites: x/y in screen pixels, unfiltered RGBA frames and scripts."""
    out = []
    # One tiny texture per palm keeps all four road poses and the original
    # 120 ms cadence. The nearer resort palm drifts further, but both take five
    # road cycles to follow the bend and return without teleporting. Clouds
    # and glints now belong to the backdrop to stay within four sprite slots.
    for name, x, base, size, reach in (('palm-far', 123, 58, 15, 2),
                                      ('palm-near', 152, 67, 29, 6)):
        layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        _palm(ImageDraw.Draw(layer), x, base, size)
        box = layer.getbbox()
        out.append({'name': name, 'x': box[0] * 2, 'y': box[1] * 2,
                    'frames': [layer.crop(box)],
                    'script': [(0, 2 * round(reach * .5 * (1 - math.cos(2 * math.pi * k / 20))), 0)
                               for k in range(20)]})
    out.append({'name': 'gull', 'x': 44 * 2, 'y': 23 * 2, 'frames': _gull_frames(),
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


def _centre(t):
    """A gentle right-hand bend in the distance, straight under the car."""
    return CENTRE + 12 * max(0, 1 - t / (H - HORIZON - 1)) ** 2


def _shore(t):
    return _centre(t) - _half(t) - 9 - t * .35


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
            light = max(((py - y) / r + .22 * (puff_x - x) / r
                         for puff_x, py, r in puffs if (x - puff_x) ** 2 + (y - py) ** 2 <= r * r), default=-1)
            if y > cy + 1:
                out[x, y] = (145, 187, 218)
            elif light < -.50:
                out[x, y] = (194, 216, 230)
            elif light < -.16:
                out[x, y] = (229, 237, 239)
            else:
                out[x, y] = (255, 253, 240)
    d.line((cx - width // 2 + 2, cy + 3, cx + width // 2 - 3, cy + 3), fill='#8fb2e0')


def _boat(d, x, y, size):
    """A sailboat seen side-on: hull, two sails and a pennant."""
    d.line((x - size, y, x + size, y), fill='#8a2b2b')
    d.line((x - size + 1, y + 1, x + size - 1, y + 1), fill='#5c1c1c')
    d.line((x, y - 2 * size - 1, x, y - 1), fill='#4a3a2a')
    d.polygon([(x + 1, y - 2 * size), (x + 1, y - 1), (x + size + 1, y - 1)], fill='#ffffff')
    d.polygon([(x - 1, y - 2 * size + 1), (x - 1, y - 1), (x - size, y - 1)], fill='#d6e2f2')
    d.point((x, y - 2 * size - 1), fill='#d9392b')


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


@lru_cache(maxsize=1)
def _backdrop():
    """A level sea meets the road, with a beach reaching toward the viewer.

    Large peripheral palms belong to the distant resort. Near roadside palms
    live in the animated window; the two must not leave frozen sprite pieces.
    """
    im = Image.new('RGB', (W, H), HAZE)
    d = ImageDraw.Draw(im)
    _bands(d, SKY, 0, HORIZON, 0.0, seed=4)
    for cx, cy, w, h in ((13, 34, 34, 18), (52, 44, 62, 12), (124, 40, 24, 9)):
        _cumulus(im, cx, cy, w, h)
    _cumulus(im, 92, 29, 32, 13)
    _streak(d, 44, 18, 22)
    # Only the right-hand headland rises above the water. There is no mountain
    # wall behind a strip of sea suspended above a second ground horizon.
    d.polygon([(81, 52), (98, 47), (108, 39), (118, 42), (130, 33),
               (139, 36), (151, 30), (159, 33), (159, 53)], fill='#438c9f')
    d.polygon([(93, 52), (108, 44), (113, 46), (130, 37), (136, 41),
               (150, 35), (159, 37), (159, 54)], fill='#367c72')
    d.polygon([(103, 52), (118, 47), (132, 45), (147, 42), (159, 45), (159, 55)], fill='#48a54c')
    for y in range(HORIZON, H):
        t = y - HORIZON
        shore = round(_shore(t))
        road_edge = round(_centre(t) + _half(t))
        # The wet strip is narrow in the distance and widens with perspective.
        d.line((0, y, W - 1, y), fill='#66bf43' if (y // 6) % 2 else '#59af39')
        d.line((0, y, road_edge + 2, y), fill='#f5db91')
        d.line((0, y, shore, y), fill='#248fbd' if t < 2 else '#1dbabf' if t < 8 else '#35d4cc')
        d.line((shore + 1, y, shore + max(1, round(1 + t * .05)), y), fill='#e5fff1')
        d.point((shore + max(2, round(2 + t * .06)), y), fill='#d9bc76')
    d.line((0, HORIZON, round(_shore(0)), HORIZON), fill='#4cd6e1')
    # Distant waves shrink to horizontal strokes; the nearer glints animate.
    for x, y, width in ((3, 54, 9), (25, 54, 6), (46, 55, 7), (58, 57, 5),
                        (0, 63, 13), (43, 62, 8), (5, 68, 14), (35, 69, 6)):
        d.line((x, y, min(x + width, round(_shore(y - HORIZON)) - 4), y), fill='#9af2e4')
    for x, y, length in ((1, 0, 5), (13, 0, 3), (6, 2, 5), (16, 3, 4)):
        offset = y % 3
        d.line((21 + x + offset, 58 + y, 21 + min(21, x + length + offset), 58 + y),
               fill='#baf9ee' if y % 2 == 0 else '#65e2dd')
    _boat(d, 14, 56, 2)
    # A tall foreground windsurf sail and a smaller distant one ground the
    # left side in the sea. Palms stand on the sand, never in open water.
    d.line((15, 64, 15, 35), fill='#243764')
    d.polygon([(14, 37), (14, 60), (2, 60)], fill='#d72b80')
    d.polygon([(12, 42), (12, 50), (8, 50)], fill='#ffd7dd')
    d.polygon([(7, 52), (13, 52), (13, 57), (4, 57)], fill='#f8e7d8')
    d.line((3, 59, 13, 59), fill='#ff74ac')
    d.line((8, 64, 20, 64), fill='#fff4cf')
    d.line((10, 66, 19, 66), fill='#1588a8')
    d.line((16, 59, 18, 63), fill='#2b4272')
    d.point((16, 58), fill='#f5c28c')
    d.line((53, 55, 53, 43), fill='#26346b')
    d.polygon([(52, 44), (52, 53), (47, 53)], fill='#e93486')
    d.line((49, 49, 52, 48), fill='#ffb4d3')
    d.line((47, 54, 55, 54), fill='#fff0d4')
    d.line((48, 56, 55, 56), fill='#167caa')
    # White resort blocks, balcony slots, terracotta roofs, beach parasols.
    for x, base, width, height in ((114, 53, 7, 7), (124, 52, 8, 10), (136, 53, 9, 7), (152, 55, 8, 9)):
        d.rectangle((x, base - height, x + width, base), fill='#f5eee0')
        d.rectangle((x + width - 2, base - height + 1, x + width, base), fill='#cbbcb3')
        d.line((x - 1, base - height, x + width + 1, base - height), fill='#ca5a42')
        for yy in range(base - height + 3, base, 3):
            d.line((x + 1, yy, x + width - 3, yy), fill='#467386')
        d.point((x + 3, base), fill='#244e5e')
    for x, y, shade in ((109, 58, '#f5a2c6'), (120, 61, '#fff0b5'), (151, 63, '#ef6478')):
        d.line((x, y - 4, x, y), fill='#736447')
        d.polygon([(x - 3, y - 3), (x, y - 5), (x + 3, y - 3)], fill=shade)
        d.line((x - 3, y - 2, x + 3, y - 2), fill='#9c635b')
    # No fixed palm over the left-hand sea. The two large resort palms on
    # the right are separate slow layers; small horizon palms remain distant.
    for x, base, size in ((82, 54, 4), (86, 53, 3), (89, 53, 2), (102, 53, 4), (108, 54, 6)):
        _palm(d, x, base, size)
    for x, y in ((24, 23), (29, 25)):
        _bird(d, x, y)
    return im


PALM_TONES = ('#134d3e', '#258d45', '#8bd747')


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
    """A three-lane bend: advancing depth bands, kerbs and two dashed lane dividers.

    A row at depth t has world position w = 70 / (t + 4); the band colour flips every half unit of w and
    shifting w by a quarter per phase makes the bands run towards the viewer. Four phases close the loop."""
    for y in range(HORIZON + 1, H):
        t = y - HORIZON
        p = phase if y >= WINDOW[1] else 0                                   # the far strip is the same in every pose
        dark = ((70 / (t + 4) + p / PHASES) % 1.0) < .5
        half = _half(t)
        centre = _centre(t)
        x0, x1 = round(centre - half), round(centre + half)
        haze = max(0.0, 1 - t / 22) * .35
        tarmac = _mix(ASPHALT[0] if dark else ASPHALT[1], HAZE, haze)
        d.line((x0, y, x1, y), fill=tarmac)
        kerb = max(1, round(1 + t * 0.045))
        colour = _mix(RED if dark else WHITE, HAZE, haze)
        d.line((x0 - kerb, y, x0 - 1, y), fill=colour)
        d.line((x1 + 1, y, x1 + kerb, y), fill=colour)
        if not dark:
            dash = max(1, round(t * 0.025))
            for side in (-1, 1):
                x = round(centre + side * half / 3)
                d.line((x - dash // 2, y, x + (dash - 1) // 2, y), fill=_mix('#fff7e4', HAZE, haze))
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
        px = round(_centre(t) - half - 4 - t * 0.10)
        if _palm_top(y, size) >= top_row and y <= H + 8 and _shows_cleanly(_palm_box(px, y, size)):
            _palm(d, px, y, size)
        w2 = w + .5                                                              # half a unit apart from the palms
        t2 = _depth(w2)
        y2 = round(HORIZON + t2)
        half2 = _half(t2)
        r = max(1, round(1 + t2 * 0.07))
        bx = round(_centre(t2) + half2 + 4 + t2 * 0.10)
        if y2 - 2 * r >= top_row and y2 <= H + 6 and _shows_cleanly((bx - 2 * r, y2 - 2 * r, bx + 2 * r, y2)):
            d.ellipse((bx - r * 2, y2 - r * 2, bx + r * 2, y2), fill='#2f8a3c')
            d.ellipse((bx - r * 2 + 1, y2 - r * 2, bx + r, y2 - r), fill='#56bf55')
            size2 = max(2, round(2 + t2 * 0.34))                                 # a second palm further out on the sand
            px2 = round(_shore(t2) + max(2, t2 * .04))
            if _palm_top(y2, size2) >= top_row and _shows_cleanly(_palm_box(px2, y2, size2)):
                _palm(d, px2, y2, size2)
        w3 = w + .25                                                             # taller round trees on the far grass
        t3 = _depth(w3)
        y3 = round(HORIZON + t3)
        rt = max(2, round(1 + t3 * 0.1))
        tx = round(_centre(t3) + _half(t3) + 12 + t3 * 0.4)
        if y3 - 3 * rt >= top_row and y3 <= H + 6 and _shows_cleanly((tx - rt, y3 - 2 * rt - 1, tx + rt, y3)):
            _tree(d, tx, y3, rt)
        # White reflector posts punctuate the curve and make forward travel
        # readable even when a nearer palm is hidden behind a quota dial.
        for side in (-1, 1):
            post_x = round(_centre(t2) + side * (_half(t2) + 3 + t2 * .07))
            height = max(1, round(t2 * .12))
            box = (post_x - 1, y2 - height, post_x + 1, y2)
            if top_row <= box[1] and 6 <= t2 and y2 < H and _shows_cleanly(box):
                d.line((post_x, y2 - height, post_x, y2), fill='#fff3d6', width=2 if height > 4 else 1)
                d.point((post_x, y2 - height + 1), fill='#e64b36')


def _rival(d, cx, by, width, body, light, lift):
    """Another car seen from behind, further up the road: tyres, a lit body, a dark rear window and taillights."""
    half = width // 2
    height = max(3, round(width * .48))
    by -= lift
    if width < 7:
        d.rectangle((cx - half, by - 2, cx + half, by), fill='#263142')
        d.line((cx - half + 1, by - 3, cx + half - 1, by - 3), fill=light)
        d.line((cx - half + 1, by - 1, cx + half - 1, by - 1), fill=body)
        return
    d.line((cx - half, by + 1, cx + half, by + 1), fill='#40404e')
    d.rectangle((cx - half, by - 2, cx - half + 1, by), fill='#16161e')
    d.rectangle((cx + half - 1, by - 2, cx + half, by), fill='#16161e')
    d.polygon([(cx - half + 1, by - 1), (cx - half + 1, by - height + 2),
               (cx - half + 3, by - height), (cx + half - 3, by - height),
               (cx + half - 1, by - height + 2), (cx + half - 1, by - 1)], fill=body)
    d.line((cx - half + 3, by - height, cx + half - 3, by - height), fill=light)
    d.line((cx - half + 3, by - height + 1, cx + half - 3, by - height + 1), fill='#18334c')
    d.line((cx - half + 1, by - 3, cx + half - 1, by - 3), fill=light)
    for side in (-1, 1):
        d.point((cx + side * (half - 1), by - 2), fill='#ff644d')
    d.point((cx, by - 1), fill='#fff7db')


def _traffic(d, phase):
    """Three cars ahead in their own lanes. They hold their place on the road (they run at our speed), so only
    their bounce changes, and they sit inside the animated window."""
    phase %= PHASES
    _rival(d, round(_centre(10)), 62, 5, '#f4e9ca', '#ffffff', 0)
    _rival(d, round(_centre(19) - _half(19) * .64), 71, 9, '#1e74bc', '#55d3ed', phase // 2)
    _rival(d, round(_centre(32) + _half(32) * .62), 84, 13, '#e3a524', '#ffe77e', phase % 2)


def _car(d, phase):
    """An original red convertible seen from behind, with a blonde passenger and a dark-haired driver.

    Wide low body, black tail panel with slats, taillights, a plate, two headrests and the occupants' heads.
    The body settles by one pixel per loop and the tyre treads alternate."""
    phase %= PHASES
    cx, by = CENTRE, 115
    # The suspension settles once per loop; no sideways wobble or bouncing
    # heads. Tyres and shadow stay planted while the body moves one pixel.
    y = by - (1 if phase in (1, 2) else 0)
    d.ellipse((cx - 23, by - 4, cx + 23, by + 3), fill='#3c4659')
    d.ellipse((cx - 18, by - 3, cx + 18, by + 2), fill='#252e40')
    for side in (-1, 1):
        x = cx + side * 18
        d.rectangle((x - 3, by - 9, x + 3, by), fill='#111a26')
        d.line((x + side * 2, by - 7, x + side * 2, by - 2), fill='#3b4655')
        d.point((x, by - 1 - phase % 2), fill='#59636b')
    # Deep red flanks and tapered rear deck give a lower, wider silhouette.
    outline = [(cx - 20, y - 11), (cx - 16, y - 18), (cx + 15, y - 18),
               (cx + 21, y - 11), (cx + 22, y - 4), (cx + 18, y),
               (cx - 19, y), (cx - 22, y - 4)]
    d.polygon(outline, fill='#701d36')
    d.polygon([(cx - 20, y - 11), (cx - 15, y - 18), (cx + 14, y - 18),
               (cx + 20, y - 11), (cx + 20, y - 4), (cx - 20, y - 4)], fill='#ef343d')
    d.line((cx - 19, y - 11, cx - 14, y - 17), fill='#ffb389')
    d.line((cx + 15, y - 16, cx + 19, y - 10), fill='#b8223d')
    d.line((cx - 19, y - 5, cx + 19, y - 5), fill='#ff7059')
    # Windshield rim, pale reflected sky, dark cabin and two original riders.
    d.polygon([(cx - 13, y - 18), (cx - 10, y - 23), (cx + 10, y - 23),
               (cx + 14, y - 18)], fill='#771f33')
    d.polygon([(cx - 11, y - 19), (cx - 9, y - 22), (cx + 9, y - 22),
               (cx + 12, y - 19)], fill='#85c9d4')
    d.line((cx - 9, y - 22, cx + 9, y - 22), fill='#e7f7dc')
    d.rectangle((cx - 12, y - 19, cx + 12, y - 15), fill='#3a2438')
    for side, hair, shirt in ((-1, '#f5ca55', '#faf0d2'), (1, '#492f35', '#55a1c7')):
        hx = cx + side * 6
        d.ellipse((hx - 3, y - 20, hx + 3, y - 15), fill='#9c4d43')
        d.line((hx - 2, y - 17, hx + 3, y - 17), fill=shirt, width=2)
        d.rectangle((hx - 2, y - 22, hx + 2, y - 19), fill='#edac7c')
        d.line((hx - 2, y - 22, hx + 1, y - 22), fill=hair, width=2)
        d.line((hx - 2, y - 21, hx - 2, y - 19), fill=hair)
        if side < 0:
            d.point((hx - 3 - phase // 2, y - 20), fill='#ffdf78')
    for side in (-1, 1):
        d.line((cx + side * 15, y - 17, cx + side * 19, y - 17), fill='#f44843')
        d.point((cx + side * 19, y - 18), fill='#ffe3b5')
    # Dark louvres across the rear deck, with highlights on the ribs.
    for row, half in ((14, 10), (12, 11), (10, 12)):
        d.line((cx - half, y - row, cx + half, y - row), fill='#681e35')
        d.point((cx - half, y - row - 1), fill='#ff9169')
    d.rectangle((cx - 19, y - 8, cx + 19, y - 3), fill='#261f32')
    d.line((cx - 18, y - 9, cx + 18, y - 9), fill='#ff8a6d')
    for dx in (-16, -11, 11, 16):
        d.ellipse((cx + dx - 1, y - 7, cx + dx + 1, y - 5), fill='#ff633e')
        d.point((cx + dx, y - 7), fill='#ffd092')
    d.rectangle((cx - 3, y - 6, cx + 3, y - 4), fill='#f7ebc4')
    d.line((cx - 1, y - 5, cx + 1, y - 5), fill='#4b4b5c')
    d.line((cx - 17, y - 2, cx + 17, y - 2), fill='#f24440')
    for dx in (-12, -9, 9, 12):
        d.point((cx + dx, y), fill='#c3ccd0')


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
