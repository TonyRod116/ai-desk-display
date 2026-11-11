"""Make the tablet's private sleeper-train films from locally supplied pictures.

The compartment has a cyan window; four independent landscape pictures travel
behind it. The artwork is deliberately not part of the repository. Encode the
films offline so the tablet can play them with its video decoder instead of
compositing large images on every frame.
"""
import argparse
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media as media  # noqa: E402

SIZE = (672, 900)
PARTS = ('dawn', 'day', 'dusk', 'night')
BRIGHTNESS = {'dawn': .98, 'day': 1.08, 'dusk': 1.0, 'night': .86}
FAR_CYCLES, NEAR_CYCLES = 1, 56
# One panorama circuit now takes eight minutes.  Doubling the near circuits
# preserves the speed of the close trees from the four-minute film.
DEFAULT_SECONDS = 480


def frame_cabin(cabin):
    """Bring the window closer while retaining its curtains, sill and lamp."""
    source = cabin.convert('RGB').resize(SIZE, Image.Resampling.LANCZOS)
    w, h = SIZE
    zoom = .74
    left = round((1 - zoom) * w / 2)
    top = round(.064 * h)
    return source.crop((left, top, left + round(w * zoom), top + round(h * zoom))).resize(SIZE, Image.Resampling.LANCZOS)


def window_mask(cabin):
    """Recover only the cyan placeholder, preserving the lamp in front of it."""
    red, green, blue = cabin.convert('RGB').split()
    cyan = ImageChops.darker(ImageChops.subtract(green, red), ImageChops.subtract(blue, red))
    cyan = cyan.point(lambda v: max(0, min(255, round((v - 20) * 255 / 45))))
    region = Image.new('L', SIZE)
    ImageDraw.Draw(region).rectangle((round(.08 * SIZE[0]), round(.13 * SIZE[1]),
                                     round(.92 * SIZE[0]), round(.90 * SIZE[1])), fill=255)
    return ImageChops.multiply(cyan, region).filter(ImageFilter.GaussianBlur(.35))


def looping_panorama(image, height):
    """Join a photograph to its reflection; the strip always scrolls left."""
    width = max(SIZE[0], round(image.width * height / image.height))
    image = image.convert('RGBA' if image.mode == 'RGBA' else 'RGB').resize((width, height), Image.Resampling.LANCZOS)
    tile = Image.new(image.mode, (width * 2, height))
    tile.paste(image, (0, 0))
    tile.paste(image.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (width, 0))
    return tile


