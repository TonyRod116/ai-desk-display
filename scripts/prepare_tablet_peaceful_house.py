"""Prepare a private seaside-house photo for the tablet; no artwork is stored here.

The old scene identifier is retained so existing selections and schedules keep
working. The supplied photo never leaves this computer or enters the repo.
"""
import argparse
import math
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media as media  # noqa: E402

SIZE = (672, 1008)
PARTS = ('dawn', 'day', 'dusk', 'night')
SCENES = {'house': 'midnight-video-club', 'mountain': 'neon-district'}  # keep existing tablet selections
TAU = 2 * math.pi
HOUSE_LIGHTS = {
    'dusk': {'point': (.55, .416), 'colour': (255, 202, 130), 'strength': .94},
    'night': {'point': (.405, .275), 'colour': (211, 231, 245), 'strength': 1.25},
}


def sunset_layer(original):
    """A transparent sunset grade for all panes, safe over moving video."""
    w, h = SIZE
    mask = Image.new('L', SIZE)
    clouds = Image.new('L', SIZE)
    src, selected = original.load(), mask.load()
    cloud_pixels = clouds.load()
    # Tint the three exterior openings, keeping the wood and open doors clear.
    # The blue-pixel test also preserves leaves and the silhouetted sailboat.
    panes = ((.020, .118), (.235, .811), (.912, 1.0))
    for y in range(round(.195 * h), round(.60 * h)):
        for left, right in panes:
            for x in range(round(left * w), min(w, round(right * w))):
                r, g, b = src[x, y]
                blue = b > r + 5 and b >= g - 10 and b > 65
                pale_cloud = y < .42 * h and min(r, g, b) > 170 and max(r, g, b) - min(r, g, b) < 45
                # The central water moves. Its wash is a smooth separate
                # layer, not a mask traced from a single frozen wave frame.
                moving_water = y >= .42 * h and .235 * w <= x <= .811 * w
                if (blue or pale_cloud) and not moving_water:
                    selected[x, y] = 255
                    if y < .42 * h:
                        cloud_pixels[x, y] = round(max(0, min(115, (min(r, g, b) - 155) * 2.0)))
    mask = mask.filter(ImageFilter.GaussianBlur(1.1))
    # Preserve the photograph's cloud texture while introducing a warm
    # horizon, rose-coloured cloud tops and muted gold in the sea.
    wash = Image.new('RGB', SIZE)
    draw = ImageDraw.Draw(wash)
    for y in range(h):
        sky = max(0.0, min(1.0, (y / h - .20) / .22))
        if y < .42 * h:
            colour = (round(204 + 44 * sky), round(129 + 43 * sky), round(157 - 32 * sky))
        else:
            colour = (176, 125, 113)
        draw.line((0, y, w, y), fill=colour)
    layer = Image.new('RGBA', SIZE)
    colour = wash.convert('RGBA')
    colour.putalpha(mask.point(lambda value: round(value * .48)))
    layer.alpha_composite(colour)
    water = Image.new('RGBA', SIZE, (196, 129, 112, 0))
    water.putalpha(ocean_mask().point(lambda value: round(value * .16)))
    layer.alpha_composite(water)
    cloud_alpha = ImageChops.multiply(clouds.filter(ImageFilter.GaussianBlur(1.0)), mask)
    cloud_colour = Image.new('RGBA', SIZE, (255, 205, 183, 0))
    cloud_colour.putalpha(cloud_alpha)
    layer.alpha_composite(cloud_colour)

    # A soft low sun on the horizon, clipped to the actual sky rather than
    # painted over the window frame, trees, sea or the little sailboat.
    glow = Image.new('L', SIZE)
    p = glow.load()
    lx, ly = HOUSE_LIGHTS['dusk']['point']
    cx, cy = round(lx * w), round(ly * h)
    for y in range(max(0, cy - 65), min(h, cy + 24)):
        for x in range(max(0, cx - 70), min(w, cx + 71)):
            d = math.hypot(x - cx, (y - cy) * 1.1)
            if d < 12:
                p[x, y] = round(228 - 28 * d / 12)
            elif d < 65:
                p[x, y] = round(105 * math.exp(-((d - 12) / 22) ** 2))
    # Restrict the glow to the selected sky; it cannot light the water as a
    # floating disc or erase detail in the silhouettes.
    glow = ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(1.4)), mask)
    horizon = Image.new('L', SIZE)
    ImageDraw.Draw(horizon).rectangle((0, 0, w, round(.420 * h) - 1), fill=255)
    glow = ImageChops.multiply(glow, horizon)
    sunlight = Image.new('RGBA', SIZE, (255, 221, 169, 0))
    sunlight.putalpha(glow)
    layer.alpha_composite(sunlight)
    return layer


def sunset_windows(original, result):
    """Warm the existing scene without covering its moving sea or wildlife."""
    return Image.alpha_composite(result.convert('RGBA'), sunset_layer(original)).convert('RGB')


