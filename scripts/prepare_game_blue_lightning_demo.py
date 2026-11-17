"""Prepare original geometric flight stand-ins; no ROM, reference or external art."""
import argparse
import fcntl
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import prepare_game_token_run as packer, tablet_media as media  # noqa: E402

NAME = 'blue-lightning'


def aircraft(attitude=0, colour='#459ecb'):
    image = Image.new('RGBA', (48, 44))
    g = ImageDraw.Draw(image)
    g.polygon([(24, 3 + attitude), (20, 17), (4, 27), (4, 31), (19, 27),
               (20, 37), (16, 41), (32, 41), (28, 37), (29, 27), (44, 31),
               (44, 27), (28, 17)], fill='#17334d')
    g.polygon([(24, 6 + attitude), (21, 20), (8, 28), (21, 25), (23, 36),
               (25, 36), (27, 25), (40, 28), (27, 20)], fill=colour)
    g.rectangle((23, 12 + attitude, 25, 23), fill='#bce8e9')
    for x in (18, 28):
        g.rectangle((x, 27, x + 2, 35), fill='#274d68')
        g.rectangle((x, 36, x + 2, 39), fill='#f7a957')
    return image, (24, 25)


def bank(image, anchor, angle):
    canvas = Image.new('RGBA', (96, 96))
    canvas.paste(image, (48 - anchor[0], 48 - anchor[1]))
    canvas = canvas.rotate(angle, resample=Image.Resampling.NEAREST, center=(48, 48))
    box = canvas.getbbox()
    return canvas.crop(box), (48 - box[0], 48 - box[1])


