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
    (0, '#0e0a2a'),
    (0.24, '#2c1650'),
    (0.48, '#762864'),
    (0.68, '#d44b64'),
    (0.85, '#f68952'),
    (1, '#ffdd88'),
]
DEPTH = [
    (0, '#040a22'),
    (0.16, '#061a48'),
    (0.32, '#0a387c'),
    (0.48, '#0e60aa'),
    (0.64, '#1492c8'),
    (0.78, '#1cd0cf'),
    (0.91, '#68f4de'),
    (1, '#dcfff5'),
]
SEA = [(0, '#322658'), (0.22, '#1a2856'), (0.58, '#0e1e44'), (1, '#07122c')]
BAYER2 = ((0, 2), (3, 1))


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


def build_streamline(points):
    """Subdivide a guide curve into segments for curvilinear barrel flow mapping."""
    dense = []
    n = len(points)
    for i in range(n - 1):
        p0 = points[max(0, i - 1)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(n - 1, i + 2)]
        for k in range(6):
            t = k / 6
            t2, t3 = t * t, t * t * t
            sx = 0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            sy = 0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            dense.append((sx, sy))
    dense.append(tuple(points[-1]))
    segments = []
    total = 0.0
    for (ax, ay), (bx, by) in zip(dense, dense[1:]):
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length > 1e-6:
            segments.append((ax, ay, dx / length, dy / length, length, total))
            total += length
    return segments, total


def streamline_coords(x, y, segments):
    """Project (x, y) onto the barrel streamline: (along_curl, signed_across)."""
    best_d2 = float('inf')
    along = 0.0
    across = 0.0
    for ax, ay, ux, uy, length, dist in segments:
        px, py = x - ax, y - ay
        u = surf.clamp(px * ux + py * uy, 0.0, length)
        rx, ry = px - u * ux, py - u * uy
        d2 = rx * rx + ry * ry
        if d2 < best_d2:
            best_d2 = d2
            along = dist + u
            across = ry * ux - rx * uy
    return along, across


