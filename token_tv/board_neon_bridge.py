"""A richer full-screen city, with independent weekly light circuits under its bridge.

The building lights are scenery. Codex withdraws left and Claude right as quota
is spent. All motion runs on the board; the PC only sends changed readings.
The previous tower-gauge variant remains in board_neon_realistic for rollback.
"""
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from token_tv import board_anim
from token_tv.board_art import _row
from token_tv.board_neon_realistic import city_motion
from token_tv.personal_faces import remaining_reading, session_pace
from token_tv.themes import face

SCALE = 4
COLORS = {'codex': (255, 185, 69), 'claude': (81, 220, 255)}
# Each half has 26 architectural lamp modules, with a narrow unlit central joint.
# The coordinates follow the actual underside of the generated bridge, not a HUD.
RAILS = {'codex': (72, 176), 'claude': (181, 285)}
HALVES = {'codex': (68, 164, 177, 200), 'claude': (179, 164, 289, 200)}


@lru_cache(maxsize=1)
def photograph():
    with Image.open(Path(__file__).with_name('assets') / 'neon-city-bridge.png') as source:
        if source.size != (320, 240):
            raise ValueError('The bridge city must be prepared at 320x240')
        return source.convert('RGB')


def _lamps(image, provider, remaining):
    """Light only the available length, anchored to each bridge's outer end.

    The inactive apertures are dark metal/glass, never a translucent screen wash.
    Unknown uses sparse neutral diagnostic lamps instead of a full/empty circuit.
    """
    box = HALVES[provider]
    ox, oy = box[:2]
    size = ((box[2]-ox)*SCALE, (box[3]-oy)*SCALE)
    fixtures = Image.new('RGBA', size)
    emission = Image.new('RGB', size)
    d, light = ImageDraw.Draw(fixtures), ImageDraw.Draw(emission)
    start, end = RAILS[provider]
    amount = None if remaining is None else (end-start)*max(0, min(100, remaining))/100
    color = COLORS[provider]

    def rect(draw, x0, x1, y0, y1, fill):
        draw.rectangle(((x0-ox)*SCALE, (y0-oy)*SCALE,
                        (x1-ox)*SCALE-1, (y1-oy)*SCALE-1), fill=fill)

    for i, x in enumerate(range(start, end, 4)):
        # Narrow seams and tiny chamfers keep this looking like physical lighting.
        rect(d, x, x+3.3, 169.8, 172.8, (9, 17, 24, 235))
        rect(d, x+.25, x+3.05, 170, 170.25, (71, 86, 99, 160))
        if amount is None:
            if i % 4 == 0:
                rect(light, x+.7, x+2.5, 170.8, 171.8, (91, 103, 112))
            continue
        lo = x if provider == 'codex' else max(x, end-amount)
        hi = min(x+3.3, start+amount) if provider == 'codex' else x+3.3
        if hi-lo < .25:
            continue
        rect(light, lo, hi, 170.25, 172.45, color)
        # A nearly white lamp core, with colored glass and a tight optical halo.
        core = tuple(round(c*.35 + 255*.65) for c in color)
        rect(light, lo, hi, 170.7, 171.45, core)

    glow = emission.filter(ImageFilter.GaussianBlur(SCALE*.8)).point(lambda c: round(c*.72))
    # Composite at native resolution so the photograph outside the fixtures stays exact.
    fixture_layer = fixtures.resize((box[2]-ox, box[3]-oy), Image.Resampling.LANCZOS)
    photo = image.crop(box).convert('RGBA')
    photo = Image.alpha_composite(photo, fixture_layer).convert('RGB')
    lit = ImageChops.screen(glow, emission).resize(photo.size, Image.Resampling.LANCZOS)
    image.paste(ImageChops.screen(photo, lit), box[:2])


