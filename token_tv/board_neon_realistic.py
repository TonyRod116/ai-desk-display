"""Photographic city: facade power is weekly quota, signs are part of the scene."""
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from token_tv import board_anim
from token_tv.board_art import _row
from token_tv.personal_faces import remaining_reading, session_pace
from token_tv.themes import face
from token_tv.board_neon_lighting import AMBIENT_ACCENTS, enrich_city, inhabit_city

# Hand-traced architectural silhouettes, never the sky/street or the other account.
FACADES = {
    'codex': ((43, 11), (78, 10), (95, 20), (98, 34), (96, 52),
              (91, 59), (95, 79), (98, 87), (97, 118), (107, 126),
              (108, 153), (104, 178), (99, 202), (82, 219), (51, 222),
              (51, 151), (47, 122), (47, 81), (35, 71),
              (35, 59), (43, 57)),
    'claude': ((267, 22), (281, 17), (292, 20), (291, 82), (299, 85),
               (298, 106), (295, 115), (295, 163), (297, 211), (282, 222), (257, 215),
               (254, 169), (260, 144),
               (260, 129), (267, 121), (269, 106), (265, 94), (266, 78)),
}
TOWER_HEIGHTS = {'codex': (10, 222), 'claude': (17, 222)}



@lru_cache(maxsize=1)
def photograph():
    with Image.open(Path(__file__).with_name('assets') / 'neon-city-realistic-soft.png') as source:
        if source.size != (320, 240):
            raise ValueError('The full-screen city must be prepared at 320x240')
        return source.convert('RGB')


@lru_cache(maxsize=1)
def backdrop():
    image = enrich_city(photograph())
    powered = enrich_city(photograph(), powered=True).load()
    pixels = image.load()
    # Stronger quota light belongs only to the two towers, never the surrounding city.
    for provider in ('codex', 'claude'):
        for point in facade_pixels(provider):
            pixels[point] = powered[point]
    return inhabit_city(image)


@lru_cache(maxsize=2)
def facade_pixels(provider):
    mask = Image.new('1', (320, 240))
    ImageDraw.Draw(mask).polygon(FACADES[provider], fill=1)
    return tuple((x, y) for y in range(9, 226) for x in range(320) if mask.getpixel((x, y)))


@lru_cache(maxsize=1)
def unlit_photograph():
    """Switch emissive circuits off, restoring nearby unlit surface detail.

    Connected coloured windows/neons are separate from the facade material.
    A few small circuits survive as ambient occupancy; large signs switch off.
    This is not a translucent wash over the building or dimming every pixel.
    """
    source = photograph()
    image = source.copy()
    pixels = image.load()
    shadow = source.filter(ImageFilter.MinFilter(5)).load()
    for provider in ('codex', 'claude'):
        candidates = set()
        for p in facade_pixels(provider):
            rgb = source.getpixel(p)
            peak = max(rgb)
            if peak > 80 and (peak - min(rgb) > 18 or peak > 125):
                candidates.add(p)
        while candidates:
            seed = min(candidates)
            candidates.remove(seed)
            circuit, pending = [seed], [seed]
            while pending:
                x, y = pending.pop()
                for q in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if q in candidates:
                        candidates.remove(q)
                        circuit.append(q)
                        pending.append(q)
            # Sparse small occupied windows, never a whole luminous neon sign.
            if len(circuit) <= 12 and (seed[0]*17 + seed[1]*31) % 13 == 0:
                continue
            for x, y in circuit:
                rgb, nearby = pixels[x,y], shadow[x,y]
                # Nearby surface supplies texture; the lamp's colour is residual.
                pixels[x,y] = tuple(round(.08*c + .92*min(n,38))
                                     for c,n in zip(rgb,nearby))
    return image


@lru_cache(maxsize=1)
def inhabited_backdrop():
    return inhabit_city(unlit_photograph())


def illuminate(image, provider, remaining):
    """Remove upper light circuits with a soft six-pixel height transition.

    Only the dense quota lighting goes out; sparse residential lights stay on.
    Material stays visible; missing data leaves the scenery untouched.
    """
    if remaining is None or remaining >= 100:
        return
    top, bottom = TOWER_HEIGHTS[provider]
    boundary = bottom - (bottom - top) * max(0, remaining) / 100
    dark = inhabited_backdrop().load()
    pixels = image.load()
    for x, y in facade_pixels(provider):
        weight = 1 if remaining <= 0 else max(0, min(1, (boundary + 3 - y) / 6))
        if weight:
            weight = weight * weight * (3 - 2 * weight)
            pixels[x, y] = tuple(round(a + (b - a) * weight)
                                 for a, b in zip(pixels[x, y], dark[x, y]))


