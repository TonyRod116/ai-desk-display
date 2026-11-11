"""Prepare Tony's own photos for the tablet's photo frame, offline: never by the running service, never from a folder nobody named.

    .venv/bin/python -B -m scripts.prepare_tablet_photos --from ~/Pictures/Frame            # first time
    .venv/bin/python -B -m scripts.prepare_tablet_photos --from ~/Pictures/Frame --replace  # a new set
    .venv/bin/python -B -m scripts.prepare_tablet_photos --from ~/Pictures/More --append    # add to the set

Every picture is turned upright, stripped of all metadata (a photo's GPS position and camera data never reach the tablet), reduced to at most
2400 pixels on its long edge and saved as `photo-NN.jpg` (at most 40, 8 MiB each) in the tablet's private folder, with a `photos.json` that
says how big each is and which point of it to keep in view when the tablet (held upright) crops it. The originals are only read.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media  # noqa: E402

LIMIT = 40
SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}
NAME = re.compile(r'photo-(0[1-9]|[1-3]\d|40)\.jpg')


def focus_of(image):
    """The point of the picture to keep in view when it is cropped to a tall screen: the centre of its local contrast (where the detail is),
    kept away from the very edges. Plain pictures (no detail) stay centred."""
    small = ImageOps.grayscale(image).resize((48, 48), Image.Resampling.BILINEAR)
    pixels = list(small.tobytes())
    total = x_sum = y_sum = 0.0
    for y in range(47):
        for x in range(47):
            here = pixels[y * 48 + x]
            weight = abs(here - pixels[y * 48 + x + 1]) + abs(here - pixels[(y + 1) * 48 + x])
            total += weight
            x_sum += weight * (x + .5)
            y_sum += weight * (y + .5)
    if total < 48:
        return [.5, .5]
    clamp = lambda v: round(min(.8, max(.2, v)), 3)
    return [clamp(x_sum / total / 48), clamp(y_sum / total / 48)]


def upright_clean(path, long_edge):
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)        # turn it as the camera held it
        image = image.convert('RGB')                    # a fresh image: nothing of the original's metadata comes along
    if max(image.size) > long_edge:
        scale = long_edge / max(image.size)
        image = image.resize((max(16, round(image.width * scale)), max(16, round(image.height * scale))), Image.Resampling.LANCZOS)
    return image


def prepare(source, destination=tablet_media.PRIVATE, *, replace=False, append=False, long_edge=2400, quality=88):
    """Prepare the pictures of `source` into `destination`; returns the manifest entries now in force."""
    source, destination = Path(source).expanduser(), Path(destination)
    if not source.is_dir():
        raise ValueError('The folder to read does not exist')
    manifest_path = destination / 'photos.json'
    entries = []
    if manifest_path.exists() and not replace:
        try:
            entries = json.loads(manifest_path.read_text(encoding='utf-8'))['photos']
        except (OSError, ValueError, KeyError, TypeError):
            entries = []
        if entries and not append:
            raise ValueError(f'The frame already has {len(entries)} photos: use --replace for a new set or --append to add to it')
    if replace:
        entries = []
    files = sorted(p for p in source.iterdir() if p.is_file() and not p.name.startswith('.') and p.suffix.lower() in SUFFIXES)
    start = len(entries)
    if not files:
        raise ValueError('That folder has no .jpg, .png or .webp pictures')
    for path in files:
        if len(entries) >= LIMIT:
            break
        try:
            image = upright_clean(path, long_edge)
        except (OSError, ValueError):
            continue                                    # not a readable picture: skipped, said at the end
        name = f'photo-{len(entries) + 1:02d}.jpg'
        tablet_media.save_image(image, destination / name, quality=quality)
        entries.append({'file': name, 'width': image.width, 'height': image.height, 'focus': focus_of(image)})
    if len(entries) == start:
        raise ValueError('None of the pictures could be read')
    if replace:                                         # pictures of an older, longer set that this one does not use
        for old in destination.glob('photo-*.jpg'):
            if NAME.fullmatch(old.name) and old.name not in {e['file'] for e in entries}:
                old.unlink()
    tablet_media._write_atomically(manifest_path, lambda target: target.write_text(json.dumps({'version': 1, 'photos': entries}, indent=1), encoding='utf-8'), 64 * 1024)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--from', dest='source', required=True, help='the folder of pictures to read (it is only read)')
    parser.add_argument('--to', type=Path, default=tablet_media.PRIVATE, help='the tablet private folder (default: the real one)')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--replace', action='store_true', help='make a new set (the old photos are removed from the frame, not from your folder)')
    group.add_argument('--append', action='store_true', help='add these to the photos already in the frame')
    args = parser.parse_args()
    try:
        entries = prepare(args.source, args.to, replace=args.replace, append=args.append)
    except ValueError as error:
        raise SystemExit(str(error))
    print(f'{len(entries)} photos in the frame ({args.to})')


if __name__ == '__main__':
    main()
