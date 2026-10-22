"""Shared scene helpers for the touch board's smooth showpiece pages (320x240).

The cockpit (page 7) is drawn in `board_space.py` and the countdown (page 8) in `board_city.py`, both with these
helpers; the `render_*` functions here only forward.

Drawn at twice the size with glow and reduced, so arcs and text have soft edges.
Same rules as every other page: unknown stays `--` and Claude's session is drawn only
from a fresh reading. Nothing here changes with the time of day, so the page changes
only when a reading does (the board's flash is not rewritten every minute).
"""
import functools
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from token_tv.display import overview_rows
from token_tv import board_reset_icons as icons
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

W, H, SS = 320, 240, 2
# One colour family per provider on every showpiece screen: Codex yellow, Claude stone.
CODEX, CLAUDE = '#ffd23f', '#cfc6b4'
RAMP = {'codex': ('#c98f00', '#fff1a0'), 'claude': ('#8a8274', '#f1ece0')}   # ring gradients, dark to light
STONE_QUOTA, STONE_TIME = '#f4efe4', '#8d8577'   # Claude's two thin five-hour rings
MUTED, WHITE, DIM = '#6f8fb0', '#eaf4ff', '#1b2c44'


def _row(snapshot, provider):
    for row in overview_rows(snapshot):
        if row['provider'] == provider:
            return row
    return {'provider': provider, 'alias': provider.upper(), 'status': 'auth_required', 'windows': []}


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(rgb)


def _mix(a, b, t):
    a, b = _rgb(a), _rgb(b)
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def band_color(remaining):
    """Green when plenty is left, amber when low, red when nearly spent; dim when unknown."""
    if remaining is None:
        return '#3a4a5c'
    if remaining >= 50:
        return '#3dfcb0'
    if remaining >= 20:
        return '#ffc23d'
    return '#ff4a5e'


STAR_COLORS = ('#8fb0d0', '#c4daf2', '#ffffff', '#6f8fb0')
STAR_COUNT = 130


@functools.lru_cache(maxsize=1)
def _star_field():
    """The fixed starfield as (x, y, colour, wide) at drawing scale: the same stars every time.

    Each star sits exactly on one pixel of the final image: half-way between two they came out
    as two faint pixels, too dim to see (or to make twinkle).
    """
    rnd = random.Random(7)
    stars = []
    for _ in range(STAR_COUNT):
        x, y = rnd.randrange(W) * SS, rnd.randrange(H) * SS
        stars.append((x, y, rnd.choice(STAR_COLORS), rnd.random() >= .8))
    return tuple(stars)


@functools.lru_cache(maxsize=1)
def _backdrop():
    """Deep-blue gradient, a soft vignette and a fixed starfield (cached: it never changes)."""
    top, bottom = _rgb('#030812'), _rgb('#0b1c38')
    img = Image.new('RGB', (W * SS, H * SS))
    px = img.load()
    for y in range(H * SS):
        t = y / (H * SS - 1)
        row = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(W * SS):
            px[x, y] = row
    d = ImageDraw.Draw(img)
    for x, y, color, wide in _star_field():
        d.rectangle((x, y, x + (2 if wide else 1), y + 1), fill=color)
    return img.convert('RGBA')


FLARE = ((0, 0), (-2, 0), (-1, 0), (1, 0), (2, 0), (0, -2), (0, -1), (0, 1), (0, 2))   # a star and its cross


def free_stars(image, limit=128, backdrop=None, field=None):
    """Stars of the field that nothing was drawn over, as (x, y, rgb565): the board makes them twinkle.

    Compared with the bare backdrop, so a star under a ring, its glow or any text is left alone. The
    board flares a star as a cross two pixels long each way (firmware 5; older firmware only
    changes the star's own pixel), so the whole cross must be free and no two crosses may touch.
    `backdrop` and `field` (callables) name another page's sky; the default is the countdown's.
    """
    base = (backdrop or _backdrop)().resize((W, H), Image.Resampling.LANCZOS).convert('RGB')
    image = image.convert('RGB')
    chosen, taken = [], set()
    for sx, sy, _, _ in (field or _star_field)():
        x, y = sx // SS, sy // SS
        if not 2 <= x < W - 2 or not 2 <= y < H - 2 or x > 218 and y > 218:   # nor under the page marker
            continue
        cross = [(x + dx, y + dy) for dx, dy in FLARE]
        if any(p in taken for p in cross):
            continue
        here, beside = base.getpixel((x, y)), base.getpixel((min(W - 1, x + 3), y))
        if sum(here) < sum(beside) + 40:                    # not really a star at this scale
            continue
        if any(abs(a - b) > 6 for p in cross for a, b in zip(base.getpixel(p), image.getpixel(p))):
            continue                                        # something covers it, or would be flared over
        taken.update(cross)
        r, g, b = image.getpixel((x, y))
        chosen.append((x, y, ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)))
    return chosen[:limit]


