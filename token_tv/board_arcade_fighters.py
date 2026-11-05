"""Codex and Claude as arcade fighters for the VERSUS page, drawn on the board's own pixel grid.

Tony, 2026-11-03: "quiero que me mejores las animaciones de los luchadores tipo street fighter. que sean mas como el
videojuego ... y quiero que me mejores los personajes tambien. quiero que sean como los de claude y codex pero
inspirados en los de SF2", and, as always, "lo que quiero es que se vea limpio y bonito, no cargado y confuso".

What is borrowed is the craft of 1990s arcade fighters, which belongs to nobody: big readable silhouettes, one dark
outline per part, three or four flat tones lit from the upper left, a bent stance with weight, anticipation, contact,
hit-stop and recovery. Nothing is traced, sampled or copied from any game, and neither fighter wears a costume, headband
or pose of a named character: Codex stays the round terminal-cloud machine with its lightning bolt and Claude the orange
octopus, as designed in this repository.

The board's engine shows every sprite pixel as 2 x 2 screen pixels, so the fighters are drawn directly on that grid
("logical" pixels, a 160 x 120 canvas) instead of being drawn bigger and squeezed down. They are built from a few shaded
ellipsoids and tubes (`Surface`), quantised to four tones, with a hand-placed face, bolt and suckers on top.

One exchange (a punch that is blocked, then a whip that is blocked) lasts 12 of the 32 beats of the loop; the rest is
breathing. The engine's rule that sprites cannot overlap is met by cutting every beat's picture into three boxes: Codex's
body, Claude's body and a middle box that holds the hands, the whip and the burst. Each fighter has at most seven distinct
body pictures, the middle box eight, and a longer reach is a longer drawing, never a bigger box.
"""
import math
from functools import lru_cache

from PIL import Image

K = 2                                           # screen pixels per logical pixel
LW, LH = 160, 120                               # the logical canvas
CODEX_BOX = (14, 54, 64, 102)                   # x0, y0, x1, y1 in logical pixels: a sprite and its restoration box
CLAUDE_BOX = (94, 54, 142, 102)
MIDDLE_BOX = (64, 69, 94, 92)                   # hands, whip and burst of an exchange
CONTACT = (79, 80)                              # where fist and tentacle meet
STEP_MS = 120                                   # one beat: three of the engine's 40 ms ticks, so it never jitters


def rgb(text):
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


# ---- palettes: dark, shade, base, light --------------------------------------------------------------------------
SHELL = [rgb(c) for c in ('#2b3678', '#4b5dc4', '#8699f6', '#d0dbff')]
GLOVE = [rgb(c) for c in ('#183a96', '#2d66de', '#57a2ff', '#bde0ff')]
STEEL = [rgb(c) for c in ('#59639a', '#909dd4', '#c6cff4', '#f6f8ff')]
BOOT = [rgb(c) for c in ('#1b2052', '#33408f', '#5669d8', '#a2b3ff')]
BOLT = [rgb(c) for c in ('#d77a00', '#f5a712', '#ffcf3a', '#fff29a')]
ORANGE = [rgb(c) for c in ('#a9442e', '#d4683a', '#f28d4f', '#ffbd7e')]
BURST = [rgb(c) for c in ('#ff8a2b', '#ffc233', '#fff08a', '#ffffff')]
INK, INK_STEEL, INK_BOLT, INK_ORANGE, INK_BURST = (rgb(c) for c in ('#131740', '#363e7e', '#4b2f5a', '#47202f', '#3b1348'))
SHADOW = rgb('#38223a')                         # darker than every plank: browns merge on the real panel
GLASS, GLASS_HI, GLARE = rgb('#0b1233'), rgb('#141d4d'), rgb('#2b3c90')
PROMPT, BEZEL_HI, BEZEL_LO = rgb('#b9faff'), rgb('#e2e9ff'), rgb('#3d4aa0')
EYE, GLINT, BROW, MOUTH = rgb('#1c1626'), rgb('#fff8ea'), rgb('#6a2530'), rgb('#6a2a36')
CREAM, SUCKER, TONGUE = rgb('#fff0cf'), rgb('#ffe3b8'), rgb('#ff8d8d')

LIGHT = (-0.52, -0.66, 0.54)                    # from the upper left and the viewer: one light for everything
_length = math.sqrt(sum(v * v for v in LIGHT))
LIGHT = tuple(v / _length for v in LIGHT)


# ---- a tiny shaded-pixel toolkit ---------------------------------------------------------------------------------
class Grid:
    """Logical pixels; None is transparent."""

    def __init__(self, w, h, ox=0, oy=0):
        self.w, self.h, self.ox, self.oy = w, h, ox, oy              # (ox, oy): where the drawing's (0, 0) falls
        self.p = [[None] * w for _ in range(h)]

    def get(self, x, y):
        x, y = x + self.ox, y + self.oy
        return self.p[y][x] if 0 <= x < self.w and 0 <= y < self.h else None

    def put(self, x, y, colour):
        x, y = x + self.ox, y + self.oy
        if 0 <= x < self.w and 0 <= y < self.h:
            self.p[y][x] = colour

    def paint(self, pixels):
        for (x, y), colour in pixels.items():
            self.put(x, y, colour)

    def merge(self, other):
        for y, row in enumerate(other.p):
            for x, colour in enumerate(row):
                if colour is not None:
                    self.p[y][x] = colour

    def image(self, box=None):
        x0, y0, x1, y1 = box or (-self.ox, -self.oy, self.w - self.ox, self.h - self.oy)
        image = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
        for y in range(y0, y1):
            for x in range(x0, x1):
                colour = self.get(x, y)
                if colour:
                    image.putpixel((x - x0, y - y0), colour + (255,))
        return image