def house_window_mask(original):
    """Select the exterior, including the small panes, without painting their frames."""
    w, h = SIZE
    mask = Image.new('L', SIZE)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((round(.235 * w), round(.195 * h), round(.811 * w), round(.70 * h)), fill=255)
    # The left and right side windows are divided by timber mullions. Fill
    # their individual panes rather than tinting the wood with the glass.
    for left, right in ((.029, .063), (.071, .115), (.914, .945), (.953, .995)):
        for top, bottom in ((.212, .273), (.282, .341), (.349, .408), (.416, .475), (.484, .541)):
            draw.rectangle((round(left * w), round(top * h), round(right * w), round(bottom * h)), fill=255)
    pixels, selected = original.load(), mask.load()
    for y in range(round(.195 * h), round(.60 * h)):
        for left, right in ((.020, .118), (.912, 1.0)):
            for x in range(round(left * w), min(w, round(right * w))):
                r, g, b = pixels[x, y]
                if (b > r + 3 and b >= g - 12 and b > 52) or (y < .42 * h and min(r, g, b) > 178 and max(r, g, b) - min(r, g, b) < 38):
                    selected[x, y] = 255
    return mask.filter(ImageFilter.GaussianBlur(.7))


def night_tone(image, factors, lift=(0, 0, 0)):
    """Colour light per channel without laying an opaque grey veil over detail."""
    channels = []
    for channel, factor, offset in zip(image.convert('RGB').split(), factors, lift):
        channels.append(channel.point(lambda value: min(255, max(0, round(value * factor + offset)))))
    return Image.merge('RGB', channels)


def mountain_sky_mask(original):
    """The sky visible through the upper glazing, leaving roof, trees and mountain in front."""
    w, h = SIZE
    opening = Image.new('L', SIZE)
    pen = ImageDraw.Draw(opening)
    for points in (
        ((0, 0), (.19, 0), (.19, .255), (0, .235)),
        ((.208, 0), (.545, 0), (.545, .27), (.208, .27)),
        ((.57, 0), (.77, 0), (.77, .285), (.57, .265)),
    ):
        pen.polygon([(round(x * w), round(y * h)) for x, y in points], fill=255)
    selected = Image.new('L', SIZE)
    source, allowed, result = original.load(), opening.load(), selected.load()
    for y in range(round(.285 * h)):
        for x in range(round(.77 * w)):
            if not allowed[x, y]:
                continue
            r, g, b = source[x, y]
            blue = b > r + 7 and b >= g - 5 and min(r, g, b) > 85
            cloud = min(r, g, b) > 195 and max(r, g, b) - min(r, g, b) < 32
            if blue or cloud:
                # The original sky is much brighter than the blue mountain.
                # Feather by luminance instead of tracing a hard diagonal
                # along the ridge, which looks like a line drawn on the photo.
                result[x, y] = max(0, min(255, round((r - 172) * 255 / 32)))
    return selected.filter(ImageFilter.GaussianBlur(1.2))


