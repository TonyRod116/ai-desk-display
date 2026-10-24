"""TIDAL RUSH: original pocket-console surf art, animated locally by Build 7."""
from functools import lru_cache
import math
import random

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

from token_tv import board_anim, board_reset_icons as icons
from token_tv.board_art import _row
from token_tv.personal_faces import remaining_reading, banked_hearts, session_pace
from pathlib import Path

INK = '#102747'
CREAM = '#fff1c7'
YELLOW = '#ffd55e'
STONE = '#e9d9b9'
BOX = (72, 130, 312, 210)
STEP_MS = 150


@lru_cache(maxsize=16)
def font(size):
    return ImageFont.truetype(str(Path(__file__).with_name('web') / 'press-start-2p.ttf'), size)


def text(d, xy, value, color, size=8):
    d.text(xy, value, font=font(size), fill=color, stroke_width=0)


def curve(points, steps=40):
    """Cubic Bezier sampled on the logical console grid."""
    return [(round((1-t)**3*points[0][0]+3*(1-t)**2*t*points[1][0]+3*(1-t)*t*t*points[2][0]+t**3*points[3][0]),
             round((1-t)**3*points[0][1]+3*(1-t)**2*t*points[1][1]+3*(1-t)*t*t*points[2][1]+t**3*points[3][1]))
            for t in (i/steps for i in range(steps+1))]


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
    for y in range(max(48, cy - radius), min(120, cy + radius + 1)):
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
SEA = [(76, '#ffd49b'), (77, '#7fbdc0'), (80, '#52a6b3'), (85, '#318ba6'), (91, '#217198'),
       (98, '#185a84'), (106, '#124a73'), (114, '#0f3e66')]
HORIZON = 76
SUN = (33, 69)


@lru_cache(maxsize=1)
def _coast():
    """Sky, sun, far islands, sea and the glitter path. The animated wave and the shore are painted over it."""
    im = Image.new('RGB', (160, 120), INK)
    d = ImageDraw.Draw(im)
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
                         (52, 49, '#8f86d6'), (150, 50, '#b8b0f0'), (156, 54, '#8f86d6'), (141, 52, '#8f86d6')):
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


def _band_curve(layer_draw, curve_pts, ramp):
    """Paint offset copies of a curve (shifted down) as flat colour bands: a gradient that follows the shape."""
    for first, last, colour in ramp:
        for k in range(first, last):
            layer_draw.line([(x, y + k) for x, y in curve_pts], fill=colour, width=2)


def _inside(mask, point):
    x, y = point
    return 0 <= x < mask.width and 0 <= y < mask.height and bool(mask.getpixel((x, y)))


def _erode(mask, steps):
    for _ in range(steps):
        mask = mask.filter(ImageFilter.MinFilter(3))
    return mask


