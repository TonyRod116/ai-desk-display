"""TIDAL RUSH's wave: the water painted once, with a lip that can fall (Tony, 2026-11-03: "a livelier wave").

The wave is a 148 x 54 layer on the page's 160 x 120 logical canvas (every logical pixel is shown 2 x 2). Everything about it is
painted by `wave_layer(pose)`: the face, its bands and streaks, the dark barrel, the sunlit crest and, depending on the pose, how far
the lip has thrown and fallen. The authored geometry is reflected as a whole, including the moving current, so the swell, breaking lip
and splash all face the same way. In the finished scene the lip changes only on the left, clear of the surfer.
"""
from functools import lru_cache
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 148, 54                  # the full shoulder extends behind the left-hand shore
ORIGIN = (12, 65)
POSES = 8
LIP_FROM = 90                   # authored column, before the whole wave is reflected for display
LIP_TOP = 8                     # layer row: nor above it (the crest above belongs to the other moving tile)


def curve(points, steps=40):
    """Cubic Bezier sampled on the logical console grid."""
    return [(round((1-t)**3*points[0][0]+3*(1-t)**2*t*points[1][0]+3*(1-t)*t*t*points[2][0]+t**3*points[3][0]),
             round((1-t)**3*points[0][1]+3*(1-t)**2*t*points[1][1]+3*(1-t)*t*t*points[2][1]+t**3*points[3][1]))
            for t in (i/steps for i in range(steps+1))]


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


@lru_cache(maxsize=1)
def _base():
    """The water before the lip: face, bands, streaks, glints, the barrel's six depths and the light along its roof.

    Returns the RGBA layer, the mask of the body of water and the outer crest curve (the lip hangs from it)."""
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
    # The unbroken water carries on behind the curl, gradually losing its
    # sunlit edge as it falls towards the distant sea.
    _band_curve(fd, shoulder, [(0, 1, '#8ae2d8'), (1, 3, '#55cfc9'), (3, 5, '#31b8bc'),
                               (5, 8, '#219eae'), (8, 13, '#168599'), (13, 18, '#157d94')])
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
    opening = curve([(88, 10), (107, 13), (100, 27), (92, 35)])
    floor = curve([(92, 35), (75, 38), (56, 42), (43, 43)])
    hole = Image.new('L', (W, H), 0)
    ImageDraw.Draw(hole).polygon(roof + opening + floor, fill=255)
    for colour, erosion in (('#1a87a0', 0), ('#146a88', 1), ('#10516f', 3), ('#0c3b58', 5), ('#082b45', 8), ('#061f37', 11)):
        im.paste(Image.new('RGBA', (W, H), colour), (0, 0), _erode(hole, erosion))
    d = ImageDraw.Draw(im)
    for x, y in ((50, 34), (56, 28), (63, 22), (72, 17), (80, 15)):          # rim light along the tube's roof
        d.point((x, y), fill='#47c4c8'); d.point((x + 1, y), fill='#2fa6b8')
    return im, body, outer


# ---- the lip -----------------------------------------------------------------------------------------------------------
def _smooth(v):
    v = max(0.0, min(1.0, v))
    return v * v * (3 - 2 * v)


# One fall of the lip, pose by pose. `LIFT` runs from -1 (the lip cocked back and up, the barrel wide) through 0 (the calm barrel the
# page carries) to +1 (the lip fallen and the barrel closed).
LIFT = (0.0, -0.5, -1.0, 0.4, 1.0, 0.9, 0.6, 0.1)
# how far a lip curve travels at most (dx, dy) when it falls and when it is cocked; nothing left of LIP_FROM ever moves
INNER_FALL, INNER_COCK = (-3.0, 3.0), (2.5, -3.0)
OUTER_FALL, OUTER_COCK = (-1.5, 3.0), (2.0, -3.0)


def _shift(points, lift, fall, cock):
    """Move a lip curve for `lift`: it never moves left of LIP_FROM, and its root on the crest stays where it is."""
    dx, dy = fall if lift > 0 else cock
    out = []
    for x, y in points:
        w = 0.0 if x < LIP_FROM + 3 or y < LIP_TOP + 2 else _smooth((x - LIP_FROM) / 11) * _smooth((y - LIP_TOP) / 12)
        out.append((x + abs(lift) * dx * w, y + abs(lift) * dy * w))
    return out


