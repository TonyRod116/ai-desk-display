"""Code Forge: a syntax-coloured editor beside two weekly quota instruments.

The illustrative TypeScript and function diagram move in two disjoint sprites,
entirely to the left of the readings. They never report real files, builds or
account activity. Firmware 7 animates locally; older boards get the first pose.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

from token_tv import board_anim
from token_tv.board_arcade import GOLD, STONE
from token_tv.board_art import _row
from token_tv.display import pixel_text
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

W, H, SCALE = 160, 120, 2
INK, PANEL, EDGE = '#07131e', '#0c1d2a', '#294454'
MINT, DIM, WHITE = '#80dfca', '#3b6d76', '#deedf3'
KEYWORD, TYPE, NAME, PUNCT = '#efb083', '#80dfca', '#91c5f5', '#9aafb9'
BANDS = {'codex': GOLD, 'claude': STONE}
STEP_MS = 480
HEART = ('.#..#.', '######', '######', '.####.', '..##..')
# Valid, compact TypeScript. This is an illustration, not a running editor.
SOURCE = (
    (('type ', KEYWORD), ('Q', TYPE), ('={', PUNCT)),
    ((' w', NAME), (':', PUNCT), ('number', TYPE)),
    ((' b', NAME), (':', PUNCT), ('number', TYPE)),
    (('};', PUNCT),),
    (('const ', KEYWORD), ('f', NAME), ('=', PUNCT)),
    (('(q:', PUNCT), ('Q', TYPE), (')=>', KEYWORD)),
    ((' q', WHITE), ('.', PUNCT), ('w', NAME), (';', PUNCT)),
)


def _label(draw, xy, text, size, colour, anchor='lt'):
    """Flat binary glyphs: no smoothing or one-pixel shimmer on the panel."""
    font = face('press-start-2p.ttf', size)
    left, top, right, bottom = draw.textbbox(xy, text, font=font, anchor=anchor)
    mask = Image.new('1', (right - left, bottom - top), 0)
    ImageDraw.Draw(mask).text((xy[0] - left, xy[1] - top), text, font=font, anchor=anchor, fill=1)
    draw.bitmap((left, top), mask, fill=colour)


def _hearts(draw, x, y, row, bands):
    count, old = banked_hearts(row)
    for index in range(3):
        filled = count is not None and count > index
        for yy, line in enumerate(HEART):
            for xx, cell in enumerate(line):
                if cell != '#':
                    continue
                border = any(ny < 0 or ny >= len(HEART) or nx < 0 or nx >= 6 or HEART[ny][nx] != '#'
                             for nx, ny in ((xx - 1, yy), (xx + 1, yy), (xx, yy - 1), (xx, yy + 1)))
                if filled or border:
                    draw.point((x + index * 7 + xx, y + yy),
                               fill=bands['mid'] if filled and not old else bands['lo'])
    mark = '?' if count is None else '+' if count > 3 else ''
    if mark:
        pixel_text(draw, (x + 19, y + 6), mark, color=bands['hi'])
    if old:
        pixel_text(draw, (x + 2, y + 6), 'OLD', color=bands['lo'])


def _module(draw, y, row, provider):
    x, bottom = 90, 63 if provider == 'codex' else 114
    bands = BANDS[provider]
    value, _, old, reset = remaining_reading(row)
    draw.polygon(((x + 2, y), (153, y), (155, y + 2), (155, bottom - 2),
                  (153, bottom), (x + 2, bottom), (x, bottom - 2), (x, y + 2)),
                 fill=PANEL, outline=EDGE)
    draw.line((x + 3, y + 1, 151, y + 1), fill=bands['lo'])
    pixel_text(draw, (x + 4, y + 3), provider.upper(), color=bands['mid'])
    _hearts(draw, x + 41, y + 4, row, bands)
    if old:
        pixel_text(draw, (x + 4, y + 10), 'OLD', color=bands['lo'])
    number = '--' if value is None else f'{round(value)}%'
    width = (len(number) * 6 - 1) * 2
    pixel_text(draw, (x + 32 - width // 2, y + 17), number, scale=2, color=bands['hi'])
    lit = 0 if value is None else math.ceil(value / 5)
    for index in range(20):
        left = x + 4 + index * 3
        colour = '#233542' if index >= lit else WHITE if index == lit - 1 else bands['mid']
        draw.rectangle((left, y + 31, left + 1, y + 33), fill=colour)
        if old and index < lit:
            draw.point((left, y + 33), fill=PANEL)
    pace = session_pace(row) if provider == 'claude' else None
    if pace is not None:
        for line, units in enumerate((math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)):
            yy = y + 35 + line * 3
            for index in range(5):
                left = x + 4 + index * 12
                draw.rectangle((left, yy, left + 9, yy + 1), fill='#26363a')
                amount = max(0, min(1, units - index))
                if amount:
                    draw.rectangle((left, yy, left + max(1, round(10 * amount)) - 1, yy + 1), fill=STONE['mid'])
    yy = y + (37 if provider == 'codex' else 41)
    pixel_text(draw, (x + 3, yy), 'RESET', color=bands['lo'])
    pixel_text(draw, (x + 63, yy), reset.upper().replace(' ', ''), color=bands['hi'], align='right')


def _source_line(draw, index):
    y = 32 + index * 8
    pixel_text(draw, (7, y), str(index + 1), color='#577483')
    x = 14
    for text, colour in SOURCE[index]:
        _label(draw, (x, y), text, 8, colour)
        x += len(text) * 8


def _flow(draw, phase=None):
    pixel_text(draw, (7, 91), 'CODE FLOW', color='#7e9ca9')
    draw.line((17, 109, 17, 112, 73, 112, 73, 109), fill='#213c48')
    for x in (28, 55):
        draw.line((x, 104, x + 6, 104), fill=DIM)
        draw.polygon(((x + 5, 102), (x + 7, 104), (x + 5, 106)), fill=DIM)
    for index, (x, text) in enumerate(((8, '{}'), (35, 'fn'), (62, '=>'))):
        active = phase == index
        colour = MINT if active else '#496e7b'
        draw.rectangle((x + 1, 100, x + 20, 110), fill='#020c15')
        draw.polygon(((x + 2, 98), (x + 17, 98), (x + 19, 100), (x + 19, 108),
                      (x, 108), (x, 100)), fill='#173540' if active else PANEL, outline=colour)
        _label(draw, (x + 10, 100), text, 7, WHITE if active else '#91b0bb', 'mt')
    if phase is not None:
        x, y = ((30, 104), (57, 104), (60, 104), (45, 112))[phase]
        draw.rectangle((x - 1, y, x + 1, y), fill=WHITE)


@lru_cache(maxsize=1)
def _editor():
    canvas = Image.new('RGB', (W, H), '#030b13')
    draw = ImageDraw.Draw(canvas)
    draw.polygon(((4, 0), (155, 0), (159, 4), (159, 115), (155, 119), (4, 119), (0, 115), (0, 4)),
                 fill=INK, outline=EDGE)
    _label(draw, (5, 5), 'CODE FORGE', 8, MINT)
    pixel_text(draw, (119, 1), 'WEEKLY', color=STONE['mid'])
    pixel_text(draw, (119, 8), 'LEFT', color='#91b0bb')
    draw.line((4, 15, 155, 15), fill=EDGE)
    draw.rectangle((4, 18, 86, 88), fill='#081722', outline=EDGE)
    draw.rectangle((5, 19, 85, 29), fill='#132b38')
    draw.rectangle((6, 19, 17, 28), fill='#285773')
    pixel_text(draw, (7, 20), 'TS', color=WHITE)
    _label(draw, (20, 20), 'quota.ts', 8, WHITE)
    draw.line((5, 30, 85, 30), fill=EDGE)
    draw.line((13, 30, 13, 86), fill='#173440')
    # Scope guide, not a dense scanline/grid pattern.
    draw.line((17, 39, 17, 52), fill='#2b4a54')
    for index in range(len(SOURCE)):
        _source_line(draw, index)
    _flow(draw)
    return canvas


@lru_cache(maxsize=1)
def _editor_motion():
    poses = []
    for phase in range(4):
        canvas = _editor().copy()
        draw = ImageDraw.Draw(canvas)
        line = (4, 5, 6, 6)[phase]
        y = 32 + line * 8
        draw.rectangle((14, y, 85, y + 7), fill='#173a46' if phase != 3 else '#112e3c')
        draw.line((6, y, 6, y + 7), fill=MINT)
        _source_line(draw, line)
        if phase != 3:
            x = min(85, 15 + sum(len(text) for text, _ in SOURCE[line]) * 8)
            draw.line((x, y, x, y + 7), fill=WHITE)
        _flow(draw, phase)
        poses.append(canvas)
    # Keep the unchanged type declaration and CODE FLOW caption out of RAM and
    # repeated LCD restores. Full boxes are disjoint and wholly left of the HUD.
    boxes = ((6, 64, 86, 88), (6, 98, 86, 113))
    return tuple({'x': box[0] * SCALE, 'y': box[1] * SCALE,
                  'frames': [pose.crop(box).convert('RGBA') for pose in poses],
                  'script': [(i, 0, 0) for i in range(4)], 'step_ms': STEP_MS}
                 for box in boxes)


def render_forge(snapshot, animated=False):
    canvas = _editor().copy()
    draw = ImageDraw.Draw(canvas)
    _module(draw, 18, _row(snapshot, 'codex'), 'codex')
    _module(draw, 66, _row(snapshot, 'claude'), 'claude')
    sprites = _editor_motion()
    if not animated:
        for sprite in sprites:
            pose = sprite['frames'][0]
            canvas.paste(pose, (sprite['x'] // SCALE, sprite['y'] // SCALE), pose)
    image = canvas.resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
    return (image, board_anim.encode(sprites)) if animated else image
