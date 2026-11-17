"""Prepare the private atlas of the tablet's real-time TOKEN RUN scene (`token_tv/tablet_web/game-token-run.js`), offline.

The scene draws its road, sea, mountains and sky in code; this script draws the SPRITES it needs, all original and code-drawn with Pillow in the
style of the board's racer (`token_tv/board_drive.py`: its palettes, palms, convertible and sailboats are reused), and packs them into the files
the tablet's game contract describes:

    scene-token-run.png    the atlas (a PNG of transparent sprites)
    scene-token-run.json   {"frames": {name: [x, y, w, h]}, "anchors": {name: [ax, ay]}, "ladders": {kind: [names by height]}, ...}
    thumb-token-run.webp   240 x 160 picture for the scene picker (a small composition of the same sprites)

    nice -n 15 ionice -c 3 .venv/bin/python -B scripts/prepare_game_token_run.py --out DIR [--manifest]

Every roadside sprite is drawn once per size of a LADDER of heights (nothing is ever resampled by a fraction: the scene picks the nearest
rung), and every frame carries an ANCHOR, the pixel that touches the ground. `--manifest` also adds the scene to the tablet's `scenes.json`
in DIR through `scripts.tablet_media`. No ROM, no game art, no external service or model; nothing is written outside DIR.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import tablet_media as media  # noqa: E402
from token_tv import board_drive  # noqa: E402
from token_tv.board_surf import _mix  # noqa: E402

NAME = 'token-run'
LADDER = (5, 6, 8, 10, 12, 15, 18, 22, 27, 33, 40, 49, 60, 74, 90, 110)      # sprite heights in art pixels, about x1.22 apart
CLEAR = (0, 0, 0, 0)
PALM = board_drive.PALM_TONES
SAND, SAND_DARK = '#f5db91', '#c4a45e'
LEAF, LEAF_LIGHT, LEAF_DARK = '#2f8a3c', '#56bf55', '#1f6a30'
WALL, WALL_SHADE, ROOF, GLASS = '#f5eee0', '#cbbcb3', '#ca5a42', '#467386'


class Sprite:
    """A transparent picture with a ground anchor (the pixel that touches the road)."""

    def __init__(self, width, height):
        self.image = Image.new('RGBA', (width, height), CLEAR)
        self.draw = ImageDraw.Draw(self.image)
        self.anchor = (width // 2, height - 1)

    def finish(self, margin=0):
        """Trim the empty border but keep the anchor in the middle of the new width, so a sprite stays centred on its ground point."""
        box = self.image.getbbox()
        if box is None:
            raise ValueError('an empty sprite')
        ax, ay = self.anchor
        half = max(ax - box[0], box[2] - 1 - ax) + margin
        left, top, bottom = ax - half, max(0, box[1] - margin), min(self.image.height, box[3] + margin)
        picture = Image.new('RGBA', (2 * half + 1, bottom - top), CLEAR)
        picture.paste(self.image.crop((max(0, left), top, ax + half + 1, bottom)), (max(0, -left), 0))
        return picture, (half, min(ay - top, picture.height - 1))


def rect(d, x0, y0, x1, y1, fill):
    if x1 >= x0 and y1 >= y0:
        d.rectangle((round(x0), round(y0), round(x1), round(y1)), fill=fill)


def shade(colour, amount):
    """A '#rrggbb' colour darker (negative) or lighter (positive) by a fraction."""
    return _mix(colour, '#000000', -amount) if amount < 0 else _mix(colour, '#ffffff', amount)


# ---- scenery ----------------------------------------------------------------------------------------------------------------------------

def palm(height, variant=0):
    """The board's roadside palm at the trunk size that makes the whole tree `height` pixels tall; variant 1 is a shorter, fuller one."""
    size = max(2, round(height / (1.45 if variant else 1.6)))
    reach = (round(size * .55) + 6) if size >= 10 else (max(3, size // 2 + 1) + 4)
    sprite = Sprite(2 * reach + 3, size + (round(size * .6) + 4) + 6)
    base = sprite.image.height - 4
    sprite.anchor = (sprite.image.width // 2, base)
    board_drive._palm(sprite.draw, sprite.anchor[0], base, size)
    if variant and size >= 12:                                                    # a second, lower ring of fronds makes the crown fuller
        top = base - size
        for angle in (-155, -118, -62, -25):
            board_drive._frond(sprite.draw, sprite.anchor[0], top + 1, angle, round(size * .5), size * .45, PALM)
    return sprite.finish()


def bush(height):
    sprite = Sprite(int(height * 1.6) + 6, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    d = sprite.draw
    sprite.anchor = (cx, base)
    w = max(2, round(height * .62))
    d.ellipse((cx - w, base - height, cx + w, base), fill=LEAF)
    if height >= 8:
        d.ellipse((cx - w, base - height, cx + w - max(1, w // 3), base - height * .45), fill=LEAF_LIGHT)
        d.line((cx - w + 1, base, cx + w - 1, base), fill=LEAF_DARK)
    if height >= 18:                                                              # blossom and a second lobe
        d.ellipse((cx + w // 3, base - height * .8, cx + w + w // 3, base - height * .1), fill=LEAF)
        for k in range(height // 9):
            d.point((cx - w // 2 + k * 3, base - height // 2 - k % 2 * 2), fill='#f6a6c8')
    return sprite.finish()


def pine(height):
    """A Mediterranean umbrella pine: a slim trunk and a flat, wide canopy."""
    sprite = Sprite(int(height * 1.4) + 8, height + 6)
    cx, base = sprite.image.width // 2, sprite.image.height - 3
    d = sprite.draw
    sprite.anchor = (cx, base)
    crown = max(2, round(height * .34))
    trunk_w = 0 if height < 12 else 1 if height < 40 else 2
    rect(d, cx - trunk_w // 2, base - height + crown, cx + (trunk_w + 1) // 2 - (1 if trunk_w else 0), base, '#6a421f')
    top = base - height
    half = max(2, round(height * .58))
    d.ellipse((cx - half, top, cx + half, top + crown * 1.5), fill=LEAF)
    d.ellipse((cx - half + 1, top, cx + half - max(1, half // 3), top + crown), fill=LEAF_LIGHT)
    if height >= 15:
        d.ellipse((cx - half // 2, top - crown // 3, cx + half // 2, top + crown), fill=LEAF_LIGHT)
        d.line((cx - half + 2, top + crown * 1.4, cx + half - 2, top + crown * 1.4), fill=LEAF_DARK)
        rect(d, cx - 1, base - height + crown * 1.2, cx + (1 if height >= 40 else 0), base - height + crown * 2.2, '#4a2e14')
    return sprite.finish()


def rock(height, variant=0):
    sprite = Sprite(int(height * 2.2) + 6, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    d = sprite.draw
    sprite.anchor = (cx, base)
    w = height * (1.0 if variant == 0 else .8)
    body = [(-w, 0), (-w * .9, -height * .45), (-w * .35, -height), (w * .25, -height * .92), (w * .85, -height * .5), (w, 0)]
    pts = [(cx + x, base + y) for x, y in body]
    d.polygon(pts, fill='#7e776c')
    lit = [(cx + x, base + y) for x, y in ((-w, 0), (-w * .9, -height * .45), (-w * .35, -height), (-w * .05, -height * .55), (-w * .3, 0))]
    d.polygon(lit, fill='#aaa292')
    d.line((cx + w * .85, base - height * .45, cx + w, base), fill='#5a554d')
    d.line((cx - w, base, cx + w, base), fill='#4a463f')
    if height >= 14:
        d.line((cx - w * .1, base - height * .7, cx + w * .35, base - height * .25), fill='#5a554d')
        d.point((cx + w * .6, base - height * .35), fill='#8d8579')
    if height >= 24:
        small = [(cx + x, base + y) for x, y in ((w * 1.0, 0), (w * 1.05, -height * .22), (w * 1.5, -height * .3), (w * 1.7, 0))]
        d.polygon(small, fill='#7e776c')
        d.line((cx + w * 1.0, base - height * .22, cx + w * 1.5, base - height * .3), fill='#aaa292')
    return sprite.finish()


def post(height):
    """A white reflector post with a red band."""
    sprite = Sprite(7, height + 2)
    cx, base = 3, sprite.image.height - 1
    thick = 1 if height < 20 else 2 if height < 50 else 3
    sprite.anchor = (cx, base)
    rect(sprite.draw, cx - thick // 2, base - height + 1, cx - thick // 2 + thick - 1, base, '#fff3d6')
    rect(sprite.draw, cx - thick // 2, base - height + 1, cx - thick // 2 + thick - 1, base - height + max(1, height // 4), '#e64b36')
    if thick > 1:
        rect(sprite.draw, cx - thick // 2 + thick - 1, base - height + 1, cx - thick // 2 + thick - 1, base, '#bdb29a')
    return sprite.finish()


def sign(height, variant=0):
    """A roadside board on a pole; variant 0 a yellow chevron board, 1 a blue one with a white sun-over-waves symbol (no letters, no numbers)."""
    board = max(4, round(height * .55))
    width = board if variant == 0 else round(board * 1.15)
    sprite = Sprite(width + 10, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    d = sprite.draw
    sprite.anchor = (cx, base)
    rect(d, cx, base - height + board, cx, base, '#8d949b')
    x0, y0 = cx - width // 2, base - height
    fill = '#f2c230' if variant == 0 else '#1f64b4'
    rect(d, x0, y0, x0 + width - 1, y0 + board - 1, fill)
    if board >= 8:
        rect(d, x0, y0, x0 + width - 1, y0, shade(fill, .35))
        rect(d, x0, y0 + board - 1, x0 + width - 1, y0 + board - 1, shade(fill, -.35))
    mid, ink = y0 + board // 2, '#1a1f2a' if variant == 0 else '#ffffff'
    if variant == 0 and board >= 6:                                                # a chevron pointing right
        step = max(1, board // 6)
        for k in range(max(2, board // 3)):
            d.line((x0 + width // 2 - step * 2 + k, mid - board // 3 + k, x0 + width // 2 - step * 2 + k + step * 2, mid), fill=ink)
            d.line((x0 + width // 2 - step * 2 + k, mid + board // 3 - k, x0 + width // 2 - step * 2 + k + step * 2, mid), fill=ink)
    elif board >= 8:
        d.ellipse((cx - board // 6, y0 + board // 5, cx + board // 6, y0 + board // 5 + board // 3), fill='#ffd23a')
        d.line((x0 + 1, mid + board // 5, x0 + width - 2, mid + board // 5), fill=ink)
        d.line((x0 + 1, mid + board // 5 + max(1, board // 8) + 1, x0 + width - 2, mid + board // 5 + max(1, board // 8) + 1), fill='#8fd0f0')
    return sprite.finish()


def billboard(height):
    """A big board on two posts; its picture is a sunset over waves with a palm (no words)."""
    panel_h = max(4, round(height * .6))
    panel_w = round(panel_h * 2.1)
    sprite = Sprite(panel_w + 8, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    d = sprite.draw
    sprite.anchor = (cx, base)
    top = base - height
    leg = max(1, panel_w // 14)
    for x in (cx - panel_w // 2 + panel_w // 6, cx + panel_w // 2 - panel_w // 6 - leg + 1):
        rect(d, x, top + panel_h, x + leg - 1, base, '#5b5f66')
    x0, x1 = cx - panel_w // 2, cx + panel_w // 2
    frame = max(1, panel_h // 12)
    rect(d, x0, top, x1, top + panel_h - 1, '#2b2f38')
    inner = (x0 + frame, top + frame, x1 - frame, top + panel_h - 1 - frame)
    h = inner[3] - inner[1] + 1
    for k, colour in enumerate(('#ffb347', '#ff8a5c', '#d9588a', '#6a4fa0')[:max(2, min(4, h // 2))]):                 # a banded sunset sky
        rect(d, inner[0], inner[1] + k * (h * 3 // 5) // 4, inner[2], inner[1] + (k + 1) * (h * 3 // 5) // 4 - 1, colour)
    sea = inner[1] + h * 3 // 5
    rect(d, inner[0], sea, inner[2], inner[3], '#1b7fa6')
    if h >= 7:
        sun_r = max(1, h // 5)
        d.ellipse((cx - panel_w // 5 - sun_r, sea - sun_r * 2, cx - panel_w // 5 + sun_r, sea), fill='#fff1b0')
        rect(d, inner[0], sea + 1, inner[2], sea + 1, '#ffd98a')
        px = cx + panel_w // 4
        rect(d, px, sea - h // 3, px, sea, '#2a1f2b')
        d.line((px - max(1, h // 6), sea - h // 3 + 1, px + max(1, h // 6), sea - h // 3 + 1), fill='#1c4d36')
        d.line((px, sea - h // 3, px - max(1, h // 5), sea - h // 3 + 2), fill='#1c4d36')
        d.line((px, sea - h // 3, px + max(1, h // 5), sea - h // 3 + 2), fill='#1c4d36')
    return sprite.finish()


def house(height, variant=0):
    """A coastal house: white walls (or sand with blue shutters), a terracotta roof, shuttered windows, a door and, when big, a balcony."""
    body = max(3, round(height * .68))
    width = max(5, round(body * 1.5))
    sprite = Sprite(width + 8, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    d = sprite.draw
    sprite.anchor = (cx, base)
    x0, x1 = cx - width // 2, cx + width // 2
    wall, wall_shade = (WALL, WALL_SHADE) if variant == 0 else ('#efd9a8', '#c9b07c')
    shutter = '#467386' if variant == 0 else '#2d6cb4'
    roof_top = base - body
    rect(d, x0, roof_top, x1, base, wall)
    rect(d, x1 - max(1, width // 7), roof_top, x1, base, wall_shade)                               # the shaded side
    roof_h = height - body
    if roof_h >= 2:
        d.polygon([(x0 - 1, roof_top), (x0 + width // 4, roof_top - roof_h), (x1 - width // 4, roof_top - roof_h), (x1 + 1, roof_top)], fill=ROOF)
        d.line((x0 + width // 4, roof_top - roof_h, x1 - width // 4, roof_top - roof_h), fill=shade(ROOF, .3))
        d.line((x0 - 1, roof_top, x1 + 1, roof_top), fill=shade(ROOF, -.3))
    if body >= 8:
        win_h, win_w = max(2, body // 4), max(2, width // 6)
        for col in (x0 + width // 6, x0 + width // 2 - win_w // 2 - width // 12, x1 - width // 4 - win_w):
            rect(d, col, roof_top + body // 5, col + win_w - 1, roof_top + body // 5 + win_h - 1, GLASS)
            if win_w >= 3:
                rect(d, col - 1, roof_top + body // 5, col - 1, roof_top + body // 5 + win_h - 1, shutter)
                rect(d, col + win_w, roof_top + body // 5, col + win_w, roof_top + body // 5 + win_h - 1, shutter)
        door_w = max(2, width // 7)
        rect(d, cx - door_w // 2 - width // 10, base - max(3, body // 3), cx + door_w // 2 - width // 10, base, '#6a421f')
    if body >= 24:                                                                                    # a balcony rail and an awning
        rect(d, x0 + width // 8, roof_top + body // 2, x0 + width // 2, roof_top + body // 2, '#3d4a55')
        rect(d, x0 + width // 8, roof_top + body // 2 + 1, x0 + width // 2, roof_top + body // 2 + 1, '#9ab0b8')
        rect(d, x1 - width // 3, base - body // 2, x1 - width // 8, base - body // 2 + 1, '#d94f4f')
    rect(d, x0, base, x1, base, '#8f8478')
    return sprite.finish()


def block(height):
    """A white resort block: rows of balconies and a flat roof with a small stair house."""
    width = max(5, round(height * .62))
    sprite = Sprite(width + 8, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    d = sprite.draw
    sprite.anchor = (cx, base)
    x0, x1, top = cx - width // 2, cx + width // 2, base - height
    rect(d, x0, top, x1, base, '#f5eee0')
    rect(d, x1 - max(1, width // 6), top, x1, base, '#cbbcb3')
    rect(d, x0 - 1, top, x1 + 1, top, '#ca5a42')
    if height >= 10:
        rows = max(2, height // 6)
        for r in range(rows):
            y = top + 2 + r * (height - 4) // rows
            for c in range(max(2, width // 5)):
                x = x0 + 1 + c * (width - 4) // max(2, width // 5)
                rect(d, x, y, x + max(1, width // 12), y + max(0, height // (rows * 3)), '#467386')
                if height >= 30:
                    rect(d, x, y + height // (rows * 3) + 1, x + max(1, width // 12) + 1, y + height // (rows * 3) + 1, '#9ab0b8')
    if height >= 18:
        rect(d, cx - width // 6, top - max(2, height // 12), cx + width // 6, top - 1, '#e8dfcf')
    return sprite.finish()


def lamp(height):
    sprite = Sprite(max(7, height // 2 + 4), height + 2)
    cx, base = 2, sprite.image.height - 1
    sprite.anchor = (cx, base)
    d = sprite.draw
    rect(d, cx, base - height + 1, cx, base, '#454d57')
    arm = max(2, height // 4)
    rect(d, cx, base - height, cx + arm, base - height, '#454d57')
    rect(d, cx + arm - max(0, height // 14), base - height, cx + arm + max(0, height // 14), base - height + max(1, height // 18), '#fff0b0')
    return sprite.finish()


def parasol(height):
    sprite = Sprite(height + 6, height + 3)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    sprite.anchor = (cx, base)
    d = sprite.draw
    r = max(2, round(height * .5))
    rect(d, cx, base - height + r // 2, cx, base, '#736447')
    d.polygon([(cx - r, base - height + r // 2 + 1), (cx, base - height), (cx + r, base - height + r // 2 + 1)], fill='#f5a2c6')
    d.line((cx - r, base - height + r // 2 + 1, cx + r, base - height + r // 2 + 1), fill='#9c635b')
    if r >= 4:
        d.line((cx, base - height, cx - r // 2, base - height + r // 2 + 1), fill='#ffffff')
        d.line((cx, base - height, cx + r // 2, base - height + r // 2 + 1), fill='#ffffff')
    return sprite.finish()


# ---- sea and sky -----------------------------------------------------------------------------------------------------------------------

def boat(height):
    """A sailboat seen side-on (the board's, drawn bigger when the sprite is): hull, two sails, a pennant, a darker water line below."""
    sprite = Sprite(int(height * 1.2) + 8, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 3
    sprite.anchor = (cx, base)
    d = sprite.draw
    if height <= 10:
        board_drive._boat(d, cx, base - 1, max(1, (height - 2) // 2))
    else:
        hull_w = round(height * .5)
        deck = base - max(1, height // 10)
        rect(d, cx - hull_w, deck, cx + hull_w, base - 1, '#8a2b2b')
        rect(d, cx - hull_w + 1, base - 1, cx + hull_w - 1, base - 1, '#5c1c1c')
        rect(d, cx - hull_w, deck, cx + hull_w, deck, '#f2e6d0')
        top = base - height + 1
        rect(d, cx, top, cx, deck - 1, '#4a3a2a')
        d.polygon([(cx + 1, top + 1), (cx + 1, deck - 1), (cx + hull_w, deck - 1)], fill='#ffffff')
        d.polygon([(cx - 1, top + 3), (cx - 1, deck - 1), (cx - hull_w + 1, deck - 1)], fill='#d6e2f2')
        d.point((cx, top), fill='#d9392b')
        d.line((cx - hull_w - 1, base, cx + hull_w + 1, base), fill='#1588a8')
    return sprite.finish()


def windsurf(height):
    """The board's magenta windsurf sail on a cream board."""
    sprite = Sprite(int(height * .8) + 8, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 3
    sprite.anchor = (cx, base)
    d = sprite.draw
    rect(d, cx, base - height + 1, cx, base - 1, '#243764')
    foot = base - max(2, height // 8)
    d.polygon([(cx - 1, base - height + 3), (cx - 1, foot), (cx - max(2, height // 3), foot)], fill='#d72b80')
    if height >= 12:
        d.polygon([(cx - 2, base - height * .6), (cx - 2, base - height * .4), (cx - height // 6, base - height * .4)], fill='#ffd7dd')
    rect(d, cx - max(2, height // 3), base - max(1, height // 12), cx + max(2, height // 5), base - 1, '#f8e7d8')
    rect(d, cx - max(2, height // 3), base, cx + max(2, height // 5), base, '#1588a8')
    if height >= 16:
        rect(d, cx + 1, base - max(2, height // 5), cx + 1, base - max(1, height // 12) - 1, '#2b4272')
        d.point((cx + 1, base - max(2, height // 5) - 1), fill='#f5c28c')
    return sprite.finish()


def cloud(width, seed=0):
    """A cumulus in the board's flat tones (white top, two greys, a blue-grey underside): round puffs on a flat base, taller in the middle."""
    rnd = random.Random(width * 31 + seed)
    height = max(6, round(width * .34))
    picture = Image.new('RGBA', (width + 6, height + 6), CLEAR)
    base = height + 2
    puffs = []
    count = max(3, width // 8)
    for i in range(count):
        t = (i + .5) / count
        r = max(2, round(height * (.2 + .3 * math.sin(math.pi * t)) * rnd.uniform(.9, 1.05)))      # the tallest puff is about half the cloud's height
        puffs.append((3 + t * (width - 1) + rnd.uniform(-1, 1), base - r + rnd.randint(0, 1), r))
    pixels = picture.load()
    for y in range(picture.height):
        for x in range(picture.width):
            inside = [p for p in puffs if (x - p[0]) ** 2 + (y - p[1]) ** 2 <= p[2] ** 2]
            if not inside or y > base:
                continue
            light = max((p[1] - y) / p[2] + .22 * (p[0] - x) / p[2] for p in inside)
            if y >= base - max(1, height // 6):
                pixels[x, y] = (145, 187, 218, 255)
            elif light < -.5:
                pixels[x, y] = (194, 216, 230, 255)
            elif light < -.16:
                pixels[x, y] = (229, 237, 239, 255)
            else:
                pixels[x, y] = (255, 253, 240, 255)
    return picture.crop(picture.getbbox()), (0, 0)


def gulls():
    """Two sizes of the board's gull, three wing poses each (up, level, down)."""
    small = board_drive._gull_frames()
    shapes = ('X...........X/.XX.......XX./..XXX...XXX../....XXXXX..../.....XXX.....',
              '............./XXXXX...XXXXX/...XXXXXXX.../.....XXX...../.............',
              '............./.....XXX...../..XXXXXXXXX../.XX...X...XX./X.....X.....X')
    medium = []
    for shape in shapes:
        rows = shape.split('/')
        frame = Image.new('RGBA', (13, 5), CLEAR)
        for y, row in enumerate(rows):
            for x, cell in enumerate(row):
                if cell == 'X':
                    frame.putpixel((x, y), (255, 255, 255, 255) if y == 0 or rows[min(4, y + 1)][x] == 'X' else (176, 190, 214, 255))
        medium.append(frame)
    return {'gull-s': small, 'gull-m': medium}


# ---- cars -----------------------------------------------------------------------------------------------------------------------------

def player_car(phase, lean):
    """The board's red convertible (phase 0-3 alternates the tyre tread and a strand of hair); `lean` -2..2 shears its body, never its tyres."""
    picture = Image.new('RGBA', (board_drive.W, board_drive.H), CLEAR)
    board_drive._car(ImageDraw.Draw(picture), phase)
    picture = picture.crop(picture.getbbox())
    padded = Image.new('RGBA', (picture.width + 6, picture.height), CLEAR)
    solid = 9                                                                    # the lowest rows are tyres and shadow: they stay planted
    for y in range(picture.height):
        up = max(0, picture.height - 1 - y - solid)
        shift = round(lean * up / max(1, picture.height - solid))
        padded.paste(picture.crop((0, y, picture.width, y + 1)), (3 + shift, y))
    return padded, (padded.width // 2, padded.height - 3)


def rival(width, body, light, kind=0):
    """Another car seen from behind, `width` pixels wide: kind 0 a low coupe, 1 a van, 2 a hatchback."""
    height = round(width * (.62, .80, .68)[kind])
    sprite = Sprite(width + 8, height + 6)
    cx, base = sprite.image.width // 2, sprite.image.height - 3
    sprite.anchor = (cx, base)
    d = sprite.draw
    x0 = cx - width // 2
    x1 = x0 + width - 1
    if width < 9:
        rect(d, x0, base - 2, x1, base, '#263142')
        rect(d, x0 + 1, base - 3, x1 - 1, base - 3, light)
        rect(d, x0 + 1, base - 1, x1 - 1, base - 1, body)
        if width >= 6:
            rect(d, x0, base - 2, x0, base - 2, '#ff644d')
            rect(d, x1, base - 2, x1, base - 2, '#ff644d')
        return sprite.finish()
    tyre_w, tyre_h = max(1, width // 7), max(2, round(height * .26))
    low = base - tyre_h // 2
    top = base - height + 1
    glass_h = round(height * (.38, .50, .44)[kind])
    body_top = top + glass_h
    rect(d, x0 - 1, base + 1, x1 + 1, base + (1 if width < 22 else 2), '#2a3140')                       # the shadow on the tarmac
    rect(d, x0 + 1, body_top, x1 - 1, low, body)
    rect(d, x0 + 1, low - max(1, height // 9), x1 - 1, low, shade(body, -.32))                         # a darker skirt
    rect(d, x0 + 1, body_top, x1 - 1, body_top, light)                                                 # the lit rear deck
    cabin = x0 + max(2, width // 6)
    taper = max(1, width // 12) if kind != 1 else 0
    d.polygon([(cabin, body_top), (cabin + taper, top), (x1 - (cabin - x0) - taper, top), (x1 - (cabin - x0), body_top)], fill=shade(body, -.1))
    pane = max(1, width // 14)
    rect(d, cabin + pane, top + 1, x1 - (cabin - x0) - pane, body_top - 1, '#18334c')                  # the rear window
    if glass_h >= 4:
        rect(d, cabin + pane, top + 1, x1 - (cabin - x0) - pane, top + 1, '#7fb6c8')
    rect(d, x0, base - tyre_h + 1, x0 + tyre_w - 1, base, '#16161e')
    rect(d, x1 - tyre_w + 1, base - tyre_h + 1, x1, base, '#16161e')
    lamp_w, lamp_h = max(1, width // 6), max(1, height // 9)
    ly = body_top + max(1, (low - body_top) // 3)
    for x in (x0 + 1, x1 - lamp_w):
        rect(d, x, ly, x + lamp_w - 1, ly + lamp_h - 1, '#ff3b2f')
        if lamp_w >= 3:
            rect(d, x + 1, ly, x + lamp_w - 2, ly, '#ff9a80')
    plate_w = max(2, width // 5)
    rect(d, cx - plate_w // 2, ly + lamp_h, cx + plate_w // 2, ly + lamp_h + max(0, height // 10), '#f7ebc4')
    if width >= 20:
        rect(d, x0 + 1, low - max(1, height // 9) - 1, x1 - 1, low - max(1, height // 9) - 1, '#33333f')           # the bumper line
    return sprite.finish()


RIVAL_STYLES = (('blue', '#1e74bc', '#55d3ed', 0), ('yellow', '#e3a524', '#ffe77e', 2), ('white', '#e9e6dc', '#ffffff', 1),
                ('teal', '#22a58f', '#8af0d8', 0), ('orange', '#e8742b', '#ffc27a', 2), ('violet', '#7a4fb8', '#c9a8f2', 0),
                ('green', '#3a8f3f', '#a6e08a', 1), ('black', '#2c3038', '#7e8794', 0))
RIVAL_WIDTHS = (5, 6, 8, 10, 12, 15, 18, 22, 27, 33, 40, 49)
BRIDGE_WIDTHS = (24, 32, 42, 54, 70, 90, 116, 150, 190, 240, 300, 380, 480)


def bridge(width):
    """An overpass the road runs under: two pillars outside the kerbs, a deck with a railing and a dark underside; the opening is transparent."""
    height = round(width * .42)
    sprite = Sprite(width + 4, height + 4)
    cx, base = sprite.image.width // 2, sprite.image.height - 2
    sprite.anchor = (cx, base)
    d = sprite.draw
    x0, x1 = cx - width // 2, cx + width // 2
    deck_h = max(2, round(height * .17))
    deck_top = base - height
    pillar = max(2, round(width * .075))
    rect(d, x0, deck_top, x1, deck_top + deck_h, '#b9b2a6')
    rect(d, x0, deck_top + deck_h - 1, x1, deck_top + deck_h, '#6f6a62')
    rect(d, x0, deck_top + deck_h + 1, x1, deck_top + deck_h + max(1, deck_h // 2), '#2a2d35')                  # the shadowed underside
    rail = max(1, deck_h // 3)
    rect(d, x0, deck_top - rail, x1, deck_top - 1, '#8f8a80')
    for k in range(0, width, max(3, width // 14)):
        rect(d, x0 + k, deck_top - rail, x0 + k, deck_top, '#d8d2c6')
    rect(d, x0, deck_top - rail, x1, deck_top - rail, '#e4ded2')
    for left in (x0, x1 - pillar + 1):
        rect(d, left, deck_top + deck_h + 1, left + pillar - 1, base, '#c9c2b6')
        rect(d, left + pillar - max(1, pillar // 3), deck_top + deck_h + 1, left + pillar - 1, base, '#8f8a80')
    return sprite.finish()


# ---- the atlas ---------------------------------------------------------------------------------------------------------------------------

def rungs(low, high):
    return [h for h in LADDER if low <= h <= high]


def build_sprites():
    """({frame name: (RGBA picture, (anchor x, anchor y))}, {ladder name: [frame names, smallest first]}), in a fixed order."""
    frames, ladders = {}, {}

    def add(ladder, name, made):
        frames[name] = made
        ladders.setdefault(ladder, []).append(name)

    for variant in (0, 1):
        for h in rungs(8, 110):
            add(f'palm{variant}', f'palm{variant}-{h:03d}', palm(h, variant))
    for kind, make, low, high in (('pine', pine, 8, 90), ('bush', bush, 5, 49), ('post', post, 5, 49), ('lamp', lamp, 12, 74), ('parasol', parasol, 5, 40),
                                  ('block', block, 12, 110), ('billboard', billboard, 10, 110), ('boat', boat, 5, 60), ('windsurf', windsurf, 8, 60)):
        for h in rungs(low, high):
            add(kind, f'{kind}-{h:03d}', make(h))
    for variant in (0, 1):
        for h in rungs(5, 60):
            add(f'rock{variant}', f'rock{variant}-{h:03d}', rock(h, variant))
        for h in rungs(8, 74):
            add(f'sign{variant}', f'sign{variant}-{h:03d}', sign(h, variant))
        for h in rungs(8, 90):
            add(f'house{variant}', f'house{variant}-{h:03d}', house(h, variant))
    for width in BRIDGE_WIDTHS:
        add('bridge', f'bridge-{width:03d}', bridge(width))
    for width in (16, 24, 34, 48, 66, 90):
        add('cloud', f'cloud-{width:03d}', cloud(width))
    for kind, poses in gulls().items():
        for k, pose in enumerate(poses):
            add(kind, f'{kind}-{k}', (pose, (pose.width // 2, pose.height - 1)))
    for lean in range(-2, 3):
        for phase in range(board_drive.PHASES):
            add('car', f'car-{lean + 2}-{phase}', player_car(phase, lean))
    for colour, body, light, style in RIVAL_STYLES:
        for width in RIVAL_WIDTHS:
            add(f'rival-{colour}', f'rival-{colour}-{width:02d}', rival(width, body, light, style))
    # Generic artwork keeps the newer optional roadside sights working even
    # when a private arcade atlas is unavailable. The private builder replaces
    # these aliases with its separately prepared authentic sprite ladders.
    for alias, existing in (('windmill', 'block'), ('billboard1', 'billboard'), ('icecream', 'sign0'),
                            ('crowd', 'bush'), ('forksign', 'sign1')):
        ladders[alias] = list(ladders[existing])
    for ladder in ladders.values():
        ladder.sort(key=lambda name: (frames[name][0].height, name))
    return frames, ladders


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


def describe(frames, ladders, positions, atlas):
    """The JSON the scene reads: where each frame is, its ground anchor and the ladders (names by height)."""
    return {'version': 1, 'scene': NAME, 'size': list(atlas.size), 'ladder_heights': list(LADDER),
            'frames': {name: [*positions[name], *frames[name][0].size] for name in sorted(frames)},
            'anchors': {name: list(frames[name][1]) for name in sorted(frames)},
            'ladders': {name: ladders[name] for name in sorted(ladders)}}


def thumbnail(frames):
    """A 240 x 160 picture for the scene picker: sky, sea, a bend of road, a few of the atlas's own sprites and the red convertible."""
    width, height, horizon = 240, 160, 50
    picture = Image.new('RGB', (width, height), board_drive.HAZE)
    d = ImageDraw.Draw(picture)
    for k, (row, colour) in enumerate(board_drive.SKY):
        d.rectangle((0, max(0, row * horizon // 50), width, (board_drive.SKY[k + 1][0] * horizon // 50 - 1) if k + 1 < len(board_drive.SKY) else horizon), fill=colour)
    d.polygon([(110, horizon), (140, horizon - 14), (160, horizon - 10), (190, horizon - 26), (215, horizon - 14), (240, horizon - 20), (240, horizon)], fill='#438c9f')
    for y in range(horizon, height):
        t = y - horizon
        half = 3 + t * .95
        centre = 128 + 20 * max(0, 1 - t / (height - horizon)) ** 2
        dark = ((70 / (t / 1.7 + 4) + 0) % 1.0) < .5
        d.line((0, y, width, y), fill='#66bf43' if dark else '#59af39')
        shore = centre - half - 14 - t * .5
        d.line((0, y, centre + half + 3, y), fill=SAND)
        d.line((0, y, shore, y), fill='#1dbabf' if t < 12 else '#35d4cc')
        d.line((shore + 1, y, shore + 2 + t * .04, y), fill='#e5fff1')
        kerb = max(1, round(1 + t * .06))
        d.line((centre - half - kerb, y, centre + half + kerb, y), fill=board_drive.RED if dark else board_drive.WHITE)
        d.line((centre - half, y, centre + half, y), fill=board_drive.ASPHALT[0] if dark else board_drive.ASPHALT[1])
        if not dark:
            for side in (-1, 1):
                x = centre + side * half / 3
                d.line((x, y, x + max(0, t * .03), y), fill='#fff7e4')

    def put(name, x, y):
        picture_, (ax, ay) = frames[name]
        picture.paste(picture_, (round(x - ax), round(y - ay)), picture_)

    put('windsurf-012' if 'windsurf-012' in frames else 'windsurf-010', 40, horizon + 12)
    put('boat-010', 84, horizon + 7)
    put('house0-022', 190, horizon + 15)
    put('palm0-033', 52, horizon + 55)
    put('palm0-049', 18, horizon + 100)
    put('palm1-027', 176, horizon + 36)
    put('pine-040', 218, horizon + 76)
    put('rival-blue-15', 128, horizon + 34)
    put('rival-yellow-27', 154, horizon + 62)
    sky_cloud = frames['cloud-066'][0]
    picture.paste(sky_cloud, (30, 12), sky_cloud)
    put('car-2-0', 128, height - 6)
    return picture


def write(out, with_manifest=False):
    """Write the atlas, its JSON and the thumbnail into `out` (owner-only files, atomically); optionally add the scene to `out/scenes.json`."""
    out = Path(out)
    frames, ladders = build_sprites()
    positions, atlas = pack(frames)
    data = describe(frames, ladders, positions, atlas)
    png, json_path, thumb = out / f'scene-{NAME}.png', out / f'scene-{NAME}.json', out / f'thumb-{NAME}.webp'
    if atlas.width > 4096 or atlas.height > 4096:
        raise ValueError('The atlas is bigger than the game contract allows (4096 px)')
    media._write_atomically(png, lambda target: atlas.save(target, format='PNG', optimize=True), media.MAX_IMAGE_BYTES)
    media._write_atomically(json_path, lambda target: target.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True), encoding='utf-8'), 512 * 1024)
    media.save_thumbnail(thumbnail(frames), thumb)
    if with_manifest:
        media.update_manifest(NAME, media.scene_entry('game', png.name, 'image', atlas.width, atlas.height, data=json_path.name), out)
    return {'atlas': str(png), 'frames': len(frames), 'size': list(atlas.size), 'bytes': png.stat().st_size, 'manifest': bool(with_manifest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, required=True, help='folder to write into (the tablet\'s private folder, or a scratch folder)')
    parser.add_argument('--manifest', action='store_true', help='also add the scene to scenes.json in that folder')
    args = parser.parse_args(argv)
    print(json.dumps(write(args.out, args.manifest)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
