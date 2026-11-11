"""Prepare the private atlas of the tablet's real-time VERSUS scene (`token_tv/tablet_web/game-fighting.js`), offline.

The scene is a small fighting game that plays itself (Tony: "bigger, smoother, more things, like a real 90s fighting game"): Codex, a sturdy blue
terminal-cloud machine whose prompt is its expression, against Claude, a springy orange octopus with a starburst on its forehead. The scene draws the
match, the stages, the life bars and the text in code; this script draws what is not worth drawing in code and writes the three files of the game contract:

    scene-fighting.png    the atlas (transparent sprites): both fighters in every pose, hit sparks, dust, projectiles, spectators, props, boats
    scene-fighting.json   {"frames": {name: [x, y, w, h]}, "anchors": {name: [ax, ay]}, "anims": {who: {move: [names]}}, ...}
    thumb-fighting.webp   240 x 160 picture for the scene picker

    nice -n 15 ionice -c 3 .venv/bin/python -B scripts/prepare_game_fighting.py --out DIR [--manifest] [--sheet FILE.png] [--private DIR]

The fighters are ORIGINAL art. They are drawn with the board's own toolkit (`token_tv/board_arcade_fighters.py`: shaded ellipsoids and tubes, four flat tones lit from
the upper left, one dark outline per part, the same palettes) at 1.6 art pixels per board pixel, as a little rig (a body that leans, rises and sags or tumbles; arms
and legs that reach to a point; a face that changes), so every pose and every in-between is a few numbers. The board's rules hold in every pose: nothing crosses
Codex's screen (its lead arm leaves from BEHIND the body and its fist is held out beside the shell); Claude's screen-left arm passes behind its body and its
screen-right arm in front. Nothing is traced or copied from any game; no ROM, no download, no external service or model.

Tony's own jungle backdrop (`~/.local/share/ai-desk-display/arcade-local/stage.png` and its four-frame ambient pieces, the board's optional private stage) is added to the
atlas as one more stage when it exists and is valid; it is private art that goes ONLY into the private atlas, never into Git, docs, tests or previews. Without it the
atlas simply has no jungle and the scene plays on its own drawn stages. `--manifest` also adds the scene to `scenes.json` in DIR through `scripts.tablet_media`.
"""
import argparse
import json
import math
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import tablet_media as media  # noqa: E402
from token_tv import board_arcade_fighters as bf  # noqa: E402

NAME = 'fighting'
S = 1.6                                   # art pixels per board pixel: Codex's box is 50 x 48 board pixels, 80 x 77 here
FLOOR = 45.4                              # the floor line inside a fighter's box, in board pixels (where the board draws the shadow)
GW, GH = 340, 190                         # the drawing canvas of one pose
GOX, GOY = 150, 160                       # where (0, 0), the centre of the floor under the fighter, falls in it
CLEAR = (0, 0, 0, 0)
BODY_HALF = {'codex': 27, 'claude': 27}   # half the width of the body in art pixels (the collision radius the scene uses)
POINTS = {}                               # {frame: [[dx, dy], ...]}: attachment points the scene needs (a rod's tip, a window), from the frame's anchor
SHADOWS = {}                              # {frame: [centre offset, half width, strength]}: the scene draws the fighter's shadow itself (it follows the light), these are its numbers

rgb = bf.rgb


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# A rig: board coordinates in, art pixels out
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

class RS(bf.Surface):
    """The board's shaded surface with a rotated ellipsoid, so a body can lean and tumble without ever rotating pixels."""

    def ellipsoid_rot(self, cx, cy, rx, ry, rz, theta=0.0, tag=0, bias=1.0):
        c, s = math.cos(theta), math.sin(theta)
        reach = max(rx, ry)
        for y in range(int(math.floor(cy - reach)), int(math.ceil(cy + reach)) + 1):
            for x in range(int(math.floor(cx - reach)), int(math.ceil(cx + reach)) + 1):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                u, v = (dx * c + dy * s) / rx, (-dx * s + dy * c) / ry
                r2 = u * u + v * v
                if r2 <= 1.0:
                    w = math.sqrt(1.0 - r2)
                    nx, ny, nz = u, v, w ** bias
                    m = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
                    nx, ny, nz = nx / m, ny / m, nz / m
                    self._put(x, y, rz * w, (nx * c - ny * s, nx * s + ny * c, nz), tag)


