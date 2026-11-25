"""Handcrafted multi-frame 16-bit biomechanical sprite builders for DEEP BLUE (`game-underwater.js`).

Every living creature uses a smooth 6-to-12 frame biomechanical motion cycle (continuous sinusoidal kinematics,
hydrodynamic fin-flex wave lag, traveling spinal/tentacle waves, and 5-stage smooth prop opening). Pre-packing
all frames (with left/right flips) into `scene-underwater.png` yields silky-smooth life-like animation at ONE
`drawImage` per creature — zero extra CPU/GPU load on modest Android tablets!
"""
import math
from PIL import Image

INK = (6, 15, 24, 255)

# Exported frame counts so game-underwater.js and tests stay in lockstep
COUNTS = {
    'diver': 12,
    'whale': 8,
    'manta': 8,
    'shark': 8,
    'dolphin': 10,
    'turtle': 10,
    'octo': 10,
    'jelly': 8,
    'fish': 6,
    'chest': 5,
    'clam': 5,
}


def _new(w, h):
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    return img, img.load()


def _put(px, w, h, x, y, col):
    ix, iy = int(round(x)), int(round(y))
    if 0 <= ix < w and 0 <= iy < h:
        px[ix, iy] = col


def _from_grid(grid, cmap):
    h = len(grid)
    w = max(len(row) for row in grid)
    img, px = _new(w, h)
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            col = cmap.get(ch)
            if col is not None:
                px[x, y] = col
    return img


def _outline_and_fill(w, h, body, pal, outline=INK, soft_outline=False):
    img, px = _new(w, h)
    if outline is not None:
        for (x, y) in body:
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + ox, y + oy
                if (nx, ny) not in body and 0 <= nx < w and 0 <= ny < h:
                    if not soft_outline or oy >= 0:
                        px[nx, ny] = outline
    for (x, y), sh in body.items():
        if 0 <= x < w and 0 <= y < h:
            px[x, y] = pal[sh]
    return img


def _paint_thick_seg(body, x0, y0, x1, y1, r0, r1, sh_top, sh_mid, sh_bot, steps=16):
    """Draw a smooth tapered capsule segment into a shade-indexed pixel map."""
    for s in range(steps + 1):
        t = s / steps
        cx = x0 + (x1 - x0) * t
        cy = y0 + (y1 - y0) * t
        rad = r0 + (r1 - r0) * t
        ir = int(math.ceil(rad))
        for dy in range(-ir, ir + 1):
            for dx in range(-ir, ir + 1):
                if dx * dx + dy * dy <= (rad + 0.25) ** 2:
                    ix, iy = int(round(cx + dx)), int(round(cy + dy))
                    sh = sh_top if dy < -rad * 0.25 else sh_bot if dy > rad * 0.35 else sh_mid
                    body[(ix, iy)] = sh


