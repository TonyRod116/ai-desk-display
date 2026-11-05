"""Two private city photographs, with local readings and native board motion."""
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from token_tv import board_anim, board_reset_icons as icons
from token_tv.board_art import _row
from token_tv.credits import exhausted_credits, format_balance
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

ART = Path.home() / '.local/share/ai-desk-display/cyber-scenes'
FILES = {'violet-horizon': 'violet-horizon.jpg', 'neon-district': 'neon-district.jpg'}
INK = {'codex': (255, 123, 221), 'claude': (92, 231, 255)}
# The two cards stand on the bottom corners, above the firmware's own page marks (the bottom 10 px). Each carries the same
# things as every other board page: the provider, the week's quota left, the weekly reset, the three saved resets as little
# bolts (one faint dot after them while the count is unknown or old) and, only on Claude's, the two thin five-hour lines
# (quota above, time below). The cards are lit glass, not panels: a thin neon edge, a translucent dark fill, no outer glow.
# `w` is the card's width, the rest are font sizes and the size of one bolt cell. Violet Horizon's Claude tower carries its
# LED rail 3 px left of the card, so its cards stay as narrow as the old ones (Tony, 2026-11-03: text too small, no saved
# resets and no five-hour lines on Neon District; asked not to make the cards heavier).
CARDS = {
    'neon-district': dict(w=80, pad=6, name=9, value=17, reset=9, bolt=.85),
    'violet-horizon': dict(w=65, pad=4, name=7, value=14, reset=8, bolt=.75),
}
CARD_BOTTOM, CARD_LEFT, CARD_RIGHT = 228, 7, 316
CARD_PAD = 4                        # padding above the first row and below the last
PACE_ROW = 9                        # extra height of Claude's two five-hour lines
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


CAP = .69   # Oxanium's capital height in em: rows are laid out from their baselines