class Rig:
    """Maps a point of the board's box (board pixels, x to the right, y down) to the pose canvas (art pixels, the floor's centre is (0, 0)).

    `rot` (degrees, clockwise on the screen) turns everything about `pivot` (board pixels from the floor's centre), then `dx`, `dy` shift the whole body."""

    def __init__(self, ref_x, rot=0.0, dx=0.0, dy=0.0, pivot=(0.0, -24.0), flat=1.0):
        self.ref_x, self.rot, self.dx, self.dy, self.pivot, self.flat = ref_x, math.radians(rot), dx, dy, pivot, flat
        self.c, self.s = math.cos(self.rot), math.sin(self.rot)

    def pt(self, bx, by):
        x, y = bx - self.ref_x, by - FLOOR
        if self.rot:
            px, py = self.pivot
            x, y = x - px, y - py
            x, y = x * self.c - y * self.s, x * self.s + y * self.c
            x, y = x + px, y + py
        return (x + self.dx) * S, (y * self.flat + self.dy) * S

    def ellipsoid(self, surface, cx, cy, rx, ry, rz=None, tag=0, bias=1.0):
        x, y = self.pt(cx, cy)
        if self.flat != 1.0:                                                  # a body lying down is flatter: squash the axis that points up
            rx, ry = rx * (1 - (1 - self.flat) * abs(self.s)), ry * (1 - (1 - self.flat) * abs(self.c))
        surface.ellipsoid_rot(x, y, rx * S, ry * S, (rz or min(rx, ry)) * S, self.rot, tag, bias)

    def limb(self, g, a, b, r0, r1, ramp, bend=0.0, ink=bf.INK):
        """A two-bone limb from a to b (board points); `bend` pushes the elbow aside."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        mid = ((a[0] + b[0]) / 2 - dy * bend, (a[1] + b[1]) / 2 + dx * bend)
        s = RS()
        s.tube([self.pt(*a), self.pt(*mid), self.pt(*b)], [r0 * S, (r0 + r1) / 2 * S, r1 * S])
        return bf._part(g, s, ramp, ink=ink)

    def tentacle(self, g, pts, r0, r1, side=1, n=8, suckers=True, every=3):
        curve = bf._spline([self.pt(*p) for p in pts], n)
        radii = [(r0 + (r1 - r0) * (i / (len(curve) - 1))) * S for i in range(len(curve))]
        s = RS()
        s.tube(curve, radii)
        pixels = bf._part(g, s, bf.ORANGE, ink=bf.INK_ORANGE)
        if suckers:
            bf._suckers(g, pixels, curve, radii, side, every)
        return pixels


def fill_poly(g, pts, colour):
    """Fill a polygon given in the canvas's floor-centred pixels, without anti-aliasing (a pixel is in when its centre is)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = int(math.floor(min(xs))) - 1, int(math.floor(min(ys))) - 1
    x1, y1 = int(math.ceil(max(xs))) + 2, int(math.ceil(max(ys))) + 2
    mask = Image.new('L', (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).polygon([(x - x0 - 0.5, y - y0 - 0.5) for x, y in pts], fill=255)
    px = mask.load()
    for j in range(mask.height):
        for i in range(mask.width):
            if px[i, j]:
                g.put(x0 + i, y0 + j, colour)


def stroke(a, b, width):
    """The quad of a thick line from a to b (pixels)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    m = math.hypot(dx, dy) or 1
    nx, ny = -dy / m * width / 2, dx / m * width / 2
    return [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]


def paste_layer(g, image, cx, cy, degrees=0.0):
    """Paste a small drawn picture (RGBA) so its centre falls on (cx, cy) of the canvas, turned by `degrees` (clockwise) without smoothing."""
    if degrees:
        image = image.rotate(-degrees, resample=Image.Resampling.NEAREST, expand=True)
    x0, y0 = int(round(cx - image.width / 2)), int(round(cy - image.height / 2))
    px = image.load()
    for j in range(image.height):
        for i in range(image.width):
            r, gg, b, a = px[i, j]
            if a:
                g.put(x0 + i, y0 + j, (r, gg, b))


def aura(image, rings):
    """Rings of flat colour round a picture's silhouette, drawn UNDER it: [(grow in pixels, colour), ...], the widest first."""
    alpha = image.getchannel('A')
    pad = max(r for r, _ in rings) + 1
    out = Image.new('RGBA', (image.width + 2 * pad, image.height + 2 * pad), CLEAR)
    big = Image.new('L', out.size, 0)
    big.paste(alpha, (pad, pad))
    for grow, colour in rings:
        mask = big.filter(ImageFilter.MaxFilter(2 * grow + 1)).point(lambda v: 255 if v else 0)
        out.paste(Image.new('RGBA', out.size, tuple(colour) + (255,)), (0, 0), mask)
    out.alpha_composite(image, (pad, pad))
    return out, pad


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Codex: a sturdy machine (faces right)
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

def screen_face(face, glow=0.0):
    """The terminal that is Codex's face (22 x 15 board pixels, drawn at art size): the prompt is its expression."""
    w, h = round(22 * S), round(15 * S)
    im = Image.new('RGBA', (w, h), CLEAR)
    d = ImageDraw.Draw(im)
    c = 2                                                                  # the corners are cut
    d.polygon([(c, 0), (w - 1 - c, 0), (w - 1, c), (w - 1, h - 1 - c), (w - 1 - c, h - 1), (c, h - 1), (0, h - 1 - c), (0, c)], fill=bf.BEZEL_LO + (255,))
    d.polygon([(c, 0), (w - 1 - c, 0), (w - 1, c), (w - 3, c), (w - 3 - c, 2), (2 + c, 2), (2, 2 + c), (0, h - 1 - c), (0, c)], fill=bf.BEZEL_HI + (255,))
    glass = bf.GLASS if glow < 0.5 else (220, 246, 255)
    ink = bf.PROMPT if glow < 0.5 else (24, 54, 150)
    d.rectangle((3, 3, w - 4, h - 4), fill=glass + (255,))
    if glow < 0.5:
        d.rectangle((3, 3, w - 4, 4), fill=bf.GLASS_HI + (255,))
        for x, y in ((5, 5), (6, 5), (5, 6), (7, 5)):
            d.point((x, y), fill=bf.GLARE + (255,))

    def chevron(x, y0=6, size=11, thick=3.2):
        a, b, cpt = (x, y0), (x + size * 0.62, y0 + size / 2), (x, y0 + size)
        for p, q in ((a, b), (b, cpt)):
            d.polygon(stroke(p, q, thick), fill=ink + (255,))

    def cross(x, y, size):
        for p, q in (((x, y), (x + size, y + size)), ((x + size, y), (x, y + size))):
            d.polygon(stroke(p, q, 2.2), fill=ink + (255,))

    if face == 'dizzy':                                                    # x_x
        cross(7, 7, 6)
        cross(w - 14, 7, 6)
        d.rectangle((12, 17, w - 13, 18), fill=ink + (255,))
    elif face == 'hurt':                                                   # > <  squeezed shut
        chevron(8, 7, 9, 2.6)
        for p, q in (((w - 9, 7), (w - 15, 11.5)), ((w - 15, 11.5), (w - 9, 16))):
            d.polygon(stroke(p, q, 2.6), fill=ink + (255,))
        d.rectangle((15, 18, w - 16, 19), fill=ink + (255,))
    elif face == 'happy':                                                  # ^_^
        for x0 in (7, w - 17):
            d.polygon(stroke((x0, 12), (x0 + 4.5, 7), 2.8), fill=ink + (255,))
            d.polygon(stroke((x0 + 4.5, 7), (x0 + 9, 12), 2.8), fill=ink + (255,))
        d.rectangle((14, 17, w - 15, 18), fill=ink + (255,))
    else:
        chevron(7)
        if face in ('idle', 'block'):
            d.rectangle((17, 16, 26, 18), fill=ink + (255,))               # the cursor
            if face == 'block':
                d.rectangle((17, 12, 26, 13), fill=ink + (255,))
        elif face == 'effort':                                             # >>
            chevron(18)
        elif face == 'strike':                                             # >!
            d.rectangle((20, 6, 22, 14), fill=ink + (255,))
            d.rectangle((20, 17, 22, 19), fill=ink + (255,))
        elif face == 'cheer':                                              # >:D  a big open prompt
            d.rectangle((17, 15, 28, 19), fill=ink + (255,))
    return im


def bolt_image(glow=0.0):
    """The lightning bolt on Codex's crown (10 x 12 board pixels at art size), with its dark outline."""
    pts = [(4.2, 0), (9.2, 0), (6.1, 4.4), (9.8, 4.4), (2.0, 12.2), (3.9, 6.6), (0.3, 6.6)]
    w, h = round(10.6 * S) + 4, round(12.4 * S) + 4
    big = Image.new('L', (w, h), 0)
    ImageDraw.Draw(big).polygon([(2 + x * S - 0.5, 2 + y * S - 0.5) for x, y in pts], fill=255)
    px = big.load()
    inside = {(i, j) for j in range(h) for i in range(w) if px[i, j]}
    im = Image.new('RGBA', (w, h), CLEAR)
    tones = bf.BOLT
    body = tones[3] if glow > 0.5 else tones[2]
    for (i, j) in inside:
        left, right = (i - 1, j) not in inside, (i + 1, j) not in inside
        colour = tones[3] if left else tones[1] if right else body
        im.putpixel((i, j), colour + (255,))
    for (i, j) in list(inside):
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (i + di, j + dj) not in inside and 0 <= i + di < w and 0 <= j + dj < h:
                im.putpixel((i + di, j + dj), bf.INK_BOLT + (255,))
    return im


def codex(pose):
    """One pose of Codex on a canvas whose (0, 0) is the floor under its middle. Board units are those of `board_arcade_fighters._codex` (a 50 x 48 box)."""
    p = dict(rise=0.0, sag=0.0, lean=0.0, shear=0.0, lead=(44, 20), lead_bend=0.12, reach=None, rear=(7, 31), rear_bend=-0.15, feet=(10, 34), lift=(0, 0),
             face='idle', rot=0.0, dx=0.0, dy=0.0, glow=0.0, shadow=1.0, pivot=None, flat=1.0)
    p.update(pose)
    top = p['rise'] + p['sag']
    cx, cy = 21.5 + p['lean'], 21.5 + top
    pivot = p['pivot'] or (cx - 22, cy - FLOOR + 5)
    rig = Rig(22, rot=p['rot'], dx=p['dx'], dy=p['dy'], pivot=pivot, flat=p['flat'])
    g = bf.Grid(GW, GH, GOX, GOY)
    g.shadow = ((p['lean'] * 0.4 + p['dx'] * 0.5) * S, 19.5 * S * p['shadow'], p['shadow'])
    rear = p['rear']

    def glove(centre, cuff_dx, cuff_dy):
        x, y = centre
        s = RS()
        rig.ellipsoid(s, x, y, 5.9, 5.5, 5.3)
        bf._part(g, s, bf.GLOVE)
        s = RS()
        rig.ellipsoid(s, x + cuff_dx, y + cuff_dy, 1.5, 3.2, 3)
        bf._part(g, s, bf.STEEL, ink=bf.INK_STEEL)

    rig.limb(g, (cx - 12, cy + 4), (rear[0] + 3, rear[1] - 1), 3.0, 2.8, bf.SHELL, bend=p['rear_bend'])                                # rear arm
    glove(rear, 3.6, -2.2)
    legs = [(p['feet'][0], 7.4, -7.5, -0.10, p['lift'][0]), (p['feet'][1], 7.8, 7.5, 0.10, p['lift'][1])]
    legs.sort(key=lambda leg: leg[0])                                                                                                  # the rearmost leg first
    for foot, boot_rx, hip, bend, lift in legs:
        rig.limb(g, (cx + hip * 0.9, cy + 11), (foot, 40.5 + lift), 4.6, 4.0, bf.SHELL, bend=bend)
        s = RS()
        rig.ellipsoid(s, foot - 0.5 + (1.5 if hip > 0 else 0), 42.5 + lift, boot_rx, 3.7, 3.5)
        bf._part(g, s, bf.BOOT)
    shoulder = (cx + 10, cy + 4)
    if p['reach'] is not None:                                                                                                         # a straight piston
        lead_fist = (p['reach'] - 1, shoulder[1] - 0.5)
        rig.limb(g, shoulder, (p['reach'] - 3, shoulder[1]), 3.3, 3.3, bf.SHELL)
        lead_cuff = (-4.4, 0.7)
    else:
        lead_fist = (p['lead'][0] - 1, p['lead'][1])
        rig.limb(g, shoulder, (p['lead'][0] - 3, p['lead'][1] + 3), 3.3, 3.1, bf.SHELL, bend=p['lead_bend'])
        lead_cuff = (-4.4, 2.2)
    s = RS()                                                                                                                           # the cloud shell
    sh = p['shear']
    rig.ellipsoid(s, cx, cy, 16.5, 11.2, 10.5, tag=0)
    rig.ellipsoid(s, cx - 9 + sh * 0.6, cy - 6.6, 8.2, 6.8, 9.5, tag=1)
    rig.ellipsoid(s, cx + 1 + sh, cy - 10.2, 10, 7.8, 10.5, tag=2)
    rig.ellipsoid(s, cx + 10 + sh * 0.8, cy - 6.6, 7.6, 6.4, 9.0, tag=3)
    bf._part(g, s, bf.SHELL)
    s = RS()                                                                                                                           # the steel belt
    rig.ellipsoid(s, cx, cy + 10.2, 14.2, 2.6, 3)
    bf._part(g, s, bf.STEEL, ink=bf.INK_STEEL)
    bx, by = rig.pt(cx, cy + 10.2)
    fill_poly(g, [(bx - 2.2, by - 1.8), (bx + 2.2, by - 1.8), (bx + 2.2, by + 1.8), (bx - 2.2, by + 1.8)], bf.SHELL[0])
    g.put(int(round(bx)), int(round(by)), bf.BOLT[2])
    fx, fy = rig.pt(cx - 0.5 + sh * 0.3, cy - 1.5)                                                                                     # the screen, centred
    paste_layer(g, screen_face(p['face'], p['glow']), fx, fy, math.degrees(rig.rot))
    bolt = bolt_image(p['glow'])
    if p['glow'] > 0.2:
        bolt, _ = aura(bolt, [(2, bf.BOLT[0]), (1, bf.BOLT[3])])
    qx, qy = rig.pt(cx - 2 + sh, top + 7)                                                                                              # the bolt on the crown
    paste_layer(g, bolt, qx, qy, math.degrees(rig.rot))
    glove(lead_fist, *lead_cuff)                                                                                                       # the lead glove, last, beside the shell
    return g


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Claude: a springy octopus (faces left)
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

def claude_face(eyes='open', mouth='smile', star=1.0, flare=0.0):
    """Eyes, brows, the starburst and the mouth, at art size, in a square picture centred on the body's middle (`flare` stretches the star's rays)."""
    size = 72
    im = Image.new('RGBA', (size, size), CLEAR)
    d = ImageDraw.Draw(im)
    mid = size / 2

    def at(bx, by):                                                                                                                    # board offsets from the body centre
        return mid + bx * S, mid + by * S

    def blob(x0, y0, w, h, colour, round_=1.0):
        d.rounded_rectangle((x0, y0, x0 + w - 1, y0 + h - 1), radius=round_, fill=colour + (255,))

    for k, ex in enumerate((-10, 2)):
        x, y = at(ex, -4)
        ew, eh = 4 * S, 7 * S
        if eyes == 'open':
            blob(x, y, ew, eh, bf.EYE, 2.2)
            d.rectangle((x + 1, y + 2, x + 2.6, y + 4.4), fill=bf.GLINT + (255,))
            bx0, by0 = at(ex - 1, -7)
            if k == 0:
                d.polygon(stroke((bx0, by0), (bx0 + 6.2 * S, by0 + 3.2 * S), 2.6), fill=bf.BROW + (255,))
            else:
                d.polygon(stroke((bx0, by0 + 3.2 * S), (bx0 + 6.2 * S, by0), 2.6), fill=bf.BROW + (255,))
        elif eyes == 'narrow':
            blob(x, y + 3 * S, ew, 3.6 * S, bf.EYE, 1.6)
            d.rectangle((x + 1, y + 3.4 * S, x + 2.6, y + 3.4 * S + 1.4), fill=bf.GLINT + (255,))
            bx0, by0 = at(ex - 1, -4)
            if k == 0:
                d.polygon(stroke((bx0, by0), (bx0 + 6.2 * S, by0 + 3.0 * S), 3.4), fill=bf.BROW + (255,))
            else:
                d.polygon(stroke((bx0, by0 + 3.0 * S), (bx0 + 6.2 * S, by0), 3.4), fill=bf.BROW + (255,))
        elif eyes == 'blink':
            blob(x, y + eh / 2 - 1, ew, 2.4, bf.EYE, 0.8)
        elif eyes == 'happy':                                                                                                          # ^ ^
            x0, y0 = at(ex, -2)
            for a, b in (((x0, y0 + 4.6 * S), (x0 + 2 * S, y0 + 1.2 * S)), ((x0 + 2 * S, y0 + 1.2 * S), (x0 + 4 * S, y0 + 4.6 * S))):
                d.polygon(stroke(a, b, 2.8), fill=bf.EYE + (255,))
        elif eyes == 'dizzy':                                                                                                          # x x
            x0, y0 = at(ex, -3)
            for a, b in (((x0, y0), (x0 + 4 * S, y0 + 5 * S)), ((x0 + 4 * S, y0), (x0, y0 + 5 * S))):
                d.polygon(stroke(a, b, 2.4), fill=bf.EYE + (255,))
        else:                                                                                                                          # shut tight:  > <
            x0, y0 = at(ex, -2)
            if k == 0:
                pts = [(x0, y0), (x0 + 4 * S, y0 + 2.2 * S), (x0, y0 + 4.4 * S)]
            else:
                pts = [(x0 + 4 * S, y0), (x0, y0 + 2.2 * S), (x0 + 4 * S, y0 + 4.4 * S)]
            for a, b in ((pts[0], pts[1]), (pts[1], pts[2])):
                d.polygon(stroke(a, b, 2.6), fill=bf.EYE + (255,))
    sx, sy = at(0, -8.2)                                                                                                               # the starburst
    r = 5.6 * S * star
    up, side, down = r * (1 + 1.5 * flare), r * (1 + 0.7 * flare), r * (0.75 if flare else 1.0)
    pts = [(0, -up), (0.26 * r, -0.26 * r), (side, 0), (0.26 * r, 0.26 * r), (0, down), (-0.26 * r, 0.26 * r), (-side, 0), (-0.26 * r, -0.26 * r)]
    if flare:
        d.polygon([(sx + x * 1.25, sy + y * 1.25 - 1) for x, y in pts], fill=bf.BURST[1] + (255,))
    d.polygon([(sx + x, sy + y) for x, y in pts], fill=bf.CREAM + (255,))
    d.polygon([(sx + x * 0.5, sy + y * 0.5) for x, y in pts], fill=(255, 250, 235, 255))
    mx, my = at(-8, 6)
    if mouth == 'smile':
        d.polygon(stroke((mx, my), (mx + 3 * S, my + 1.6 * S), 2.2), fill=bf.MOUTH + (255,))
        d.polygon(stroke((mx + 3 * S, my + 1.6 * S), (mx + 6.4 * S, my + 1.6 * S), 2.2), fill=bf.MOUTH + (255,))
        d.polygon(stroke((mx + 6.4 * S, my + 1.6 * S), (mx + 9.4 * S, my), 2.2), fill=bf.MOUTH + (255,))
    elif mouth == 'grit':
        d.rectangle((mx, my - 0.5, mx + 8.4 * S, my + 3.2 * S), fill=bf.MOUTH + (255,))
        for tx in range(int(mx) + 1, int(mx + 8.4 * S) - 1, 3):
            d.rectangle((tx, my + 0.5, tx + 1, my + 2.2), fill=bf.CREAM + (255,))
    else:                                                                                                                              # a shout
        d.ellipse((mx + 1.2 * S, my - 1.2 * S, mx + 7.2 * S, my + 4.4 * S), fill=bf.MOUTH + (255,))
        d.ellipse((mx + 2.4 * S, my + 1.8 * S, mx + 6.0 * S, my + 4.0 * S), fill=bf.TONGUE + (255,))
    return im


def claude(pose):
    """One pose of Claude on a canvas whose (0, 0) is the floor under its middle (board units as in `board_arcade_fighters._claude`)."""
    p = dict(rise=0.0, lean=0.0, splay=0.0, eyes='open', mouth='smile', lead=None, rear=None, whip=None, wave=1.2, rot=0.0, dx=0.0, dy=0.0, glow=0.0, shadow=1.0,
             tips=None, pivot=None, star=1.0, flat=1.0, lead_r=(3.4, 1.5), flare=0.0)
    p.update(pose)
    cx, cy = 24 + p['lean'], 17 + p['rise']
    rig = Rig(24, rot=p['rot'], dx=p['dx'], dy=p['dy'], pivot=p['pivot'] or (cx - 24, cy - FLOOR + 6), flat=p['flat'])
    g = bf.Grid(GW, GH, GOX, GOY)
    g.shadow = ((p['lean'] * 0.4 + p['dx'] * 0.5) * S, 21 * S * p['shadow'], p['shadow'])
    legs = [[(4, 41.5), (1.5, 40.5), (1.5, 37.5), -1], [(16, 42), (13, 44), (10, 43), -1], [(30, 42), (33, 44), (36, 43), 1], [(41, 41), (44, 40), (44, 37), 1]]
    bases = ((-10, 11), (-4, 12), (4, 12), (10, 11))
    thick = ((3.4, 1.4), (3.2, 1.3), (3.2, 1.3), (3.4, 1.4))
    for i in (3, 0, 2, 1):                                                                                                             # four planted tentacles, outer ones first
        foot, c1, c2, out = legs[i]
        shift = p['tips'][i] if p['tips'] else (0, 0, 0)
        base = (cx + bases[i][0], cy + bases[i][1])
        tip = (1 + foot[0] + shift[0], foot[1] + shift[1])
        mid = ((base[0] + tip[0]) / 2 + out * (1.2 + p['splay']), (base[1] + tip[1]) / 2 + min(0, shift[1]) * 0.5)
        rig.tentacle(g, [base, mid, tip, (1 + c1[0] + shift[0], c1[1] + shift[1] * 0.7), (1 + c2[0] + shift[0], c2[1] + shift[1] * 0.4)], *thick[i], side=out)

    if p['whip'] is not None:                                                                                                          # the lead arm, behind the body
        rx, ry = cx - 13, cy + 9
        length = p['whip']
        pts, radii, x = [], [], rx
        while x >= rx - length - 0.01:
            d = rx - x
            pts.append(rig.pt(x, ry + p['wave'] * math.sin(d * 0.33 + 0.0)))
            radii.append(max(1.3, min(3.3 - 0.025 * d, 1.3 + (length - d) * 0.55)) * S)
            x -= 0.5
        s = RS()
        s.tube(pts, radii)
        bf._suckers(g, bf._part(g, s, bf.ORANGE, ink=bf.INK_ORANGE), pts, radii, 1, 5)
    else:
        lead = p['lead'] or ((-13, 8), (-19, 6), (-21, 0), (-18, -4))
        rig.tentacle(g, [(cx + x, cy + y) for x, y in lead], p['lead_r'][0], p['lead_r'][1], side=-1)
    s = RS()
    rig.ellipsoid(s, cx, cy, 16, 12.5, 10, tag=0, bias=0.8)
    rig.ellipsoid(s, cx - 11, cy + 3.5, 6.0, 6.5, 6.5, tag=1)
    rig.ellipsoid(s, cx + 11, cy + 3.5, 6.0, 6.5, 6.5, tag=2)
    bf._part(g, s, bf.ORANGE, ink=bf.INK_ORANGE, th=(0.86, 0.52, 0.22))
    rear = p['rear'] or ((13, 7), (18, 6), (20, 0), (17, -4))                                                                          # the rear arm, in front of the body
    rig.tentacle(g, [(cx + x, cy + y) for x, y in rear], 3.0, 1.4)
    fx, fy = rig.pt(cx, cy)
    face = claude_face(p['eyes'], p['mouth'], p['star'], p['flare'])
    paste_layer(g, face, fx, fy, math.degrees(rig.rot))
    return g


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Rendering a pose into a trimmed sprite with its floor anchor
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

def finish(grid, extra=None):
    """(RGBA picture trimmed to what is drawn, the anchor): the anchor is the floor's centre, whatever the pose does."""
    full = grid.image((-GOX, -GOY, GW - GOX, GH - GOY))
    box = full.getbbox()
    if box is None:
        raise ValueError('an empty pose')
    return full.crop(box), (GOX - box[0], GOY - box[1])


def record_shadow(name, grid):
    offset, half, strength = getattr(grid, 'shadow', (0.0, 0.0, 0.0))
    SHADOWS[name] = [round(offset, 1), round(half, 1), round(strength, 2)]


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# The poses: every move is a few frames, every frame a few numbers (board units)
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

def codex_walk():
    frames = []
    for k in range(6):
        phi = math.radians(k * 60)
        c, sn = math.cos(phi), math.sin(phi)
        frames.append(dict(rise=-1.1 * abs(sn), lean=0.8, shear=0.4, feet=(22 - 13 * c, 22 + 13 * c), lift=(-5.0 * max(0, sn), -5.0 * max(0, -sn)),
                           lead=(44 + 2 * c, 20 - 1.2 * abs(sn)), rear=(7 - 2 * c, 31 - 1.0 * abs(sn))))
    return frames


CODEX = {
    'idle': [dict(), dict(rise=-0.5, lead=(44, 19.6), rear=(7, 30.6)), dict(rise=-1.0, lead=(44, 19.2), rear=(7, 30.2), face='cursor'),
             dict(rise=-1.4, lead=(44, 18.8), rear=(7, 29.8), face='cursor')],
    'walk': codex_walk(),
    'guard': [dict(sag=1.5, lean=1, lead=(46, 16), rear=(9, 25), face='block', feet=(9, 35), shear=0.5),
              dict(sag=2.5, lean=1.5, lead=(48, 11), rear=(10, 20), face='block', feet=(8, 36), shear=0.8)],
    'jab': [dict(sag=1, lean=-1, shear=-0.5, lead=(37, 27), lead_bend=-0.1, face='effort', rear=(8, 29)),
            dict(sag=1, lean=2, shear=0.5, reach=52, face='strike', rear=(8, 28)),
            dict(sag=1, lean=3, shear=1.0, reach=62, face='strike', rear=(8, 28)),
            dict(sag=0.5, lean=1, lead=(47, 23), face='idle', rear=(8, 29))],
    'heavy': [dict(sag=3, lean=-3, shear=-1.5, lead=(36, 34), lead_bend=-0.2, rear=(10, 33), feet=(8, 33), face='effort'),
              dict(sag=4, lean=-5, shear=-2.5, lead=(31, 39), lead_bend=-0.2, rear=(9, 26), feet=(7, 32), face='effort', rot=-4),
              dict(sag=2, lean=3, shear=1.5, reach=50, feet=(12, 38), face='strike', rot=3, dx=1.5, rear=(8, 27)),
              dict(sag=2, lean=6, shear=2.5, reach=68, feet=(11, 40), face='strike', dx=3.5, rear=(9, 27)),
              dict(sag=1, lean=3, shear=1, reach=58, feet=(10, 38), face='idle', dx=2, rear=(8, 29))],
    'special': [dict(sag=2, lean=-2, glow=0.3, lead=(40, 30), rear=(8, 30), face='effort', feet=(8, 33)),
                dict(sag=3, lean=-3, glow=0.7, lead=(36, 34), rear=(6, 26), face='effort', feet=(7, 32)),
                dict(sag=3, lean=-3, shear=-1, glow=1.0, lead=(36, 34), rear=(6, 20), face='effort', feet=(7, 32)),
                dict(sag=1, lean=5, shear=2, glow=1.0, reach=64, rear=(6, 13), face='strike', feet=(11, 38), dx=2.5),
                dict(sag=1, lean=6, shear=2.5, glow=0.6, reach=68, rear=(6, 14), face='strike', feet=(11, 38), dx=3.5),
                dict(sag=0.5, lean=2, reach=56, face='idle', feet=(10, 36), dx=1.5)],
    'hit': [dict(lean=-3, shear=-2, sag=1, lead=(40, 24), rear=(8, 30), face='hurt', rot=-3),
            dict(lean=-2, shear=-1, lead=(42, 22), face='hurt', rot=-2)],
    'hurt': [dict(lean=-6, shear=-3.5, sag=0.5, rot=-9, dx=-1.5, face='hurt', lead=(38, 16), rear=(4, 24), feet=(9, 35)),
             dict(lean=-5, shear=-3, rot=-7, dx=-1.5, face='dizzy', lead=(40, 22), rear=(5, 28))],
    'kd': [dict(rot=-25, dy=-4, face='hurt', lead=(40, 12), rear=(2, 20), lift=(-3, -2), shadow=0.9),
           dict(rot=-55, dy=-12, face='dizzy', lead=(42, 6), rear=(0, 16), lift=(-6, -8), shadow=0.7),
           dict(rot=-85, dy=-12, face='dizzy', lead=(40, 12), rear=(2, 22), lift=(-4, -6), shadow=0.6),
           dict(rot=-90, dy=-1, face='dizzy', lead=(40, 14), rear=(2, 24), shadow=0.9, flat=0.62),
           dict(rot=-90, dy=2.0, face='dizzy', lead=(40, 16), rear=(2, 26), shadow=1.0, flat=0.62)],
    'getup': [dict(rot=-62, dy=-1.5, face='dizzy', lead=(40, 24), rear=(2, 30), flat=0.8),
              dict(rot=-30, sag=2, face='hurt', lead=(42, 26), rear=(5, 31)),
              dict(rot=-8, sag=3, face='effort', lead=(42, 28), rear=(7, 32), feet=(9, 34))],
    'win': [dict(rise=-0.5, lean=0.5, lead=(42, 8), face='happy'),
            dict(rise=-1.5, lead=(44, 3), face='happy', dy=-2, lift=(-1, -1)),
            dict(rise=-0.5, lean=0.5, lead=(42, 8), face='cheer')],
    'taunt': [dict(sag=2, lean=-1, lead=(40, 26), rear=(10, 28), face='happy'),
              dict(rise=-1, lead=(45, 14), rear=(6, 22), face='cheer'),
              dict(sag=2, lean=-1, lead=(38, 24), rear=(11, 27), face='happy')],
}

ARM_L = [(-13, 8), (-19, 6), (-21, 0), (-18, -4)]           # Claude's screen-left arm at rest (it passes behind the body)
ARM_R = [(13, 7), (18, 6), (20, 0), (17, -4)]               # and its screen-right arm (in front of it)


def claude_walk():
    frames = []
    for k in range(6):
        phi = math.radians(k * 60)
        tips = [(4.0 * math.sin(phi + i * math.pi / 2), -3.0 * max(0.0, math.cos(phi + i * math.pi / 2)), 0) for i in range(4)]
        frames.append(dict(rise=1.0 + 0.9 * math.sin(2 * phi), lean=-1.5, splay=0.8, tips=tips,
                           lead=[(-13, 8), (-19, 6 + 1.2 * math.sin(phi)), (-21, 0), (-18, -4 + 1.5 * math.sin(phi))],
                           rear=[(13, 7), (18, 6 - 1.2 * math.sin(phi)), (20, 0), (17, -4 - 1.5 * math.sin(phi))]))
    return frames


CLAUDE = {
    'idle': [dict(), dict(rise=1, splay=0.6), dict(rise=2, splay=1.2), dict(rise=1, splay=0.6)],
    'blink': [dict(eyes='blink')],
    'walk': claude_walk(),
    'guard': [dict(rise=1.5, splay=1.0, eyes='narrow', mouth='grit', lead=[(-12, 9), (-19, 4), (-21, -4), (-16, -10), (-10, -9)],
                   rear=[(13, 8), (18, 4), (20, -3), (17, -9)]),
              dict(rise=2.5, splay=1.6, eyes='narrow', mouth='grit', lead=[(-12, 9), (-18, 4), (-20, -3), (-17, -9), (-12, -9)],
                   rear=[(13, 8), (17, 4), (19, -3), (17, -8)])],
    'jab': [dict(rise=1.5, lean=1, splay=1.0, eyes='narrow', mouth='grit', lead=[(-12, 9), (-17, 9), (-19, 6), (-17, 2)]),
            dict(rise=1, lean=-2, splay=0.8, eyes='narrow', mouth='grit', lead=[(-12, 9), (-22, 9), (-32, 8), (-40, 7)], lead_r=(3.6, 2.7)),
            dict(rise=1, lean=-3, splay=0.8, eyes='narrow', mouth='grit', lead=[(-12, 9), (-24, 9), (-36, 8), (-46, 7)], lead_r=(3.6, 2.8)),
            dict(rise=1, lean=-1, splay=0.8, eyes='narrow', mouth='grit', lead=[(-12, 9), (-20, 8), (-26, 6), (-24, 1)], lead_r=(3.5, 2.2))],
    'heavy': [dict(rise=2, lean=2, splay=1.8, eyes='narrow', mouth='grit', lead=[(-12, 9), (-16, 2), (-14, -8), (-6, -15), (2, -17)],
                   rear=[(13, 7), (17, 8), (19, 3), (16, -1)]),
              dict(rise=3, lean=3, splay=2.0, eyes='narrow', mouth='grit', lead=[(-12, 9), (-17, 0), (-12, -12), (0, -19), (12, -17), (22, -12)],
                   rear=[(13, 7), (17, 8), (19, 3), (16, -1)]),
              dict(rise=1, lean=-3, splay=1.0, eyes='narrow', mouth='grit', lead=[(-12, 9), (-22, 0), (-34, -4), (-44, 2), (-50, 10)], lead_r=(3.8, 2.9),
                   rear=[(13, 7), (18, 8), (20, 14), (17, 18)]),
              dict(rise=1.5, lean=-4, splay=1.0, eyes='narrow', mouth='grit', lead=[(-12, 9), (-24, 4), (-38, 6), (-50, 12)], lead_r=(3.8, 3.0),
                   rear=[(13, 7), (18, 8), (20, 14), (17, 18)]),
              dict(rise=1, lean=-1, splay=0.8, eyes='narrow', mouth='grit', lead=[(-12, 9), (-20, 7), (-26, 3), (-24, -2)])],
    'whip': [dict(rise=2, lean=1, splay=1.8, eyes='narrow', mouth='grit', lead=[(-12, 9), (-18, 4), (-18, -5), (-10, -13)]),
             dict(rise=3, lean=2, splay=2.0, eyes='narrow', mouth='grit', lead=[(-12, 9), (-19, 3), (-17, -7), (-7, -15), (4, -16), (11, -12)],
                  rear=[(13, 7), (17, 8), (19, 3), (16, -1)]),
             dict(rise=1, lean=-3, splay=0.8, eyes='narrow', mouth='grit', whip=34, wave=2.2, rear=[(13, 7), (18, 8), (20, 14), (17, 18)]),
             dict(rise=1, lean=-4, splay=0.8, eyes='narrow', mouth='grit', whip=62, wave=1.0, rear=[(13, 7), (18, 8), (20, 14), (17, 18)]),
             dict(rise=1, lean=-4, splay=0.8, eyes='narrow', mouth='grit', whip=62, wave=-1.6, rear=[(13, 7), (18, 8), (20, 14), (17, 18)]),
             dict(rise=1.5, lean=-2, splay=1.2, eyes='narrow', mouth='grit', whip=30, wave=2.6, rear=[(13, 7), (18, 8), (20, 14), (17, 18)])],
    'special': [dict(rise=3, splay=2.5, eyes='narrow', mouth='grit', glow=0.3, star=1.1, flare=0.3),
                dict(rise=3.5, splay=3.0, eyes='narrow', mouth='grit', glow=0.7, star=1.2, flare=0.7, lead=[(-12, 9), (-20, 8), (-27, 4), (-31, -2)],
                     rear=[(13, 7), (21, 8), (28, 4), (32, -2)]),
                dict(rise=-2, splay=3.5, eyes='open', mouth='open', glow=1.0, star=1.3, flare=1.0, dy=-5, lead=[(-12, 6), (-18, -2), (-22, -12), (-24, -20)],
                     rear=[(12, 6), (18, -2), (22, -12), (24, -20)], tips=[(-3, -3, 0), (-2, -4, 0), (2, -4, 0), (3, -3, 0)]),
                dict(rise=0, lean=-2, splay=2.0, eyes='narrow', mouth='open', glow=1.0, star=1.3, flare=1.0, lead=[(-12, 9), (-24, 6), (-36, 2), (-44, -4)],
                     rear=[(13, 7), (21, 8), (28, 4), (32, -2)]),
                dict(rise=0.5, lean=-2, splay=1.6, eyes='narrow', mouth='open', glow=0.6, star=1.2, flare=0.6, lead=[(-12, 9), (-24, 6), (-34, 2), (-40, -2)]),
                dict(rise=1.5, splay=1.4, eyes='open', mouth='smile', star=1.0)],
    'hit': [dict(rise=-1, lean=3, splay=0.4, eyes='shut', mouth='open', lead=[(-13, 8), (-18, 3), (-21, -4), (-16, -9)], rear=[(13, 7), (17, 9), (19, 3), (16, -2)]),
            dict(rise=0, lean=2, splay=0.6, eyes='shut', mouth='open')],
    'hurt': [dict(rise=-1, lean=6, rot=8, dy=-1, splay=0.2, eyes='shut', mouth='open', lead=[(-13, 8), (-19, 2), (-22, -6), (-18, -12)],
                  rear=[(13, 7), (19, 9), (22, 4), (20, -2)]),
             dict(rise=-0.5, lean=5, rot=6, splay=0.4, eyes='dizzy', mouth='open')],
    'kd': [dict(rot=25, dy=-4, eyes='shut', mouth='open', tips=[(0, -3, 0), (0, -3, 0), (0, -2, 0), (0, -2, 0)], shadow=0.9),
           dict(rot=55, dy=-12, eyes='dizzy', mouth='open', tips=[(-2, -5, 0), (-2, -5, 0), (2, -4, 0), (2, -4, 0)], shadow=0.7,
                lead=[(-13, 8), (-20, 2), (-25, -6), (-24, -13)], rear=[(13, 7), (20, 2), (25, -6), (24, -13)]),
           dict(rot=85, dy=-12, eyes='dizzy', mouth='open', shadow=0.6),
           dict(rot=90, dy=-1, eyes='dizzy', mouth='open', shadow=0.9, flat=0.7),
           dict(rot=90, dy=4, eyes='dizzy', mouth='open', shadow=1.0, flat=0.7)],
    'getup': [dict(rot=62, dy=0, eyes='dizzy', mouth='open', flat=0.85),
              dict(rot=30, rise=2, eyes='shut', mouth='grit'),
              dict(rot=8, rise=2.5, splay=1.6, eyes='narrow', mouth='grit')],
    'win': [dict(rise=-1, eyes='happy', mouth='open', lead=[(-12, 6), (-18, -2), (-22, -12), (-24, -20)], rear=[(12, 6), (18, -2), (22, -12), (24, -20)]),
            dict(rise=-3, eyes='happy', mouth='open', dy=-3, lead=[(-12, 6), (-17, -4), (-20, -14), (-20, -23)], rear=[(12, 6), (17, -4), (20, -14), (20, -23)],
                 tips=[(-2, -2, 0), (-1, -3, 0), (1, -3, 0), (2, -2, 0)]),
            dict(rise=0, eyes='happy', mouth='smile', lead=[(-12, 6), (-18, -2), (-22, -12), (-24, -20)], rear=[(12, 6), (18, -2), (22, -12), (24, -20)])],
    'taunt': [dict(rise=1.5, splay=1.0, eyes='narrow', mouth='smile', lead=[(-13, 8), (-21, 4), (-27, -2), (-24, -8)]),
              dict(rise=0, eyes='open', mouth='open', lead=[(-13, 8), (-23, 2), (-30, -4), (-33, -11)]),
              dict(rise=1.5, splay=1.0, eyes='narrow', mouth='smile', lead=[(-13, 8), (-19, 6), (-24, -1), (-27, -7)])],
}


# In-between poses: the frames between a pose and the next, made by blending two poses (numbers and points; the face of the one the move is heading for), so a fighter
# eases into a windup and out of a blow instead of popping. They are named `<who>-tw-<name>` and the scene puts them in a move's sequence as strings.
CODEX_DEFAULTS = dict(rise=0.0, sag=0.0, lean=0.0, shear=0.0, lead=(44, 20), lead_bend=0.12, reach=None, rear=(7, 31), rear_bend=-0.15, feet=(10, 34), lift=(0, 0),
                      face='idle', rot=0.0, dx=0.0, dy=0.0, glow=0.0, shadow=1.0, pivot=None, flat=1.0)
CLAUDE_DEFAULTS = dict(rise=0.0, lean=0.0, splay=0.0, eyes='open', mouth='smile', lead=[(-13, 8), (-19, 6), (-21, 0), (-18, -4)], rear=[(13, 7), (18, 6), (20, 0), (17, -4)], whip=None,
                       wave=1.2, rot=0.0, dx=0.0, dy=0.0, glow=0.0, shadow=1.0, tips=[(0, 0, 0)] * 4, pivot=None, star=1.0, flat=1.0, lead_r=(3.4, 1.5), flare=0.0)


def _lerp(a, b, t):
    return a + (b - a) * t


def _blend_value(a, b, t):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _lerp(a, b, t)
    if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b) and all(isinstance(v, (int, float)) for v in a + b):
        return tuple(_lerp(x, y, t) for x, y in zip(a, b))
    if isinstance(a, list) and isinstance(b, list):
        n = max(len(a), len(b))

        def at(points, i):
            if len(points) == 1:
                return points[0]
            u = i / (n - 1) * (len(points) - 1)
            k = min(int(u), len(points) - 2)
            f = u - k
            return tuple(_lerp(x, y, f) for x, y in zip(points[k], points[k + 1]))
        return [tuple(_lerp(x, y, t) for x, y in zip(at(a, i), at(b, i))) for i in range(n)]
    return b if t >= 0.5 else a