def _lip(im, outer, pose):
    """The lip, its light and its foam, for one pose of its fall."""
    lift = LIFT[pose]
    d = ImageDraw.Draw(im)
    inner = _shift(curve([(92, 35), (97, 26), (102, 15), (88, 10)]), lift, INNER_FALL, INNER_COCK)
    lip = _shift(curve([(99, 2), (119, 7), (98, 27), (92, 35)]), lift, OUTER_FALL, OUTER_COCK)
    # Light coming through the thin lip: a luminous crescent just inside it.
    for k, colour in enumerate(('#1f98ae', '#37bcc2', '#7fe6d6', '#37bcc2')):
        d.line([(x - 1 - k * .8, y) for x, y in inner], fill=colour, width=1)
    d.point((95, 21), fill='#fff2c8'); d.point((96, 20), fill='#ffe1a8')
    # The lip: thick, translucent, its edge bright where the sun grazes it.
    d.polygon(lip + inner, fill='#6fe4d2')
    if lift > 0:                                      # a fallen lip is a thicker band: it shades from the barrel's dark into mint
        band = Image.new('L', im.size, 0)
        ImageDraw.Draw(band).polygon(lip + inner, fill=255)
        shade = Image.new('RGBA', im.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for k, colour in enumerate(('#2fb1ba', '#37bcc2', '#46c8c6', '#52d3c9', '#5bd8cb', '#64dcce')):
            sd.line([(x + k * 1.2, y) for x, y in inner if x >= LIP_FROM + 3], fill=colour, width=2)
        im.paste(shade, (0, 0), ImageChops.multiply(shade.getchannel('A'), band.point(lambda v: v if lift > 0.15 else 0)))
        d = ImageDraw.Draw(im)
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


def _finish(im, body):
    """The face rolls into the sea over six rows, with a wash on its outer foot."""
    d = ImageDraw.Draw(im)
    px = im.load()
    for x in range(W):
        edge = max((y for y in range(H) if body.getpixel((x, y))), default=-1)
        for y in range(max(0, edge - 5), edge + 1):
            r, g, b, a = px[x, y]
            px[x, y] = (r, g, b, round(a * (edge - y + 1) / 6))
    # The original pale, rounded wash supports the moving breaking foam.
    for x, y, r in ((3, 44, 3), (8, 43, 4), (14, 42, 4), (20, 41, 4), (25, 42, 3)):
        d.ellipse((x-r, y-r+2, x+r, y+r+1), fill='#62bebc')
        d.ellipse((x-r, y-r, x+r, y+r-1), fill='#c5f6e6')
        d.arc((x-r, y-r, x+r, y+r-1), 190, 310, fill='#f4fff0')
    for x, y in ((2, 48), (7, 49), (13, 47), (21, 47), (27, 46)):
        d.line((x, y, x+2, y), fill='#b7ebde')
    return im


@lru_cache(maxsize=POSES)
def wave_layer(pose=0):
    """The whole wave in one pose of the lip's fall, as an RGBA layer to paste at ORIGIN."""
    base, body, outer = _base()
    im = base.copy()
    _lip(im, outer, pose)
    im = _finish(im, body)
    # Broken reflections, not an outline at the foot (they need the bottom curve, so they live here, last of all).
    d = ImageDraw.Draw(im)
    bottom = curve([(126, 44), (97, 49), (64, 44), (24, 48)], 60)
    for x in range(16, 90, 15):
        yy = min(bottom, key=lambda q: abs(q[0] - x))[1] - 4
        d.line((x, yy, x + 4, yy - 1), fill='#45b2b7')
    return im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)


# ---- the current ------------------------------------------------------------------------------------------------------------
FLOW_PHASES = 4                 # the outer current repeats every four phases, each moving every stroke four path pixels on


def _breaking_foam(phase):
    """The original small billows rise and settle without crossing the tile edge."""
    foam = Image.new('RGBA', (30, 49), (0, 0, 0, 0))
    d = ImageDraw.Draw(foam)
    for j in range(8):
        age = (phase + j) % 4
        x = (8, 13, 18, 22)[j % 4] + (0, 1, 0, -1)[age]
        y = 35 + j // 4 - (0, 2, 1, 0)[age]
        radius = (2, 3, 3, 2)[age]
        d.ellipse((x-radius, y-1, x+radius+1, y+2), fill='#42aeb4')
        d.ellipse((x-radius, y-radius, x+radius, y+1),
                  fill=('#f4fff0', '#e0fff1', '#b8eddf', '#76d0c8')[age])
        if age < 2:
            d.line((x-1, y-radius, x+1, y-radius), fill='#ffffff')
            d.point((x-2, y-radius-2), fill='#d4fff0')
        else:
            d.line((x-radius-2, y+1, x-radius, y+1), fill='#b8eddf')
    for j in range(4):
        age = (phase + j) % 4
        x, y = 6 + j * 5 + (0, 1, 0, -1)[age], 36 - j % 2
        d.line((x, y, x+3+age, y), fill=('#effff2', '#c5f6e6', '#8adbd0', '#53b9bd')[age])
    return foam


def flow_overlay(phase):
    """The moving current, crest foam, glints and impact billows, reflected with the wave they belong to."""
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
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
    for i, (x, y) in enumerate(dict.fromkeys(reversed(crest))):
        if (i - phase * 2) % 8 in (0, 1, 2):
            d.point((x, y), fill='#a5f3df')
    for j, (x, y) in enumerate(((16, 31), (24, 27), (31, 24), (39, 19), (47, 15), (55, 11), (63, 8))):
        if (j + phase) % 3 == 0:                                  # glints on the face, three of seven at a time
            d.point((x, y), fill='#fff1c4'); d.point((x + 1, y), fill='#ffd8a8')
    im.alpha_composite(_breaking_foam(phase))
    return im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
