"""The stage art of the tablet's VERSUS scene that is not worth drawing in code: little actors (a sailor band, a dancing couple, a fisherman, a cat, kids, flag wavers, a
lantern parade), harbour traffic (a ferry, a tug, a blimp, a banner plane, containers), the lantern market's stalls, vendors and paper lanterns, and a few more effects.

Everything here is ORIGINAL art, hand-built from rectangles, shaded ellipsoids and small ASCII maps in flat tones with one dark outline, in the same family as the fighters and the
fans (`scripts/prepare_game_fighting.py`, which writes the atlas and calls `stage_sprites()`). Nothing is traced or copied from any game; no ROM, no download, no service, no model.
Every picture is crisp (alpha 0 or 255) and anchored where the scene puts it (feet, keel, base). `points` are attachment points the scene needs (a rod tip, a window), in pixels from
the anchor.
"""
import math
import random

from PIL import Image, ImageDraw

from token_tv import board_arcade_fighters as bf

CLEAR = (0, 0, 0, 0)
rgb = bf.rgb


def hx(text):
    return rgb(text)


# ---- palettes: four flat tones, dark to light ---------------------------------------------------------------------------------------------------------
TEAL = [hx(c) for c in ('#0e5560', '#1c8f8f', '#3fc8b8', '#a8f2e0')]
PINK = [hx(c) for c in ('#8a2a5c', '#cf4f8c', '#f27fb0', '#ffc4dc')]
VIOLET = [hx(c) for c in ('#3b2a78', '#6a4fb8', '#9a82e8', '#d3c6ff')]
GREEN = [hx(c) for c in ('#1e5a2a', '#3a9a44', '#68d066', '#c4f5a8')]
NAVY = [hx(c) for c in ('#152350', '#2a4590', '#4f78d0', '#a9c4ff')]
GOLD = [hx(c) for c in ('#8a5a10', '#d49a1e', '#ffcf3a', '#fff0a0')]
RED = [hx(c) for c in ('#8a1c2a', '#cf3a3a', '#f26a4a', '#ffb89a')]
INKS = {'teal': hx('#0a2f3a'), 'pink': hx('#4a1230'), 'violet': hx('#1c1240'), 'green': hx('#0e2e16'), 'navy': hx('#0a1030'), 'gold': hx('#4a2c08'), 'red': hx('#3a0c14')}
RAMPS = {'teal': TEAL, 'pink': PINK, 'violet': VIOLET, 'green': GREEN, 'navy': NAVY, 'gold': GOLD, 'red': RED}
WHITE, CREAM, OFFWHITE = (255, 255, 255), hx('#fff0cf'), hx('#f4f0e4')
WOOD = [hx(c) for c in ('#5a3a1a', '#8a5a2b', '#b07a3e', '#d9a05a')]
IRON = [hx(c) for c in ('#1c222c', '#2a303c', '#4a5262', '#7a8498')]


class RS(bf.Surface):
    """The board's shaded surface (flat tones lit from the upper left)."""