def paint_background(noise):
    """The sun, sky and sea behind a wave that can uncover them."""
    horizon = GEOMETRY['horizon']
    picture = Image.new('RGB', (surf.W, surf.H))
    pixels = picture.load()
    classes = bytearray(surf.W * surf.H)
    far_ridge = [
        (0, 127),
        (9, 123),
        (17, 126),
        (27, 132),
        (36, 136),
        (45, 141),
        (53, 146),
    ]
    near_ridge = [
        (0, 132),
        (7, 129),
        (14, 133),
        (21, 137),
        (30, 141),
        (40, 146),
    ]
    cape_far = [curve(far_ridge, x) if x <= 53 else horizon for x in range(surf.W)]
    cape_near = [curve(near_ridge, x) if x <= 40 else horizon for x in range(surf.W)]
    sx, sy, radius = GEOMETRY['sun'].values()
    sky_ramp = [palette(SKY, y / horizon) for y in range(horizon + 1)]
    sea_ramp = [palette(SEA, y / 174) for y in range(surf.H - horizon)]
    warm = colour('#ffcf84')
    coral_glow = colour('#ff825c')
    gold_core = colour('#fffce0')
    for y in range(surf.H):
        for x in range(surf.W):
            i = y * surf.W + x
            grain = noise.value(x * 0.53, y * 0.62)
            if y < horizon:
                classes[i] = surf.CLS_SKY
                pigment = sky_ramp[y]
                sun_distance = math.hypot(x - sx, y - sy)
                glow = max(0, 1 - sun_distance / 108)
                tight = max(0, 1 - sun_distance / 42)
                pigment = mix(pigment, coral_glow, glow**1.8 * 0.34)
                pigment = mix(pigment, warm, glow**1.35 * 0.48 + tight**1.8 * 0.38)
                # Warm golden horizon band visible through the barrel mouth too.
                horiz_bloom = math.exp(-max(0, horizon - y) / 16)
                pigment = mix(pigment, warm, horiz_bloom * 0.24)
                clouds = noise.fbm(x * 0.028, y * 0.078, 3)
                streak = math.sin(y * 0.16 + 0.032 * x + clouds * 2.6)
                cloud = surf.clamp((clouds - 0.44) * 3.8, 0, 1) * (
                    0.42 + 0.58 * max(0, streak)
                )
                # Rich violet cloud tops with glowing molten-gold undersides near the sun.
                cloud_shade = mix(colour('#32194c'), colour('#72305c'), glow * 0.6)
                pigment = mix(
                    pigment, cloud_shade, cloud * 0.58 * (1 - tight * 0.72)
                )
                if clouds > 0.51 and streak < -0.10:
                    underlit = surf.clamp((clouds - 0.51) * 2.4, 0, 1) * (0.45 + 0.55 * glow)
                    pigment = mix(pigment, colour('#ffbe78'), underlit * 0.68)
                if sun_distance < radius:
                    v = surf.clamp((y - sy + radius) / (radius * 2), 0, 1)
                    pigment = palette(
                        [
                            (0, '#fffee4'),
                            (0.38, '#ffe388'),
                            (0.72, '#ffaa54'),
                            (1.0, '#f06a52'),
                        ],
                        v,
                    )
                    if (abs(y - (sy + 7)) < 1.1 or abs(y - (sy + 12)) < 1.2) and abs(x - sx) < radius * 0.92:
                        pigment = mix(pigment, colour('#e8685a'), 0.36)
                if y >= cape_far[x]:
                    classes[i] = surf.CLS_STILL
                    if y >= cape_near[x]:
                        depth_c = surf.clamp((y - cape_near[x]) / 14, 0, 1)
                        pigment = mix(colour('#24163b'), colour('#42254c'), depth_c)
                        if y - cape_near[x] < 1.6 and x > 6:
                            pigment = mix(pigment, colour('#df7c68'), 0.52)
                        if y >= horizon - 4 and (x * 17 + y * 11) % 31 == 0:
                            pigment = colour('#ffe6a4')
                        elif (x * 13 + y * 7) % 43 == 0:
                            pigment = mix(pigment, colour('#ffbe7a'), 0.55)
                    else:
                        depth_f = surf.clamp((y - cape_far[x]) / 16, 0, 1)
                        pigment = mix(colour('#4d2b58'), colour('#703b66'), depth_f)
                        if y - cape_far[x] < 1.5 and x > 14:
                            pigment = mix(pigment, colour('#f29c70'), 0.46)
            else:
                classes[i] = surf.CLS_SEA
                z = y - horizon
                pigment = sea_ramp[z]
                # Faint sunset sky wash right beneath the horizon.
                pigment = mix(pigment, colour('#7a4268'), math.exp(-z / 12) * 0.38)
                rim = math.sin(z * 0.56 + 4.2 * grain + x * 0.072)
                glitter = max(0, 1 - abs(x - sx) / (7 + z * 0.34))
                core_glitter = max(0, 1 - abs(x - sx) / (3 + z * 0.14))
                if rim > 0.02 and glitter > 0.10:
                    shimmer = mix(colour('#f07260'), colour('#ffea9e'), surf.clamp(core_glitter * 0.8 + grain * 0.3, 0, 1))
                    pigment = mix(colour('#322250'), shimmer, surf.clamp(glitter * (0.42 + 0.56 * grain), 0, 1))
                elif rim > 0.72:
                    pigment = mix(pigment, colour('#5a5e8a'), 0.30)
            pixels[x, y] = mix(pigment, colour('#e8c8a2'), 0.018 * grain)
    return picture, classes