class Surface:
    """Ellipsoids and tubes seen from the front; every pixel keeps the normal of the frontmost shape."""

    def __init__(self):
        self.px = {}

    def _put(self, x, y, z, normal, tag):
        old = self.px.get((x, y))
        if old is None or z > old[0]:
            self.px[(x, y)] = (z, normal, tag)

    def ellipsoid(self, cx, cy, rx, ry, rz=None, tag=0, bias=1.0):
        rz = rz or min(rx, ry)
        for y in range(int(math.floor(cy - ry)), int(math.ceil(cy + ry)) + 1):
            for x in range(int(math.floor(cx - rx)), int(math.ceil(cx + rx)) + 1):
                u, v = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                r2 = u * u + v * v
                if r2 <= 1.0:
                    w = math.sqrt(1.0 - r2)
                    n = (u, v, w ** bias)
                    m = math.sqrt(sum(t * t for t in n)) or 1
                    self._put(x, y, rz * w, tuple(t / m for t in n), tag)

    def tube(self, pts, radii, tag=0):
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            r0, r1 = radii[i], radii[i + 1]
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy or 1e-9
            reach = max(r0, r1)
            for y in range(int(math.floor(min(ay, by) - reach)), int(math.ceil(max(ay, by) + reach)) + 1):
                for x in range(int(math.floor(min(ax, bx) - reach)), int(math.ceil(max(ax, bx) + reach)) + 1):
                    px, py = x + 0.5, y + 0.5
                    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
                    ox, oy = px - (ax + t * dx), py - (ay + t * dy)
                    r = r0 + (r1 - r0) * t
                    d = math.hypot(ox, oy)
                    if d <= r:
                        w = math.sqrt(max(0.0, 1 - (d / r) ** 2))
                        n = (ox / r, oy / r, w)
                        m = math.sqrt(sum(q * q for q in n)) or 1
                        self._put(x, y, r * w, tuple(q / m for q in n), tag)

    def shade(self, th=(0.86, 0.50, 0.20)):
        """Tone index 0-3 per pixel. A lobe in front of another darkens the one behind along their meeting line."""
        tones = {}
        for xy, (z, n, tag) in self.px.items():
            i = n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2]
            tones[xy] = 3 if i >= th[0] else 2 if i >= th[1] else 1 if i >= th[2] else 0
        for (x, y), (z, n, tag) in self.px.items():
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                other = self.px.get((x + dx, y + dy))
                if other is not None and other[2] != tag and other[0] > z + 0.6:
                    tones[(x, y)] = max(0, tones[(x, y)] - 1)
                    break
        return tones


def _clean(tones):
    """A speck whose neighbours mostly agree on another tone adopts it: tight clusters, no noise."""
    out = dict(tones)
    for (x, y), k in tones.items():
        votes, same = {}, 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = tones.get((x + dx, y + dy)) if dx or dy else None
                if q is not None:
                    same += q == k
                    votes[q] = votes.get(q, 0) + 1
        if same <= 1 and votes:
            best = max(votes, key=votes.get)
            if votes[best] >= 4:
                out[(x, y)] = best
    return out


def _outline(mask, colour):
    ring = {}
    for x, y in mask:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in mask:
                ring[(x + dx, y + dy)] = colour
    return ring


def _part(grid, surface, ramp, ink=INK, th=(0.86, 0.50, 0.20)):
    pixels = {xy: ramp[k] for xy, k in _clean(surface.shade(th)).items()}
    grid.paint(_outline(set(pixels), ink))
    grid.paint(pixels)
    return pixels


def _flat_ellipse(grid, cx, cy, rx, ry, colour):
    for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
        for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
            if ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1:
                grid.put(x, y, colour)


def _art(grid, x0, y0, rows, key):
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch in key:
                grid.put(x0 + i, y0 + j, key[ch])


def _spline(pts, n=8):
    """Catmull-Rom curve through the points."""
    out, p = [], [pts[0]] + list(pts) + [pts[-1]]
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for k in range(n):
            t = k / n
            out.append(tuple(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t * t
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t ** 3) for j in (0, 1)))
    return out + [pts[-1]]