def _mixed(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def card_height(scene, provider):
    """Height in pixels of a provider's card: Claude's carries the two five-hour lines under the three rows."""
    style = CARDS[scene]
    rows = CARD_PAD + round(CAP * style['name']) + 3 + round(CAP * style['value']) + 3 + round(CAP * style['reset']) + CARD_PAD
    return rows + (PACE_ROW if provider == 'claude' else 0)


def card_box(scene, provider):
    """(left, top, right, bottom) of a provider's card on the picture, bottom edge included."""
    width, height = CARDS[scene]['w'], card_height(scene, provider)
    left = CARD_LEFT if provider == 'codex' else CARD_RIGHT - width
    return left, CARD_BOTTOM - height, left + width, CARD_BOTTOM


SIGN_WIDTH = max(card['w'] for card in CARDS.values())
SIGN_HEIGHT = max(card_height(scene, 'claude') for scene in CARDS)     # the tallest card: Claude's
SIGN_TOP = CARD_BOTTOM - SIGN_HEIGHT                                   # and the highest a card ever reaches


BOLT = ((3.8, 0), (.4, 5), (2.9, 5), (2, 9), (6, 3.6), (3.6, 3.6), (5, 0))     # a lightning bolt in a 6 x 9 box


def _bolts(d, scale, right, middle, count, old, color, card, size):
    """The saved resets: one little neon bolt each, bright when available and faint when not, then ONE faint dot after them while
    the count is unknown or old (never `?` or OLD, Tony 2026-10-20) or a `+` for more than three. Right-aligned at `right`; the
    dot or plus has the last 5 px, so the bolts never move between states."""
    pitch = 8 * size
    left = right - (2 * pitch + 6 * size)
    have = count if count is not None else 0
    faint = _mixed(color, card, .72)
    for i in range(3):
        points = [((left + i * pitch + px * size) * scale, (middle + (py - 4.5) * size) * scale) for px, py in BOLT]
        d.polygon(points, fill=(*(color if have > i else faint), 255))
    if icons.marked(count, old):
        cx = right + 3.4
        d.ellipse(((cx - 1.1) * scale, (middle - 1.1) * scale, (cx + 1.1) * scale, (middle + 1.1) * scale), fill=(*_mixed(color, card, .45), 255))
    mark = icons.mark(count, old)
    if mark:
        d.text(((right + 6.5) * scale, (middle + 3) * scale), mark, anchor='rs', fill=(*color, 255), font=face('oxanium.woff2', 9 * scale))


def sign(image, provider, remaining, credit, x, reset, saved=(None, False), pace=None, scene='neon-district'):
    """A lit-glass card for one provider: the name and its saved resets, the week's quota left, the weekly reset and, on Claude's,
    the two thin five-hour lines. `saved` is `banked_hearts(row)` and `pace` the fresh `session_pace(row)`; unknown draws a
    dash and no line, so it never reads as empty."""
    scale, style = 3, CARDS[scene]
    width, height = style['w'], card_height(scene, provider)
    top = CARD_BOTTOM - height
    badge = Image.new('RGBA', (width * scale, height * scale))
    d = ImageDraw.Draw(badge)
    color, card = INK[provider], (7, 13, 27)
    d.rounded_rectangle((1, 1, width * scale - 2, height * scale - 2), radius=5 * scale,
                        fill=(*card, 198), outline=(*color, 240), width=scale)
    pad = style['pad']
    # row 1: the provider and its saved resets
    y1 = CARD_PAD + CAP * style['name']
    d.text((pad * scale, y1 * scale), provider.upper(), anchor='ls', font=face('oxanium.woff2', style['name'] * scale), fill=(*color, 255))
    count, old_count = saved
    _bolts(d, scale, width - pad - 5.5, y1 - CAP * style['name'] / 2, count, old_count, color, card, style['bolt'])
    # row 2: the week's quota left, or the credit balance of an exhausted Codex week
    y2 = y1 + 3 + CAP * style['value']
    value = ('CR ' + format_balance(credit)) if credit is not None else '--' if remaining is None else '<1%' if 0 < remaining < 1 else f'{round(remaining)}%'
    inner = (width - 2 * pad) * scale
    size = style['value'] if credit is None else min(style['value'], 13)
    while size > 6 and face('oxanium.woff2', size * scale).getlength(value) > inner:
        size -= 1
    d.text((pad * scale, y2 * scale), value, anchor='ls', font=face('oxanium.woff2', size * scale), fill='#f6f8ff')
    # row 3: the weekly reset
    y3 = y2 + 3 + CAP * style['reset']
    label, size = 'RESET ' + reset.upper(), style['reset']
    while size > 6 and face('oxanium.woff2', size * scale).getlength(label) > inner:
        size -= 1
    d.text((pad * scale, y3 * scale), label, anchor='ls', font=face('oxanium.woff2', size * scale), fill='#d4e4f5')
    if provider == 'claude' and pace is not None:
        # the two thin lines of five parts: the session's quota left (5 % steps) above, its time left (quarter hours) below
        quota, hours = pace
        part, between = (inner / scale - 4 * 2.2) / 5, 2.2
        for line, units in enumerate((math.ceil(quota / 5) / 4, round(hours * 4) / 4)):
            top_line = y3 + 4.5 + line * 3.5
            lit = color if line == 0 else _mixed(color, (150, 160, 180), .45)
            for k in range(5):
                x0 = pad + k * (part + between)
                d.rectangle((x0 * scale, top_line * scale, (x0 + part) * scale - 1, (top_line + 2) * scale - 1), fill=(*_mixed(color, card, .82), 255))
                fill = max(0, min(1, units - k))
                if fill > 0:
                    d.rectangle((x0 * scale, top_line * scale, (x0 + part * fill) * scale - 1, (top_line + 2) * scale - 1), fill=(*lit, 255))
    badge = badge.resize((width, height), Image.Resampling.LANCZOS)
    glow = badge.filter(ImageFilter.GaussianBlur(2))
    glow.putalpha(glow.getchannel('A').point(lambda a: a * 2 // 5))
    image.paste(glow, (x, top), glow)
    image.paste(badge, (x, top), badge)


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


def _natural_violet_lights(image, area, offset=0):
    """Dim and relight four isolated lights already present in the city."""
    x, y, width, height = area
    source = image.crop((x, y, x + width, y + height)).resize(
        (width // 2, height // 2), Image.Resampling.BOX)
    pixels = source.load()
    boxes = [card_box('violet-horizon', provider) for provider in ('codex', 'claude')]
    candidates = []
    for py in range(1, source.height - 1):
        for px in range(1, source.width - 1):
            gx, gy = x + 2 * px, y + 2 * py
            if (204 <= gx <= 210 or 245 <= gx <= 250 or
                    any(gx + 2 > left and gx <= right and gy + 2 > top and gy <= bottom
                        for left, top, right, bottom in boxes)):
                continue
            colour = pixels[px, py]
            neighbours = [pixels[px + dx, py + dy] for dx, dy in
                          ((-1, 0), (1, 0), (0, -1), (0, 1))]
            # Choose small highlights, not a long neon edge or a dark window.
            score = max(colour) - sorted(max(c) for c in neighbours)[2]
            if max(colour) >= 115 and colour[2] >= colour[0] and score >= 8:
                candidates.append((score, px, py, colour, min(neighbours, key=max)))
    candidates.sort(reverse=True)
    chosen = []
    for candidate in candidates:
        _, px, py, _, _ = candidate
        if all((px - other[1]) ** 2 + (py - other[2]) ** 2 >= 25 for other in chosen):
            chosen.append(candidate)
            if len(chosen) == 4:
                break
    if len(chosen) < 4:
        return None  # Preserve the existing fallback for other local artwork.

    frames = []
    for frame in range(4):
        pose = Image.new('RGBA', source.size)
        for i, (_, px, py, original, dark) in enumerate(chosen):
            lit = (0b0011, 0b0110, 0b1100, 0b1001)[i] & (1 << frame)
            colour = tuple(min(255, round(c * 1.1 + 5)) for c in original) if lit else _mixed(original, dark, .8)
            pose.putpixel((px, py), (*colour, 255))
        frames.append(pose)
    poses = (0, 1, 1, 2, 2, 3, 3, 0) if offset else (0, 1, 2, 3)
    return {'x': x, 'y': y, 'frames': frames,
            'script': [(pose, 0, 0) for pose in poses], 'step_ms': 4000 if offset else 8000}


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


def _beside_the_cards(scene, points):
    """The windows that may twinkle: a lit window is drawn over the page, so none may shine through a card. The first eight stay
    the always-lit ones of the calm cycle, whatever is dropped."""
    boxes = [card_box(scene, provider) for provider in ('codex', 'claude')]
    return [(x, y) for x, y in points
            if not any(x + 2 > left and x <= right and y + 2 > top and y <= bottom for left, top, right, bottom in boxes)]


def _lift_violet_ship(image):
    """Lift the little existing craft into memory and repair only its old spot.

    The image and the derived frames remain local. Legacy boards keep the
    untouched photograph, so a board without the new engine never loses it.
    """
    box = (112, 47, 126, 64)
    ship = image.crop(box).convert('RGBA')
    mask = Image.new('L', ship.size)
    ImageDraw.Draw(mask).polygon(((0, 15), (10, 0), (13, 0), (13, 12), (6, 16)), fill=255)
    ship.putalpha(mask)

    # The original craft has a cyan contrail painted into the sky. Remove
    # only those cyan pixels along its known path; otherwise it would end in
    # mid-air while the moving craft travels elsewhere. The flying pose has
    # a shorter, moving light trail of its own.
    sky = image.copy()
    target, clean = image.load(), sky.load()
    for x in range(126):
        centre = round(23 + x * .266)
        for y in range(max(5, centre - 3), min(64, centre + 4)):
            red, green, blue = clean[x, y]
            if green + blue - 2 * red > 70 and blue > red * 1.2:
                target[x, y] = _mixed(clean[x, y - 5], clean[x, y + 5], .5)

    # Interpolate the unobstructed sky just either side of the small craft.
    # A softly feathered edge avoids a visible rectangular repair.
    repair = Image.new('RGB', (18, 20))
    pixels = repair.load()
    original = image.load()
    for y in range(repair.height):
        left, right = original[110, 46 + y], original[129, 46 + y]
        for x in range(repair.width):
            pixels[x, y] = _mixed(left, right, (x + 1) / 19)
    feather = Image.new('L', repair.size)
    ImageDraw.Draw(feather).ellipse((1, 0, 16, 19), fill=255)
    image.paste(repair, (111, 46), feather.filter(ImageFilter.GaussianBlur(.7)))
    return ship


def _violet_water(image):
    """Gently refract the actual city reflection, in a narrow safe water strip."""
    area = (74, 218, 176, 22)
    x, y, w, h = area
    source = image.crop((x, y, x + w, y + h)).resize((w // 2, h // 2), Image.Resampling.BOX)
    values = source.load()
    frames = []
    for frame in range(8):
        pose = Image.new('RGBA', source.size)
        pixels = pose.load()
        phase = math.pi * frame / 7
        for py in range(source.height):
            for px in range(source.width):
                strength = min(1, (px + 1) / 5, (source.width - px) / 5,
                               (py + 1) / 2, (source.height - py) / 2)
                # Small waves change direction across depths instead of
                # moving the entire water surface like a flat sheet.
                shift = min(1.8, 1.05 + py * .09) * math.sin(phase + py * .7 + px * .045)
                sample = max(0, min(source.width - 1, px + shift))
                left = int(sample)
                right = min(source.width - 1, left + 1)
                warped = _mixed(values[left, py], values[right, py], sample - left)
                original = values[px, py]
                colour = _mixed(original, warped, strength * .85)
                if max(abs(colour[k] - original[k]) for k in range(3)) >= 3:
                    pixels[px, py] = (*colour, 255)
        frames.append(pose)
    poses = tuple(range(8)) + tuple(reversed(range(8)))
    return {'x': x, 'y': y, 'frames': frames,
            'script': [(i, 0, 0) for i in poses], 'step_ms': 125}


def _reflect_violet_city(image):
    """Blend a vertically compressed reflection of the skyline into its water.

    The source is the local photograph and its tower lights, before the quota
    cards are added. Only the strip between those cards is touched; the board's
    own page dots and the readings remain outside it.
    """
    x, y, width, height = 74, 218, 176, 22
    skyline = image.crop((x, 138, x + width, y)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    skyline = skyline.resize((width, height), Image.Resampling.BOX).filter(ImageFilter.GaussianBlur(.45))
    reflection, water = skyline.load(), image.load()
    for row in range(height):
        fade = .57 * (1 - .35 * row / max(1, height - 1))
        for column in range(width):
            # Feather the two ends into the unchanged photograph, while
            # keeping the right-hand tower visible beside the Claude card.
            edge = min(1, (column + 1) / 5, (width - column) / 3)
            water[x + column, y + row] = _mixed(water[x + column, y + row],
                                                reflection[column, row], fade * edge)


def _trim_transparent(sprite):
    """Discard unused sprite margins without changing any displayed pixels."""
    mask = sprite['frames'][0].getchannel('A')
    for frame in sprite['frames'][1:]:
        mask = ImageChops.lighter(mask, frame.getchannel('A'))
    box = mask.getbbox() or (0, 0, 1, 1)
    left, top, _, _ = box
    return {**sprite, 'x': sprite['x'] + left * 2, 'y': sprite['y'] + top * 2,
            'frames': [frame.crop(box) for frame in sprite['frames']]}


def _ship_poses(ship, wide=False):
    """Several sizes and a clear pose; the approaching craft grows larger."""
    canvas = (32, 19) if wide else (12, 8)
    frames = [Image.new('RGBA', canvas)]
    sizes = ((2, 2), (5, 4), (10, 6), (17, 10), (24, 14), (32, 19)) if wide else ((2, 2), (3, 4), (4, 6), (6, 8))
    for w, h in sizes:
        pose = Image.new('RGBA', canvas)
        scaled = ship.resize((w, h), Image.Resampling.LANCZOS)
        pose.alpha_composite(scaled, ((canvas[0] - w) // 2, (canvas[1] - h) // 2))
        if not wide and w >= 3:
            # The original cyan wake follows the craft, not the background.
            left, top = (12 - w) // 2, (8 - h) // 2
            ImageDraw.Draw(pose).line((max(0, left - 3), top + 1, left - 1, top + 2),
                                      fill=(100, 193, 255, 255))
        frames.append(pose)
    return frames


def _incoming_ship():
    """An oblique stealth craft with blue and violet reflections from the city."""
    scale = 10
    ship = Image.new('RGBA', (32 * scale, 19 * scale))
    d = ImageDraw.Draw(ship)

    def polygon(points, fill):
        d.polygon([(round(x * scale), round(y * scale)) for x, y in points], fill=fill)

    def line(points, fill, width=.3):
        d.line([(round(x * scale), round(y * scale)) for x, y in points],
               fill=fill, width=max(1, round(width * scale)), joint='curve')

    # An asymmetrical silhouette and layered facets echo the original art;
    # reflected neon gives shape without the heavy outline of an icon.
    polygon([(20,.2),(21.5,5.1),(31.7,10.8),(30.5,13.7),(22,13.1),
             (19.8,17.7),(16.9,15.8),(13.5,17.4),(11.4,14),(1,14),(.2,12.3),(15.6,5)], '#080b20')
    polygon([(19.7,.9),(17.2,8.1),(12.1,12.5),(1.9,12.7),(16.2,5.5)], '#34254e')
    polygon([(20.1,.9),(21.2,5.6),(30.6,10.9),(29.7,12.5),(21.5,11.4),(18.8,9)], '#143459')
    polygon([(4,12.4),(13,9.4),(12,11.5),(7,13.2)], '#674273')
    polygon([(22,8),(29.1,11),(28.9,12),(22.8,10.3)], '#21527a')
    polygon([(16.9,4.6),(19.7,4.7),(21.6,11.6),(19.5,16.7),(17.2,14.7),(14.2,16.3),(12.5,13.2)], '#171f3b')
    polygon([(19.2,1.7),(20.1,5.5),(18.5,10.1),(16.8,10.7),(16.4,7.1)], '#3c7097')
    polygon([(19.2,3.2),(19.5,5.6),(18.4,8.7),(17.1,9.2),(17,7)], '#081b33')
    polygon([(13.1,12),(15.8,11.3),(16.8,13.8),(14.5,16),(12.7,14)], '#263855')
    polygon([(20.3,11.3),(21,12.5),(19.7,15.9),(18.7,14.4)], '#344a66')
    line([(2,12.8),(11.8,10.5),(15.2,7.5)], '#f078d4', .35)
    line([(21.1,6.2),(24.3,8),(30.1,10.9)], '#7ddcff', .35)
    line([(19.4,1.5),(17,6.9)], '#bfecff', .3)
    line([(13.7,14.8),(14.5,15.6)], '#ffb5ed', .6)
    line([(19.4,14.8),(20,15.4)], '#d5f8ff', .6)
    line([(14.4,15.6),(13.7,18.2)], '#c15fd3', .3)
    line([(19.8,15.4),(20.5,18)], '#62bcea', .3)
    line([(15.2,11.7),(17,11.1),(19.3,11.7)], '#839cbc', .25)
    return ship.resize((32, 19), Image.Resampling.LANCZOS)


def _violet_ships(original):
    """One craft goes right; the other approaches and leaves above the viewer.

    The outgoing journey is split at the middle because the existing wire
    format stores signed one-byte offsets. The two legs meet one frame apart.
    Their quiet poses are identical, so the board does not redraw them while
    the other ship is crossing the same part of the sky.
    """
    frames = _ship_poses(original)
    approaching = _ship_poses(_incoming_ship(), wide=True)
    blank = (0, 0, 0)
    first, second, inbound = [blank] * 128, [blank] * 128, [blank] * 128
    for k in range(1, 36):
        x = -24 + round(184 * k / 36)
        y = 43 + round((x + 24) / 27)
        pose = max(1, 4 - (k * 4 // 72))
        first[k] = (2 if pose == 4 else 1, x - 80, y - 40)
    for k in range(36, 72):
        x = 160 + round(160 * (k - 36) / 36)
        y = 50 + round((x - 160) / 27)
        pose = max(1, 4 - (k * 4 // 72))
        second[k] = (pose, x - 240, y - 50)
    for k in range(73, 120):
        progress = (k - 72) / 47
        x = 320 - round(130 * progress)
        # Let the growing craft stay in view long enough to see its detail;
        # then accelerate it above the camera before selecting a blank pose.
        departure = max(0, (progress - .7) / .3)
        y = 33 - round(19 * min(progress / .7, 1) + 53 * departure ** 2)
        pose = min(6, 1 + int(progress * 6))
        inbound[k] = (pose, x - 250, y - 20)
    return [
        {'x': 80, 'y': 40, 'frames': [frames[0], frames[3], frames[4]], 'script': first, 'step_ms': 125},
        {'x': 240, 'y': 50, 'frames': frames[:3], 'script': second, 'step_ms': 125},
        {'x': 250, 'y': 20, 'frames': approaching, 'script': inbound, 'step_ms': 125},
    ]


def _violet_motion(image, natural_lights=False):
    sprites = [_cloud_sprite(image, (0, 80, 176, 44)), _cloud_sprite(image, (272, 74, 48, 54)),
            _window_sprite((16, 148, 86, 52),
                    _beside_the_cards('violet-horizon',
                    [(18,148),(24,156),(30,164),(18,172),(28,180),(22,188),(34,196),(26,194),
                     (56,174),(60,184),(64,194),(72,174),(88,166),(94,174),(100,186),(90,198)]),
                    [(95,225,255),(255,126,224),(255,210,140)], calm=True),
            _window_sprite((210, 134, 60, 66),
                    _beside_the_cards('violet-horizon',
                    [(212,136),(218,148),(224,160),(214,174),(252,134),(260,146),(266,160),(254,176),
                     (222,186),(228,198),(216,196),(222,176),(262,186),(268,194),(254,192),(266,176)]),
                    [(110,240,255),(255,138,225),(255,212,160)], 1, calm=True)]
    if natural_lights:
        for index, area in enumerate(((16, 148, 86, 52), (210, 134, 60, 66))):
            lights = _natural_violet_lights(image, area, offset=index)
            if lights:
                sprites[index + 2] = lights
    return sprites


def _neon_motion(image):
    return [_sign_sprite(image, (46, 38, 50, 84), (110,250,255), 'vertical'),
            _sign_sprite(image, (144, 48, 48, 104), (255,135,240), 'vertical', 2),
            _sign_sprite(image, (198, 18, 58, 62), (255,240,150), 'horizontal', 5),
            _window_sprite((160, 166, 150, 48),
                    _beside_the_cards('neon-district',
                    [(160,172),(168,182),(176,192),(186,170),(194,182),(204,194),(214,174),
                     (226,186),(238,196),(250,172),(262,184),(274,194),(286,170),(298,182),
                     (308,194)]), [(65,230,255),(255,99,220),(255,227,166)], 1, 400)]


def motion(scene, image, extended_anim=False, ship=None):
    """Run ambient cycles; extended motion is reserved for capable boards."""
    sprites = _violet_motion(image, natural_lights=extended_anim) if scene == 'violet-horizon' else _neon_motion(image)
    if scene == 'violet-horizon' and extended_anim:
        sprites = [_trim_transparent(sprite) for sprite in sprites]
        sprites += [_violet_water(image), *_violet_ships(ship)]
    return board_anim.encode(sprites=sprites, extended=scene == 'violet-horizon' and extended_anim)


def render_city(scene, snapshot, animated=False, extended_anim=False):
    image = backdrop(scene).copy()
    ship = _lift_violet_ship(image) if scene == 'violet-horizon' and animated and extended_anim else None
    readings = {}
    cards = []
    for provider in ('codex', 'claude'):
        row = _row(snapshot, provider)
        remaining, _, old, reset = remaining_reading(row)
        if old:
            remaining, reset = None, '--'
        readings[provider] = remaining
        credit = exhausted_credits(row) if remaining == 0 else None
        if scene in RAILS:
            rail(image, provider, RAILS[scene][provider], remaining)
        pace = session_pace(row) if provider == 'claude' and not old else None      # only from a fresh reading
        cards.append((provider, remaining, credit, reset, banked_hearts(row), pace))
    if scene == 'violet-horizon' and animated and extended_anim:
        _reflect_violet_city(image)
    for provider, remaining, credit, reset, saved, pace in cards:
        sign(image, provider, remaining, credit, card_box(scene, provider)[0], reset, saved, pace, scene)
    if scene == 'neon-district':
        figures(image, readings)
    return (image, motion(scene, image, extended_anim=extended_anim, ship=ship)) if animated else image
