"""Page 4, immediately after Orbit: "TOKEN COCKPIT", an eighties pixel CRT (320x240).

Two phosphor wireframe dials on a dark tube with coarse, fixed background scanlines. The ring of twenty
blocks is the quota left of the week (the last lit block is white, like a cursor), hearts are saved resets,
and Claude's five-hour session is two thin rings of five parts inside Claude's dial (quota left outside, time
left inside, in the dial's own colour, with no marks or numbers; nothing at all while the session is
unknown, so unknown never reads as empty).

Everything, including the text and its stepped phosphor halo, is drawn on a 160x120 canvas without
anti-aliasing and scaled 2x. Flat colours only; scanlines are 2px high, 10px apart and behind the readings,
never a dense two-axis grid or an animated flicker. A sunset driving scene runs in two disjoint sprites
using firmware 7's ANIM trailer. Instrument pixels are masked out; animation never depends on PC time
and never adds repeated uploads or flash writes. Older firmware gets the first pose as a static picture.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

from token_tv.board_art import CLAUDE, CODEX, _row
from token_tv.board_arcade import GOLD, HEART, STONE, _px
from token_tv import board_anim, board_drive_classic as board_drive
from token_tv.display import pixel_text
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

LW, LH, K = 160, 120, 2
START, SWEEP, BLOCKS = 135, 270, 20
UNLIT = {'codex': '#30280e', 'claude': '#252920'}
UNLIT_THIN = '#31382b'
BANDS = {'codex': (GOLD['lo'], GOLD['mid'], GOLD['hi']), 'claude': (STONE['lo'], STONE['mid'], STONE['hi'])}
CENTRES = {'codex': (40, 52), 'claude': (120, 52)}
PHOSPHOR, FRAME, SCREEN = '#a7c295', '#34553c', '#06110b'
HALO = {'codex': '#3c310e', 'claude': '#343a2b'}


def _ring(draw, centre, r_in, r_out, colour_at):
    """Paint the annulus r_in <= r < r_out pixel by pixel: `colour_at(angle, radius)` gives a colour or None.

    Angles are in degrees, clockwise from 3 o'clock. Doing it by hand keeps the edges exact and the thickness
    even, which PIL's thick arcs do not."""
    cx, cy = centre
    reach = int(r_out) + 1
    for y in range(cy - reach, cy + reach + 1):
        for x in range(cx - reach, cx + reach + 1):
            radius = math.hypot(x - cx, y - cy)
            if r_in <= radius < r_out:
                colour = colour_at(math.degrees(math.atan2(y - cy, x - cx)) % 360, radius)
                if colour:
                    draw.point((x, y), fill=colour)


def _span(angle, start, sweep):
    """Position of `angle` inside the arc that starts at `start` and runs `sweep` degrees, or None."""
    rel = (angle - start) % 360
    return rel if rel <= sweep else None


def _bezel(draw, centre, provider):
    """Light drawn on CRT glass, with stepped halos instead of a shiny steel bezel."""
    cx, cy = centre
    _ring(draw, centre, 0, 33.5, lambda a, r: '#020805')
    for y in range(cy - 31, cy + 32):
        if (y - 6) % 5:
            continue
        reach = math.floor(math.sqrt(max(0, 31 * 31 - (y - cy) ** 2)))
        draw.line((cx - reach, y, cx + reach, y), fill='#0b2013')
    _ring(draw, centre, 33.5, 38.5, lambda a, r: '#152319')
    _ring(draw, centre, 34, 37.5, lambda a, r: HALO[provider])
    _ring(draw, centre, 35, 36, lambda a, r: BANDS[provider][0])
    _ring(draw, centre, 30.5, 31.5, lambda a, r: UNLIT[provider])


def _ticks(draw, centre, provider):
    cx, cy = centre
    for i in range(BLOCKS + 1):
        angle = math.radians(START + SWEEP * i / BLOCKS)
        r0 = 29 if i % 5 == 0 else 30
        draw.line((cx + math.cos(angle) * r0, cy + math.sin(angle) * r0,
                   cx + math.cos(angle) * 32, cy + math.sin(angle) * 32),
                  fill=BANDS[provider][1] if i % 5 == 0 else BANDS[provider][0])


