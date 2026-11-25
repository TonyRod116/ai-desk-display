"""Prepare the tablet's real-time DEEP BLUE underwater pixel-art scene (`token_tv/tablet_web/game-underwater.js`), offline.

Bakes museum-grade 16-bit pixel-art plates at native 267 x 427 (x3 = 801 x 1281 on the tablet):
  - `bg`: layered atmospheric underwater cliffs, distant sunken Atlantis triumphal archway with coffered pilasters,
          distant kelp forest silhouettes, and a warm sunlit sandy seabed with smooth depth haze
  - `fg`: transparent-water foreground layer with a multi-tiered carved Atlantis masonry tower, weathered shipwreck bow,
          3D-perspective classical colonnades with fluted cracked columns, pedestals, ruined stairs, sculpted statues,
          hanging olive-moss drapes, dark foreground framing rocks, and plump 16-bit coral gardens

    nice -n 15 ionice -c 3 .venv/bin/python -B scripts/prepare_game_underwater.py --out DIR [--manifest]
"""
import argparse
import json
import math
import random
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import tablet_media as media  # noqa: E402
from scripts import underwater_sprites as usprites  # noqa: E402

NAME = 'underwater'
VIEW = (267, 427)
W, H = VIEW
SAND_Y = 346
CW, CH = 134, 214
GUTTER = 1
ATLAS_W = W * 2 + GUTTER
SPRITE_BAND_H = 930
ATLAS_SIZE = (ATLAS_W, H + GUTTER + SPRITE_BAND_H)
SCENE_JS = ROOT / 'token_tv/tablet_web/game-underwater.js'

# Ordered 4x4 Bayer matrix normalized to [-0.5, 0.5]
BAYER4 = (
    (-0.46875,  0.03125, -0.34375,  0.15625),
    ( 0.28125, -0.21875,  0.40625, -0.09375),
    (-0.28125,  0.21875, -0.40625,  0.09375),
    ( 0.46875, -0.03125,  0.34375, -0.15625),
)

# Master hue-shifted 16-bit Atlantis limestone palette: deep navy-ink shadow -> teal-olive mid -> warm sunlit cream
INK   = (6, 15, 24, 255)
DEEP  = (14, 30, 44, 255)
SHAD  = (30, 54, 66, 255)
MID   = (62, 90, 90, 255)
LIT   = (114, 140, 122, 255)
WARM  = (174, 186, 152, 255)
CREAM = (224, 224, 186, 255)
STONE_RAMP = [INK, DEEP, SHAD, MID, LIT, WARM, CREAM]

# Darker foreground silhouette rock ramp (rich blue-slate shadows -> weathered moss-slate highlights)
ROCK_RAMP = [
    (5, 13, 21, 255),
    (12, 25, 38, 255),
    (24, 46, 58, 255),
    (44, 72, 80, 255),
    (76, 106, 104, 255),
    (122, 148, 134, 255),
]

_RGBA_RE = re.compile(r'rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)')


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _lerp(a, b, t):
    return a + (b - a) * t


def _blend_rgb(c0, c1, t):
    return (
        int(round(_lerp(c0[0], c1[0], t))),
        int(round(_lerp(c0[1], c1[1], t))),
        int(round(_lerp(c0[2], c1[2], t))),
        255,
    )


def _hash2(ix, iy, seed):
    n = (ix * 374761393 + iy * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFF) / 16777216.0


def _vnoise(x, y, seed):
    ix, iy = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - ix, y - iy
    ux = fx * fx * (3 - 2 * fx)
    uy = fy * fy * (3 - 2 * fy)
    a = _hash2(ix, iy, seed)
    b = _hash2(ix + 1, iy, seed)
    c = _hash2(ix, iy + 1, seed)
    d = _hash2(ix + 1, iy + 1, seed)
    return (a * (1 - ux) + b * ux) * (1 - uy) + (c * (1 - ux) + d * ux) * uy


def _fbm(x, y, seed, octaves=3):
    val, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        val += amp * _vnoise(x * freq, y * freq, seed + o * 97)
        norm += amp
        amp *= 0.5
        freq *= 2.05
    return val / norm


def _dither_pick(ramp, val, x, y, spread=0.6):
    idx = val * (len(ramp) - 1) + BAYER4[y & 3][x & 3] * spread
    return ramp[int(_clamp(round(idx), 0, len(ramp) - 1))]


def _put(px, x, y, col):
    ix, iy = int(round(x)), int(round(y))
    if 0 <= ix < W and 0 <= iy < H:
        px[ix, iy] = col


def _rect(px, x0, y0, w, h, col):
    ix0, iy0 = max(0, int(round(x0))), max(0, int(round(y0)))
    ix1, iy1 = min(W, int(round(x0 + w))), min(H, int(round(y0 + h)))
    for y in range(iy0, iy1):
        for x in range(ix0, ix1):
            px[x, y] = col


def _darken(px, x0, y0, w, h, factor=0.52):
    """Cast a crisp underwater shadow over already-painted opaque pixels."""
    ix0, iy0 = max(0, int(round(x0))), max(0, int(round(y0)))
    ix1, iy1 = min(W, int(round(x0 + w))), min(H, int(round(y0 + h)))
    for y in range(iy0, iy1):
        for x in range(ix0, ix1):
            r, g, b, a = px[x, y]
            if a > 0:
                px[x, y] = (
                    max(6, int(r * factor)),
                    max(14, int(g * factor + 2)),
                    max(22, int(b * factor + 4)),
                    a,
                )


def _paint_block(px, x0, y0, w, h, shade_bias=0.0, top_sun=True, right_sun=True, seed=11):
    """Paint one beveled, weathered 16-bit carved stone masonry block with dark ink mortar joints."""
    if w < 3 or h < 3:
        return
    for dy in range(h):
        for dx in range(w):
            x, y = x0 + dx, y0 + dy
            if not (0 <= x < W and 0 <= y < H):
                continue
            # Crisp 1px ink mortar on bottom & shadowed edges
            if dy == h - 1 or (not right_sun and dx == w - 1) or (right_sun and dx == 0 and w > 5):
                px[x, y] = INK
                continue
            # Sunlit top bevel
            if dy == 0 and top_sun:
                n = _hash2(x, y, seed)
                px[x, y] = CREAM if (n > 0.35 and shade_bias > -0.15) else WARM if shade_bias > -0.35 else LIT
                continue
            # Sunlit right bevel
            if dx == w - 1 and right_sun:
                px[x, y] = WARM if dy < h - 2 else MID
                continue
            # Bottom inner shadow bevel
            if dy == h - 2:
                px[x, y] = DEEP if shade_bias < 0.0 else SHAD
                continue
            # Subtle weathered limestone texture inside block
            n = _fbm(x * 0.16, y * 0.18, seed, 2)
            grad = (1.0 - dy / max(1, h - 1)) * 0.24 + (dx / max(1, w - 1) if right_sun else (1.0 - dx / max(1, w - 1))) * 0.24
            val = _clamp(0.32 + grad + (n - 0.5) * 0.28 + shade_bias, 0.08, 0.92)
            # Occasional chipped dark pit
            if n < 0.18 and 1 < dx < w - 2 and 1 < dy < h - 2:
                px[x, y] = DEEP
            else:
                px[x, y] = _dither_pick(STONE_RAMP[1:6], val, x, y, 0.38)


def _paint_boulder(px, cx, cy, rx, ry, ramp, seed, light_dir=(0.65, -0.76), outline=INK, sand_bounce=False):
    """Pass-4 sculpted 16-bit boulder with directional light, moss lichen cushions, rock strata cracks & sand bounce-light."""
    lx, ly = light_dir
    mask = {}
    for dy in range(-ry - 1, ry + 2):
        for dx in range(-rx - 1, rx + 2):
            ang = math.atan2(dy, dx)
            facet = 1.0 + 0.14 * math.sin(ang * 3.0 + seed) + 0.09 * math.cos(ang * 5.0 - seed * 1.7)
            d = math.hypot(dx / max(1, rx * facet), dy / max(1, ry * facet))
            if d <= 1.0:
                mask[(dx, dy)] = d
    for (dx, dy), d in mask.items():
        x, y = cx + dx, cy + dy
        if not (0 <= x < W and 0 <= y < H):
            continue
        is_edge = any((dx + ox, dy + oy) not in mask for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)))
        is_top = (dx, dy - 1) not in mask
        if is_edge and not is_top:
            px[x, y] = outline
            continue
        nx, ny = dx / max(1.0, rx), dy / max(1.0, ry)
        ndotl = nx * lx + ny * ly
        n = _fbm(x * 0.14, y * 0.14, seed, 2)
        crk = _fbm(x * 0.24, y * 0.34, seed + 91, 2)
        shade = 0.40 + ndotl * 0.44 + (n - 0.5) * 0.22 - d * 0.12
        if is_top:
            shade += 0.30
        # Subtle internal rock crevice lines
        if 0.46 < crk < 0.50 and not is_top and d < 0.88:
            px[x, y] = ramp[1]
            continue
        # Soft sunlit olive-moss cushion along upper-facing shoulders
        if is_top and n > 0.56 and ndotl > 0.15:
            px[x, y] = (128, 166, 92, 255) if n > 0.70 else (72, 114, 74, 255)
            continue
        # Warm reflected sand bounce-light on lower sand-facing flank!
        if sand_bounce and dy > ry * 0.15 and ((lx > 0 and dx > rx * 0.45) or (lx < 0 and dx < -rx * 0.45)):
            px[x, y] = (84, 110, 96, 255) if shade > 0.32 else (52, 78, 76, 255)
            continue
        px[x, y] = _dither_pick(ramp, _clamp(shade, 0.05, 0.98), x, y, 0.38)


def _paint_medallion(px, cx, cy, r, right_sun=True):
    """Carved ancient Atlantis stone wheel/spiral medallion embedded in temple masonry."""
    for dy in range(-r - 1, r + 2):
        for dx in range(-r - 1, r + 2):
            d = math.hypot(dx, dy)
            if d > r + 0.6:
                continue
            x, y = cx + dx, cy + dy
            if d > r - 0.8:
                _put(px, x, y, INK)
            elif d > r - 2.3:
                lit = (dy < 0) or (dx > 0 if right_sun else dx < 0)
                _put(px, x, y, WARM if (dy < -r * 0.3) else LIT if lit else SHAD)
            elif d > r - 3.6:
                _put(px, x, y, INK)
            elif d < 2.2:
                _put(px, x, y, LIT if dy <= 0 else DEEP)
            else:
                # 4 radial spokes inside recessed carved stone ring
                ang = math.atan2(dy, dx)
                spoke = abs(math.sin(ang * 2.0)) < 0.24
                _put(px, x, y, MID if spoke else DEEP)


def _paint_cornice(px, x0, y0, w, h, right_sun=True, seed=71):
    """3D-perspective classical temple entablature: sunlit top slab, overhanging moulding, dentils & deep shadow."""
    # Top sunlit horizontal stone slab (sloped perspective edge on exposed side)
    top_h = 4
    for dy in range(top_h):
        inset = (top_h - 1 - dy) if right_sun else 0
        out_r = (top_h - 1 - dy) if not right_sun else 0
        sx0 = x0 + (inset if not right_sun else 0)
        sx1 = x0 + w - (out_r if not right_sun else 0) + (dy if right_sun else 0)
        for x in range(sx0, min(W, sx1)):
            if dy == 0:
                c = CREAM if _hash2(x, y0, seed) > 0.25 else WARM
            elif dy == 1:
                c = WARM if (x % 7 != 0) else LIT
            elif dy == 2:
                c = LIT
            else:
                c = SHAD
            _put(px, x, y0 + dy, c)
        _put(px, min(W - 1, sx1), y0 + dy, INK)
    # Thick cornice block row
    bx = x0
    while bx < x0 + w:
        bw = min(14 + (bx * 7) % 10, x0 + w - bx)
        _paint_block(px, bx, y0 + top_h, bw, 6, shade_bias=0.12, top_sun=True, right_sun=right_sun, seed=seed + bx)
        bx += bw
    # Shadowed dentil frieze (carved stone teeth with ink gaps!)
    dy_dent = y0 + top_h + 6
    _rect(px, x0, dy_dent, w, 4, INK)
    for x in range(x0 + 2, x0 + w - 2, 5):
        _rect(px, x, dy_dent, 3, 3, WARM if right_sun else LIT)
        _rect(px, x, dy_dent + 2, 3, 1, SHAD)
    # Lower architrave beam
    _rect(px, x0, dy_dent + 4, w - 3, 4, MID)
    _rect(px, x0, dy_dent + 4, w - 3, 1, LIT)
    _rect(px, x0, dy_dent + 7, w - 3, 1, INK)