def blend_pose(defaults, a, b, t, face_from='b'):
    """The pose a fraction `t` of the way from pose `a` to pose `b` (both partial dicts over `defaults`)."""
    pa, pb = dict(defaults), dict(defaults)
    pa.update(a)
    pb.update(b)
    out = {}
    for key in defaults:
        va, vb = pa[key], pb[key]
        if key == 'reach':                                                                       # a straight piston against a lead point: compare the fists' reach
            if va is None and vb is None:
                out[key] = None
            else:
                va = va if va is not None else pa['lead'][0]
                vb = vb if vb is not None else pb['lead'][0]
                out[key] = _lerp(va, vb, t)
        elif key in ('face', 'eyes', 'mouth'):
            out[key] = (pb if face_from == 'b' else pa)[key]
        elif key == 'whip':
            out[key] = vb if t >= 0.5 else va
        elif va is None or vb is None:
            out[key] = va if vb is None else vb
        else:
            out[key] = _blend_value(va, vb, t)
    return out


def _tweens(*names):
    """{key: (move a, frame a, move b, frame b, how far, the face from)}: 'x-in' eases from the idle pose into move x, 'x-out' from its last pose back to idle."""
    out = {}
    for name in names:
        move, direction = name.rsplit('-', 1)
        last = {'jab': 3, 'heavy': 4, 'special': 5, 'guard': 1, 'hit': 1, 'getup': 2, 'taunt': 2, 'win': 2}.get(move, 0)
        out[name] = ('idle', 0, move, 0, 0.55, 'b') if direction == 'in' else (move, last, 'idle', 0, 0.5, 'b')
    return out