# ---- tiny pixel helpers ----------------------------------------------------------------------------------------------------------------------------------
class Pix:
    """A transparent RGBA picture with crisp drawing helpers (x, y are pixels from the top left)."""

    def __init__(self, w, h):
        self.im = Image.new('RGBA', (w, h), CLEAR)
        self.d = ImageDraw.Draw(self.im)
        self.w, self.h = w, h

    def px(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.im.putpixel((int(x), int(y)), tuple(c) + (255,))

    def rect(self, x0, y0, x1, y1, c):
        if x1 >= x0 and y1 >= y0:
            self.d.rectangle((round(x0), round(y0), round(x1), round(y1)), fill=tuple(c) + (255,))

    def line(self, a, b, c, width=1):
        self.d.line((round(a[0]), round(a[1]), round(b[0]), round(b[1])), fill=tuple(c) + (255,), width=width)

    def poly(self, pts, c):
        self.d.polygon([(round(x), round(y)) for x, y in pts], fill=tuple(c) + (255,))

    def disc(self, cx, cy, r, c):
        for y in range(int(cy - r) - 1, int(cy + r) + 2):
            for x in range(int(cx - r) - 1, int(cx + r) + 2):
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    self.px(x, y, c)

    def ell(self, cx, cy, rx, ry, c):
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1:
                    self.px(x, y, c)

    def art(self, x0, y0, rows, key):
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch in key:
                    self.px(x0 + i, y0 + j, key[ch])

    def outline(self, colour, only_alpha=True):
        """A one-pixel dark ring round everything drawn (never over an existing pixel)."""
        solid = {(x, y) for y in range(self.h) for x in range(self.w) if self.im.getpixel((x, y))[3]}
        for x, y in solid:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (x + dx, y + dy) not in solid:
                    self.px(x + dx, y + dy, colour)
        return self

    def mirror(self):
        out = Pix(self.w, self.h)
        out.im = self.im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        out.d = ImageDraw.Draw(out.im)
        return out

    def result(self, anchor):
        return self.im, tuple(anchor)


def grid_to(g, box):
    full = g.image(box)
    bbox = full.getbbox()
    return full.crop(bbox), (-box[0] - bbox[0], -box[1] - bbox[1])


def ink_of(c, k=0.35):
    return tuple(int(v * k) for v in c)


# ---- critters: the fans' body, with arms and accessories under control ------------------------------------------------------------------------------
def critter(shape, ramp_name, cy=-11.0, hop=0.0, arm_l=None, arm_r=None, face='idle', legs=None, tilt=0.0, shadow=False):
    """A small cloud-bot ('bot') or octopus kid ('octo') on a Grid whose (0, 0) is the middle of the feet. `arm_l`/`arm_r` are the hand points (screen-left and screen-right),
    `face` is idle, cheer, gasp, sing (an open round mouth), shut (eyes closed, smile) or dizzy; `legs` shifts the feet for a walk: (left dx, right dx, left lift, right lift)."""
    ramp, ink = RAMPS[ramp_name], INKS[ramp_name]
    g = bf.Grid(72, 64, 36, 54)
    cy = cy + hop
    if shadow:
        bf._flat_ellipse(g, 0, 0, 8.5, 1.8, bf.SHADOW)
    arm_l = arm_l or (-11.0, cy + 8)
    arm_r = arm_r or (11.0, cy + 8)
    if shape == 'bot':
        for sx, hand in ((-1, arm_l), (1, arm_r)):
            s = RS()
            ax, ay = sx * 8.5, cy + 3
            s.tube([(ax, ay), ((ax + hand[0]) / 2, (ay + hand[1]) / 2), hand], [1.7, 1.6, 1.8])
            bf._part(g, s, ramp, ink=ink)
        lg = legs or (0, 0, 0, 0)
        for sx, k in ((-1, 0), (1, 1)):
            s = RS()
            s.ellipsoid(sx * 3.6 + lg[k], -2.2 - lg[2 + k] + hop * 0.3, 3.2, 2.2, 2.2)
            bf._part(g, s, ramp, ink=ink)
        s = RS()
        s.ellipsoid(0, cy + 1.5, 8.5, 6.5, 6.5, tag=0)
        s.ellipsoid(-5, cy - 2.5, 4.6, 4.0, 5, tag=1)
        s.ellipsoid(0.5, cy - 4.5, 5.6, 4.6, 5.6, tag=2)
        s.ellipsoid(5, cy - 2.5, 4.4, 3.8, 5, tag=3)
        bf._part(g, s, ramp, ink=ink)
        for j in range(7):                                                                                                      # the little screen
            for i in range(11):
                if i in (0, 10) and j in (0, 6):
                    continue
                g.put(-5 + i, int(cy - 4) + j, (230, 240, 255) if (i in (0, 10) or j in (0, 6)) else (12, 18, 52))
        c = (180, 250, 255)
        ey = int(cy - 2)
        if face == 'gasp':
            for dx, dy in ((-2, 0), (-3, 1), (2, 0), (3, 1), (0, 2), (-1, 2), (0, 3), (-1, 3)):
                g.put(dx, ey + dy, c)
        elif face in ('cheer', 'sing'):
            for dx, dy in ((-3, 1), (-2, 0), (-1, 1), (1, 1), (2, 0), (3, 1)):
                g.put(dx, ey + dy, c)
            if face == 'sing':
                for dx, dy in ((0, 2), (-1, 2), (0, 3), (-1, 3)):
                    g.put(dx, ey + dy, c)
        elif face == 'shut':
            for dx in (-3, -2, 2, 3):
                g.put(dx, ey, c)
        elif face == 'dizzy':
            for dx, dy in ((-3, 0), (-2, 1), (-3, 1), (2, 0), (3, 1), (2, 1)):
                g.put(dx, ey + dy, c)
        else:
            for dx in (-2, 2):
                g.put(dx, ey, c)
                g.put(dx, ey + 1, c)
        return g, 'bot'
    lg = legs or (0, 0, 0, 0)
    for sx, foot in ((-1, 5), (1, 5), (-1, 9), (1, 9)):                                                                         # legs
        s = RS()
        sh = lg[0] if sx < 0 else lg[1]
        s.tube([(sx * 3, cy + 5), (sx * foot * 0.7 + sh * 0.5, -4), (sx * (foot + 1.5) + sh, -1)], [1.8, 1.5, 1.2])
        bf._part(g, s, ramp, ink=ink)
    for sx, hand in ((-1, arm_l), (1, arm_r)):
        s = RS()
        ax, ay = sx * 8, cy + 1
        s.tube([(ax, ay), ((ax + hand[0]) / 2 + sx * 1.0, (ay + hand[1]) / 2), hand], [1.7, 1.5, 1.2])
        bf._part(g, s, ramp, ink=ink)
    s = RS()
    s.ellipsoid(0, cy, 8.8, 7.2, 6.5, bias=0.8)
    bf._part(g, s, ramp, ink=ink, th=(0.86, 0.52, 0.22))
    eye, white = (20, 16, 38), (255, 255, 255)
    for ex in (-4, 2):
        for dx, dy in ((0, -1), (1, -1), (0, 0), (1, 0)):
            g.put(ex + dx, int(cy) + dy, eye)
        if face not in ('gasp', 'shut'):
            g.put(ex, int(cy) - 1, white)
        if face == 'shut':
            g.put(ex, int(cy) - 1, ramp[2]), g.put(ex + 1, int(cy) - 1, ramp[2])
    if face == 'gasp':
        for dx, dy in ((-1, 3), (0, 3), (-1, 4), (0, 4)):
            g.put(dx, int(cy) + dy, (110, 30, 50))
    elif face in ('cheer', 'sing', 'shut'):
        for dx in range(-2, 2):
            g.put(dx, int(cy) + 3 + (1 if dx in (-2, 1) else 0), (110, 30, 50))
    for dx, dy in ((0, -1), (-1, 0), (0, 0), (1, 0), (0, 1)):                                                                   # a tiny cream starburst on the forehead
        g.put(-1 + dx, int(cy - 6) + dy, bf.CREAM)
    return g, 'octo'


def _grow(g, up):
    """The same grid on a taller canvas (the feet stay at (0, 0))."""
    out = bf.Grid(g.w, g.h + up, g.ox, g.oy + up)
    for y, row in enumerate(g.p):
        for x, c in enumerate(row):
            if c is not None:
                out.p[y + up][x] = c
    return out


def put_rows(g, x0, y0, rows, key):
    bf._art(g, x0, y0, rows, key)


K = {'.': None}
CAP = {'W': hx('#f4f0e4'), 'w': hx('#c8d0e0'), 'N': hx('#24408c'), 'n': hx('#142a60'), 'Y': hx('#f0c030')}
SAILOR_CAP = ('..wWWWWWw..', '.wWWWWWWWw.', '.WWWWYWWWW.', 'nNNNNNNNNNn', '.nNNNNNNNn.')
HARD_HAT = {'Y': hx('#ffd23a'), 'y': hx('#d49a1e'), 'h': hx('#fff6b0'), 'k': hx('#5a3a10')}
HARD = ('...hhYYYY...', '..YYhYYYYY..', '.YYYYYYYYYY.', 'kyyyyyyyyyyk')
CAPTAIN = {'W': hx('#f4f0e4'), 'B': hx('#101830'), 'G': hx('#f0c030'), 'R': hx('#c03030')}
CAPTAIN_ROWS = ('...BBBBBB...', '..BWWWWWWB..', '.BWWWGGWWWB.', 'BBBBBBBBBBBB')


def crown_row(g, cy, rows, key, dx=-6, dy=-14):
    put_rows(g, dx, int(cy) + dy, rows, key)


def fan_variant(kind, pose):
    """The three new spectator kinds: a sailor bot (a white cap), a captain octo, a dockworker bot (a hard hat). Same poses as the first four fans."""
    shape, ramp = {'bot-sailor': ('bot', 'navy'), 'octo-cap': ('octo', 'gold'), 'bot-hard': ('bot', 'green')}[kind]
    up = pose.startswith('cheer')
    hop = -2 if pose == 'cheer1' else 0
    bob = -1 if pose in ('idle1', 'cheer0') else 0
    cy = -11.0 + bob
    face = {'gasp': 'gasp', 'cheer0': 'cheer', 'cheer1': 'cheer'}.get(pose, 'idle')
    if shape == 'bot':
        al = (-11, cy - 7 + hop) if up else (-11, cy + 8)
        ar = (11, cy - 7 + hop) if up else (11, cy + 8)
    else:
        al = (-10, cy - 11 + hop) if up else (-11, cy + 6)
        ar = (10, cy - 11 + hop) if up else (11, cy + 6)
    g, _ = critter(shape, ramp, cy=cy, hop=hop, arm_l=al, arm_r=ar, face=face, shadow=True)
    cyh = cy + hop
    if kind == 'bot-sailor':
        put_rows(g, -5, int(cyh) - 13, SAILOR_CAP, CAP)
    elif kind == 'bot-hard':
        put_rows(g, -6, int(cyh) - 13, HARD, HARD_HAT)
    else:
        put_rows(g, -6, int(cyh) - 12, CAPTAIN_ROWS, CAPTAIN)
    return grid_to(g, (-36, -54, 36, 8))


# ---- the band: a drummer, a horn player, an accordionist, and their little stage ----------------------------------------------------------------
DRUM = {'R': hx('#e8453c'), 'r': hx('#8a1c2a'), 'W': hx('#f4f0e4'), 'G': hx('#ffcf3a'), 'y': hx('#fff0a0'), 'D': hx('#3a0c14')}
DRUM_ROWS = ('..DDDDDDDDDD..', '.DWWWWWWWWWWD.', 'DWWRRRRRRRRWWD', 'DWRRRGGGGRRRWD', 'DRRRGGyyGGRRRD', 'DRRRGGyyGGRRRD', 'DRrRRGGGGRRrRD', 'DWWrRRRRRRrWWD', '.DWWWWWWWWWWD.', '..DDDDDDDDDD..')
STICK = hx('#f0d8a0')
BRASS = {'Y': hx('#ffcf3a'), 'y': hx('#d49a1e'), 'h': hx('#fff6b0'), 'D': hx('#6a4410')}
HORN_UP = ('.......DDDD', '......DYYhhD', '..DDDDYYYhhD', 'DDYYYYYyyDDD', 'DYyyyyyDDD..', '.DDDDDD.....')
HORN_DOWN = ('........DDD.', '.......DYhhD', '..DDDDDYYhhD', 'DDYYYYYYyhDD', 'DYyyyyyyDDD.', '.DDDDDDD....')
ACC = {'R': hx('#cf3a3a'), 'r': hx('#8a1c2a'), 'W': hx('#f4f0e4'), 'D': hx('#3a0c14'), 'K': hx('#2a303c')}
ACC_OPEN = ('DDKKKKKKKKKKDD', 'DWWRWRWRWRWWRD', 'DKrRrRrRrRrRKD', 'DKRrRrRrRrRrKD', 'DKrRrRrRrRrRKD', 'DWWRWRWRWRWWRD', 'DDKKKKKKKKKKDD')
ACC_SHUT = ('DDKKKKKKDD', 'DWWRWRWRWD', 'DKrRrRrRKD', 'DKRrRrRrKD', 'DWWRWRWRWD', 'DDKKKKKKDD')


def drummer(k):
    cy = -11.0
    left_up = k == 0
    g, _ = critter('bot', 'teal', cy=cy, arm_l=(-9, cy - 6) if left_up else (-8, cy + 6), arm_r=(9, cy + 6) if left_up else (9, cy - 6), face='sing' if k else 'cheer', shadow=True)
    put_rows(g, -5, int(cy) - 13, SAILOR_CAP, CAP)
    put_rows(g, -7, int(cy) + 1, DRUM_ROWS, DRUM)                                                                                  # the bass drum in front
    sx, sy = (-9, int(cy) - 7) if left_up else (9, int(cy) - 7)
    for j in range(5):
        g.put(sx + (-j if left_up else j), sy - j, STICK)
        g.put(sx + (-j if left_up else j), sy - j + 1, hx('#a07a40'))
    g.put(sx + (-5 if left_up else 5), sy - 5, WHITE)
    return grid_to(g, (-36, -54, 36, 8))


def horn(k):
    cy = -11.0 + (-1 if k else 0)
    g, _ = critter('octo', 'pink', cy=cy, arm_l=(-8, cy - 1), arm_r=(7, cy - 1), face='sing', shadow=True)
    put_rows(g, -6, int(cy) - 12, CAPTAIN_ROWS, CAPTAIN)
    put_rows(g, -4, int(cy) - 6 if k else int(cy) - 8, HORN_DOWN if k else HORN_UP, BRASS)
    return grid_to(g, (-36, -54, 36, 8))


def accordion(k):
    cy = -11.0
    g, _ = critter('bot', 'violet', cy=cy, arm_l=(-9, cy + 3), arm_r=(9, cy + 3), face='cheer' if k else 'idle', shadow=True)
    put_rows(g, -5, int(cy) - 13, SAILOR_CAP, CAP)
    rows = ACC_OPEN if k else ACC_SHUT
    put_rows(g, -len(rows[0]) // 2, int(cy) + 0, rows, ACC)
    return grid_to(g, (-36, -54, 36, 8))


def bandstand():
    """A low wooden stage with a trim of bunting: the band stands on it (anchor: the middle of the front edge, at the floor)."""
    w, h = 78, 14
    p = Pix(w, h)
    p.rect(0, 3, w - 1, h - 1, WOOD[0])
    p.rect(1, 3, w - 2, 4, WOOD[3])
    p.rect(0, 5, w - 1, h - 2, WOOD[1])
    for x in range(6, w - 4, 13):
        p.rect(x, 6, x, h - 2, WOOD[0])
        p.rect(x + 1, 6, x + 1, h - 2, WOOD[2])
    p.rect(0, h - 1, w - 1, h - 1, WOOD[0])
    p.rect(0, 0, w - 1, 2, hx('#2a303c'))
    for i, c in enumerate(('#e8453c', '#f5c12e', '#f4f4ec', '#2f7fd0')):
        for x in range(2 + i * 4, w - 4, 16):
            p.rect(x, 3, x + 3, 6, hx(c))
            p.rect(x + 1, 7, x + 2, 7, hx(c))
    return p.result((w // 2, h - 1))


# ---- a dancing couple, a fisherman, a cat, kids on a crate, flags, balloons -------------------------------------------------------------------------
def dancers(k):
    """A bot and an octopus kid dancing: sway left, sway right, a twirl (the octopus arm up), a dip."""
    g = bf.Grid(96, 64, 48, 54)
    sway = (-2, 2, 0, 0)[k]
    dip = (0, 0, 0, 2)[k]
    a, _ = critter('bot', 'pink', cy=-11.0 + dip, arm_l=(-6, -10 + dip), arm_r=(10, -16 + dip) if k != 3 else (9, -9), face='cheer', legs=(sway, sway, 0, 0))
    b, _ = critter('octo', 'green', cy=-11.0 + dip, arm_l=(-9, -12) if k != 2 else (-8, -24), arm_r=(10, -10), face='cheer', legs=(sway, sway, 0, 0))
    for src, dx in ((a, -9 + sway), (b, 10 + sway)):
        for y, row in enumerate(src.p):
            for x, c in enumerate(row):
                if c is not None:
                    gx, gy = x - src.ox + dx, y - src.oy
                    g.put(gx, gy, c)
    bf._flat_ellipse(g, 0, 0, 17, 2, bf.SHADOW)
    return grid_to(g, (-48, -54, 48, 8))


def fisher(k):
    """An old bot in a straw hat sitting on a crate with a rod: wait, wait (the float bobs), a bite (the rod bends), a catch (a fish held up)."""
    g = bf.Grid(80, 64, 40, 54)
    bf._flat_ellipse(g, 0, 0, 11, 2, bf.SHADOW)
    crate = {'d': WOOD[0], 'm': WOOD[1], 'l': WOOD[2], 'h': WOOD[3]}
    put_rows(g, -9, -9, ('dddddddddddddddddd', 'dhhhhhhhhhhhhhhhhd', 'dmmmmmmmmmmmmmmmmd', 'dmlmmmmmmmmmmlmmmd', 'dmmmmmmmmmmmmmmmmd', 'dddddddddddddddddd'), crate)
    cy = -17.0 + (-1 if k == 1 else 0)
    arm_r = {0: (9, cy + 2), 1: (9, cy + 1), 2: (8, cy - 2), 3: (7, cy - 12)}[k]
    face = {0: 'idle', 1: 'idle', 2: 'gasp', 3: 'cheer'}[k]
    gg, _ = critter('bot', 'navy', cy=cy, arm_l=(-8, cy + 6), arm_r=arm_r, face=face)
    for y, row in enumerate(gg.p):
        for x, c in enumerate(row):
            if c is not None:
                g.put(x - gg.ox, y - gg.oy, c)
    hat = {'S': hx('#e8c860'), 's': hx('#b08a30'), 'B': hx('#c03030')}
    put_rows(g, -9, int(cy) - 12, ('.....sSSSs.....', '...sSSSSSSSs...', '..sSSSSBBSSSs..', 'ssSSSSSBBSSSSss', 'sSSSSSSSSSSSSSs', '.ssssssssssssss'), hat)
    rod = hx('#6a4422')
    tip = (23, int(cy) - 15)
    if k == 2:
        tip = (21, int(cy) - 8)
    if k == 3:
        tip = (17, int(cy) - 24)
    hand = (arm_r[0] + 1, int(arm_r[1]))
    steps = 24
    for i in range(steps + 1):
        t = i / steps
        bend = 0
        if k == 2:
            bend = math.sin(t * math.pi) * -3
        g.put(round(hand[0] + (tip[0] - hand[0]) * t), round(hand[1] + (tip[1] - hand[1]) * t + bend), rod)
    if k == 3:
        fish = {'S': hx('#b8d0e8'), 's': hx('#7aa0c8'), 'D': hx('#24406a'), 'W': WHITE}
        put_rows(g, 8, int(cy) - 14, ('..DDDD.', '.DSSWsD', 'DDSSSsD', '.DsssDD', '..DDDD.'), fish)
    img, anchor = grid_to(g, (-40, -54, 40, 8))
    bbox_x = img.width
    return img, anchor, (tip[0] + anchor[0], tip[1] + anchor[1])


CAT = {'k': hx('#14141e'), 'b': hx('#2c2c3e'), 'h': hx('#4c4c66'), 'w': hx('#f4f0e4'), 'e': hx('#ffd23a'), 'p': hx('#ff9aa8'), 'z': hx('#a8c8ff')}
CAT_FRAMES = {
    'sit0': ('.k..k....', 'kbk.kbk...', 'kbbkbbk...', 'kbebbek...', 'kbbpbbk...', '.kbbbbk...', '.kbbbbbk..', 'kbhbbbbbk.', 'kbbbbbbbbk', 'kwwkbbbbbk', '.kkkkkkkkk'),
    'sit1': ('.k..k....k', 'kbk.kbk.kb', 'kbbkbbk.kb', 'kbebbek.kb', 'kbbpbbk.kb', '.kbbbbk.kb', '.kbbbbbkkb', 'kbhbbbbbbk', 'kbbbbbbbbk', 'kwwkbbbbbk', '.kkkkkkkkk'),
    'walk0': ('...k..k.......', '..kbk.kbk.....', '..kbbkbbk..kk.', '..kbebbek.kbk.', '..kbbpbbkkbbk.', '...kbbbbbbbbk.', '..kbhbbbbbbbk.', '.kbbbbbbbbbk..', 'kwk.kbk.kbk...', 'kk..kk..kk....'),
    'walk1': ('...k..k.......', '..kbk.kbk..kk.', '..kbbkbbk.kbk.', '..kbebbek.kbk.', '..kbbpbbkkbbk.', '...kbbbbbbbbk.', '..kbhbbbbbbbk.', '.kbbbbbbbbbk..', '.kbk.kbk.kwk..', '.kk..kk..kk...'),
    'lick': ('..........', '..k..k....', '.kbkkbk...', 'kbbbbbbk..', 'kbpbbbbbk.', '.kbbbbbbbk', '.kbhbbbbbk', 'kbbbbbbbbk', 'kwwkbbbbbk', '.kkkkkkkkk'),
    'arch': ('...k..k....', '..kbk.kbk.k.', '..kbbkbbkkb.', '..kbeeebbbbk', '...kbbpbbbbk', '..kbhbbbbbbk', '.kbbbbbbbbbk', '.kbk.kbk.kbk', '.kwk.kwk.kwk', '.kk..kk..kk.'),
    'sleep': ('..........zz.', '.........z.z.', '..........zz.', '.kkkkkkkk....', 'kbbbbbbbbk...', 'kbhbbbbbbbk..', 'kbbbbbbbbbbk.', 'kwkkbbbbbkk..', '.kkkkkkkkk...'),
}


def cat(name):
    rows = CAT_FRAMES[name]
    p = Pix(len(rows[0]) + 2, len(rows) + 1)
    p.art(1, 0, rows, CAT)
    return p.result((p.w // 2, p.h - 1))


def kids(k):
    """Two octopus kids sitting on a crate, legs swinging (0, 1) or cheering (2)."""
    g = bf.Grid(64, 60, 32, 52)
    crate = {'d': WOOD[0], 'm': WOOD[1], 'l': WOOD[2], 'h': WOOD[3]}
    bf._flat_ellipse(g, 0, 0, 15, 2, bf.SHADOW)
    put_rows(g, -14, -14, ('dddddddddddddddddddddddddddd', 'dhhhhhhhhhhhhhhhhhhhhhhhhhhd', 'dmmmmmmmmmmmmmmmmmmmmmmmmmmd', 'dmmlmmmmmmmmmmmmmmmmmmlmmmmd', 'dmmmmmmmmmmmmmmmmmmmmmmmmmmd', 'dmmmmmmmmmmmmmmmmmmmmmmmmmmd',
                         'dmmmmmmmmmmmmmmmmmmmmmmmmmmd', 'dmmmmmmmmmmmmmmmmmmmmmmmmmmd', 'dmmlmmmmmmmmmmmmmmmmmmlmmmmd', 'dddddddddddddddddddddddddddd'), crate)
    swing = (0, 3, 0)[k]
    for who, (ramp, dx) in enumerate((('teal', -8), ('violet', 8))):
        cy = -23.0 - (2 if k == 2 else 0)
        al = (dx - 9, cy - 10) if k == 2 else (dx - 8, cy + 7)
        ar = (dx + 9, cy - 10) if k == 2 else (dx + 8, cy + 7)
        gg, _ = critter('octo', ramp, cy=cy, arm_l=(al[0] - dx, al[1]), arm_r=(ar[0] - dx, ar[1]), face='cheer' if k == 2 else 'idle',
                        legs=(swing if who == 0 else -swing, swing if who else -swing, 0, 0))
        for y, row in enumerate(gg.p):
            for x, c in enumerate(row):
                if c is not None and y - gg.oy < -14 + 6:
                    g.put(x - gg.ox + dx, y - gg.oy, c)
    return grid_to(g, (-32, -52, 32, 8))


def flag(which, k):
    """A team flag on a pole (anchor: the foot of the pole). Codex: blue with a white prompt; Claude: orange with a cream starburst."""
    p = Pix(24, 34)
    p.rect(2, 4, 2, 33, hx('#cfc4a8'))
    p.rect(1, 3, 3, 3, hx('#ffcf3a'))
    sway = 1 if k else 0
    base, hi, ink = (hx('#2a4590'), hx('#4f78d0'), hx('#101a48')) if which == 'codex' else (hx('#d4683a'), hx('#f28d4f'), hx('#47202f'))
    for x in range(3, 21):
        wave = round(math.sin((x + k * 3) * 0.55) * 1.2)
        for y in range(5, 15):
            p.px(x, y + wave + sway * 0, base)
        p.px(x, 5 + wave, hi)
        p.px(x, 14 + wave, ink)
        p.px(x, 4 + wave, ink)
    if which == 'codex':
        for i, (dx, dy) in enumerate(((7, 7), (8, 8), (9, 9), (8, 10), (7, 11))):
            p.px(dx + 1, dy + 1, WHITE)
        for dx in range(11, 15):
            p.px(dx + 2, 12, WHITE)
    else:
        for dx, dy in ((11, 8), (10, 9), (11, 9), (12, 9), (11, 10), (11, 11), (9, 9), (13, 9)):
            p.px(dx + 1, dy, CREAM)
    return p.result((2, 33))


def balloon(k):
    c = (RED, GOLD, TEAL)[k]
    p = Pix(10, 20)
    p.ell(5, 5, 4, 4.8, c[1])
    p.ell(4, 4, 2, 2.4, c[2])
    p.px(3, 3, c[3])
    p.px(4, 3, c[3])
    p.rect(4, 10, 6, 10, c[0])
    p.outline(INKS[('red', 'gold', 'teal')[k]])
    for y in range(11, 19):
        p.px(5 + (1 if y % 4 > 1 else 0), y, hx('#e8e8f0'))
    return p.result((5, 19))


FISH = {'S': hx('#b8d0e8'), 's': hx('#7aa0c8'), 'D': hx('#24406a'), 'W': WHITE, 'O': hx('#ff9a52')}
FISH_FRAMES = (('..DDDD...D', '.DSSSWsDDD', 'DDSSSssDOD', '.DsssssDDD', '..DDDDD..D'), ('..DDDD..DD', '.DSSSWsDDD', 'DDSSSssDOD', '.DsssssDDD', '..DDDDD...'))


def fish(k):
    p = Pix(12, 7)
    p.art(1, 1, FISH_FRAMES[k], FISH)
    return p.result((6, 3))


# ---- harbour traffic ---------------------------------------------------------------------------------------------------------------------------------------
def container(variant):
    cols = [(hx('#d9702e'), hx('#a84a1a'), hx('#ffa060')), (hx('#3a7ab8'), hx('#1f4a7a'), hx('#7ab4e8')), (hx('#cfae3a'), hx('#8a7418'), hx('#f4d878')), (hx('#3aa06a'), hx('#1c6a40'), hx('#7ad8a0'))][variant]
    p = Pix(24, 10)
    p.rect(0, 0, 23, 9, cols[1])
    p.rect(1, 1, 22, 8, cols[0])
    p.rect(1, 1, 22, 1, cols[2])
    for x in range(4, 22, 3):
        p.rect(x, 2, x, 8, cols[1])
    p.rect(0, 0, 1, 1, hx('#2a303c'))
    p.rect(22, 0, 23, 1, hx('#2a303c'))
    p.rect(0, 8, 1, 9, hx('#2a303c'))
    p.rect(22, 8, 23, 9, hx('#2a303c'))
    return p.result((12, 9))


def ferry(k):
    w, h = 64, 30
    p = Pix(w, h)
    hull_d, hull_r, white, grey, win, dk = hx('#1c2c50'), hx('#c0402e'), hx('#f0f4f8'), hx('#8a98b0'), hx('#ffe28a'), hx('#101c38')
    p.poly([(2, 21), (62, 21), (56, 28), (8, 28)], hull_d)
    p.rect(3, 19, 61, 21, hull_r)
    p.rect(8, 27, 56, 27, dk)
    p.poly([(2, 21), (62, 21), (61, 22), (3, 22)], hx('#ffffff'))
    p.rect(8, 11, 54, 18, white)
    p.rect(8, 11, 54, 11, grey)
    p.rect(8, 18, 54, 18, grey)
    p.rect(14, 4, 46, 10, white)
    p.rect(14, 4, 46, 4, grey)
    p.rect(14, 10, 46, 10, grey)
    lights = []
    for x in range(10, 53, 5):
        p.rect(x, 13, x + 2, 15, hx('#4a7898'))
        lights.append((x, 13))
    for x in range(17, 45, 5):
        p.rect(x, 6, x + 2, 8, hx('#4a7898'))
        lights.append((x, 6))
    p.rect(26, 0, 33, 3, hx('#c0402e'))
    p.rect(26, 0, 33, 0, hx('#1a1a22'))
    p.rect(29, 1, 30, 3, hx('#f0c030'))
    p.rect(40, 0 + (1 if k else 0), 41, 3, grey)
    p.rect(44, 2, 44, 10, hx('#3a3a46'))
    p.poly([(44, 1 + k), (49, 2 + k), (44, 4 + k)], hx('#e8453c'))
    pts = [(x - 32 + 1, y - 29) for x, y in lights]
    p.outline(dk)
    return p.im, (32, 29), pts


def tug(k):
    w, h = 36, 22
    p = Pix(w, h)
    dk, red, white, blk = hx('#1c1c28'), hx('#c0402e'), hx('#f0f4f8'), hx('#2a2a38')
    p.poly([(1, 13), (34, 13), (30, 19), (5, 19)], blk)
    p.rect(2, 11, 33, 13, red)
    p.rect(2, 11, 33, 11, hx('#e8705a'))
    for x in (4, 12, 20, 28):
        p.ell(x + 2, 15, 1.6, 1.6, hx('#3a3a4a'))
    p.rect(11, 4, 22, 10, white)
    p.rect(11, 4, 22, 4, hx('#9aa8c0'))
    p.rect(13, 6, 15, 8, hx('#4a7898'))
    p.rect(18, 6, 20, 8, hx('#4a7898'))
    p.rect(25, 1, 28, 10, blk)
    p.rect(25, 1, 28, 2, red)
    p.rect(8, 0 + k, 8, 5, hx('#8a7a60'))
    pts = [(14 - 18, 6 - 21), (19 - 18, 6 - 21)]
    p.outline(dk)
    return p.im, (18, 21), pts


def blimp(k):
    w, h = 72, 32
    p = Pix(w, h)
    body = (hx('#7a1f2c'), hx('#d6463a'), hx('#ff8a6a'), hx('#ffd0b8'))
    for y in range(3, 22):
        t = (y - 12.5) / 9.5
        half = int(math.sqrt(max(0, 1 - t * t)) * 31)
        shade = body[3 if y < 7 else 2 if y < 11 else 1 if y < 17 else 0]
        p.rect(36 - half + 2, y, 36 + half, y, shade)
    for x in range(12, 60, 9):
        for y in range(5, 21):
            t = (y - 12.5) / 9.5
            half = int(math.sqrt(max(0, 1 - t * t)) * 31)
            if abs(x - 36) < half:
                p.px(x, y, hx('#f4f0e4') if y > 11 else hx('#fff6e8'))
    p.poly([(4, 12), (-1, 6), (8, 10)], body[1])
    p.poly([(4, 13), (-1, 20), (8, 15)], body[0])
    p.rect(4, 11, 9, 14, body[1])
    p.poly([(66, 11), (70, 4), (70, 22), (66, 15)], body[1])
    p.rect(54, 22, 60, 24, hx('#3a3a4a'))
    p.rect(24, 22, 48, 28, hx('#2a303c'))
    p.rect(25, 23, 47, 24, hx('#d8dde8'))
    lights = []
    for x in range(27, 46, 4):
        p.rect(x, 25, x + 2, 26, hx('#ffe28a'))
        lights.append((x, 25))
    p.rect(30, 21, 31, 22, hx('#2a303c'))
    p.rect(40, 21, 41, 22, hx('#2a303c'))
    prop_x = 71
    p.rect(prop_x - 1, 11 + (k * 2), prop_x, 14 + (k * 2), hx('#c0c8d8'))
    p.outline(hx('#2a0c14'))
    pts = [(x - 36, y - 28) for x, y in lights]
    return p.im, (36, 28), pts


def plane(k):
    w, h = 34, 14
    p = Pix(w, h)
    p.poly([(4, 6), (26, 5), (32, 7), (26, 9), (4, 9)], hx('#f4f0e4'))
    p.rect(8, 4, 20, 6, hx('#cf3a3a'))
    p.rect(8, 9, 20, 10, hx('#a8b4c8'))
    p.rect(2, 3, 5, 8, hx('#cf3a3a'))
    p.rect(14, 1, 24, 3, hx('#d8e0ec'))
    p.rect(14, 10, 24, 12, hx('#c0c8d8'))
    p.rect(22, 6, 25, 7, hx('#4a7898'))
    p.rect(32, 4 + (k * 3), 33, 9 - (k * 3) if k else 9, hx('#2a303c'))
    p.outline(hx('#1a2038'))
    return p.im, (4, 7)


def buoy(k):
    p = Pix(10, 14)
    p.rect(3, 9, 6, 12, hx('#c03030'))
    p.rect(3, 6, 6, 8, hx('#f4f0e4'))
    p.rect(3, 3, 6, 5, hx('#c03030'))
    p.rect(4, 0, 5, 2, hx('#2a303c'))
    p.px(4, 0, hx('#ffd23a') if k else hx('#6a4a10'))
    p.outline(hx('#2a0c14'))
    return p.result((5, 12))


# ---- the lantern market ------------------------------------------------------------------------------------------------------------------------------------
LANTERN_COLOURS = [(hx('#8a1c2a'), hx('#e8453c'), hx('#ff8a6a'), hx('#ffd0b8')), (hx('#8a4a10'), hx('#f08a2a'), hx('#ffc050'), hx('#fff0b0')),
                   (hx('#8a6a10'), hx('#ffcf3a'), hx('#fff06a'), hx('#fffbd0')), (hx('#8a2a5c'), hx('#e8509a'), hx('#ff9acc'), hx('#ffd8ec'))]


def paper_lantern(colour, big):
    c = LANTERN_COLOURS[colour]
    rx, ry = (6.5, 7.5) if big else (4.5, 5.5)
    w, h = int(rx * 2) + 6, int(ry * 2) + 12
    p = Pix(w, h)
    cx, cy = w / 2, 6 + ry
    for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
        for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
            u, v = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            r2 = u * u + v * v
            if r2 <= 1:
                t = (-u * 0.5 - v * 0.6 + math.sqrt(1 - r2) * 0.6)
                p.px(x, y, c[3] if t > 0.75 else c[2] if t > 0.3 else c[1] if t > -0.15 else c[0])
    for k in (-0.55, 0.0, 0.55):                                                                                              # ribs
        y = round(cy + k * ry)
        for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
            if p.im.getpixel((x, y))[3]:
                p.px(x, y, c[0])
    p.rect(cx - 2.5, cy - ry - 2, cx + 1.5, cy - ry, hx('#2a1810'))
    p.rect(cx - 2.5, cy + ry - 0.5, cx + 1.5, cy + ry + 1, hx('#2a1810'))
    p.rect(cx - 0.5, 0, cx - 0.5, cy - ry - 2, hx('#2a1810'))
    p.rect(cx - 0.5, cy + ry + 1, cx - 0.5, cy + ry + 4, c[2])
    p.px(cx - 1.5, cy + ry + 4, c[1])
    p.px(cx + 0.5, cy + ry + 4, c[1])
    p.outline(INKS['red'])
    return p.result((p.w // 2, 0))


def skylantern(k):
    p = Pix(9, 12)
    p.rect(2, 1, 6, 8, hx('#ffb24a'))
    p.rect(3, 2, 5, 7, hx('#ffe9a0'))
    p.rect(2, 1, 6, 1, hx('#8a4a10'))
    p.rect(2, 8, 6, 8, hx('#8a4a10'))
    p.px(4, 5, hx('#ffffff'))
    p.px(4, 9 + k, hx('#ff9a30'))
    p.px(4, 10 + k, hx('#ffd23a'))
    p.outline(hx('#4a2008'))
    return p.result((4, 6))


def stall(variant):
    """The front of a market stall: an awning, posts and a counter, with the window to the vendor left transparent. Returns (picture, anchor, points) where points are [window rect, sign rect]."""
    awning = {0: (hx('#e8453c'), hx('#f8f4ec')), 1: (hx('#3a9a44'), hx('#f5e08a')), 2: (hx('#2f6fd0'), hx('#f8f4ec')), 3: (hx('#8a4fc0'), hx('#ffd23a'))}[variant]
    w, h = 54, 52
    p = Pix(w, h)
    dk = hx('#2a1810')
    p.rect(2, 12, 4, h - 1, WOOD[1])
    p.rect(w - 5, 12, w - 3, h - 1, WOOD[1])
    p.rect(2, 12, 2, h - 1, WOOD[2])
    p.rect(w - 5, 12, w - 5, h - 1, WOOD[2])
    for x in range(0, w):                                                                                                       # the striped awning
        a = awning[(x // 5) % 2]
        sag = 1 if (x % 5) in (1, 2, 3) else 0
        p.rect(x, 3, x, 11 + sag, a)
        p.px(x, 3, hx('#ffffff') if a == awning[1] else tuple(min(255, int(c * 1.25)) for c in a))
        p.px(x, 12 + sag, ink_of(a, 0.45))
    for x in range(0, w, 5):
        p.poly([(x, 12), (x + 4, 12), (x + 2, 15)], awning[(x // 5) % 2])
        p.px(x + 2, 15, ink_of(awning[(x // 5) % 2], 0.45))
    p.rect(0, 2, w - 1, 2, dk)
    p.rect(1, 33, w - 2, 35, WOOD[3])
    p.rect(1, 36, w - 2, h - 1, WOOD[1])
    for x in range(6, w - 4, 9):
        p.rect(x, 37, x, h - 2, WOOD[0])
    p.rect(1, 36, w - 2, 36, WOOD[2])
    p.rect(1, h - 1, w - 2, h - 1, WOOD[0])
    p.rect(1, 35, w - 2, 35, WOOD[0])
    sign = (w // 2 - 15, 17, 30, 9)
    p.rect(sign[0] - 1, sign[1] - 1, sign[0] + sign[2], sign[1] + sign[3], dk)
    p.rect(sign[0], sign[1], sign[0] + sign[2] - 1, sign[1] + sign[3] - 1, hx('#10202c'))
    goods = {
        0: lambda: [p.ell(18, 32, 5, 2.2, hx('#d8d8e0')), p.rect(14, 28, 22, 31, hx('#9aa8b8')), p.rect(14, 28, 22, 28, hx('#e8eef4')), p.rect(34, 30, 42, 32, hx('#d9702e')), p.rect(34, 30, 42, 30, hx('#ffa060'))],
        1: lambda: [p.disc(15 + 5 * i, 31, 2.6, (hx('#f08a2a'), hx('#e8453c'), hx('#8ad05a'), hx('#ffd23a'))[i % 4]) for i in range(7)],
        2: lambda: [p.rect(12, 30, 42, 32, hx('#4a3a38')), p.rect(12, 30, 42, 30, hx('#ff9a30'))] + [p.px(15 + 4 * i, 29, hx('#ffd23a')) for i in range(7)],
        3: lambda: [p.rect(12 + 8 * i, 26, 17 + 8 * i, 32, (hx('#e8509a'), hx('#2f7fd0'), hx('#ffcf3a'), hx('#68d066'))[i % 4]) for i in range(4)],
    }[variant]
    goods()
    window = (8, 16, w - 9, 34)
    p.outline(dk)
    pts = [(window[0] - w // 2, window[1] - (h - 1)), (window[2] - w // 2, window[3] - (h - 1)), (sign[0] - w // 2, sign[1] - (h - 1)), (sign[0] + sign[2] - w // 2, sign[1] + sign[3] - (h - 1))]
    return p.im, (w // 2, h - 1), pts


def vendor(kind, k):
    """The cook behind a counter: a bust that stops at the counter's top (its anchor is the middle of its bottom edge), drawn over the stall. 'noodle': an octopus with a headband flipping noodles; 'grill': a bot fanning a skewer grill."""
    if kind == 'noodle':
        a = ((-10, -24), (9, -8), 'cheer'), ((-10, -9), (9, -22), 'idle'), ((-9, -16), (9, -16), 'sing')
        al, ar, face = a[k]
        g, _ = critter('octo', 'red', cy=-11.0, arm_l=al, arm_r=ar, face=face)
        put_rows(g, -7, -17, ('.WWWWWWWW.', 'WRRRRRRRRW', '.nnnnnnnn.'), {'W': hx('#f4f0e4'), 'R': hx('#cf3a3a'), 'n': hx('#8a1c2a')})
        if k == 0:
            for dy in range(3):
                g.put(-10 + (dy % 2), -27 - dy, hx('#fff0a0'))
        image, (ax, _) = grid_to(g, (-36, -54, 36, -7))
        return image, (ax, image.height)
    g, _ = critter('bot', 'teal', cy=-11.0, arm_l=(-10, -7 if k else -3), arm_r=(10, -4), face='cheer' if k else 'idle')
    put_rows(g, -6, -17, ('.WWWWWWWW.', 'WWWWWWWWWW', 'WWWWWWWWWW'), {'W': hx('#f4f0e4')})
    image, (ax, _) = grid_to(g, (-36, -54, 36, -7))
    return image, (ax, image.height)


def carrier(kind, k):
    """A lantern-parade walker: a bot or an octopus kid with a pole and a big round lantern, four steps of a walk."""
    phi = k * math.pi / 2
    bob = -abs(math.sin(phi)) * 1.5
    lg = (round(3 * math.sin(phi)), round(-3 * math.sin(phi)), max(0, round(2 * math.sin(phi))), max(0, round(-2 * math.sin(phi))))
    g, _ = critter('bot' if kind == 'bot' else 'octo', 'gold' if kind == 'bot' else 'green', cy=-11.0 + bob, arm_l=(-8, -17 + bob), arm_r=(10, -22 + bob), face='cheer', legs=lg, shadow=True)
    g = _grow(g, 70)
    x = 11
    for y in range(-46, -9):
        g.put(x, y + round(bob), hx('#8a6a3a'))
    for dy, (ramp, ink) in ((0, (LANTERN_COLOURS[0], INKS['red'])),):
        cx, cy2 = x, -52 + round(bob)
        rx, ry = 6.5, 8
        for yy in range(int(cy2 - ry) - 1, int(cy2 + ry) + 2):
            for xx in range(int(cx - rx) - 1, int(cx + rx) + 2):
                u, v = (xx + 0.5 - cx) / rx, (yy + 0.5 - cy2) / ry
                r2 = u * u + v * v
                if r2 <= 1:
                    t = (-u * 0.5 - v * 0.6 + math.sqrt(1 - r2) * 0.6)
                    g.put(xx, yy, ramp[3] if t > 0.75 else ramp[2] if t > 0.3 else ramp[1] if t > -0.15 else ramp[0])
        for yy in (cy2 - 3, cy2, cy2 + 3):
            for xx in range(int(cx - rx), int(cx + rx) + 1):
                if g.get(xx, int(yy)) is not None:
                    g.put(xx, int(yy), ramp[0])
    return grid_to(g, (-36, -70, 36, 8))


# ---- more effects: a slash, an impact streak burst, notes, steam and a splash ----------------------------------------------------------------------------
def fx_slash(k):
    """A bright crescent that sweeps (three sizes), for the whip and the heavy blows."""
    size = (30, 42, 54)[k]
    p = Pix(size + 4, size + 4)
    cx, cy = size * 0.2, size * 0.55
    r_out, r_in = size * 0.9, size * 0.9 - (4 + k * 2)
    for y in range(p.h):
        for x in range(p.w):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            d = math.hypot(dx, dy)
            ang = math.degrees(math.atan2(dy, dx))
            if r_in - 3 <= d <= r_out and -62 + k * 8 <= ang <= 62 - k * 8:
                core = r_in <= d <= r_out - 2
                p.px(x, y, WHITE if core and d > r_in + 2 else hx('#fff08a') if core else hx('#ff9a30'))
    p.outline(bf.INK_BURST)
    return p.result((p.w // 4, p.h // 2))


def fx_streak(k):
    """Radial speed lines around the point of impact (a spiky ring with an empty middle)."""
    size = (36, 52, 64)[k]
    p = Pix(size, size)
    c = size / 2
    n = 14
    for i in range(n):
        a = i * 2 * math.pi / n + 0.2 * k
        r0, r1 = size * (0.2 + 0.05 * k), size * (0.46 + 0.02 * ((i * 7) % 3))
        for t in range(int(r0), int(r1) + 1):
            p.px(c + math.cos(a) * t, c + math.sin(a) * t, WHITE if t > (r0 + r1) / 2 else hx('#ffd23a'))
    return p.result((size // 2, size // 2))


def fx_note(k):
    p = Pix(9, 11)
    ink, hi = hx('#ffffff'), hx('#ffd23a')
    if k == 0:
        p.rect(4, 1, 4, 7, ink)
        p.rect(4, 1, 7, 2, ink)
        p.rect(1, 7, 4, 9, hi)
        p.rect(0, 8, 3, 8, ink)
    else:
        p.rect(2, 1, 2, 8, ink)
        p.rect(6, 2, 6, 9, ink)
        p.rect(2, 1, 6, 2, ink)
        p.rect(0, 7, 2, 9, hi)
        p.rect(4, 8, 6, 10, hi)
    p.outline(hx('#3b1348'))
    return p.result((4, 5))


def fx_steam(k):
    size = (10, 14, 18, 22)[k]
    p = Pix(size + 4, size + 4)
    rnd = random.Random(k * 17 + 3)
    for i in range(3 + k):
        cx, cy = size / 2 + rnd.uniform(-size * 0.25, size * 0.25) + 2, size * (0.75 - 0.2 * i / max(1, 3 + k)) + 2
        r = size * rnd.uniform(0.18, 0.3)
        p.disc(cx, cy, r, hx('#e8edf4'))
        p.disc(cx - 1, cy - 1, r * 0.55, WHITE)
    return p.result((p.w // 2, p.h - 1))


def fx_splash(k):
    p = Pix(30, 24)
    cx = 15
    n = (3, 5, 6, 4)[k]
    for i in range(n):
        a = -math.pi * (0.15 + 0.7 * i / max(1, n - 1))
        r = (4 + 3 * k) * (1 + 0.3 * (i % 2))
        x, y = cx + math.cos(a) * r * 1.2, 20 + math.sin(a) * r * (1.4 - 0.2 * k)
        p.disc(x, y, 1.6 if k < 3 else 1.1, hx('#e8f4fa'))
        p.px(x, y - 1, WHITE)
    if k in (1, 2):
        p.rect(cx - 2, 14 - k * 2, cx + 1, 20, hx('#d8ecf6'))
        p.rect(cx - 1, 14 - k * 2, cx, 20, WHITE)
    return p.result((15, 21))


# ---- the list of everything this module adds ---------------------------------------------------------------------------------------------------------------
NEW_CROWD = ('bot-sailor', 'octo-cap', 'bot-hard')
NEW_FX = {'slash': (3, fx_slash), 'streak': (3, fx_streak), 'note': (2, fx_note), 'steam': (4, fx_steam), 'splash': (4, fx_splash)}
ACTORS = {'drummer': 2, 'horn': 2, 'accordion': 2, 'bandstand': 1, 'dancers': 4, 'fisher': 4, 'fish': 2, 'cat': 7, 'kids': 3, 'flag-codex': 2, 'flag-claude': 2, 'balloon': 3, 'cont': 4,
          'ferry': 2, 'tug': 2, 'blimp': 2, 'plane': 2, 'buoy': 2, 'lantern': 8, 'skylantern': 2, 'stall': 4, 'noodle': 3, 'grill': 2, 'carrier-bot': 4, 'carrier-octo': 4}
CAT_ORDER = ('sit0', 'sit1', 'walk0', 'walk1', 'lick', 'arch', 'sleep')


def actor_frames():
    """({name: (picture, anchor)}, {actor: [frame names]}, {frame name: [[dx, dy], ...]}) in a fixed order."""
    frames, anims, points = {}, {}, {}

    def add(actor, k, art):
        name = f'act-{actor}-{k}'
        if len(art) == 3:
            image, anchor, pts = art
            points[name] = [[int(x), int(y)] for x, y in pts]
        else:
            image, anchor = art
        frames[name] = (image, anchor)
        anims.setdefault(actor, []).append(name)

    for k in range(2):
        add('drummer', k, drummer(k))
        add('horn', k, horn(k))
        add('accordion', k, accordion(k))
    add('bandstand', 0, bandstand())
    for k in range(4):
        add('dancers', k, dancers(k))
    for k in range(4):
        image, anchor, tip = fisher(k)
        add('fisher', k, (image, anchor, [(tip[0] - anchor[0], tip[1] - anchor[1])]))
    for k in range(2):
        add('fish', k, fish(k))
    for k, pose in enumerate(CAT_ORDER):
        add('cat', k, cat(pose))
    for k in range(3):
        add('kids', k, kids(k))
    for k in range(2):
        add('flag-codex', k, flag('codex', k))
        add('flag-claude', k, flag('claude', k))
    for k in range(3):
        add('balloon', k, balloon(k))
    for k in range(4):
        add('cont', k, container(k))
    for k in range(2):
        add('ferry', k, ferry(k))
        add('tug', k, tug(k))
        add('blimp', k, blimp(k))
        add('plane', k, plane(k))
        add('buoy', k, buoy(k))
    for big in (0, 1):
        for colour in range(4):
            add('lantern', colour + 4 * big, paper_lantern(colour, bool(big)))
    for k in range(2):
        add('skylantern', k, skylantern(k))
    for v in range(4):
        add('stall', v, stall(v))
    for k in range(3):
        add('noodle', k, vendor('noodle', k))
    for k in range(2):
        add('grill', k, vendor('grill', k))
    for k in range(4):
        add('carrier-bot', k, carrier('bot', k))
        add('carrier-octo', k, carrier('octo', k))
    return frames, anims, points


def stage_sprites():
    """Everything the new stages add to the atlas: (frames, anims by group, points)."""
    frames, actors, points = actor_frames()
    anims = {'actors': actors, 'fx': {}, 'crowd': {}}
    for kind, (count, make) in NEW_FX.items():
        anims['fx'][kind] = []
        for k in range(count):
            image, anchor = make(k)
            name = f'fx-{kind}-{k}'
            frames[name] = (image, anchor)
            anims['fx'][kind].append(name)
    for kind in NEW_CROWD:
        anims['crowd'][kind] = []
        for pose in ('idle0', 'idle1', 'cheer0', 'cheer1', 'gasp'):
            name = f'crowd-{kind}-{pose}'
            frames[name] = fan_variant(kind, pose)
            anims['crowd'][kind].append(name)
    return frames, anims, points


def sheet(frames, names, scale=3, cols=10, background=(44, 74, 112)):
    """A contact sheet of some frames (to LOOK at; not a scene file)."""
    cell = max(max(frames[n][0].size) for n in names) + 4
    rows = (len(names) + cols - 1) // cols
    out = Image.new('RGBA', (cols * cell * scale, rows * cell * scale), background + (255,))
    for i, n in enumerate(names):
        img, (ax, ay) = frames[n]
        big = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
        x0 = (i % cols) * cell * scale + (cell // 2 - ax) * scale
        y0 = (i // cols) * cell * scale + (cell - 6 - ay) * scale
        out.alpha_composite(big, (x0, y0))
    return out.convert('RGB')