def _paint_column(px, x, y0, y1, w, rnd, right_sun=True):
    """Monumental weathered fluted classical Ionic column with carved volutes, jagged cracks, missing chips & plinth."""
    # Ornate Ionic capital
    _rect(px, x - 4, y0, w + 8, 1, INK)
    _rect(px, x - 4, y0 + 1, w + 8, 2, WARM)
    _rect(px, x - 4, y0 + 1, w + 8, 1, CREAM)
    _rect(px, x - 4, y0 + 3, w + 8, 1, SHAD)
    _rect(px, x - 3, y0 + 4, w + 6, 4, MID)
    _rect(px, x - 3, y0 + 8, w + 6, 1, INK)
    # Scroll volutes on left & right of capital
    for vx in (x - 3, x + w - 1):
        _rect(px, vx, y0 + 3, 4, 4, INK)
        _rect(px, vx + 1, y0 + 4, 2, 2, CREAM)
        _put(px, vx + 1, y0 + 5, SHAD)
    # Fluted shaft with crisp cylindrical light + deep flute shadows + drum seams
    for y in range(y0 + 9, y1 - 8):
        # Cast shadow from capital at very top of shaft
        cap_ao = -0.34 * max(0.0, 1.0 - (y - (y0 + 9)) / 9.0)
        for i in range(w):
            if i == 0 or i == w - 1:
                _put(px, x + i, y, INK)
                continue
            u = i / max(1, w - 1)
            cyl = math.sin(u * math.pi)
            dir_lit = (u * 0.42) if right_sun else ((1.0 - u) * 0.42)
            # 4 crisp carved flutes across the shaft
            flute_phase = ((i - 1) % 3)
            flute = -0.28 if flute_phase == 1 else (0.14 if flute_phase == 2 else -0.04)
            n = (_fbm(i * 0.25, y * 0.14, 881 + x, 2) - 0.5) * 0.14
            shade = 0.24 + cyl * 0.34 + dir_lit + flute + n + cap_ao
            if (right_sun and i == w - 2) or (not right_sun and i == 1):
                shade = max(shade, 0.86)  # bright sunlit rim edge
            _put(px, x + i, y, _dither_pick(STONE_RAMP[1:], _clamp(shade, 0.04, 0.98), x + i, y, 0.35))
        # Horizontal stone drum seam every 20px
        if (y - y0) % 20 == 0:
            for i in range(1, w - 1):
                _put(px, x + i, y, DEEP if i < w - 3 else SHAD)
                _put(px, x + i, y + 1, WARM if i > w // 2 else MID)
    # Dramatic diagonal weathered crack + chipped notch
    cy = y0 + 34 + rnd.randint(0, max(12, y1 - y0 - 70))
    for i in range(1, w - 1):
        yy = cy + int(i * 0.62 + math.sin(i * 0.8) * 1.4)
        _put(px, x + i, yy, INK)
        _put(px, x + i, yy + 1, DEEP)
        if i % 3 == 0:
            _put(px, x + i, yy - 1, CREAM)
    # Chipped missing bite on edge of column
    bite_y = cy + 6
    bx_edge = x + (w - 3 if right_sun else 0)
    _rect(px, bx_edge, bite_y, 3, 4, INK)
    # Molded classical base plinth
    _rect(px, x - 2, y1 - 8, w + 4, 1, CREAM)
    _rect(px, x - 2, y1 - 7, w + 4, 2, LIT)
    _rect(px, x - 3, y1 - 5, w + 6, 1, WARM)
    _rect(px, x - 3, y1 - 4, w + 6, 3, MID)
    _rect(px, x - 3, y1 - 1, w + 6, 1, INK)


def _paint_pedestal(px, x0, y0, w, h, right_sun=True):
    """Carved stone temple pedestal base with sunken rosette relief panel (just like reference.jpg!)."""
    _paint_block(px, x0, y0, w, 4, shade_bias=0.18, top_sun=True, right_sun=right_sun, seed=501)
    _paint_block(px, x0 + 2, y0 + 4, w - 4, h - 8, shade_bias=-0.04, top_sun=False, right_sun=right_sun, seed=502)
    # Sunken decorative carved stone panel inside pedestal
    if w >= 16 and h >= 18:
        px0, py0, pw, ph = x0 + 5, y0 + 7, w - 10, h - 14
        _rect(px, px0, py0, pw, ph, DEEP)
        _rect(px, px0 + 1, py0 + 1, pw - 2, ph - 2, SHAD)
        _rect(px, px0 + 1, py0 + ph - 2, pw - 2, 1, LIT)
        _rect(px, px0 + pw - 2, py0 + 1, 1, ph - 2, LIT)
        # Tiny carved diamond/rosette center
        cx, cy = px0 + pw // 2, py0 + ph // 2
        _rect(px, cx - 2, cy - 1, 5, 3, MID)
        _rect(px, cx - 1, cy - 2, 3, 5, MID)
        _put(px, cx, cy, WARM)
    _paint_block(px, x0 - 1, y0 + h - 4, w + 2, 4, shade_bias=-0.12, top_sun=True, right_sun=right_sun, seed=503)


def _paint_ruined_stairs(px, x0, y0, steps, dx_step, dy_step, right_sun=True):
    """Pass-4 diagonal broken stone temple stairs with clean sloped stringer grounded seamlessly into sand."""
    x_end = x0 + (steps - 1) * dx_step + (10 if dx_step > 0 else 2)
    y_end = y0 + (steps - 1) * dy_step + 4
    sx_start = x0 if dx_step > 0 else x0 + 12
    for i in range(56):
        t = i / 55.0
        rx = int(round(_lerp(sx_start, x_end, t)))
        ry = int(round(_lerp(y0 + 2, y_end, t)))
        h_wall = max(3, int(round(_lerp(9, 4, t))))
        _rect(px, rx - 1, ry, 4, h_wall, DEEP)
        _put(px, rx, ry, WARM)
        _put(px, rx, ry + 1, LIT)
        _put(px, rx, ry + h_wall - 1, INK)
    for s in range(steps):
        sx = x0 + s * dx_step
        sy = y0 + s * dy_step
        h_sup = 5 if s < steps - 1 else 3
        _rect(px, sx, sy + 3, 14, h_sup, DEEP)
        _rect(px, sx + (2 if right_sun else 0), sy + 3, 10, max(2, h_sup - 1), SHAD)
        _rect(px, sx - 1, sy, 15, 1, CREAM)
        _rect(px, sx - 1, sy + 1, 15, 2, WARM if s % 2 == 0 else LIT)
        _rect(px, sx - 1, sy + 3, 15, 1, INK)
        if s % 3 == 1:
            _rect(px, sx + 5, sy, 2, 2, INK)


def _paint_angled_drum(px, cx, cy):
    """Fallen fluted classical stone column drum tilted in 3D perspective on the foreground seabed (like reference.jpg!)."""
    # Tilted elliptical cylinder body (angle ~ -28 deg)
    ca, sa = math.cos(-0.46), math.sin(-0.46)
    pts = {}
    for ly in range(-9, 10):
        for lx in range(-15, 16):
            # Elliptical end-caps at lx = -13 and lx = +13
            if lx < -10:
                d = ((lx + 10) / 5.0) ** 2 + (ly / 8.5) ** 2
                if d > 1.0:
                    continue
                kind = 'cap'
            elif lx > 10:
                d = ((lx - 10) / 5.0) ** 2 + (ly / 8.5) ** 2
                if d > 1.0:
                    continue
                kind = 'body'
            else:
                if abs(ly) > 8:
                    continue
                kind = 'body'
            rx = int(round(cx + lx * ca - ly * sa))
            ry = int(round(cy + lx * sa + ly * ca))
            if kind == 'cap':
                sh = 2 if ly > 1 else 3
            else:
                # Fluted ridges along cylinder length!
                flute = ((ly + 9) % 4)
                base = 4 if ly < -3 else 3 if ly < 1 else 2 if ly < 5 else 1
                sh = max(1, min(5, base + (1 if flute == 0 else -1 if flute == 2 else 0)))
            pts[(rx, ry)] = max(pts.get((rx, ry), 0), sh)
    for (ix, iy) in list(pts.keys()):
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if (ix + ox, iy + oy) not in pts:
                _put(px, ix + ox, iy + oy, INK)
    for (ix, iy), sh in pts.items():
        _put(px, ix, iy, STONE_RAMP[sh])


def _paint_amphora(px, x0, y0):
    """Half-buried ancient terracotta Greek amphora resting in the sunlit golden sand."""
    t_ink = INK
    t_dark = (88, 38, 26, 255)
    t_mid = (156, 72, 46, 255)
    t_lit = (212, 118, 74, 255)
    t_hi = (246, 174, 116, 255)
    cmap = {'.': None, 'k': t_ink, 'd': t_dark, 'm': t_mid, 'l': t_lit, 'h': t_hi}
    grid = [
        '.....kkkk.....',
        '....khlmmk....',
        '.....kmmk.....',
        '...kkhlmmkk...',
        '..kmkhlmmkmk..',
        '..kmkhllmkdk..',
        '...khhllmdk...',
        '..khhlllmmmk..',
        '.khhlllmmmddk.',
        '.khlllmmmdddk.',
        '.klllmmmddddk.',
        '..kmmmmddddk..',
        '...kkkkkkkk...',
    ]
    _paint_sprite_grid(px, x0, y0, grid, cmap)


def _paint_distant_citadel(px):
    """Pass-5 misty sunken Atlantis Acropolis: distant Greek temple pediment, colonnade, aqueduct arches & luminous depth glow!"""
    # Soft sunlit cyan-teal underwater depth glow peeking through the central archway
    for y in range(252, SAND_Y + 4):
        for x in range(134, 228):
            dx = (x - 179) / 38.0
            dy = (y - 318) / 50.0
            glow = math.exp(-(dx * dx + dy * dy))
            if glow > 0.14:
                r, g, b, a = px[x, y]
                if a == 0:
                    alpha = int(min(138, glow * 138))
                    px[x, y] = (34, 136, 158, alpha)
                else:
                    px[x, y] = (
                        min(255, int(r + glow * 14)),
                        min(255, int(g + glow * 34)),
                        min(255, int(b + glow * 36)),
                        a,
                    )
    c_far = (16, 78, 108, 255)
    c_far_hi = (42, 134, 152, 255)
    c_mid = (12, 62, 92, 255)
    c_mid_hi = (32, 108, 130, 255)

    # 1. Distant sunken Greek Parthenon / Atlantis Acropolis visible right through the central archway!
    # Triangular pediment roof (x = 162..196, y = 294..304)
    for dy in range(10):
        hw = 2 + int(dy * 1.7)
        _rect(px, 179 - hw, 294 + dy, hw * 2, 1, c_far_hi if dy < 2 else c_far)
    _rect(px, 161, 304, 36, 2, c_far_hi)
    # 5 slender misty acropolis temple columns + dark sanctuary gap behind them
    _rect(px, 164, 306, 30, 32, (11, 56, 86, 255))
    for col_x in (164, 171, 178, 185, 192):
        _rect(px, col_x, 306, 3, 32, c_far)
        _rect(px, col_x + 2, 306, 1, 32, c_far_hi)
    # Stepped acropolis stylobate foundation
    _rect(px, 159, 338, 40, 4, c_far_hi)
    _rect(px, 156, 342, 46, 5, c_far)

    # 2. Multi-arch sunken aqueduct receding into the deep blue left of the main archway!
    _rect(px, 106, 286, 56, 4, c_mid_hi)
    for ax in (110, 128, 146):
        _rect(px, ax, 290, 6, 56, c_mid)
        _rect(px, ax + 5, 290, 1, 56, c_mid_hi)
        # Small misty arch connecting piers
        for dx in range(12):
            arch_h = int(math.sin((dx / 11.0) * math.pi) * 6)
            _rect(px, ax + 6 + dx, 290, 1, max(1, 7 - arch_h), c_mid)
    # Distant tapered obelisk spire rising behind the aqueduct
    _rect(px, 124, 260, 5, 26, c_far)
    _rect(px, 125, 254, 3, 6, c_far_hi)
    _put(px, 126, 252, c_far_hi)

    # 3. Far-right misty sunken citadel tower & dome behind Poseidon parapet
    _rect(px, 206, 268, 14, 78, c_mid)
    _rect(px, 206, 268, 2, 78, c_mid_hi)
    for dy in range(-6, 1):
        hw = int(math.sqrt(max(0, 36 - dy * dy)))
        _rect(px, 213 - hw, 268 + dy, hw * 2, 1, c_mid_hi if dy < -3 else c_mid)


def _paint_seabed_details(bpx, fpx, rnd):
    """Pass-4 seabed storytelling: smooth organic pebbles, cast shadows, amphora, seashells, starfish & cinema fronds!"""
    # 1. Soft directional cast shadows onto the golden sand from left & right ruins + archway
    _darken(bpx, 56, 352, 54, 14, 0.60)
    _darken(bpx, 198, 352, 68, 14, 0.60)
    _darken(bpx, 136, 346, 94, 7, 0.74)

    # 2. Smooth, rounded organic underwater pebbles (warm sandstone/slate — NO harsh black rectangular bars!)
    pebbles = [
        (114, 378, 3, 2), (132, 366, 2, 1), (166, 372, 3, 2), (192, 368, 2, 1),
        (106, 396, 4, 2), (140, 400, 3, 1), (168, 404, 4, 2), (124, 414, 3, 2),
        (158, 418, 3, 2), (186, 384, 2, 1), (148, 358, 3, 1),
    ]
    for px0, py0, rx, ry in pebbles:
        _darken(bpx, px0 - rx + 1, py0 + 1, rx * 2, 2, 0.62)
        for dy in range(-ry, ry + 1):
            for dx in range(-rx, rx + 1):
                if (dx / (rx + 0.3)) ** 2 + (dy / (ry + 0.3)) ** 2 <= 1.0:
                    c = (158, 152, 118, 255) if dy < 0 else (98, 108, 96, 255) if dy == 0 else (48, 66, 68, 255)
                    _put(bpx, px0 + dx, py0 + dy, c)

    # 3. Half-buried ancient terracotta amphora resting near the left ruins
    _darken(bpx, 113, 372, 14, 4, 0.56)
    _paint_amphora(bpx, 114, 363)

    # 4. Crisp 16-bit starfish & spiral sea shell on the sunlit sand
    for sx, sy, c_dark, c_mid, c_hi in (
        (110, 404, (132, 32, 26, 255), (236, 86, 62, 255), (255, 194, 134, 255)),
        (174, 412, (138, 56, 20, 255), (246, 138, 54, 255), (255, 218, 138, 255)),
    ):
        _darken(bpx, sx - 5, sy + 2, 11, 2, 0.62)
        for a in range(5):
            rad = math.radians(a * 72 - 18)
            for r in range(6):
                ix, iy = int(round(sx + math.cos(rad) * r)), int(round(sy + math.sin(rad) * r * 0.62))
                _put(bpx, ix, iy + 1, c_dark)
                _put(bpx, ix, iy, c_mid if r > 1 else c_hi)
        _put(bpx, sx, sy, c_hi)
    # Tiny cream-pink scallop shell at (134, 418)
    _darken(bpx, 131, 420, 7, 2, 0.65)
    _rect(bpx, 132, 417, 5, 3, (238, 188, 174, 255))
    _rect(bpx, 133, 416, 3, 2, (255, 232, 218, 255))
    _put(bpx, 134, 419, (168, 102, 98, 255))

    # 5. Clusters of delicate sunlit seagrass blades sprouting from the golden sand
    for gx, gy in ((154, 396), (158, 398), (161, 395), (165, 397), (126, 382), (129, 384), (188, 378)):
        bh = 5 + (gx % 4)
        for i in range(bh):
            ox = int(math.sin(i * 0.5 + gx) * 0.8)
            _put(bpx, gx + ox, gy - i, (132, 178, 86, 255) if i > bh - 3 else (58, 108, 66, 255))

    # 6. Dramatic DARK SILHOUETTED foreground kelp / sea-fan blades along the very bottom edge (cinematic framing!)
    fg_blades = [
        (6, 427, 46, -0.25), (14, 427, 58, -0.10), (24, 427, 42, 0.14), (36, 427, 34, 0.28),
        (68, 427, 26, -0.22), (76, 427, 32, -0.05), (84, 427, 24, 0.22), (94, 427, 18, 0.32),
        (134, 427, 16, -0.24), (142, 427, 20, 0.08), (150, 427, 15, 0.28),
        (216, 427, 28, -0.26), (226, 427, 36, -0.06), (236, 427, 44, 0.12), (248, 427, 52, 0.24), (259, 427, 38, -0.12),
    ]
    for bx0, by0, bh, lean in fg_blades:
        for i in range(bh):
            frac = i / max(1, bh)
            x = int(round(bx0 + lean * i + math.sin(frac * 3.4 + bx0) * (1.8 + frac * 3.5)))
            y = by0 - i
            w = 3 if frac < 0.35 else 2 if frac < 0.72 else 1
            for dx in range(w):
                c = (5, 13, 21, 255) if (dx == 0 or frac < 0.25) else (16, 38, 44, 255) if frac < 0.7 else (36, 68, 62, 255)
                _put(fpx, x + dx, y, c)


def _paint_pass6_biodiversity(bpx, fpx, rnd):
    """Pass-6 lush reef storytelling: half-buried ship's helm wheel, spilled gold doubloons, gorgonian sea fans & crevice polyps!"""
    # 1. Half-buried weathered wooden & brass ship's helm wheel resting on the right sand beside the boulders!
    wx, wy, wr = 188, 376, 9
    _darken(bpx, wx - wr - 1, wy + 1, wr * 2 + 3, 4, 0.52)
    w_d, w_m, w_l, b_g = (58, 34, 22, 255), (112, 68, 40, 255), (168, 114, 68, 255), (236, 194, 78, 255)
    # Upper exposed arc of the ship's wheel (y <= wy + 1)
    for ang_deg in range(-175, 10, 8):
        rad = math.radians(ang_deg)
        for r in (wr - 2, wr - 1, wr):
            px0, py0 = int(round(wx + math.cos(rad) * r)), int(round(wy + math.sin(rad) * r * 0.85))
            if py0 <= wy + 1:
                _put(bpx, px0, py0, INK if r == wr else w_l if ang_deg < -60 else w_m)
    # Spokes & protruding wooden handles
    for ang_deg in (-165, -135, -105, -75, -45, -15):
        rad = math.radians(ang_deg)
        for r in range(2, wr + 4):
            px0, py0 = int(round(wx + math.cos(rad) * r)), int(round(wy + math.sin(rad) * r * 0.85))
            if py0 <= wy + 1:
                _put(bpx, px0, py0, w_l if r > wr else b_g if r < 4 else w_m if r % 2 == 0 else w_d)
    _rect(bpx, wx - 2, wy - 2, 5, 4, INK); _rect(bpx, wx - 1, wy - 1, 3, 2, b_g)

    # 2. Spilled gleaming antique gold doubloons & sparkling emerald/ruby gems scattered in the golden sand!
    treasures = [
        (134, 378, (248, 206, 56, 255), (255, 248, 172, 255)),
        (140, 384, (242, 194, 44, 255), (255, 244, 152, 255)),
        (158, 381, (248, 206, 56, 255), (255, 248, 172, 255)),
        (164, 377, (44, 242, 168, 255), (186, 255, 232, 255)),  # sunken emerald
        (148, 388, (255, 76, 142, 255), (255, 196, 224, 255)),  # sunken ruby
        (128, 390, (238, 192, 48, 255), (255, 242, 156, 255)),
        (170, 392, (242, 196, 52, 255), (255, 244, 162, 255)),
    ]
    for tx, ty, c_mid, c_hi in treasures:
        _darken(bpx, tx - 1, ty + 1, 4, 2, 0.56)
        _put(bpx, tx - 1, ty, INK); _put(bpx, tx + 2, ty, INK)
        _put(bpx, tx, ty, c_hi); _put(bpx, tx + 1, ty, c_mid)

    # 3. Delicate lacy Gorgonian Sea-Fans (filigree fan coral in crimson-gold & violet-coral!)
    fans = [
        (56, 62, 1.0, (132, 24, 52, 255), (232, 68, 96, 255), (255, 164, 158, 255)),
        (214, 272, 0.9, (124, 48, 16, 255), (238, 134, 42, 255), (255, 218, 118, 255)),
        (60, 390, 0.85, (72, 24, 108, 255), (176, 86, 228, 255), (236, 184, 255, 255)),
    ]
    for fx, fy, sc, c_d, c_m, c_h in fans:
        for b in range(7):
            ang = -math.pi * 0.85 + (b / 6.0) * math.pi * 0.72
            length = int((11 + (b % 3) * 3) * sc)
            for s in range(1, length):
                px0 = int(round(fx + math.cos(ang) * s))
                py0 = int(round(fy + math.sin(ang) * s))
                _put(fpx, px0, py0, c_h if s > length - 3 else c_m if s > 3 else c_d)
                # Delicate filigree cross-webbing between ribs!
                if s > 3 and s % 3 == 0:
                    _put(fpx, px0 + 1, py0, c_m if s > length // 2 else c_d)

    # 4. Colorful glowing tiny sea-anemone polyps & feather-duster worms tucked into rock crevices!
    polyps = [
        (24, 344, (255, 118, 204, 255), (255, 214, 242, 255)),
        (46, 368, (64, 238, 236, 255), (206, 255, 252, 255)),
        (238, 376, (255, 178, 68, 255), (255, 238, 162, 255)),
        (216, 396, (198, 118, 255, 255), (242, 210, 255, 255)),
        (16, 18, (255, 136, 198, 255), (255, 222, 242, 255)),
    ]
    for px0, py0, c1, c2 in polyps:
        for a in range(6):
            rad = a * (math.pi / 3.0)
            _put(fpx, px0 + math.cos(rad) * 2.4, py0 + math.sin(rad) * 1.8, c1)
        _put(fpx, px0, py0, c2)

    # 5. Delicate moss & trailing vine tendrils draping along the central distant Atlantis archway!
    for ax, ay, alen in ((152, 286, 12), (160, 268, 9), (194, 266, 11), (204, 286, 14)):
        for i in range(alen):
            _put(bpx, ax + (1 if i % 4 == 0 else 0), ay + i, (44, 122, 112, 255) if i < 4 else (24, 86, 98, 255))


def _paint_caustic_kiss(fpx):
    """Pass-4 sunlit turquoise-cream caustic dapples kissing the upper stone ledges & shipwreck planks nearest the surface!"""
    dapples = [
        (36, 26, 12), (52, 27, 10), (30, 92, 14), (48, 93, 12),
        (24, 126, 14), (44, 131, 10), (14, 194, 16), (40, 195, 18), (94, 195, 16),
        (214, 230, 14), (236, 231, 14),
    ]
    for x0, y0, length in dapples:
        for dx in range(length):
            if (dx * 7 + y0) % 3 == 0:
                continue
            x = x0 + dx
            if 0 <= x < W and 0 <= y0 < H and fpx[x, y0][3] > 0:
                r, g, b, a = fpx[x, y0]
                fpx[x, y0] = (min(255, r + 26), min(255, g + 34), min(255, b + 28), a)


def _paint_shipwreck_bow(px, rnd):
    """Rich, dark-outlined weathered galleon bow wedged harmoniously into the left sunken cliff alcove."""
    wood = [INK, (28, 22, 24, 255), (62, 44, 38, 255), (104, 74, 56, 255), (154, 118, 84, 255), (202, 168, 122, 255)]
    brass = [(56, 38, 16, 255), (146, 106, 36, 255), (236, 198, 98, 255), (255, 244, 186, 255)]
    # Curved hull polygon mask
    hull_poly = [(0, 126), (34, 125), (64, 133), (80, 143), (62, 166), (32, 175), (0, 178)]
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).polygon(hull_poly, fill=255)
    mpx = mask.load()
    # Cast dark shadow beneath hull onto masonry behind it
    _darken(px, 0, 174, 68, 10, 0.35)
    for y in range(124, 180):
        for x in range(0, 82):
            if not mpx[x, y]:
                continue
            is_edge = any(not (0 <= x + ox < W and 0 <= y + oy < H and mpx[x + ox, y + oy]) for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)))
            is_top = y > 0 and not mpx[x, y - 1]
            if is_edge and not is_top:
                px[x, y] = INK
                continue
            # Curved timber planking lines following the hull sheer
            sheer = y - int((x / 66.0) ** 2 * 9.0)
            plank_y = (sheer - 126) % 7
            plank_id = (sheer - 126) // 7
            if is_top:
                px[x, y] = wood[5]
            elif plank_y == 0:
                px[x, y] = INK
            elif plank_y == 1:
                px[x, y] = wood[4] if plank_id < 3 else wood[3]
            else:
                # Curved vertical hull shading (bright upper-right, deep dark underside)
                v = (y - 126) / 52.0
                grain = (_vnoise(x * 0.25, y * 0.65, 919 + plank_id) - 0.5) * 0.16
                val = _clamp(0.76 - v * 0.56 + (x / 82.0) * 0.16 + grain, 0.08, 0.92)
                px[x, y] = _dither_pick(wood[1:5], val, x, y, 0.32)
            # Subtle vertical plank butt joints with brass rivets
            if plank_y in (2, 3, 4) and (x + plank_id * 11) % 23 == 0:
                px[x, y] = wood[1]
    # Thick carved bow timber stem post on leading edge
    for s in range(30):
        t = s / 29.0
        bx = int(80 - t * 18)
        by = int(143 + t * 23)
        _rect(px, bx - 2, by, 4, 2, wood[4] if t < 0.5 else wood[2])
        _put(px, bx + 2, by, INK)
    # Angled broken bowsprit spar with sunlit top edge & ink underside
    for s in range(42):
        sx = 48 + s
        sy = 131 - int(s * 0.42)
        thick = 4 if s < 14 else 3 if s < 28 else 2
        _put(px, sx, sy - 1, INK)
        for dy in range(thick):
            _put(px, sx, sy + dy, wood[5] if dy == 0 else wood[3] if dy < thick - 1 else wood[1])
        _put(px, sx, sy + thick, INK)
        # Draped seaweed rigging
        if s in (15, 27, 37):
            for d in range(11 + (s % 6)):
                ox = int(math.sin(d * 0.45) * 1.3)
                _put(px, sx + ox, sy + thick + 1 + d, (112, 152, 74, 255) if d < 4 else (48, 92, 60, 255) if d < 9 else (18, 46, 42, 255))
    # Two crisp riveted brass portholes
    for cx, cy, r in ((21, 147, 6), (44, 151, 5)):
        for dy in range(-r - 1, r + 2):
            for dx in range(-r - 1, r + 2):
                d = math.hypot(dx, dy)
                if d <= r + 0.6:
                    if d > r - 0.5:
                        c = INK
                    elif d > r - 2.1:
                        c = brass[3] if (dy < -1 and dx > -2) else brass[2] if dy < 1 else brass[1]
                    elif d > r - 2.9:
                        c = brass[0]
                    else:
                        c = (5, 14, 24, 255) if (dx + dy) > -1 else (22, 68, 86, 255)
                    _put(px, cx + dx, cy + dy, c)
    # Rusted iron anchor chain hanging gracefully from the hawsepipe to the suspended iron anchor!
    for i in range(9):
        cx = 56 + int(math.sin(i * 0.4) * 1.4)
        cy = 158 + i * 2
        _put(px, cx - 1, cy, INK); _put(px, cx + 2, cy, INK)
        _put(px, cx, cy, (152, 138, 114, 255) if i % 2 == 0 else (72, 68, 66, 255))
        _put(px, cx + 1, cy + 1, (98, 88, 76, 255))
    # Pass-5/6: Carved golden-bronze figurehead scroll at bow prow + splintered deck railings + crisp suspended iron fluke anchor!
    for s in range(12):
        t = s / 11.0
        fx = int(round(78 - t * 9 + math.sin(t * math.pi) * 3))
        fy = int(round(138 + t * 13))
        _put(px, fx - 1, fy, INK); _put(px, fx + 2, fy, INK)
        _put(px, fx, fy, brass[3] if t < 0.45 else brass[2])
        _put(px, fx + 1, fy, brass[1])
    for rx, rh in ((6, 7), (16, 8), (27, 6), (38, 5)):
        _rect(px, rx - 1, 125 - rh, 4, rh, INK)
        _rect(px, rx, 125 - rh, 2, rh, wood[3])
        _put(px, rx, 125 - rh, wood[5])
    _rect(px, 2, 120, 38, 2, wood[4])
    _rect(px, 2, 122, 38, 1, INK)
    # Heavy rusted iron anchor dangling clearly below the bow prow (no coral overlap!)
    ax, ay = 58, 174
    ir_d, ir_m, ir_l = (36, 44, 52, 255), (86, 102, 108, 255), (164, 178, 170, 255)
    _rect(px, ax - 1, ay - 3, 4, 12, INK); _rect(px, ax, ay - 2, 2, 10, ir_m); _put(px, ax, ay - 2, ir_l)
    _rect(px, ax - 5, ay - 1, 12, 3, INK); _rect(px, ax - 4, ay, 10, 1, ir_l)
    for dx in range(-6, 7):
        fy = ay + 8 - int((dx * dx) * 0.14)
        _put(px, ax + dx, fy + 1, INK); _put(px, ax + dx, fy, ir_l if abs(dx) > 4 else ir_m if dx > 0 else ir_d)
    for bx, by in ((10, 162), (14, 165), (32, 166), (48, 160), (54, 146), (29, 138)):
        _put(px, bx, by, (214, 212, 188, 255)); _put(px, bx + 1, by, (142, 148, 134, 255))