def sign(image, provider, value, pace=None):
    """Supersampled emissive signage on the existing slanted foreground facades."""
    scale = 4
    width, height = (44, 20) if provider == 'codex' else (38, 28)
    origin = (38, 205) if provider == 'codex' else (279, 175)
    slope = -13 / 44 if provider == 'codex' else 8 / 38
    tint = (255, 218, 150) if provider == 'codex' else (218, 239, 255)
    panel = Image.new('RGB', (width * scale, height * scale), '#101425')
    d = ImageDraw.Draw(panel)
    d.rectangle((0, 0, width * scale - 1, height * scale - 1), outline='#657b9e', width=2)
    d.text((width * scale / 2, 2 * scale), provider.upper(), anchor='mt',
           font=face('oxanium.woff2', 5 * scale), fill=tint)
    d.text((width * scale / 2, 8 * scale), '--' if value is None else f'{round(value)}%',
           anchor='mt', font=face('oxanium.woff2', 10 * scale), fill=tint)
    if pace is not None:
        # Same semantics as every other face: upper quota, lower time; five segments.
        units = (math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)
        for j, amount in enumerate(units):
            for k in range(5):
                x, y = (3 + k * 6.5) * scale, (20 + j * 4) * scale
                d.rectangle((x, y, x + 5 * scale - 1, y + 2 * scale - 1), fill='#334057')
                fraction = max(0, min(1, amount - k))
                if fraction:
                    d.rectangle((x, y, x + 5 * scale * fraction - 1, y + 2 * scale - 1),
                                fill=tint if j == 0 else '#849eb7')
    # Inverse affine map of a plane receding along the building's street axis.
    canvas = Image.new('RGBA', (320 * scale, 240 * scale))
    ox, oy = origin
    projected = panel.convert('RGBA').transform(canvas.size, Image.Transform.AFFINE,
        (1, 0, -ox * scale, -slope, 1, (slope * ox - oy) * scale),
        Image.Resampling.BICUBIC)
    projected = projected.resize(image.size, Image.Resampling.LANCZOS)
    image.paste(projected, (0, 0), projected)


def _car(width, reverse=False):
    """Small distant vehicles; no flickering pose or brightness animation."""
    image = Image.new('RGBA', (width, 4))
    d = ImageDraw.Draw(image)
    d.line((1, 2, width - 1, 2), fill='#3c526d')
    d.line((width // 3, 1, width - 3, 1), fill='#9bc4da')
    d.point((width - 1, 2), fill='#fff1cd')
    d.point((0, 2), fill='#e380b1')
    d.line((2, 3, width - 3, 3), fill='#1b263c')
    return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if reverse else image


def _lane(y, width, positions, left, right, reverse=False):
    car = _car(width, reverse)
    empty = Image.new('RGBA', car.size)
    entering, leaving = car.copy(), car.copy()
    # The two partial poses are actual occlusion, not transparency in open sky.
    ImageDraw.Draw(entering).rectangle((0, 0, width // 2 - 1, 3), fill=(0, 0, 0, 0))
    ImageDraw.Draw(leaving).rectangle((width // 2, 0, width - 1, 3), fill=(0, 0, 0, 0))
    script = []
    for x in positions:
        pose = 0 if x + width * 2 <= left or x >= right else 2 if x < left else 3 if x + width * 2 > right else 1
        script.append((pose, x - 180, 0))
    return {'x': 180, 'y': y, 'frames': (empty, car, entering, leaving),
            'script': script, 'step_ms': 140}


@lru_cache(maxsize=1)
def city_motion():
    # Mostly 4 screen pixels/tick (29 px/s), no bobbing, no visible loop teleport.
    # Lower air lane emerges behind the central spire and enters the right tower.
    near = [124, 132] + list(range(140, 249, 4)) + [256, 264]
    # Distant traffic is half-sized, flies leftwards, and uses its own disjoint lane.
    far = list(reversed([132, 136] + [round(140 + 116 * i / 27) for i in range(28)] + [260, 264]))
    return (_lane(112, 8, near, 140, 264),
            _lane(88, 4, far, 140, 264, reverse=True))


@lru_cache(maxsize=1)
def ambient_motion():
    lights = []
    for index, (x, y, width, color) in enumerate(AMBIENT_ACCENTS):
        levels = (.8, .9, 1, .9) if index == 0 else (.9, .72, 1, .5)
        frames = tuple(Image.new('RGBA', (width // 2, 1),
                                tuple(round(c * level) for c in color) + (255,))
                       for level in levels)
        phases = [i // 8 for i in range(32)] if index == 0 else [0] * 27 + [1, 0, 3, 2, 0]
        lights.append({'x': x, 'y': y, 'frames': frames,
                       'script': [(phase, 0, 0) for phase in phases],
                       'step_ms': 280 if index == 0 else 700})
    return tuple(lights)


def render_neon_realistic(snapshot, animated=False):
    image = backdrop().copy()
    for provider in ('codex', 'claude'):
        row = _row(snapshot, provider)
        value, _, old, _ = remaining_reading(row)
        if old:
            value = None
        illuminate(image, provider, value)
        pace = session_pace(row) if provider == 'claude' and not old else None
        sign(image, provider, value, pace)
    for light in ambient_motion():
        first = light['frames'][0].resize((light['frames'][0].width * 2, 2), Image.Resampling.NEAREST)
        image.paste(first, (light['x'], light['y']), first)
    if animated:
        return image, board_anim.encode(city_motion() + ambient_motion())
    return image