def _wave_layer():
    """The breaking wave as a 124x54 RGBA layer, painted once and shared by every pose (continuous water)."""
    W, H = 124, 54
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    outer = curve([(0, 38), (23, 21), (61, -9), (99, 2)], 90)
    # The unbroken swell continues beyond the right edge, feeding the curl;
    # it must not drop like a detached wall immediately behind the lip.
    shoulder = curve([(99, 2), (120, 3), (130, 28), (140, 44)], 50)
    bottom = curve([(126, 44), (97, 49), (64, 44), (24, 48)], 60)
    body_pts = outer + shoulder + bottom + [(0, 38)]
    body = Image.new('L', (W, H), 0)
    ImageDraw.Draw(body).polygon(body_pts, fill=255)
    d.polygon(body_pts, fill='#157d94')
    # The face: bands that follow the top contour, bright near the sunlit crest, deep towards the base.
    face = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)
    _band_curve(fd, outer, [(0, 2, '#f4fff0'), (2, 4, '#bff9e4'), (4, 6, '#79ead6'), (6, 9, '#3fd0c8'),
                            (9, 12, '#26b0bb'), (12, 16, '#1d97ae'), (16, 22, '#188199')])
    face.putalpha(ImageChops.multiply(face.getchannel('A'), body))
    im.alpha_composite(face)
    d = ImageDraw.Draw(im)
    top = {x: next((y for y in range(H) if body.getpixel((x, y))), None) for x in range(W)}
    rnd = random.Random(6)
    for x in range(W):                                        # below the bands the water deepens with depth
        if top[x] is None:
            continue
        for y in range(top[x] + 22, H):
            if body.getpixel((x, y)):
                depth = y - top[x]
                colour = '#1a88a0' if depth < 30 else ('#17788f' if depth < 40 else '#136785')
                if x > 99 and y < 46:                           # the shoulder's wall catches more light
                    colour = '#2ab2ba' if y < 30 else ('#22a0b0' if y < 38 else '#1b8aa3')
                    if rnd.random() < .12:
                        colour = '#3ecdc6'
                d.point((x, y), fill=colour)
    for offset in range(0, 16, 4):                           # water bends over the shoulder into the trough
        ripple = curve([(106 + offset, 12), (109 + offset, 22),
                        (112 + offset, 33), (126 + offset, 39)], 24)
        for i, point in enumerate(ripple):
            if _inside(body, point):
                d.point(point, fill='#3ec9c4' if i < 16 else '#239caf')
    rnd = random.Random(12)                                   # long streaks that follow the face, light and dark
    for _ in range(46):
        k = rnd.randint(7, 34)
        j = rnd.randint(4, len(outer) - 30)
        length = rnd.randint(6, 20)
        light = rnd.random() < .62
        if k < 13:
            colour = '#9cf3df' if light else '#2bbac0'
        elif k < 22:
            colour = '#58d8cf' if light else '#1b92aa'
        else:
            colour = '#35b9bf' if light else '#177b98'
        seg = [(x, y + k) for x, y in outer[j:j + length]]
        if len(seg) > 1 and all(_inside(body, q) for q in seg):
            d.line(seg, fill=colour, width=1)
            if light and length > 11:                         # a thin wisp of foam riding the longer ones
                d.point(seg[len(seg) // 2], fill='#e9fff6')
    # The sunset glances off the face: a few warm glints on the sunward side.
    for x, y in ((12, 33), (20, 29), (26, 26), (34, 22), (17, 36)):
        if _inside(body, (x, y)):
            d.point((x, y), fill='#ffd2a8')
            d.point((x + 1, y), fill='#ffb7a0')
    # The tube: a recessed lens, rimmed in lit water and darker towards the throat.
    roof = curve([(43, 43), (53, 22), (69, 7), (88, 10)])
    opening = curve([(88, 10), (107, 13), (94, 32), (77, 35)])
    floor = curve([(77, 35), (66, 38), (56, 42), (43, 43)])
    hole = Image.new('L', (W, H), 0)
    ImageDraw.Draw(hole).polygon(roof + opening + floor, fill=255)
    for colour, erosion in (('#1a87a0', 0), ('#146a88', 1), ('#10516f', 3), ('#0c3b58', 5), ('#082b45', 8), ('#061f37', 11)):
        im.paste(Image.new('RGBA', (W, H), colour), (0, 0), _erode(hole, erosion))
    d = ImageDraw.Draw(im)
    for x, y in ((50, 34), (56, 28), (63, 22), (72, 17), (80, 15)):          # rim light along the tube's roof
        d.point((x, y), fill='#47c4c8'); d.point((x + 1, y), fill='#2fa6b8')
    # Light coming through the thin lip: a luminous crescent just inside it.
    inner = curve([(77, 35), (93, 27), (100, 15), (88, 10)])
    for k, colour in enumerate(('#1f98ae', '#37bcc2', '#7fe6d6', '#37bcc2')):
        d.line([(x - 1 - k * .8, y) for x, y in inner], fill=colour, width=1)
    d.point((95, 21), fill='#fff2c8'); d.point((96, 20), fill='#ffe1a8')
    # The lip: thick, translucent, its edge bright where the sun grazes it.
    lip = curve([(99, 2), (119, 7), (100, 35), (77, 35)])
    d.polygon(lip + inner, fill='#6fe4d2')
    for k, colour in ((0, '#9af2e0'), (2, '#55d2c8'), (4, '#2aaebb')):
        d.line([(x - k * .6, y) for x, y in lip[len(lip) // 3:]], fill=colour, width=1)
    # Foam builds up towards the breaking crest, instead of outlining the
    # entire swell in white all the way down to otherwise calm water.
    d.line(outer[:24], fill='#68d2cd', width=2)
    d.line(outer[23:40], fill='#b5f3df', width=2)
    d.line(outer[39:] + lip, fill='#d9fff0', width=3)
    d.line(outer[46:] + lip, fill='#fffbe9', width=1)
    d.line(inner, fill='#2fb1ba', width=2)
    for x, y in curve([(80, 3), (90, 0), (104, 2), (113, 8)], 7):             # sunlit foam beads on the crest
        d.point((x, y - 2), fill='#fff6d0')
    # Foam scattered along the lip's outer curve, like beads of spray.
    rnd = random.Random(14)
    for i in range(2, len(lip) - 2, 3):
        x, y = lip[i]
        d.point((x + rnd.randint(1, 3), y + rnd.randint(-1, 1)), fill='#f6ffe8')
        if i % 6 == 0:
            d.point((x + rnd.randint(2, 4), y + rnd.randint(-2, 2)), fill='#bdf3e5')
    # The face rolls into the surrounding sea over six rows. Preserve the
    # crest and tube; only dissolve the lower edge, before adding white water.
    px = im.load()
    for x in range(W):
        edge = max((y for y in range(H) if body.getpixel((x, y))), default=-1)
        for y in range(max(0, edge - 5), edge + 1):
            r, g, b, a = px[x, y]
            px[x, y] = (r, g, b, round(a * (edge - y + 1) / 6))
    rnd = random.Random(31)
    bank = [(x, y, r) for x, y, r in ((98, 46, 4), (103, 43, 5), (109, 41, 5), (115, 42, 5), (121, 44, 5),
                                      (124, 47, 4), (106, 47, 5), (113, 47, 5), (119, 49, 4), (100, 49, 4))]
    for x, y, r in bank:                                      # shadow side first, then the lit foam on top
        d.ellipse((x - r, y - r + 2, x + r, y + r + 2), fill='#9fdccf')
    for x, y, r in bank:
        d.ellipse((x - r, y - r, x + r, y + r), fill='#e4fff6')
    for x, y, r in bank:
        d.ellipse((x - r + 1, y - r, x + r - 2, y), fill='#fbfffc')
    for _ in range(26):                                       # bubbles and flecks inside the foam
        x, y = rnd.randint(97, 124), rnd.randint(41, 50)
        d.point((x, y), fill='#8fdccf')
    for x, y in ((96, 51), (101, 52), (108, 52), (116, 52), (123, 52), (93, 50)):
        d.point((x, y), fill='#e4fff6')                       # flecks drifting out over the sea
    # Whitewater at the left impact joins the animated billows to the sea,
    # including the shared strip below the sprite's fixed perimeter.
    for x, y, r in ((3,44,3), (8,43,4), (14,42,4), (20,41,4), (25,42,3)):
        d.ellipse((x-r,y-r+2,x+r,y+r+1), fill='#62bebc')
        d.ellipse((x-r,y-r,x+r,y+r-1), fill='#c5f6e6')
        d.arc((x-r,y-r,x+r,y+r-1), 190, 310, fill='#f4fff0')
    for x, y in ((2,48), (7,49), (13,47), (21,47), (27,46)):
        d.line((x,y,x+2,y), fill='#b7ebde')
    for x in range(16, 90, 15):                              # broken reflections, not an outline at the foot
        yy = min(bottom, key=lambda q: abs(q[0] - x))[1] - 4
        d.line((x, yy, x + 4, yy - 1), fill='#45b2b7')
    return im


@lru_cache(maxsize=1)
def beach():
    """Continuous water geometry is drawn beyond the animated rectangle."""
    im = _coast().copy()
    _shore(im)
    water = _wave_layer()
    im.paste(water, (36, 65), water)
    return im.resize((320, 240), Image.Resampling.NEAREST)


SKIN, SKIN_HI, SKIN_LO = '#ffd4a0', '#ffe8c6', '#d98f62'
SHIRT, SHIRT_HI, SHIRT_LO = '#ff7770', '#ffa79c', '#c94a4d'
SHORTS, SHORTS_HI = '#233a73', '#3f62b5'
HAIR, HAIR_HI = '#3b3352', '#6a5a8c'
BOARD, BOARD_HI, BOARD_LO, DECK, FIN = '#fc6a59', '#ff9c7e', '#b83f43', '#ffe69b', '#6e2a3a'
FOAM, SPRAY = '#f6ffdf', '#a5f3df'


def _limb(d, points, colour, shade, width=2):
    """A limb as a thick line with a darker edge on its lower side, so it reads as round."""
    d.line([(x, y + 1) for x, y in points], fill=shade, width=width)
    d.line(points, fill=colour, width=width)


def _surfer(d, phase, sx, sy):
    """A crouching surfer on a fixed board: the feet stay planted while knees, hips, shoulders, arms and head move."""
    c = (0, 1, 2, 1)[phase]
    # the board: a thick curved profile, a bright deck edge and a dark underside, with a fin under the tail
    deck = [(sx - 9, sy + 10), (sx - 4, sy + 10), (sx + 4, sy + 9), (sx + 9, sy + 8), (sx + 13, sy + 5)]
    d.line([(x, y + 2) for x, y in deck], fill=BOARD_LO, width=1)
    d.line(deck, fill=BOARD, width=2)
    d.line([(x, y - 1) for x, y in deck[1:]], fill=BOARD_HI, width=1)
    d.line([(sx - 5, sy + 9), (sx + 8, sy + 7)], fill=DECK, width=1)
    d.polygon([(sx - 8, sy + 12), (sx - 6, sy + 12), (sx - 8, sy + 15)], fill=FIN)
    # legs: planted feet, knees that swing out as the surfer sinks
    hip = (sx + 1, sy + 1 + c)
    knee_b = (sx - 4 - c // 2 + (phase == 3), sy + 4 + c // 2)
    knee_f = (sx + 7 + c // 2, sy + 3 + c)
    _limb(d, [hip, knee_b, (sx - 4, sy + 8)], SKIN, SKIN_LO)
    _limb(d, [hip, knee_f, (sx + 5, sy + 7)], SKIN, SKIN_LO)
    d.point((knee_b[0], knee_b[1] - 1), fill=SKIN_HI); d.point((knee_f[0], knee_f[1] - 1), fill=SKIN_HI)
    d.rectangle((sx - 5, sy + 7, sx - 3, sy + 8), fill=SKIN_LO)              # feet on the wax
    d.rectangle((sx + 4, sy + 6, sx + 6, sy + 7), fill=SKIN_LO)
    # board shorts with a stripe
    d.rectangle((hip[0] - 2, hip[1] - 1, hip[0] + 3, hip[1] + 1), fill=SHORTS)
    d.line((hip[0] - 2, hip[1] - 1, hip[0] + 3, hip[1] - 1), fill=SHORTS_HI)
    d.line((hip[0] + 1, hip[1], hip[0] + 1, hip[1] + 1), fill=DECK)
    # torso, leaning with the crouch
    shoulder = (sx + 4 + c // 2, sy - 5 + c + c // 2)
    d.line([(hip[0] + 1, hip[1] - 2), (shoulder[0] + 1, shoulder[1] + 1)], fill=SHIRT_LO, width=4)
    d.line([(hip[0], hip[1] - 2), shoulder], fill=SHIRT, width=4)
    d.line([(hip[0] - 1, hip[1] - 3), (shoulder[0] - 1, shoulder[1])], fill=SHIRT_HI, width=1)
    # arms: the back one trails, the front one reaches along the board
    back = [shoulder, (sx - 1 - phase % 2, sy - 6 + c), (sx - 6, sy - 9 + c - (phase == 1))]
    front = [shoulder, (sx + 9, sy - 1 + c), (sx + 13, sy + 1 + c // 2 - (phase == 3))]
    _limb(d, back, SKIN, SKIN_LO)
    _limb(d, front, SKIN, SKIN_LO)
    for hand in (back[-1], front[-1]):
        d.point(hand, fill=SKIN_HI)
    # head: skin, dark hair swept back, an eye and a nose
    hx, hy = shoulder[0] - 1, shoulder[1] - 6
    d.rectangle((hx, hy, hx + 3, hy + 3), fill=SKIN)
    d.rectangle((hx - 1, hy - 1, hx + 3, hy), fill=HAIR)
    d.rectangle((hx - 1, hy, hx, hy + 2), fill=HAIR)
    d.point((hx + 1, hy - 1), fill=HAIR_HI)
    d.point((hx + 3, hy + 1), fill='#2a2438')
    d.point((hx + 4, hy + 2), fill=SKIN_HI)
    d.point((hx + 3, hy + 3), fill=SKIN_LO)
    # cool light from the lip's glow rims the surfer's right side
    d.point((shoulder[0] + 3, shoulder[1] + 1), fill='#7fe6d6')
    d.point((hx + 4, hy), fill='#7fe6d6')
    # the board's shadow on the water and its wake
    d.line((sx - 7, sy + 13, sx + 8, sy + 12), fill='#0c3b58')
    d.line((sx - 4, sy + 14, sx + 5, sy + 13), fill='#17789a')


def _spray(d, phase, sx, sy):
    """Spray thrown from the tail and the rail, and a white wake that streams behind the board."""
    for i in range(7):                                       # roost from the tail
        x = sx - 10 - i * 2 - (phase + i) % 2
        y = sy + 9 - (i + phase) % 3 - i // 2
        d.point((x, y), fill=FOAM if i % 2 else SPRAY)
    for i in range(6):                                       # rail spray at the nose
        x = sx + 11 + i * 2 + (phase * 2 + i) % 3
        y = sy + 7 - i // 2 - (phase + i) % 2
        d.point((x, y), fill=FOAM if i % 3 else SPRAY)
    for k in range(4):                                       # the wake: flecks sliding left, a little differently each pose
        x = sx - 12 - ((k * 6 + phase * 3) % 22)
        d.line((x, sy + 12 + k % 2, x + 2 + k % 2, sy + 12 + k % 2), fill='#d9fff2' if k % 2 else '#7fd9d0')


def _breaking_foam(d, phase):
    """Impact billows rise, then spread left and dissolve into mint-coloured wash."""
    for j in range(8):
        age = (phase+j) % 4
        x = 10 + j % 4 * 6 - age * 2
        y = 35 + j // 4 - (0,2,1,0)[age]
        radius = (2,3,3,2)[age]
        d.ellipse((x-radius,y-1,x+radius+1,y+2), fill='#42aeb4')
        d.ellipse((x-radius,y-radius,x+radius,y+1),
                  fill=('#f4fff0','#e0fff1','#b8eddf','#76d0c8')[age])
        if age < 2:
            d.line((x-1,y-radius,x+1,y-radius), fill='#ffffff')
            d.point((x-2,y-radius-2), fill='#d4fff0')
        else:
            d.line((x-radius-2,y+1,x-radius,y+1), fill='#b8eddf')
    for j in range(5):
        age = (phase+j) % 4
        x, y = 8+j*6-age*2, 36-j%2
        d.line((x,y,x+3+age,y), fill=('#effff2','#c5f6e6','#8adbd0','#53b9bd')[age])


def _wave_motion(d, phase):
    """Foam running along the crest, drops falling from the roof of the tube, sunset glints on the face and
    refracted streaks flowing into the throat. Everything else about the wave is static."""
    # The face drains down and left from the crest, never climbs uphill.
    # Keep falling spray and the surfer's own timeline independent.
    for lane in range(5):
        path = list(dict.fromkeys(curve([(5 + lane * 4, 37),
            (30 + lane * 3, 25), (60 + lane * 2, 4 + lane),
            (91 + lane, 5 + lane)], 100)))
        for start in range(-16, len(path) + 16, 16):
            k = start - phase * 4 + lane * 3 % 16
            stroke = path[max(0, k):max(0, k + 7)]
            if len(stroke) > 1:
                d.line(stroke, fill=('#48c6cb', '#82e9dc', '#2aabbc', '#b1f5df', '#4dcbc9')[lane])
    crest = [(x, y + 1) for x, y in curve([(0, 38), (23, 21), (61, -9), (99, 2)], 90)[24:]]
    falling = curve([(99, 2), (119, 7), (100, 35), (77, 35)], 40)
    # A four-step travelling pattern: the last pose advances into the first,
    # rather than every fleck jumping backwards when the four-frame loop wraps.
    for is_lip, points in ((False, reversed(crest)), (True, falling)):
        for i, (x, y) in enumerate(dict.fromkeys(points)):
            if (i - phase * 2) % 8 not in (0, 1, 2):
                continue
            d.point((x, y), fill=FOAM if is_lip else SPRAY)
            if is_lip:
                d.point((x, y - 1), fill='#ddfff1')
    # The lip breaks into a fan of froth, rather than simply ending in a line.
    for j in range(9):
        age = (phase + j) % 4
        x, y = 91 + j % 3 * 4 - age * 2, 27 + j // 3 * 3 + age
        d.line((x, y, x + 2 + age % 2, y), fill=('#f1fff1', '#baffea', '#79dfd5', '#39b1bf')[age])
    roof = curve([(43, 43), (53, 22), (69, 7), (88, 10)], 40)
    for j, (x, y) in enumerate(roof[18:38:4]):                  # drops falling from the tube's roof
        fall = (phase + j) % 4
        d.line((x, y + 2, x, y + 3 + fall), fill='#289aaa')
        d.point((x, y + 4 + fall), fill=('#8cded5', '#b2eee3', '#7acbc9', '#3b9fae')[fall])
    for j, (x, y) in enumerate(((16, 31), (24, 27), (31, 24), (39, 19), (47, 15), (55, 11), (63, 8))):
        if (j + phase) % 3 == 0:                                  # glints on the face, three of seven at a time
            d.point((x, y), fill='#fff1c4'); d.point((x + 1, y), fill='#ffd8a8')
    for j in range(5):
        x = 49 + j * 7 + (phase % 2)
        y = 34 - j * 3
        d.line([(x, y), (x + 3, y - 2)], fill='#2790ab')
    for j in range(11):
        x = 79 + (j * 7 + phase * 2) % 22
        y = 25 + (j * 3 + phase) % 12
        if x < 102 - (y - 25):
            d.point((x, y), fill='#b2fff0')
    _breaking_foam(d, phase)


def wave_pose(phase):
    """The animated rectangle: the shared water with its foam, drops, glints and the surfer on top.

    The board holds one line (it may bob a single logical pixel); the feet are planted on it."""
    background = beach().crop(BOX).resize((120, 40), Image.Resampling.NEAREST).convert('RGBA')
    im = background.copy()
    d = ImageDraw.Draw(im)
    _wave_motion(d, phase)
    sx, sy = 71, 24 + (phase == 2)
    _spray(d, phase, sx, sy)
    _surfer(d, phase, sx, sy)
    # Exact shared perimeter: moving pixels never reach the crop boundary.
    # This protects all four sides, including the former seam at board height.
    im.paste(background.crop((0, 0, 120, 2)), (0, 0))
    im.paste(background.crop((0, 38, 120, 40)), (0, 38))
    im.paste(background.crop((0, 0, 2, 40)), (0, 0))
    im.paste(background.crop((118, 0, 120, 40)), (118, 0))
    return im


GULL_A = (('X.........X', '.X.......X.', '..XX...XX..', '....XXX....', '...........'),
          ('...........', '.XXX...XXX.', 'X...XXX...X', '...........', '...........'),
          ('...........', '...XXXXX...', '.XXX...XXX.', 'XX.......XX', '...........'))
GULL_B = (('X.......X', '.X.....X.', '..XXXXX..', '.........'),
          ('.........', '.XX...XX.', 'X..XXX..X', '.........'),
          ('.........', '..XXXXX..', '.XX...XX.', 'X.......X'))


def _gull_frames(rows_by_frame, colour='#2e1745', rim='#ff9f88'):
    frames = []
    for rows in rows_by_frame:
        im = Image.new('RGBA', (len(rows[0]), len(rows)), (0, 0, 0, 0))
        for y, row in enumerate(rows):
            for x, cell in enumerate(row):
                if cell == 'X':
                    im.putpixel((x, y), ImageColor.getrgb(rim if y == 0 and x % 2 == 0 else colour) + (255,))
        frames.append(im)
    return frames


def _gull_sprite(rows_by_frame, x, y, step_dx, offset):
    """A gull crossing the sky right to left: 32 steps of 150 ms (4.8 s), wings up, level, down, level."""
    script = []
    for i in range(32):
        k = (i + offset) % 32
        script.append(((0, 1, 2, 1)[i % 4], -round(step_dx * k), 1 if i % 4 == 2 else 0))
    return {'x': x, 'y': y, 'frames': _gull_frames(rows_by_frame), 'script': script, 'step_ms': STEP_MS}


@lru_cache(maxsize=1)
def animation():
    poses=[wave_pose(i) for i in range(4)]
    # Build 7 permits at most 96 logical pixels per sprite. Adjacent, disjoint
    # halves share the same script and clock; restoration cannot erase the other.
    sprites=tuple({'x':BOX[0]+half*120,'y':BOX[1],
                   'frames':[pose.crop((half*60,0,(half+1)*60,40)) for pose in poses],
                   'script':[(i,0,0) for i in range(4)],'step_ms':STEP_MS}
                  for half in range(2))
    sprites += (_gull_sprite(GULL_A, 90, 108, 2.8, 0), _gull_sprite(GULL_B, 84, 120, 2.6, 16))
    return sprites,board_anim.encode(sprites)


def instrument(d,row,provider,x):
    color=YELLOW if provider=='codex' else STONE
    value,_,old,reset=remaining_reading(row)
    count,old_bank=banked_hearts(row)
    text(d,(x,5),provider.upper(),color,10)
    have=count if count is not None else 0
    for i in range(3):                  # one palm tree per saved reset (was a heart)
        hx=x+83+i*13
        if have>i:
            for xx,yy,tone,_ in icons.cells('palm'):
                d.point((hx+xx,5+yy),fill=_mix(color,'#000000',-icons.DETAIL['palm']) if tone=='o' else color)
        else:
            for xx,yy in icons.hollow('palm'):
                d.point((hx+xx,5+yy),fill='#4a6590')
    if icons.marked(count,old_bank):    # unknown or old: one faint dot at the end of the row, no ? and no OLD
        d.rectangle((x+121,9,x+122,10),fill='#4a6590')
    mark=icons.mark(count,old_bank)
    if mark:text(d,(x+126,6),mark,CREAM,6)
    text(d,(x,24),'--' if value is None else str(round(value)),CREAM,28)
    if value is not None:text(d,(x+88,34),'%',color,12)
    if old:text(d,(x+115,35),'OLD',color,6)
    d.rectangle((x-3,53,x+141,63),fill='#0a182f',outline='#2d557f')
    lit_hi,lit_lo=_mix(color,'#ffffff',.38),_mix(color,'#000000',.32)
    for j in range(20):
        on=value is not None and j<math.ceil(value/5)
        d.rectangle((x+j*7,56,x+j*7+4,60),fill=color if on else '#2f435f')
        d.line((x+j*7,56,x+j*7+4,56),fill=lit_hi if on else '#41587a')
        d.line((x+j*7,60,x+j*7+4,60),fill=lit_lo if on else '#1d2d46')
    pace=session_pace(row) if provider=='claude' else None
    if pace:
        for line,units in enumerate((math.ceil(pace[0]/5)/4,round(pace[1]*4)/4)):
            for j in range(5):
                left=x+j*28;top=64+line*4
                d.rectangle((left,top,left+23,top+2),fill='#2f435f')
                d.line((left,top+2,left+23,top+2),fill='#1d2d46')
                amount=max(0,min(1,units-j))
                if amount:
                    d.rectangle((left,top,left+max(0,round(23*amount)),top+2),fill=color)
                    d.line((left,top,left+max(0,round(23*amount)),top),fill=_mix(color,'#ffffff',.38))
    text(d,(x,79),'RST', '#91b8c6',7)
    # Font fits longest supported weekly reset string wholly inside its column.
    text(d,(x+31,77),reset.upper(),CREAM,10)


def _text_mask(value, size):
    """A hard-edged (no anti-aliasing) mask of `value` in the pixel font, so letters stay crisp on the panel."""
    f = font(size)
    box = f.getbbox(value)
    mask = Image.new('L', (box[2] + 8, box[3] + 8), 0)
    ImageDraw.Draw(mask).text((4, 4), value, font=f, fill=255)
    return mask.point(lambda v: 255 if v > 127 else 0)


LOGO_BOX = (144, 99, 240, 115)       # where the title sits (screen px): nothing animated may cross it


def _logo(image, left, top):
    """TIDAL RUSH as a quiet title: small spaced letters, cream to peach, a muted violet outline and a soft shadow.

    The first version used big gradient letters with sparkles and shouted over the scene (the user, 2026-10-19)."""
    letters = Image.new('L', (96, 16), 0)
    ld = ImageDraw.Draw(letters)
    for i, ch in enumerate('TIDAL RUSH'):
        ld.text((3 + i * 9, 3), ch, font=font(8), fill=255)           # one pixel of extra air between letters
    letters = letters.point(lambda v: 255 if v > 127 else 0)
    outline = letters.filter(ImageFilter.MaxFilter(3))
    layers = Image.new('RGBA', letters.size, (0, 0, 0, 0))
    for mask, colour in ((ImageChops.offset(outline, 1, 1), '#3a2468'), (outline, '#5a3d85')):
        layers.paste(Image.new('RGBA', letters.size, colour), (0, 0), mask)
    fill = Image.new('RGBA', letters.size, '#fff1d8')
    fd = ImageDraw.Draw(fill)
    fd.rectangle((0, 7, 96, 16), fill='#ffd6b0')
    layers.paste(fill, (0, 0), letters)
    image.paste(layers, (left, top), layers)


def render_surf(snapshot,animated=False):
    image=beach().copy()
    d=ImageDraw.Draw(image)
    d.rectangle((0,0,319,95),fill='#08162b')
    for x0 in (3,164):
        d.rounded_rectangle((x0,2,x0+152,90),radius=4,fill='#102a4c',outline='#2c5a86')
        d.line((x0+4,3,x0+148,3),fill='#3d78a8')                         # light catching the top edge
        d.line((x0+4,89,x0+148,89),fill='#0a1c36')
        for cx,cy in ((x0+3,5),(x0+149,5),(x0+3,87),(x0+149,87)):          # four small rivets
            d.point((cx,cy),fill='#5f93bd')
    d.line((0,92,319,92),fill='#a9672f')
    d.line((0,93,319,93),fill='#ffd27a')
    d.line((0,94,319,94),fill='#ffc77d')
    d.line((0,95,319,95),fill='#7a4a25')
    for x in range(4,320,10):                                             # rope twists along the divider
        d.line((x,93,x+4,94),fill='#fff0b8')
    instrument(d,_row(snapshot,'codex'),'codex',9)
    instrument(d,_row(snapshot,'claude'),'claude',170)
    # Title sits in the sky, never on the quotas or the animated water.
    _logo(image, 144, 99)
    sprites,payload=animation()
    if not animated:
        for sprite in sprites:                       # the first pose, exactly where step 0 of its script puts it
            frame, dx, dy = sprite['script'][0]
            first = sprite['frames'][frame]
            first = first.resize((first.width * 2, first.height * 2), Image.Resampling.NEAREST)
            image.paste(first, (sprite['x'] + dx, sprite['y'] + dy), first)
    return (image,payload) if animated else image