def _paint_coral(px, cx, cy, kind, scale, rnd):
    """Pass-2 lush 16-bit coral colonies: lacy bifurcating staghorn, grooved brain domes, hollow tube sponges & table fans."""
    pals = {
        'pink':   [INK, (96, 16, 56, 255), (184, 34, 102, 255), (242, 92, 162, 255), (255, 192, 224, 255)],
        'orange': [INK, (108, 30, 12, 255), (198, 74, 22, 255), (248, 148, 48, 255), (255, 222, 124, 255)],
        'cyan':   [INK, (10, 62, 78, 255), (24, 134, 148, 255), (78, 218, 218, 255), (192, 255, 248, 255)],
        'violet': [INK, (52, 18, 86, 255), (118, 46, 174, 255), (188, 106, 238, 255), (236, 194, 255, 255)],
    }
    pal = pals[kind]

    # 1. Hollow cylindrical tube-sponge cluster (electric cyan)
    if kind == 'cyan' and rnd.random() < 0.62:
        tubes = 4 + rnd.randint(0, 2)
        order = sorted(range(tubes), key=lambda i: abs(i - (tubes - 1) / 2), reverse=True)
        for i in order:
            tx = cx + int((i - (tubes - 1) / 2) * 3.4 * scale) + rnd.randint(-1, 1)
            th = int((9 + rnd.randint(2, 11) - abs(i - tubes / 2) * 1.4) * scale)
            tw = max(3, int(3.2 * scale))
            hx = tw >> 1
            for dy in range(th + 1):
                y = cy - dy
                _put(px, tx - hx - 1, y, INK)
                _put(px, tx + hx + (tw % 2), y, INK)
                for dx in range(tw):
                    x = tx - hx + dx
                    if dy == th:
                        _put(px, x, y, pal[4] if (dx == 0 or dx == tw - 1) else INK)
                    elif dy == th - 1 and 0 < dx < tw - 1:
                        _put(px, x, y, pal[1])
                    else:
                        u = dx / max(1, tw - 1)
                        v = dy / max(1, th)
                        sh = 4 if (u > 0.72 and v > 0.45) else 3 if (u > 0.42 and v > 0.2) else 2 if v > 0.12 else 1
                        _put(px, x, y, pal[sh])
        return

    # 2. Sculpted labyrinth brain coral dome (tangerine/gold)
    if kind == 'orange' and rnd.random() < 0.45:
        rx, ry = max(5, int(8 * scale)), max(4, int(6 * scale))
        pts = set()
        for dy in range(-ry, 2):
            for dx in range(-rx, rx + 1):
                if (dx / rx) ** 2 + (dy / ry) ** 2 <= 1.0:
                    pts.add((cx + dx, cy + dy))
        for ix, iy in pts:
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                if (ix + ox, iy + oy) not in pts:
                    _put(px, ix + ox, iy + oy, INK)
        for ix, iy in pts:
            dx, dy = ix - cx, iy - cy
            groove = math.sin(dx * 0.95 + math.sin(dy * 0.85) * 1.6)
            lit = 0.52 - (dy / ry) * 0.34 + (dx / rx) * 0.18 + groove * 0.28
            sh = 4 if lit > 0.82 else 3 if lit > 0.56 else 2 if lit > 0.30 else 1
            _put(px, ix, iy, pal[sh])
        return

    # 3. Delicate organic bifurcating staghorn & reef coral (slender stems + forked sub-twigs + bright polyp tips!)
    pts = {}
    stems = 5 + rnd.randint(0, 3)

    def grow(x0, y0, ang, length, depth):
        bx, by = float(x0), float(y0)
        wiggle = (rnd.random() - 0.5) * 0.35
        for s in range(length):
            frac = s / max(1, length - 1)
            bx += math.cos(ang + math.sin(s * 0.45 + wiggle * 6) * 0.24)
            by += math.sin(ang)
            ix, iy = int(round(bx)), int(round(by))
            # Base slightly thicker (2px), upper forks delicate 1px with plump glowing tip buds!
            is_tip = s >= length - 2
            sh = 4 if is_tip else (3 if (frac > 0.48 or depth > 0) else 2 if frac > 0.2 else 1)
            pts[(ix, iy)] = max(pts.get((ix, iy), 0), sh)
            if depth == 0 and s < length * 0.45:
                pts[(ix + 1, iy)] = max(pts.get((ix + 1, iy), 0), max(1, sh - 1))
            if is_tip:
                pts[(ix, iy - 1)] = max(pts.get((ix, iy - 1), 0), 4)
            # Fork organic side-shoots
            if depth < 2 and s > 2 and s % 4 == 0 and rnd.random() < 0.78:
                side = -1 if ((s + depth) % 2 == 0) else 1
                sub_len = max(3, int((length - s) * 0.68))
                grow(bx, by, ang + side * (0.48 + rnd.random() * 0.22), sub_len, depth + 1)

    for b in range(stems):
        ang = -math.pi * 0.90 + (b / max(1, stems - 1)) * math.pi * 0.80 + (rnd.random() - 0.5) * 0.16
        length = max(6, int((9 + rnd.randint(0, 8)) * scale))
        grow(cx + (b - stems / 2) * 1.6, cy, ang, length, 0)

    # Dark base shadow outline only below/behind so branches look crisp yet airy (never chunky cartoon mittens!)
    for (ix, iy) in list(pts.keys()):
        for ox, oy in ((0, 1), (-1, 1), (-1, 0)):
            if (ix + ox, iy + oy) not in pts:
                _put(px, ix + ox, iy + oy, INK)
    for (ix, iy), sh in pts.items():
        _put(px, ix, iy, pal[sh])


