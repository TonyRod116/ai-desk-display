"""Prepare Tony's selected GIF locally; the original never enters the repo."""

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat

from token_tv.board_beach import (ART_DIRECTORY, BOAT_FRAMES, BOAT_H, BOAT_W, BOAT_X, BOAT_Y,
                                  FRAMES, HEIGHT, TOP, WIDTH)


def prepare(source, destination):
    with Image.open(source) as video:
        if video.size != (384, 480) or video.n_frames < FRAMES:
            raise ValueError('Expected the selected 384 x 480 animated beach GIF')
        selected = {round(index * video.n_frames / FRAMES) for index in range(FRAMES)}
        frames = []
        for index in range(video.n_frames):
            video.seek(index)
            if index in selected:
                frames.append(video.convert('RGB'))

    # Match static clouds and palms to the first frame before cropping. Sky and
    # the sailboat then come from that still; only the water and sand animate.
    box = (16, 16, 176, 100)
    reference = frames[0].convert('L').resize((192, 240)).crop(box)
    crops = []
    for frame in frames:
        grey = frame.convert('L').resize((192, 240))
        candidates = []
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                shifted = grey.crop((box[0]+dx, box[1]+dy, box[2]+dx, box[3]+dy))
                score = ImageStat.Stat(ImageChops.difference(reference, shifted)).sum[0]
                candidates.append((score, dx, dy))
        _, dx, dy = min(candidates)
        dx, dy = 2*dx, 2*dy
        crop = frame.crop((6+dx, 125+dy, 378+dx, 404+dy))
        photo = crop.resize((320, 240), Image.Resampling.LANCZOS)
        # Keep the approved boat/sky exactly as framed. The animated foam is
        # farther down in the portrait GIF, beyond a plain 4:3 crop. Bring that
        # foreground into the lower part with a smooth perspective adjustment:
        # its slope matches the original crop at TOP, so there is no hard seam.
        full_height = frame.crop((6+dx, 0, 378+dx, 480)).resize((320, 480), Image.Resampling.LANCZOS)
        for y in range(TOP, 240):
            t = (y - TOP) / (239 - TOP)
            source_y = max(0, min(478, 125 + dy + y * 279 / 240 + 70 * t * t))
            row = full_height.transform((320, 1), Image.Transform.AFFINE,
                                        (1, 0, 0, 0, 0, source_y), resample=Image.Resampling.BICUBIC)
            photo.paste(row, (0, y))
        crops.append(photo)

    film = Image.new('RGB', (WIDTH, HEIGHT * FRAMES))
    water_frames = [crop.crop((0, TOP, 320, 240)).resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
                    .filter(ImageFilter.GaussianBlur(.55)) for crop in crops]
    for index, water in enumerate(water_frames):
        # Quantise the change from frame zero, not two unrelated photo colours:
        # that avoids coloured speckle while retaining the sharp original still.
        difference = ImageChops.subtract(water, water_frames[0], scale=1, offset=128)
        film.paste(difference, (0, index * HEIGHT))
    film = film.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)

    # Reuse the selected GIF's own sailboat movement. Only this little patch
    # moves; feather its edges into the fixed photograph to avoid a moving seam.
    boat_box = (BOAT_X, BOAT_Y, BOAT_X + BOAT_W, BOAT_Y + BOAT_H)
    still_boat = crops[0].crop(boat_box)
    neutral = Image.new('RGB', (BOAT_W, BOAT_H), (128, 128, 128))
    feather = Image.new('L', (BOAT_W, BOAT_H))
    feather.putdata([round(255 * min(1, min(x, y, BOAT_W - 1 - x, BOAT_H - 1 - y) / 4))
                     for y in range(BOAT_H) for x in range(BOAT_W)])
    boat = Image.new('RGB', (BOAT_W, BOAT_H * BOAT_FRAMES))
    for index in range(BOAT_FRAMES):
        current = crops[index * FRAMES // BOAT_FRAMES].crop(boat_box)
        difference = ImageChops.subtract(current, still_boat, scale=1, offset=128)
        boat.paste(Image.composite(difference, neutral, feather), (0, index * BOAT_H))
    boat = boat.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    crops[0].save(destination / 'background.png')
    film.save(destination / 'water.png')
    boat.save(destination / 'boat.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gif', type=Path)
    parser.add_argument('--output', type=Path, default=ART_DIRECTORY)
    args = parser.parse_args()
    prepare(args.gif, args.output)
    print('Prepared the private beach background and water animation locally.')


if __name__ == '__main__':
    main()
