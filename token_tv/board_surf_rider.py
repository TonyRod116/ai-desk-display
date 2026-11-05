"""The surfer of TIDAL RUSH: a generic, original human on the board's own 2 x 2 sprite grid (Tony, 2026-11-03: "quiero que surfee
un humano").

The figure restores the lean, hand-pixelled surfer that Tony preferred before the 3 November redesign: narrow limbs, small head,
coral top and navy board shorts. Its original drawing faced right; its joints and face now face the left-pointing nose of the board.
The art is original to this repository and is neither traced nor copied from a game or character.

He is not fixed on a line. He is ONE sprite with eight pictures, moved across the face of the wave by the engine's per-step offsets, so
he climbs and drops smoothly while his pictures change only where the body does: cruising, rising, crouching, skimming the water
with a hand, tucking into the tube, going under the lip, bursting out in foam and standing up again. The water around him is the page's
own (the lens, the face), which is why every picture is mostly transparent and why the wave's moving tiles stay clear of his box.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

from token_tv.board_arcade_fighters import Grid, _outline, rgb

# ---- the picture: 50 x 36 logical pixels, the board's centre at ANCHOR ---------------------------------------------------
FRAME = (50, 36)
ANCHOR = (25, 28)

# dark, shade, base, light. The base tones are the ones the tests (and Tony's eye) know the parts by.
SKIN = [rgb(c) for c in ('#b8644a', '#e0956a', '#ffd4a0', '#ffeacc')]
SHIRT = [rgb(c) for c in ('#9a3550', '#d24f5a', '#ff7770', '#ffa79c')]
SHORTS = [rgb(c) for c in ('#121b44', '#1b2b5e', '#233a73', '#3f62b5')]
HAIR = [rgb(c) for c in ('#1c1730', '#2c2548', '#3b3352', '#6a5a8c')]
BOARD = [rgb(c) for c in ('#8e2f44', '#d9505a', '#fc6a59', '#ff9c7e')]
FOAM = [rgb(c) for c in ('#5cb8b4', '#9fe0d3', '#dffaf0', '#ffffff')]
INK, INK_BOARD, INK_FOAM = rgb('#1d1330'), rgb('#4a1e33'), rgb('#3aa6ad')
DECK, FIN = rgb('#ffe69b'), rgb('#6e2a3a')
EYE, SPRAY, SPRAY_LIT, SHADOW = rgb('#2a2438'), rgb('#a5f3df'), rgb('#f6ffdf'), rgb('#0c3b58')


LENGTH = 32


def _deck(x, pitch):
    """Height of the deck at x (0 at the middle): a rocker that lifts the nose and, less, the tail, plus the pitch of the board."""
    rocker = 0.0
    if x < -8:
        rocker = -(-x - 8) * 0.30
    elif x > 10:
        rocker = -(x - 10) * 0.18
    return rocker + pitch * x


def _board(g, pitch):
    half = LENGTH / 2
    cols = {}
    for x in range(-int(half), int(half) + 1):
        t = abs(x) / half
        cols[x] = (round(_deck(x, pitch)), 3 if t < 0.8 else 2 if t < 0.93 else 1)
    pixels = {}
    for x, (top, thick) in cols.items():
        for k in range(thick):
            tone = 3 if k == 0 else (2 if k < thick - 1 or thick == 1 else 1)
            pixels[(x, top + k)] = BOARD[tone] if thick > 1 else BOARD[2]
        if thick >= 3:
            pixels[(x, top + thick - 1)] = BOARD[0]
    for x in range(-int(half * .55), int(half * .55)):                  # the cream deck stripe
        pixels[(x, cols[x][0])] = DECK
    g.paint(_outline(set(pixels), INK_BOARD))
    g.paint(pixels)
    fin = int(half * .5)                                                    # a fin under the tail, behind the left-pointing nose
    top = cols[fin][0] + cols[fin][1]
    for k in range(3):
        g.put(fin + k // 2, top + k, FIN)
    g.put(fin - 1, top, FIN)


def _surfer(g, pose):
    """Animate the original slender figure; mirror it so his face points left."""
    sink = pose.get('sink', 0)
    pitch = pose.get('pitch', 0.0)
    _board(g, pitch)

    # Draw the old figure at its original proportions on a roomy transparent
    # canvas, then reflect its pixels. This keeps its hand-drawn flat shading
    # and lets the caller's Grid catch anything outside the animation box.
    canvas = Image.new('RGBA', (100, 80))
    d = ImageDraw.Draw(canvas)
    def point(p):
        return (round(p[0]) + 50, round(p[1]) + 40)
    def line(points, colour, width=1):
        d.line([point(p) for p in points], fill=colour + (255,), width=width)
    def rect(box, colour):
        a, b = point(box[:2]), point(box[2:])
        d.rectangle((a, b), fill=colour + (255,))
    def dot(p, colour):
        d.point(point(p), fill=colour + (255,))
    def limb(points):
        line([(x, y + 1) for x, y in points], SKIN[1], 2)
        line(points, SKIN[2], 2)

    bend = max(0, sink)
    hip = (1 + pose.get('hip_x', 0), -9 + sink)
    knee_b = (-4 - bend // 2, -6 + bend // 2)
    knee_f = (7 + bend // 2, -7 + sink)
    back_foot = (-4, round(_deck(4, pitch)) - 1)
    front_foot = (5, round(_deck(-5, pitch)) - 1)
    limb([hip, knee_b, back_foot])
    limb([hip, knee_f, front_foot])
    dot((knee_b[0], knee_b[1] - 1), SKIN[3])
    dot((knee_f[0], knee_f[1] - 1), SKIN[3])
    for x, y in (back_foot, front_foot):
        rect((x - 1, y - 1, x + 1, y), SKIN[1])

    rect((hip[0] - 2, hip[1] - 1, hip[0] + 3, hip[1] + 1), SHORTS[2])
    line([(hip[0] - 2, hip[1] - 1), (hip[0] + 3, hip[1] - 1)], SHORTS[3])
    line([(hip[0] + 1, hip[1]), (hip[0] + 1, hip[1] + 1)], DECK)
    shoulder = (4 + sink // 2 + pose.get('lean', 0), -15 + sink + sink // 2)
    line([(hip[0] + 1, hip[1] - 2), (shoulder[0] + 1, shoulder[1] + 1)], SHIRT[1], 4)
    line([(hip[0], hip[1] - 2), shoulder], SHIRT[2], 4)
    line([(hip[0] - 1, hip[1] - 3), (shoulder[0] - 1, shoulder[1])], SHIRT[3])

    back_hand = pose.get('back_hand', (-6, -19 + sink))
    front_hand = pose.get('front_hand', (13, -9 + sink // 2))
    limb([shoulder, (-1, -16 + sink), back_hand])
    limb([shoulder, (9, -11 + sink), front_hand])
    dot(back_hand, SKIN[3])
    dot(front_hand, SKIN[3])
    hx, hy = shoulder[0] - 1, shoulder[1] - 6
    rect((hx, hy, hx + 3, hy + 3), SKIN[2])
    rect((hx - 1, hy - 1, hx + 3, hy), HAIR[2])
    rect((hx - 1, hy, hx, hy + 2), HAIR[2])
    dot((hx + 1, hy - 1), HAIR[3])
    dot((hx + 3, hy + 1), EYE)
    dot((hx + 4, hy + 2), SKIN[3])
    dot((hx + 3, hy + 3), SKIN[1])
    dot((shoulder[0] + 3, shoulder[1] + 1), rgb('#7fe6d6'))

    for y in range(canvas.height):
        for x in range(canvas.width):
            colour = canvas.getpixel((x, y))
            if colour[3]:
                g.put(50 - x, y - 40, colour[:3])
    return g


POSES = {
    'cruise': dict(),
    'rise': dict(pitch=0.10, sink=-1, lean=1, back_hand=(-4, -20), front_hand=(13, -12)),
    'crouch': dict(sink=2, hip_x=-1, back_hand=(-8, -13), front_hand=(12, -7)),
    'skim': dict(sink=3, hip_x=-2, back_hand=(-8, -17), front_hand=(12, 1)),
    'tuck': dict(sink=4, hip_x=-2, back_hand=(-10, -7), front_hand=(9, -5)),
    'exit': dict(pitch=0.05, sink=-1, back_hand=(-8, -23), front_hand=(12, -22)),
}


# ---- the water around him ------------------------------------------------------------------------------------------------
FOAM_DEEP, FOAM_SHADE, FOAM_MID, FOAM_LIT = (rgb(c) for c in ('#62bebc', '#9fdccf', '#c5f6e6', '#e4fff6'))


def _wash(g, crest, highlights, volume=0, spray=()):
    """A broken, textured sheet of foam; volume rises around the surfer as the lip lands."""
    canvas = Image.new('RGBA', FRAME)
    d = ImageDraw.Draw(canvas)

    def coords(points):
        return [(x + ANCHOR[0], y + ANCHOR[1]) for x, y in points]

    if volume:
        mask = Image.new('1', FRAME)
        left, right = crest[0][0], crest[-1][0]
        lower = [(right, 4), (right - 4, 3), (right - 8, 5), (right - 13, 4),
                 (left + 11, 5), (left + 6, 3), (left, 4)]
        ImageDraw.Draw(mask).polygon(coords(crest + lower), fill=1)
        palette = (FOAM_DEEP, FOAM_SHADE, FOAM_MID, FOAM_LIT)
        for y in range(FRAME[1]):
            for x in range(FRAME[0]):
                if not mask.getpixel((x, y)):
                    continue
                # Broad, irregular ribbons of shadow and light give the foam
                # texture without isolated dots or round cartoon-like puffs.
                ribbon = (math.sin(x * .30 + y * .71 + volume * .8) +
                          .55 * math.sin(x * .61 - y * .38) + .3 * math.sin(x * .23 + y * 1.14))
                colour = palette[0 if ribbon < -.9 else 1 if ribbon < -.2 else 2 if ribbon < .65 else 3]
                d.point((x, y), fill=colour + (255,))
    d.line(coords(crest), fill=FOAM_SHADE + (255,))
    for stroke in highlights:
        d.line(coords(stroke), fill=FOAM_LIT + (255,))
        x, y = stroke[-1]
        d.line(coords([(x, y + 2), (x + 2, y + 2)]), fill=FOAM_DEEP + (255,))
    for stroke in spray:
        d.line(coords(stroke), fill=FOAM_SHADE + (255,), width=2 if volume > 1 else 1)
        d.line(coords(stroke[1:]), fill=FOAM_LIT + (255,))
    for y in range(canvas.height):
        for x in range(canvas.width):
            colour = canvas.getpixel((x, y))
            if colour[3]:
                g.put(x - ANCHOR[0], y - ANCHOR[1], colour[:3])


def _wake(g, length, shift, tail=15):
    """The board's trail on the water behind the tail: a bright line, a mint one beneath it and a few flecks that differ
    from picture to picture, so the wake streams on while the board keeps its own line."""
    for k in range(length):
        x = tail + k
        if (k + shift) % 5 == 4:
            continue                                                       # gaps: the trail is made of foam, not a rule
        g.put(x, 3 + (k > 5) * 0, FOAM[3] if k < length - 3 else SPRAY_LIT)
        g.put(x + 1, 4, SPRAY if (k + shift) % 3 else SPRAY_LIT)
    for k, (dx, dy) in enumerate(((3, 5), (5, 2), (7, 5))):
        if (k + shift) % 2 == 0 and dx <= length:
            g.put(tail + dx, dy, SPRAY_LIT)


def _shadow(g, reach=11):
    for x in range(-reach, reach + 1):                                       # the board's shadow on the face of the wave
        g.put(x, 4, SHADOW)


def _tail_spray(g, shift, size=6):
    """Drops arcing up and back from the tail."""
    for i in range(size):
        x = 16 + i + (i + shift) % 2
        y = 1 - round(i * 1.0) + round(i * i * 0.09) - (shift + i) % 2
        g.put(x, y, SPRAY_LIT if i % 2 else SPRAY)


def _nose_spray(g, shift, size=4):
    for i in range(size):
        g.put(-17 - round(i * 1.6) - (shift + i) % 2, -2 - i + (shift + i) % 2, SPRAY_LIT if i % 2 else SPRAY)


def _curtain(g):
    """The lip's tip arriving: a sheet of mint water hanging from the top of the picture, bright where it is lit."""
    for k, colour in ((0, FOAM[3]), (1, FOAM[2]), (2, rgb('#6fe4d2')), (3, rgb('#6fe4d2')), (4, rgb('#2aaebb'))):
        pts = [(15 - k + round(0.55 * (i / 6) ** 2 * 6), -26 + i * 3) for i in range(0, 9)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            for t in range(4):
                g.put(round(x0 + (x1 - x0) * t / 4), round(y0 + (y1 - y0) * t / 4), colour)


def _drops(g, points, colours=(SPRAY_LIT, SPRAY)):
    for k, (x, y) in enumerate(points):
        g.put(x, y, colours[k % 2])


def _hand_spray(g, lit=True):
    """The hand ploughing the face: a short foam line under it and drops thrown up and back from it."""
    for k in range(6):
        g.put(-12 + k, 3, FOAM[3] if k < 3 else SPRAY)
    _drops(g, ((-14, 0), (-16, -2), (-15, -4), (-18, -5), (-17, -7), (-13, -3), (-19, -2)))


def _picture(index):
    """Picture `index` (0-7) of the surfer: cruise, rise, crouch, skim, tuck, under the lip, burst, stand."""
    g = Grid(FRAME[0], FRAME[1], ox=ANCHOR[0], oy=ANCHOR[1])
    kind = ('cruise', 'rise', 'crouch', 'skim', 'tuck', 'tuck', None, 'exit')[index]
    _shadow(g)
    _wake(g, (8, 7, 8, 8, 7, 6, 7, 8)[index], (0, 2, 1, 3, 0, 1, 2, 4)[index])
    if index in (0, 1, 2, 3, 7):
        _tail_spray(g, (0, 1, 0, 1, 0, 0, 0, 1)[index], (5, 6, 6, 7, 0, 0, 0, 5)[index])
        _nose_spray(g, (0, 1, 0, 1, 0, 0, 0, 1)[index], (3, 3, 4, 4, 0, 0, 0, 3)[index])
    if index == 3:
        _hand_spray(g)
    if kind:
        _surfer(g, POSES[kind])
    if index == 4:                                                         # the first drops fall from the lip's tip
        _drops(g, ((9, -25), (12, -22), (14, -25), (11, -18), (15, -20), (7, -22)))
        _wash(g, [(-17, 2), (-14, 0), (-11, 1), (-7, 0), (-4, 2)],
              [[(-17, 2), (-14, 0), (-12, 1)], [(-9, 1), (-7, 0), (-5, 1)]])
    if index == 5:                                                         # the lip throws white water up around him
        _wash(g, [(-20, 3), (-18, 0), (-16, -2), (-14, -1), (-12, -5), (-10, -3),
                  (-8, -7), (-5, -4), (-3, -8), (-1, -6), (1, -7), (4, -4),
                  (6, -5), (9, -2), (11, -3), (14, 0), (18, 2)],
              [[(-19, 2), (-16, -2), (-14, -1)], [(-12, -5), (-10, -3), (-8, -7)],
               [(-6, -5), (-3, -8), (-1, -6)], [(1, -7), (4, -4), (6, -5)], [(9, -2), (11, -3), (14, 0)]],
              volume=1, spray=[[(-18, -2), (-20, -4), (-21, -6)], [(-13, -5), (-15, -8)],
                               [(8, -4), (10, -6), (11, -8)]])
        _drops(g, ((-16, -6), (-12, -9), (-9, -7)))
    if index == 6:                                                         # a fan of spray breaks outward, then falls back
        _surfer(g, POSES['crouch'])
        _wash(g, [(-23, 3), (-21, 1), (-18, 0), (-16, -4), (-14, -2), (-12, -6),
                  (-9, -4), (-7, -7), (-4, -4), (-2, -6), (1, -3), (4, -5),
                  (6, -2), (9, -3), (12, 0), (15, 1), (19, 3)],
              [[(-22, 2), (-18, 0), (-16, -4)], [(-14, -2), (-12, -6), (-9, -4)],
               [(-8, -6), (-7, -7), (-4, -4)], [(-2, -6), (1, -3), (4, -5)], [(7, -2), (9, -3), (12, 0)]],
              volume=2, spray=[[(-18, -3), (-20, -6), (-21, -9)], [(-14, -5), (-16, -9), (-17, -12)],
                               [(-10, -7), (-12, -11), (-13, -14)], [(-5, -8), (-7, -12), (-8, -16)],
                               [(2, -7), (4, -11), (5, -14)], [(8, -5), (10, -8), (11, -11)]])
        _drops(g, ((-21, -11), (-17, -14), (-13, -16), (-8, -18), (5, -16), (11, -13)))
    if index == 7:                                                         # the last foam breaks apart into the wake
        _wash(g, [(-18, 2), (-16, 0), (-14, -2), (-12, 0), (-10, -3), (-7, -1),
                  (-5, -2), (-2, 0), (2, 2), (5, 1), (9, 3)],
              [[(-17, 2), (-16, 0), (-14, -2)], [(-12, 0), (-10, -3), (-7, -1)],
               [(-5, -2), (-2, 0), (1, 2)]], volume=1,
              spray=[[(-14, -2), (-16, -5), (-17, -7)], [(-9, -3), (-10, -6)]])
    return g


@lru_cache(maxsize=None)
def pictures():
    """The eight pictures as RGBA images of FRAME size."""
    return tuple(_picture(i).image() for i in range(8))