def _paint_sprite_grid(px, x0, y0, grid, cmap):
    """Paint a hand-pixelled ASCII sprite grid cleanly onto an RGBA pixel buffer."""
    for dy, row in enumerate(grid):
        for dx, ch in enumerate(row):
            col = cmap.get(ch)
            if col is not None:
                _put(px, x0 + dx, y0 + dy, col)


def _paint_statue(px, x, y, pose):
    """Pass-2 hand-pixelled 16-bit classical Atlantis sculptures with draped folds, anatomy & sunlit rim."""
    cmap = {'.': None, 'k': INK, 'd': DEEP, 's': SHAD, 'm': MID, 'l': LIT, 'w': WARM, 'c': CREAM}
    if pose == 'seated':
        # Iconic seated classical philosopher/hero perched on the left temple cornice (24 x 36 px)
        grid = [
            '........kkkk............',
            '.......kccwwk...........',
            '......kcwwmlwk..........',
            '......kwmllmck..........',
            '......ksmsllck..........',
            '.......ksmmmk...........',
            '.......kksskk...........',
            '.....kkkmlwwkk..........',
            '....ksmllwwwcck.........',
            '...kdmmllwwllwck........',
            '...kdsmmllwwmllk........',
            '..kddssmmllwmmwck.......',
            '..kddsmmsllsmmlwck......',
            '..kddsmmsslsmsllwck.....',
            '..kddsmmsllsmsmllwck....',
            '..kdddmmlllsmsmmlwwk....',
            '...kddsmllssmslmmllk....',
            '...kddssmlssssmmlkkk....',
            '..kkddssmllllwwwwckk....',
            '.kmmlkddssllwwwwwwcck...',
            '.kmllkddssmmmllllwcck...',
            '.ksmmkdddssssmmmllwck...',
            '.ksddkddddssssmmllwck...',
            '.ksddkkkkkkkkkkmllwck...',
            '.ksdsmmllllmmkkmlwwck...',
            '.ksdsmlwwllmmkkmlwwck...',
            '.ksdsmllmlmmmkkmlwwk....',
            '.ksdsmmmlmmmmkkmlwwk....',
            '.ksdssssssssskkmlwwk....',
            '.kdddddddddddkkmlwck....',
            '.kdddddddddddkkmlwck....',
            '.kdddddddddddkkmllwk....',
            '.kdddddddddddkksmlwck...',
            'ksssssssssssskksllwwwk..',
            'kddddddddddddkkssssssk..',
            'kkkkkkkkkkkkkkkkkkkkkk..',
        ]
        _paint_sprite_grid(px, x - 3, y - 3, grid, cmap)
    else:
        # Standing Poseidon guardian with classical draped chiton & ornate carved trident (22 x 44 px)
        grid = [
            '............k..kk..k..',
            '............kc.kck.kc.',
            '............kc.kck.kc.',
            '............kc.kck.kc.',
            '............kcckwccck.',
            '......kkkk..kkccwwckk.',
            '.....kcwwwk...kkwck...',
            '....kcwwmlwk...kwk....',
            '....kcwllmms...kwk....',
            '....kcllsmmk...kwk....',
            '.....ksmmmk....kwk....',
            '....kkssmmkk...kwk....',
            '...kcwwlmmsskk.kwk....',
            '..kcwwllmmmsllkkwk....',
            '..kcwllmmmsllwccwk....',
            '..kcwlmmssmllwwmwk....',
            '..kwllmsmmmsllwkwk....',
            '..kwlmssmllmsmmkwk....',
            '..kwlmmsmlmmssskwk....',
            '..kwlmmsllmmmsdkwk....',
            '..kclmmsllmmsddkwk....',
            '..kwlmmsllmmssdkwk....',
            '..kcllmllmmssddkwk....',
            '..kwllmlllmmssdkwk....',
            '..kwllmsllmmsddkwk....',
            '..kwllmsllmmsddkwk....',
            '..kclmmsllmmsddkwk....',
            '..kwlmmsllmmsddkwk....',
            '..kwllmsllmmsddkwk....',
            '..kclmmsllmmsddkwk....',
            '..kwlmmsllmmsddkwk....',
            '..kwllmsllmmsddkwk....',
            '..kclmmsllmmsddkwk....',
            '..kwlmmsllmmsddkwk....',
            '..kwllmsllmmsddkwk....',
            '..kwlmmsllmmsddkwk....',
            '..ksllmsllmmsddkwk....',
            '.kksssdsllmmssdkwk....',
            '.kwwlllsssdddddkwk....',
            '.kmmmmssssdddddkwk....',
            '.kkkkkkkkkkkkkkkkk....',
        ]
        _paint_sprite_grid(px, x + 2, y - 6, grid, cmap)


