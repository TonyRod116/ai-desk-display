"""Paint and pack Tidal Rush's original twilight stage on the tablet's pixel grid."""

import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import prepare_game_surf as surf, tablet_media as media


GEOMETRY = {
    'horizon': 146,
    'sun': {'x': 43, 'y': 125, 'r': 18},
    'centre': [122, 147],
    'hole': [119, 144, 40, 36],
    'tip': [69, 154],
    'palm': {'x': -10, 'y': -9},
    'path': [16, 81],
    'lip': [
        [199, 31],
        [181, 26],
        [162, 25],
        [144, 29],
        [126, 37],
        [111, 51],
        [97, 70],
        [86, 93],
        [78, 117],
        [72, 138],
        [69, 154],
    ],
    'line': [
        [97, 203],
        [108, 197],
        [121, 188],
        [133, 177],
        [145, 164],
        [152, 150],
        [155, 135],
        [152, 121],
        [144, 110],
        [132, 105],
        [120, 106],
    ],
    'current': [
        [106, 254],
        [139, 230],
        [159, 201],
        [172, 173],
        [176, 141],
        [170, 109],
        [150, 79],
        [126, 62],
        [108, 70],
        [93, 92],
        [79, 121],
        [69, 151],
    ],
    'foot': [
        [0, 232],
        [38, 228],
        [70, 218],
        [103, 203],
        [133, 183],
        [155, 159],
        [175, 140],
        [199, 125],
    ],
}
UNDERSIDE = [
    [73, 155],
    [81, 149],
    [90, 132],
    [103, 117],
    [116, 108],
    [132, 108],
    [144, 114],
    [151, 127],
    [151, 142],
    [141, 161],
    [128, 179],
    [109, 195],
    [86, 207],
    [61, 216],
    [34, 221],
    [0, 222],
]
SKY = [
    (0, '#181a3a'),
    (0.28, '#3d304e'),
    (0.55, '#865260'),
    (0.77, '#c67a72'),
    (1, '#f5bf80'),
]
DEPTH = [
    (0, '#102c46'),
    (0.22, '#115160'),
    (0.46, '#197d75'),
    (0.70, '#3eaa8e'),
    (1, '#9cdeb0'),
]
SEA = [(0, '#535268'), (0.20, '#3f5365'), (0.59, '#334757'), (1, '#212d43')]


def colour(value):
    return tuple(bytes.fromhex(value.lstrip('#')))


def mix(a, b, amount):
    u = surf.clamp(amount, 0, 1)
    return tuple(round(x + (y - x) * u) for x, y in zip(a, b))


def palette(stops, t):
    for (left, a), (right, b) in zip(stops, stops[1:]):
        if t <= right:
            return mix(colour(a), colour(b), (t - left) / (right - left))
    return colour(stops[-1][1])


def curve(points, x):
    for (left, a), (right, b) in zip(points, points[1:]):
        if min(left, right) <= x <= max(left, right) and left != right:
            u = (x - left) / (right - left)
            return a + (b - a) * u
    return points[-1][1]


def distance(x, y, points):
    best = float('inf')
    for (a, b), (c, d) in zip(points, points[1:]):
        dx, dy = c - a, d - b
        u = surf.clamp(((x - a) * dx + (y - b) * dy) / (dx * dx + dy * dy), 0, 1)
        best = min(best, (x - a - dx * u) ** 2 + (y - b - dy * u) ** 2)
    return math.sqrt(best)