def _limb(grid, a, b, r0, r1, ramp, bend=0.0, ink=INK):
    """A two-bone limb from a to b; `bend` pushes the elbow aside (positive: down and to the right of a-b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    mid = ((a[0] + b[0]) / 2 - dy * bend, (a[1] + b[1]) / 2 + dx * bend)
    s = Surface()
    s.tube([a, mid, b], [r0, (r0 + r1) / 2, r1])
    return _part(grid, s, ramp, ink=ink)


# ---- Codex: a sturdy machine -------------------------------------------------------------------------------------
BOLT_ART = ('.....OOOO.', '....OYYYYO', '...OYYYYO.', '..OYYYYO..', '.OYYYYYYO.', '.OHHYYYYYO',
            '..OOOYYYO.', '....OYYO..', '...OYYO...', '..OYYO....', '..OYO.....', '..OO......')
CHEVRON = ('##...', '.##..', '..##.', '...##', '..##.', '.##..', '##...')


def _bolt(grid, x, y):
    for j, row in enumerate(BOLT_ART):
        for i, ch in enumerate(row):
            colour = {'O': INK_BOLT, 'Y': BOLT[2], 'H': BOLT[3]}.get(ch)
            if colour:
                grid.put(x + i, y + j, colour)
        xs = [i for i, ch in enumerate(row) if ch == 'Y']
        if xs and 0 < j < 11:
            grid.put(x + max(xs), y + j, BOLT[1])


SCREEN_W, SCREEN_H = 22, 15


def _screen(grid, x, y, face):
    """The terminal that is Codex's face (22 x 15): the prompt is its expression."""
    w, h = SCREEN_W, SCREEN_H
    for j in range(h):
        for i in range(w):
            if i in (0, w - 1) and j in (0, h - 1):
                continue
            colour = GLASS_HI if j == 1 else GLASS
            if i in (0, w - 1) or j in (0, h - 1):
                colour = BEZEL_HI if (j == 0 or i == 0) else BEZEL_LO
            grid.put(x + i, y + j, colour)
    for i, j in ((3, 2), (4, 2), (3, 3), (5, 2)):
        grid.put(x + i, y + j, GLARE)
    if face == 'dizzy':                                                   # x_x
        for px, py in ((5, 4), (6, 5), (7, 6), (7, 4), (5, 6), (14, 4), (15, 5), (16, 6), (16, 4), (14, 6)):
            grid.put(x + px + 1, y + py + 2, PROMPT)
        for i in range(8, 13):
            grid.put(x + i, y + 11, PROMPT)
        return
    _art(grid, x + 4, y + 4, CHEVRON, {'#': PROMPT})
    if face in ('idle', 'block'):                                         # >_
        for i in range(10, 16):
            grid.put(x + i, y + 10, PROMPT)
            grid.put(x + i, y + 11, PROMPT)
    elif face == 'effort':                                                # >>
        _art(grid, x + 10, y + 4, CHEVRON, {'#': PROMPT})
    elif face == 'strike':                                                # >!
        for j in range(7):
            if j != 5:
                grid.put(x + 13, y + 4 + j, PROMPT)
                grid.put(x + 14, y + 4 + j, PROMPT)


def _glove(grid, cx, cy, cuff_dx=-4.4, cuff_dy=2.2):
    s = Surface()
    s.ellipsoid(cx, cy, 5.9, 5.5, 5.3)
    _part(grid, s, GLOVE)
    cuff = Surface()
    cuff.ellipsoid(cx + cuff_dx, cy + cuff_dy, 1.5, 3.2, 3)
    _part(grid, cuff, STEEL, ink=INK_STEEL)


def _codex(g, ox, oy, rise=0, lean=0, sag=0, shear=0.0, lead=(44, 20), rear=(7, 31), face='idle', feet=(10, 34),
           reach=None, lead_bend=0.12):
    """Codex faces right. (ox, oy) is the top-left of its 50 x 48 box. `reach` is the x of a straight punching glove.
    The terminal is its face and nothing ever crosses it (Tony, 2026-11-03: "tiene el brazo en medio de la cara"): the lead arm
    leaves from BEHIND the body and the fist is held out beside the shell, well clear of the screen (his second note: "demasiado
    superpuesto encima de la cara, no se ve natural")."""
    top = rise + sag
    cx, cy = ox + 21.5 + lean, oy + 21.5 + top
    _flat_ellipse(g, ox + 22 + lean * 0.4, oy + 45.4, 19.5, 2.4, SHADOW)
    _limb(g, (cx - 12, cy + 4), (ox + rear[0] + 3, oy + rear[1] - 1), 3.0, 2.8, SHELL, bend=-0.15)       # rear arm
    _glove(g, ox + rear[0], oy + rear[1], cuff_dx=3.6, cuff_dy=-2.2)
    for foot, boot_rx, hip, bend in ((feet[0], 7.4, -7.5, -0.10), (feet[1], 7.8, 7.5, 0.10)):         # sturdy legs
        _limb(g, (cx + hip * 0.9, cy + 11), (ox + foot, oy + 40.5), 4.6, 4.0, SHELL, bend=bend)
        s = Surface()
        s.ellipsoid(ox + foot - 0.5 + (1.5 if hip > 0 else 0), oy + 42.5, boot_rx, 3.7, 3.5)
        _part(g, s, BOOT)
    shoulder = (cx + 10, cy + 4)

    if reach is not None:                          # a straight piston: its centre line never depends on its length
        _limb(g, shoulder, (ox + reach - 3, shoulder[1]), 3.3, 3.3, SHELL)
    else:
        _limb(g, shoulder, (ox + lead[0] - 3, oy + lead[1] + 3), 3.3, 3.1, SHELL, bend=lead_bend)
    s = Surface()                                                                             # the cloud shell
    s.ellipsoid(cx, cy, 16.5, 11.2, 10.5, tag=0)
    s.ellipsoid(cx - 9 + shear * 0.6, cy - 6.6, 8.2, 6.8, 9.5, tag=1)
    s.ellipsoid(cx + 1 + shear, cy - 10.2, 10, 7.8, 10.5, tag=2)
    s.ellipsoid(cx + 10 + shear * 0.8, cy - 6.6, 7.6, 6.4, 9.0, tag=3)
    _part(g, s, SHELL)
    s = Surface()
    s.ellipsoid(cx, cy + 10.2, 14.2, 2.6, 3)                                                  # steel belt
    _part(g, s, STEEL, ink=INK_STEEL)
    for dy in (0, 1):
        for dx in (-1, 0, 1):
            g.put(int(cx) + dx, int(cy + 9.5) + dy, SHELL[0])
    g.put(int(cx), int(cy + 9.5), BOLT[2])
    _screen(g, int(cx - 11.5 + shear * 0.3), int(cy - 9), face)
    _bolt(g, int(cx - 7 + shear), max(oy, int(oy + 1 + top)))
    if reach is not None:
        _glove(g, ox + reach - 1, shoulder[1] - 0.5, cuff_dx=-4.4, cuff_dy=0.7)
    else:
        _glove(g, ox + lead[0] - 1, oy + lead[1])
    return g