def _paint_moss(px, x0, x1, y, rnd, max_len=20):
    """Rich draped olive-gold & emerald underwater moss hanging naturally from temple cornices."""
    for x in range(x0, x1, 2):
        if rnd.random() > 0.66:
            continue
        length = 6 + rnd.randint(0, max_len)
        for i in range(length):
            if i < 2:
                c = (176, 206, 98, 255)
            elif i < length * 0.45:
                c = (118, 158, 72, 255)
            elif i < length * 0.78:
                c = (54, 102, 64, 255)
            else:
                c = (18, 48, 46, 255)
            ox = int(math.sin(i * 0.35 + x) * 0.8)
            _put(px, x + ox, y + i, c)
            if i < length * 0.35:
                _put(px, x + ox + 1, y + i, (68, 114, 66, 255))


def _paint_tower_tier(px, x0, y0, w, h, seed, right_sun=True, overhang=True, taper=0):
    """Build one sculpted, crumbling ancient Atlantis masonry tier with deep left shadow, irregular stepped edges & cracks."""
    row_h = 8
    y = y0
    row = 0
    while y < y0 + h:
        rh = min(row_h + (row % 2) * 2, y0 + h - y)
        frac = (y - y0) / max(1, h)
        # Crumbling organic stepped outer silhouette (NOT a flat vertical brick wall!)
        jitter = int(math.sin(row * 1.9 + seed) * 3.5) + (4 if (overhang and row == 0) else 0)
        edge_w = max(14, int(w + taper * frac + jitter))
        _rect(px, x0, y, edge_w, rh, INK)
        bx = x0 - ((row % 2) * 6)
        while bx < x0 + edge_w:
            bw = 10 + ((bx * 17 + row * 11 + seed) % 10)
            sx = max(x0, bx)
            sw = min(bx + bw, x0 + edge_w) - sx
            if sw >= 4:
                x_frac = (sx + sw * 0.5 - x0) / max(1, edge_w)
                # Dramatic 3D chiaroscuro: deep marine shadow on far left, warm sunlit stone on right cliff face!
                bias = -0.52 + (x_frac ** 1.25) * 0.78 - (0.18 if row > 0 and overhang and y - y0 < row_h + 7 else 0.0)
                _paint_block(px, sx, y, sw, rh, shade_bias=bias, top_sun=(row == 0 or (x_frac > 0.35 and sw > 7)), right_sun=right_sun, seed=seed + row * 31 + sx)
            bx += bw
        y += rh
        row += 1
    # Deep irregular diagonal weathering crack across the tier
    cx = x0 + int(w * 0.48)
    for dy in range(min(h - 4, 24)):
        kx = cx + int(dy * 0.35 + math.sin(dy * 0.7 + seed) * 1.5)
        _put(px, kx, y0 + 6 + dy, INK)
        _put(px, kx + 1, y0 + 6 + dy, DEEP)
    if overhang:
        _darken(px, x0, y0 + h, w + 8, 7, 0.32)


def _paint_sanctuary_recess(px, x0, y0, w, h, seed):
    """Pass-5 deep shadowed temple gallery: receding interior stone archways, dim inner columns & mysterious Atlantean carving!"""
    _rect(px, x0, y0, w, h, (5, 12, 22, 255))
    # Craggy shadow rock + subtle receding masonry courses inside the temple hall
    for y in range(y0, y0 + h):
        for x in range(x0, min(W, x0 + w)):
            n = _fbm(x * 0.08, y * 0.08, seed, 2)
            if n > 0.58:
                px[x, y] = (10, 23, 36, 255) if n < 0.72 else (17, 36, 52, 255)
            elif (y - y0) % 12 == 0 and n > 0.28:
                px[x, y] = (9, 20, 34, 255)
    # Dim inner recessed temple archway & twin shadow pillars inside the left gallery (gives HUGE architectural depth!)
    if w > 70:
        ax, ay, ar = x0 + 68, y0 + 52, 16
        for dy in range(-ar - 4, 48):
            for dx in range(-ar - 5, ar + 6):
                d = math.hypot(dx, dy)
                if dy <= 0:
                    if ar <= d <= ar + 4:
                        _put(px, ax + dx, ay + dy, (22, 46, 60, 255) if d > ar + 2 else (13, 28, 42, 255))
                elif abs(dx) >= ar and abs(dx) <= ar + 4:
                    _put(px, ax + dx, ay + dy, (18, 38, 52, 255) if dx > 0 else (12, 26, 40, 255))
        # Subtle ancient glowing turquoise Atlantean glyph carved on the shadowed inner wall!
        gx, gy = ax, ay + 14
        for ox, oy in ((0, -5), (-2, -3), (2, -3), (-3, 0), (3, 0), (0, 0), (-2, 3), (2, 3), (0, 5)):
            _put(px, gx + ox, gy + oy, (26, 98, 114, 255))
        _put(px, gx, gy, (64, 178, 188, 255))
    else:
        # Mysterious faint golden trident glint inside the dark right Poseidon vault (teases hidden treasure!)
        gx, gy = x0 + 36, y0 + 46
        for ox, oy in ((0, -4), (0, -2), (0, 0), (-3, -3), (3, -3)):
            _put(px, gx + ox, gy + oy, (42, 68, 76, 255))
        _put(px, gx, gy - 4, (112, 134, 92, 255))