def night_mountain(original):
    """Moonlit landscape and local warm light in the same mountain house."""
    w, h = SIZE
    cool = night_tone(original, (.55, .64, .77), (3, 5, 9))
    warm = night_tone(original, (.86, .73, .61), (5, 3, 1))
    interior = Image.new('L', SIZE)
    pen = ImageDraw.Draw(interior)
    pen.polygon(((0, round(.80 * h)), (round(.47 * w), round(.81 * h)),
                 (round(.77 * w), round(.755 * h)), (w, round(.715 * h)), (w, h), (0, h)), fill=230)
    pen.polygon(((round(.79 * w), round(.30 * h)), (w, round(.24 * h)),
                 (w, h), (round(.79 * w), h)), fill=195)
    interior = interior.filter(ImageFilter.GaussianBlur(13))
    result = Image.composite(warm, cool, interior)

    # Keep a single continuous moonlit grade across the landscape. The old
    # threshold-based sky recolouring also selected bright mountain pixels,
    # leaving a conspicuous straight-edged patch across the slope. The mask
    # is still useful to place the moon behind the glass and trees.
    sky = mountain_sky_mask(original)
    result = result.convert('RGBA')

    # Light bounces across the room and the wooden column, not the mountain.
    light = Image.new('L', SIZE)
    pen = ImageDraw.Draw(light)
    pen.ellipse((45, 680, 500, 1120), fill=125)
    pen.ellipse((365, 550, 790, 1010), fill=125)
    pen.ellipse((475, 300, 675, 720), fill=82)
    light = ImageChops.multiply(light.filter(ImageFilter.GaussianBlur(55)), interior)
    lit = night_tone(original, (1.0, .84, .69), (8, 5, 2))
    result = Image.composite(lit, result.convert('RGB'), light).convert('RGBA')

    # A moon behind the glass and small recessed lights beneath the dark beam.
    layer = Image.new('RGBA', SIZE)
    halo = Image.new('L', SIZE)
    pen = ImageDraw.Draw(halo)
    mx, my = round(.29 * w), round(.115 * h)
    pen.ellipse((mx - 27, my - 27, mx + 27, my + 27), fill=135)
    halo = ImageChops.multiply(halo.filter(ImageFilter.GaussianBlur(17)), sky)
    glow = Image.new('RGBA', SIZE, (152, 193, 230, 0)); glow.putalpha(halo)
    layer.alpha_composite(glow)
    moon_mask = Image.new('L', SIZE)
    ImageDraw.Draw(moon_mask).ellipse((mx - 10, my - 10, mx + 10, my + 10), fill=235)
    moon_mask = ImageChops.multiply(moon_mask.filter(ImageFilter.GaussianBlur(.6)), sky)
    moon = Image.new('RGBA', SIZE, (242, 239, 222, 0)); moon.putalpha(moon_mask)
    layer.alpha_composite(moon)
    for x in (round(.25 * w), round(.62 * w)):
        y = round(316 + .10 * x)
        glow_mask = Image.new('L', SIZE)
        ImageDraw.Draw(glow_mask).ellipse((x - 13, y - 8, x + 13, y + 12), fill=145)
        lamp_glow = Image.new('RGBA', SIZE, (255, 170, 78, 0))
        lamp_glow.putalpha(glow_mask.filter(ImageFilter.GaussianBlur(10)))
        layer.alpha_composite(lamp_glow)
        pen = ImageDraw.Draw(layer)
        pen.ellipse((x - 4, y - 2, x + 4, y + 2), fill=(234, 163, 79, 235))
        pen.ellipse((x - 2, y - 1, x + 2, y + 1), fill=(255, 229, 174, 255))
    result.alpha_composite(layer)
    return result.convert('RGB')


def night_house(original):
    """Moonlit windows and a warm room, retaining the photograph's texture."""
    w, h = SIZE
    outside = house_window_mask(original)
    cool = night_tone(original, (.51, .62, .78), (3, 5, 9))
    sky = Image.new('L', SIZE)
    src, dst = original.load(), sky.load()
    for y in range(round(.195 * h), round(.42 * h)):
        for left, right in ((.020, .118), (.235, .811), (.912, 1.0)):
            for x in range(round(left * w), min(w, round(right * w))):
                r, g, b = src[x, y]
                if (b > r + 5 and b >= g - 8) or (min(r, g, b) > 180 and max(r, g, b) - min(r, g, b) < 45):
                    dst[x, y] = 255
    sky = ImageChops.multiply(sky.filter(ImageFilter.GaussianBlur(.8)), outside)
    cool = Image.composite(night_tone(original, (.36, .47, .63), (4, 7, 14)), cool, sky)
    # Match the side-window sea to the separately graded moving central sea.
    side_sea = Image.new('L', SIZE)
    painter = ImageDraw.Draw(side_sea)
    for left, right in ((.029, .063), (.071, .115), (.914, .945), (.953, .995)):
        for top, bottom in ((.416, .475), (.484, .541)):
            painter.rectangle((round(left * w), round(top * h), round(right * w), round(bottom * h)), fill=255)
    darker_water = night_tone(original, (.47, .58, .73), (3, 5, 9))
    cool = Image.composite(darker_water, cool, side_sea.filter(ImageFilter.GaussianBlur(.7)))
    warm = night_tone(original, (.86, .73, .61), (5, 3, 1))
    result = Image.composite(cool, warm, outside).convert('RGBA')

    # Two unobtrusive pendants light the wall and floor, not the exterior.
    light = Image.new('L', SIZE)
    painter = ImageDraw.Draw(light)
    for x in (round(.14 * w), round(.86 * w)):
        painter.ellipse((x - 112, 108, x + 112, 342), fill=125)
        painter.ellipse((x - 170, 610, x + 170, 1050), fill=95)
    light = ImageChops.multiply(light.filter(ImageFilter.GaussianBlur(65)), ImageOps.invert(outside))
    illuminated = night_tone(original, (1.0, .84, .69), (8, 5, 2))
    result = Image.composite(illuminated, result.convert('RGB'), light).convert('RGBA')

    lamps = Image.new('RGBA', SIZE)
    glow = Image.new('L', SIZE)
    p = ImageDraw.Draw(glow)
    for x in (round(.14 * w), round(.86 * w)):
        p.ellipse((x - 17, 141, x + 17, 175), fill=150)
    gold = Image.new('RGBA', SIZE, (255, 183, 90, 0))
    gold.putalpha(glow.filter(ImageFilter.GaussianBlur(13)))
    lamps.alpha_composite(gold)
    p = ImageDraw.Draw(lamps)
    for x in (round(.14 * w), round(.86 * w)):
        p.line((x, 78, x, 145), fill=(47, 36, 30, 230), width=2)
        p.polygon(((x - 9, 150), (x - 5, 143), (x + 5, 143), (x + 9, 150)), fill=(92, 60, 37, 255))
        p.ellipse((x - 5, 148, x + 5, 159), fill=(255, 210, 137, 245))
        p.ellipse((x - 2, 150, x + 2, 156), fill=(255, 239, 194, 255))
    result.alpha_composite(lamps)

    # The moon is restricted to the original sky, so it stays behind leaves.
    lx, ly = HOUSE_LIGHTS['night']['point']
    cx, cy = round(lx * w), round(ly * h)
    halo = Image.new('L', SIZE)
    ImageDraw.Draw(halo).ellipse((cx - 24, cy - 24, cx + 24, cy + 24), fill=150)
    halo = ImageChops.multiply(halo.filter(ImageFilter.GaussianBlur(17)), sky)
    moonlight = Image.new('RGBA', SIZE, (174, 207, 238, 0))
    moonlight.putalpha(halo)
    result.alpha_composite(moonlight)
    disk = Image.new('L', SIZE)
    ImageDraw.Draw(disk).ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=235)
    disk = ImageChops.multiply(disk.filter(ImageFilter.GaussianBlur(.55)), sky)
    moon = Image.new('RGBA', SIZE, (235, 239, 225, 0))
    moon.putalpha(disk)
    result.alpha_composite(moon)
    return result.convert('RGB')


