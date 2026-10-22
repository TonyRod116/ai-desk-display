"""Page 5 of the touch board: TOKEN RUN, a daytime coast road in the spirit of the arcade game Out Run (320x240).

The road is the star: sky, clouds, mountains, sea and sand, a road in perspective with red and white kerbs,
palms that rush past and a red convertible (all in `board_drive.py`, original pixel art). The usage readings
are two round dials set into the bottom corners, like an arcade dashboard:

- the ring of twenty LED blocks is the quota left of the week (the last lit block is a paler tint of its colour, like a
  cursor), and the blocks change colour with their place on the ring like an arcade rev counter: red up to 20 %, amber up to 50 %,
  green above (the user, 2026-10-19; the same limits as the VERSUS life bars). Empty blocks are a plain dark navy: a faint zone tint made the level hard to see at a glance;
- three pixel hearts in the gap at the foot of each dial are the saved resets, without a number;
- Claude's five-hour session is two thin rings of five parts inside its dial (quota left outside, time left
  inside, with no marks or numbers; nothing at all while the session is unknown, so unknown never reads as empty);
- the number is the quota left and a small % sits in the gap below it. Codex is yellow and Claude stone.

A scoreboard strip at the top carries the names, the weekly reset of each and the title. Everything (scoreboard
text included, in the 5x7 bitmap font with an arcade drop shadow) is painted on a 160x120 canvas with no
anti-aliasing and scaled 2x (hard 2x2 pixels). A cathode-ray-tube look is then applied per canvas pixel, so the
animated road carries it too: a scan line on every other row, a stepped vignette towards the edges and rounded
screen corners. Only one direction of line pattern is used: the panel shimmers on grids in both directions.

Animation (firmware 7+ `ANIM`): the page carries the first pose of the road, so a board that cannot animate just
shows it. One 72x62 sprite holds the four stored poses of the whole road (bands, kerbs, dashes, palms, bushes
and the car); every pixel of the dials is masked out of it, so a dial is never overpainted. No pose depends on
the clock, an account or the PC, nothing is streamed and nothing is written to flash to animate.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

from token_tv.board_art import CLAUDE, CODEX, _row
from token_tv.board_arcade import GOLD, STONE
from token_tv.board_surf import _mix
from token_tv import board_anim, board_drive, board_reset_icons as icons
from token_tv.display import pixel_text
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace

LW, LH, K = 160, 120, 2
START, SWEEP, BLOCKS = 135, 270, 20
CENTRES = {'codex': board_drive.DIALS[0], 'claude': board_drive.DIALS[1]}
RADIUS = board_drive.DIAL_RADIUS               # the whole dial, rim included (the rim ring is painted below 28)
BANDS = {'codex': (GOLD['lo'], GOLD['mid'], GOLD['hi']), 'claude': (STONE['lo'], STONE['mid'], STONE['hi'])}
UNLIT, UNLIT_THIN = '#1a2240', '#2b3452'       # the empty part of the weekly ring must stay quiet so the level reads at a glance
ZONES = ('#e53a2c', '#f4a21a', '#47c64c')       # red <= 20 %, amber <= 50 %, green above: the outer ring's blocks
ZONE_BLOCKS = (4, 10)                           # blocks 0-3 are red, 4-9 amber, 10-19 green
SHADOW = {'codex': '#4a3200', 'claude': '#3e3a30'}
BEZEL = (5, 7, 13)
SCAN_DIM, SCAN_BRIGHT = .90, 1.02                # brightness of the dark and the bright scan lines
CORNER = 4                                      # radius of the rounded screen corners, in canvas pixels


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


def _face(draw, centre):
    """A round gauge: a dark outline, a bevelled steel rim lit from the upper left, and a deep-blue face."""
    def rim(angle, radius):
        if radius >= 27 or radius < 25:
            return '#070a14'
        if 170 <= angle <= 290:
            return '#e2e8f5'
        if angle >= 350 or angle <= 110:
            return '#4a526b'
        return '#8d97ae'
    _ring(draw, centre, 0, 25, lambda a, r: '#0a1226' if r < 23 else '#060b18')
    _ring(draw, centre, 24.5, 28, rim)


def _ticks(draw, centre):
    cx, cy = centre
    for i in range(BLOCKS + 1):
        angle = math.radians(START + SWEEP * i / BLOCKS)
        r0 = 22.6 if i % 5 == 0 else 23.2
        draw.line((cx + math.cos(angle) * r0, cy + math.sin(angle) * r0,
                   cx + math.cos(angle) * 24.2, cy + math.sin(angle) * 24.2),
                  fill='#ffffff' if i % 5 == 0 else '#8e9bbd')


def _zone(k):
    """The colour of block k of the ring (0 = empty end, 19 = full end)."""
    return ZONES[0] if k < ZONE_BLOCKS[0] else ZONES[1] if k < ZONE_BLOCKS[1] else ZONES[2]


def _led_ring(draw, centre, remaining):
    """Twenty blocks of 5 %: the lit ones are the quota left, coloured by where they sit on the ring (red, amber,
    green); the last lit one is paler unless it is the only one (a white one hid the red when little was left).
    Empty blocks are a plain, quiet dark. Unknown lights none."""
    part = SWEEP / BLOCKS
    lit = 0 if remaining is None else max(1 if remaining > 0 else 0, round(remaining / 5))

    def colour_at(angle, radius):
        rel = _span(angle, START, SWEEP)
        if rel is None:
            return None
        k = min(BLOCKS - 1, int(rel // part))
        if rel - k * part < 1.3 or (k + 1) * part - rel < 1.3:                          # the gap between blocks
            return None
        if k < lit:
            return _mix(_zone(k), '#ffffff', .55) if k == lit - 1 and lit > 1 else _zone(k)
        return UNLIT
    _ring(draw, centre, 17, 22, colour_at)


def _session_rings(draw, centre, pace):
    """Two thin rings of five parts: quota left outside, time left inside; the dial's own colour."""
    if pace is None:
        return
    quota, hours = pace
    part = SWEEP / 5
    values = (math.ceil(quota / 5) / 4, round(hours * 4) / 4)
    for index, value in enumerate(values):
        r_out = 15 - index * 3

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


