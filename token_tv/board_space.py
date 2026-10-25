"""Page 7 of the touch board: the cockpit, two glass orbs in deep space (320x240).

Two quota instruments float over a detailed nebula, with a galaxy, a ringed planet and an occasional UFO.

- The backdrop is a nebula built from layered smooth noise (violet, magenta, teal and blue gas, dark dust lanes), a
  small spiral galaxy and a fixed starfield, all deterministic and cached. It stays dim around the readings.
- Each gauge is a glass orb: dark and quiet in the middle for the number, a lit rim, a highlight and an aura. The
  weekly quota left is the luminous band around it (270 degrees, 10 % steps), Codex yellow and Claude stone. Claude's
  five-hour session is the two thin five-part rings between the orb and the band, only from a fresh reading.
- Three rockets under each name are the saved resets. Unknown is `--`, never zero.

The board animates a small UFO and twinkling stars through ANIM; older firmware keeps the STAR fallback.
Nothing here depends on the time of day: the page changes only when a reading does.
Colours stay Codex yellow and Claude stone, no traffic-light colours on this page.
"""
import functools
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from token_tv import board_anim

from token_tv.board_art import (CLAUDE, CODEX, DIM, MUTED, RAMP, SS, WHITE, H, W, Scene, _resets, _hex, _mix, _rgb,
                                _row, _session_rings)
from token_tv.display import pixel_text  # noqa: F401  (kept for parity with the other pages' helpers)
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

CENTRES = {'codex': (82, 100), 'claude': (238, 100)}
BAND_RADIUS = 58                      # the weekly band is 48-58 px from the centre (width 10)
ORB_RADIUS = 30
LABEL = '#a9c5e1'                     # small labels: brighter than the other pages' MUTED, because the sky is brighter
STAR_TINTS = (('#6f8fb0', 5), ('#8fb0d0', 5), ('#c4daf2', 4), ('#ffffff', 2), ('#d8cfff', 1), ('#ffe2b8', 1))


def _smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _fbm(seed, width, height, grid=(4, 3), octaves=5, persistence=.56):
    """Smooth fractal noise as an 'L' image: octaves of random grids, each up-scaled with a bicubic filter."""
    rnd = random.Random(seed)
    layers = []
    for octave in range(octaves):
        gw, gh = grid[0] * 2 ** octave, grid[1] * 2 ** octave
        data = bytes(rnd.randrange(256) for _ in range(gw * gh))
        layers.append((Image.frombytes('L', (gw, gh), data).resize((width, height), Image.Resampling.BICUBIC),
                       persistence ** octave))
    total = sum(weight for _, weight in layers)
    out = None
    for layer, weight in layers:
        part = layer.point([round(v * weight / total) for v in range(256)])
        out = part if out is None else ImageChops.add(out, part)
    return out


def _band(noise, low, high):
    """Cloud-like mask: the noise is clear below `low` and solid above `high` (soft edge between)."""
    return noise.point([round(255 * _smoothstep((v - low) / (high - low))) for v in range(256)])


