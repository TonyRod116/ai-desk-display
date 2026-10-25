"""Small-screen instruments showing remaining quota, never an estimated message count."""
import functools
import math
import time

from PIL import Image, ImageDraw

from token_tv.display import overview_rows
from token_tv.themes import Canvas, bot_sprite, face, place_bot, reading


def remaining_reading(row):
    used, period, old, reset = reading(row, period='WEEK' if row.get('provider') in ('claude', 'codex') else None)
    return (None if used is None else 100 - used), period, old, reset


def session_window(row, now=None):
    """Claude's live five-hour window from a fresh official row, else None.

    The weekly number stays the headline, but the session is what stops work first.
    Unknown, expired, old or non-Claude readings give None, so nothing is drawn and
    an unknown session can never look like an empty one.
    """
    now = time.time() if now is None else now
    if row.get('provider') != 'claude':
        return None
    for window in row.get('windows') or []:
        used, reset = window.get('used_percent'), window.get('resets_at')
        if (window.get('label') == '5H' and type(used) in (int, float) and math.isfinite(used)
                and type(reset) in (int, float) and math.isfinite(reset) and reset > now):
            return window
    return None


def session_remaining(row, now=None):
    """Remaining % of Claude's five-hour session, else None."""
    window = session_window(row, now)
    return None if window is None else max(0, min(100, 100 - window['used_percent']))


def session_hours(row, now=None):
    """Hours left until Claude's five-hour session renews (0 to 5), else None."""
    now = time.time() if now is None else now
    window = session_window(row, now)
    return None if window is None else max(0.0, min(5.0, (window['resets_at'] - now) / 3600))


def session_pace(row, now=None):
    """(quota % left, hours left) of Claude's live five-hour session, else None."""
    window = session_window(row, now)
    if window is None:
        return None
    return session_remaining(row, now), session_hours(row, now)


