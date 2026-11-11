"""Add occasional photographic wildlife to the existing private house films.

The supplied sprite pictures and the films stay local. The original 18-second
water film is repeated unchanged underneath a longer, loopable wildlife visit.
"""
import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media as media  # noqa: E402

SIZE = (672, 1008)
PARTS = ('dawn', 'day', 'dusk', 'night')
SCENE = 'midnight-video-club'
FPS = 24
LOOPS = 3
SECONDS = 54
RECORDED_SECONDS = 60
RECORDED_WAVE_SECONDS = 15


def recorded_water_phase(frame):
    """Four water cycles per visit, with wildlife on its original 60-second clock."""
    cycle = FPS * RECORDED_WAVE_SECONDS
    return (frame % cycle) / cycle


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def bird_state(phase):
    """A sparrow comes from outside, rests on the table and flies out again."""
    p = phase % 1
    if .06 <= p < .115:
        t = (p - .06) / .055
        e = smooth(t)
        return {'x': .77 - .29 * e, 'y': .36 + .38 * e - .04 * math.sin(math.pi * t),
                'size': 15 + 23 * e, 'alpha': smooth(t * 6), 'fly': True, 'right': False}
    if .115 <= p < .26:
        return {'x': .48, 'y': .74, 'size': 38, 'alpha': 1, 'fly': False, 'right': False}
    if .26 <= p < .315:
        t = (p - .26) / .055
        e = smooth(t)
        return {'x': .48 + .29 * e, 'y': .74 - .38 * e - .05 * math.sin(math.pi * t),
                'size': 38 - 23 * e, 'alpha': smooth((1 - t) * 6), 'fly': True, 'right': True}
    return None


def butterfly_state(phase):
    p = phase % 1
    if not .42 <= p < .78:
        return None
    t = (p - .42) / .36
    return {'x': .80 - .54 * t, 'y': .34 + .045 * math.sin(3 * math.pi * t) + .02 * math.sin(13 * math.pi * t),
            'alpha': smooth(t * 8) * smooth((1 - t) * 8), 'size': 13}


def shaded(image, part):
    alpha = image.getchannel('A')
    factor = {'dawn': .86, 'day': 1, 'dusk': .70, 'night': .44}[part]
    result = ImageEnhance.Brightness(image.convert('RGB')).enhance(factor).convert('RGBA')
    result.putalpha(alpha)
    return result


class HouseLife:
    def __init__(self, directory, part):
        directory = Path(directory)
        if part not in PARTS:
            raise ValueError('Unknown time of day')
        self.birds = []
        for i in range(4):
            with Image.open(directory / f'bird-{i}.png') as image:
                self.birds.append(shaded(image.convert('RGBA'), part))
        with Image.open(directory / 'butterfly.png') as image:
            self.butterfly = shaded(image.convert('RGBA'), part)
        self.part = part

    @staticmethod
    def paste(frame, image, x, y, width, opacity, mirrored=False, body_height=None):
        width = max(1, round(width))
        height = max(1, round(image.height * width / image.width))
        sprite = image.resize((width, height), Image.Resampling.LANCZOS)
        if mirrored:
            sprite = ImageOps.mirror(sprite)
        if opacity < 1:
            sprite.putalpha(sprite.getchannel('A').point(lambda a: round(a * opacity)))
        # The wing-up and wing-down pictures have different bounding boxes.
        # Align their bodies, not their lowest feathers, so flapping cannot
        # make the whole bird jump up and down.
        top = y * SIZE[1] - height if body_height is None else y * SIZE[1] - width * .49 - height * body_height
        frame.alpha_composite(sprite, (round(x * SIZE[0] - width / 2), round(top)))

    def frame(self, phase):
        frame = Image.new('RGBA', SIZE)
        state = bird_state(phase)
        if state and state['alpha'] > 0:
            if not state['fly']:
                shadow = Image.new('L', SIZE)
                x, y = round(state['x'] * SIZE[0]), round(state['y'] * SIZE[1])
                ImageDraw.Draw(shadow).ellipse((x - 14, y - 2, x + 14, y + 3), fill=70)
                shade = Image.new('RGBA', SIZE, (31, 26, 20, 0))
                shade.putalpha(shadow.filter(ImageFilter.GaussianBlur(3)))
                frame.alpha_composite(shade)
            sequence = (0, 1, 2, 1)
            pose = sequence[int((phase * SECONDS) * 8) % len(sequence)] if state['fly'] else 3
            body_height = (.72, .40, .25)[pose] if state['fly'] else None
            self.paste(frame, self.birds[pose], state['x'], state['y'], state['size'], state['alpha'], state['right'], body_height)
        butterfly = butterfly_state(phase)
        if butterfly and butterfly['alpha'] > 0 and self.part != 'night':
            # Small irregular flight through the opening, never a giant decal.
            flutter = .76 + .24 * abs(math.sin(phase * SECONDS * 17))
            self.paste(frame, self.butterfly, butterfly['x'], butterfly['y'],
                       butterfly['size'] * flutter, butterfly['alpha'] * .9)
        return frame


def overlay_video(source, life, destination):
    """Decode one existing water cycle, then composite life and encode 3 cycles."""
    ffmpeg = media.find_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError('No ffmpeg available')
    count = FPS * SECONDS
    with tempfile.TemporaryDirectory(prefix='.house-frames-', dir=destination.parent) as temp:
        pattern = str(Path(temp) / 'frame-%04d.png')
        command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                   '-an', '-c:v', 'png', '-f', 'image2', pattern]
        decoded = subprocess.run(command, capture_output=True, check=False)
        paths = sorted(Path(temp).glob('frame-*.png'))
        if decoded.returncode or len(paths) != FPS * 18:
            raise RuntimeError(f'Failed to decode the existing water film: {decoded.stderr.decode("utf-8", "replace")[:400]}')
        def frames():
            for index in range(count):
                with Image.open(paths[index % len(paths)]) as picture:
                    base = picture.convert('RGBA')
                yield Image.alpha_composite(base, life.frame(index / count)).convert('RGB')
        width, height, written = media.encode_webm(frames(), FPS, destination, crf=18, max_kbps=2200, speed=4)
        if (width, height, written) != (*SIZE, count):
            raise RuntimeError('Incomplete house animation')