class Scene:
    """A supersampled canvas with a glow layer, finished into a 320x240 RGB image."""

    def __init__(self, backdrop=None):
        self.base = (backdrop or _backdrop)().copy()
        self.glow = Image.new('RGBA', self.base.size, (0, 0, 0, 0))
        self.ink = Image.new('RGBA', self.base.size, (0, 0, 0, 0))
        self.g = ImageDraw.Draw(self.glow)
        self.d = ImageDraw.Draw(self.ink)

    def arc(self, center, radius, start, sweep, width, color, glow=True, steps=None):
        """Arc from `start` degrees (0 = 3 o'clock, clockwise) over `sweep` degrees; colour may be a callable of 0..1."""
        cx, cy = center[0] * SS, center[1] * SS
        r, w = radius * SS, width * SS
        box = (cx - r, cy - r, cx + r, cy + r)
        if sweep <= 0:
            return
        if not callable(color):
            for layer, draw in ((self.glow, self.g), (self.ink, self.d)):
                if layer is self.glow and not glow:
                    continue
                draw.arc(box, start, start + sweep, fill=color, width=w)
            return
        n = steps or max(2, int(sweep / 2))
        for i in range(n):
            a0 = start + sweep * i / n
            a1 = start + sweep * (i + 1) / n + 0.6
            c = color((i + .5) / n)
            self.d.arc(box, a0, a1, fill=c, width=w)
            if glow:
                self.g.arc(box, a0, a1, fill=c, width=w)

    def dot(self, xy, radius, color, glow=True):
        x, y, r = xy[0] * SS, xy[1] * SS, radius * SS
        self.d.ellipse((x - r, y - r, x + r, y + r), fill=color)
        if glow:
            self.g.ellipse((x - r * 1.4, y - r * 1.4, x + r * 1.4, y + r * 1.4), fill=color)

    def hollow(self, xy, radius, color, width=1):
        x, y, r = xy[0] * SS, xy[1] * SS, radius * SS
        self.d.ellipse((x - r, y - r, x + r, y + r), outline=color, width=max(1, round(width * SS)))

    def line(self, a, b, color, width=1, glow=False):
        pts = (a[0] * SS, a[1] * SS, b[0] * SS, b[1] * SS)
        self.d.line(pts, fill=color, width=max(1, round(width * SS)))
        if glow:
            self.g.line(pts, fill=color, width=max(1, round(width * SS)))

    def text(self, xy, text, font, size, color, anchor='la', glow=False):
        f = face(font, size * SS)
        self.d.text((xy[0] * SS, xy[1] * SS), text, font=f, fill=color, anchor=anchor)
        if glow:
            self.g.text((xy[0] * SS, xy[1] * SS), text, font=f, fill=color, anchor=anchor)

    def rect(self, box, fill=None, outline=None, width=1, glow=False, radius=0):
        b = tuple(v * SS for v in box)
        kw = {'fill': fill, 'outline': outline, 'width': max(1, width * SS)}
        (self.d.rounded_rectangle(b, radius=radius * SS, **kw) if radius else self.d.rectangle(b, **kw))
        if glow:
            (self.g.rounded_rectangle(b, radius=radius * SS, **kw) if radius else self.g.rectangle(b, **kw))

    def finish(self, blur=5):
        out = self.base.copy()
        halo = self.glow.filter(ImageFilter.GaussianBlur(blur * SS / 2))
        out.alpha_composite(halo)
        out.alpha_composite(self.glow.filter(ImageFilter.GaussianBlur(blur * SS / 6)))
        out.alpha_composite(self.ink)
        return out.convert('RGB').resize((W, H), Image.Resampling.LANCZOS)