def _paint_sanctuary_lit_left():
    """Hand-crafted 16-bit illuminated LEFT ATLANTIS SANCTUARY interior (`101 x 134`, placed at `0, 212`).

    Stops cleanly behind the right fluted Ionic column (x=86..103) so light NEVER bleeds past the exterior facade!
    Reveals a warm golden-turquoise vaulted temple hall: carved stone arches, Atlantean Sun-Compass & Trident murals,
    marble relic pedestal, golden amphorae & glowing cave crystals!
    """
    rw, rh = 101, 134
    img = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    px = img.load()

    def put(x, y, c):
        if 0 <= x < rw and 0 <= y < rh:
            px[x, y] = c

    def rect(x, y, w, h, c):
        for yy in range(max(0, y), min(rh, y + h)):
            for xx in range(max(0, x), min(rw, x + w)):
                px[xx, yy] = c

    # 1. Warm whole-room volumetric underwater glow across carved ashlar masonry back wall!
    wall_ramp = [
        (16, 46, 68, 255),
        (26, 72, 92, 255),
        (42, 104, 116, 255),
        (74, 140, 136, 255),
        (124, 174, 146, 255),
        (184, 206, 158, 255),
        (232, 232, 182, 255),
    ]
    for y in range(rh):
        for x in range(rw):
            # Whole-room illumination centered in the sanctuary arch (68, 62) + secondary bounce in left gallery (22, 54)!
            d1 = math.hypot((x - 68) / 56.0, (y - 62) / 68.0)
            d2 = math.hypot((x - 20) / 38.0, (y - 54) / 52.0)
            glow = max(math.exp(-d1 * d1 * 1.15), 0.78 * math.exp(-d2 * d2 * 1.25))
            ceil_ao = _clamp(y / 14.0, 0.35, 1.0)
            n = (_fbm(x * 0.14, y * 0.14, 912, 2) - 0.5) * 0.16
            # Recessed ashlar stone courses & vertical joints
            mortar = (y % 11 == 0) or (((x + (y // 11) * 7) % 16) == 0)
            val = _clamp((0.18 + glow * 0.72 + n) * ceil_ao - (0.24 if mortar else 0.0), 0.04, 0.96)
            px[x, y] = _dither_pick(wall_ramp, val, x, y, 0.36)

    # 2. Lit inner recessed temple archway framing the Atlantean Relic Altar (right in the window x=53..86!)
    ax, ay, ar = 68, 50, 16
    # Deep warm golden-teal sanctuary niche inside the arch
    for y in range(ay - ar, 122):
        for x in range(ax - ar, ax + ar + 1):
            if y < ay and math.hypot(x - ax, y - ay) > ar:
                continue
            dn = math.hypot((x - ax) / 17.0, (y - 64) / 34.0)
            nv = _clamp(0.42 + (1.0 - dn) * 0.50, 0.16, 0.94)
            put(x, y, _dither_pick([(18, 56, 78, 255), (30, 88, 108, 255), (56, 138, 148, 255), (108, 192, 184, 255), (178, 232, 204, 255)], nv, x, y, 0.34))
    # Carved warm-lit stone arch ring & inner pilasters
    for dy in range(-ar - 5, 72):
        for dx in range(-ar - 5, ar + 6):
            d = math.hypot(dx, dy)
            if dy <= 0:
                if ar <= d <= ar + 4.6:
                    c = (232, 224, 174, 255) if d < ar + 1.4 else (164, 176, 142, 255) if d < ar + 3.2 else (64, 94, 98, 255)
                    put(ax + dx, ay + dy, c)
            elif ar <= abs(dx) <= ar + 4:
                inner = abs(dx) < ar + 1.5
                c = (212, 208, 162, 255) if inner else (128, 150, 132, 255) if abs(dx) < ar + 3 else (52, 82, 90, 255)
                put(ax + dx, ay + dy, c)

    # 3. Carved Golden Atlantean Sun-Mosaic & Trident Relief on the upper niche wall (x=58..78, y=38..56)
    g_hi, g_mid, g_dk = (255, 246, 172, 255), (236, 186, 62, 255), (156, 104, 34, 255)
    t_hi, t_mid = (146, 254, 246, 255), (52, 206, 206, 255)
    # Sunburst disc behind trident
    for dy in range(-7, 8):
        for dx in range(-7, 8):
            d = math.hypot(dx, dy)
            if 4.2 <= d <= 6.8:
                put(ax + dx, 47 + dy, g_mid if dy >= 0 else g_hi)
            elif d < 4.2:
                put(ax + dx, 47 + dy, t_mid if d > 2.2 else t_hi)
    # Golden carved trident emblem inside sunburst
    rect(ax - 1, 41, 2, 13, g_hi)
    rect(ax - 5, 43, 2, 5, g_hi); rect(ax + 4, 43, 2, 5, g_hi)
    rect(ax - 4, 47, 9, 2, g_mid)
    # Flanking glowing turquoise wall rune columns
    for ry in (58, 66, 74):
        rect(ax - 11, ry, 3, 2, t_hi); put(ax - 10, ry + 2, t_mid)
        rect(ax + 9, ry, 3, 2, t_hi); put(ax + 10, ry + 2, t_mid)

    # 4. Ornate Carved Marble Relic Pedestal Altar (x=60..76, y=76..118) — holds the live floating Crystal Orb!
    rect(ax - 8, 76, 17, 3, (238, 232, 188, 255))
    rect(ax - 7, 79, 15, 2, (168, 174, 142, 255))
    rect(ax - 5, 81, 11, 24, (124, 144, 128, 255))
    rect(ax - 4, 81, 3, 24, (196, 202, 166, 255))
    rect(ax - 2, 85, 5, 14, (56, 92, 98, 255))
    rect(ax - 1, 87, 3, 10, t_mid); put(ax, 91, t_hi)
    rect(ax - 9, 105, 19, 4, (196, 200, 160, 255))
    rect(ax - 10, 109, 21, 5, (118, 138, 124, 255))
    # Golden chalice & gleaming amphora resting beside the pedestal!
    rect(ax - 14, 104, 4, 5, g_mid); rect(ax - 14, 103, 4, 1, g_hi); rect(ax - 13, 109, 2, 3, g_dk)
    rect(ax + 11, 103, 5, 8, (186, 94, 54, 255)); rect(ax + 12, 101, 3, 2, (236, 148, 94, 255))
    rect(ax + 12, 104, 2, 4, (242, 168, 108, 255))

    # 5. LEFT GALLERY WINDOW (x=4..35, y=12..88): Ancient Carved Atlantean Compass-Sun Mosaic + Glowing Cave Crystals!
    rect(6, 18, 26, 38, (46, 82, 94, 255))
    rect(7, 19, 24, 36, (68, 110, 118, 255))
    rect(8, 20, 22, 2, (226, 220, 172, 255))
    rect(8, 52, 22, 2, (168, 174, 140, 255))
    # Ornate carved golden Atlantean compass-wheel & sunlit ocean waves inside tablet!
    mcx, mcy = 19, 36
    for dy in range(-8, 9):
        for dx in range(-8, 9):
            d = math.hypot(dx, dy)
            if 5.8 <= d <= 7.8:
                put(mcx + dx, mcy + dy, g_hi if dy < 0 else g_mid)
            elif 3.0 <= d <= 4.2:
                put(mcx + dx, mcy + dy, t_mid)
    for d in (-6, -5, -4, 4, 5, 6):
        put(mcx + d, mcy, g_hi); put(mcx, mcy + d, g_hi)
    rect(mcx - 1, mcy - 1, 3, 3, t_hi); put(mcx, mcy, (255, 255, 255, 255))
    for dx in range(-9, 10):
        yy = 48 + int(round(math.sin(dx * 0.7) * 1.4))
        put(mcx + dx, yy, t_hi if dx % 2 == 0 else t_mid)
    # Glowing turquoise & amethyst cave crystal cluster sprouting from stone alcove (x=8..32, y=60..84)
    crystals = [
        (12, 82, 18, 4, (64, 226, 228, 255), (186, 255, 254, 255)),
        (18, 84, 22, 5, (158, 114, 248, 255), (234, 212, 255, 255)),
        (25, 82, 15, 4, (56, 214, 212, 255), (178, 255, 250, 255)),
        (8,  83, 12, 3, (124, 92, 224, 255), (214, 192, 255, 255)),
    ]
    for cx0, by0, ch, cw, cmid, chi in crystals:
        for i in range(ch):
            frac = i / max(1, ch)
            w_now = max(1, int(round(cw * (1.0 - max(0.0, frac - 0.55) * 1.9))))
            for dx in range(w_now):
                put(cx0 + dx - (w_now >> 1), by0 - i, chi if (dx == 0 or frac > 0.72) else cmid)
    # Stone sanctuary floor glow
    for y in range(114, rh):
        for x in range(rw):
            val = _clamp(0.45 + (1.0 - abs(x - 64) / 60.0) * 0.42, 0.2, 0.9)
            put(x, y, _dither_pick(wall_ramp[1:6], val, x, y, 0.4))
    return img


def _paint_sanctuary_lit_right():
    """Hand-crafted 16-bit illuminated RIGHT POSEIDON VAULT interior (`45 x 98`, placed at `222, 244`).

    Starts cleanly behind the right fluted column (x=220..236) so glow NEVER bleeds outside the left edge of the column!
    Reveals a warm amber-gold & emerald sunken treasury: vaulted stone arch, glowing Poseidon rune tablet,
    golden crown & jeweled trident shrine, crystal geodes & ancient gold coin mound!
    """
    rw, rh = 45, 98
    img = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    px = img.load()

    def put(x, y, c):
        if 0 <= x < rw and 0 <= y < rh:
            px[x, y] = c

    def rect(x, y, w, h, c):
        for yy in range(max(0, y), min(rh, y + h)):
            for xx in range(max(0, x), min(rw, x + w)):
                px[xx, yy] = c

    # 1. Warm amber-emerald vaulted treasury illumination across back stone wall!
    vault_ramp = [
        (16, 44, 62, 255),
        (28, 68, 82, 255),
        (48, 98, 100, 255),
        (86, 134, 114, 255),
        (144, 168, 124, 255),
        (206, 200, 140, 255),
        (246, 234, 174, 255),
    ]
    for y in range(rh):
        for x in range(rw):
            d = math.hypot((x - 29) / 26.0, (y - 46) / 48.0)
            glow = math.exp(-d * d * 1.1)
            ceil_ao = _clamp(y / 12.0, 0.35, 1.0)
            mortar = (y % 10 == 0) or (((x + (y // 10) * 5) % 14) == 0)
            n = (_fbm(x * 0.16, y * 0.16, 977, 2) - 0.5) * 0.16
            val = _clamp((0.20 + glow * 0.72 + n) * ceil_ao - (0.24 if mortar else 0.0), 0.05, 0.96)
            px[x, y] = _dither_pick(vault_ramp, val, x, y, 0.36)

    # 2. Arched inner treasury alcove (world x=238..264 -> local x=16..42, right behind column x=220..236!)
    ax, ay, ar = 29, 24, 12
    for y in range(ay - ar, 88):
        for x in range(ax - ar, min(rw, ax + ar + 1)):
            if y < ay and math.hypot(x - ax, y - ay) > ar:
                continue
            dn = math.hypot((x - ax) / 14.0, (y - 46) / 34.0)
            nv = _clamp(0.45 + (1.0 - dn) * 0.48, 0.18, 0.94)
            put(x, y, _dither_pick([(20, 56, 70, 255), (36, 92, 98, 255), (68, 142, 130, 255), (132, 194, 152, 255), (218, 234, 176, 255)], nv, x, y, 0.35))
    for dy in range(-ar - 3, 64):
        for dx in range(-ar - 3, ar + 4):
            d = math.hypot(dx, dy)
            if dy <= 0 and ar <= d <= ar + 3.2:
                put(ax + dx, ay + dy, (238, 224, 166, 255) if d < ar + 1.4 else (136, 154, 124, 255))
            elif dy > 0 and ar <= abs(dx) <= ar + 3:
                put(ax + dx, ay + dy, (214, 204, 152, 255) if abs(dx) < ar + 1.4 else (112, 134, 114, 255))

    # 3. Glowing Emerald-Gold Poseidon Rune Tablet (y=18..34)
    g_hi, g_mid, g_dk = (255, 248, 174, 255), (242, 192, 54, 255), (162, 108, 28, 255)
    e_hi, e_mid = (156, 255, 214, 255), (46, 214, 152, 255)
    rect(ax - 7, 18, 15, 16, (44, 78, 80, 255))
    rect(ax - 6, 19, 13, 14, (72, 112, 104, 255))
    # Glowing emerald Atlantean glyphs
    rect(ax - 4, 21, 9, 1, e_hi); rect(ax - 4, 24, 4, 1, e_mid); rect(ax + 1, 24, 4, 1, e_hi)
    rect(ax - 3, 27, 7, 1, e_hi); rect(ax - 1, 21, 2, 10, e_hi)

    # 4. Sunken Golden Crown & Jeweled Trident Shrine on carved plinth (y=38..68)
    # Upright gleaming golden trident behind crown
    rect(ax - 1, 37, 2, 24, g_hi)
    rect(ax - 5, 39, 2, 7, g_hi); rect(ax + 4, 39, 2, 7, g_hi)
    rect(ax - 4, 45, 9, 2, g_mid); put(ax, 36, e_hi)
    # Jeweled Golden Crown resting on stone shrine slab
    rect(ax - 6, 54, 13, 5, g_mid); rect(ax - 6, 54, 13, 1, g_hi)
    rect(ax - 6, 51, 2, 3, g_hi); rect(ax - 1, 50, 3, 4, g_hi); rect(ax + 5, 51, 2, 3, g_hi)
    put(ax, 56, e_hi); put(ax - 4, 56, (255, 86, 146, 255)); put(ax + 4, 56, (255, 86, 146, 255))
    # Carved stone altar slab
    rect(ax - 9, 59, 19, 4, (222, 216, 168, 255))
    rect(ax - 8, 63, 17, 10, (112, 136, 118, 255))
    # Dark cozy moray-eel crevice nestled under the altar arch (x=31..43, y=65..74)
    rect(ax - 4, 65, 10, 9, (12, 28, 42, 255))
    rect(ax - 3, 66, 8, 7, (6, 16, 26, 255))

    # 5. Sparkling Emerald Crystal Geodes & Ancient Gold Coin Mound at floor (y=74..94)
    for gx, gy, gh in ((18, 86, 10), (22, 88, 13), (38, 86, 11)):
        for i in range(gh):
            w_now = max(1, 3 - i // 4)
            rect(gx, gy - i, w_now, 1, e_hi if i > gh - 4 else e_mid)
    for cx0, cy0 in ((26, 82), (29, 81), (32, 82), (28, 84), (31, 84), (34, 84), (25, 85), (30, 86)):
        rect(cx0, cy0, 3, 2, g_mid); put(cx0, cy0, g_hi)
    return img


def _paint_frieze_and_urns(fpx):
    """Pass-5 Greek wave-scroll meander frieze on temple cornices + classical marble urn & weathered relief details!"""
    # Carved Greek key / meander relief along the left & right temple entablature architraves
    for x in range(6, 110, 8):
        _rect(fpx, x, 205, 5, 1, CREAM)
        _put(fpx, x + 4, 206, WARM); _put(fpx, x + 2, 206, WARM)
        _rect(fpx, x + 2, 207, 3, 1, LIT)
    for x in range(214, 262, 8):
        _rect(fpx, x, 241, 5, 1, WARM)
        _put(fpx, x, 242, LIT); _put(fpx, x + 2, 242, LIT)
        _rect(fpx, x, 243, 3, 1, MID)
    # Ornate classical marble urn perched beside the left cornice corals
    u_cmap = {'.': None, 'k': INK, 'd': SHAD, 'm': MID, 'l': LIT, 'w': WARM, 'c': CREAM}
    urn = [
        '..kkkkkk..',
        '.kcwwmlmk.',
        '..kkmmkk..',
        '.kkcwmwkk.',
        'kmkclmwkdk',
        '.kcllmmdk.',
        '.kclmmddk.',
        '..kmmddk..',
        '..kkddkk..',
        '.kwmmmddk.',
        '.kkkkkkkk.',
    ]
    _paint_sprite_grid(fpx, 60, 184, urn, u_cmap)


def build_plates():
    """Build Pass-1 `bg` (atmospheric canyon + coffered Atlantis arch + golden seabed) & `fg` (tiered masonry ruins)."""
    bg = Image.new('RGBA', VIEW, (0, 0, 0, 0))
    fg = Image.new('RGBA', VIEW, (0, 0, 0, 0))
    bpx, fpx = bg.load(), fg.load()
    rnd = random.Random(20261124)

    # ===== 1. BACKGROUND PLATE: 3-layer atmospheric canyon ridges, coffered Atlantis arch & sunlit seabed =====
    # Far misty canyon silhouettes (soft deep marine teal-blue, 2 layers for depth)
    far_poly = [
        (0, 212), (38, 224), (82, 266), (118, 288), (144, 314), (168, 304),
        (206, 268), (242, 232), (W - 1, 218), (W - 1, SAND_Y + 6), (0, SAND_Y + 6),
    ]
    mask_far = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask_far).polygon(far_poly, fill=255)
    mfar = mask_far.load()
    for y in range(210, SAND_Y + 6):
        vf = (y - 210) / max(1, SAND_Y - 210)
        for x in range(W):
            if mfar[x, y]:
                top = y > 0 and not mfar[x, y - 1]
                col = (26, 98, 126, 255) if top else _blend_rgb((15, 68, 98), (11, 52, 82), vf)
                bpx[x, y] = col

    # Distant misty sunken Atlantis citadel spires & broken sentinel pillar behind the archway!
    _paint_distant_citadel(bpx)

    # Mid-distant kelp forest silhouettes with curved leaf blades swaying behind the sunken archway
    for kx, kh, kw in ((116, 92, 3), (128, 76, 2), (140, 60, 2), (202, 104, 3), (214, 82, 2)):
        for i in range(kh):
            frac = i / max(1, kh)
            sx = kx + int(math.sin(i * 0.09 + kx * 0.2) * (2.8 + frac * 4.0))
            c0 = (10, 52, 78, 255)
            c1 = (20, 82, 108, 255)
            w_cur = max(1, int(kw * (1.0 - frac * 0.55)))
            for dx in range(w_cur):
                _put(bpx, sx + dx, SAND_Y + 2 - i, c1 if dx == w_cur - 1 else c0)
            # Subtle curved kelp leaf fronds every 11px
            if i > 10 and i % 11 == 0 and frac < 0.88:
                side = -1 if ((i // 11) % 2 == 0) else 1
                for lf in range(1, 5):
                    _put(bpx, sx + side * lf, SAND_Y + 2 - i - (lf >> 1), c1 if lf < 3 else c0)

    # Iconic sunken Atlantis triumphal archway with COFFERED PILASTERS & radiating carved voussoirs!
    cx, base_y, arch_r, arch_y = 179, SAND_Y + 2, 22, 286
    a_ink  = (9, 44, 68, 255)
    a_dark = (16, 66, 92, 255)
    a_mid  = (32, 98, 120, 255)
    a_lit  = (62, 138, 148, 255)
    a_rim  = (112, 182, 178, 255)
    for side in (-1, 1):
        px0 = cx - arch_r - 13 if side < 0 else cx + arch_r + 1
        # Pilaster shaft with crisp edge lighting
        _rect(bpx, px0, arch_y, 12, base_y - arch_y, a_mid)
        _rect(bpx, px0, arch_y, 1, base_y - arch_y, a_ink)
        _rect(bpx, px0 + 11, arch_y, 1, base_y - arch_y, a_ink)
        _rect(bpx, px0 + (1 if side < 0 else 9), arch_y, 2, base_y - arch_y, a_lit)
        _rect(bpx, px0 + (9 if side < 0 else 1), arch_y, 2, base_y - arch_y, a_dark)
        # Carved recessed coffered X-panels inside the pilasters (signature detail from reference.jpg!)
        for py in range(arch_y + 8, base_y - 12, 16):
            _rect(bpx, px0 + 3, py, 6, 12, a_dark)
            _rect(bpx, px0 + 4, py + 1, 4, 10, a_mid)
            for k in range(5):
                _put(bpx, px0 + 4 + (k * 3) // 4, py + 2 + k * 2, a_dark)
                _put(px=bpx, x=px0 + 7 - (k * 3) // 4, y=py + 2 + k * 2, col=a_dark)
        # Molded pilaster capital & stepped plinth
        _rect(bpx, px0 - 3, arch_y - 5, 18, 5, a_lit)
        _rect(bpx, px0 - 3, arch_y - 5, 18, 1, a_rim)
        _rect(bpx, px0 - 3, arch_y - 1, 18, 1, a_ink)
        _rect(bpx, px0 - 3, base_y - 8, 18, 8, a_mid)
        _rect(bpx, px0 - 3, base_y - 8, 18, 1, a_rim)
        _rect(bpx, px0 - 4, base_y - 4, 20, 4, a_dark)
        _rect(bpx, px0 - 4, base_y - 4, 20, 1, a_lit)
    # Semicircular radiating carved stone arch ring
    for y in range(arch_y - arch_r - 12, arch_y + 1):
        for x in range(cx - arch_r - 12, cx + arch_r + 13):
            d = math.hypot(x - cx, y - arch_y)
            if arch_r - 1 <= d <= arch_r + 10:
                if d < arch_r + 0.5 or d > arch_r + 9.2:
                    c = a_ink
                elif d < arch_r + 2.2:
                    c = a_dark
                elif d > arch_r + 7.4:
                    c = a_rim if y < arch_y - 10 else a_lit
                else:
                    c = a_lit if (y < arch_y - arch_r - 2 or x < cx) else a_mid
                _put(bpx, x, y, c)
    # Crisp radiating voussoir block joints
    for ang in range(-78, 79, 19):
        rad = math.radians(ang)
        for r in range(arch_r, arch_r + 10):
            _put(bpx, cx + math.sin(rad) * r, arch_y - math.cos(rad) * r, a_ink)
    # Ornate carved keystone at crown of arch
    _rect(bpx, cx - 4, arch_y - arch_r - 12, 9, 12, a_ink)
    _rect(bpx, cx - 3, arch_y - arch_r - 11, 7, 10, a_lit)
    _rect(bpx, cx - 3, arch_y - arch_r - 11, 7, 2, a_rim)
    # Weathered ancient stone steps descending right of the archway + fallen carved block in center-left
    for k in range(6):
        _rect(bpx, cx + 12 - k * 3, base_y - 13 + k * 2, 16, 2, a_rim if k % 2 == 0 else a_lit)
        _rect(bpx, cx + 12 - k * 3, base_y - 11 + k * 2, 16, 1, a_ink)
    _rect(bpx, 146, base_y - 5, 11, 5, a_mid)
    _rect(bpx, 146, base_y - 5, 11, 1, a_rim)
    _rect(bpx, 146, base_y - 1, 11, 1, a_ink)

    # Sunlit sculpted golden sandy seabed (y = SAND_Y..H) with smooth atmospheric mist near horizon!
    # Subtle warm-sandy contrast so translucent sunlit caustic filaments glow richly against the golden seabed!
    sand_ramp = [
        (46, 102, 106, 255),   # misty sea-teal distant sand horizon
        (92, 128, 104, 255),   # cool distant golden sand
        (138, 144, 104, 255),  # mid warm sand
        (174, 164, 114, 255),  # rich warm golden sand
        (202, 188, 132, 255),  # sunlit beach sand
        (222, 210, 156, 255),  # peak warm sand dune
    ]
    for y in range(SAND_Y, H):
        v = (y - SAND_Y) / max(1, H - SAND_Y)
        for x in range(W):
            dune = math.sin(x * 0.048 + v * 4.8) * 0.06 + (_fbm(x * 0.07, y * 0.14, 303, 2) - 0.5) * 0.12
            center_lit = math.exp(-((x - 138) / 86.0) ** 2) * 0.24
            # Smooth water-haze rolloff at the very top of the seabed (y = 346..360)
            horizon_haze = _clamp((y - SAND_Y) / 14.0, 0.0, 1.0)
            val = _clamp((0.10 + v * 0.64 + center_lit + dune) * (0.28 + 0.72 * horizon_haze), 0.0, 1.0)
            bpx[x, y] = _dither_pick(sand_ramp, val, x, y, 0.55)

    # ===== 2. FOREGROUND PLATE: multi-tiered Atlantis masonry tower, shipwreck, colonnades, stairs & foreground frame =====
    # --- LEFT MULTI-TIERED SUNKEN ATLANTIS TEMPLE TOWER (y = 0..202) ---
    # Tier 1: dramatic tapering upper temple turret + overhanging cornice
    _paint_tower_tier(fpx, 0, 0, 56, 32, seed=401, right_sun=True, overhang=True, taper=14)
    _paint_cornice(fpx, 0, 26, 74, 14, right_sun=True, seed=402)
    # Tier 2: shadowed recessed wall with circular stone oculus + stacked carved Atlantis wheel medallions!
    _paint_tower_tier(fpx, 0, 40, 54, 56, seed=405, right_sun=True, overhang=False, taper=10)
    _paint_medallion(fpx, 28, 56, 9, right_sun=True)
    _paint_medallion(fpx, 34, 80, 6, right_sun=True)
    _paint_cornice(fpx, 0, 92, 68, 14, right_sun=True, seed=408)
    # Tier 3: lower cliff masonry behind shipwreck + carved twin wheel reliefs
    _paint_tower_tier(fpx, 0, 106, 48, 92, seed=412, right_sun=True, overhang=False, taper=16)
    _paint_medallion(fpx, 38, 120, 6, right_sun=True)
    _paint_medallion(fpx, 38, 178, 6, right_sun=True)

    # Weathered sunken wooden galleon bow wedged into Tier 3!
    _paint_shipwreck_bow(fpx, rnd)

    # --- LEFT GRAND CLASSICAL COLONNADE (y = 194..364) ---
    # Recessed shadowy temple cavern behind the columns (craggy stone & deep marine depth!)
    _paint_sanctuary_recess(fpx, 0, 210, 106, 152, seed=555)
    # Cast shadow from entablature onto temple interior
    _darken(fpx, 0, 212, 114, 10, 0.30)
    # Right dark sanctuary recess behind right column
    _paint_sanctuary_recess(fpx, 216, 244, W - 216, 122, seed=777)

    # Front architectural occlusion layer: painted separately then alpha-composited onto `fg`
    # so `occ_left` & `occ_right` are SUBPIXEL-EXACT 3D masks (columns, cornices, moss, stairs & corals IN FRONT of the diver!).
    front = Image.new('RGBA', VIEW, (0, 0, 0, 0))
    frpx = front.load()

    # Grand 3D-perspective entablature ledge above the left columns
    _paint_cornice(frpx, 0, 194, 122, 18, right_sun=True, seed=505)
    # Two monumental weathered fluted Ionic columns with carved relief pedestals!
    _paint_column(frpx, 36, 212, 336, 17, rnd, right_sun=True)
    _paint_pedestal(frpx, 31, 336, 27, 26, right_sun=True)
    _paint_column(frpx, 86, 212, 336, 17, rnd, right_sun=True)
    _paint_pedestal(frpx, 81, 336, 27, 26, right_sun=True)
    # Seated Atlantis statue perched majestically on the left temple cornice
    _paint_statue(frpx, 78, 163, 'seated')

    # --- LEFT RUINED DIAGONAL STAIRS & SCULPTED FOREGROUND BOULDERS (bottom-left) ---
    _paint_ruined_stairs(frpx, 2, 292, 9, 8, 8, right_sun=True)
    for bx, by, rx, ry, sd in (
        (16, 336, 22, 16, 610), (42, 358, 20, 15, 611), (18, 376, 28, 22, 612),
        (56, 384, 24, 18, 613), (26, 412, 36, 24, 614), (74, 414, 30, 20, 615),
    ):
        _paint_boulder(frpx, bx, by, rx, ry, ROCK_RAMP, sd, light_dir=(0.68, -0.74), sand_bounce=True)

    # --- RIGHT CLASSICAL PARAPET, SHRINE COLUMN, POSEIDON STATUE & BROKEN RAMP ---
    _paint_cornice(frpx, 208, 230, W - 208, 16, right_sun=False, seed=707)
    _paint_column(frpx, 220, 246, 338, 16, rnd, right_sun=False)
    _paint_pedestal(frpx, 215, 338, 28, 24, right_sun=False)
    _paint_statue(frpx, 232, 194, 'standing')
    # Diagonal ruined stone ramp descending on the right onto the sand
    _paint_ruined_stairs(frpx, 246, 336, 6, -9, 6, right_sun=False)
    for bx, by, rx, ry, sd in (
        (252, 368, 24, 18, 810), (228, 392, 24, 18, 811),
        (250, 412, 32, 22, 812), (206, 416, 26, 18, 813),
    ):
        _paint_boulder(frpx, bx, by, rx, ry, ROCK_RAMP, sd, light_dir=(-0.62, -0.78), sand_bounce=True)

    # --- FALLEN 3D ANGLED FLUTED COLUMN DRUM ON FOREGROUND SAND (with dark cast shadow!) ---
    _darken(bpx, 174, 404, 38, 10, 0.42)
    _paint_angled_drum(frpx, 194, 400)

    # --- HANGING MOSS DRAPES (upper tower on `fg`; doorway drapes on `front` so they hang IN FRONT of diver!) ---
    _paint_moss(fpx, 18, 70, 36, rnd, 16)
    _paint_moss(fpx, 22, 64, 102, rnd, 18)
    _paint_moss(frpx, 12, 118, 208, rnd, 24)
    _paint_moss(frpx, 210, 264, 242, rnd, 22)

    # --- PASS-2 LIVING CORAL GARDENS (upper tower on `fg`; colonnade/doorway/boulder corals on `front`!) ---
    upper_corals = [
        (54, 27, 'pink', 1.15), (66, 28, 'orange', 0.90),
        (46, 92, 'cyan', 1.05), (58, 92, 'pink', 1.25),
        (16, 125, 'cyan', 1.10), (62, 140, 'orange', 0.95),
    ]
    for cx0, cy0, kind, sc in upper_corals:
        _paint_coral(fpx, cx0, cy0, kind, sc, rnd)
    front_corals = [
        # Left temple cornice garden (flanking seated statue!)
        (16, 194, 'violet', 1.15), (46, 194, 'pink', 1.25), (66, 194, 'orange', 1.0),
        # Left ruined stairs & boulder garden (anchored on actual steps & rocks!)
        (16, 294, 'cyan', 1.15), (24, 308, 'pink', 1.15), (42, 326, 'orange', 1.05),
        (76, 358, 'pink', 1.0), (112, 358, 'orange', 0.95), (96, 360, 'cyan', 0.85),
        # Right parapet & Poseidon shrine garden
        (218, 230, 'pink', 1.15), (258, 230, 'violet', 0.95),
        # Right temple pedestal & boulders (grounded firmly on plinth & rocks!)
        (214, 340, 'pink', 1.10), (248, 336, 'cyan', 1.20),
        (206, 364, 'pink', 1.00), (232, 366, 'orange', 1.10), (254, 370, 'violet', 0.95),
    ]
    for cx0, cy0, kind, sc in front_corals:
        _paint_coral(frpx, cx0, cy0, kind, sc, rnd)

    # --- PASS-4, PASS-5 & PASS-6 SEABED STORYTELLING, FRIEZES, URNS, HELM WHEEL, SEA FANS & CAUSTIC KISS ---
    _paint_frieze_and_urns(frpx)
    _paint_seabed_details(bpx, frpx, rnd)
    _paint_pass6_biodiversity(bpx, frpx, rnd)
    _paint_caustic_kiss(frpx)

    # Composite `front` cleanly onto `fg` (identical silhouette!), and attach exact 3D occlusion & lit room plates!
    fg.alpha_composite(front)
    fg._extras = {
        'room_left_lit': _paint_sanctuary_lit_left(),
        'room_right_lit': _paint_sanctuary_lit_right(),
        'occ_left': front.crop((0, 194, 122, 368)),
        'occ_right': front.crop((208, 230, 267, 376)),
    }

    return bg, fg


def build_caustic_mask(bg, fg):
    """Bake a 134 x 214 3D sunlight-exposure mask from `bg` & `fg` so translucent caustics dance over ALL sunlit ruins, shipwreck, statues, boulders & sand!"""
    mask = Image.new('RGBA', (CW, CH), (0, 0, 0, 255))
    mpx = mask.load()
    bpx, fpx = bg.load(), fg.load()
    for j in range(CH):
        y = min(H - 1, j * 2)
        depth_fade = 1.0 - (y / H) * 0.16
        for i in range(CW):
            x = min(W - 1, i * 2)
            fr, fg_c, fb, fa = fpx[x, y]
            val = 0.0
            if fa > 128:
                lum = (0.299 * fr + 0.587 * fg_c + 0.114 * fb) / 255.0
                # Skip pitch-black cave interior behind columns & crisp dark ink outlines/silhouettes!
                if lum > 0.12:
                    top_open = (y >= 4 and fpx[x, y - 4][3] < 64) or (y >= 8 and fpx[x, y - 8][3] < 64)
                    right_open = (x + 4 < W and fpx[x + 4, y][3] < 64) or (x + 8 < W and y >= 4 and fpx[x + 8, y - 4][3] < 64)
                    # Generous exposure on sunlit masonry, shipwreck timber, fluted columns, statues & boulders!
                    base = 0.28 + _clamp((lum - 0.12) / 0.50, 0.0, 1.0) * 0.62
                    boost = (0.26 if top_open else 0.0) + (0.18 if right_open else 0.0)
                    # Keep the very darkest bottom foreground kelp silhouettes crisp
                    if y > 378 and lum < 0.20:
                        val = 0.0
                    else:
                        val = _clamp((base + boost) * depth_fade, 0.0, 0.96)
            else:
                br, bg_c, bb, ba = bpx[x, y]
                if ba > 160:
                    lum = (0.299 * br + 0.587 * bg_c + 0.114 * bb) / 255.0
                    if y >= SAND_Y:
                        # Golden sandy seabed: full luminous translucent caustics with smooth horizon rolloff!
                        horiz = _clamp((y - SAND_Y) / 10.0, 0.32, 1.0)
                        center = 0.72 + 0.28 * math.exp(-((x - 142) / 104.0) ** 2)
                        val = _clamp((0.55 + lum * 0.55) * horiz * center, 0.28, 1.0)
                    elif y >= 248 and br >= 24 and lum > 0.30:
                        # Magical dancing caustic shimmer strictly on the carved Atlantis archway stones & steps (NOT on misty water behind it!)
                        val = _clamp(0.24 + (lum - 0.30) * 1.45, 0.20, 0.66)
            u8 = int(_clamp(round(val * 255.0), 0, 255))
            mpx[i, j] = (u8, u8, u8, 255)
    return mask


def pack_atlas(bg, fg, sprites=None):
    """Pack `bg`, `fg`, all handcrafted 16-bit sprites, and the 3D `caustic_mask` cleanly into one crisp RGBA atlas."""
    if sprites is None:
        sprites = usprites.build_sprites()
    atlas = Image.new('RGBA', ATLAS_SIZE, (0, 0, 0, 0))
    atlas.paste(bg, (0, 0))
    atlas.paste(fg, (W + GUTTER, 0))
    frames = {
        'bg': [0, 0, W, H],
        'fg': [W + GUTTER, 0, W, H],
    }
    # Pack 134 x 214 caustic exposure mask cleanly on the right edge of the sprite band!
    cmask = build_caustic_mask(bg, fg)
    mx, my = ATLAS_W - CW, H + GUTTER
    atlas.paste(cmask, (mx, my))
    frames['caustic_mask'] = [mx, my, CW, CH]

    # Shelf-pack all sprites into the left column (0 .. mx - 1) and full width below my + CH!
    x, y, row_h = 0, H + GUTTER, 0
    for name, img in sprites.items():
        sw, sh = img.size
        limit_w = (mx - GUTTER) if y < (my + CH + GUTTER) else ATLAS_W
        if x + sw > limit_w:
            x = 0
            y += row_h + GUTTER
            row_h = 0
            limit_w = (mx - GUTTER) if y < (my + CH + GUTTER) else ATLAS_W
        if y + sh > ATLAS_SIZE[1]:
            raise RuntimeError(f'Sprite {name} ({sw}x{sh}) exceeded ATLAS_SIZE {ATLAS_SIZE}')
        atlas.paste(img, (x, y))
        frames[name] = [x, y, sw, sh]
        x += sw + GUTTER
        if sh > row_h:
            row_h = sh

    # Pack the 4 illuminated sanctuary & 3D column occlusion plates cleanly on a dedicated bottom row!
    extras = getattr(fg, '_extras', None) or {
        'room_left_lit': _paint_sanctuary_lit_left(),
        'room_right_lit': _paint_sanctuary_lit_right(),
        'occ_left': Image.new('RGBA', (122, 174), (0, 0, 0, 0)),
        'occ_right': Image.new('RGBA', (59, 146), (0, 0, 0, 0)),
    }
    x = 0
    y = max(y + row_h + GUTTER, my + CH + GUTTER)
    row_h = 0
    for name in ('room_left_lit', 'occ_left', 'room_right_lit', 'occ_right'):
        img = extras[name]
        sw, sh = img.size
        if x + sw > ATLAS_W:
            x = 0
            y += row_h + GUTTER
            row_h = 0
        if y + sh > ATLAS_SIZE[1]:
            raise RuntimeError(f'Room plate {name} ({sw}x{sh}) exceeded ATLAS_SIZE {ATLAS_SIZE}')
        atlas.paste(img, (x, y))
        frames[name] = [x, y, sw, sh]
        x += sw + GUTTER
        if sh > row_h:
            row_h = sh
    return atlas, frames


def describe(frames=None):
    if frames is None:
        _, frames = pack_atlas(Image.new('RGBA', VIEW, (0, 0, 0, 0)), Image.new('RGBA', VIEW, (0, 0, 0, 0)))
    return {
        'version': 3,
        'scene': NAME,
        'size': list(ATLAS_SIZE),
        'view': list(VIEW),
        'frames': frames,
    }


def _parse_color(color, cache):
    value = cache.get(color)
    if value is not None:
        return value
    if color.startswith('#'):
        hexa = color[1:]
        if len(hexa) == 3:
            hexa = ''.join(ch * 2 for ch in hexa)
        value = (int(hexa[0:2], 16), int(hexa[2:4], 16), int(hexa[4:6], 16), 255)
    else:
        match = _RGBA_RE.match(color)
        if match:
            alpha = float(match.group(4)) if match.group(4) is not None else 1.0
            value = (
                int(float(match.group(1))),
                int(float(match.group(2))),
                int(float(match.group(3))),
                max(0, min(255, int(round(alpha * 255)))),
            )
        else:
            value = (0, 0, 0, 255)
    cache[color] = value
    return value


def render_preview(bg, fg, phase='day', steps=42, seed=4242, atlas=None, frames=None, poke=None):
    """Render a full 267 x 427 composite preview using `game-underwater.js` + plates, 16-bit sprites & 3D translucent caustics."""
    if atlas is None or frames is None:
        atlas, frames = pack_atlas(bg, fg)
    # Extract the exact baked 134 x 214 caustic exposure mask so the Node preview renders identical translucent full-scene caustics!
    mx, my, mw, mh = frames['caustic_mask']
    cmask_img = atlas.crop((mx, my, mx + mw, my + mh))
    mask_bytes = [cmask_img.getpixel((i, j))[0] for j in range(mh) for i in range(mw)]
    poke_js = f"uw.pokeWorld(world, {float(poke[0])}, {float(poke[1])});" if poke else ""
    node_script = (
        f"const uw = require({json.dumps(str(SCENE_JS))});"
        f"const mask = Uint8Array.from({json.dumps(mask_bytes)});"
        "const ops = []; let path = [];"
        "const g = {"
        "  fillStyle: '#000', globalAlpha: 1,"
        "  fillRect(x, y, w, h) { ops.push(['r', x, y, w, h, this.fillStyle, this.globalAlpha]); },"
        "  beginPath() { path = []; },"
        "  moveTo(x, y) { path.push([x, y]); },"
        "  lineTo(x, y) { path.push([x, y]); },"
        "  closePath() {},"
        "  fill() { if (path.length >= 3) ops.push(['p', path, this.fillStyle, this.globalAlpha]); path = []; },"
        "  drawImage(img, sx, sy, sw, sh, dx, dy) { ops.push(['i', img, sx, sy, sw, sh, dx, dy, this.globalAlpha]); }"
        "};"
        f"const world = uw.createWorld({int(seed)});"
        f"{poke_js}"
        f"for (let i = 0; i < {int(steps)}; i++) uw.stepWorld(world, uw.STEP, 427);"
        "const cData = new Uint8ClampedArray(uw.CW * uw.CH * 4);"
        "const causticBuf = { canvas: 'caustic', g: { putImageData(){} }, img: { data: cData, width: uw.CW, height: uw.CH }, u32: new Uint32Array(cData.buffer) };"
        f"uw.renderFrame(g, {{ world, atlas: 'atlas', frames: {json.dumps(frames)}, phase: {json.dumps(phase)}, causticBuf, causticMask: mask, causticTick: -99, causticPhase: '' }}, 'high');"
        "process.stdout.write(JSON.stringify({ ops, cw: uw.CW, ch: uw.CH, caustic: Array.from(cData) }));"
    )
    raw = subprocess.check_output(['node', '-e', node_script], cwd=str(ROOT))
    payload = json.loads(raw.decode('utf-8'))
    ops = payload['ops']
    cw_p, ch_p = int(payload['cw']), int(payload['ch'])
    caustic_rgba = Image.frombytes('RGBA', (cw_p, ch_p), bytes(payload['caustic']))
    if (cw_p, ch_p) != VIEW:
        caustic_rgba = caustic_rgba.resize(VIEW, Image.Resampling.BILINEAR)
    image = Image.new('RGB', VIEW, (10, 48, 78))
    draw = ImageDraw.Draw(image, 'RGBA')
    cache = {}
    for op in ops:
        if op[0] == 'r':
            _, x, y, w, h, col, ga = op
            if w <= 0 or h <= 0 or ga <= 0.005:
                continue
            x0, y0 = int(round(x)), int(round(y))
            r, gr, b, a = _parse_color(col, cache)
            a = int(round(a * max(0.0, min(1.0, ga))))
            draw.rectangle((x0, y0, x0 + int(round(w)) - 1, y0 + int(round(h)) - 1), fill=(r, gr, b, a))
        elif op[0] == 'p':
            _, pts, col, ga = op
            r, gr, b, a = _parse_color(col, cache)
            a = int(round(a * max(0.0, min(1.0, ga))))
            draw.polygon([(int(round(px)), int(round(py))) for px, py in pts], fill=(r, gr, b, a))
        elif op[0] == 'i':
            _, img_tag, sx, sy, sw, sh, dx, dy, ga = op
            if ga <= 0.005:
                continue
            if img_tag == 'caustic':
                image.paste(caustic_rgba, (0, 0), caustic_rgba)
            else:
                crop = atlas.crop((int(round(sx)), int(round(sy)), int(round(sx + sw)), int(round(sy + sh))))
                if ga < 0.995:
                    r_ch, g_ch, b_ch, a_ch = crop.split()
                    a_ch = a_ch.point(lambda v: int(round(v * ga)))
                    crop = Image.merge('RGBA', (r_ch, g_ch, b_ch, a_ch))
                image.paste(crop, (int(round(dx)), int(round(dy))), crop)
            draw = ImageDraw.Draw(image, 'RGBA')
    return image


def thumbnail(bg, fg, atlas=None, frames=None):
    """A vibrant 240 x 160 scene-picker thumbnail showing the animated surface, sunbeams, ruins, corals & scuba diver."""
    try:
        full = render_preview(bg, fg, phase='day', steps=42, seed=4242, atlas=atlas, frames=frames)
    except Exception:
        full = Image.new('RGB', VIEW, (14, 86, 118))
        full.paste(bg, (0, 0), bg)
        full.paste(fg, (0, 0), fg)
    return full.crop((0, 12, W, 190)).resize((240, 160), Image.Resampling.NEAREST)


def write(out, with_manifest=False):
    """Write the atlas PNG, JSON metadata and WebP thumbnail atomically (0o600) into `out`."""
    out = Path(out)
    bg, fg = build_plates()
    atlas, frames = pack_atlas(bg, fg)
    data = describe(frames)
    png = out / f'scene-{NAME}.png'
    json_path = out / f'scene-{NAME}.json'
    thumb = out / f'thumb-{NAME}.webp'
    media._write_atomically(png, lambda target: atlas.save(target, format='PNG', optimize=True), media.MAX_IMAGE_BYTES)
    media._write_atomically(json_path, lambda target: target.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True), encoding='utf-8'), 512 * 1024)
    media.save_thumbnail(thumbnail(bg, fg, atlas=atlas, frames=frames), thumb)
    if with_manifest:
        media.update_manifest(NAME, media.scene_entry('game', png.name, 'image', ATLAS_SIZE[0], ATLAS_SIZE[1], data=json_path.name), out)
    return {'atlas': str(png), 'size': list(ATLAS_SIZE), 'view': list(VIEW), 'bytes': png.stat().st_size, 'manifest': bool(with_manifest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, required=True, help='destination folder (the tablet private folder or a scratch folder)')
    parser.add_argument('--manifest', action='store_true', help='also add the scene to scenes.json in that folder')
    args = parser.parse_args(argv)
    print(json.dumps(write(args.out, args.manifest)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
