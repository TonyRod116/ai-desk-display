"""Prepare the explicitly chosen skyline image entirely offline.

The original stays in Downloads. The clean, metadata-free native crop is packaged
so refreshes never depend on the source file, a browser or an external service.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageOps


SIZE = (174, 216)
# Same 29:36 ratio as the art column: retain the moon, orange emblem, aerial
# cruiser, main street and foreground car without distorting the architecture.
CROP = (42, 0, 448, 504)


def prepare(source):
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original)
        if image.width < CROP[2] or image.height < CROP[3]:
            raise ValueError('The skyline crop must fit inside the chosen image')
        crop = image.crop(CROP).convert('RGB').resize(SIZE, Image.Resampling.LANCZOS)
    clean = Image.new('RGB', SIZE)
    clean.paste(crop, (0, 0))
    return clean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'token_tv/assets/neon-city.png')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.out.resolve()
    if source == output:
        parser.error('The original must never be overwritten')
    image = prepare(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format='PNG', optimize=True)


if __name__ == '__main__':
    main()