# ---- 1. HERO SCUBA DIVER WITH REAL LONG FLEXING SCUBA FINS (58 x 32, 12 silky-smooth flutter-kick frames, facing RIGHT!) ----
def _make_diver(frame, total=12):
    w, h = 58, 32
    ph = (frame / total) * math.pi * 2.0
    pal = [
        INK,                       # 0 outline
        (12, 22, 36, 255),         # 1 far-leg dark wetsuit
        (22, 40, 58, 255),         # 2 far-leg mid wetsuit
        (20, 38, 56, 255),         # 3 near-leg shadow wetsuit
        (36, 66, 90, 255),         # 4 near-leg lit wetsuit
        (58, 102, 128, 255),       # 5 near-leg top highlight
        (16, 28, 42, 255),         # 6 far-fin dark blade rail
        (34, 152, 160, 255),       # 7 far-fin muted teal flex channel
        (182, 142, 26, 255),       # 8 far-fin muted yellow tip
        (24, 42, 62, 255),         # 9 near-fin sleek black-navy side rail
        (54, 226, 220, 255),       # 10 near-fin vibrant turquoise flex channel
        (248, 200, 48, 255),       # 11 near-fin bright yellow paddle tip
        (255, 246, 156, 255),      # 12 near-fin sunlit edge highlight
    ]
    body = {}
    bob = math.sin(ph * 2.0) * 0.55

    # Draw FAR leg first (lagging pi radians), then NEAR leg on top — BOTH with long 15px flexing scuba fins!
    for leg in (0, 1):
        lp = ph + (math.pi if leg == 0 else 0.0)
        hip_x, hip_y = 29.0, 16.2 + (0.6 if leg == 1 else -0.6) + bob * 0.5
        # Graceful controlled scuba flutter kick (no awkward scissor-splits, ZERO edge clipping!)
        a_thigh = math.sin(lp) * 0.21
        a_calf = math.sin(lp - 0.62) * 0.31
        knee_x = hip_x - math.cos(a_thigh) * 6.5
        knee_y = hip_y + math.sin(a_thigh) * 6.5
        ankle_x = knee_x - math.cos(a_calf) * 6.5
        ankle_y = knee_y + math.sin(a_calf) * 6.5

        if leg == 0:
            _paint_thick_seg(body, hip_x, hip_y, knee_x, knee_y, 1.9, 1.6, 2, 1, 1, 10)
            _paint_thick_seg(body, knee_x, knee_y, ankle_x, ankle_y, 1.5, 1.2, 2, 1, 1, 10)
        else:
            _paint_thick_seg(body, hip_x, hip_y, knee_x, knee_y, 2.0, 1.7, 5, 4, 3, 10)
            _paint_thick_seg(body, knee_x, knee_y, ankle_x, ankle_y, 1.6, 1.3, 5, 4, 3, 10)

        # REAL LONG FLEXING SCUBA FIN (15px blade!) with hydrodynamic whip-bend traveling smoothly down the blade!
        fx, fy = ankle_x, ankle_y
        fin_len = 15.0
        for s in range(18):
            u = s / 17.0
            bend = a_calf + math.sin(lp - 1.28 - u * 1.15) * (0.28 + u * 0.30)
            step = fin_len / 17.0
            fx -= math.cos(bend) * step
            fy += math.sin(bend) * step
            hw = 1.15 + u * 1.75
            nx, ny = math.sin(bend), math.cos(bend)
            for k in range(-3, 4):
                off = k * 0.72
                if abs(off) > hw:
                    continue
                ix, iy = int(round(fx + nx * off)), int(round(fy + ny * off))
                is_rail = abs(off) > hw - 0.85
                if leg == 0:
                    sh = 6 if is_rail else (8 if u > 0.72 else 7 if u > 0.25 else 6)
                else:
                    if is_rail:
                        sh = 12 if (off < 0 and u > 0.35 and u < 0.85) else 9
                    elif u > 0.72:
                        sh = 12 if off < -0.2 else 11
                    elif u > 0.22:
                        sh = 10
                    else:
                        sh = 9
                body[(ix, iy)] = sh

    img = _outline_and_fill(w, h, body, pal, outline=INK)
    px = img.load()

    cmap = {
        '.': None, 'k': INK,
        'd': (14, 26, 40, 255), 's': (26, 48, 68, 255), 'b': (48, 86, 114, 255), 'c': (56, 232, 226, 255),
        'y': (244, 192, 42, 255), 'Y': (255, 244, 152, 255), 'o': (158, 106, 18, 255),
        'g': (152, 255, 248, 255), 'w': (255, 255, 255, 255), 'f': (236, 174, 134, 255),
        'm': (202, 224, 234, 255), 'r': (62, 82, 98, 255),
    }
    upper = [
        '.....kkkkkkkkkkk..................',
        '....kYYYYYYYYYYkmk................',
        '...kyykkyyyykkykmkkk..............',
        '...kyykkyyyykkyksk.kk.............',
        '...kookyooookkooks..kkkkk.........',
        '..kkkkkkkkkkkkkkkkkksbbbbsk.......',
        '.kssbbbbbbbbbbbbbsksbbkggwmk......',
        'ksbsssccccccccbbbsksbkgggwmk......',
        'kddsssssbbbbbbbbsskksbkffggmk.....',
        'kkddddssssssssssskkkksbfffskk.....',
        '..kkkkkddddssssssbssssskkkkkkk....',
        '......kkkkkddsssbsssbbbbckrrwmk...',
        '...........kkkkkkddddssbckrrwmk...',
        '................kkkkkkkkkkkkkk....',
    ]
    oy = int(round(7 + bob))
    for dy, row in enumerate(upper):
        for dx, ch in enumerate(row):
            col = cmap.get(ch)
            if col is not None:
                _put(px, w, h, 24 + dx, oy + dy, col)
    return img