def grade(source, part, kind='house'):
    """Grade the existing picture locally, preserving its composition."""
    image = ImageOps.fit(source.convert('RGB'), SIZE, method=Image.Resampling.LANCZOS)
    if part == 'day':
        return image
    if kind == 'house' and part == 'night':
        return night_house(image)
    if kind == 'mountain' and part == 'night':
        return night_mountain(image)
    settings = {
        'dawn': ((255, 185, 155), .15, .90),
        'dusk': ((242, 133, 94), .22, .72),
        'night': ((70, 102, 145), .34, .43),
    }
    colour, mix, brightness = settings[part]
    result = Image.blend(image, Image.new('RGB', SIZE, colour), mix)
    result = ImageEnhance.Brightness(result).enhance(brightness)
    if kind == 'house':
        # The photograph's sky gets a separate, soft light, but foliage,
        # the frame and furniture retain their detail. This makes the four
        # times of day legible rather than just darkening the whole photo.
        sky = Image.new('L', SIZE)
        pixels, target = image.load(), sky.load()
        for y in range(round(.205 * SIZE[1]), round(.42 * SIZE[1])):
            for left, right in ((.020, .118), (.236, .808), (.912, 1.0)):
                for x in range(round(left * SIZE[0]), min(SIZE[0], round(right * SIZE[0]))):
                    r, g, b = pixels[x, y]
                    if (b >= g - 5 and b > r + 5) or (min(r, g, b) > 185 and max(r, g, b) - min(r, g, b) < 45):
                        target[x, y] = 255
        strength = {'dawn': .24, 'dusk': .35, 'night': .53}[part]
        colour = {'dawn': (250, 168, 168), 'dusk': (242, 116, 94), 'night': (19, 35, 73)}[part]
        tinted = Image.blend(result, Image.new('RGB', SIZE, colour), strength)
        result = Image.composite(tinted, result, sky.filter(ImageFilter.GaussianBlur(2)))
        if part == 'dusk':
            result = sunset_windows(image, result)
    if part == 'night':
        # A little warmth inside the room, without changing the sea or sky.
        warm = Image.blend(result, Image.new('RGB', SIZE, (137, 94, 58)), .14)
        outside = Image.new('L', SIZE)
        ImageDraw.Draw(outside).rectangle((round(.23 * SIZE[0]), round(.18 * SIZE[1]),
                                          round(.82 * SIZE[0]), round(.71 * SIZE[1])), fill=255)
        result = Image.composite(result, warm, outside.filter(ImageFilter.GaussianBlur(4)))
    return result


def water_mask(kind='house'):
    """Only exposed water: the chairs, doorway and sand must remain still."""
    if kind == 'house':
        points = ((.235, .420), (.811, .420), (.811, .510), (.775, .510),
                  (.739, .550), (.650, .556), (.615, .608), (.345, .608),
                  (.320, .540), (.300, .518), (.235, .518))
    else:
        points = ((0, .658), (.375, .658), (.425, .675), (.49, .692), (.57, .713),
                  (.57, .783), (.33, .798), (.12, .790), (.12, .735), (0, .735))
    mask = Image.new('L', SIZE)
    draw = ImageDraw.Draw(mask)
    draw.polygon([(round(x * SIZE[0]), round(y * SIZE[1])) for x, y in points], fill=255)
    if kind == 'mountain':  # the wooden window post is in front of the pool
        draw.rectangle((round(.085 * SIZE[0]), round(.64 * SIZE[1]), round(.12 * SIZE[0]), round(.82 * SIZE[1])), fill=0)
    return mask.filter(ImageFilter.GaussianBlur(1.3))


