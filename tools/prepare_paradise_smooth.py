"""Prepare an optional, higher-frame-count shoreline locally from the original GIF."""

import argparse
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageChops, ImageFilter, ImageStat

from token_tv import board_beach
from tools.refine_paradise_film import _shore


def _default_mask():
    mask = Image.new('L', (320, board_beach.ROWS))
    pixels = mask.load()
    for y in range(board_beach.ROWS):
        shore = _shore(board_beach.TOP + y)
        for x in range(320):
            distance = x - shore
            alpha = min(1, max(0, (distance + 36) / 16), max(0, (80 - distance) / 20))
            pixels[x, y] = round(alpha * 255)
    return mask.filter(ImageFilter.GaussianBlur(2))


def prepare_smooth(source, destination, *, mask_path=None, replace=False):
    """Write only water48.png; preserve the source, existing still, and old film."""
    destination = Path(destination)
    target = destination / 'water48.png'
    if target.exists() and not replace:
        raise FileExistsError('water48.png already exists; back it up before replacing it')
    with Image.open(source) as video:
        if video.size != (384, 480) or video.n_frames < 25:
            raise ValueError('Expected a 384 x 480 beach GIF with at least 25 frames')
        middle = video.n_frames // 2
        wanted = {round(i * middle / 24) for i in range(25)}
        frames = {}
        for i in range(video.n_frames):
            video.seek(i)
            if i in wanted:
                frames[i] = video.convert('RGB')

    box = (16, 16, 176, 100)
    reference = frames[0].convert('L').resize((192, 240)).crop(box)
    crops = {}
    for index, frame in frames.items():
        grey = frame.convert('L').resize((192, 240))
        candidates = []
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                shifted = grey.crop((box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))
                score = ImageStat.Stat(ImageChops.difference(reference, shifted)).sum[0]
                candidates.append((score, dx, dy))
        _, dx, dy = min(candidates)
        dx, dy = 2 * dx, 2 * dy
        full = frame.crop((6 + dx, 0, 378 + dx, 480)).resize((320, 480), Image.Resampling.LANCZOS)
        water = Image.new('RGB', (320, board_beach.ROWS))
        for y in range(board_beach.TOP, 240):
            t = (y - board_beach.TOP) / (239 - board_beach.TOP)
            source_y = max(0, min(478, 125 + dy + y * 279 / 240 + 70 * t * t))
            row = full.transform((320, 1), Image.Transform.AFFINE, (1, 0, 0, 0, 0, source_y),
                                 resample=Image.Resampling.BICUBIC)
            water.paste(row, (0, y - board_beach.TOP))
        crops[index] = water.resize((board_beach.WIDTH, board_beach.HEIGHT), Image.Resampling.LANCZOS)\
                            .filter(ImageFilter.GaussianBlur(.55))

    if mask_path:
        with Image.open(mask_path) as source_mask:
            if source_mask.size != (320, board_beach.ROWS):
                raise ValueError('The shoreline mask must be 320 x 108')
            mask = source_mask.convert('L')
    else:
        mask = _default_mask()
    mask = mask.resize((board_beach.WIDTH, board_beach.HEIGHT), Image.Resampling.LANCZOS)
    neutral = Image.new('RGB', mask.size, (128, 128, 128))
    film = Image.new('RGB', (board_beach.WIDTH, board_beach.HEIGHT * board_beach.SMOOTH_FRAMES))
    for phase in range(board_beach.SMOOTH_FRAMES):
        index = round(min(phase, board_beach.SMOOTH_FRAMES - phase) * middle / 24)
        difference = ImageChops.subtract(crops[index], crops[0], scale=1, offset=128)
        film.paste(Image.composite(difference, neutral, mask), (0, phase * board_beach.HEIGHT))

    prepared = None
    for colors in (256, 128, 64, 32):
        candidate = film.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        palette = candidate.getpalette()
        words = tuple(board_beach._word(palette[i:i + 3]) for i in range(0, 768, 3))
        try:
            board_beach._encode_smooth(words, candidate.tobytes())
        except ValueError:
            continue
        prepared = candidate
        break
    if prepared is None:
        raise ValueError('The shoreline animation does not fit the board capacity')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with NamedTemporaryFile(dir=destination, suffix='.png', delete=False) as file:
        temporary = Path(file.name)
    try:
        prepared.save(temporary, format='PNG')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gif', type=Path)
    parser.add_argument('--output', type=Path, default=board_beach.ART_DIRECTORY)
    parser.add_argument('--mask', type=Path, help='optional 320 x 108 grayscale shoreline mask')
    parser.add_argument('--replace', action='store_true', help='replace an existing water48.png')
    args = parser.parse_args()
    prepare_smooth(args.gif, args.output, mask_path=args.mask, replace=args.replace)
    print('Prepared the private, smooth shoreline locally.')


if __name__ == '__main__':
    main()