# ---- Claude: a springy octopus -----------------------------------------------------------------------------------
def _tentacle(g, pts, r0, r1, side=1, n=8, suckers=True):
    curve = _spline(pts, n)
    radii = [r0 + (r1 - r0) * (i / (len(curve) - 1)) for i in range(len(curve))]
    s = Surface()
    s.tube(curve, radii)
    pixels = _part(g, s, ORANGE, ink=INK_ORANGE)
    if suckers:
        _suckers(g, pixels, curve, radii, side, 3)


def _suckers(g, pixels, curve, radii, side, every):
    for i in range(2, len(curve) - 2, every):
        (x0, y0), (x1, y1) = curve[i - 1], curve[i + 1]
        dx, dy = x1 - x0, y1 - y0
        m = math.hypot(dx, dy) or 1
        if radii[i] >= 1.3:
            sx = int(curve[i][0] - dy / m * side * radii[i] * 0.45)
            sy = int(curve[i][1] + dx / m * side * radii[i] * 0.45)
            if (sx, sy) in pixels:
                g.put(sx, sy, SUCKER)


def _whip(g, root, tip_x, wave=1.2):
    """A tentacle going left from `root`. Its centre line and thickness depend only on the distance from the root, so a
    shorter whip is exactly the part of a longer one and the picture inside Claude's own box never changes."""
    rx, ry = root
    pts, radii, x = [], [], rx
    while x >= tip_x - 0.01:
        d = rx - x
        pts.append((x, ry + wave * math.sin(d * 0.33)))
        radii.append(max(1.3, min(3.3 - 0.025 * d, 1.3 + (x - tip_x) * 0.55)))
        x -= 0.5
    s = Surface()
    s.tube(pts, radii)
    _suckers(g, _part(g, s, ORANGE, ink=INK_ORANGE), pts, radii, 1, 5)


