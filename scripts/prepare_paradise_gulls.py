"""Rig a Paradise gull from the private wildlife sheet already on the tablet."""

import argparse
import math
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.tablet_media import MAX_IMAGE_BYTES, _write_atomically


CELL = 128
MARKER = (44, 183, 221, 255)
MARKER_AT = (511, 767)


def mask_at(size, outline):
    mask = Image.new('L', size)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(0.56))


def layer(gull, mask):
    part = gull.copy()
    part.putalpha(ImageChops.multiply(gull.getchannel('A'), mask))
    return part


def beat(wing, joint, original, destination, reach, chord, light):
    """Move the photographic span and chord around a shoulder that stays in place."""
    x, y = joint
    # Inverse affine transform for a back-swept wing with a hinged shoulder.
    skew = (original - destination / chord) / reach
    shape = wing.transform(
        wing.size,
        Image.Transform.AFFINE,
        (1 / reach, 0, x - x / reach, skew, 1 / chord, y - skew * x - y / chord),
        Image.Resampling.BICUBIC,
    )
    corrected = (
        ImageEnhance.Brightness(shape.convert('RGB')).enhance(light).convert('RGBA')
    )
    corrected.putalpha(shape.getchannel('A'))
    return corrected


def frames(gull):
    near_area = mask_at(
        gull.size,
        [
            (0, 23),
            (65, 26),
            (72, 45),
            (74, 54),
            (80, 60),
            (82, 69),
            (76, 74),
            (66, 74),
            (49, 71),
            (41, 56),
            (0, 49),
        ],
    )
    far_area = mask_at(
        gull.size,
        [
            (73, 64),
            (79, 57),
            (94, 50),
            (108, 43),
            (126, 43),
            (126, 62),
            (98, 64),
            (83, 67),
        ],
    )
    front, rear = layer(gull, near_area), layer(gull, far_area)
    body = layer(gull, ImageChops.invert(ImageChops.lighter(near_area, far_area)))
    for index in range(8):
        phase = math.tau * index / 8
        down = math.sin(phase)
        lagged = math.sin(phase - 0.18)
        image = beat(
            rear,
            (77, 64),
            -0.42,
            -0.21 + 0.73 * lagged,
            0.88 - 0.22 * abs(lagged),
            0.70 + 0.15 * abs(lagged),
            1 - 0.14 * max(0, lagged),
        )
        image.alpha_composite(body)
        image.alpha_composite(
            beat(
                front,
                (65, 70),
                0.57,
                0.32 - 0.97 * down,
                0.96 - 0.13 * abs(down),
                0.82 + 0.11 * abs(down),
                1 - 0.12 * max(0, down),
            )
        )
        yield image.resize((64, 64), Image.Resampling.LANCZOS)


def prepare(source, destination):
    with Image.open(source) as raw:
        plate = raw.convert('RGBA')
    if plate.size != (512, 1024):
        raise ValueError('Expected the private 512 × 1024 wildlife atlas.')
    gull = plate.crop((3 * CELL, 0, 4 * CELL, CELL))
    if not gull.getchannel('A').getbbox():
        raise ValueError('The gliding gull pose is missing.')
    for index, frame in enumerate(frames(gull)):
        x = (2 + index // 4) * CELL + index % 2 * 64
        y = 5 * CELL + index % 4 // 2 * 64
        plate.paste(frame, (x, y))
    plate.putpixel(MARKER_AT, MARKER)
    _write_atomically(
        destination,
        lambda file: plate.save(file, format='PNG', optimize=True),
        MAX_IMAGE_BYTES,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination)