def session_pace_line(cv, x, y, width, pace, lit, track, mark, row=3):
    """Two glued bars for Claude's five-hour session: quota left above, time left below.

    Both are the session's five hours as five one-hour segments, so they compare at a
    glance: if the time bar is longer than the quota bar, the quota runs out before the
    session renews. The time bar ending halfway through the second segment is about an
    hour and a half. They are separate rows, never drawn over each other: a mark placed
    inside the bar vanished whenever the quota left was larger than the time left.
    Quota moves in 5% steps and time in quarter hours, so the faces change rarely and
    the clock's flash is not rewritten every minute. Unknown draws nothing, so it can
    never read as an empty session. Total height is 2 * row + 1.
    """
    if pace is None:
        return
    remaining, hours = pace
    gap = 4
    seg = (width - 4 * gap) / 5
    for index, (units, color) in enumerate(((math.ceil(remaining / 5) / 4, lit),   # quota, hour-sized units
                                            (round(hours * 4) / 4, mark))):        # time, quarter hours
        top = y + index * (row + 1)
        for k in range(5):
            left = x + k * (seg + gap)
            for px in range(round(left), round(left + seg), 2):  # faint dotted track
                cv.draw.point((px, top + row // 2), fill=track)
            fill = max(0, min(1, units - k))
            if fill > 0:
                cv.draw.rectangle((round(left), top, round(left + seg * fill) - 1, top + row - 1), fill=color)



def pixel(size):
    return face('press-start-2p.ttf', size)


def two_colors(image, paper, ink):
    palette = Image.new('P', (1, 1))
    colors = [int(c[i:i + 2], 16) for c in (paper, ink) for i in (1, 3, 5)]
    palette.putpalette(colors * 128)
    return image.quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB')


def reset_heart_fills(count):
    if count is None:
        return None
    if type(count) is not int or count < 0:
        raise ValueError('Saved resets must be a non-negative whole number')
    return [1 if count > i else 0 for i in range(3)]


def banked_hearts(row):
    """(count, old): the fresh count, or the last confirmed one flagged old, or unknown (None, False)."""
    banked = row.get('banked_resets') or {}
    count = banked.get('available')
    if count is None and type(banked.get('last_known')) is int:
        return banked['last_known'], True
    return count, False


def hearts(cv, x, y, count, ink, paper, scale=2, old=False, quiet=False):
    """Three hearts for the saved resets. `quiet` (the board's wider screen; the user, 2026-10-20): while the number is unknown or old the
    hearts stay and ONE faint dot ends the row, with no `?` and no OLD."""
    shape = ('.##.##.', '#######', '#######', '.#####.', '..###..', '...#...')
    fills = reset_heart_fills(count)
    for index in range(3):
        fraction = fills[index] if fills is not None else 0
        left = x + index * 9 * scale
        for yy, line in enumerate(shape):
            for xx, cell in enumerate(line):
                if cell != '#':
                    continue
                edge = any(ny < 0 or ny >= len(shape) or nx < 0 or nx >= 7 or shape[ny][nx] != '#'
                           for nx, ny in ((xx-1, yy), (xx+1, yy), (xx, yy-1), (xx, yy+1)))
                filled = xx + .5 <= fraction * 7
                color = ink if edge or filled else paper
                cv.draw.rectangle((left + xx*scale, y + yy*scale,
                                   left + (xx+1)*scale-1, y + (yy+1)*scale-1), fill=color)
    if quiet:
        if count is None or old:
            cv.draw.rectangle((x + 27 * scale, y + 2 * scale, x + 27 * scale + scale - 1, y + 2 * scale + scale - 1), fill=ink)
        label = '+' if count is not None and count > 3 else ''
    else:
        label = '?' if count is None else ('+' if count > 3 else '') + ('OLD' if old else '')
    if label:
        cv.text((x + 28*scale + (4 * scale if quiet and (count is None or old) else 0), y + 2), label, pixel(8), ink)


def bars(cv, x, y, width, value, ink, paper, old=False):
    for i in range(20):
        left = x + i * width / 20
        box = (left, y, left + width / 20 - 3, y + 8)
        cv.draw.rectangle(box, outline=ink,
                          fill=ink if value is not None and i < math.ceil(value / 5) else paper)
        if old:
            cv.draw.line((left, y + 8, left + width / 20 - 3, y), fill=paper)


@functools.lru_cache(maxsize=8)
def _grid_mask(size, cell, axes='both'):
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    if axes in ('both', 'vertical'):
        for x in range(cell - 1, size[0], cell):
            draw.line((x, 0, x, size[1]), fill=255)
    if axes in ('both', 'horizontal'):
        for y in range(cell - 1, size[1], cell):
            draw.line((0, y, size[0], y), fill=255)
    return mask


def lcd_grid(image, shade, strength=.22, cell=2, axes='both'):
    """The dot-matrix look of a real Game Boy LCD: a thin darker line between neighbouring pixels.

    `axes` is 'both', 'vertical' (lines between columns) or 'horizontal' (between rows). A line every
    2 px in both directions made the board's panel shimmer (the user, 2026-10-13).
    """
    image = image.convert('RGB')
    dark = Image.blend(image, Image.new('RGB', image.size, shade), strength)
    return Image.composite(dark, image, _grid_mask(image.size, cell, axes))


def gameboy(data, paper, ink, title, screen=(240, 240), grid=False):
    dx = screen[0] - 240  # the faces are drawn for 240 and stretch to wider screens, not the other way
    cv = Canvas(paper, screen)
    cv.draw.rectangle((3, 3, 236 + dx, 236), outline=ink, width=3)
    cv.draw.rectangle((9, 9, 230 + dx, 27), fill=ink)
    cv.text((16, 14), title, pixel(8), paper)
    cv.text((120 + dx // 2, 34), 'WEEKLY QUOTA', pixel(8), ink, anchor='ma')
    rows = overview_rows(data)
    pitch = 174 // len(rows)
    compact = len(rows) == 3
    for i, row in enumerate(rows):
        y = 51 + i * pitch
        value, period, old, reset = remaining_reading(row)
        place_bot(cv.ink, bot_sprite(row['provider'], 20, 16, ink, paper), (14, y, 20, 16))
        cv.text((41, y + 3), row['provider'].upper(), pixel(9), ink)
        header_period = 'N/A' if period == 'NO DATA' else period
        cv.text((222 + dx, y + 3), 'OLD' if old else header_period, pixel(8), ink, anchor='ra')
        count, old_count = banked_hearts(row)
        hearts(cv, 111 + dx // 2, y + 5, count, ink, paper, scale=2, old=old_count, quiet=dx > 0)
        size = 16 if compact else 25
        number = '--' if value is None else f'{round(value)}%'
        cv.text((15, y + 24), number, pixel(size), ink)
        cv.text((222 + dx, y + (20 if compact else 23)), 'RESET', pixel(7 if compact else 9), ink, anchor='ra')
        cv.text((222 + dx, y + (32 if compact else 38)), reset.replace(' ', ''), pixel(8 if compact else 16), ink, anchor='ra')
        bar_y = y + pitch - (12 if compact else 17)
        bars(cv, 15, bar_y, 212 + dx, value, ink, paper, old)
        session_pace_line(cv, 15, bar_y + (10 if compact else 12), 212 + dx, session_pace(row), ink, ink, ink,
                          row=1 if compact else 3)
    image = two_colors(cv.finish(), paper, ink)
    if not grid:
        return image
    axes, strength = grid if isinstance(grid, tuple) else ('both', .22)   # grid: True or (axes, strength)
    return lcd_grid(image, ink, strength=strength, axes=axes)


DMG = ('#afc93f', '#0f380f')  # the Game Boy's green LCD: the original darkest shade, its lightest eased ~20% (#9bbc0f was too green on the board)


def render_gameboy(data, screen=(240, 240), colors=DMG, grid=False):
    paper, ink = colors
    return gameboy(data, paper, ink, 'TOKEN BOY    LOCAL', screen, grid)


POCKET = ('#6cc24a', '#08240c')  # a clear mid green with near-black ink: it read as pale grey on the board's panel when softer


def render_pocket(data, screen=(240, 240), colors=POCKET, grid=False):
    paper, ink = colors
    return gameboy(data, paper, ink, 'TOKEN POCKET LOCAL', screen, grid)


def render_amber(data, screen=(240, 240)):
    dx = screen[0] - 240
    cv = Canvas('#110d06', screen)
    ink, dim = '#ffc66b', '#73532b'
    cv.draw.rectangle((7, 7, 232 + dx, 232), outline=dim)
    cv.text((16, 15), 'QUOTA / TERMINAL', face('vt323.woff2', 21), ink)
    cv.draw.line((16, 38, 224 + dx, 38), fill=dim)
    cv.text((16, 42), 'WEEKLY REMAINING', pixel(8), ink)
    rows = overview_rows(data)
    pitch = 168 // len(rows)
    compact = len(rows) == 3
    for i, row in enumerate(rows):
        y = 60 + i * pitch
        value, period, old, reset = remaining_reading(row)
        cv.text((16, y), '> ' + row['provider'].upper(), face('vt323.woff2', 21), ink)
        cv.text((222 + dx, y + 4), 'OLD' if old else 'N/A' if period == 'NO DATA' else period, pixel(8), ink, anchor='ra')
        count, old_count = banked_hearts(row)
        hearts(cv, 113 + dx // 2, y + 5, count, ink, '#110d06', scale=2, old=old_count)
        number = '--' if value is None else f'{round(value)}%'
        cv.text((18, y + 18), number, face('vt323.woff2', 25 if compact else 43), ink)
        cv.text((221 + dx, y + (20 if compact else 24)), 'RESET', face('vt323.woff2', 11 if compact else 15), dim, anchor='ra')
        cv.text((221 + dx, y + (31 if compact else 39)), reset, face('vt323.woff2', 14 if compact else 17), ink, anchor='ra')
        bar_y = y + pitch - (11 if compact else 16)
        bars(cv, 18, bar_y, 207 + dx, value, ink, '#110d06', old)
        session_pace_line(cv, 18, bar_y + (10 if compact else 12), 207 + dx, session_pace(row), ink, '#6b4d26',
                          '#ff7a45', row=1 if compact else 3)
    return cv.finish()


def render_orbit(data, screen=(240, 240)):
    dx = screen[0] - 240
    cv = Canvas('#07141b', screen)
    white, muted = '#e4f3eb', '#8daeb5'
    cv.text((14, 13), 'ORBIT', face('orbitron.ttf', 16), white)
    cv.text((226 + dx, 18), 'WEEK', pixel(7), muted, anchor='ra')
    cv.draw.line((14, 37, 226 + dx, 37), fill='#29434b')
    rows = overview_rows(data)
    pitch = 188 // len(rows)
    compact = len(rows) == 3
    for i, row in enumerate(rows):
        y = 47 + i * pitch
        value, period, old, reset = remaining_reading(row)
        ink = '#ffb986' if row['provider'] == 'claude' else '#7be1d7'
        diameter = min(76, pitch - 9)
        ring_x, text_x = 13 + dx // 4, 103 + dx // 2   # a wider screen: ring and text move in together
        box = (ring_x, y, ring_x + diameter, y + diameter)
        cv.draw.arc(box, 130, 410, fill='#253a42', width=5)
        if value is not None and value > 0:
            cv.draw.arc(box, 130, 130 + 280 * value / 100, fill=muted if old else ink, width=5)
        # Claude's session line sits under the text column, where the ring has no room for it.
        session_pace_line(cv, text_x, y + (55 if compact else 80), 123 + dx // 2, session_pace(row), '#ffd8bf', '#3a555d',
                          '#7be1d7', row=1 if compact else 3)
        number = '--' if value is None else f'{round(value)}'
        cx = ring_x + diameter / 2
        cv.text((cx, y + diameter / 2 - 12), number, face('oxanium.woff2', 26), white, anchor='ma')
        cv.text((cx, y + diameter / 2 + 14), '%' if value is not None else '?', pixel(8), ink, anchor='ma')
        cv.text((text_x, y + 4), row['provider'].upper(), face('orbitron.ttf', 13), ink)
        count, old_count = banked_hearts(row)
        hearts(cv, 175 + dx // 2, y + 5, count, ink, '#07141b', scale=1, old=old_count)
        cv.text((text_x, y + (23 if compact else 29)), 'OLD' if old else period, pixel(8), muted)
        cv.text((text_x, y + (38 if compact else 47)), ('R ' if compact else '') + reset,
                face('oxanium.woff2', 15 if compact else 17), white)
        if not compact:
            cv.text((text_x, y + 68), 'RESET', pixel(7), muted)
    return cv.finish()


RENDERERS = {'game-boy': render_gameboy, 'game-boy-pocket': render_pocket,
             'amber-terminal': render_amber, 'orbit': render_orbit}