def prepare(source, sprites, out, previews=False):
    source, out = Path(source), Path(out)
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    catalog = json.loads((source / 'scenes.json').read_text())['scenes']
    for part in PARTS:
        name = SCENE + '-' + part
        info = catalog[name]
        if info['media'].get('fps') != FPS or info['media'].get('loop_seconds') != 18:
            raise ValueError('Expected the existing 18-second, 24 fps house video')
        life = HouseLife(sprites, part)
        still = source / f'scene-{name}.jpg'
        if previews:
            with Image.open(still) as picture:
                picture = picture.convert('RGBA')
            for phase in (.08, .13, .245, .29, .54):
                media.save_image(Image.alpha_composite(picture, life.frame(phase)), out / f'preview-{part}-{phase:.3f}.jpg')
            continue
        for filename in (f'scene-{name}.jpg', f'thumb-{name}.webp'):
            shutil.copyfile(source / filename, out / filename)
        video = out / f'scene-{name}.webm'
        overlay_video(source / f'scene-{name}.webm', life, video)
        entry = media.scene_entry('photo', video.name, 'video', *SIZE, fps=FPS,
                                  loop_seconds=SECONDS, still=f'scene-{name}.jpg', focus=(.5, .5))
        media.update_manifest(name, entry, directory=out)
        print(f'{part}: {SECONDS} seconds, {video.stat().st_size // 1024} KiB', flush=True)
    if not previews:
        for suffix in ('webm', 'jpg'):
            shutil.copyfile(out / f'scene-{SCENE}-day.{suffix}', out / f'scene-{SCENE}.{suffix}')
        shutil.copyfile(out / f'thumb-{SCENE}-day.webp', out / f'thumb-{SCENE}.webp')
        media.update_manifest(SCENE, media.scene_entry('photo', f'scene-{SCENE}.webm', 'video', *SIZE,
                              fps=FPS, loop_seconds=SECONDS, still=f'scene-{SCENE}.jpg', focus=(.5, .5)), directory=out)


def prepare_recorded_house(source, ocean_frames, sprites, out, *, parts=PARTS):
    """Render real water and the same wildlife together in one 60-second loop."""
    from scripts.prepare_tablet_peaceful_house import PeacefulHouse, PhotographicOcean

    out = Path(out)
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    with Image.open(source) as picture:
        photo = picture.convert('RGB')
    ocean = PhotographicOcean(ocean_frames)
    for part in parts:
        name = SCENE + '-' + part
        sea = PeacefulHouse(photo, part, ocean=ocean)
        life = HouseLife(sprites, part)
        still = sea.frame(0)
        media.save_image(still, out / f'scene-{name}.jpg', quality=92)
        media.save_thumbnail(still, out / f'thumb-{name}.webp')
        # Keep wildlife at its natural pace while the sea completes four
        # 15-second cycles, returning cleanly at the end of the visit.
        loop_seconds = RECORDED_SECONDS
        count = FPS * loop_seconds

        def frames():
            for index in range(count):
                water = sea.frame(recorded_water_phase(index)).convert('RGBA')
                yield Image.alpha_composite(water, life.frame(index / count)).convert('RGB')

        video = out / f'scene-{name}.webm'
        width, height, written = media.encode_webm(frames(), FPS, video, crf=18, max_kbps=2200, speed=4)
        if (width, height, written) != (*SIZE, count):
            raise RuntimeError('Incomplete house animation')
        media.update_manifest(name, media.scene_entry('photo', video.name, 'video', *SIZE, fps=FPS,
                              loop_seconds=loop_seconds, still=f'scene-{name}.jpg', focus=(.5, .5)), directory=out)
        print(f'{part}: {written} frames, {FPS} fps, {video.stat().st_size // 1024} KiB', flush=True)
    if 'day' in parts:
        for suffix in ('webm', 'jpg'):
            shutil.copyfile(out / f'scene-{SCENE}-day.{suffix}', out / f'scene-{SCENE}.{suffix}')
        shutil.copyfile(out / f'thumb-{SCENE}-day.webp', out / f'thumb-{SCENE}.webp')
        media.update_manifest(SCENE, media.scene_entry('photo', f'scene-{SCENE}.webm', 'video', *SIZE,
                              fps=FPS, loop_seconds=loop_seconds, still=f'scene-{SCENE}.jpg', focus=(.5, .5)), directory=out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='existing 18-second house films')
    parser.add_argument('--input', type=Path, help='house photo for a new recorded-ocean film')
    parser.add_argument('--ocean-frames', type=Path, help='local source ocean frames')
    parser.add_argument('--sprites', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--previews', action='store_true')
    parser.add_argument('--parts', nargs='+', choices=PARTS, default=PARTS, help='only rebuild selected recorded-ocean dayparts')
    args = parser.parse_args()
    if args.input and args.ocean_frames and not args.source and not args.previews:
        prepare_recorded_house(args.input, args.ocean_frames, args.sprites, args.out, parts=args.parts)
    elif args.source and not args.input and not args.ocean_frames:
        prepare(args.source, args.sprites, args.out, args.previews)
    else:
        parser.error('Supply --source, or --input and --ocean-frames without --previews')