def extended_panorama(image, height, extension=None):
    """Add a separately supplied view before the reflection, with a soft join."""
    width = max(SIZE[0], round(image.width * height / image.height))
    original = image.convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
    extra = ImageOps.fit((extension or image).convert('RGB'), (width, height), method=Image.Resampling.LANCZOS)
    # Bring independently generated scenery into the same light, without
    # changing the original picture at all.
    a, b = ImageStat.Stat(original).mean, ImageStat.Stat(extra).mean
    extra = Image.merge('RGB', tuple(channel.point(lambda v, d=delta: max(0, min(255, round(v + d))))
                                     for channel, delta in zip(extra.split(), (x - y for x, y in zip(a, b)))))
    extra_width, blend = round(width * .7), max(1, width // 8)
    joined = Image.new('RGB', (width + extra_width, height))
    joined.paste(original, (0, 0))
    start = max(0, (width - extra_width - blend) // 2)
    strip = extra.crop((start, 0, start + extra_width + blend, height))
    mask = Image.new('L', (strip.width, 1), 255)
    for x in range(blend):
        mask.putpixel((x, 0), round(255 * x / blend))
    joined.paste(strip, (width - blend, 0), mask.resize(strip.size))
    tile = Image.new('RGB', (joined.width * 2, height))
    tile.paste(joined, (0, 0))
    tile.paste(ImageOps.mirror(joined), (joined.width, 0))
    return tile


def distant_panorama(land):
    """Make a shorter seamless strip, so one circuit moves more slowly.

    The existing panorama contains an outward view followed by its mirror.
    Keep the outward view at its original scale and crossfade its ends over a
    wide overlap. A full circuit in the same film then moves under half as
    fast, without reversing direction or compressing the mountain scenery.
    """
    width, height = land.size
    half = width // 2
    overlap = max(1, half // 8)
    # Preserve the picture's original scale and halve the previous strip's
    # length: one complete circuit still fits the existing eight-minute film,
    # but the distant mountains travel at half their previous speed.
    period = max(overlap, (half - overlap) // 2)
    source = land.crop((0, 0, period + overlap, height)).convert('RGB')
    distance = source.crop((overlap, 0, overlap + period, height))
    transition = Image.new('L', (overlap, 1))
    for x in range(overlap):
        transition.putpixel((x, 0), round(255 * (x + 1) / overlap))
    distance.paste(source.crop((0, 0, overlap, height)), (distance.width - overlap, 0),
                   transition.resize((overlap, height)))
    return distance


def middle_fade(height):
    """Keep the distant ridges behind the lake, land and trackside trees."""
    fade = Image.new('L', (1, height))
    for y in range(height):
        # Keep the shoreline and its buildings opaque.  A narrow, smooth
        # transition in the hazy horizon avoids doubling them as the two
        # landscapes slide past one another.
        value = max(0.0, min(1.0, (y / height - .43) / .09))
        fade.putpixel((0, y), round(255 * value * value * (3 - 2 * value)))
    return fade.resize((SIZE[0], height))


def varied_foreground(image, height):
    """Eight times the old repeat length, keeping the original scroll speed."""
    width = max(SIZE[0], round(image.width * height / image.height))
    source = image.convert('RGBA').resize((width, height), Image.Resampling.LANCZOS)
    tile = Image.new('RGBA', (width * 16, height))
    rng = random.Random(9721)
    # Overlapping transparent plants avoid hard joins and offer varied scale,
    # spacing and lighting. Wrapped copies make the full strip seamless.
    for index in range(16):
        scale = rng.uniform(.76, 1.26)
        plant = source.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)
        if rng.randrange(2):
            plant = ImageOps.mirror(plant)
        alpha = plant.getchannel('A')
        plant = ImageEnhance.Brightness(plant.convert('RGB')).enhance(rng.uniform(.82, 1.12)).convert('RGBA')
        plant.putalpha(alpha)
        x = round(index * width + rng.uniform(-.18, .18) * width)
        y = height - plant.height
        for shift in (-tile.width, 0, tile.width):
            tile.alpha_composite(plant, (x + shift, y))
    return trackside_blur(tile)


def scroll(tile, offset, width):
    """A wraparound crop, so frame zero and frame one are identical."""
    start = round(offset) % tile.width
    out = Image.new(tile.mode, (width, tile.height))
    written = 0
    while written < width:
        length = min(width - written, tile.width - start)
        out.paste(tile.crop((start, 0, start + length, tile.height)), (written, 0))
        written += length
        start = 0
    return out


def trackside_blur(tile, distance=18):
    """A small horizontal motion blur, wrapped so the panorama stays seamless."""
    # Blur premultiplied colour and alpha together to avoid coloured fringes on
    # transparent leaves. Preparing it once keeps playback a plain video.
    mode = tile.mode
    source = tile.convert('RGBa') if mode == 'RGBA' else tile
    result = source.copy()
    for shift in range(1, distance + 1):
        result = Image.blend(result, ImageChops.offset(source, shift, 0), 1 / (shift + 1))
    return result.convert(mode) if mode == 'RGBA' else result


def carriage_jostle(phase):
    """Small, smooth and loopable camera motion from the carriage suspension."""
    angle = 2 * math.pi * (phase % 1)
    x = .65 * math.sin(328 * angle) + .25 * math.sin(664 * angle)
    y = 1.05 * math.sin(584 * angle) + .30 * math.sin(904 * angle)
    return x, y


def jostle_frame(frame, phase):
    """Move the scenery without exposing the image edge or shaking the UI."""
    x, y = carriage_jostle(phase)
    inset = 3
    box = (inset + x, inset + y, SIZE[0] - inset + x, SIZE[1] - inset + y)
    return frame.transform(SIZE, Image.Transform.EXTENT, box, resample=Image.Resampling.BILINEAR)


def key_foreground(picture, part):
    """Separate independently generated plants from their magenta backdrop."""
    picture = picture.convert('RGB')
    red, green, blue = picture.split()
    magenta = ImageChops.darker(ImageChops.subtract(red, green), ImageChops.subtract(blue, green))
    # JPEG compression can leave purple fringing around fine leaves. Reject
    # magenta-dominant edge pixels and remove spill from the remaining fringe.
    alpha = magenta.point(lambda value: max(0, min(255, round((55 - value) * 255 / 40))))
    spill = magenta.point(lambda value: 255 if value > 5 else 0)
    cap = ImageChops.add(green, Image.new('L', green.size, 18))
    red = Image.composite(ImageChops.darker(red, cap), red, spill)
    blue = Image.composite(ImageChops.darker(blue, cap), blue, spill)
    picture = Image.merge('RGB', (red, green, blue))
    # Cut empty space, then tint the foliage to the same light as the view.
    picture = ImageEnhance.Brightness(picture).enhance({'dawn': .74, 'day': .92, 'dusk': .66, 'night': .31}[part])
    picture.putalpha(alpha)
    bbox = picture.getbbox()
    if not bbox or bbox[3] - bbox[1] < 30:
        raise ValueError('Foreground image has no usable foliage')
    return picture.crop((0, max(0, bbox[1] - 3), picture.width, picture.height))


class TrainJourney:
    def __init__(self, cabin, landscape, part, foreground=None, extension=None):
        if part not in PARTS:
            raise ValueError('Unknown time of day')
        source = frame_cabin(cabin)
        self.mask = window_mask(source)
        bounds = self.mask.getbbox()
        if not bounds or bounds[2] - bounds[0] < 100 or bounds[3] - bounds[1] < 100:
            raise ValueError('The compartment needs a clear cyan window')
        self.top, self.height = bounds[1], bounds[3] - bounds[1]
        self.base = ImageEnhance.Brightness(source).enhance(BRIGHTNESS[part])
        self.land = extended_panorama(landscape, self.height, extension)
        self.distance = distant_panorama(self.land)
        self.middle_fade = middle_fade(self.height)

        # Three depths: a slow distant ridge, the original middle landscape,
        # and fast trackside plants. Blending happens offline in the film.
        source = landscape.convert('RGB')
        near = key_foreground(foreground, part) if foreground is not None else source.crop((0, int(source.height * .68), source.width, source.height))
        self.near_height = max(1, round(self.height * (.40 if foreground is not None else .35)))
        self.near = varied_foreground(near, self.near_height) if foreground is not None else trackside_blur(looping_panorama(near, self.near_height))
        self.keyed = foreground is not None
        fade = Image.new('L', (SIZE[0], self.near_height))
        draw = ImageDraw.Draw(fade)
        for y in range(self.near_height):
            draw.line((0, y, SIZE[0], y), fill=round(205 * max(0, (y / self.near_height - .12) / .88)))
        self.fade = fade.filter(ImageFilter.GaussianBlur(3))

    def offsets(self, phase):
        """The established middle and near offsets, unchanged from before."""
        phase %= 1
        far = phase * FAR_CYCLES * self.land.width
        near = phase * NEAR_CYCLES * self.near.width
        return far, near

    def distant_offset(self, phase):
        """The farthest ridge goes left more slowly and completes one loop."""
        return (phase % 1) * self.distance.width

    def frame(self, phase):
        phase %= 1
        view = Image.new('RGB', SIZE)
        far, close = self.offsets(phase)
        view.paste(scroll(self.distance, self.distant_offset(phase), SIZE[0]), (0, self.top))
        view.paste(scroll(self.land, far, SIZE[0]), (0, self.top), self.middle_fade)
        near = scroll(self.near, close, SIZE[0])
        view.paste(near, (0, self.top + self.height - self.near_height), near.getchannel('A') if self.keyed else self.fade)
        return jostle_frame(Image.composite(view, self.base, self.mask), phase)


def prepare(cabin, landscapes, out, *, fps=24, seconds=DEFAULT_SECONDS, previews=False, foreground=None, extensions=None, parts=PARTS):
    out = Path(out)
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    with Image.open(cabin) as source:
        room = source.convert('RGB')
    plants = None
    if foreground:
        with Image.open(foreground) as source:
            plants = source.convert('RGB')
    entries = {}
    for part in parts:
        extra = None
        if extensions and extensions.get(part):
            with Image.open(extensions[part]) as source:
                extra = source.convert('RGB')
        with Image.open(landscapes[part]) as source:
            scene = TrainJourney(room, source, part, plants, extra)
        name = 'infinite-express-' + part
        still = scene.frame(0)
        media.save_image(still, out / f'scene-{name}.jpg', quality=92)
        media.save_thumbnail(still, out / f'thumb-{name}.webp')
        if previews:
            for index in range(4):
                media.save_image(scene.frame(index / 4), out / f'preview-{name}-{index}.jpg', quality=90)
            continue
        video = out / f'scene-{name}.webm'
        total = fps * seconds
        w, h, written = media.encode_webm((scene.frame(i / total) for i in range(total)), fps, video,
                                         crf=36, max_kbps=600, speed=5, qmax=56, rate_cap_kbps=700)
        entries[name] = media.scene_entry('photo', video.name, 'video', w, h, fps=fps,
                                          loop_seconds=written / fps, still=f'scene-{name}.jpg', focus=(.5, .42))
        media.update_manifest(name, entries[name], directory=out)
        print(f'{part}: {written} frames, {fps} fps, {video.stat().st_size // 1024} KiB', flush=True)
    if not previews and 'infinite-express-day' in entries:
        # Keep a fully prepared default for older clients and any missing part.
        import shutil
        for extension in ('webm', 'jpg'):
            source = out / f'scene-infinite-express-day.{extension}'
            destination = out / f'scene-infinite-express.{extension}'
            limit = media.MAX_VIDEO_BYTES if extension == 'webm' else media.MAX_IMAGE_BYTES
            media._write_atomically(destination, lambda target: shutil.copyfile(source, target), limit)
        with Image.open(out / 'scene-infinite-express-day.jpg') as picture:
            media.save_thumbnail(picture, out / 'thumb-infinite-express.webp')
        default = dict(entries['infinite-express-day'])
        default['media'] = dict(default['media'], file='scene-infinite-express.webm')
        default['still'] = 'scene-infinite-express.jpg'
        media.update_manifest('infinite-express', default, directory=out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cabin', required=True, type=Path)
    parser.add_argument('--foreground', type=Path, help='optional locally prepared magenta-backed trackside plants')
    for part in PARTS:
        parser.add_argument('--' + part, required=True, type=Path)
        parser.add_argument('--' + part + '-extension', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--fps', type=int, default=24, choices=(20, 24, 30))
    parser.add_argument('--seconds', type=int, default=DEFAULT_SECONDS, choices=range(8, 481))
    parser.add_argument('--previews', action='store_true')
    parser.add_argument('--parts', nargs='+', choices=PARTS, default=PARTS)
    args = parser.parse_args()
    prepare(args.cabin, {part: getattr(args, part) for part in PARTS}, args.out,
            fps=args.fps, seconds=args.seconds, previews=args.previews, foreground=args.foreground,
            extensions={part: getattr(args, part + '_extension') for part in PARTS}, parts=args.parts)


if __name__ == '__main__':
    main()