def _sign(image, provider, remaining, pace):
    """Small hanging transit signs fixed to the bridge, with readable weekly values."""
    x, y = (74, 175) if provider == 'codex' else (240, 175)
    width, height = 47, 12
    extra = 8 if provider == 'claude' and pace is not None else 0
    sign = Image.new('RGBA', (width*SCALE, (height+extra)*SCALE))
    d = ImageDraw.Draw(sign)
    color = COLORS[provider]
    tint = tuple(round(c*.35+255*.65) for c in color)
    # Bolts and short suspension rods tie the sign to the actual bridge structure.
    d.line((3*SCALE, 0, 3*SCALE, 2*SCALE), fill='#9aa9ae', width=2)
    d.line(((width-3)*SCALE, 0, (width-3)*SCALE, 2*SCALE), fill='#9aa9ae', width=2)
    d.rectangle((0, 2*SCALE, width*SCALE-1, height*SCALE-1), fill=(7, 15, 24, 245),
                outline=(75, 90, 99, 230), width=2)
    d.line((SCALE, 2.8*SCALE, (width-1)*SCALE, 2.8*SCALE), fill=(*color, 140), width=1)
    value = '--' if remaining is None else '<1%' if 0 < remaining < 1 else f'{round(remaining)}%'
    d.text((3*SCALE, 5*SCALE), provider.upper(), fill=tint,
           font=face('oxanium.woff2', round(4.7*SCALE)))
    d.text(((width-3)*SCALE, 3*SCALE), value, anchor='rt', fill=tint,
           font=face('oxanium.woff2', round(8.3*SCALE)))
    if extra:
        d.rectangle((0, height*SCALE, width*SCALE-1, (height+extra)*SCALE-1),
                    fill=(7, 15, 24, 245), outline=(75, 90, 99, 230), width=2)
        # Identical five-hour semantics to the other screens: quota then time.
        units = (math.ceil(pace[0]/5)/4, round(pace[1]*4)/4)
        for row, amount in enumerate(units):
            for i in range(5):
                px, py = (3+i*8)*SCALE, (height+1.5+row*3)*SCALE
                d.rectangle((px, py, px+6*SCALE-1, py+1.5*SCALE-1), fill='#283e4b')
                fraction = max(0, min(1, amount-i))
                if fraction:
                    d.rectangle((px, py, px+6*SCALE*fraction-1, py+1.5*SCALE-1),
                                fill=tint if row == 0 else '#7e9eaa')
    sign = sign.resize((width, height+extra), Image.Resampling.LANCZOS)
    image.paste(sign, (x, y), sign)


@lru_cache(maxsize=1)
def ambient_motion():
    """Animate two small existing facade neons, independent of provider readings."""
    result = []
    for index, (x, y, width, height) in enumerate(((65, 80, 2, 8), (279, 138, 2, 8))):
        patch = photograph().crop((x, y, x+width, y+height)).resize(
            (width//2, height//2), Image.Resampling.LANCZOS)
        levels = (1, .9, 1.18, .9) if index == 0 else (1, .75, 1.15, .5)
        frames = tuple(patch.point(lambda c, level=level: min(255, round(c*level))).convert('RGBA')
                       for level in levels)
        phases = [i//8 for i in range(32)] if index == 0 else [0]*27 + [1, 0, 3, 2, 0]
        result.append({'x': x, 'y': y, 'frames': frames,
                       'script': [(phase, 0, 0) for phase in phases],
                       'step_ms': 280 if index == 0 else 700})
    return tuple(result)


def render_neon_bridge(snapshot, animated=False):
    image = photograph().copy()
    for provider in ('codex', 'claude'):
        row = _row(snapshot, provider)
        remaining, _, old, _ = remaining_reading(row)
        if old:
            remaining = None
        pace = session_pace(row) if provider == 'claude' and not old else None
        _lamps(image, provider, remaining)
        _sign(image, provider, remaining, pace)
    for light in ambient_motion():
        frame = light['frames'][0]
        first = frame.resize((frame.width*2, frame.height*2), Image.Resampling.NEAREST)
        image.paste(first, (light['x'], light['y']), first)
    if animated:
        return image, board_anim.encode(city_motion() + ambient_motion())
    return image