def paint_background(noise):
    """The sun, sky and sea behind a wave that can uncover them."""
    horizon = GEOMETRY['horizon']
    picture = Image.new('RGB', (surf.W, surf.H))
    pixels = picture.load()
    classes = bytearray(surf.W * surf.H)
    height = [
        (0, 131),
        (6, 127),
        (11, 129),
        (19, 135),
        (23, 134),
        (29, 139),
        (38, 143),
        (47, 146),
    ]
    cape = [curve(height, x) if x <= 47 else horizon for x in range(surf.W)]
    sx, sy, radius = GEOMETRY['sun'].values()
    sky_ramp = [palette(SKY, y / horizon) for y in range(horizon + 1)]
    sea_ramp = [palette(SEA, y / 174) for y in range(surf.H - horizon)]
    warm = colour('#ffc88d')
    for y in range(surf.H):
        for x in range(surf.W):
            i = y * surf.W + x
            grain = noise.value(x * 0.53, y * 0.62)
            if y < horizon:
                classes[i] = surf.CLS_SKY
                pigment = sky_ramp[y]
                sun_distance = math.hypot(x - sx, y - sy)
                glow = max(0, 1 - sun_distance / 87)
                pigment = mix(pigment, warm, glow**1.6 * 0.53)
                clouds = noise.fbm(x * 0.031, y * 0.082, 3)
                streak = math.sin(y * 0.17 + 0.034 * x + clouds * 2.5)
                cloud = surf.clamp((clouds - 0.45) * 4, 0, 1) * (
                    0.45 + 0.55 * max(0, streak)
                )
                pigment = mix(
                    pigment, colour('#463751'), cloud * 0.61 * (1 - glow * 0.58)
                )
                if clouds > 0.54 and streak < -0.15:
                    pigment = mix(pigment, colour('#eea981'), (clouds - 0.54) * 0.76)
                if sun_distance < radius:
                    pigment = mix(
                        colour('#fff1c4'),
                        colour('#f9a973'),
                        (y - sy + radius) / (radius * 2) * 0.55,
                    )
                    if streak < -0.72 and y > sy + 5:
                        pigment = mix(pigment, colour('#c96767'), 0.20)
                if y >= cape[x]:
                    classes[i] = surf.CLS_STILL
                    pigment = mix(
                        colour('#37334b'), colour('#655167'), (y - cape[x]) / 17
                    )
                    if (x * 13 + y * 7) % 41 == 0:
                        pigment = mix(pigment, colour('#e9ab85'), 0.41)
            else:
                classes[i] = surf.CLS_SEA
                z = y - horizon
                pigment = sea_ramp[z]
                rim = math.sin(z * 0.53 + 4 * grain + x * 0.074)
                glitter = max(0, 1 - abs(x - sx) / (6 + z * 0.31))
                if rim > 0.08 and glitter > 0.13:
                    pigment = mix(pigment, warm, glitter * (0.28 + 0.68 * grain))
                elif rim > 0.74:
                    pigment = mix(pigment, colour('#8b8492'), 0.28)
            pixels[x, y] = mix(pigment, colour('#e2c5a3'), 0.022 * grain)
    return picture, classes


def paint_plate():
    noise = surf.Noise(0x28D915)
    background, seascape = paint_background(noise)
    tide = GEOMETRY['lip'] + UNDERSIDE + [[0, surf.H], [surf.W, surf.H]]
    classes = bytearray(surf.classify(GEOMETRY, tide))
    picture = background.copy()
    lower = picture.load()
    wave_ramp = [palette(DEPTH, i / 99) for i in range(100)]
    warm = colour('#ffc88d')
    foam_top, foam_shadow = colour('#fff8e8'), colour('#b1d5d4')
    face_shade = colour('#183b52')
    break_x = GEOMETRY['tip'][0] - 12
    break_y = curve(GEOMETRY['foot'], break_x) - 8
    for y in range(surf.H):
        for x in range(surf.W):
            i = y * surf.W + x
            if classes[i] != surf.CLS_WATER:
                classes[i] = seascape[i]
                continue
            grain = noise.value(x * 0.53, y * 0.62)
            inner = distance(x, y, UNDERSIDE)
            crest = distance(x, y, GEOMETRY['lip'])
            # Translucent green where the lip thins. Deeper blue under
            # the overhang and in the trough below the open face.
            swell = noise.fbm(x * 0.081 - y * 0.033, y * 0.064, 2)
            taper = surf.clamp((y - 142) / 174, 0, 1)
            glaze = math.exp(-crest / 27)
            tube_shadow = math.exp(-inner / 15) * (0.68 + 0.32 * taper)
            reflection_x = 167 + (y - 126) * 0.24
            sheen = math.exp(-abs(x - reflection_x) / 26)
            slope = math.sin((x - 0.43 * y) * 0.105 + 1.8 * swell)
            depth = 0.43 + 0.34 * glaze - 0.31 * taper - 0.23 * tube_shadow
            depth += 0.17 * sheen + 0.068 * slope + 0.21 * (swell - 0.5)
            depth += 0.042 * (grain - 0.5)
            pigment = wave_ramp[round(surf.clamp(depth, 0, 1) * 99)]
            pigment = mix(pigment, face_shade, 0.14 * tube_shadow)
            pigment = mix(pigment, warm, 0.18 * glaze)

            # The crown is ragged, with warm highlights and blue
            # creases. The inside of the arch is a thin glass edge.
            lip_width = 4.4 + 8.8 * swell + 3.8 * grain
            whitecap = surf.clamp(1 - (crest - 0.8) / lip_width, 0, 1)
            whitecap *= 0.57 + 0.43 * surf.clamp((193 - x) / 63, 0, 1)
            if whitecap > 0:
                foam_colour = mix(foam_shadow, foam_top, 0.3 + 0.8 * grain)
                pigment = mix(pigment, foam_colour, whitecap**0.54)
            elif inner < 4 and y < 159:
                pigment = mix(pigment, warm, (1 - inner / 4) * 0.16)

            # White water is already accumulating under the break.
            # The renderer adds moving lobes as the crest lands here.
            dx = x - break_x
            dy = y - break_y + dx * 0.17
            whitewater = 1 - math.hypot(dx / 55, dy / 20)
            whitewater += 0.68 * (swell - 0.52)
            if whitewater > 0:
                foam_colour = mix(foam_shadow, foam_top, 0.15 + 1.06 * grain)
                pigment = mix(
                    pigment, foam_colour, whitewater**0.8 * (0.6 + 0.4 * grain)
                )
            # Reflections in the low sea plane run sideways as the
            # tall face flattens into the foreground.
            foreground = surf.clamp((y - 230 - x * 0.075) / 45, 0, 1)
            if foreground > 0:
                streak = noise.fbm(x * 0.075, y * 0.39 + x * 0.045, 2)
                ocean = mix(colour('#142c43'), colour('#416b75'), streak)
                pigment = mix(pigment, ocean, foreground * foreground * 0.88)
                if foreground > 0.97:
                    classes[i] = surf.CLS_SEA
            lower[x, y] = mix(pigment, colour('#e2c5a3'), 0.022 * grain)
    size = (surf.W, surf.H)
    stacked = Image.new('RGB', (surf.W, 2 * surf.H))
    stacked.paste(picture, (0, 0))
    stacked.paste(background, (0, surf.H))
    common = surf.quantise(stacked, 84, 3)
    return (
        common.crop((0, 0, *size)),
        bytes(classes),
        common.crop((0, surf.H, surf.W, 2 * surf.H)),
    )