def paint_plate():
    noise = surf.Noise(0x28D915)
    background, seascape = paint_background(noise)
    tide = GEOMETRY['lip'] + UNDERSIDE + [[0, surf.H], [surf.W, surf.H]]
    classes = bytearray(surf.classify(GEOMETRY, tide))
    picture = background.copy()
    lower = picture.load()
    wave_ramp = [palette(DEPTH, i / 99) for i in range(100)]
    stream_segs, stream_len = build_streamline(GEOMETRY['current'])
    sun_gold = colour('#ffe08c')
    sunset_coral = colour('#ff906c')
    crystal_aqua = colour('#1adcc8')
    crystal_glow = colour('#8affea')
    sky_reflect = colour('#58ace8')
    vein_aqua = colour('#5ce4f4')
    vein_pearl = colour('#eeffff')
    foam_top, foam_warm, foam_mid, foam_deep = (
        colour('#fffaf0'),
        colour('#ffd688'),
        colour('#4cd4e8'),
        colour('#0e4a7a'),
    )
    vault_shadow = colour('#030b24')
    break_x = GEOMETRY['tip'][0] - 12
    break_y = curve(GEOMETRY['foot'], break_x) - 8
    for y in range(surf.H):
        for x in range(surf.W):
            i = y * surf.W + x
            if classes[i] != surf.CLS_WATER:
                classes[i] = seascape[i]
                continue
            grain = noise.value(x * 0.53, y * 0.62)
            dither = (BAYER2[y & 1][x & 1] - 1.5) * 0.030
            inner = distance(x, y, UNDERSIDE)
            crest = distance(x, y, GEOMETRY['lip'])
            along, across = streamline_coords(x, y, stream_segs)
            along_u = surf.clamp(along / max(1.0, stream_len), 0.0, 1.0)

            # Anisotropic curvilinear 90s-arcade water striations: bold sweeping
            # concentric flow bands & glossy draw-lines racing up the wall and
            # curving cleanly overhead through the barrel.
            warp = noise.fbm(along * 0.016, across * 0.052, 2) - 0.5
            flow_fine = noise.fbm(along * 0.013, across * 0.21 + warp * 1.6, 3)
            flow_broad = noise.fbm(along * 0.019 + 4.3, across * 0.082 + warp * 0.85, 2)
            ribs = math.sin(across * 0.36 + warp * 4.2 + along * 0.016)
            fine_ribs = math.sin(across * 0.76 + warp * 5.8 - along * 0.025)

            # Iconic Capcom/SNK/Sega barrel lighting:
            # - Deep midnight-indigo concave pocket behind the rider
            # - Rich cobalt-cerulean curved wall with electric azure ribs
            # - Luminous backlit emerald-turquoise sea-glass window where the
            #   thin curling roof catches the setting sun from behind!
            taper = surf.clamp((y - 152) / 164.0, 0.0, 1.0)
            glaze = math.exp(-crest / 24.0)
            upper_arch = surf.clamp((150 - y) / 96.0, 0.0, 1.0)
            sun_facing = surf.clamp((168 - x) / 86.0, 0.0, 1.0)
            thin_backlit = glaze * upper_arch * (0.42 + 0.58 * math.exp(-inner / 34.0))
            glass_window = (
                math.exp(-((crest - 12.0) / 14.0) ** 2)
                * surf.clamp((146 - y) / 76.0, 0.0, 1.0)
                * (0.45 + 0.55 * sun_facing)
            )
            vault = math.exp(-inner / 20.0) * (0.58 + 0.42 * taper) * (1.0 - 0.72 * max(thin_backlit, glass_window))
            sheen_center = 4.5 + 7.2 * math.sin(along_u * 4.5)
            glass_sheen = math.exp(-((across - sheen_center) / 17.0) ** 2) * (0.60 + 0.40 * (1.0 - taper))

            depth = (
                0.35
                + 0.38 * thin_backlit
                + 0.24 * glass_window
                + 0.21 * glass_sheen
                - 0.35 * taper
                - 0.28 * vault
            )
            depth += 0.13 * (flow_fine - 0.5) + 0.10 * (flow_broad - 0.5)
            depth += 0.092 * ribs + 0.038 * fine_ribs
            # Crisp 16-bit/32-bit stepped color bands with 2x2 ordered Bayer dithering.
            banded = round(surf.clamp(depth + dither, 0.0, 1.0) * 12.0) / 12.0
            pigment = wave_ramp[round(surf.clamp(banded, 0.0, 1.0) * 99)]

            # Deepen the concave vault into classic Neo-Geo midnight indigo.
            pigment = mix(pigment, vault_shadow, 0.42 * vault)
            # Glossy electric-azure sky sheen on the curved barrel ribs.
            rib_gloss = surf.clamp((ribs - 0.12) * 1.18, 0.0, 1.0) * glass_sheen * (1.0 - taper * 0.50)
            if rib_gloss > 0.14:
                pigment = mix(pigment, sky_reflect, surf.clamp(rib_gloss * 0.46, 0.0, 0.50))

            # Luminous backlit sea-glass emerald-turquoise window inside the thin roof!
            backlit_power = max(thin_backlit, glass_window * 0.95)
            if backlit_power > 0.10:
                pigment = mix(pigment, crystal_aqua, surf.clamp(backlit_power * 0.76, 0.0, 0.78))
                if backlit_power > 0.44 and inner < 28:
                    pigment = mix(pigment, crystal_glow, surf.clamp((backlit_power - 0.44) * 1.05, 0.0, 0.62))

            # Crisp lacy foam veins & crest tendrils ("barrel cobwebs") pulled
            # along the curved streamlines up the face and arching overhead.
            vein_noise = noise.fbm(along * 0.022 + 7.2, across * 0.35 + warp * 2.4, 3)
            vein_ridge = surf.clamp((vein_noise - 0.60) * 6.0, 0.0, 1.0)
            vein_zone = surf.clamp((along_u - 0.14) / 0.50, 0.0, 1.0) * (1.0 - taper * 0.70)
            crest_tendril = math.exp(-crest / 24.0) * surf.clamp((vein_noise - 0.52) * 5.2, 0.0, 1.0)
            vein = max(vein_ridge * vein_zone * (0.48 + 0.52 * abs(fine_ribs)), crest_tendril * 0.88)
            if vein > 0.16:
                vein_col = vein_pearl if vein > 0.54 else vein_aqua
                pigment = mix(pigment, vein_col, surf.clamp(vein * 0.74, 0.0, 0.84))

            # Warm golden sunset glow strictly on the sun-facing upper lip edge
            # (leaving the mid-face vivid blue/turquoise for rider & wake pop!).
            upper_lip_sun = math.exp(-crest / 11.5) * surf.clamp((142 - y) / 98.0, 0.0, 1.0) * surf.clamp((156 - x) / 76.0, 0.0, 1.0)
            if upper_lip_sun > 0.08:
                pigment = mix(pigment, sun_gold, 0.34 * upper_lip_sun)

            # Bold sculpted 90s-arcade scalloped whitecap crest (4 crisp tones:
            # deep cobalt underside -> turquoise mid -> pearl -> sunset gold rim).
            scallop = 0.5 + 0.5 * math.sin(along * 0.24 + noise.fbm(along * 0.06, across * 0.14, 2) * 4.2)
            lip_width = 4.6 + 6.8 * scallop + 2.4 * grain
            whitecap = surf.clamp(1.0 - (crest - 0.8) / lip_width, 0.0, 1.0)
            whitecap *= 0.68 + 0.32 * surf.clamp((196 - x) / 62.0, 0.0, 1.0)
            if whitecap > 0.05:
                sun_kiss = surf.clamp((160 - x) / 84.0, 0.0, 1.0)
                lit_crest = mix(foam_top, foam_warm, 0.50 * sun_kiss)
                w_step = whitecap + dither * 1.5
                if w_step < 0.28:
                    foam_colour = foam_deep
                elif w_step < 0.56:
                    foam_colour = foam_mid
                elif w_step < 0.80:
                    foam_colour = foam_top
                else:
                    foam_colour = lit_crest
                pigment = mix(pigment, foam_colour, surf.clamp(whitecap**0.38, 0.0, 0.96))
            elif inner < 5.5 and y < 156:
                glass_rim = (1.0 - inner / 5.5) * surf.clamp((156 - y) / 56.0, 0.0, 1.0)
                rim_col = mix(sunset_coral, sun_gold, surf.clamp((156 - y) / 50.0, 0.0, 1.0))
                pigment = mix(pigment, rim_col, glass_rim * 0.54)

            # Organic turbulent 90s-arcade cauldron foam bed (replaces oval
            # stepping stones with ragged multi-scale boiling surf tongues).
            dx_c = x - break_x
            dy_c = y - break_y + dx_c * 0.14
            reach_c = 52.0 if dx_c > 0 else 48.0
            height_c = 17.0 if dy_c > 0 else 11.5 + 5.5 * math.exp(-(dx_c / 26.0) ** 2)
            ell = math.hypot(dx_c / reach_c, dy_c / height_c)
            if ell < 1.28:
                billow_a = noise.fbm(x * 0.11 + 2.1, y * 0.16, 3)
                billow_b = noise.fbm(x * 0.23 - 5.4, y * 0.28, 2)
                ragged = (billow_a - 0.45) * 0.62 + (billow_b - 0.48) * 0.34
                foam_field = surf.clamp(1.0 - ell + ragged, 0.0, 1.0)
                if foam_field > 0.10:
                    sun_side = surf.clamp((92 - x) / 68.0, 0.0, 1.0)
                    lit_foam = mix(foam_top, foam_warm, 0.36 * sun_side)
                    # Shade each turbulent crest upward with crisp 3-tone arcade steps.
                    crest_lit = surf.clamp(0.55 - dy_c / 18.0 + (billow_b - 0.46) * 0.95, 0.0, 1.0) + dither * 1.4
                    if crest_lit < 0.32:
                        foam_colour = foam_deep
                    elif crest_lit < 0.62:
                        foam_colour = foam_mid
                    else:
                        foam_colour = lit_foam
                    pigment = mix(pigment, foam_colour, surf.clamp(foam_field**0.48, 0.0, 0.94))

            # Deep glossy 90s-arcade foreground ocean trough below the wave:
            # rich midnight-sapphire water with sweeping turquoise contour
            # ripples and subtle twilight magenta/gold horizon reflections.
            foreground = surf.clamp((y - 226 - x * 0.075) / 46.0, 0.0, 1.0)
            if foreground > 0:
                streak = noise.fbm(x * 0.048, y * 0.32 + x * 0.030, 2)
                dash = math.sin(y * 0.44 + x * 0.055 + streak * 4.4)
                caustic = math.exp(-abs(x - (108 + (y - 228) * 0.34)) / 58.0) * (1.0 - foreground * 0.42)
                ocean = mix(colour('#040d28'), colour('#0f447c'), surf.clamp(streak * 1.12 + dither, 0.0, 1.0))
                if dash > 0.50 and caustic > 0.18:
                    ocean = mix(ocean, colour('#2eb2d8'), surf.clamp((dash - 0.50) * 2.0 * caustic, 0.0, 0.72))
                elif dash > 0.70 and x < 104:
                    ocean = mix(ocean, colour('#c46c80'), 0.30)
                pigment = mix(pigment, ocean, foreground * foreground * 0.90)
                if foreground > 0.97:
                    classes[i] = surf.CLS_SEA
            lower[x, y] = pigment
    size = (surf.W, surf.H)
    stacked = Image.new('RGB', (surf.W, 2 * surf.H))
    stacked.paste(picture, (0, 0))
    stacked.paste(background, (0, surf.H))
    common = surf.quantise(stacked, 116, 2)
    return (
        common.crop((0, 0, *size)),
        bytes(classes),
        common.crop((0, surf.H, surf.W, 2 * surf.H)),
    )


