"""the reference fine skyline photograph with aerial traffic and breathing neon.

Only disjoint small sprites move; the native photo and weekly instruments stay
sharp. Motion is decorative, independent of readings and the PC clock.
"""
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageDraw

from token_tv import board_anim, board_reset_icons as icons
from token_tv.board_arcade import GOLD, STONE
from token_tv.board_art import _row
from token_tv.display import pixel_text
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

W, H, SCALE = 160, 120, 2
INK, PANEL, EDGE = '#09091a', '#0c1d2a', '#294454'
WHITE = '#deedf3'
MINT, TEAL = '#79e9f2', '#5788c9'
BANDS = {'codex': GOLD, 'claude': STONE}
STEP_MS, STEPS = 140, 32
ART_BOX = (0, 24, 174, 240)
EMBLEM_BOX = (16, 36, 42, 58)
SIGN_BOX = (26, 170, 42, 192)


def _label(draw, xy, text, size, colour, anchor='lt'):
    """Flat binary glyphs: no smoothing or one-pixel shimmer on the panel."""
    font = face('press-start-2p.ttf', size)
    left, top, right, bottom = draw.textbbox(xy, text, font=font, anchor=anchor)
    mask = Image.new('1', (right - left, bottom - top), 0)
    ImageDraw.Draw(mask).text((xy[0] - left, xy[1] - top), text, font=font, anchor=anchor, fill=1)
    draw.bitmap((left, top), mask, fill=colour)


def _resets(draw, x, y, row, bands):
    """One neon lightning bolt per saved reset (the user, 2026-10-20: something of the screen's own instead of hearts). While the
    number is unknown or old the bolts stay and one faint dot ends the row: no `?` and no OLD."""
    count, old = banked_hearts(row)
    have = count if count is not None else 0
    for index in range(3):
        lit = have > index
        for xx, yy in ([(a, b) for a, b, _, _ in icons.cells('bolt')] if lit else icons.hollow('bolt')):
            draw.point((x + index * 7 + xx, y + yy), fill=bands['mid'] if lit and not old else bands['lo'])
    end = x + 21
    if icons.marked(count, old):
        draw.point((end, y + 2), fill=bands['lo'])
        end += 3
    mark = icons.mark(count, old)
    if mark:
        pixel_text(draw, (end, y + 6), mark, color=bands['hi'])