def foreground_palm():
    image = Image.new('RGBA', (106, 143))
    ink = ImageDraw.Draw(image)
    trunk = [(32, 140), (35, 115), (43, 91), (52, 65), (60, 49)]
    ink.line(trunk, fill='#382833', width=8)
    ink.line([(x + 2, y - 1) for x, y in trunk], fill='#917058', width=3)
    for y in range(55, 140, 6):
        x = round(curve([(b, a) for a, b in reversed(trunk)], y))
        ink.line((x - 3, y, x + 3, y + 1), fill='#63464a', width=1)
    origin = (60, 49)
    for n, (control, tip) in enumerate(
        [
            ((27, 29), (1, 46)),
            ((22, 42), (14, 76)),
            ((32, 11), (15, 12)),
            ((55, 13), (48, 2)),
            ((78, 11), (97, 9)),
            ((88, 31), (104, 48)),
            ((92, 54), (96, 79)),
            ((69, 63), (77, 103)),
        ]
    ):
        shade = ('#253932', '#315045', '#3b5446', '#4f6450')[n % 4]

        def point(u):
            v = 1 - u
            return (
                origin[0] * v * v + 2 * control[0] * v * u + tip[0] * u * u,
                origin[1] * v * v + 2 * control[1] * v * u + tip[1] * u * u,
            )

        for k in range(1, 20):
            t = k / 20
            x, y = point(t)
            bx, by = point(min(1, t + 0.05))
            length = math.hypot(bx - x, by - y) or 1
            dx, dy = (bx - x) / length, (by - y) / length
            for side in (-1, 1):
                width = (3 + 5.7 * math.sin(math.pi * t)) * (1 - t * 0.53)
                leaf = (
                    x + dx * width * 0.66 - dy * width * side,
                    y + dy * width * 0.66 + dx * width * side,
                )
                ink.polygon(
                    [(x, y), leaf, (bx + dx, by + dy)],
                    fill=shade if side == 1 else '#344939',
                )
                if side == -1 and (n + k) % 3 == 0:
                    ink.point(tuple(round(v) for v in leaf), fill='#8d8864')
        ink.line([point(t / 30) for t in range(31)], fill=shade, width=1)
    for x, y, r in [(58, 53, 4), (65, 55, 4), (59, 59, 3)]:
        ink.ellipse((x - r, y - r, x + r, y + r), fill='#604237')
        ink.line((x - r + 1, y - r + 1, x, y - r + 1), fill='#c79062', width=1)
    return image


def build(destination):
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    plate, classes, background = paint_plate()
    brushes = surf.build_brushes()
    brushes['background'] = background
    palm = foreground_palm()
    atlas, frames = surf.build_atlas(plate, classes, brushes, palm)
    raw = {
        'version': 2,
        'scene': 'surf',
        'size': list(atlas.size),
        'frames': frames,
        'geometry': GEOMETRY,
        'brushes': {
            style: [f'foam-{style}-{i}' for i in range(len(spec[0]))]
            for style, spec in surf.STYLES.items()
        },
    }
    media._write_atomically(
        destination / 'scene-surf.png',
        lambda p: atlas.save(p, format='PNG', optimize=True),
        media.MAX_IMAGE_BYTES,
    )
    media._write_atomically(
        destination / 'scene-surf.json',
        lambda p: p.write_text(json.dumps(raw, separators=(',', ':'))),
        512 * 1024,
    )
    media.save_thumbnail(surf.thumbnail(plate, GEOMETRY, palm), destination / 'thumb-surf.webp')
    media.update_manifest(
        'surf',
        media.scene_entry(
            'game', 'scene-surf.png', 'image', *atlas.size, data='scene-surf.json'
        ),
        destination,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    build(parser.parse_args().out)