def prepare_assets(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if list(directory.glob('scene-blue-lightning.*')) or list(directory.glob('thumb-blue-lightning.*')):
        raise FileExistsError('Flight scene files already exist; choose another output folder')
    frames, families = {}, {}
    for family, attitude in (('level', 0), ('up', -3), ('down', 3)):
        families[family] = []
        for i, angle in enumerate((0, 22.5, 45, 67.5, 90)):
            name = f'player-{family}-{i}'
            frames[name] = bank(*aircraft(attitude), angle)
            families[family].append(name)
    for family, attitude in (('up', -1), ('down', 1)):
        name = f'player-{family}-transition'
        frames[name] = aircraft(attitude)
        families[family + '_transition'] = name
    for i in range(6):
        frames[f'player-{i}'] = bank(*aircraft(), i * 18)
    for model, colour in enumerate(('#d48864', '#9bb69c')):
        image, anchor = aircraft(colour=colour)
        for width in (5, 7, 10, 14, 18, 24, 32, 42, 54):
            scale = width / image.width
            frames[f'enemy-{model}-{width}'] = (
                image.resize((width, max(1, round(image.height * scale))), Image.Resampling.NEAREST),
                (round(anchor[0] * scale), round(anchor[1] * scale)))
    cloud_widths, clouds = [16, 24, 36, 54, 80, 120, 180], []
    for style, (w, h) in enumerate(((111, 30), (159, 38))):
        image = Image.new('RGBA', (w, h))
        g = ImageDraw.Draw(image)
        g.rectangle((0, h // 2, w - 1, h - 1), fill='#adcbd5')
        for left, top, right in ((.06, .28, .42), (.24, .04, .68), (.59, .24, .94)):
            g.rectangle((round(w * left), round(h * top), round(w * right), h * 3 // 4), fill='#e8f4f5')
        names = []
        for nominal in cloud_widths:
            size = (max(1, round(w * nominal / 159)), max(1, round(h * nominal / 159)))
            name = f'cloud-pose-{style}-{nominal}'
            frames[name] = (image.resize(size, Image.Resampling.NEAREST), (size[0] // 2, size[1] // 2))
            names.append(name)
        clouds.append({'frames': names, 'source_size': [w, h], 'source_anchor': [w // 2, h // 2], 'flips': [[False, False]]})
    positions, atlas = packer.pack(frames, width=512)
    data = packer.describe(frames, {}, positions, atlas)
    data.update(scene=NAME, asset_origin='procedural_demo',
                aircraft_poses={'version': 1, 'bank_angles': [0, 22.5, 45, 67.5, 90], 'right_flip': True,
                                **families, 'evidence': 'procedural_demo'},
                cloud_poses={'version': 1, 'anchor_mode': 'visual_center', 'widths': cloud_widths,
                             'reference_width': 159, 'poses': clouds, 'draw_mode': 5, 'transparent_index': 0,
                             'evidence': 'procedural_demo'})
    png = directory / f'scene-{NAME}.png'
    media._write_atomically(png, lambda path: atlas.save(path, format='PNG', optimize=True), media.MAX_IMAGE_BYTES)
    data['atlas_sha256'] = hashlib.sha256(png.read_bytes()).hexdigest()
    media._write_atomically(directory / f'scene-{NAME}.json', lambda path: path.write_text(json.dumps(data), encoding='utf-8'), 512 * 1024)
    thumb = Image.new('RGB', (240, 160), '#83c2d5')
    g = ImageDraw.Draw(thumb)
    g.polygon([(0, 90), (120, 70), (240, 90), (240, 160), (0, 160)], fill='#6b955d')
    jet, _anchor = bank(*aircraft(), 22.5)
    thumb.paste(jet, (120 - jet.width // 2, 115 - jet.height // 2), jet)
    media.save_thumbnail(thumb, directory / f'thumb-{NAME}.webp')
    return media.scene_entry('game', png.name, 'image', *atlas.size, data=f'scene-{NAME}.json')


def _catalogue(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Scene catalogue contains duplicate keys')
            result[key] = value
        return result
    def invalid_number(_value):
        raise ValueError('Scene catalogue contains a non-finite number')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {'version': 2, 'scenes': {}}, None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 64 * 1024:
            raise ValueError('Scene catalogue is not a bounded regular file')
        raw = stream.read(64 * 1024 + 1)
    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_number)
    if (not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 2
            or not isinstance(data.get('scenes'), dict)):
        raise ValueError('Scene catalogue has an unexpected structure')
    return data, raw


def prepare_scene(directory):
    """Publish a new demo under the catalogue lock without replacing another scene."""
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(directory / '.scenes.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError('Scene catalogue lock is not a regular file')
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / 'scenes.json'
        catalogue, before = _catalogue(path)
        if NAME in catalogue['scenes']:
            raise FileExistsError('Flight scene is already in the catalogue; choose another folder')
        if list(directory.glob('scene-blue-lightning.*')) or list(directory.glob('thumb-blue-lightning.*')):
            raise FileExistsError('Flight scene files already exist; choose another folder')
        with tempfile.TemporaryDirectory(prefix='.flight-demo-', dir=directory) as temporary:
            stage = Path(temporary)
            entry = prepare_assets(stage)
            updated = {**catalogue, 'scenes': {**catalogue['scenes'], NAME: entry}}
            encoded = json.dumps(updated, allow_nan=False, separators=(',', ':')).encode()
            if len(encoded) > 64 * 1024:
                raise ValueError('Updated scene catalogue exceeds its size limit')
            if _catalogue(path)[1] != before:
                raise RuntimeError('Scene catalogue changed while preparing the demo')
            published = []
            try:
                for name in (f'scene-{NAME}.png', f'scene-{NAME}.json', f'thumb-{NAME}.webp'):
                    source, target = stage / name, directory / name
                    os.link(source, target)  # Atomic creation fails instead of overwriting an existing file.
                    info = source.stat()
                    published.append((target, (info.st_dev, info.st_ino)))
                if _catalogue(path)[1] != before:
                    raise RuntimeError('Scene catalogue changed before publication')
                media._write_atomically(path, lambda target: target.write_bytes(encoded), 64 * 1024)
            except BaseException:
                try:
                    committed = _catalogue(path)[1] == encoded
                except (OSError, ValueError):
                    committed = True  # Unknown commit state: retain complete assets rather than break an entry.
                if not committed:
                    for target, identity in reversed(published):
                        try:
                            info = target.lstat()
                            if (info.st_dev, info.st_ino) == identity:
                                target.unlink()
                        except FileNotFoundError:
                            pass
                raise
        return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare_scene(args.out)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')
    print('Original flight demo prepared. No cartridge or external artwork is needed.')


if __name__ == '__main__':
    main()
