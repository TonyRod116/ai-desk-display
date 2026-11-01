"""Two private city photographs, with local readings and native board motion."""
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from token_tv import board_anim
from token_tv.board_art import _row
from token_tv.credits import exhausted_credits, format_balance
from token_tv.personal_faces import remaining_reading
from token_tv.themes import face

ART = Path.home() / '.local/share/ai-desk-display/cyber-scenes'
FILES = {'violet-horizon': 'violet-horizon.jpg', 'neon-district': 'neon-district.jpg'}
INK = {'codex': (255, 123, 221), 'claude': (92, 231, 255)}
SIGN_TOP, SIGN_WIDTH, SIGN_HEIGHT = 199, 65, 29
# The two tallest matching towers in the centre-right. Value fills from below.
RAILS = {'violet-horizon': {'codex': (206, 109, 216), 'claude': (247, 109, 216)}}


def backdrop(scene):
    path = ART / FILES[scene]
    try:
        stat = path.stat()
        return _cached_backdrop(path, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        # Private art is optional on another installation. Fail visibly, never as quota zero.
        image = Image.new('RGB', (320, 240), '#101521')
        ImageDraw.Draw(image).text((24, 105), 'LOCAL IMAGE UNAVAILABLE', font=face('oxanium.woff2', 14), fill='#d6e4f1')
        return image


@lru_cache(maxsize=4)
def _cached_backdrop(path, modified, size):
    # Include the file version in the key, so a restored/replaced image appears.
    with Image.open(path) as source:
        return ImageOps.fit(source.convert('RGB'), (320, 240),
                            method=Image.Resampling.LANCZOS, centering=(.5, .5))


def rail(image, provider, spec, remaining):
    x, top, bottom = spec
    color = INK[provider]
    overlay = Image.new('RGBA', image.size)
    d = ImageDraw.Draw(overlay)
    # A dark channel makes the unlit section readable against the luminous city.
    d.line((x, top, x, bottom), fill=(6, 10, 30, 175), width=3)
    n = (bottom-top)//4
    for i in range(n):
        y = bottom-i*4
        on = remaining is not None and i < n * max(0, min(100, remaining))/100
        dim = remaining is None and i % 4 == 0
        if on or dim:
            d.line((x, y-2, x, y), fill=(*color, 230) if on else (138, 145, 164, 125), width=2)
    glow = overlay.filter(ImageFilter.GaussianBlur(2)).point(lambda v: round(v*.55))
    image.paste(glow, (0, 0), glow)
    image.paste(overlay, (0, 0), overlay)


def figures(image, readings):
    """Two people on the rooftop, illuminated from their feet by weekly quota."""
    scale = 3
    size = tuple(n * scale for n in image.size)

    def polygon(draw, points, fill=255, offset=0):
        draw.polygon([((x + offset) * scale, y * scale) for x, y in points], fill=fill)

    def person(existing):
        mask = Image.new('L', size)
        d = ImageDraw.Draw(mask)
        if existing:
            # Follow the outline of the figure already in the photograph.
            d.ellipse((115*scale, 180*scale, 120*scale, 185*scale), fill=255)
            polygon(d, [(115,184),(120,184),(123,187),(124,194),(125,199),
                        (125,205),(123,205),(122,196),(121,198),(121,209),
                        (118,210),(117,199),(116,210),(113,210),(113,197),
                        (112,193),(113,186)])
        else:
            # A second figure, with a different stance and a long coat.
            offset = 37
            d.ellipse(((97+offset)*scale, 181*scale, (102+offset)*scale, 186*scale), fill=255)
            polygon(d, [(97,185),(102,185),(105,188),(106,196),(108,199),
                        (107,201),(104,199),(103,195),(104,203),(102,204),
                        (102,210),(99,210),(99,204),(97,204),(97,210),
                        (94,210),(95,201),(94,195),(93,199),(91,198),
                        (93,188)], offset=offset)
        return mask.resize(image.size, Image.Resampling.LANCZOS)

    for provider, existing in (('codex', True), ('claude', False)):
        mask = person(existing)
        if not existing:
            # Only the new person needs an opaque foundation; preserve the original.
            ImageDraw.Draw(image).line((130, 210, 146, 210), fill=(6, 14, 22), width=2)
            foundation = Image.new('RGB', image.size, (4, 10, 20))
            image.paste(foundation, (0, 0), mask)
        color = INK[provider]
        remaining = readings[provider]
        edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))
        rim = Image.new('RGBA', image.size, (*color, 75))
        image.paste(rim, (0, 0), ImageChops.multiply(edge, rim.getchannel('A')))
        if remaining is None:
            continue  # The sign uses a dash; unknown must not become zero.
        fraction = max(0, min(100, remaining)) / 100
        if not fraction:
            continue
        fill = Image.new('L', image.size)
        boundary = 210 - round(30 * fraction)
        ImageDraw.Draw(fill).rectangle((0, boundary, 319, 210), fill=205)
        lit = ImageChops.multiply(mask, fill)
        glow = lit.filter(ImageFilter.GaussianBlur(2)).point(lambda n: n // 2)
        image.paste(Image.new('RGB', image.size, color), (0, 0), glow)
        image.paste(Image.new('RGB', image.size, color), (0, 0), lit)


def sign(image, provider, remaining, credit, x, reset):
    """An illuminated weekly reading and its reset, integrated into the scene."""
    scale, width, height = 3, SIGN_WIDTH, SIGN_HEIGHT
    badge = Image.new('RGBA', (width*scale, height*scale))
    d = ImageDraw.Draw(badge)
    color = INK[provider]
    d.rounded_rectangle((1, 1, width*scale-2, height*scale-2), radius=5*scale,
                        fill=(7, 13, 27, 234), outline=(*color, 255), width=scale)
    name_font = face('oxanium.woff2', 6*scale)
    d.text((6*scale, (2 if credit is not None else 3)*scale), provider.upper(), font=name_font, fill=(*color, 255))
    value = ('CR ' + format_balance(credit)) if credit is not None else '--' if remaining is None else '<1%' if 0 < remaining < 1 else f'{round(remaining)}%'
    available = 55*scale if credit is not None else 52*scale - name_font.getlength(provider.upper())
    font_size = 10 if credit is not None else 13
    while font_size > 6 and face('oxanium.woff2', font_size*scale).getlength(value) > available:
        font_size -= 1
    d.text(((width-5)*scale, (7 if credit is not None else 1)*scale), value, anchor='ra', font=face('oxanium.woff2', font_size*scale), fill='#f6f8ff')
    reset_label = 'RESET ' + reset.upper()
    reset_size = 7 if credit is not None else 8
    while reset_size > 6 and face('oxanium.woff2', reset_size*scale).getlength(reset_label) > 55*scale:
        reset_size -= 1
    d.text((5*scale, (19 if credit is not None else 16)*scale), reset_label, font=face('oxanium.woff2', reset_size*scale), fill='#d4e4f5')
    badge = badge.resize((width, height), Image.Resampling.LANCZOS)
    glow = badge.filter(ImageFilter.GaussianBlur(2))
    image.paste(glow, (x, SIGN_TOP), glow)
    image.paste(badge, (x, SIGN_TOP), badge)


def _sprite(area, frames, period=400, offset=0):
    """Use one short, shared cycle; never redraw the same pose twice in a row."""
    x, y, _, _ = area
    return {'x': x, 'y': y, 'frames': frames,
            'script': [((i + offset) % len(frames), 0, 0) for i in range(8)], 'step_ms': period}


def _cloud_sprite(image, area):
    """Drift soft areas of the original blue and lilac cloud texture."""
    x, y, w, h = area
    size = w // 2, h // 2
    source = image.crop((x, y, x+w, y+h)).resize(size, Image.Resampling.BOX)
    native = image.load()
    base = source.load()
    frames = []
    for frame in range(8):
        offset = 1.65 * math.sin(math.tau * frame / 8)
        moved = source.transform(size, Image.Transform.AFFINE, (1, 0, offset, 0, 1, offset * .16),
                                 resample=Image.Resampling.BICUBIC).load()
        pose = Image.new('RGBA', size)
        pixels = pose.load()
        for py in range(size[1]):
            for px in range(size[0]):
                # The moving part comes only from existing lilac and blue clouds.
                original = base[px, py]
                if max(original) < 65 or original[2] < original[1] * 1.2:
                    continue
                details = [native[x+px*2+dx, y+py*2+dy] for dy in (0, 1) for dx in (0, 1)]
                if max(abs(c[k]-original[k]) for c in details for k in range(3)) > 28:
                    continue  # leave crisp stars, streaks and building edges alone
                feather = min(1, px/4, py/3, (size[0]-1-px)/4, (size[1]-1-py)/3)
                if feather <= 0:
                    continue
                new = [round(original[k] + (moved[px, py][k]-original[k]) * feather * .8) for k in range(3)]
                # No extra dark smudges: only move a soft, luminous cloud veil.
                deficit = max(0, sum(original) - sum(new))
                if deficit:
                    new = [min(255, c + math.ceil(deficit / 3)) for c in new]
                if max(abs(new[k] - original[k]) for k in range(3)) >= 4:
                    pixels[px, py] = tuple(new) + (255,)
        frames.append(pose)
    return _sprite(area, frames, 500)


def _window_sprite(area, points, colors, offset=0, period=500, calm=False):
    """Twinkle a handful of existing-looking windows, not whole buildings."""
    x, y, w, h = area
    frames = []
    for f in range(4):
        frame = Image.new('RGBA', (w//2, h//2))
        draw = ImageDraw.Draw(frame)
        for i, (gx, gy) in enumerate(points):
            if calm:
                # Most rooms stay lit; two pairs trade places on each change.
                if i >= 8 and not ((0b0011, 0b0110, 0b1100, 0b1001)[(i - 8) % 4] & (1 << f)):
                    continue
            elif (i * 3 + f + offset) % 4 != 0:
                continue
            if not (x <= gx < x+w and y <= gy < y+h):
                raise ValueError((area, gx, gy))
            draw.point(((gx-x)//2, (gy-y)//2), fill=colors[i % len(colors)] + (255,))
        frames.append(frame)
    if calm:
        # The towers alternate every four seconds. Each tower changes only
        # every eight seconds and its complete pattern repeats after 32.
        poses = (0, 1, 1, 2, 2, 3, 3, 0) if offset else (0, 1, 2, 3)
        return {'x': x, 'y': y, 'frames': frames,
                'script': [(pose, 0, 0) for pose in poses], 'step_ms': 4000 if offset else 8000}
    return _sprite(area, frames, period, offset)


def _sign_sprite(image, area, tint, axis='vertical', offset=0):
    """Sweep neon light across details already present in a sign."""
    x, y, w, h = area
    source = image.crop((x, y, x+w, y+h)).resize((w//2, h//2), Image.Resampling.BOX)
    values = source.load()
    frames = []
    for f in range(8):
        frame = Image.new('RGBA', source.size)
        px = frame.load()
        for yy in range(source.height):
            for xx in range(source.width):
                band = (yy if axis == 'vertical' else xx)
                length = (source.height if axis == 'vertical' else source.width)
                center = (f-1) * (length+8) / 6 - 3
                distance = abs(band-center)
                red, green, blue = values[xx, yy]
                if distance > 2 or max(red,green,blue) < 118:
                    continue
                strength = .75 * (1-distance/3)
                # Only illuminate the sign's existing details, not its dark edges.
                color = tuple(round(c + (max(c, tint[k])-c)*strength) for k,c in enumerate((red,green,blue)))
                px[xx,yy] = color + (255,)
        frames.append(frame)
    return _sprite(area, frames, 400, offset)


def _violet_motion(image):
    return [_cloud_sprite(image, (0, 80, 176, 44)), _cloud_sprite(image, (272, 74, 48, 54)),
            _window_sprite((10, 148, 96, 60),
                    [(18,148),(24,156),(30,164),(18,172),(28,180),(22,188),(34,196),(26,194),
                     (56,174),(60,184),(64,194),(72,174),(88,166),(94,174),(100,186),(90,198)],
                    [(95,225,255),(255,126,224),(255,210,140)], calm=True),
            _window_sprite((208, 130, 64, 78),
                    [(212,136),(218,148),(224,160),(214,174),(252,134),(260,146),(266,160),(254,176),
                     (222,186),(228,198),(216,196),(222,176),(262,186),(268,194),(254,192),(266,176)],
                    [(110,240,255),(255,138,225),(255,212,160)], 1, calm=True)]


def _neon_motion(image):
    return [_sign_sprite(image, (46, 38, 50, 84), (110,250,255), 'vertical'),
            _sign_sprite(image, (144, 48, 48, 104), (255,135,240), 'vertical', 2),
            _sign_sprite(image, (198, 18, 58, 62), (255,240,150), 'horizontal', 5),
            _window_sprite((160, 166, 150, 48),
                    [(160,172),(168,182),(176,192),(186,170),(194,182),(204,194),(214,174),
                     (226,186),(238,196),(250,172),(262,184),(274,194),(286,170),(298,182),
                     (308,194)], [(65,230,255),(255,99,220),(255,227,166)], 1, 400)]


def motion(scene, image):
    """Run distinct, seamless ambient cycles within the board's four-sprite limit."""
    sprites = _violet_motion(image) if scene == 'violet-horizon' else _neon_motion(image)
    return board_anim.encode(sprites=sprites)


def render_city(scene, snapshot, animated=False):
    image = backdrop(scene).copy()
    readings = {}
    for provider, x in (('codex', 7), ('claude', 251)):
        row = _row(snapshot, provider)
        remaining, _, old, reset = remaining_reading(row)
        if old:
            remaining, reset = None, '--'
        readings[provider] = remaining
        credit = exhausted_credits(row) if remaining == 0 else None
        if scene in RAILS:
            rail(image, provider, RAILS[scene][provider], remaining)
        sign(image, provider, remaining, credit, x, reset)
    if scene == 'neon-district':
        figures(image, readings)
    return (image, motion(scene, image)) if animated else image