def _flags(draw, x, y, count, provider, marked=False):
    """One chequered flag per saved reset (was a heart): bright when available, a faint flag when not. While the number is unknown
    or old the flags stay (faint when unknown, the last known count when old) and one faint dot ends the row: no `?` and no OLD."""
    bright, dim = BANDS[provider][1], BANDS[provider][0]
    dark = _mix(bright, '#000000', abs(icons.DETAIL['flag']))
    have = count if count is not None else 0
    for i in range(3):
        if have > i:
            for xx, yy, tone, _ in icons.cells('flag'):
                draw.point((x + i * 9 + xx, y + yy), fill=dark if tone == 'o' else bright)
        else:
            for xx, yy in icons.hollow('flag'):
                draw.point((x + i * 9 + xx, y + yy), fill=dim)
    if marked:
        draw.point((x + 27, y + 3), fill=dim)


def _dial(draw, provider, value, count, pace, marked=False):
    centre = CENTRES[provider]
    cx, cy = centre
    _face(draw, centre)
    _ticks(draw, centre)
    _led_ring(draw, centre, value)
    if provider == 'claude':
        _session_rings(draw, centre, pace)
    text = '--' if value is None else f'{round(value)}'
    pixel_text(draw, (cx - (len(text) * 6 - 1) // 2, cy - 4), text, color=BANDS[provider][2])
    pixel_text(draw, (cx - 2, cy + 5), '%' if value is not None else '?', color=BANDS[provider][1])
    _flags(draw, cx - 13, cy + 15, count, provider, marked)


MICRO = {
    'A': '010/101/111/101/101', 'C': '011/100/100/100/011', 'D': '110/101/101/101/110', 'E': '111/100/110/100/111',
    'H': '101/101/111/101/101', 'K': '101/101/110/101/101', 'L': '100/100/100/100/111', 'N': '111/101/101/101/101',
    'O': '111/101/101/101/111', 'R': '110/101/110/101/101', 'S': '011/100/010/001/110', 'T': '111/010/010/010/010',
    'U': '101/101/101/101/111', 'X': '101/101/010/101/101', '?': '110/001/010/000/010', '+': '000/010/111/010/000',
    '-': '000/000/111/000/000', ' ': '000/000/000/000/000',
    '0': '111/101/101/101/111', '1': '010/110/010/010/111', '2': '110/001/010/100/111', '3': '110/001/110/001/110',
    '4': '101/101/111/001/001', '5': '111/100/110/001/110', '6': '011/100/111/101/111', '7': '111/001/010/010/010',
    '8': '111/101/111/101/101', '9': '111/101/111/001/110',
}
MICRO['8'] = '111/101/111/101/111'


def _micro(draw, xy, text, color, align='left'):
    """Text in a 3x5 bitmap font (one canvas pixel per dot, four per letter)."""
    text = text.upper()
    x, y = xy
    if align == 'right':
        x -= len(text) * 4 - 1
    for index, character in enumerate(text):
        for yy, line in enumerate(MICRO.get(character, MICRO['?']).split('/')):
            for xx, bit in enumerate(line):
                if bit == '1':
                    draw.point((x + index * 4 + xx, y + yy), fill=color)


def _shadowed(draw, xy, text, color, shadow, align='left'):
    """Scoreboard text with the arcade's one-pixel drop shadow (down and right)."""
    x, y = xy
    _micro(draw, (x + 1, y + 1), text, shadow, align)
    _micro(draw, (x, y), text, color, align)


def _crt_gain(x, y):
    """The tube at canvas pixel (x, y): None outside the rounded screen, otherwise a brightness factor."""
    corner = min(x, LW - 1 - x), min(y, LH - 1 - y)
    if corner[0] < CORNER and corner[1] < CORNER and math.hypot(CORNER - corner[0] - .5, CORNER - corner[1] - .5) > CORNER:
        return None
    dx, dy = abs(x - (LW - 1) / 2) / (LW / 2), abs(y - (LH - 1) / 2) / (LH / 2)
    edge = (dx ** 3 + dy ** 3) ** (1 / 3)
    vignette = 1.0 if edge < .90 else .97 if edge < 1.0 else .94 if edge < 1.1 else .91
    return vignette * (SCAN_DIM if y % 2 else SCAN_BRIGHT)


def _crt(image, origin=(0, 0)):
    """The tube: scan lines, a stepped vignette and rounded corners, decided per canvas pixel (so it is the same
    for the stored picture and for every pose of the road). `origin` is the canvas position of the image's corner,
    for crops. Nothing here looks at neighbours or at the time. Alpha, if any, is kept."""
    out = image.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            gain = _crt_gain(x + origin[0], y + origin[1])
            pixel = px[x, y]
            if len(pixel) == 4 and pixel[3] < 128:
                continue
            if gain is None:
                px[x, y] = BEZEL + pixel[3:]
                continue
            px[x, y] = tuple(min(255, round(c * gain)) for c in pixel[:3]) + pixel[3:]
    return out


@lru_cache(maxsize=1)
def _sprites():
    """The road window in its four poses, with every pixel of the dials left transparent, then the slow sky things."""
    x0, y0, x1, y1 = board_drive.WINDOW
    poses = []
    for phase in range(board_drive.PHASES):
        pose = _crt(board_drive.scene(phase).crop((x0, y0, x1, y1)).convert('RGBA'), (x0, y0))
        px = pose.load()
        for y in range(y1 - y0):
            for x in range(x1 - x0):
                if any(math.hypot(x + x0 - cx, y + y0 - cy) <= RADIUS for cx, cy in CENTRES.values()):
                    px[x, y] = (0, 0, 0, 0)
        poses.append(pose)
    sprites = [{'x': x0 * K, 'y': y0 * K, 'frames': poses, 'script': [(i, 0, 0) for i in range(len(poses))],
                'step_ms': board_drive.STEP_MS}]
    for thing in board_drive.ambient():
        origin = (thing['x'] // K, thing['y'] // K)
        sprites.append({'x': thing['x'], 'y': thing['y'], 'script': thing['script'], 'step_ms': board_drive.STEP_MS,
                        'frames': [_crt(frame, origin) for frame in thing['frames']]})
    return sprites


def render_dials(snapshot, animated=False):
    canvas = board_drive.scene(0).copy()
    if not animated:                                        # a board without ANIM keeps the first pose of the sky things
        for thing in board_drive.ambient():
            frame, dx, dy = thing['script'][0]
            canvas.paste(thing['frames'][frame], ((thing['x'] + dx) // K, (thing['y'] + dy) // K), thing['frames'][frame])
    draw = ImageDraw.Draw(canvas)
    rows = {provider: _row(snapshot, provider) for provider in ('codex', 'claude')}
    reads = {}
    for provider, row in rows.items():
        value, _, _, reset = remaining_reading(row)
        count, old = banked_hearts(row)
        reads[provider] = (reset, count, old)
        _dial(draw, provider, value, count, session_pace(row) if provider == 'claude' else None, icons.marked(count, old))
    # The scoreboard strip, in the manner of the arcade's: names, weekly resets, and the title in the middle.
    for provider, accent, x, align in (('codex', CODEX, 7, 'left'), ('claude', CLAUDE, 153, 'right')):
        reset, count, old = reads[provider]
        _shadowed(draw, (x, 2), provider.upper(), accent, SHADOW[provider], align)
        _shadowed(draw, (x, 10), 'RESET ' + reset.upper(), '#ffffff', '#16306e', align)
        mark = icons.mark(count, old)
        if mark:
            width = len(provider) * 4 + 2
            mx = x + width if align == 'left' else x - width
            _shadowed(draw, (mx, 2), mark, '#ffffff', '#16306e', align)
    _shadowed(draw, (62, 2), 'TOKEN RUN', '#fff1c8', '#8a2a1c')
    image = _crt(canvas).resize((LW * K, LH * K), Image.Resampling.NEAREST)
    if not animated:
        return image
    return image, board_anim.encode(_sprites())