TWEENS = {
    'codex': _tweens('jab-in', 'jab-out', 'heavy-in', 'heavy-out', 'special-in', 'special-out', 'guard-in', 'guard-out', 'hit-out', 'getup-out', 'taunt-in', 'win-in'),
    'claude': _tweens('jab-in', 'jab-out', 'heavy-in', 'heavy-out', 'whip-in', 'special-in', 'special-out', 'guard-in', 'guard-out', 'hit-out', 'getup-out', 'taunt-in', 'win-in'),
}
CLAUDE_WHIP_OUT = dict(rise=1.2, lean=-1.5, splay=1.0, eyes='narrow', mouth='grit', whip=14, wave=2.6, rear=[(13, 7), (18, 8), (20, 14), (17, 18)])


@lru_cache(maxsize=1)
def build_fighters():
    """({frame name: (picture, anchor)}, {fighter: {move: [frame names]}}), in a fixed order (drawn once per run: every other caller shares the result)."""
    frames, anims = {}, {}

    def add(name, grid):
        frames[name] = finish(grid)
        record_shadow(name, grid)

    for who, table, draw, defaults in (('codex', CODEX, codex, CODEX_DEFAULTS), ('claude', CLAUDE, claude, CLAUDE_DEFAULTS)):
        anims[who] = {}
        for move, poses in table.items():
            names = []
            for k, pose in enumerate(poses):
                name = f'{who}-{move}-{k}'
                add(name, draw(pose))
                names.append(name)
            anims[who][move] = names
        anims[who]['tw'] = []
        for key, (move_a, ka, move_b, kb, t, face_from) in TWEENS[who].items():
            name = f'{who}-tw-{key}'
            add(name, draw(blend_pose(defaults, table[move_a][ka], table[move_b][kb], t, face_from)))
            anims[who]['tw'].append(name)
        if who == 'claude':
            add('claude-tw-whip-out', draw(CLAUDE_WHIP_OUT))
            anims[who]['tw'].append('claude-tw-whip-out')
    return frames, anims


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Looking at the art
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

