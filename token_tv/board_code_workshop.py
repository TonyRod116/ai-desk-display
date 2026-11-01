"""Code Forge: weekly quota modules feeding a pixel-art software workshop (page 3).

Four stored signal poses run on firmware 7, below the readings. The circuit board,
terminal and branch graph are decorative, never claims about real builds or jobs.
Older boards receive the same scene with its first pose drawn in. No streaming,
randomness, PC-clock animation, new account queries or runtime dependencies.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

from token_tv import board_anim
from token_tv.board_arcade import GOLD, HEART, STONE
from token_tv.board_art import _row
from token_tv.display import pixel_text
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

W, H, SCALE = 160, 120, 2
INK, PANEL, EDGE = '#061019', '#0d1f29', '#28515b'
MINT, DIM, WHITE = '#75efcf', '#276568', '#d7faf0'
BANDS = {'codex': GOLD, 'claude': STONE}
STEP_MS = 200
PATHS = (((36, 78), (36, 84), (54, 93)), ((124, 78), (124, 84), (106, 93)),
         ((58, 102), (45, 110), (34, 110)), ((102, 102), (115, 110), (126, 110)))


def _label(draw, xy, text, size, colour, anchor='lt'):
    """Flat binary glyphs, including symbols absent from the 5x7 bitmap font."""
    font = face('press-start-2p.ttf', size)
    left, top, right, bottom = draw.textbbox(xy, text, font=font, anchor=anchor)
    mask = Image.new('1', (right - left, bottom - top), 0)
    ImageDraw.Draw(mask).text((xy[0] - left, xy[1] - top), text, font=font, anchor=anchor, fill=1)
    draw.bitmap((left, top), mask, fill=colour)


def _module(draw, x, row, provider):
    bands = BANDS[provider]
    value, _, old, reset = remaining_reading(row)
    count, old_hearts = banked_hearts(row)
    draw.polygon(((x + 3, 18), (x + 69, 18), (x + 73, 22), (x + 73, 71),
                  (x + 70, 74), (x + 3, 74), (x, 71), (x, 21)), fill=PANEL, outline=EDGE)
    draw.line((x + 4, 19, x + 67, 19), fill=bands['lo'])
    _label(draw, (x + 5, 23), provider.upper(), 7, bands['mid'])
    if old:
        _label(draw, (x + 55, 24), 'OLD', 5, bands['lo'])
    _label(draw, (x + 36, 32), '--' if value is None else f'{round(value)}%', 14, bands['hi'], 'mt')
    lit = 0 if value is None else math.ceil(value / 5)
    for index in range(20):
        left = x + 6 + index * 3
        colour = '#203740' if index >= lit else (WHITE if index == lit - 1 else bands['mid'])
        draw.rectangle((left, 47, left + 1, 50), fill=colour)
        if old and index < lit:
            draw.point((left, 50), fill=PANEL)
    pace = session_pace(row) if provider == 'claude' else None
    if pace is not None:
        for line, units in enumerate((math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)):
            y = 52 + line * 3
            for index in range(5):
                left = x + 6 + index * 12
                draw.rectangle((left, y, left + 9, y + 1), fill='#26363a')
                amount = max(0, min(1, units - index))
                if amount:
                    draw.rectangle((left, y, left + max(1, round(10 * amount)) - 1, y + 1), fill=STONE['mid'])
    for index in range(3):
        filled = count is not None and count > index
        for yy, line in enumerate(HEART):
            for xx, cell in enumerate(line):
                if cell != '#':
                    continue
                border = any(ny < 0 or ny >= 6 or nx < 0 or nx >= 7 or HEART[ny][nx] != '#'
                             for nx, ny in ((xx - 1, yy), (xx + 1, yy), (xx, yy - 1), (xx, yy + 1)))
                if filled or border:
                    draw.point((x + 6 + index * 9 + xx, 58 + yy),
                               fill=bands['mid'] if filled and not old_hearts else bands['lo'])
    mark = '?' if count is None else ('+' if count > 3 else '') + ('OLD' if old_hearts else '')
    if mark:
        _label(draw, (x + 35, 59), mark, 5, bands['lo'])
    pixel_text(draw, (x + 5, 66), 'RESET', color=bands['hi'])
    pixel_text(draw, (x + 71, 66), reset.upper(), color=bands['hi'], align='right')


def _workshop(draw):
    # Routed tracks rather than a dense grid: all geometry stays on logical pixels.
    draw.line((40, 74, 40, 77, 36, 77, 36, 78), fill=GOLD['lo'])
    draw.line((120, 74, 120, 77, 124, 77, 124, 78), fill=STONE['lo'])
    for index, path in enumerate(PATHS):
        draw.line(path, fill='#102e38', width=3)
        draw.line(path, fill=(GOLD['lo'], STONE['lo'], DIM, DIM)[index])
    draw.line((10, 80, 26, 80, 30, 84, 30, 100), fill='#1b3e49')
    draw.line((150, 80, 136, 80, 130, 84, 130, 100), fill='#1b3e49')
    draw.polygon(((80, 81), (111, 96), (80, 115), (49, 96)), fill='#02090f')
    # Socket, two shaded sides, gold pins and the raised silicon die.
    draw.polygon(((80, 77), (112, 93), (80, 111), (48, 93)), fill='#14323d', outline=EDGE)
    for i in range(1, 7):
        x, y = 48 + i * 4, 93 + i * 2
        draw.line((x, y, x, y + 3), fill=GOLD['lo'])
        x = 112 - i * 4
        draw.line((x, y, x, y + 3), fill='#439791')
    draw.polygon(((56, 91), (80, 104), (80, 109), (56, 96)), fill='#13404a')
    draw.polygon(((80, 104), (104, 91), (104, 96), (80, 109)), fill='#092e38')
    draw.polygon(((80, 79), (104, 91), (80, 104), (56, 91)), fill='#205a5e', outline='#48968c')
    draw.polygon(((80, 83), (97, 91), (80, 100), (63, 91)), fill=INK, outline=MINT)
    _label(draw, (80, 91), '>_', 10, WHITE, 'mm')
    # Mini editor and commit branches frame the chip. No fake compilation/status text.
    draw.rectangle((5, 88, 29, 111), fill='#091923', outline=EDGE)
    draw.line((6, 94, 28, 94), fill=EDGE)
    for x, colour in ((8, GOLD['mid']), (12, MINT), (16, STONE['mid'])):
        draw.point((x, 91), fill=colour)
    pixel_text(draw, (8, 96), 'FN', color=MINT)
    _label(draw, (8, 104), '{..}', 5, STONE['mid'])
    draw.rectangle((132, 88, 155, 111), fill='#091923', outline=EDGE)
    pixel_text(draw, (135, 89), 'GIT', color=MINT)
    draw.line((138, 98, 138, 107), fill=DIM)
    draw.line((138, 100, 149, 104, 149, 108), fill=DIM)
    for x, y in ((138, 98), (138, 107), (149, 108)):
        draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=INK, outline=MINT)


def _along(path, progress):
    lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    distance = progress * sum(lengths)
    for a, b, length in zip(path, path[1:], lengths):
        if distance <= length:
            return tuple(round(start + (end - start) * distance / length) for start, end in zip(a, b))
        distance -= length
    return path[-1]


@lru_cache(maxsize=1)
def _signals():
    frames = []
    for phase in range(4):
        layer = Image.new('RGBA', (96, 36), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for index, path in enumerate(PATHS):
            x, y = _along(path, (phase / 4 + index / 8) % 1)
            x, y = x - 32, y - 78
            colour = (GOLD['hi'], STONE['hi'], MINT, MINT)[index]
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill='#1b555b')
            draw.point((x, y), fill=colour)
        # A traveling die highlight, decorative and entirely below the quota modules.
        x, y = ((80, 83), (97, 91), (80, 100), (63, 91))[phase]
        draw.rectangle((x - 33, y - 79, x - 31, y - 77), fill=MINT)
        frames.append(layer)
    return ({'x': 64, 'y': 156, 'frames': frames, 'script': [(i, 0, 0) for i in range(4)],
             'step_ms': STEP_MS},)


def render_forge(snapshot, animated=False):
    canvas = Image.new('RGB', (W, H), '#02090f')
    draw = ImageDraw.Draw(canvas)
    draw.polygon(((5, 0), (154, 0), (159, 5), (159, 114), (154, 119), (5, 119), (0, 114), (0, 5)),
                 fill=INK, outline=EDGE)
    _label(draw, (6, 5), 'CODE FORGE', 8, MINT)
    pixel_text(draw, (119, 1), 'WEEKLY', color=STONE['mid'])
    pixel_text(draw, (107, 8), 'LEFT', color='#82a3a5')
    draw.line((5, 15, 154, 15), fill=EDGE)
    _module(draw, 4, _row(snapshot, 'codex'), 'codex')
    _module(draw, 82, _row(snapshot, 'claude'), 'claude')
    _workshop(draw)
    pixel_text(draw, (7, 112), 'CODE', color='#59918f')
    _label(draw, (153, 113), '</>', 6, MINT, 'rt')
    sprites = _signals()
    if not animated:
        for sprite in sprites:
            pose = sprite['frames'][0]
            canvas.paste(pose, (sprite['x'] // SCALE, sprite['y'] // SCALE), pose)
    image = canvas.resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
    return (image, board_anim.encode(sprites)) if animated else image