def _rocket(scene, cx, top, filled, color, muted):
    """A small smooth rocket (nose, round window, two fins and a flame): solid when the reset is available, an outline when not."""
    def pts(points):
        return [(round((cx + a) * SS), round((top + b) * SS)) for a, b in points]
    body = [(0, 0), (1.0, 1.2), (1.8, 2.6), (2.3, 4.4), (2.3, 8.0), (-2.3, 8.0), (-2.3, 4.4), (-1.8, 2.6), (-1.0, 1.2)]
    fins = ([(-2.3, 5.0), (-4.3, 8.9), (-2.3, 8.0)], [(2.3, 5.0), (4.3, 8.9), (2.3, 8.0)])
    if filled:
        scene.d.polygon(pts([(-1.1, 8.1), (1.1, 8.1), (0, 11.4)]), fill=_mix(color, '#ffffff', .55))      # the flame
        for fin in fins:
            scene.d.polygon(pts(fin), fill=_mix(color, '#000000', .25))
        scene.d.polygon(pts(body), fill=color)
        scene.d.ellipse(((cx - 1.05) * SS, (top + 3.0) * SS, (cx + 1.05) * SS, (top + 5.1) * SS), fill=_mix(color, '#000000', .68))
        scene.d.line(pts([(-2.3, 7.2), (2.3, 7.2)]), fill=_mix(color, '#000000', .25), width=max(1, round(SS * .6)))
    else:
        for shape in (body, *fins):
            points = pts(shape)
            scene.d.line(points + [points[0]], fill=muted, width=SS, joint='curve')


def _resets(scene, cx, y, count, old, color, muted, icon):
    """The saved resets, one icon each: bright when available, an outline when not, `+` beside them for more than three. While the
    number is unknown or old the three icons stay (all outlines when unknown, the last known count when old) and ONE faint dot ends
    the row: no `?` and no OLD (the user, 2026-10-20). Each page picks its own icon (`board_reset_icons`; the cockpit's rocket is smooth)."""
    pitch = 9 * 1.4
    x0 = cx - 1.5 * pitch
    have = count if count is not None else 0
    if icon == 'rocket':
        for i in range(3):
            _rocket(scene, x0 + i * pitch + 4.9, y - 1.4, have > i, color, muted)
    else:
        scale = 1.4
        detail = icons.DETAIL[icon]
        tone = {'#': color, 'o': _mix(color, '#ffffff' if detail > 0 else '#000000', abs(detail))}
        for i in range(3):
            left = x0 + i * pitch
            if have > i:
                drawn = [(xx, yy, tone[cell]) for xx, yy, cell, _ in icons.cells(icon)]
            else:
                drawn = [(xx, yy, muted) for xx, yy in icons.hollow(icon)]
            for xx, yy, fill in drawn:
                scene.rect((left + xx * scale, y + yy * scale, left + (xx + 1) * scale, y + (yy + 1) * scale), fill=fill)
    end = x0 + 3 * pitch
    if icons.marked(count, old):
        scene.dot((end + 0.2, y + 4.2), 1.0, _mix(muted, '#000000', .35), glow=False)
        end += 3.6
    mark = icons.mark(count, old)
    if mark:
        scene.text((end + 2, y + 1), mark, 'press-start-2p.ttf', 7, muted)


TRACK = '#1a2c47'   # the unfilled part of a thin five-hour ring: visible, quieter than the fill


def _session_rings(scene, cx, cy, radius, pace, color):
    """Claude's five-hour session as two thin rings inside the weekly band, each in five parts.

    Outer: the quota left (whole ring = 100%, 5% steps). Inner: the time left (one part per hour, quarter
    hours). Same colour as the weekly band; no marks or numbers. Nothing at all while the session is
    unknown, so unknown can never read as empty.
    """
    if pace is None:
        return
    quota, hours = pace
    sweep, start, gap = 270, 135, 5
    part = sweep / 5
    for index, value in enumerate((math.ceil(quota / 5) / 4, round(hours * 4) / 4)):
        r = radius - 15 - index * 7
        for k in range(5):
            a0, length = start + k * part + gap / 2, part - gap
            scene.arc((cx, cy), r, a0, length, 3, TRACK, glow=False)
            fill = max(0, min(1, value - k))
            if fill > 0:
                scene.arc((cx, cy), r, a0, length * fill, 3, color, glow=False)


def render_cockpit(snapshot):
    """Page 7: two glass orbs in deep space (see board_space.py)."""
    from token_tv.board_space import render_cockpit as render
    return render(snapshot)


def render_countdown(snapshot, animated=False):
    """Page 8: Manhattan seen from above at dusk, three buildings carrying the usage (see board_city.py)."""
    from token_tv.board_city import render_countdown as render
    return render(snapshot, animated)