def foreground_palm():
    image = Image.new('RGBA', (106, 143))
    ink = ImageDraw.Draw(image)
    trunk = [(31, 140), (35, 114), (43, 90), (52, 65), (60, 49)]
    ink.line(trunk, fill='#26162c', width=9)
    ink.line([(x + 1, y) for x, y in trunk], fill='#5c363e', width=5)
    ink.line([(x + 3, y - 1) for x, y in trunk], fill='#d48b5c', width=2)
    for y in range(54, 140, 5):
        x = round(curve([(b, a) for a, b in reversed(trunk)], y))
        ink.line((x - 4, y, x + 3, y + 1), fill='#3a2036', width=1)
        ink.point((x + 3, y), fill='#f0b476')
    origin = (60, 49)
    fronds = [
        ((26, 28), (1, 47)),
        ((20, 42), (10, 78)),
        ((31, 10), (14, 11)),
        ((54, 11), (47, 1)),
        ((79, 10), (99, 8)),
        ((88, 29), (105, 48)),
        ((91, 52), (96, 82)),
        ((69, 63), (78, 104)),
        ((41, 56), (34, 92)),
    ]
    for n, (control, tip) in enumerate(fronds):
        shade = ('#183430', '#21483e', '#2c5c4a', '#3b6d54')[n % 4]
        lit_leaf = '#4e7e5b' if n in (0, 1, 6, 7, 8) else '#305446'

        def point(u):
            v = 1 - u
            return (
                origin[0] * v * v + 2 * control[0] * v * u + tip[0] * u * u,
                origin[1] * v * v + 2 * control[1] * v * u + tip[1] * u * u,
            )

        for k in range(1, 22):
            t = k / 22
            x, y = point(t)
            bx, by = point(min(1, t + 0.05))
            length = math.hypot(bx - x, by - y) or 1
            dx, dy = (bx - x) / length, (by - y) / length
            for side in (-1, 1):
                width = (3.2 + 6.0 * math.sin(math.pi * t)) * (1 - t * 0.50)
                leaf = (
                    x + dx * width * 0.66 - dy * width * side,
                    y + dy * width * 0.66 + dx * width * side,
                )
                ink.polygon(
                    [(x, y), leaf, (bx + dx, by + dy)],
                    fill=shade if side == 1 else lit_leaf,
                )
                # Warm golden sunset rim-light kissing the undersides & tips of fronds.
                if side == -1 and (n + k) % 2 == 0 and t > 0.15:
                    rim_c = '#f0ca78' if y > 40 else '#c89e64'
                    ink.point(tuple(round(v) for v in leaf), fill=rim_c)
        ink.line([point(t / 30) for t in range(31)], fill='#1a2b2d', width=1)
    for x, y, r in [(57, 52, 4), (64, 54, 4), (59, 59, 4), (64, 60, 3)]:
        ink.ellipse((x - r, y - r, x + r, y + r), fill='#4a2a28')
        ink.ellipse((x - r + 1, y - r + 1, x + r - 1, y + r - 1), fill='#784836')
        ink.line((x - r + 1, y - r + 1, x + 1, y - r + 1), fill='#f2ba78', width=1)
    return image


def build(destination):
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    plate, classes, background = paint_plate()
    palm = foreground_palm()
    brushes = surf.build_brushes()
    brushes['background'] = background
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