def _blob(size, boxes, blur):
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.ellipse(box, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def _scale(mask, factor):
    return mask.point([round(v * factor) for v in range(256)])


@functools.lru_cache(maxsize=1)
def _nebulae():
    """The painted deep-space picture at drawing scale, RGB, without any star."""
    size = (W * SS, H * SS)
    sky = Image.new('RGB', size)
    px = sky.load()
    top, bottom = _rgb('#02030b'), _rgb('#050a1c')
    for y in range(size[1]):
        t = y / (size[1] - 1)
        row = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(size[0]):
            px[x, y] = row
    # (seed, colour, lower threshold, upper threshold, strength, where it lives)
    clouds = (
        (11, '#4a33c4', 84, 160, 1.0, [(-140, 0, 380, 340), (120, 290, 540, 540)]),        # violet-blue, left
        (23, '#c02f93', 92, 162, .95, [(300, -110, 780, 270), (420, 180, 720, 340)]),      # magenta, upper right
        (37, '#16a0b4', 96, 168, .85, [(230, 320, 720, 580), (-60, 340, 220, 540)]),       # teal, low
        (51, '#3a66e0', 100, 172, .70, [(100, -90, 480, 170)]),                            # blue, top
        (63, '#d8602e', 120, 176, .42, [(470, 290, 700, 480), (-30, 130, 150, 300)]),      # a little ember-orange
    )
    for seed, colour, low, high, strength, boxes in clouds:
        mask = _band(_fbm(seed, *size, grid=(3, 2)), low, high)
        mask = ImageChops.multiply(mask, _blob(size, boxes, 70))
        mask = _scale(mask, strength)
        sky = Image.composite(Image.new('RGB', size, colour), sky, mask)
        # a brighter, tighter core inside the thickest gas
        core = _scale(_band(_fbm(seed + 1, *size, grid=(4, 3)), 140, 205), .6)
        core = ImageChops.multiply(core, mask)
        # thin bright filaments where the gas is thick: contour lines of a second noise ("ridged" noise)
        ridged = _fbm(seed + 2, *size, grid=(6, 4), octaves=6).point([round(255 * (1 - abs(2 * v / 255 - 1))) for v in range(256)])
        wisps = _scale(ImageChops.multiply(_band(ridged, 224, 250), mask), .58)
        sky = Image.composite(Image.new('RGB', size, _hex(_mix(colour, '#ffffff', .5))), sky, wisps)
        sky = Image.composite(Image.new('RGB', size, _hex(_mix(colour, '#ffeaf8', .6))), sky, _scale(core, .9))
    dust = _scale(_band(_fbm(77, *size, grid=(3, 2), octaves=6), 120, 190), .62)       # dark lanes cut through the gas
    lanes = Image.merge('RGB', [dust.point([255 - v for v in range(256)])] * 3)
    sky = ImageChops.multiply(sky, lanes)
    # keep the nebula quiet where text lives: under the gauges (names, resets, hearts) and the title row
    calm = Image.new('L', size, 255)
    calmd = ImageDraw.Draw(calm)
    calmd.rectangle((0, 0, size[0], 26 * SS), fill=105)
    calmd.rectangle((14 * SS, 150 * SS, 306 * SS, size[1]), fill=82)
    calm = calm.filter(ImageFilter.GaussianBlur(12 * SS))
    return ImageChops.multiply(sky, Image.merge('RGB', [calm] * 3))


def _galaxy(image, cx, cy):
    """A small tilted spiral galaxy: a soft disc, a bright core and two faint arms."""
    size = (60 * SS, 30 * SS)
    layer = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    mid = (size[0] // 2, size[1] // 2)
    for k, (rx, ry, a) in enumerate(((26, 8, 28), (20, 6, 44), (13, 4, 70), (7, 2.4, 110))):
        d.ellipse((mid[0] - rx * SS, mid[1] - ry * SS, mid[0] + rx * SS, mid[1] + ry * SS), fill=(176, 190, 255, a))
    for sign in (-1, 1):                                                       # two arms as short bright arcs
        pts = []
        for i in range(24):
            t = i / 23
            ang = math.pi * (.15 + 1.1 * t)
            r = (4 + 22 * t) * SS
            pts.append((mid[0] + sign * math.cos(ang) * r, mid[1] + sign * math.sin(ang) * r * .34))
        d.line(pts, fill=(214, 224, 255, 70), width=SS)
    d.ellipse((mid[0] - 3 * SS, mid[1] - 1.5 * SS, mid[0] + 3 * SS, mid[1] + 1.5 * SS), fill=(255, 244, 224, 230))
    layer = layer.filter(ImageFilter.GaussianBlur(SS * .65))
    d = ImageDraw.Draw(layer)
    rnd = random.Random(805)
    for sign in (-1, 1):
        for i in range(95):
            t = rnd.random()
            ang = math.pi*(.15+1.1*t)+rnd.uniform(-.14,.14)
            r = (4+22*t)*SS
            x = mid[0]+sign*math.cos(ang)*r
            y = mid[1]+sign*math.sin(ang)*r*.34
            d.point((round(x),round(y)),fill=(190,217,255,rnd.randrange(80,210)))
    layer = layer.rotate(-16, resample=Image.Resampling.BICUBIC, expand=True)
    image.alpha_composite(layer, (cx * SS - layer.width // 2, cy * SS - layer.height // 2))


def _ringed_planet(image):
    """An icy world in the gap between the instruments, lit from upper left."""
    cx, cy, radius = 160 * SS, 216 * SS, 14 * SS
    layer = Image.new('RGBA', image.size)
    d = ImageDraw.Draw(layer)
    rings = (cx - 23 * SS, cy - 6 * SS, cx + 23 * SS, cy + 6 * SS)
    d.ellipse(rings, outline='#467d9e', width=2 * SS)
    d.ellipse((rings[0]+2*SS, rings[1]+SS, rings[2]-2*SS, rings[3]-SS), outline='#8bbed0', width=SS)
    px = layer.load()
    for y in range(cy-radius, cy+radius+1):
        for x in range(cx-radius, cx+radius+1):
            nx, ny = (x-cx)/radius, (y-cy)/radius
            rr = nx*nx+ny*ny
            if rr > 1: continue
            nz = math.sqrt(1-rr)
            light = max(0, -.6*nx-.5*ny+.6*nz)
            bands = .5+.5*math.sin(ny*25+math.sin(nx*4)*.65)
            limb = (1-nz)**3
            px[x,y] = (round(9+42*light+12*bands*light),
                       round(17+101*light+17*bands*light+15*limb),
                       round(32+136*light+15*bands*light+24*limb),255)
    # The front half occludes the world, with a thin dark Cassini division.
    d.arc(rings, 0, 180, fill='#c0dfdc', width=2*SS)
    d.arc((rings[0]+2*SS,rings[1]+SS,rings[2]-2*SS,rings[3]-SS),0,180,fill='#30536d',width=SS)
    image.alpha_composite(layer)


def _in_calm_zone(x, y):
    """Where a star would sit under a gauge, its labels or the title row: no stars are made there."""
    if y < 15 or (x > 218 and y > 218):
        return True
    return any(math.hypot(x - cx, y - cy) < BAND_RADIUS + 17 for cx, cy in CENTRES.values()) or \
        (155 <= y <= 224 and (28 <= x <= 136 or 184 <= x <= 292))


@functools.lru_cache(maxsize=1)
def star_field():
    """The fixed twinkling starfield as (x, y, colour, wide) at drawing scale: one star per final pixel."""
    rnd = random.Random(19)
    tints = [c for c, n in STAR_TINTS for _ in range(n)]
    stars, taken = [], []
    while len(stars) < 230:
        x, y = rnd.randrange(4, W - 4), rnd.randrange(4, H - 4)
        if _in_calm_zone(x, y) or any(abs(x - a) < 5 and abs(y - b) < 5 for a, b in taken):
            continue
        taken.append((x, y))
        stars.append((x * SS, y * SS, rnd.choice(tints), rnd.random() >= .78))
    return tuple(stars)


# A few big stars with spikes, drawn into the backdrop (they do not twinkle).
FEATURE_STARS = ((22, 50, '#fff3d6', 5), (304, 56, '#d6e8ff', 6), (150, 214, '#ffe9c4', 4), (12, 196, '#d6e0ff', 4),
                 (307, 154, '#fff0e0', 4))


@functools.lru_cache(maxsize=1)
def space_backdrop():
    """Nebulae, a galaxy, the twinkling field and a few bright stars, as an RGBA drawing-scale image (cached)."""
    img = _nebulae().convert('RGBA')
    _galaxy(img, 160, 27)
    draw = ImageDraw.Draw(img)
    for x, y, color, wide in star_field():
        draw.rectangle((x, y, x + (2 if wide else 1), y + 1), fill=color)
    glow = Image.new('RGBA', img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for x, y, color, reach in FEATURE_STARS:
        cx, cy, r = x * SS, y * SS, reach * SS
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_rgb(color) + (95,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3 * SS)))
    draw = ImageDraw.Draw(img)
    for x, y, color, reach in FEATURE_STARS:
        cx, cy = x * SS, y * SS
        for dx, dy, length in ((1, 0, .62), (-1, 0, .62), (0, 1, 1.0), (0, -1, 1.0)):
            span = round(reach * SS * 1.5 * length)
            for k in range(1, span):
                fade = 1 - k / span
                alpha = round(235 * fade ** 2.2)
                draw.point((cx + dx * k, cy + dy * k), fill=_rgb(color) + (alpha,))
                if k < span // 3:                                  # arms are two pixels thick near the core
                    draw.point((cx + dx * k + dy, cy + dy * k + dx), fill=_rgb(color) + (alpha // 2,))
        draw.rectangle((cx - 1, cy - 1, cx + 1, cy + 1), fill='#ffffff')
    _ringed_planet(img)
    return img


def _orb(scene, cx, cy, radius, accent):
    """A glass orb lit from the upper left: quiet and dark in the middle, a bright limb, a highlight and an aura."""
    px = scene.ink.load()
    R, ox, oy = radius * SS, cx * SS, cy * SS
    light = (-.52, -.62, .59)
    length = math.sqrt(sum(v * v for v in light))
    light = tuple(v / length for v in light)
    tone = _rgb(accent)
    rim_tone = tuple(min(255, c + 55) for c in tone)
    deep = (6, 12, 28)
    for y in range(int(oy - R) - 1, int(oy + R) + 2):
        for x in range(int(ox - R) - 1, int(ox + R) + 2):
            dx, dy = (x + .5 - ox) / R, (y + .5 - oy) / R
            rr = dx * dx + dy * dy
            if rr >= 1:
                continue
            nz = math.sqrt(1 - rr)
            lam = max(0.0, dx * light[0] + dy * light[1] + nz * light[2])
            fres = (1 - nz) ** 2.3
            spec = max(0.0, 1 - math.hypot(dx + .43, dy + .47) / .26) ** 2
            bands = .5 + .5 * math.sin(dy * 20 + math.sin(dx * 5.2) * 1.8)
            storms = (.5 + .5 * math.sin(dx * 22 + dy * 17)) * bands
            colour = [deep[i] + tone[i] * (.10 * lam + (.035 * bands + .045 * storms) * lam) + rim_tone[i] * fres * (.30 + 1.05 * lam) + 255 * .6 * spec
                      for i in range(3)]
            edge = min(1.0, (1 - math.sqrt(rr)) * R)
            px[x, y] = tuple(min(255, round(v)) for v in colour) + (round(238 * edge),)
    aura = scene.g
    for grow, alpha in ((1.5, 120), (3.5, 60)):
        r = (radius + grow) * SS
        aura.ellipse((ox - r, oy - r, ox + r, oy + r), outline=tone + (alpha,), width=SS)
    # a thin crisp crescent of light along the lit limb
    scene.d.arc((ox - R + SS, oy - R + SS, ox + R - SS, oy + R - SS), 195, 265, fill=rim_tone + (230,), width=SS)


def _dashed(scene, cx, cy, radius, colour, dash=3, gap=3):
    for a in range(0, 360, dash + gap):
        scene.arc((cx, cy), radius, a, dash, 1, colour, glow=False)


def _band_edges(scene, cx, cy, accent):
    """Fine lines along both edges of the weekly track, so the band reads as a lit channel."""
    for r, strength in ((BAND_RADIUS + .6, .55), (BAND_RADIUS - 9.6, .35)):
        scene.arc((cx, cy), r, 135, 270, 1, _hex(_mix('#0c1830', accent, strength)), glow=False)


def _gauge(scene, provider, value, banked, pace, reset, accent):
    cx, cy = CENTRES[provider]
    sweep, start = 270, 135
    ramp = RAMP[provider]
    _dashed(scene, cx, cy, BAND_RADIUS + 15, '#1a2f55')
    for k in range(21):
        a = math.radians(start + sweep * k / 20)
        major = k % 2 == 0
        r0, r1 = BAND_RADIUS + 5, BAND_RADIUS + (13 if k % 10 == 0 else 10 if major else 8)
        scene.line((cx + math.cos(a) * r0, cy + math.sin(a) * r0), (cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                   WHITE if k % 10 == 0 else MUTED if major else '#32486a', 1)
    scene.arc((cx, cy), BAND_RADIUS, start, sweep, 10, DIM, glow=False)             # the empty track
    _band_edges(scene, cx, cy, accent)
    if value is not None and value > 0:
        end_t = max(.02, value / 100)
        scene.arc((cx, cy), BAND_RADIUS, start, sweep * end_t, 10,
                  lambda t: _hex(_mix(ramp[0], ramp[1], t)), steps=int(sweep * end_t / 2) + 2)
        scene.arc((cx, cy), BAND_RADIUS - 2.5, start, sweep * end_t, 1, _hex(_mix(ramp[1], '#ffffff', .55)), glow=False)
        a = math.radians(start + sweep * end_t)
        mid = BAND_RADIUS - 5                                    # arcs are drawn inwards: the band's centre is 5 px in
        scene.dot((cx + math.cos(a) * mid, cy + math.sin(a) * mid), 7, WHITE)
    _orb(scene, cx, cy, ORB_RADIUS, accent)
    if provider == 'claude':
        _session_rings(scene, cx, cy, BAND_RADIUS - 1, pace, accent)
    number = '--' if value is None else f'{round(value)}'
    scene.text((cx, cy - 3), number, 'oxanium.woff2', 31, WHITE, anchor='mm', glow=True)
    scene.text((cx, cy + 20), '%' if value is not None else '?', 'press-start-2p.ttf', 7, accent, anchor='mm')
    # name flanked by two short rules, then the weekly reset and the saved resets
    name = provider.upper()
    half = face('orbitron.ttf', 14 * SS).getlength(name) / SS / 2
    ruled = _hex(_mix('#0b1830', accent, .5))
    scene.line((cx - half - 30, cy + BAND_RADIUS + 19), (cx - half - 8, cy + BAND_RADIUS + 19), ruled, 1)
    scene.line((cx + half + 8, cy + BAND_RADIUS + 19), (cx + half + 30, cy + BAND_RADIUS + 19), ruled, 1)
    scene.text((cx, cy + BAND_RADIUS + 19), name, 'orbitron.ttf', 14, accent, anchor='mm', glow=True)
    scene.text((cx, cy + BAND_RADIUS + 36), 'RESET ' + reset.upper(), 'oxanium.woff2', 13, LABEL, anchor='mm')
    count, old = banked
    _resets(scene, cx, cy + BAND_RADIUS + 46, count, old, accent, LABEL, 'rocket')


def _divider(scene):
    """A vertical hairline that fades out at both ends."""
    for y in range(34, 212):
        t = (y - 34) / 177
        alpha = round(150 * math.sin(math.pi * t) ** 1.5)
        scene.d.line((160 * SS, y * SS, 160 * SS, (y + 1) * SS), fill=_rgb('#2a4574') + (alpha,), width=SS)


def _ufo():
    """A brief flyby across clear sky; a dim approach and departure, then a pause."""
    frames = []
    for phase in range(3):
        im = Image.new('RGBA', (14, 7))
        d = ImageDraw.Draw(im)
        d.ellipse((5, 0, 9, 4), fill='#427eaa', outline='#b2edf0')
        d.point((6, 1), fill='#f6fff4')
        d.ellipse((1, 2, 13, 5), fill='#465c81', outline='#a1ced7')
        d.line((3, 3, 11, 3), fill='#e0edf4')
        d.line((4, 5, 10, 5), fill='#177898')
        for x in (4, 7, 10):
            d.point((x, 4), fill='#91fff3' if (x+phase)%2 else '#ffb5dd')
        d.line((5, 6, 9, 6), fill='#54cdd1' if phase == 1 else '#327f9f')
        if phase == 0:
            # RGB dimming, not semi-transparent pixels (the native key is binary).
            im = Image.merge('RGBA', [im.getchannel(c).point(lambda v: round(v*.42)) for c in 'RGB']+[im.getchannel('A')])
        frames.append(im)
    frames.append(Image.new('RGBA', (14, 7)))
    script = []
    for i in range(32):
        t = min(i,23)/23
        frame = (0 if i < 2 or i > 21 else 1+i%2) if i < 24 else 3
        script.append((frame, round(-28+56*t), round(6*math.sin(math.pi*t))))
    return {'x':146,'y':16,'frames':frames,'script':script,'step_ms':140}


def render_cockpit(snapshot, animated=False):
    scene = Scene(space_backdrop)
    scene.text((12, 7), 'DEEP SPACE', 'press-start-2p.ttf', 6, LABEL)
    scene.text((308, 7), 'WEEKLY REMAINING', 'press-start-2p.ttf', 6, LABEL, anchor='ra')
    _divider(scene)
    for provider, accent in (('codex', CODEX), ('claude', CLAUDE)):
        row = _row(snapshot, provider)
        value, _, _, reset = remaining_reading(row)
        pace = session_pace(row) if provider == 'claude' else None   # only Claude has a five-hour session
        _gauge(scene, provider, value, banked_hearts(row), pace, reset, accent)
    image = scene.finish()
    sprite = _ufo()
    if not animated:
        frame, dx, dy = sprite['script'][0]
        pose = sprite['frames'][frame].resize((28,14),Image.Resampling.NEAREST)
        image.paste(pose,(sprite['x']+dx,sprite['y']+dy),pose)
        return image
    from token_tv.board_art import free_stars
    # Native sprites restore their entire movement rectangle; twinkling there
    # would paint over the ship. Keep the two animation systems disjoint.
    candidates = [(x,y,c) for x,y,c in free_stars(image,backdrop=space_backdrop,field=star_field)
                  if not (114 <= x <= 206 and 12 <= y <= 42)
                  and not (136 <= x <= 184 and 198 <= y <= 234)]
    stars = [(x,y,c,board_anim.rgb565((215,239,255)),board_anim.rgb565((38,57,86)))
             for x,y,c in candidates[::max(1,len(candidates)//48)][:48]]
    return image, board_anim.encode([sprite],stars)