def _module(draw, y, row, provider):
    x, bottom = 90, y + 53
    bands = BANDS[provider]
    value, _, old, reset = remaining_reading(row)
    draw.polygon(((x + 2, y), (153, y), (155, y + 2), (155, bottom - 2),
                  (153, bottom), (x + 2, bottom), (x, bottom - 2), (x, y + 2)),
                 fill=PANEL, outline=EDGE)
    draw.line((x + 3, y + 1, 151, y + 1), fill=bands['lo'])
    pixel_text(draw, (x + 4, y + 3), provider.upper(), color=bands['mid'])
    _resets(draw, x + 41, y + 4, row, bands)
    if old:
        pixel_text(draw, (x + 4, y + 10), 'OLD', color=bands['lo'])
    number = '--' if value is None else f'{round(value)}%'
    width = (len(number) * 6 - 1) * 2
    pixel_text(draw, (x + 32 - width // 2, y + 17), number, scale=2, color=bands['hi'])
    lit = 0 if value is None else math.ceil(value / 5)
    for index in range(20):
        left = x + 4 + index * 3
        colour = '#233542' if index >= lit else WHITE if index == lit - 1 else bands['mid']
        draw.rectangle((left, y + 32, left + 1, y + 39), fill=colour)
        if old and index < lit:
            draw.point((left, y + 39), fill=PANEL)
    pace = session_pace(row) if provider == 'claude' else None
    if pace is not None:
        for line, units in enumerate((math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)):
            yy = y + 41 + line * 3
            for index in range(5):
                left = x + 13 + index * 8
                draw.rectangle((left, yy, left + 5, yy + 1), fill='#26363a')
                amount = max(0, min(1, units - index))
                if amount:
                    draw.rectangle((left, yy, left + max(1, round(6 * amount)) - 1, yy + 1), fill=STONE['mid'])
    yy = y + 47
    pixel_text(draw, (x + 3, yy), 'RESET', color=bands['lo'])
    pixel_text(draw, (x + 63, yy), reset.upper().replace(' ', ''), color=bands['hi'], align='right')



@lru_cache(maxsize=1)
def _city():
    canvas = Image.new('RGB', (W, H), '#030b13')
    draw = ImageDraw.Draw(canvas)
    draw.polygon(((4, 0), (155, 0), (159, 4), (159, 115), (155, 119),
                  (4, 119), (0, 115), (0, 4)), fill=INK, outline=EDGE)
    _label(draw, (5, 2), 'NEON CITY', 8, MINT)
    draw.line((4, 10, 82, 10), fill=TEAL)
    canvas = canvas.resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
    # Native one-pixel detail; no 160x120 intermediate, reduced palette, colour
    # grading or enlargement grid is ever applied to the user's skyline.
    with Image.open(Path(__file__).with_name('assets') / 'neon-city.png') as photo:
        if photo.size != (174, 216):
            raise ValueError('Neon City needs the prepared native skyline crop')
        canvas.paste(photo.convert('RGB'), ART_BOX[:2])
    return canvas


def _car(phase, distant=False):
    size = (11, 4) if distant else (18, 7)
    frame = Image.new('RGBA', size)
    if phase == 3:
        return frame  # disappearing at the edge makes the loop re-entry gentle
    draw = ImageDraw.Draw(frame)
    cyan = '#82e5f5' if phase else '#497d94'
    pink = '#f467ac' if phase else '#8c4b78'
    hull = '#161d38' if phase else '#182137'
    if distant:
        draw.polygon(((1, 2), (4, 0), (7, 0), (10, 2), (8, 3), (2, 3)),
                     fill=hull, outline='#66749d')
        draw.line((4, 1, 7, 1), fill=cyan)
        draw.line((3, 3, 8, 3), fill=pink)
        draw.point((0, 2), fill='#ffe197')
        draw.point((9, 2), fill=cyan)
    else:
        draw.line((0, 4, 3, 4), fill=pink)
        draw.polygon(((3, 3), (6, 2), (8, 1), (12, 1), (14, 3),
                      (17, 4), (15, 5), (4, 5)), fill=hull, outline='#6375a5')
        draw.line((8, 2, 12, 2), fill=cyan)
        draw.point((10, 2), fill='#d6f6fc')
        draw.line((5, 4, 14, 4), fill='#324569')
        draw.line((5, 6, 13, 6), fill=pink)
        draw.line((15, 4, 16, 4), fill=cyan)
        draw.point((3, 4), fill='#ffe197')
        if phase == 2:
            draw.line((0, 3, 2, 3), fill='#8c67e2')
            draw.point((1, 4), fill='#ffc5ec')
    return frame


def _neon(box, phase):
    """Light only existing warm sign pixels; keep the underlying fine photo."""
    left, top, right, bottom = box
    frame = Image.new('RGBA', ((right - left) // 2, (bottom - top) // 2))
    if phase == 0:
        return frame
    source = _city().load()
    gain = (0, .16, .34, .56)[phase]
    for y in range(frame.height):
        for x in range(frame.width):
            pixels = [source[left + 2 * x + dx, top + 2 * y + dy]
                      for dy in (0, 1) for dx in (0, 1)]
            rgb = tuple(sum(p[k] for p in pixels) / 4 for k in range(3))
            # Orange/magenta neon, not black facade, architecture or sky.
            if rgb[0] < 90 or rgb[0] < rgb[1] * 1.18:
                continue
            colour = tuple(min(248, round(c * (1 + gain))) for c in rgb)
            frame.putpixel((x, y), colour + (255,))
    return frame


@lru_cache(maxsize=1)
def _city_motion():
    # Restoration covers the full old/new sprite boxes. These four lanes never
    # intersect each other or the HUD, even when every transparent texel counts.
    glow = tuple((i // 4 if i < 16 else (31 - i) // 4) for i in range(STEPS))

    def pose(index):
        if index in (0, 30, 31):
            return 3
        if index in (1, 29):
            return 0
        return 1 + index % 2

    return (
        {'x': 4, 'y': 120, 'frames': [_car(i) for i in range(4)],
         'script': [(pose(i), round(127 * i / 31), (i // 4) % 2) for i in range(STEPS)],
         'step_ms': STEP_MS},
        {'x': 148, 'y': 85, 'frames': [_car(i, distant=True) for i in range(4)],
         'script': [(pose(i), -round(128 * i / 31), -((i // 8) % 2)) for i in range(STEPS)],
         'step_ms': STEP_MS},
        {'x': EMBLEM_BOX[0], 'y': EMBLEM_BOX[1],
         'frames': [_neon(EMBLEM_BOX, i) for i in range(4)],
         'script': [(level, 0, 0) for level in glow], 'step_ms': STEP_MS},
        {'x': SIGN_BOX[0], 'y': SIGN_BOX[1],
         'frames': [_neon(SIGN_BOX, i) for i in range(4)],
         'script': [(glow[(i + 8) % STEPS], 0, 0) for i in range(STEPS)],
         'step_ms': STEP_MS},
    )


def render_forge(snapshot, animated=False):
    canvas = _city().copy()
    # Keep every established instrument pixel: the user's finer photo never
    # passes through this 2x bitmap path, only the separate HUD column does.
    hud = canvas.resize((W, H), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(hud)
    _module(draw, 10, _row(snapshot, 'codex'), 'codex')
    _module(draw, 65, _row(snapshot, 'claude'), 'claude')
    hud = hud.resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
    canvas.paste(hud.crop((178, 16, 320, 240)), (178, 16))
    sprites = _city_motion()
    if not animated:
        for sprite in sprites:
            pose = sprite['frames'][sprite['script'][0][0]]
            pose = pose.resize((pose.width * SCALE, pose.height * SCALE), Image.Resampling.NEAREST)
            canvas.paste(pose, (sprite['x'], sprite['y']), pose)
    return (canvas, board_anim.encode(sprites)) if animated else canvas
