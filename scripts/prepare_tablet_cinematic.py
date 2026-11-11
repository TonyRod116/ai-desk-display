"""Prepare private, seamless tablet films from two separately created portrait stills.

There is no artwork in this script. Coordinates refer to the express's window and
the shop's window and television. The tablet service only serves prepared files.
"""
import argparse
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media as media  # noqa: E402

NAMES = ('infinite-express', 'midnight-video-club')
SIZE = (672, 900)
TAU = 2 * math.pi


def xy(x, y):
    return round(x * SIZE[0]), round(y * SIZE[1])


def polygon_mask(points):
    image = Image.new('L', SIZE, 0)
    ImageDraw.Draw(image).polygon([xy(*p) for p in points], fill=255)
    return image


def clipped(image, mask):
    image.putalpha(ImageChops.multiply(image.getchannel('A'), mask))
    return image


def forest(seed, baseline, height, count):
    """A horizontally repeating silhouette strip underneath the train window."""
    rnd = random.Random(seed)
    image = Image.new('RGBA', SIZE)
    draw = ImageDraw.Draw(image)
    for _ in range(count):
        x = rnd.randrange(SIZE[0])
        h = rnd.randint(round(height * .55), height)
        w = rnd.randint(max(3, h // 7), max(4, h // 4))
        y = round(baseline * SIZE[1]) + rnd.randrange(-5, 6)
        ink = rnd.choice(((5, 19, 30, 115), (6, 24, 35, 135), (12, 29, 38, 125)))
        for cx in (x - SIZE[0], x, x + SIZE[0]):
            draw.rectangle((cx - 1, y - h // 3, cx + 1, y + 3), fill=ink)
            for level in range(3):
                bottom = y - level * h // 5
                top = y - h + level * h // 9
                half = max(2, w - level * w // 5)
                draw.polygon(((cx, top), (cx - half, bottom), (cx + half, bottom)), fill=ink)
    return image


def scroll_strip(strip, phase):
    """A complete revolution every loop; adjacent copies meet without a time seam."""
    shift = int((phase % 1) * SIZE[0])
    out = Image.new('RGBA', SIZE)
    for offset in (-SIZE[0], 0, SIZE[0]):
        out.alpha_composite(strip, (offset - shift, 0))
    return out


class Cinematic:
    def __init__(self, name, picture):
        if name not in NAMES:
            raise ValueError('Unknown cinematic scene')
        self.name = name
        self.base = picture.convert('RGB').resize(SIZE, Image.Resampling.LANCZOS).convert('RGBA')
        self.window = polygon_mask(((.184, .30), (.817, .338), (.817, .64), (.80, .66), (.19, .721), (.178, .70)))
        self.window = self.window.filter(ImageFilter.GaussianBlur(1))
        # The foreground trees belong beside the tracks, never on top of them.
        self.near_window = polygon_mask(((.18, .53), (.46, .53), (.43, .62), (.40, .70), (.18, .721)))
        self.near_window = self.near_window.filter(ImageFilter.GaussianBlur(8))
        self.far = forest(80, .535, 28, 85)
        self.near = forest(128, .691, 66, 38)
        self.shop_windows = Image.new('L', SIZE, 0)
        draw = ImageDraw.Draw(self.shop_windows)
        for rect in ((.17, .205, .398, .367), (.414, .205, .832, .367)):
            draw.rectangle((*xy(rect[0], rect[1]), *xy(rect[2], rect[3])), fill=255)
        self.shop_windows = self.shop_windows.filter(ImageFilter.GaussianBlur(.7))
        rnd = random.Random(7865)
        self.drops = [(rnd.random(), rnd.random(), rnd.randrange(1, 4), rnd.randrange(3, 8)) for _ in range(300)]
        self.stars = [(rnd.uniform(.22, .75), rnd.uniform(.09, .25), rnd.uniform(0, TAU), rnd.randrange(1, 4)) for _ in range(24)]
        self.town = [(rnd.uniform(.28, .54), rnd.uniform(.485, .535), rnd.uniform(0, TAU)) for _ in range(24)]
        self.neon = Image.new('RGBA', SIZE)
        light = ImageDraw.Draw(self.neon)
        light.rounded_rectangle((*xy(.483, .18), *xy(.666, .191)), radius=4, fill=(79, 233, 255, 80))
        light.rounded_rectangle((*xy(.683, .18), *xy(.858, .191)), radius=4, fill=(255, 158, 88, 70))
        self.neon = self.neon.filter(ImageFilter.GaussianBlur(6))

    def express(self, phase):
        frame = self.base.copy()
        # Both layers travel in the same direction, the nearer one twice as fast.
        frame.alpha_composite(clipped(scroll_strip(self.far, phase), self.window))
        frame.alpha_composite(clipped(scroll_strip(self.near, phase * 2), self.near_window))
        glow = Image.new('RGBA', SIZE)
        draw = ImageDraw.Draw(glow)
        for x, y, offset, radius in self.stars:
            alpha = round(20 + 65 * (.5 + .5 * math.sin(TAU * phase + offset)))
            cx, cy = xy(x, y)
            draw.ellipse((cx - radius / 2, cy - radius / 2, cx + radius / 2, cy + radius / 2), fill=(195, 220, 255, alpha))
        for x, y, offset in self.town:
            alpha = round(35 + 85 * (.5 + .5 * math.sin(TAU * phase + offset)))
            cx, cy = xy(x, y)
            draw.ellipse((cx, cy, cx + 1, cy + 1), fill=(255, 204, 129, alpha))
        frame.alpha_composite(glow)
        return frame.convert('RGB')

    def video_club(self, phase):
        frame = self.base.copy()
        rain = Image.new('RGBA', SIZE)
        draw = ImageDraw.Draw(rain)
        for x, y, cycles, length in self.drops:
            px = round(x * SIZE[0])
            py = round(((y + phase * cycles) % 1) * SIZE[1])
            draw.line((px, py, px - 1, py + length), fill=(165, 206, 230, 60), width=1)
        frame.alpha_composite(clipped(rain, self.shop_windows))
        tv = Image.new('RGBA', SIZE)
        draw = ImageDraw.Draw(tv)
        x0, y0 = xy(.459, .394)
        x1, y1 = xy(.565, .451)
        for row, y in enumerate(range(y0, y1, 2)):
            flicker = .5 + .5 * math.sin(TAU * (phase * 3 + row * .21))
            draw.line((x0 + 2, y, x1 - 2, y), fill=(140, 220, 250, round(8 + 42 * flicker)), width=1)
        frame.alpha_composite(tv)
        breath = .45 + .20 * math.sin(TAU * phase)
        halo = self.neon.copy()
        halo.putalpha(halo.getchannel('A').point(lambda value: round(value * breath)))
        frame.alpha_composite(halo)
        return frame.convert('RGB')

    def frame(self, phase):
        phase %= 1
        return self.express(phase) if self.name == 'infinite-express' else self.video_club(phase)


def prepare(name, source, out, fps=24, seconds=10, previews=False):
    with Image.open(source) as image:
        scene = Cinematic(name, image)
    out = Path(out)
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    still = scene.base.convert('RGB')
    media.save_image(still, out / f'scene-{name}.jpg', quality=92)
    media.save_thumbnail(still, out / f'thumb-{name}.webp')
    if previews:
        for i in range(4):
            media.save_image(scene.frame(i / 4), out / f'preview-{name}-{i}.jpg', quality=90)
        return
    total = fps * seconds
    video = out / f'scene-{name}.webm'
    frames = (scene.frame(i / total) for i in range(total))
    width, height, written = media.encode_webm(frames, fps, video, crf=18, max_kbps=2200, speed=4)
    entry = media.scene_entry('photo', video.name, 'video', width, height, fps=fps, loop_seconds=written / fps,
                              still=f'scene-{name}.jpg', focus=(.5, .42))
    media.update_manifest(name, entry, directory=out)
    print(f'{name}: {written} frames, {fps} fps, {written / fps:g} seconds, {video.stat().st_size // 1024} KiB')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=NAMES)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--fps', type=int, default=24, choices=(20, 24, 30))
    parser.add_argument('--seconds', type=int, default=10, choices=range(4, 31))
    parser.add_argument('--previews', action='store_true')
    args = parser.parse_args()
    prepare(args.name, args.input, args.out, args.fps, args.seconds, args.previews)


if __name__ == '__main__':
    main()