def sky_mask():
    """The opening above the sea, with the doorway and walls protected."""
    mask = Image.new('L', SIZE)
    ImageDraw.Draw(mask).rectangle((round(.236 * SIZE[0]), round(.205 * SIZE[1]),
                                    round(.808 * SIZE[0]), round(.405 * SIZE[1])), fill=255)
    return mask


class SeaReflection:
    """Broken specular light under the actual sky source, following the water's fine crests.

    This is a photographic compositing approximation, not a fluid simulation.
    Only the alpha varies: room, shore and sky never move with this layer.
    """
    def __init__(self, part):
        light = HOUSE_LIGHTS[part]
        self.point, self.colour, self.strength = light['point'], light['colour'], light['strength']
        w, h = SIZE
        self.box = (round(.235*w), round(.420*h), round(.811*w), round(.610*h))
        x0, y0, x1, y1 = self.box
        width, height = x1-x0, y1-y0
        self.mask = water_mask()
        self.limit = self.mask.crop(self.box)
        self.envelope = Image.new('L', (width,height))
        pixels = self.envelope.load()
        # Reflect the source vertically about the photographed horizon. The
        # higher moon concentrates nearer the viewer; the low sun near the horizon.
        mirror_y = 2*.420*h - self.point[1]*h
        for row in range(height):
            depth = row / max(1,height-1)
            spread = (5 + 45*depth) if part == 'dusk' else (4 + 30*depth)
            vertical = .25 + .75*math.exp(-((y0+row-mirror_y)/(115 if part=='dusk' else 65))**2)
            for col in range(width):
                cross = math.exp(-((x0+col-self.point[0]*w)/spread)**2)
                pixels[col,row] = round(255*cross*vertical)
        rng = random.Random(52651)
        tile = Image.frombytes('L', (max(1,width//4),32), bytes(rng.randrange(256) for _ in range(max(1,width//4)*32)))
        tile = tile.resize((width,32), Image.Resampling.BILINEAR).point(lambda v:max(0,min(255,round((v-116)*2.5))))
        self.texture = Image.new('L', (width,height))
        for y in range(0,height,32): self.texture.paste(tile,(0,y))

    def layer(self, water, phase):
        phase %= 1
        width,height = self.envelope.size
        shift = phase*32
        offset = math.floor(shift)
        texture = ImageChops.offset(self.texture,0,offset)
        if shift-offset:
            texture = Image.blend(texture,ImageChops.offset(texture,0,1),shift-offset)
        # Fine bright ridges in the current photographic wave modulate the
        # highlight. Troughs stay dark instead of acquiring an opaque light stripe.
        luma = water.crop(self.box).convert('L')
        crests = ImageChops.subtract(luma,luma.filter(ImageFilter.GaussianBlur(1.15)),offset=128)
        crests = crests.point(lambda v:max(0,min(255,90+12*(v-128))))
        mesh=[]
        for y in range(0,height,12):
            end=min(height,y+12)
            def drift(row): return (1+3*row/height)*math.sin(TAU*(2*phase+row/68))
            a,b=drift(y),drift(end)
            mesh.append(((0,y,width,end),(a,y,b,end,width+b,end,width+a,y)))
        envelope = self.envelope.transform(self.envelope.size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
        alpha = ImageChops.multiply(envelope,ImageChops.multiply(crests,texture))
        alpha = alpha.point(lambda v:min(255,round(v*self.strength)))
        alpha = ImageChops.add(alpha,envelope.point(lambda v:round(v*.045)))
        alpha = ImageChops.multiply(alpha,self.limit)
        patch = Image.new('RGBA', self.envelope.size,self.colour+(0,))
        patch.putalpha(alpha)
        layer = Image.new('RGBA',SIZE)
        layer.paste(patch,self.box[:2])
        return layer


def shore_wave_state(phase):
    """One crest rolls in, breaks and recedes, three times per 16-second loop."""
    p = (3 * phase) % 1
    t = p / .68 if p < .68 else (p - .68) / .32
    eased = t * t * (3 - 2 * t)
    advance = eased if p < .68 else 1 - .24 * eased
    opacity = math.sin(math.pi * p) ** .8
    return advance, opacity


def shore_foam(day, graded):
    """Keep the photo's own irregular foam, softly separated from the sea."""
    box = (225, 570, 405, 614)
    mask = day.crop(box).convert('L').point(lambda v: min(235, max(0, round((v - 95) * 2.2))))
    edges = Image.new('L', mask.size)
    ImageDraw.Draw(edges).rounded_rectangle((2, 2, mask.width - 3, mask.height - 3), radius=12, fill=255)
    mask = ImageChops.multiply(mask, edges.filter(ImageFilter.GaussianBlur(5)))
    result = graded.crop(box).convert('RGBA')
    result.putalpha(mask)
    return result


class PhotographicOcean:
    """Use real video frames and crossfade their ends without reversing time."""

    def __init__(self, directory, overlap=48):
        self.paths = sorted(Path(directory).glob('frame-*.jpg'))
        if len(self.paths) < 8:
            raise ValueError('At least eight consecutive ocean frames are required')
        self.overlap = min(overlap, len(self.paths) // 4)
        self.length = len(self.paths) - self.overlap

    def _frame_at(self, index):
        with Image.open(self.paths[index + self.overlap]) as picture:
            current = picture.convert('RGB')
        start = self.length - self.overlap
        if index >= start:
            amount = (index - start + 1) / self.overlap
            amount = amount * amount * (3 - 2 * amount)
            with Image.open(self.paths[index - start]) as picture:
                following = picture.convert('RGB').resize(current.size, Image.Resampling.BILINEAR)
            current = Image.blend(current, following, amount)
        return current

    def frame(self, phase):
        # Interpolate rather than repeat source frames when playback is slowed;
        # both the footage and its crossfade continue smoothly at the loop seam.
        position = (phase % 1) * self.length
        index = min(self.length - 1, int(position + 1e-9))
        fraction = max(0.0, position - index)
        current = self._frame_at(index)
        if fraction < 1e-7:
            return current
        following = self._frame_at((index + 1) % self.length)
        return Image.blend(current, following, fraction)


def ocean_grade(image, part, adjustment=(0, 0, 0)):
    """Match the moving water to the lighting of each scene."""
    image = Image.merge('RGB', tuple(channel.point(lambda v, d=delta: max(0, min(255, round(v + d))))
                                     for channel, delta in zip(image.split(), adjustment)))
    if part == 'day':
        return image
    if part == 'night':
        # Match the brighter moonlit window, so moving footage does not appear
        # as a dark horizontal strip over the still horizon.
        return night_tone(image, (.51, .62, .78), (3, 5, 9))
    colour, mix, brightness = {
        'dawn': ((255, 185, 155), .15, .90),
        'dusk': ((242, 133, 94), .22, .72),
    }[part]
    return ImageEnhance.Brightness(Image.blend(image, Image.new('RGB', image.size, colour), mix)).enhance(brightness)


def ocean_mask():
    """Feather the footage into the existing water, preserving the horizon and sand."""
    w, h = SIZE
    mask = Image.new('L', SIZE)
    points = ((.235, .420), (.811, .420), (.811, .510), (.775, .510),
              (.748, .550), (.662, .556), (.625, .608), (.325, .608),
              (.300, .540), (.286, .518), (.235, .518))
    ImageDraw.Draw(mask).polygon([(round(x * w), round(y * h)) for x, y in points], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(6))
    top, bottom = round(.420 * h), round(.610 * h)
    fade = Image.new('L', (1, h))
    for y in range(top, bottom):
        amount = min(1, max(0, (y - top - 18) / 60), max(0, (bottom - y) / 14))
        fade.putpixel((0, y), round(245 * amount))
    return ImageChops.multiply(mask, fade.resize((w, h)))


class PeacefulHouse:
    def __init__(self, image, part, kind='house', highlights=None, ocean=None):
        if part not in PARTS:
            raise ValueError('Unknown time of day')
        self.base = grade(image, part, kind)
        self.part = part
        self.kind = kind
        self.ocean = ocean if kind == 'house' else None
        self.mask = water_mask(kind)
        self.ocean_mask = ocean_mask() if self.ocean else None
        self.ocean_adjustment = (0, 0, 0)
        if self.ocean:
            # Match the source water to the existing photograph once, so the
            # colour does not change or flicker as individual waves pass.
            reference = grade(image, 'day', kind).crop((225, 460, 450, 525))
            first = self.ocean.frame(0)
            water = first.crop((round(first.width * .15), round(first.height * .20),
                                round(first.width * .85), round(first.height * .62)))
            target = ImageStat.Stat(reference).mean
            actual = ImageStat.Stat(water).mean
            self.ocean_adjustment = tuple(max(-40, min(40, t - a)) for t, a in zip(target, actual))
        self.sky = sky_mask() if kind == 'house' else Image.new('L', SIZE)
        self.water_base = self.base
        self.foam = None
        if kind == 'house' and self.ocean is None:
            # The original photo contains a single frozen breaker. Replace
            # just that strip with neighbouring open water, then reuse the
            # actual photographic foam as a travelling, changing crest.
            self.foam = shore_foam(grade(image, 'day', kind), self.base)
            y0, y1 = round(.545 * SIZE[1]), round(.610 * SIZE[1])
            smooth = self.base.crop((0, round(.475 * SIZE[1]), SIZE[0], y0)).resize(
                (SIZE[0], y1 - y0), Image.Resampling.BILINEAR)
            self.water_base = self.base.copy()
            fade = Image.new('L', (1, y1 - y0))
            for y in range(y1 - y0):
                fade.putpixel((0, y), round(255 * min(1, y / 16)))
            self.water_base.paste(smooth, (0, y0), fade.resize(smooth.size))
        self.highlights = None
        if highlights is not None:
            start, stop = (.42, .61) if kind == 'house' else (.65, .82)
            y0, y1 = round(start * SIZE[1]), round(stop * SIZE[1])
            texture = ImageOps.fit(highlights.convert('L'), (SIZE[0], y1 - y0), method=Image.Resampling.LANCZOS)
            # The generated layer is white light on black, not a second photo.
            texture = texture.point(lambda value: max(0, round((value - 12) * .48)))
            self.highlights = Image.new('L', SIZE)
            self.highlights.paste(texture, (0, y0))
        rng = random.Random(8614)
        ranges = (.25, .79, .43, .59) if kind == 'house' else (.01, .57, .66, .79)
        self.glints = [(rng.uniform(ranges[0], ranges[1]), rng.uniform(ranges[2], ranges[3]), rng.uniform(0, TAU), rng.randrange(1, 5)) for _ in range(100)]
        self.reflection = SeaReflection(part) if kind=='house' and part in HOUSE_LIGHTS else None

    def frame(self, phase, *, atmosphere_phase=None):
        phase %= 1
        atmosphere_phase = phase if atmosphere_phase is None else atmosphere_phase % 1
        w, h = SIZE
        water = self.water_base.copy()
        if self.ocean is not None:
            # The whole visible sea is footage of moving water, not a shifted
            # still or a cut-out crest. Keep the furniture and horizon fixed.
            x0, x1 = round(.235 * w), round(.811 * w)
            y0, y1 = round(.420 * h), round(.610 * h)
            clip = ocean_grade(self.ocean.frame(phase), self.part, self.ocean_adjustment)
            # Exclude the source beach so the new shoreline stays blue.
            clip = clip.crop((0, 0, clip.width, round(clip.height * .86)))
            clip = ImageOps.fit(clip, (x1 - x0, y1 - y0), method=Image.Resampling.LANCZOS)
            # Compress the filmed wave vertically, retaining its real timing
            # and a feathered join to the still horizon above it.
            shortened = clip.resize((clip.width, round(clip.height * .72)), Image.Resampling.LANCZOS)
            fade = Image.new('L', (1, shortened.height))
            for row in range(shortened.height):
                fade.putpixel((0, row), round(255 * min(1, row / 20)))
            water.paste(shortened, (x0, y1 - shortened.height), fade.resize(shortened.size))
            frame = Image.composite(water, self.base, self.ocean_mask).convert('RGBA')
        else:
            # The optional mountain pool and older scenes use a mild local warp.
            start, stop = (.42, .61) if self.kind == 'house' else (.65, .82)
            for y in range(round(start * h), round(stop * h), 3):
                depth = (y / h - start) / (stop - start)
                cycles = 3 if self.kind == 'house' else 2
                dx = (1.2 + 2.6 * depth) * math.sin(TAU * (cycles * phase + y / 74))
                dy = (0.8 + 4.0 * depth) * math.sin(TAU * (cycles * phase + y / 120))
                stripe = self.water_base.transform((w, 3), Image.Transform.AFFINE, (1, 0, -dx, 0, 1, y - dy), resample=Image.Resampling.BILINEAR)
                water.paste(stripe, (0, y))
            frame = Image.composite(water, self.base, self.mask).convert('RGBA')
        if self.foam is not None:
            advance, opacity = shore_wave_state(phase)
            wave = ImageOps.mirror(self.foam) if int(phase * 3) % 2 else self.foam
            crest = wave.resize((round(190 + 75 * advance), round(12 + 22 * advance)), Image.Resampling.BILINEAR)
            layer = Image.new('RGBA', SIZE)
            x = round((w - crest.width) / 2 + 4 * math.sin(TAU * 3 * phase))
            y = round(.525 * h + advance * .068 * h - crest.height / 2)
            layer.paste(crest, (x, y))
            intensity = {'dawn': .85, 'day': 1, 'dusk': .76, 'night': .45}[self.part]
            alpha = layer.getchannel('A').point(lambda a: round(a * opacity * intensity))
            layer.putalpha(ImageChops.multiply(alpha, self.mask))
            frame.alpha_composite(layer)
        shine = Image.new('RGBA', SIZE)
        if self.highlights is not None and self.ocean is None:
            shifted = ImageChops.offset(self.highlights, round(4 * math.sin(TAU * phase)), 0)
            opacity = {'dawn': .55, 'day': .75, 'dusk': .50, 'night': .16}[self.part]
            alpha = ImageChops.multiply(shifted.point(lambda value: round(value * opacity)), self.mask)
            shine.paste((226, 244, 248, 255), (0, 0, w, h))
            shine.putalpha(alpha)
        draw = ImageDraw.Draw(shine)
        intensity = {'dawn': .70, 'day': 1, 'dusk': .65, 'night': .18}[self.part]
        for x, y, offset, length in (() if self.ocean is not None else self.glints):
            t = max(0, math.sin(TAU * (phase * 2) + offset)) ** 6
            px, py = round(x * w), round(y * h)
            draw.line((px, py, px + length, py), fill=(236, 247, 249, round(100 * t * intensity)), width=1)
        shine.putalpha(ImageChops.multiply(shine.getchannel('A'), self.mask))
        frame.alpha_composite(shine)
        if self.reflection is not None:
            frame.alpha_composite(self.reflection.layer(frame,phase))
        if self.kind == 'house':
            # Distant birds enter and leave behind the doorway.
            birds = Image.new('RGBA', SIZE)
            pen = ImageDraw.Draw(birds)
            strength = {'dawn': .7, 'day': .8, 'dusk': .7, 'night': .16}[self.part]
            for offset, y, size in ((0.0, .322, 5), (.14, .337, 4), (.56, .290, 3)):
                p = (atmosphere_phase + offset) % 1
                x = round((.83 - .62 * p) * w)
                cy = round((y + .005 * math.sin(TAU * p)) * h)
                wing = round(1.5 * math.sin(TAU * (5 * atmosphere_phase + offset)))
                pen.line(((x - size, cy - wing), (x - 2, cy), (x, cy + 1),
                          (x + 2, cy), (x + size, cy - wing)),
                         fill=(45, 58, 65, round(160 * strength)), width=1)
            birds.putalpha(ImageChops.multiply(birds.getchannel('A'), self.sky))
            frame.alpha_composite(birds)
        return frame.convert('RGB')


def prepare(source, out, fps=24, seconds=16, previews=False, kind='house', highlights=None, ocean_frames=None):
    out = Path(out)
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    with Image.open(source) as picture:
        original = picture.convert('RGB')
    texture = None
    if highlights:
        with Image.open(highlights) as picture:
            texture = picture.convert('RGB')
    ocean = PhotographicOcean(ocean_frames) if ocean_frames else None
    entries = {}
    scene_id = SCENES[kind]
    for part in PARTS:
        scene = PeacefulHouse(original, part, kind, texture, ocean)
        name = scene_id + '-' + part
        still = scene.frame(0)
        media.save_image(still, out / f'scene-{name}.jpg', quality=92)
        media.save_thumbnail(still, out / f'thumb-{name}.webp')
        if previews:
            for index in range(4):
                media.save_image(scene.frame(index / 4), out / f'preview-{name}-{index}.jpg', quality=90)
            continue
        video = out / f'scene-{name}.webm'
        total = fps * seconds
        width, height, written = media.encode_webm((scene.frame(i / total) for i in range(total)), fps, video,
                                                  crf=18, max_kbps=2200, speed=4)
        entries[name] = media.scene_entry('photo', video.name, 'video', width, height, fps=fps,
                                          loop_seconds=written / fps, still=f'scene-{name}.jpg', focus=(.5, .5))
        media.update_manifest(name, entries[name], directory=out)
        print(f'{part}: {written} frames, {fps} fps, {video.stat().st_size // 1024} KiB', flush=True)
    if not previews:
        for ext in ('webm', 'jpg'):
            limit = media.MAX_VIDEO_BYTES if ext == 'webm' else media.MAX_IMAGE_BYTES
            media._write_atomically(out / f'scene-{scene_id}.{ext}', lambda target: shutil.copyfile(out / f'scene-{scene_id}-day.{ext}', target), limit)
        with Image.open(out / f'scene-{scene_id}-day.jpg') as picture:
            media.save_thumbnail(picture, out / f'thumb-{scene_id}.webp')
        default = dict(entries[scene_id + '-day'])
        default['media'] = dict(default['media'], file=f'scene-{scene_id}.webm')
        default['still'] = f'scene-{scene_id}.jpg'
        media.update_manifest(scene_id, default, directory=out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--kind', choices=tuple(SCENES), default='house')
    parser.add_argument('--highlights', type=Path, help='optional locally generated light-on-black water texture')
    parser.add_argument('--ocean-frames', type=Path, help='optional local sequence of real ocean video frames for the house')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--fps', type=int, default=24, choices=(20, 24, 30))
    parser.add_argument('--seconds', type=int, default=16, choices=range(8, 61))
    parser.add_argument('--previews', action='store_true')
    args = parser.parse_args()
    prepare(args.input, args.out, args.fps, args.seconds, args.previews, args.kind, args.highlights, args.ocean_frames)


if __name__ == '__main__':
    main()
