"""Refine the selected private beach film without changing its original files."""

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from token_tv.board_beach import BOAT_H, BOAT_W, BOAT_X, BOAT_Y, FRAMES, HEIGHT, TOP, WIDTH


# Approximate shoreline in the user's approved crop, in screen coordinates.
COAST = ((132, 120), (140, 105), (150, 88), (160, 81), (170, 85), (180, 93),
         (190, 105), (200, 119), (210, 135), (220, 149), (230, 160), (240, 173))
RETURN = (0, 1, 3, 5, 6, 5, 3, 1)


def _shore(y):
    for (y0, x0), (y1, x1) in zip(COAST, COAST[1:]):
        if y <= y1:
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
    return COAST[-1][1]


def returning_water(film):
    """Reverse the shoreline wash, retaining independent motion in the open sea."""
    if film.mode != 'P' or film.size != (WIDTH, HEIGHT * FRAMES):
        raise ValueError('Invalid private water film')
    source = film.convert('RGB').load()
    result = Image.new('RGB', film.size)
    pixels = result.load()
    for phase in range(FRAMES):
        for y in range(HEIGHT):
            shore = _shore(TOP + 2 * y + 1)
            for x in range(WIDTH):
                distance = 2 * x + 1 - shore
                blend = max(0, min(1, (65 - distance) / 30))
                a = source[x, phase * HEIGHT + y]
                b = source[x, RETURN[phase] * HEIGHT + y]
                pixels[x, phase * HEIGHT + y] = tuple(round(a[c] * (1 - blend) + b[c] * blend)
                                                      for c in range(3))
    return result.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def swaying_boat(photo):
    """Tilt the photographed sails about the hull, leaving the background fixed."""
    if photo.size != (320, 240):
        raise ValueError('Invalid private beach photo')
    patch = photo.convert('RGB').crop((BOAT_X, BOAT_Y, BOAT_X + BOAT_W, BOAT_Y + BOAT_H))

    # The triangular mask isolates the actual photographed sails and mast.
    scale = 4
    mask = Image.new('L', (BOAT_W * scale, BOAT_H * scale))
    polygon = ((17, 1), (20, 1), (34, 46), (34, 49), (4, 49), (4, 46))
    ImageDraw.Draw(mask).polygon([(x * scale, y * scale) for x, y in polygon], fill=255)
    mask = mask.resize((BOAT_W, BOAT_H), Image.Resampling.LANCZOS)

    # Interpolate only the hidden sky behind the sails; the visible photo and
    # the hull outside the mask never move.
    clean = patch.copy()
    src, alpha, dst = patch.load(), mask.load(), clean.load()
    for y in range(BOAT_H):
        covered = [x for x in range(BOAT_W) if alpha[x, y] > 8]
        if not covered:
            continue
        left, right = max(0, covered[0] - 2), min(BOAT_W - 1, covered[-1] + 2)
        for x in range(left + 1, right):
            t = (x - left) / (right - left)
            fill = tuple(round(src[left, y][c] * (1 - t) + src[right, y][c] * t) for c in range(3))
            a = alpha[x, y] / 255
            dst[x, y] = tuple(round(src[x, y][c] * (1 - a) + fill[c] * a) for c in range(3))
    sail = patch.convert('RGBA')
    sail.putalpha(mask)
    neutral = Image.new('RGB', patch.size, (128, 128, 128))
    feather = Image.new('L', patch.size)
    feather.putdata([round(255 * min(1, min(x, y, BOAT_W - 1 - x, BOAT_H - 1 - y) / 4))
                     for y in range(BOAT_H) for x in range(BOAT_W)])
    result = Image.new('RGB', (BOAT_W, BOAT_H * 4))
    for phase, displacement in enumerate((0, 5, 0, -5)):
        if displacement:
            factor = displacement / 50
            shifted = sail.transform(patch.size, Image.Transform.AFFINE,
                                     (1, factor, -displacement, 0, 1, 0),
                                     resample=Image.Resampling.BICUBIC)
            moved = Image.alpha_composite(clean.convert('RGBA'), shifted).convert('RGB')
        else:
            moved = patch
        difference = ImageChops.subtract(moved, patch, scale=1, offset=128)
        result.paste(Image.composite(difference, neutral, feather), (0, phase * BOAT_H))
    return result.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def refine(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('Choose a separate output directory to preserve the original film')
    with Image.open(source / 'background.png') as image:
        photo = image.convert('RGB')
    with Image.open(source / 'water.png') as image:
        water = returning_water(image)
    boat = swaying_boat(photo)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    photo.save(destination / 'background.png')
    water.save(destination / 'water.png')
    boat.save(destination / 'boat.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    refine(args.source, args.destination)
    print('Prepared a returning wave and a swaying boat locally.')