def _eyes(g, cx, cy, eyes):
    for k, ex in enumerate((int(cx - 10), int(cx + 2))):
        ey = int(cy - 4)
        if eyes == 'open':
            for j in range(7):
                for i in range(4 if 0 < j < 6 else 3):
                    g.put(ex + i, ey + j, EYE)
            for i, j in ((0, 1), (1, 1), (0, 2)):
                g.put(ex + i, ey + j, GLINT)
            for i in range(6):
                g.put(ex - 1 + i, ey - 3 + (i // 2 if k == 0 else (5 - i) // 2), BROW)
        elif eyes == 'narrow':
            for j in range(3, 7):
                for i in range(4 if j in (4, 5) else 3):
                    g.put(ex + i, ey + j, EYE)
            g.put(ex, ey + 4, GLINT)
            g.put(ex + 1, ey + 4, GLINT)
            for i in range(6):
                for dy in (0, 1):
                    g.put(ex - 1 + i, ey + dy + (i // 2 if k == 0 else (5 - i) // 2), BROW)
        else:                                                                 # shut tight: > <
            rows = ('##..', '.##.', '..##', '.##.', '##..') if k == 0 else ('..##', '.##.', '##..', '.##.', '..##')
            _art(g, ex, ey + 1, rows, {'#': EYE})


def _mouth(g, cx, cy, mouth):
    x0 = int(cx - 8)
    if mouth == 'smile':
        for i in range(7):
            g.put(x0 + i, int(cy + 6), MOUTH)
        for i in range(1, 6):
            g.put(x0 + i, int(cy + 7), MOUTH)
    elif mouth == 'grit':
        for i in range(8):
            g.put(x0 + i - 1, int(cy + 6), MOUTH)
            g.put(x0 + i - 1, int(cy + 8), MOUTH)
            g.put(x0 + i - 1, int(cy + 7), CREAM if i % 2 == 0 else MOUTH)
    else:                                                                     # a shout
        for j in range(4):
            for i in range(5 if j in (1, 2) else 3):
                g.put(x0 + 1 + i - (1 if j in (1, 2) else 0), int(cy + 5) + j, MOUTH)
        g.put(x0 + 2, int(cy + 7), TONGUE)
        g.put(x0 + 3, int(cy + 7), TONGUE)


def _claude(g, ox, oy, rise=0, lean=0, splay=0.0, eyes='open', mouth='smile', lead=None, rear=None, whip=None):
    """Claude faces left: its left arm is behind its body, its right arm in front in every pose."""
    ox += 1
    cx, cy = ox + 23 + lean, oy + 17 + rise
    _flat_ellipse(g, ox + 23 + lean * 0.4, oy + 45.4, 21, 2.4, SHADOW)
    legs = (((4, 41.5), (1.5, 40.5), (1.5, 37.5), -1), ((16, 42), (13, 44), (10, 43), -1),
            ((30, 42), (33, 44), (36, 43), 1), ((41, 41), (44, 40), (44, 37), 1))
    bases = ((-10, 11), (-4, 12), (4, 12), (10, 11))
    thick = ((3.4, 1.4), (3.2, 1.3), (3.2, 1.3), (3.4, 1.4))
    for i in (3, 0, 2, 1):                                           # four planted tentacles, outer ones first
        foot, c1, c2, out = legs[i]
        base, tip = (cx + bases[i][0], cy + bases[i][1]), (ox + foot[0], oy + foot[1])
        mid = ((base[0] + tip[0]) / 2 + out * (1.2 + splay), (base[1] + tip[1]) / 2)
        _tentacle(g, [base, mid, tip, (ox + c1[0], oy + c1[1]), (ox + c2[0], oy + c2[1])], *thick[i], side=out)
    def lead_arm():
        if whip is not None:
            _whip(g, (cx - 13, cy + 9), whip)
        else:
            pts = lead or ((-13, 8), (-19, 6), (-21, 0), (-18, -4))
            _tentacle(g, [(cx + x, cy + y) for x, y in pts], 3.4, 1.5, side=-1)

    lead_arm()                                                        # screen-left arm passes behind the body
    s = Surface()
    s.ellipsoid(cx, cy, 16, 12.5, 10, tag=0, bias=0.8)
    s.ellipsoid(cx - 11, cy + 3.5, 6.0, 6.5, 6.5, tag=1)
    s.ellipsoid(cx + 11, cy + 3.5, 6.0, 6.5, 6.5, tag=2)
    _part(g, s, ORANGE, ink=INK_ORANGE, th=(0.86, 0.52, 0.22))
    _tentacle(g, [(cx + x, cy + y) for x, y in (rear or ((13, 7), (18, 6), (20, 0), (17, -4)))], 3.0, 1.4)
    _eyes(g, cx, cy, eyes)
    for i, j in ((2, 0), (2, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (2, 3), (2, 4), (1, 1), (3, 1), (1, 3), (3, 3)):
        g.put(int(cx - 3) + i, int(cy - 10) + j, CREAM)               # Claude's own starburst on the forehead
    _mouth(g, cx, cy, mouth)
    return g


def _burst(g, cx, cy, size):
    """A generic impact star: 0 flash, 1 big, 2 fading sparks."""
    if size == 2:
        for dx, dy, c in ((-8, -5, 2), (7, -6, 2), (-6, 6, 1), (9, 4, 1), (0, -9, 2), (-11, 0, 1), (11, -1, 2), (3, 8, 1)):
            g.put(cx + dx, cy + dy, BURST[c])
            g.put(cx + dx + 1, cy + dy, BURST[c])
        return
    big, small, spikes = (10, 4.2, 8) if size == 1 else (7, 3.0, 8)
    pixels = {}
    for y in range(int(cy - big) - 2, int(cy + big) + 3):
        for x in range(int(cx - big) - 2, int(cx + big) + 3):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            rad = small + (big - small) * max(0.0, math.cos(spikes / 2 * (math.atan2(dy, dx) - 0.25))) ** 2.2
            d = math.hypot(dx, dy)
            if d <= rad:
                t = d / rad
                pixels[(x, y)] = BURST[3] if t < 0.38 else BURST[2] if t < 0.62 else BURST[1] if t < 0.85 else BURST[0]
    g.paint(_outline(set(pixels), INK_BURST))
    g.paint(pixels)


# ---- the poses (box coordinates; see the module note for what each is for) ---------------------------------------
CODEX_POSES = {
    'C0': dict(),                                                                        # guard
    'C1': dict(rise=-1, lead=(44, 19), rear=(7, 30), face='cursor'),                    # breathes in; the cursor blinks
    'C2': dict(sag=2, lean=-2, shear=-1.0, lead=(41, 33), face='effort', feet=(9, 33),
               lead_bend=-0.15),                                                         # winds up: crouch, fist cocked at the hip
    'C3a': dict(sag=1, lean=2, shear=0.5, face='strike', feet=(9, 34), reach=54, rear=(8, 28)),    # the punch leaves
    'C3': dict(sag=1, lean=3, shear=1.0, face='strike', feet=(9, 34), reach=60, rear=(8, 28)),     # and lands
    'C4': dict(sag=1, lean=1, face='block', feet=(10, 34), reach=59, rear=(8, 28)),                 # braces against the whip
}
CLAUDE_POSES = {
    'K0': dict(),                                                                        # guard
    'K2': dict(rise=2, splay=1.6),                                                       # squashes: bounce and brace
    'K3a': dict(rise=2, lean=1, splay=1.8, eyes='narrow', mouth='grit',
                lead=[(-12, 9), (-18, 4), (-18, -5), (-10, -13)]),                       # the whip starts to rise
    'K3': dict(rise=3, lean=2, splay=2.0, eyes='narrow', mouth='grit',
               lead=[(-12, 9), (-19, 3), (-17, -7), (-7, -15), (4, -16), (11, -12)],
               rear=[(13, 7), (17, 8), (19, 3), (16, -1)]),                              # whip overhead
    'K4a': dict(rise=1, lean=-3, splay=0.8, eyes='narrow', mouth='grit', whip=89.5,
                rear=[(13, 7), (18, 8), (20, 14), (17, 18)]),                            # the whip leaves
    'K4': dict(rise=1, lean=-3, splay=0.8, eyes='narrow', mouth='grit', whip=80.0,
               rear=[(13, 7), (18, 8), (20, 14), (17, 18)]),                             # and lands
    'K5': dict(rise=2, lean=-1, splay=1.6, eyes='shut', mouth='grit',
               lead=[(-13, 9), (-22, 10), (-30, 9), (-35, 4), (-34, -1)],
               rear=[(13, 7), (18, 3), (17, -6), (10, -11)]),                            # a tentacle catches the fist
    'K6': dict(rise=-1, lean=2, splay=0.4, eyes='shut', mouth='open',
               lead=[(-13, 8), (-18, 3), (-21, -4), (-16, -9)],
               rear=[(13, 7), (17, 9), (19, 3), (16, -2)]),                              # pushed back
}


@lru_cache(maxsize=None)
def _pose(who, name):
    g = Grid(LW, LH)
    if who == 'codex':
        _codex(g, CODEX_BOX[0], CODEX_BOX[1], **CODEX_POSES[name])
    else:
        _claude(g, CLAUDE_BOX[0], CLAUDE_BOX[1], **CLAUDE_POSES[name])
    return g


@lru_cache(maxsize=None)
def _scene(codex_pose, claude_pose, burst):
    g = Grid(LW, LH)
    g.merge(_pose('codex', codex_pose))
    g.merge(_pose('claude', claude_pose))
    if burst is not None:
        _burst(g, CONTACT[0], CONTACT[1], burst)
    return g


# ---- the loop: 32 beats of STEP_MS -------------------------------------------------------------------------------
BREATH = ('C0', 'C0', 'C0', 'C1', 'C1', 'C1', 'C0', 'C0')        # Codex: slow, heavy
BOUNCE = ('K0', 'K0', 'K2', 'K2', 'K0', 'K0', 'K2', 'K0')        # Claude: quick, springy
# beat 8-19: Codex punches and Claude catches it with a tentacle; Claude whips and Codex braces. (codex, claude, burst, dx)
EXCHANGE = (('C2', 'K2', None, 0), ('C3a', 'K2', None, 0), ('C3', 'K5', 0, 0), ('C3', 'K5', 1, 0),
            ('C1', 'K6', 2, 6), ('C0', 'K2', None, 3), ('C1', 'K3a', None, 0), ('C1', 'K3', None, 0),
            ('C1', 'K4a', None, 0), ('C4', 'K4', 0, 0), ('C4', 'K4', 1, 0), ('C1', 'K2', 2, 0))


def _duel():
    steps = [(BREATH[i], BOUNCE[(i + 4) % 8], None, 0) for i in range(8)]
    steps += list(EXCHANGE)
    steps += [(BREATH[i % 8], BOUNCE[(i + 4) % 8], None, 0) for i in range(12)]
    return steps


def _idle(who):
    return [((BREATH[i], 'K0', None, 0) if who == 'codex' else ('C0', BOUNCE[i], None, 0)) for i in range(8)]


def _slice_program(steps, boxes):
    """Cut every beat into the boxes; identical cuts share one frame. Returns {name: (frames, script)}."""
    result = {name: ([], [], {}) for name in boxes}
    for codex_pose, claude_pose, burst, dx in steps:
        g = _scene(codex_pose, claude_pose, burst)
        for name, box in boxes.items():
            frames, script, seen = result[name]
            image = g.image(box)
            key = image.tobytes()
            if key not in seen:
                seen[key] = len(frames)
                frames.append(image)
            script.append((seen[key], dx if name == 'claude' else 0, 0))
    return {name: (frames, script) for name, (frames, script, _) in result.items()}


@lru_cache(maxsize=None)
def _programs():
    duel = _slice_program(_duel(), {'codex': CODEX_BOX, 'claude': CLAUDE_BOX, 'middle': MIDDLE_BOX})
    codex = _slice_program(_idle('codex'), {'codex': CODEX_BOX})['codex']
    claude = _slice_program(_idle('claude'), {'claude': CLAUDE_BOX})['claude']
    return duel, codex, claude


def _sprite(box, frames, script, step_ms):
    return {'x': box[0] * K, 'y': box[1] * K, 'frames': [f.copy() for f in frames], 'script': list(script),
            'step_ms': step_ms}


def _nothing(box, step_ms):
    return {'x': box[0] * K, 'y': box[1] * K, 'frames': [Image.new('RGBA', (1, 1), (0, 0, 0, 0))],
            'script': [(0, 0, 0)], 'step_ms': step_ms}


def actor_sprites(codex_down, claude_down, frames=8):
    """The fighters' resident sprites. Boards with eight frames get Codex, Claude and the middle box (a duel while both
    stand; breathing alone for a survivor; a fixed 1 x 1 nothing for a knocked-out side, whose body is drawn into the
    page). Older boards get Codex and Claude breathing only, with the four poses they can hold."""
    duel, codex_idle, claude_idle = _programs()
    if frames >= 8:
        step_ms = STEP_MS
        if not codex_down and not claude_down:
            return [_sprite(CODEX_BOX, *duel['codex'], step_ms), _sprite(CLAUDE_BOX, *duel['claude'], step_ms),
                    _sprite(MIDDLE_BOX, *duel['middle'], step_ms)]
        return [_nothing(CODEX_BOX, step_ms) if codex_down else _sprite(CODEX_BOX, *codex_idle, step_ms),
                _nothing(CLAUDE_BOX, step_ms) if claude_down else _sprite(CLAUDE_BOX, *claude_idle, step_ms),
                _nothing(MIDDLE_BOX, step_ms)]
    step_ms = 2 * STEP_MS
    return [_nothing(CODEX_BOX, step_ms) if codex_down else _sprite(CODEX_BOX, *codex_idle, step_ms),
            _nothing(CLAUDE_BOX, step_ms) if claude_down else _sprite(CLAUDE_BOX, *claude_idle, step_ms)]


# ---- knocked out: one fixed picture on the floor, drawn into the page (Tony: KO only on a fresh confirmed weekly zero) ----
FALLEN_SIZE = (66, 30)


def _stars(g, points):
    for x, y in points:
        for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
            g.put(x + dx, y + dy, BOLT[2] if dx == dy == 0 else BOLT[1])
        g.put(x, y, BOLT[3])


def _fallen_codex():
    """Flat on its back: the screen dizzy, the gloves flung out and both boots in the air."""
    g = Grid(*FALLEN_SIZE, ox=4, oy=2)
    _flat_ellipse(g, 30, 24.4, 28, 2.4, SHADOW)
    for a, b, ramp in (((9, 15), (3.5, 20), SHELL), ((40, 17), (47, 10), SHELL), ((41, 19.5), (51, 19), SHELL)):
        _limb(g, a, b, 3.4, 3.0, ramp)
    s = Surface()
    s.ellipsoid(3.5, 21, 5.4, 4.8, 4.8)
    _part(g, s, GLOVE)
    for cx, cy, rx, ry in ((49.5, 7.5, 3.4, 5.2), (53, 19, 3.6, 4.2)):
        s = Surface()
        s.ellipsoid(cx, cy, rx, ry, 3.4)
        _part(g, s, BOOT)
    s = Surface()
    s.ellipsoid(24, 17.5, 16.5, 6.8, 7, tag=0)
    s.ellipsoid(12.5, 15.5, 8.2, 5.8, 7, tag=1)
    s.ellipsoid(22.5, 12.5, 10, 5.4, 7.5, tag=2)
    s.ellipsoid(33.5, 15, 7.4, 5.2, 6.5, tag=3)
    _part(g, s, SHELL)
    s = Surface()
    s.ellipsoid(40, 18, 2.6, 6.3, 3)
    _part(g, s, STEEL, ink=INK_STEEL)
    for j in range(8):                                                 # the terminal, seen from the side
        for i in range(23):
            if i in (0, 22) and j in (0, 7):
                continue
            edge = i in (0, 22) or j in (0, 7)
            g.put(11 + i, 11 + j, (BEZEL_HI if j == 0 or i == 0 else BEZEL_LO) if edge else GLASS)
    for x0 in (16, 25):                                                # x x
        for dx, dy in ((0, 0), (2, 0), (1, 1), (0, 2), (2, 2)):
            g.put(x0 + dx, 13 + dy, PROMPT)
    for i in range(20, 25):
        g.put(i, 18, PROMPT)
    for j, row in enumerate(BOLT_ART):                                 # the crest has come off and lies across the shell
        for i, ch in enumerate(row):
            colour = {'O': INK_BOLT, 'Y': BOLT[2], 'H': BOLT[3]}.get(ch)
            if colour:
                g.put(15 + len(BOLT_ART) - 1 - j, 1 + i, colour)
    _stars(g, ((6, 4), (30, 2), (45, 3)))
    return g


def _fallen_claude():
    """Flat out with its tongue out and every tentacle limp."""
    g = Grid(*FALLEN_SIZE, ox=4, oy=2)
    _flat_ellipse(g, 30, 24.4, 28, 2.4, SHADOW)
    for pts, side in (([(17, 20), (11, 22), (5, 22), (1.5, 19.5)], -1), ([(21, 21.5), (16, 24), (9, 24.5), (5, 23)], -1),
                      ([(39, 20), (46, 22), (52, 22), (56.5, 19.5)], 1), ([(35, 21.5), (42, 24), (49, 24.5), (54, 23)], 1)):
        _tentacle(g, pts, 3.2, 1.3, side=side)
    s = Surface()
    s.ellipsoid(29, 15.5, 16.5, 8.8, 8, tag=0, bias=0.8)
    s.ellipsoid(17.5, 18.5, 6.2, 5.6, 6, tag=1)
    s.ellipsoid(40.5, 18.5, 6.2, 5.6, 6, tag=2)
    _part(g, s, ORANGE, ink=INK_ORANGE, th=(0.86, 0.52, 0.22))
    for x0 in (20, 33):                                                # x x
        for dx, dy in ((0, 0), (3, 0), (1, 1), (2, 1), (1, 2), (2, 2), (0, 3), (3, 3)):
            g.put(x0 + dx, 12 + dy, EYE)
    for i in range(5):                                                 # flat brows
        g.put(19 + i, 10, BROW)
        g.put(33 + i, 10, BROW)
    for i in range(7):
        g.put(24 + i, 20, MOUTH)
    for i in (26, 27, 28):
        g.put(i, 21, TONGUE)
        g.put(i, 22, TONGUE)
    for i, j in ((2, 0), (2, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (2, 3), (2, 4), (1, 1), (3, 1), (1, 3), (3, 3)):
        g.put(27 + i, 5 + j, CREAM)
    _stars(g, ((14, 4), (31, 1), (46, 4)))
    return g


@lru_cache(maxsize=None)
def _fallen_grid(provider):
    if provider == 'codex':
        return _fallen_codex()
    if provider == 'claude':
        return _fallen_claude()
    raise ValueError('unknown fighter')


def fallen(provider):
    """The knocked-out fighter as an RGBA image at logical size (the page shows each pixel 2 x 2)."""
    return _fallen_grid(provider).image()


# ---- the HUD portraits: the same two faces on a 14 x 12 grid -----------------------------------------------------
@lru_cache(maxsize=None)
def _portrait_grid(provider):
    g = Grid(14, 12)
    if provider == 'codex':
        s = Surface()                                                   # the cloud, a little lower to leave the bolt room
        s.ellipsoid(7, 8.2, 6.5, 3.8, 5)
        s.ellipsoid(3.6, 6.6, 3.0, 2.6, 4, tag=1)
        s.ellipsoid(8.0, 5.7, 3.8, 3.0, 4.2, tag=2)
        s.ellipsoid(11.0, 7.0, 2.6, 2.3, 3.6, tag=3)
        _part(g, s, SHELL)
        for j in range(5):                                              # the terminal: bezel, glass, prompt
            for i in range(10):
                if i in (0, 9) and j in (0, 4):
                    continue
                edge = i in (0, 9) or j in (0, 4)
                g.put(2 + i, 6 + j, SHELL[1] if edge else GLASS)
        for xy in ((4, 7), (5, 8), (4, 9), (7, 9), (8, 9), (9, 9)):      # > and _
            g.put(*xy, PROMPT)
        for xy, tone in (((7, 0), 3), ((6, 1), 3), ((7, 1), 2), ((5, 2), 2), ((6, 2), 2), ((7, 2), 2), ((6, 3), 2), ((5, 4), 1)):
            g.put(*xy, BOLT[tone])                                      # the bolt on the crown
    elif provider == 'claude':
        for x in (2, 5, 8, 11):
            _tentacle(g, [(x + 0.5, 9), (x + (-1 if x < 7 else 1), 11)], 1.5, 1.0, suckers=False)
        s = Surface()
        s.ellipsoid(7, 6, 6.4, 5.2, 5, bias=0.8)
        s.ellipsoid(2.4, 8, 2.2, 2.4, 3, tag=1)
        s.ellipsoid(11.6, 8, 2.2, 2.4, 3, tag=2)
        _part(g, s, ORANGE, ink=INK_ORANGE, th=(0.86, 0.52, 0.22))
        for x in (3, 8):
            for j in range(3):
                g.put(x, 5 + j, EYE)
                g.put(x + 1, 5 + j, EYE)
            g.put(x, 5, GLINT)
        for i in range(4):
            g.put(2 + i, 3 + i // 2, BROW)
            g.put(11 - i, 3 + i // 2, BROW)
        for i in range(4):
            g.put(5 + i, 9, MOUTH)
        for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
            g.put(7 + dx, 1 + dy, CREAM)
    else:
        raise ValueError('unknown fighter')
    return g


def portrait(provider):
    """The face for the scoreboard, an RGBA image of 14 x 12 logical pixels."""
    return _portrait_grid(provider).image()