# ---- 2. MAJESTIC HUMPBACK WHALE (108 x 40, 8 slow majestic undulation frames, facing RIGHT!) ----
def _make_whale(frame, total=8):
    w, h = 108, 40
    ph = (frame / total) * math.pi * 2.0
    pal = [
        (7, 36, 58, 255),
        (9, 44, 68, 255),
        (13, 58, 86, 255),
        (21, 78, 108, 255),
        (40, 118, 144, 255),
    ]
    body = {}
    for x in range(6, 102):
        u = (x - 6) / 96.0
        # Traveling dorsoventral wave propagating head -> tail (strongest at tail, calm at head!)
        amp = ((1.0 - u) ** 1.75) * 4.4
        wave_y = math.sin(ph + u * 3.2) * amp
        if u < 0.14:
            tf = u / 0.14
            cy = 19.0 + wave_y
            half_h = 1.8 + (1.0 - tf) * 10.6
            notch = (0.055 - u) / 0.055 * 5.0 if u < 0.055 else 0.0
        elif u < 0.42:
            pf = (u - 0.14) / 0.28
            cy = 19.0 + wave_y
            half_h = 2.0 + (pf ** 1.35) * 6.8
            notch = 0.0
        else:
            bf = (u - 0.42) / 0.58
            cy = 19.2 - math.sin(bf * math.pi) * 1.4 + wave_y * 0.45
            half_h = 9.2 * math.sin(max(0.0, min(1.0, (1.0 - bf) * 0.90 + 0.10)) * math.pi * 0.62)
            if bf > 0.78:
                half_h *= max(0.24, (1.0 - bf) / 0.22) ** 0.36
            notch = 0.0
        for y in range(int(cy - half_h), int(cy + half_h) + 1):
            if notch > 0 and abs(y - cy) < notch:
                continue
            rel = (y - (cy - half_h)) / max(1.0, half_h * 2.0)
            sh = 4 if (rel < 0.14 and u > 0.24) else 3 if rel < 0.40 else 2 if rel < 0.74 else 1
            if u > 0.62 and rel > 0.66 and (y % 2 == 0):
                sh = 0
            body[(x, y)] = sh
    # Dorsal fin bump
    df_y = int(round(12 + math.sin(ph + 0.35 * 3.2) * 1.2))
    for dx in range(9):
        hh = int(3.8 * math.sin((dx / 8.0) * math.pi))
        for dy in range(hh):
            body[(36 + dx, df_y - dy)] = 4 if dy == hh - 1 else 2
    # Sweeping pectoral fin oscillating gently with body glide
    pec_shift = math.sin(ph + 0.68 * 3.2) * 2.0
    for i in range(21):
        fx = 71 - i
        fy = int(round(24 + i * 0.54 + pec_shift * (i / 20.0)))
        fw = max(2, 7 - i // 4)
        for dx in range(fw):
            body[(fx - dx, fy)] = 1 if i > 10 else 2
    return _outline_and_fill(w, h, body, pal, outline=pal[0], soft_outline=True)


# ---- 3. GIANT MANTA RAY (70 x 32, 8 hypnotic traveling-wave wingtip flight frames, facing RIGHT!) ----
def _make_manta(frame, total=8):
    w, h = 70, 32
    ph = (frame / total) * math.pi * 2.0
    pal = [
        (7, 36, 58, 255),
        (10, 48, 74, 255),
        (16, 68, 96, 255),
        (28, 96, 124, 255),
        (60, 152, 172, 255),
    ]
    body = {}
    # Sinuous trailing whip tail with wave traveling body (u=1) -> tail tip (u=0)
    for x in range(4, 28):
        u = (x - 4) / 24.0
        y = int(round(16 + math.sin(ph + u * 4.2) * (2.6 - u * 1.2)))
        body[(x, y)] = 1 if x < 16 else 2
    # Sweeping diamond wings with anterior-to-posterior traveling undulation (u=1 front -> u=0 rear)!
    for x in range(27, 61):
        u = (x - 27) / 34.0
        span = 11.8 * math.sin(u * math.pi)
        wing_wave = math.sin(ph + u * 2.2) * 4.8 * (math.sin(u * math.pi) ** 1.15)
        y_top = int(round(16 - span + wing_wave * 0.62))
        y_bot = int(round(16 + span * 0.72 + wing_wave * 0.42))
        for y in range(y_top, y_bot + 1):
            rel = (y - y_top) / max(1.0, y_bot - y_top)
            sh = 4 if rel < 0.16 else 3 if rel < 0.44 else 2 if rel < 0.78 else 1
            body[(x, y)] = sh
    for x in range(59, 65):
        body[(x, 13)] = 4; body[(x, 14)] = 2
        body[(x, 18)] = 2; body[(x, 19)] = 1
    return _outline_and_fill(w, h, body, pal, outline=pal[0], soft_outline=True)


# ---- 4. PATROLLING REEF SHARK (66 x 26, 8 sleek sinusoidal swim frames, facing RIGHT!) ----
def _make_shark(frame, total=8):
    w, h = 66, 26
    ph = (frame / total) * math.pi * 2.0
    pal = [
        INK,
        (16, 48, 70, 255),
        (32, 78, 104, 255),
        (56, 114, 138, 255),
        (114, 176, 192, 255),
        (194, 236, 240, 255),
    ]
    body = {}
    tail_wag = math.sin(ph) * 2.4
    for x in range(13, 62):
        u = (x - 13) / 49.0
        cy = 14.0 + math.sin(ph + u * 3.4) * ((1.0 - u) ** 1.8) * 2.2
        if u < 0.28:
            hh = 1.6 + (u / 0.28) * 3.8
        elif u < 0.78:
            hh = 5.4 + math.sin((u - 0.28) / 0.50 * math.pi) * 1.4
        else:
            hh = 5.4 * max(0.08, (1.0 - u) / 0.22) ** 0.65
        for y in range(int(cy - hh), int(cy + hh) + 1):
            rel = (y - (cy - hh)) / max(1.0, hh * 2.0)
            sh = 3 if rel < 0.22 else 2 if rel < 0.56 else 4 if rel < 0.84 else 5
            body[(x, y)] = sh
    for dy in range(8):
        x0 = 34 - int(dy * 0.55)
        fw = max(2, 9 - dy)
        for dx in range(fw):
            body[(x0 + dx, 8 - dy)] = 3 if dx == fw - 1 else 1 if dx < 2 else 2
    pec_bob = int(round(math.sin(ph + 2.2) * 0.7))
    for dy in range(6):
        x0 = 43 - int(dy * 0.7)
        fw = max(2, 7 - dy)
        for dx in range(fw):
            body[(x0 + dx, 18 + dy + pec_bob)] = 1 if dy > 3 else 2
    ty = 14.0 + tail_wag
    # Tail foreshortens slightly at lateral extremes of the sweep for realistic 3D shark tail swing!
    tail_spread = 0.72 + 0.28 * abs(math.cos(ph))
    for dy in range(-9, 8):
        dist = abs(dy)
        sweep = int(dist * 0.65 * tail_spread)
        thick = max(2, int((5 - dist // 3) * (0.78 + 0.22 * abs(math.cos(ph)))))
        if dy < 0 or dist < 6:
            for dx in range(thick):
                body[(13 - sweep + dx, int(round(ty + dy)))] = 2 if dx > 0 else 1
    img = _outline_and_fill(w, h, body, pal, outline=INK)
    px = img.load()
    _put(px, w, h, 54, 13, INK); _put(px, w, h, 55, 12, pal[5])
    for gx in (44, 46, 48):
        for gy in (13, 14, 15):
            _put(px, w, h, gx, gy, pal[1])
    return img


# ---- 5. PLAYFUL BOTTLENOSE DOLPHIN (54 x 24, 10 fluid dorsoventral spinal-wave frames, facing RIGHT!) ----
def _make_dolphin(frame, total=10):
    w, h = 54, 24
    ph = (frame / total) * math.pi * 2.0
    pal = [
        INK,
        (26, 68, 102, 255),
        (54, 118, 154, 255),
        (106, 180, 210, 255),
        (188, 236, 248, 255),
        (240, 254, 255, 255),
    ]
    body = {}
    head_nod = math.sin(ph + 3.4) * 0.9
    for x in range(11, 45):
        u = (x - 11) / 34.0
        # Real dolphin traveling spinal wave: propagates HEAD (u=1) -> BODY -> TAIL (u=0)!
        arch = -math.sin(u * math.pi) * 2.5
        wave = math.sin(ph + u * 3.4) * ((1.0 - u) ** 1.45) * 4.0 + head_nod * u
        cy = 13.0 + arch + wave
        if u < 0.35:
            hh = 1.1 + (u / 0.35) * 2.5
        elif u < 0.82:
            hh = 3.6 + math.sin((u - 0.35) / 0.47 * math.pi) * 1.1
        else:
            hh = 3.6 * max(0.36, (1.0 - u) / 0.18) ** 0.42
        for y in range(int(cy - hh), int(cy + hh) + 1):
            rel = (y - (cy - hh)) / max(1.0, hh * 2.0)
            sh = 5 if (rel < 0.16 and 0.40 < u < 0.86) else 3 if rel < 0.38 else 2 if rel < 0.68 else 4
            body[(x, y)] = sh
    head_y = int(round(13.0 + head_nod))
    # Crisp bottlenose beak (rostrum) extending cleanly forward on the RIGHT!
    for x in range(44, 51):
        body[(x, head_y - 1)] = 3 if x < 49 else 2
        body[(x, head_y)] = 2 if x < 50 else 4
        if x < 49:
            body[(x, head_y + 1)] = 4
    dors_y = int(round(7.4 + math.sin(ph + 0.45 * 3.4) * 1.2 + head_nod * 0.45))
    for dy in range(6):
        x0 = 28 - int(dy * 0.72)
        for dx in range(max(2, 6 - dy)):
            body[(x0 + dx, dors_y - dy)] = 3 if dx == 0 else 1
    pec_y = int(round(14.3 + math.sin(ph + 0.65 * 3.4) * 0.8 + head_nod * 0.65))
    for dy in range(5):
        for dx in range(max(2, 5 - dy)):
            body[(35 - dy + dx, pec_y + dy)] = 1
    # Horizontal flukes pitch dynamically with tail velocity (trailing edge lags behind stroke!)
    ty = 13.0 + math.sin(ph) * 4.0
    fluke_pitch = math.cos(ph) * 0.48
    for dy in range(-5, 6):
        sw = int(abs(dy) * 0.82 + dy * fluke_pitch)
        for dx in range(max(2, 4 - abs(dy) // 2)):
            body[(11 - sw - dx, int(round(ty + dy)))] = 1 if dy > 1 else 2
    img = _outline_and_fill(w, h, body, pal, outline=INK)
    px = img.load()
    _put(px, w, h, 42, head_y - 2, INK); _put(px, w, h, 43, head_y - 3, pal[5])
    return img


# ---- 6. LUSH GREEN SEA TURTLE (40 x 24, 10 figure-8 underwater-flight flipper frames, facing RIGHT!) ----
def _make_turtle(frame, total=10):
    w, h = 40, 24
    ph = (frame / total) * math.pi * 2.0
    pal = [
        INK,
        (34, 64, 42, 255),     # 1 dark olive shadow
        (74, 124, 68, 255),    # 2 sea-green skin mid
        (136, 188, 94, 255),   # 3 bright sunlit green
        (106, 98, 52, 255),    # 4 bronze carapace groove
        (176, 154, 76, 255),   # 5 golden-amber scute
        (234, 216, 128, 255),  # 6 sunlit carapace highlight
        (222, 206, 132, 255),  # 7 pale plastron belly
        (255, 255, 242, 255),  # 8 eye specular
    ]
    body = {}
    bob = math.sin(ph) * 0.8

    # 1. Hind rudder flipper gently undulating in back
    hx0, hy0 = 10.0, 12.2 + bob
    hind_ang = math.sin(ph - 1.2) * 0.35
    _paint_thick_seg(body, hx0, hy0, hx0 - 6.0, hy0 + 1.5 + hind_ang * 5.0, 1.5, 1.0, 3, 2, 1, 8)

    # 2. Far front flipper peeking slightly behind neck on upstroke
    up_far = math.sin(ph + 0.35)
    if up_far < 0.15:
        _paint_thick_seg(body, 26.5, 11.5 + bob, 24.0 + math.cos(ph) * 3.0, 9.0 + bob + up_far * 4.5, 1.4, 0.9, 2, 1, 1, 8)

    # 3. Domed hexagonal scute carapace (clean oval dome with warm amber/olive scutes!)
    cx, cy = 19.0, 11.0 + bob
    for dy in range(-6, 4):
        for dx in range(-10, 11):
            if (dx / 10.2) ** 2 + (dy / 6.2) ** 2 <= 1.0:
                ix, iy = int(round(cx + dx)), int(round(cy + dy))
                if dy >= 2:
                    sh = 7
                else:
                    # Crisp hexagonal scute borders across shell
                    is_seam = (dy == -1) or (abs(dx + (2 if dy < -1 else -1)) % 5 == 0 and dy < 2)
                    sh = 4 if is_seam else (6 if dy < -3 else 5 if dy < 1 else 4)
                body[(ix, iy)] = sh

    # 4. Outstretched curved turtle neck & expressive head
    head_bob = math.sin(ph - 0.6) * 0.7
    _paint_thick_seg(body, 28.0, 11.2 + bob, 33.5, 10.2 + bob + head_bob, 2.0, 2.3, 3, 2, 1, 8)

    # 5. HERO FORE-FLIPPER executing a REAL 10-phase figure-8 underwater "flight" stroke!
    # Forward-up reach -> deep sweeping power downstroke -> graceful feathered glide back!
    sh_x, sh_y = 26.2, 12.2 + bob
    # Figure-8 tip trajectory: x sweeps back on downstroke, forward on upstroke; y sweeps deep down then rises!
    tip_x = sh_x - 3.5 + math.cos(ph) * 5.2
    tip_y = sh_y + 2.8 + math.sin(ph) * 5.8
    mid_x = (sh_x + tip_x) * 0.5 + math.sin(ph) * 1.4
    mid_y = (sh_y + tip_y) * 0.5 + math.cos(ph) * 1.2
    _paint_thick_seg(body, sh_x, sh_y, mid_x, mid_y, 2.1, 1.8, 3, 2, 1, 10)
    _paint_thick_seg(body, mid_x, mid_y, tip_x, tip_y, 1.7, 0.9, 3, 2, 1, 10)

    img = _outline_and_fill(w, h, body, pal, outline=INK)
    px = img.load()
    ey = int(round(9.4 + bob + head_bob))
    _put(px, w, h, 34, ey, INK); _put(px, w, h, 33, ey - 1, pal[8])
    return img


# ---- 7. CHEEKY CORAL REEF OCTOPUS (34 x 28, 10 silky multi-arm undulating frames + natural eye blink!) ----
def _make_octopus(frame, total=10):
    w, h = 34, 28
    ph = (frame / total) * math.pi * 2.0
    pal = [
        INK,
        (138, 32, 26, 255),    # 1 deep crimson underside
        (218, 66, 38, 255),    # 2 coral-orange body
        (252, 126, 62, 255),   # 3 sunlit bright orange
        (255, 206, 134, 255),  # 4 glossy mantle highlight spots
        (255, 242, 136, 255),  # 5 golden eyes
        (255, 218, 184, 255),  # 6 cute pale suction cups
        (255, 255, 255, 255),  # 7 eye glint
    ]
    body = {}
    breath = math.sin(ph) * 0.65
    cx, cy = 17.0, 9.5 - breath * 0.6

    # 1. Six sinuous undulating curled tentacles with traveling outward waves & pale suction cups!
    arm_specs = [
        (-5.2, -1.05, 11.5, 0.0),
        (-3.2, -0.58, 12.8, 1.1),
        (-1.2, -0.18, 13.0, 2.2),
        ( 1.2,  0.18, 13.0, 3.3),
        ( 3.2,  0.58, 12.8, 4.4),
        ( 5.2,  1.05, 11.5, 5.5),
    ]
    for ox, spread, length, off in arm_specs:
        ax, ay = cx + ox, 13.5
        for s in range(15):
            u = s / 14.0
            # Wave travels outward along the tentacle; curl intensifies toward tip!
            curl = math.sin(ph - u * 4.2 + off) * (1.1 + u * 2.8)
            px0 = ax + spread * u * 8.5 + curl
            py0 = ay + u * length - (u * u * 2.2 * abs(spread))
            rad = 1.45 * (1.0 - u * 0.55)
            ir = int(math.ceil(rad))
            for dy in range(-ir, ir + 1):
                for dx in range(-ir, ir + 1):
                    if dx * dx + dy * dy <= (rad + 0.15) ** 2:
                        ix, iy = int(round(px0 + dx)), int(round(py0 + dy))
                        # Cute pale suction cups dotted along the inner underside of each curled arm!
                        if s % 3 == 1 and dy > 0 and u > 0.25 and u < 0.88:
                            sh = 6
                        else:
                            sh = 3 if (dy < 0 and u < 0.5) else 2 if dy <= 0 else 1
                        body[(ix, iy)] = sh

    # 2. Rounded bulbous breathing mantle dome (iterate exact integer pixels -> ZERO skipped banker's-rounding rows!)
    rx = 6.2 + breath * 0.45
    ry = 5.6 - breath * 0.35
    for iy in range(2, 18):
        for ix in range(9, 26):
            dx, dy = ix - cx, iy - cy
            if (dx / rx) ** 2 + (dy / ry) ** 2 <= 1.0:
                lit = (dy / ry) * -0.55 + (dx / rx) * 0.25
                sh = 3 if lit > 0.12 else 2 if lit > -0.25 else 1
                body[(ix, iy)] = sh
    # Glossy speckled mantle spots
    for sx, sy in ((cx - 2, cy - 3), (cx + 2, cy - 3), (cx + 3, cy - 1)):
        body[(int(round(sx)), int(round(sy)))] = 4

    img = _outline_and_fill(w, h, body, pal, outline=INK)
    px = img.load()
    # Expressive big golden eyes (with a natural cute blink on frame 8!)
    ey = int(round(cy + 2.2))
    blink = (frame == 8)
    for ex in (14, 19):
        if blink:
            _put(px, w, h, ex, ey, INK); _put(px, w, h, ex + 1, ey, INK)
        else:
            for dy in (0, 1):
                for dx in (0, 1):
                    _put(px, w, h, ex + dx, ey + dy, pal[5])
            _put(px, w, h, ex + 1, ey + 1, INK)
            _put(px, w, h, ex, ey, pal[7])
    return img


# ---- 8. TRANSLUCENT BIOLUMINESCENT JELLYFISH (26 x 40, 8 graceful medusa jet-pulse frames x pink/cyan!) ----
def _make_jellyfish(pink, frame, total=8):
    w, h = 26, 40
    ph = (frame / total) * math.pi * 2.0
    img, px = _new(w, h)
    if pink:
        rim  = (255, 234, 252, 238)
        lit  = (248, 154, 232, 198)
        mid  = (196, 86, 188, 155)
        deep = (132, 46, 148, 145)
        tent = (242, 168, 238, 188)
        t_lo = (182, 92, 196, 122)
    else:
        rim  = (224, 255, 255, 238)
        lit  = (118, 244, 252, 198)
        mid  = (46, 186, 212, 155)
        deep = (22, 118, 156, 145)
        tent = (138, 246, 255, 188)
        t_lo = (58, 174, 206, 122)

    cx = w // 2
    # Asymmetric organic medusa bell pulse: slow graceful expansion, crisp rhythmic contraction!
    pulse = math.sin(ph) + 0.22 * math.sin(2.0 * ph)
    rx = 7.6 - pulse * 1.45
    ry = 6.0 + pulse * 1.25
    cy = 9
    for y in range(1, cy + 4):
        for x in range(2, w - 2):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            if dy <= 0.16:
                d = dx * dx + dy * dy
                if d <= 1.0:
                    if d > 0.72 and dy < -0.08:
                        col = rim
                    elif abs(dy - 0.08) < 0.22:
                        col = rim if ((x + frame) % 3 != 0) else deep
                    elif d < 0.35 and dy < -0.25:
                        col = rim if ((x + y) % 2 == 0) else lit
                    else:
                        col = lit if dx < 0.22 else mid
                    px[x, y] = col
    # Frilled undulating inner oral curtain
    for y in range(cy + 1, cy + 9):
        for dx in (-3, -1, 1, 3):
            ox = int(round(math.sin(ph - (y - cy) * 0.55 + dx * 0.7) * 1.1))
            _put(px, w, h, cx + dx + ox, y, lit if y < cy + 4 else deep)
    # 5 delicate sinuous trailing tentacles with smooth downward traveling waves!
    for k, off in enumerate((-5.2, -2.6, 0.0, 2.6, 5.2)):
        tx0 = cx + off * (rx / 7.6)
        length = 21 + (k % 2) * 5 + (2 if k == 2 else 0)
        for i in range(length):
            wave = math.sin(ph - i * 0.30 + k * 1.25) * (1.1 + i * 0.09)
            _put(px, w, h, tx0 + wave, cy + 2 + i, tent if i < length * 0.6 else t_lo)
    return img


# ---- 9. ORNATE TREASURE CHEST (34 x 28, 5 smooth lid-opening frames: 0=closed .. 4=overflowing sparkle!) ----
def _make_chest(stage):
    w, h = 34, 28
    img, px = _new(w, h)
    c_d, c_w, c_l = (64, 34, 18, 255), (118, 66, 32, 255), (168, 102, 48, 255)
    c_o, c_g, c_Y = (158, 108, 22, 255), (236, 186, 44, 255), (255, 242, 144, 255)
    c_e, c_r, c_c = (46, 246, 168, 255), (255, 68, 138, 255), (128, 248, 255, 255)

    def box(x0, y0, bw, bh, col):
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                _put(px, w, h, x, y, col)

    # Smooth lid lift across 5 stages (0, 2, 4, 6, 8 px)
    lift = stage * 2
    # Back interior + glowing mound of gold doubloons & jewels revealed smoothly as lid lifts!
    if stage > 0:
        box(5, 14 - lift, 24, lift + 2, (34, 18, 10, 255))
        gh = min(6, lift + 1)
        box(6, 15 - gh, 22, gh, c_g)
        box(8, 15 - gh, 18, 2, c_Y)
        if stage >= 2:
            box(10, 15 - gh + 1, 3, 2, c_e); box(19, 15 - gh + 1, 3, 2, c_r)
        if stage >= 3:
            box(14, 15 - gh, 2, 2, c_c); box(23, 15 - gh + 1, 2, 2, c_e)
        if stage == 4:
            # Tiny diamond sparkle cross hovering over overflowing treasure!
            _put(px, w, h, 16, 4, c_Y); _put(px, w, h, 15, 5, c_c); _put(px, w, h, 16, 5, (255, 255, 255, 255)); _put(px, w, h, 17, 5, c_c); _put(px, w, h, 16, 6, c_Y)

    # Lower riveted galleon chest base (y = 14..26)
    box(3, 14, 28, 12, INK)
    box(4, 15, 26, 10, c_w); box(4, 16, 26, 2, c_l); box(4, 21, 26, 2, c_l); box(4, 23, 26, 2, c_d)
    box(4, 15, 2, 10, c_g); box(28, 15, 2, 10, c_g); box(4, 24, 26, 1, c_g); box(4, 15, 26, 1, c_g)
    # Ornate golden keyhole clasp
    box(14, 14, 6, 6, INK); box(15, 15, 4, 4, c_g); box(15, 15, 4, 1, c_Y); _put(px, w, h, 16, 17, INK); _put(px, w, h, 17, 17, INK)

    # Domed hinged lid rising cleanly by `lift` pixels!
    ly = 9 - lift
    box(4, ly, 26, 6, INK); box(5, ly + 1, 24, 4, c_w); box(5, ly + 1, 24, 2, c_l); box(5, ly + 4, 24, 1, c_d)
    box(5, ly + 1, 2, 4, c_g); box(27, ly + 1, 2, 4, c_g); box(5, ly + 1, 24, 1, c_Y)
    return img


# ---- 10. GIANT SCALLOPED PEARL CLAM (28 x 22, 5 smooth opening frames: 0=shut .. 4=wide glowing pearl!) ----
def _make_clam(stage):
    w, h = 28, 22
    img, px = _new(w, h)
    c_v, c_d, c_p, c_l, c_h = (28, 16, 48, 255), (62, 32, 92, 255), (118, 68, 162, 255), (184, 126, 224, 255), (234, 198, 252, 255)
    c_t, c_c, c_s, c_P, c_w = (24, 184, 192, 255), (122, 252, 248, 255), (146, 212, 236, 255), (214, 246, 255, 255), (255, 255, 255, 255)

    def box(x0, y0, bw, bh, col):
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                _put(px, w, h, x, y, col)

    gap = stage * 2
    # Lower scalloped shell cup (y = 14..20)
    box(3, 14, 22, 5, INK); box(4, 15, 20, 3, c_d); box(6, 15, 16, 2, c_p)
    for rx in (7, 11, 15, 19):
        _put(px, w, h, rx, 15, c_l); _put(px, w, h, rx + 1, 15, c_l)
    box(6, 19, 16, 2, INK); box(7, 19, 14, 1, c_d)

    # Interior cavity, undulating bioluminescent turquoise mantle & spherical pearl!
    if stage > 0:
        box(5, 14 - gap, 18, gap + 1, c_v)
        # Wavy glowing cyan mantle ruffle
        for x in range(5, 23):
            wy = 14 - (gap // 2) + int(round(math.sin(x * 0.9 + stage) * 0.8))
            _put(px, w, h, x, wy, c_c if x % 2 == 0 else c_t)
            _put(px, w, h, x, wy + 1, c_t)
        if stage >= 2:
            pr = 2 if stage == 2 else 3
            pcy = 13 - (gap // 2)
            for dy in range(-pr, pr + 1):
                for dx in range(-pr, pr + 1):
                    d = math.hypot(dx, dy)
                    if d <= pr + 0.35:
                        col = INK if d > pr - 0.35 else c_w if (dx < 0 and dy < 0) else c_P if dy <= 0 else c_s
                        _put(px, w, h, 14 + dx, pcy + dy, col)
            if stage == 4:
                _put(px, w, h, 12, pcy - 2, c_w); _put(px, w, h, 14, pcy - 4, c_w)

    # Upper scalloped fan shell dome lifting cleanly by `gap` pixels!
    uy = 9 - gap
    for x in range(3, 25):
        u = (x - 14) / 11.0
        scallop = abs(math.sin((x - 3) * 0.55)) * 1.4
        top_y = uy + int(round(u * u * 3.8 - scallop))
        _put(px, w, h, x, top_y - 1, INK)
        for y in range(top_y, uy + 6):
            is_rib = (x % 4 in (0, 1))
            col = c_h if y == top_y else (c_l if is_rib and y < uy + 3 else c_p if y < uy + 4 else c_d)
            _put(px, w, h, x, y, col)
        _put(px, w, h, x, uy + 6, INK)
    return img


# ---- 11. TROPICAL REEF FISH (20 x 14, 6 smooth caudal-wave + fin-flutter frames x 3 species, facing RIGHT!) ----
def _make_fish(kind, frame, total=6):
    w, h = 20, 14
    ph = (frame / total) * math.pi * 2.0
    wag = math.sin(ph) * 1.6
    fin_f = math.sin(ph + 1.2) > 0
    if kind == 'teal':
        pal = [INK, (18, 108, 128, 255), (40, 188, 198, 255), (136, 248, 242, 255), (214, 92, 22, 255), (255, 178, 48, 255), (255, 236, 134, 255), (255, 255, 255, 255)]
        rx, ry = 5.4, 3.8
    elif kind == 'crimson':
        pal = [INK, (128, 22, 58, 255), (222, 52, 98, 255), (255, 138, 178, 255), (255, 236, 246, 255), (255, 236, 246, 255), (255, 255, 255, 255), (255, 255, 255, 255)]
        rx, ry = 4.6, 3.2
    else:
        pal = [INK, (184, 58, 14, 255), (255, 114, 24, 255), (255, 196, 82, 255), (255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255)]
        rx, ry = 4.8, 3.4

    body = {}
    cx, cy = 11.5, 7.0
    # Flowing 6-phase animated forked/fan tail on left!
    tx0 = int(round(cx - rx))
    for dx in range(5):
        frac = dx / 4.0
        spread = 1.0 + frac * (2.6 if kind == 'teal' else 2.0)
        ty = cy + wag * (0.4 + frac * 0.8)
        for dy in range(-4, 5):
            if abs(dy) <= spread and not (kind == 'teal' and dx == 4 and abs(dy) < 1.2):
                sh = 6 if (kind == 'teal' and abs(dy) > spread - 1.1) else 5 if kind == 'teal' else 2 if abs(dy) < spread - 0.5 else 1
                body[(tx0 - dx, int(round(ty + dy)))] = sh
    # Dorsal fin crest
    for dx in range(-3, 3):
        dh = 2 if (dx > -2 and dx < 2) else 1
        for dy in range(dh):
            body[(int(round(cx + dx)), int(round(cy - ry - dy)))] = 5 if kind == 'teal' else 3
    # Curved teardrop fish body
    for dy in range(-5, 6):
        for dx in range(-6, 7):
            if (dx / rx) ** 2 + (dy / ry) ** 2 <= 1.0:
                ix, iy = int(round(cx + dx)), int(round(cy + dy))
                if kind == 'teal':
                    sh = 3 if dy < -1 else 2 if dy < 2 else 1
                elif kind == 'crimson':
                    sh = 4 if (dx in (-2, 1)) else (3 if dy < -1 else 2 if dy < 2 else 1)
                else:
                    # Plump clownfish with crisp white vertical bands!
                    sh = 4 if (dx in (-2, 2)) else (3 if dy < -1 else 2 if dy < 2 else 1)
                body[(ix, iy)] = sh
    # Fluttering side pectoral fin
    if kind == 'teal':
        body[(int(round(cx)), int(round(cy + (1 if fin_f else 2))))] = 4
        body[(int(round(cx - 1)), int(round(cy + (1 if fin_f else 2))))] = 5

    img = _outline_and_fill(w, h, body, pal, outline=INK)
    px = img.load()
    ex, ey = int(round(cx + rx - 2.2)), int(round(cy - 0.5))
    _put(px, w, h, ex, ey, INK); _put(px, w, h, ex - 1, ey - 1, pal[7])
    return img


def build_sprites():
    """Return an ordered dict of `{sprite_name: PIL.Image}` with full 6-to-12-frame biomechanical motion cycles."""
    sprites = {}
    directional = []
    for f in range(COUNTS['diver']):
        directional.append((f'diver_{f}', _make_diver(f, COUNTS['diver'])))
    for f in range(COUNTS['whale']):
        directional.append((f'whale_{f}', _make_whale(f, COUNTS['whale'])))
    for f in range(COUNTS['manta']):
        directional.append((f'manta_{f}', _make_manta(f, COUNTS['manta'])))
    for f in range(COUNTS['shark']):
        directional.append((f'shark_{f}', _make_shark(f, COUNTS['shark'])))
    for f in range(COUNTS['dolphin']):
        directional.append((f'dolphin_{f}', _make_dolphin(f, COUNTS['dolphin'])))
    for f in range(COUNTS['turtle']):
        directional.append((f'turtle_{f}', _make_turtle(f, COUNTS['turtle'])))
    for kind in ('teal', 'crimson', 'clown'):
        for f in range(COUNTS['fish']):
            directional.append((f'fish_{kind}_{f}', _make_fish(kind, f, COUNTS['fish'])))

    for name, img in directional:
        sprites[f'{name}_r'] = img
        sprites[f'{name}_l'] = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    for f in range(COUNTS['octo']):
        sprites[f'octo_{f}'] = _make_octopus(f, COUNTS['octo'])
    for f in range(COUNTS['jelly']):
        sprites[f'jelly_pink_{f}'] = _make_jellyfish(True, f, COUNTS['jelly'])
        sprites[f'jelly_cyan_{f}'] = _make_jellyfish(False, f, COUNTS['jelly'])
    for f in range(COUNTS['chest']):
        sprites[f'chest_{f}'] = _make_chest(f)
    for f in range(COUNTS['clam']):
        sprites[f'clam_{f}'] = _make_clam(f)
    return sprites