def contact_sheet(frames, anims, scale=2, background=(44, 74, 112)):
    """A labelled picture of every fighter frame, one row per move, to LOOK at (it is not a scene file)."""
    from PIL import ImageFont
    font = ImageFont.load_default()
    rows = [(who, move, names) for who, table in anims.items() for move, names in table.items()]
    cell_w = max(f[0].width for f in frames.values()) + 6
    cell_h = max(f[0].height for f in frames.values()) + 6
    width = 70 + max(len(names) for _, _, names in rows) * cell_w * scale
    sheet = Image.new('RGBA', (width, len(rows) * cell_h * scale), background + (255,))
    draw = ImageDraw.Draw(sheet)
    for r, (who, move, names) in enumerate(rows):
        y0 = r * cell_h * scale
        draw.text((4, y0 + 4), f'{who}\n{move}', fill=(255, 255, 255, 255), font=font)
        for k, name in enumerate(names):
            picture, (ax, ay) = frames[name]
            big = picture.resize((picture.width * scale, picture.height * scale), Image.Resampling.NEAREST)
            sheet.alpha_composite(big, (70 + k * cell_w * scale + (cell_w // 2 - ax) * scale, y0 + (cell_h - 14 - ay) * scale))
    return sheet.convert('RGB')


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Effects: hit sparks, blocks, dust, rings, dizzy stars, glints and the two projectiles
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

def hexrgb(text):
    return rgb(text)


BLUE_BURST = [hexrgb(c) for c in ('#2d4fc8', '#57a2ff', '#bde0ff', '#ffffff')]
DUST = [hexrgb(c) for c in ('#8a7f78', '#b9ad9f', '#dfd4c4', '#f8f0e2')]
STAR_YELLOW = [hexrgb(c) for c in ('#d77a00', '#f5a712', '#ffcf3a', '#fff29a')]


def new_image(w, h):
    return Image.new('RGBA', (w, h), CLEAR)


def outline_mask(pixels, colour):
    """The one-pixel ring round a set of pixels."""
    ring = {}
    for x, y in pixels:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in pixels:
                ring[(x + dx, y + dy)] = colour
    return ring


def put_pixels(im, pixels):
    for (x, y), colour in pixels.items():
        if 0 <= x < im.width and 0 <= y < im.height:
            im.putpixel((x, y), tuple(colour) + (255,))


def star_burst(big, small, spikes=8, phase=0.25, tones=bf.BURST, ink=bf.INK_BURST, pad=3):
    """A generic impact star: a white heart, then cream, yellow and an orange rim, with a dark outline (the board's burst, any size)."""
    size = int(big) * 2 + 2 * pad + 1
    c = size / 2
    pixels = {}
    for y in range(size):
        for x in range(size):
            dx, dy = x + 0.5 - c, y + 0.5 - c
            rad = small + (big - small) * max(0.0, math.cos(spikes / 2 * (math.atan2(dy, dx) - phase))) ** 2.2
            d = math.hypot(dx, dy)
            if d <= rad:
                t = d / rad
                pixels[(x, y)] = tones[3] if t < 0.38 else tones[2] if t < 0.62 else tones[1] if t < 0.85 else tones[0]
    im = new_image(size, size)
    put_pixels(im, outline_mask(set(pixels), ink))
    put_pixels(im, pixels)
    return im


def sparks(radius, count=8, size=2, tones=bf.BURST, phase=0.3, spread=0.35):
    """A ring of small flying sparks."""
    box = int(radius * 2 + 2 * size + 6)
    im = new_image(box, box)
    c = box / 2
    for k in range(count):
        a = phase + k * 2 * math.pi / count
        r = radius * (1 - spread * (k % 2))
        x, y = int(c + math.cos(a) * r), int(c + math.sin(a) * r)
        colour = tones[2 if k % 3 else 3]
        for dx in range(size):
            for dy in range(size):
                im.putpixel((x + dx, y + dy), tuple(colour) + (255,))
    return im


def over(base, top):
    """`top` centred over `base` (both RGBA), on the bigger canvas."""
    w, h = max(base.width, top.width), max(base.height, top.height)
    im = new_image(w, h)
    im.alpha_composite(base, ((w - base.width) // 2, (h - base.height) // 2))
    im.alpha_composite(top, ((w - top.width) // 2, (h - top.height) // 2))
    return im


def effect_frames():
    """{name: [pictures]}: each picture's centre is the effect's centre (the scene anchors them there)."""
    fx = {}
    fx['spark'] = [star_burst(6, 2.5, 6), star_burst(11, 4, 6, 0.4), star_burst(9, 3.5, 6, 0.7), sparks(9, 6, 2)]
    fx['impact'] = [star_burst(12, 5, 8), star_burst(21, 8, 8, 0.4), star_burst(25, 9, 8, 0.6), star_burst(20, 7, 8, 0.8), sparks(24, 8, 2)]
    fx['flash'] = [star_burst(20, 8, 10), star_burst(34, 12, 12, 0.3), star_burst(44, 14, 12, 0.5), star_burst(38, 12, 12, 0.7), star_burst(26, 8, 12, 0.9), sparks(40, 12, 3)]
    fx['block'] = [star_burst(6, 3, 6, tones=BLUE_BURST), star_burst(11, 4, 6, 0.4, tones=BLUE_BURST), star_burst(9, 3.5, 6, 0.7, tones=BLUE_BURST),
                   sparks(10, 6, 2, tones=BLUE_BURST)]
    fx['dust'] = dust_frames()
    fx['ring'] = ring_frames()
    fx['stars'] = star_ring_frames()
    fx['glint'] = [glint(r) for r in (2, 4, 6, 4)]
    return fx


def glint(r):
    """A four-point sparkle."""
    size = 2 * r + 3
    im = new_image(size, size)
    c = size // 2
    for k in range(-r, r + 1):
        w = r - abs(k)
        im.putpixel((c + k, c), (255, 255, 255, 255))
        im.putpixel((c, c + k), (255, 255, 255, 255))
        if w > 1 and abs(k) < r - 1:
            for q in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                if abs(k) <= 1:
                    im.putpixel((c + q[0] * abs(k) if k else c + q[0], c + q[1] * (abs(k) if k else 1)), (255, 247, 200, 255))
    return im


def dust_frames():
    out = []
    plan = ((3, 0.0, 3), (5, 3.0, 4), (7, 6.5, 4), (6, 10.0, 3), (4, 13.5, 3))        # puff radius, spread, how many puffs
    for k, (radius, spread, count) in enumerate(plan):
        size = int(spread * 2 + radius * 2 + 8)
        im = new_image(size, size)
        d = ImageDraw.Draw(im)
        c = size / 2
        for i in range(count):
            a = -math.pi * (0.15 + 0.7 * i / max(1, count - 1))
            x, y = c + math.cos(a) * spread * 1.1, c + math.sin(a) * spread * 0.5
            r = radius * (1.0 - 0.18 * (i % 2))
            tone = DUST[min(3, 1 + k // 2 + (i % 2))] if k < 4 else DUST[2]
            d.ellipse((x - r, y - r * 0.8, x + r, y + r * 0.8), fill=DUST[0] + (255,))
            d.ellipse((x - r + 1, y - r * 0.8, x + r - 0.5, y + r * 0.8 - 1.2), fill=tone + (255,))
        out.append(im)
    return out


def ring_frames():
    out = []
    for k, (w, thick) in enumerate(((18, 4), (32, 4), (46, 3), (58, 3), (68, 2))):
        h = max(6, int(w * 0.26))
        im = new_image(w + 8, h + 8)
        d = ImageDraw.Draw(im)
        box = (3, 3, w + 4, h + 4)
        d.ellipse(box, outline=BLUE_BURST[1] + (255,), width=thick + 1)
        d.ellipse((box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), outline=BLUE_BURST[3] + (255,), width=max(1, thick - 1))
        out.append(im)
    return out


def star_ring_frames():
    out = []
    for k in range(4):
        im = new_image(44, 16)
        for i in range(3):
            a = k * 0.5 + i * 2 * math.pi / 3
            x, y = 22 + math.cos(a) * 17, 8 + math.sin(a) * 4.5
            for dx, dy, c in ((0, 0, 3), (-1, 0, 2), (1, 0, 2), (0, -1, 2), (0, 1, 2), (-2, 0, 1), (2, 0, 1)):
                px, py = int(x) + dx, int(y) + dy
                if 0 <= px < 44 and 0 <= py < 16:
                    im.putpixel((px, py), tuple(STAR_YELLOW[c]) + (255,))
        out.append(im)
    return out


def chevron_poly(x, y, size, thick):
    return [(x, y - size), (x + thick, y - size), (x + thick + size * 0.7, y), (x + thick, y + size), (x, y + size), (x + size * 0.7, y)]


def projectile_codex():
    """A burst of prompt chevrons (>>>) flying right, bright at the front, fading behind (the prompt is Codex's voice)."""
    frames = []
    for k in range(4):
        im = new_image(54, 34)
        d = ImageDraw.Draw(im)
        for i, shade in enumerate((0, 1, 2)):
            x = 10 + i * 13 + (k % 2) * 2
            size = 11 - (2 - i) * 1.4
            pts = chevron_poly(x, 17, size, 4.4)
            colour = (bf.PROMPT, (150, 226, 255), (96, 168, 255))[2 - i] if i != 2 else (255, 255, 255)
            d.polygon([(px + 1.2, py + 1.2) for px, py in pts], fill=bf.INK_STEEL + (255,))
            d.polygon(pts, fill=tuple(colour) + (255,))
        for j in range(3):
            d.rectangle((2 + j * 3 + (k * 2) % 5, 14 + (j * 5 + k * 3) % 8, 4 + j * 3 + (k * 2) % 5, 15 + (j * 5 + k * 3) % 8), fill=bf.PROMPT + (255,))
        frames.append(im)
    return frames


def projectile_claude():
    """A spinning four-point starburst (Claude's own mark), orange rim and cream heart, with embers behind it."""
    frames = []
    for k in range(4):
        im = new_image(42, 42)
        d = ImageDraw.Draw(im)
        a0 = k * math.pi / 8
        for scale, colour in ((1.0, bf.INK_ORANGE), (0.88, bf.ORANGE[2]), (0.62, bf.CREAM), (0.34, (255, 255, 255))):
            r = 18 * scale
            pts = []
            for i in range(8):
                a = a0 + i * math.pi / 4
                rr = r if i % 2 == 0 else r * 0.34
                pts.append((21 + math.cos(a) * rr - 0.5, 21 + math.sin(a) * rr - 0.5))
            d.polygon(pts, fill=tuple(colour) + (255,))
        for j in range(4):
            x, y = 36 + (k + j * 2) % 5, 8 + j * 8 + (k * 3) % 4
            if x < 42:
                im.putpixel((x, y), tuple(bf.BURST[1]) + (255,))
        frames.append(im)
    return frames


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Spectators: small fans of the two fighters (a cloud-bot and an octopus kid), in four colours
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

TEAL = [hexrgb(c) for c in ('#0e5560', '#1c8f8f', '#3fc8b8', '#a8f2e0')]
PINK = [hexrgb(c) for c in ('#8a2a5c', '#cf4f8c', '#f27fb0', '#ffc4dc')]
VIOLET = [hexrgb(c) for c in ('#3b2a78', '#6a4fb8', '#9a82e8', '#d3c6ff')]
GREEN = [hexrgb(c) for c in ('#1e5a2a', '#3a9a44', '#68d066', '#c4f5a8')]
INKS = {'teal': hexrgb('#0a2f3a'), 'pink': hexrgb('#4a1230'), 'violet': hexrgb('#1c1240'), 'green': hexrgb('#0e2e16')}
CROWD_KINDS = {'bot-teal': ('bot', TEAL, 'teal'), 'bot-pink': ('bot', PINK, 'pink'), 'octo-violet': ('octo', VIOLET, 'violet'), 'octo-green': ('octo', GREEN, 'green')}
CROWD_POSES = ('idle0', 'idle1', 'cheer0', 'cheer1', 'gasp')


def fan(kind, pose):
    """A small spectator (about 22 x 24 pixels), anchored at its feet. Poses: two idle bobs, two cheers (arms up, a hop) and a gasp (mouth open)."""
    shape, ramp, ink_name = CROWD_KINDS[kind]
    ink = INKS[ink_name]
    g = bf.Grid(60, 52, 30, 44)
    hop = -2 if pose in ('cheer1',) else 0
    bob = -1 if pose in ('idle1', 'cheer0') else 0
    up = pose.startswith('cheer')
    cx, cy = 0.0, -11.0 + bob + hop
    bf._flat_ellipse(g, 0, 0, 8.5, 1.8, bf.SHADOW)
    if shape == 'bot':
        for sx in (-1, 1):                                                                                                      # arms
            s = RS()
            ax, ay = sx * 8.5, cy + 3
            bx, by = (sx * 11, cy - 7) if up else (sx * 11, cy + 8)
            s.tube([(ax, ay), ((ax + bx) / 2, (ay + by) / 2), (bx, by)], [1.7, 1.6, 1.8])
            bf._part(g, s, ramp, ink=ink)
        for sx in (-1, 1):                                                                                                      # boots
            s = RS()
            s.ellipsoid(sx * 3.6, -2.2 + hop * 0.3, 3.2, 2.2, 2.2)
            bf._part(g, s, ramp, ink=ink)
        s = RS()
        s.ellipsoid(cx, cy + 1.5, 8.5, 6.5, 6.5, tag=0)
        s.ellipsoid(cx - 5, cy - 2.5, 4.6, 4.0, 5, tag=1)
        s.ellipsoid(cx + 0.5, cy - 4.5, 5.6, 4.6, 5.6, tag=2)
        s.ellipsoid(cx + 5, cy - 2.5, 4.4, 3.8, 5, tag=3)
        bf._part(g, s, ramp, ink=ink)
        for j in range(7):                                                                                                      # the little screen
            for i in range(11):
                if (i in (0, 10)) and (j in (0, 6)):
                    continue
                g.put(-5 + i, int(cy - 4) + j, (230, 240, 255) if (i in (0, 10) or j in (0, 6)) else (12, 18, 52))
        face = (14, 22, 70)
        if pose == 'gasp':
            for dx, dy in ((-2, 0), (-3, 1), (2, 0), (3, 1)):
                g.put(dx, int(cy - 2) + dy, (180, 250, 255))
            for dx, dy in ((0, 2), (-1, 2), (0, 3), (-1, 3)):
                g.put(dx, int(cy - 2) + dy, (180, 250, 255))
        elif up:
            for dx, dy in ((-3, 1), (-2, 0), (-1, 1), (1, 1), (2, 0), (3, 1)):
                g.put(dx, int(cy - 2) + dy, (180, 250, 255))
        else:
            for dx in (-2, 2):
                g.put(dx, int(cy - 2), (180, 250, 255))
                g.put(dx, int(cy - 1), (180, 250, 255))
        for dx, dy, c in ((0, 0, 3), (-1, 0, 2), (1, 0, 2), (0, 1, 2), (1, 1, 2)):                                           # a tiny bolt crest
            g.put(1 + dx, int(cy - 12) + dy, bf.BOLT[c])
    else:
        for sx, foot in ((-1, 5), (1, 5), (-1, 9), (1, 9)):                                                                    # legs
            s = RS()
            s.tube([(sx * 3, cy + 5), (sx * foot * 0.7, -4), (sx * (foot + 1.5), -1)], [1.8, 1.5, 1.2])
            bf._part(g, s, ramp, ink=ink)
        for sx in (-1, 1):                                                                                                      # arms
            s = RS()
            ax, ay = sx * 8, cy + 1
            bx, by = (sx * 10, cy - 11) if up else (sx * 11, cy + 6)
            s.tube([(ax, ay), ((ax + bx) / 2 + sx * 1.5, (ay + by) / 2), (bx, by)], [1.7, 1.5, 1.2])
            bf._part(g, s, ramp, ink=ink)
        s = RS()
        s.ellipsoid(cx, cy, 8.8, 7.2, 6.5, bias=0.8)
        bf._part(g, s, ramp, ink=ink, th=(0.86, 0.52, 0.22))
        for ex in (-4, 2):
            g.put(ex, int(cy - 1), (20, 16, 38))
            g.put(ex + 1, int(cy - 1), (20, 16, 38))
            g.put(ex, int(cy), (20, 16, 38))
            g.put(ex + 1, int(cy), (20, 16, 38))
            if pose != 'gasp':
                g.put(ex, int(cy - 1), (255, 255, 255))
        if pose == 'gasp':
            for dx, dy in ((-1, 3), (0, 3), (-1, 4), (0, 4)):
                g.put(dx, int(cy) + dy, (110, 30, 50))
        elif up:
            for dx in range(-2, 2):
                g.put(dx, int(cy) + 3 + (1 if dx in (-2, 1) else 0), (110, 30, 50))
        for dx, dy in ((0, -1), (-1, 0), (0, 0), (1, 0), (0, 1)):
            g.put(-1 + dx, int(cy - 6) + dy, bf.CREAM)
    return finish_small(g, (-30, -44, 30, 8))


def finish_small(grid, box):
    full = grid.image(box)
    bbox = full.getbbox()
    return full.crop(bbox), (-box[0] - bbox[0], -box[1] - bbox[1])


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Props, boats, gulls and clouds for the drawn stages
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

def rect(d, x0, y0, x1, y1, fill):
    if x1 >= x0 and y1 >= y0:
        d.rectangle((round(x0), round(y0), round(x1), round(y1)), fill=tuple(fill) + (255,) if len(fill) == 3 else tuple(fill))


def lantern():
    im = new_image(24, 54)
    d = ImageDraw.Draw(im)
    iron, iron_hi = hexrgb('#2a303c'), hexrgb('#4a5262')
    rect(d, 11, 20, 12, 52, iron)
    rect(d, 12, 20, 12, 52, iron_hi)
    rect(d, 7, 50, 16, 53, iron)
    rect(d, 8, 50, 15, 50, iron_hi)
    rect(d, 6, 4, 17, 6, iron)
    d.polygon([(7, 4), (11.5, 0), (16, 4)], fill=iron + (255,))
    rect(d, 7, 7, 16, 18, hexrgb('#ffb347'))
    rect(d, 8, 8, 15, 17, hexrgb('#ffe9a8'))
    rect(d, 9, 9, 13, 14, hexrgb('#fffbe0'))
    rect(d, 11, 7, 12, 18, hexrgb('#ffb347'))
    rect(d, 6, 19, 17, 20, iron)
    return im, (11, 53)


def barrel():
    im = new_image(22, 26)
    d = ImageDraw.Draw(im)
    wood, wood_hi, wood_lo, iron = hexrgb('#8a5a2b'), hexrgb('#b07a3e'), hexrgb('#5a3a1a'), hexrgb('#2a303c')
    d.ellipse((2, 20, 19, 25), fill=wood_lo + (255,))
    d.rounded_rectangle((2, 5, 19, 22), radius=3, fill=wood + (255,))
    rect(d, 4, 6, 7, 21, wood_hi)
    rect(d, 16, 6, 18, 21, wood_lo)
    d.ellipse((2, 2, 19, 9), fill=wood_hi + (255,), outline=wood_lo + (255,))
    d.ellipse((5, 3, 16, 7), fill=hexrgb('#d9a05a') + (255,))
    rect(d, 2, 10, 19, 11, iron)
    rect(d, 2, 17, 19, 18, iron)
    return im, (10, 24)


def crate():
    im = new_image(24, 24)
    d = ImageDraw.Draw(im)
    wood, wood_hi, wood_lo = hexrgb('#b9824a'), hexrgb('#dba76a'), hexrgb('#6a4422')
    rect(d, 1, 1, 22, 22, wood_lo)
    rect(d, 2, 2, 21, 21, wood)
    rect(d, 2, 2, 21, 3, wood_hi)
    for k in (7, 12, 17):
        rect(d, 2, k, 21, k, wood_lo)
    d.line((3, 3, 20, 20), fill=wood_lo + (255,))
    d.line((3, 20, 20, 3), fill=wood_lo + (255,))
    rect(d, 2, 2, 3, 21, wood_hi)
    return im, (11, 22)


def bollard():
    im = new_image(14, 16)
    d = ImageDraw.Draw(im)
    iron, hi = hexrgb('#2a303c'), hexrgb('#5a6476')
    d.ellipse((1, 11, 12, 15), fill=iron + (255,))
    rect(d, 3, 4, 10, 12, iron)
    rect(d, 4, 4, 5, 12, hi)
    d.ellipse((2, 1, 11, 6), fill=hi + (255,), outline=iron + (255,))
    rect(d, 3, 9, 10, 10, hexrgb('#c9b27a'))
    return im, (6, 14)


def sailboat(variant):
    hull = hexrgb('#9a2f2f') if variant == 0 else hexrgb('#24508f')
    sail = (255, 252, 240), (214, 226, 242)
    w, h = (34, 40) if variant == 0 else (26, 30)
    im = new_image(w, h)
    d = ImageDraw.Draw(im)
    base = h - 4
    mid = w // 2
    d.polygon([(mid - w // 2 + 2, base - 5), (mid + w // 2 - 2, base - 5), (mid + w // 2 - 6, base), (mid - w // 2 + 6, base)], fill=hull + (255,))
    rect(d, mid - w // 2 + 2, base - 6, mid + w // 2 - 2, base - 5, (242, 232, 212))
    rect(d, mid, 3, mid, base - 6, hexrgb('#4a3a2a'))
    d.polygon([(mid + 1, 4), (mid + 1, base - 8), (mid + w // 2 - 3, base - 8)], fill=sail[0] + (255,))
    d.polygon([(mid - 1, 8), (mid - 1, base - 8), (mid - w // 2 + 3, base - 8)], fill=sail[1] + (255,))
    d.point((mid, 2), fill=hexrgb('#d9392b') + (255,))
    return im, (mid, base)


def ship():
    im = new_image(84, 36)
    d = ImageDraw.Draw(im)
    dark, red, white, grey = hexrgb('#1c2c50'), hexrgb('#b8402e'), hexrgb('#e8edf2'), hexrgb('#59657a')
    d.polygon([(2, 22), (82, 22), (74, 31), (10, 31)], fill=dark + (255,))
    rect(d, 4, 22, 80, 23, red)
    rect(d, 8, 27, 76, 27, hexrgb('#101c38'))
    rect(d, 52, 10, 72, 21, white)
    rect(d, 52, 10, 72, 11, grey)
    for x in range(55, 70, 4):
        rect(d, x, 14, x + 1, 16, hexrgb('#3a6a86'))
    rect(d, 60, 4, 66, 9, red)
    rect(d, 60, 4, 66, 5, hexrgb('#1a1a22'))
    for x in (8, 22, 36):                                                                                                      # containers
        for k, colour in enumerate(('#d9702e', '#3a7ab8', '#cfae3a')):
            rect(d, x, 15 - k * 0 + 0, x + 11, 21, hexrgb(colour) if (x // 14 + k) % 3 == k else hexrgb('#3a7ab8'))
            rect(d, x, 15, x + 11, 15, hexrgb('#ffffff'))
    return im, (42, 29)


def gull_frames():
    shapes = ('X...........X/.XX.......XX./..XXX...XXX../....XXXXX..../.....XXX.....',
              '............./XXXXX...XXXXX/...XXXXXXX.../.....XXX...../.............',
              '............./.....XXX...../..XXXXXXXXX../.XX...X...XX./X.....X.....X')
    frames = []
    for shape in shapes:
        rows = shape.split('/')
        im = new_image(13, 5)
        for y, row in enumerate(rows):
            for x, cell in enumerate(row):
                if cell == 'X':
                    im.putpixel((x, y), (255, 255, 255, 255) if y == 0 or rows[min(4, y + 1)][x] == 'X' else (176, 190, 214, 255))
        frames.append(im)
    return frames


def cloud(width, seed=0):
    """A flat-bottomed cumulus in four flat tones, a little taller in the middle."""
    import random
    rnd = random.Random(width * 31 + seed)
    height = max(6, round(width * .32))
    im = new_image(width + 6, height + 6)
    base = height + 2
    puffs = []
    count = max(3, width // 8)
    for i in range(count):
        t = (i + .5) / count
        r = max(2, round(height * (.2 + .3 * math.sin(math.pi * t)) * rnd.uniform(.9, 1.05)))
        puffs.append((3 + t * (width - 1) + rnd.uniform(-1, 1), base - r + rnd.randint(0, 1), r))
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            inside = [p for p in puffs if (x - p[0]) ** 2 + (y - p[1]) ** 2 <= p[2] ** 2]
            if not inside or y > base:
                continue
            light = max((p[1] - y) / p[2] + .22 * (p[0] - x) / p[2] for p in inside)
            if y >= base - max(1, height // 6):
                px[x, y] = (145, 187, 218, 255)
            elif light < -.5:
                px[x, y] = (194, 216, 230, 255)
            elif light < -.16:
                px[x, y] = (229, 237, 239, 255)
            else:
                px[x, y] = (255, 253, 240, 255)
    return im.crop(im.getbbox()), (0, 0)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# Tony's private jungle stage (optional)
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

STAGE_ROWS = (24, 223)                     # the rows of the board's 320 x 240 stage that are picture (the rest is the board's flat bands for its HUD)
JUNGLE_FLOOR = 166                         # the row of the cropped stage where the fighters' feet go (the middle of the deck)
AMBIENT_SCRIPT = [0, 1, 2, 3, 2, 1]
AMBIENT_MS = 600


def private_stage(directory=None):
    """The board's optional private stage ((320 x 240 RGB, [[RGBA ambient frames] x 2])) or None when it is missing or not valid. It is Tony's private art:
    it is read, never written, and goes only into the private atlas."""
    from token_tv import board_arcade_local as local
    old = local.ART_DIRECTORY
    if directory is not None:
        local.ART_DIRECTORY = Path(directory)
    try:
        return local.load()
    finally:
        local.ART_DIRECTORY = old


def jungle(art):
    """(frames, stage entry) of the private stage cropped to its picture rows, with its two ambient pieces at their place in the crop."""
    background, effects = art
    top, bottom = STAGE_ROWS
    frames = {'stage-jungle': (background.convert('RGBA').crop((0, top, background.width, bottom)), (0, 0))}
    ambient = []
    from token_tv import board_arcade_local as local
    for index, ((x, y, w, h), pieces) in enumerate(zip(local.EFFECTS, effects)):
        names = []
        for k, piece in enumerate(pieces):
            name = f'stage-jungle-amb-{index}-{k}'
            frames[name] = (piece.convert('RGBA'), (0, 0))
            names.append(name)
        ambient.append({'at': [x, y - top], 'frames': names, 'script': list(AMBIENT_SCRIPT), 'ms': AMBIENT_MS})
    entry = {'frame': 'stage-jungle', 'size': [background.width, bottom - top], 'floor': JUNGLE_FLOOR, 'ambient': ambient}
    return frames, entry


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# The atlas
# ---------------------------------------------------------------------------------------------------------------------------------------------------------

CLOUD_WIDTHS = (24, 40, 64, 96)
SAIL = 2


def build_sprites(art=None):
    """({frame name: (RGBA picture, (anchor x, anchor y))}, {group: {kind: [names]}}, {stage: entry}), in a fixed order."""
    frames, anims, stages = {}, {}, {}
    fighters, anims_fighters = build_fighters()
    frames.update(fighters)
    anims.update(anims_fighters)
    anims['fx'] = {}
    for kind, pictures in effect_frames().items():
        anims['fx'][kind] = []
        for k, picture in enumerate(pictures):
            name = f'fx-{kind}-{k}'
            frames[name] = (picture, (picture.width // 2, picture.height // 2))
            anims['fx'][kind].append(name)
    anims['proj'] = {}
    for who, pictures in (('codex', projectile_codex()), ('claude', projectile_claude())):
        anims['proj'][who] = []
        for k, picture in enumerate(pictures):
            name = f'proj-{who}-{k}'
            frames[name] = (picture, (picture.width // 2, picture.height // 2))
            anims['proj'][who].append(name)
    anims['crowd'] = {}
    for kind in CROWD_KINDS:
        anims['crowd'][kind] = []
        for pose in CROWD_POSES:
            name = f'crowd-{kind}-{pose}'
            frames[name] = fan(kind, pose)
            anims['crowd'][kind].append(name)
    anims['props'] = {}
    for kind, make in (('lantern', lantern), ('barrel', barrel), ('crate', crate), ('bollard', bollard), ('ship', ship)):
        frames[f'prop-{kind}'] = make()
        anims['props'][kind] = [f'prop-{kind}']
    anims['boats'] = {'sail': []}
    for variant in (0, 1):
        frames[f'boat-sail-{variant}'] = sailboat(variant)
        anims['boats']['sail'].append(f'boat-sail-{variant}')
    anims['gulls'] = {'fly': []}
    for k, picture in enumerate(gull_frames()):
        frames[f'gull-{k}'] = (picture, (picture.width // 2, picture.height - 1))
        anims['gulls']['fly'].append(f'gull-{k}')
    anims['clouds'] = {'cumulus': []}
    for width in CLOUD_WIDTHS:
        frames[f'cloud-{width:03d}'] = cloud(width)
        anims['clouds']['cumulus'].append(f'cloud-{width:03d}')
    from scripts import fighting_stage_art as stage_art
    new_frames, new_anims, points = stage_art.stage_sprites()
    frames.update(new_frames)
    anims['actors'] = new_anims['actors']
    for kind, names in new_anims['fx'].items():
        anims['fx'][kind] = names
    for kind, names in new_anims['crowd'].items():
        anims['crowd'][kind] = names
    POINTS.clear()
    POINTS.update(points)
    if art:
        stage_frames, entry = jungle(art)
        frames.update(stage_frames)
        stages['jungle'] = entry
    return frames, anims, stages


def pack(frames, width=1024, gutter=1):
    """Shelf-pack every picture, tallest first: ({name: (x, y)}, atlas picture)."""
    order = sorted(frames, key=lambda name: (-frames[name][0].height, name))
    x = y = shelf = 0
    positions = {}
    for name in order:
        w, h = frames[name][0].size
        if x + w + gutter > width:
            x, y, shelf = 0, y + shelf + gutter, 0
        positions[name] = (x, y)
        x += w + gutter
        shelf = max(shelf, h)
    atlas = Image.new('RGBA', (width, y + shelf), CLEAR)
    for name, position in positions.items():
        atlas.paste(frames[name][0], position)
    return positions, atlas


def describe(frames, anims, stages, positions, atlas):
    """The JSON the scene reads: where each frame is, its anchor (a fighter's is the floor's centre; an effect's its middle) and the animations by name."""
    return {'version': 1, 'scene': NAME, 'size': list(atlas.size), 'scale': S, 'body_half': BODY_HALF,
            'frames': {name: [*positions[name], *frames[name][0].size] for name in sorted(frames)},
            'anchors': {name: list(frames[name][1]) for name in sorted(frames)},
            'anims': anims, 'stages': stages, 'points': {name: POINTS[name] for name in sorted(POINTS)}, 'shadows': {name: SHADOWS[name] for name in sorted(SHADOWS)}}


def thumbnail(frames):
    """A 240 x 160 picture for the picker: a harbour at dusk, both fighters face to face, a spark between them and the two life bars."""
    w, h = 240, 160
    im = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(im)
    sky = ('#2c4a9c', '#4d5ca8', '#9a6aa0', '#e8806a', '#ff9a52', '#ffc070')
    for k, colour in enumerate(sky):
        d.rectangle((0, k * 15, w, k * 15 + 15), fill=colour)
    d.ellipse((150, 58, 190, 98), fill='#ffd98a')
    d.rectangle((0, 90, w, 112), fill='#2a5f8f')
    for k in range(9):
        d.rectangle((10 + k * 27, 94 + (k * 7) % 14, 26 + k * 27, 95 + (k * 7) % 14), fill='#4a8ab8')
    for x, bw, bh in ((0, 18, 30), (20, 14, 22), (36, 20, 38), (60, 16, 26), (178, 18, 34), (198, 14, 24), (214, 26, 40)):
        d.rectangle((x, 90 - bh, x + bw, 90), fill='#2a2450')
        for wy in range(90 - bh + 4, 88, 7):
            for wx in range(x + 3, x + bw - 2, 5):
                d.point((wx, wy), fill='#ffd36a')
    for k in range(0, 48, 12):
        d.rectangle((0, 112 + k, w, 123 + k), fill='#a8743c' if (k // 12) % 2 == 0 else '#94642f')
        for x in range(((k // 12) * 23) % 46, w, 46):
            d.line((x, 112 + k, x, 123 + k), fill='#6a4422')
    d.rectangle((0, 112, w, 113), fill='#6a4422')

    def put(name, x, y):
        picture, (ax, ay) = frames[name]
        im.paste(picture, (round(x - ax), round(y - ay)), picture)

    put('codex-idle-1', 78, 140)
    put('claude-idle-2', 164, 140)
    put('fx-impact-2', 120, 100)
    for x0, x1 in ((8, 104), (136, 232)):
        d.rectangle((x0 - 2, 6, x1 + 2, 17), fill='#14182c')
        d.rectangle((x0, 8, x1, 15), fill='#6a1a1a')
    d.rectangle((8, 8, 92, 15), fill='#ffd23a')
    d.rectangle((8, 8, 92, 10), fill='#fff29a')
    d.rectangle((148, 8, 232, 15), fill='#ffd23a')
    d.rectangle((148, 8, 232, 10), fill='#fff29a')
    d.rectangle((112, 6, 128, 17), fill='#14182c')
    return im


def write(out, with_manifest=False, private=None, sheet=None):
    """Write the atlas, its JSON and the thumbnail into `out` (owner-only files, atomically); optionally add the scene to `out/scenes.json`."""
    out = Path(out)
    # Only read user-supplied art when its folder was explicitly requested.
    art = private_stage(private) if private is not None else None
    frames, anims, stages = build_sprites(art)
    positions, atlas = pack(frames)
    data = describe(frames, anims, stages, positions, atlas)
    png, json_path, thumb = out / f'scene-{NAME}.png', out / f'scene-{NAME}.json', out / f'thumb-{NAME}.webp'
    if atlas.width > 4096 or atlas.height > 4096:
        raise ValueError('The atlas is bigger than the game contract allows (4096 px)')
    media._write_atomically(png, lambda target: atlas.save(target, format='PNG', optimize=True), media.MAX_IMAGE_BYTES)
    media._write_atomically(json_path, lambda target: target.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True), encoding='utf-8'), 512 * 1024)
    media.save_thumbnail(thumbnail(frames), thumb)
    if sheet:
        contact_sheet(frames, {who: anims[who] for who in ('codex', 'claude')}).save(sheet)
    if with_manifest:
        media.update_manifest(NAME, media.scene_entry('game', png.name, 'image', atlas.width, atlas.height, data=json_path.name), out)
    return {'atlas': str(png), 'frames': len(frames), 'size': list(atlas.size), 'bytes': png.stat().st_size, 'jungle': bool(stages), 'manifest': bool(with_manifest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, required=True, help="folder to write into (the tablet's private folder, or a scratch folder)")
    parser.add_argument('--manifest', action='store_true', help='also add the scene to scenes.json in that folder')
    parser.add_argument('--sheet', type=Path, help='also write a labelled picture of every fighter frame, to look at (not a scene file; keep it out of the repository)')
    parser.add_argument('--private', type=Path, help='optional folder containing your own compatible stage artwork')
    args = parser.parse_args(argv)
    print(json.dumps(write(args.out, args.manifest, args.private, args.sheet)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