def _led_ring(draw, centre, remaining, provider):
    """Twenty blocks of 5 %: the lit ones are the quota left; unknown lights none."""
    part = SWEEP / BLOCKS
    lit = 0 if remaining is None else max(1 if remaining > 0 else 0, round(remaining / 5))
    bands = BANDS[provider]

    def colour_at(angle, radius):
        rel = _span(angle, START, SWEEP)
        if rel is None:
            return None
        k = min(BLOCKS - 1, int(rel // part))
        if rel - k * part < 1.2 or (k + 1) * part - rel < 1.2:                          # the gap between blocks
            return None
        if k < lit:
            return '#ffffff' if k == lit - 1 else bands[min(2, k * 3 // BLOCKS)]
        return UNLIT[provider]
    _ring(draw, centre, 22, 28.5, colour_at)


def _session_rings(draw, centre, pace):
    """Two thin rings of five parts: quota left outside, time left inside; the dial's own colour."""
    if pace is None:
        return
    quota, hours = pace
    part = SWEEP / 5
    values = (math.ceil(quota / 5) / 4, round(hours * 4) / 4)
    for index, value in enumerate(values):
        r_out = 20 - index * 4

        def colour_at(angle, radius, value=value):
            rel = _span(angle, START, SWEEP)
            if rel is None:
                return None
            k = min(4, int(rel // part))
            inside = rel - k * part
            if inside < 3 or inside > part - 3:
                return None
            fill = max(0, min(1, value - k))
            return STONE['mid'] if (inside - 3) / (part - 6) <= fill and fill > 0 else UNLIT_THIN
        _ring(draw, centre, r_out - 2, r_out, colour_at)


def _text(draw, xy, text, size, colour, anchor='mm', halo=None, bloom=False):
    # Pillow can smooth a stroked TrueType outline even with fontmode='1'. Binary masks keep
    # both the glyph and the stepped phosphor bloom flat, rather than adding blended edge colours.
    font = face('press-start-2p.ttf', size)
    layers = ([(2, '#152319')] if halo and bloom else []) + ([(1, halo)] if halo else []) + [(0, colour)]
    for stroke, fill in layers:
        left, top, right, bottom = draw.textbbox(xy, text, font=font, anchor=anchor, stroke_width=stroke)
        mask = Image.new('1', (right - left, bottom - top), 0)
        ImageDraw.Draw(mask).text((xy[0] - left, xy[1] - top), text, font=font, anchor=anchor,
                                  fill=1, stroke_width=stroke, stroke_fill=1)
        draw.bitmap((left, top), mask, fill=fill)


def _hearts(draw, x, y, count, provider):
    """Bright phosphor lives and dim hollow outlines, in the provider's own colour."""
    for i in range(3):
        filled = count is not None and count > i
        for yy, line in enumerate(HEART):
            for xx, cell in enumerate(line):
                if cell != '#':
                    continue
                edge = any(ny < 0 or ny >= 6 or nx < 0 or nx >= 7 or HEART[ny][nx] != '#'
                           for nx, ny in ((xx - 1, yy), (xx + 1, yy), (xx, yy - 1), (xx, yy + 1)))
                if filled or edge:
                    draw.point((x + i * 9 + xx, y + yy),
                               fill=BANDS[provider][1] if filled else BANDS[provider][0])


@lru_cache(maxsize=1)
def _driving_sprites():
    """Keep the complete instrument faces/LEDs and footer out of the two road sprites."""
    poses = [frame.copy() for frame in board_drive.frames()]
    for y in range(board_drive.HEIGHT):
        py = y + board_drive.TOP
        for x in range(LW):
            keep = 4 <= x <= 155
            for cx, cy in CENTRES.values():
                dx, dy = x - cx, py - cy
                radius = math.hypot(dx, dy)
                angle = math.degrees(math.atan2(dy, dx)) % 360
                if radius < 22 or 33.5 <= radius < 38.5 or (
                        radius < 33.5 and _span(angle, START, SWEEP) is not None):
                    keep = False
            if not keep:
                for pose in poses:
                    pose.putpixel((x, y), (0, 0, 0, 0))
    return tuple({'x': x * K, 'y': board_drive.TOP * K,
                  'frames': [pose.crop((x, 0, x + 80, board_drive.HEIGHT)) for pose in poses],
                  'script': [(i, 0, 0) for i in range(4)], 'step_ms': board_drive.STEP_MS}
                 for x in (0, 80))


def render_dials(snapshot, animated=False):
    canvas = Image.new('RGB', (LW, LH), '#020604')
    draw = ImageDraw.Draw(canvas)
    draw.fontmode = '1'
    # A stepped tube edge and low-contrast, coarse scanlines: no one-pixel panel shimmer.
    outer = ((10, 0), (149, 0), (159, 10), (159, 109), (149, 119), (10, 119), (0, 109), (0, 10))
    draw.polygon(outer, fill='#16251b', outline='#273c2b')
    edge = ((9, 2), (150, 2), (157, 9), (157, 110), (150, 117), (9, 117), (2, 110), (2, 9))
    draw.polygon(edge, fill=SCREEN, outline=FRAME)
    board_drive.sunset(draw)
    for y in range(6, 115, 5):
        draw.line((4, y, 155, y), fill='#142b1c')
    _px(draw, 4, 3, 155, 13, '#08170d')
    _px(draw, 4, 14, 155, 14, FRAME)
    _px(draw, 4, 93, 155, 93, FRAME)

    texts = []
    for provider, accent in (('codex', CODEX), ('claude', CLAUDE)):
        row = _row(snapshot, provider)
        value, _, _, reset = remaining_reading(row)
        count, old = banked_hearts(row)
        centre = CENTRES[provider]
        _bezel(draw, centre, provider)
        _ticks(draw, centre, provider)
        _led_ring(draw, centre, value, provider)
        if provider == 'claude':
            _session_rings(draw, centre, session_pace(row))
        _hearts(draw, centre[0] - 13, 110, count, provider)
        texts.append(('number', centre, '--' if value is None else f'{round(value)}', provider))
        texts.append(('name', (centre[0], 96), provider.upper(), accent))
        texts.append(('reset', (centre[0], 105), 'RESET ' + reset.upper(), provider))
        mark = '?' if count is None else ('+' if count > 3 else '') + ('OLD' if old else '')
        if mark:
            texts.append(('mark', (centre[0] + 16, 113), mark, accent))
    _text(draw, (5, 5), 'TOKEN COCKPIT', 6, PHOSPHOR, anchor='la', halo='#25402b', bloom=True)
    _text(draw, (155, 3), 'WEEKLY', 5, PHOSPHOR, anchor='ra')
    _text(draw, (155, 8), 'LEFT', 5, PHOSPHOR, anchor='ra')
    for kind, (x, y), text, *rest in texts:
        if kind == 'number':
            provider = rest[0]
            _text(draw, (x, y - 1), text, 8, BANDS[provider][2], halo=HALO[provider])
            pixel_text(draw, (x - 2, y + 5), '%' if text != '--' else '?', color=BANDS[provider][1])
        elif kind == 'name':
            _text(draw, (x, y + 1), text, 8, rest[0], halo=HALO[text.lower()], bloom=True)
        elif kind == 'reset':
            pixel_text(draw, (x - (len(text) * 6 - 1) // 2, y - 3), text, color=BANDS[rest[0]][2])
        else:
            _text(draw, (x, y), text, 5, rest[0], anchor='lm')
    sprites = _driving_sprites()
    if not animated:
        for sprite in sprites:
            pose = sprite['frames'][0]
            canvas.paste(pose, (sprite['x'] // K, sprite['y'] // K), pose)
    image = canvas.resize((LW * K, LH * K), Image.Resampling.NEAREST)
    return (image, board_anim.encode(sprites)) if animated else image
