"""Prepare the private photograph cutouts used by the tablet's photo scenes."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.tablet_media import MAX_IMAGE_BYTES, _write_atomically


def sheet(source):
    with Image.open(source) as picture:
        original = picture.convert('RGB')
    if original.width != original.height or original.width % 4 or original.width < 512:
        raise ValueError('Expected a square, four-by-four source sheet')
    return original


def subject(image, row, col):
    size = image.width // 4
    cell = image.crop((col * size, row * size, (col + 1) * size, (row + 1) * size))
    red, green, blue = cell.split()
    purple = ImageChops.subtract(ImageChops.darker(red, blue), green)
    alpha = purple.point(lambda value: max(0, min(255, round((96 - value) * 4))))
    # Remove the magenta contribution from both channels at the feathered edge.
    # Brown fur and leaves have little or no positive excess in both channels.
    spill = purple.point(lambda value: max(0, round((value - 12) * .88)))
    corrected = Image.merge('RGB', (ImageChops.subtract(red, spill), green, ImageChops.subtract(blue, spill)))
    corrected.putalpha(alpha)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError(f'Missing picture in row {row + 1}, column {col + 1}')
    crop = corrected.crop(bounds)
    crop.thumbnail((105, 94), Image.Resampling.LANCZOS)
    return crop


def atlas(source, dogs=None):
    original = sheet(source)
    tile = 128
    result = Image.new('RGBA', (tile * 4, tile * (8 if dogs else 6)))
    for row in range(4):
        for col in range(4):
            crop = subject(original, row, col)
            top = 105 - crop.height if row == 2 else (tile - crop.height) // 2
            result.alpha_composite(crop, (col * tile + (tile - crop.width) // 2, row * tile + top))
    if dogs:
        stride = sheet(dogs)
        for row in range(2):
            for col in range(4):
                crop = subject(stride, row, col)
                result.alpha_composite(crop, (col * tile + (tile - crop.width) // 2, (row + 6) * tile + 107 - crop.height))
    return result


def peel_craft(stock, mask, box, polygon, result, index):
    crop = stock.crop(box).convert('RGBA')
    alpha = Image.new('L', crop.size)
    shape = [(round(x * crop.width), round(y * crop.height)) for x, y in polygon]
    ImageDraw.Draw(alpha).polygon(shape, fill=255)
    crop.putalpha(alpha.filter(ImageFilter.GaussianBlur(.8)))
    crop.thumbnail((110, 105), Image.Resampling.LANCZOS)
    x, y = index % 4 * 128, index // 4 * 128
    result.alpha_composite(crop, (x + (128 - crop.width) // 2, y + (128 - crop.height) // 2))
    ImageDraw.Draw(mask).polygon([(box[0] + x, box[1] + y) for x, y in shape], fill=255)


def paint_clear_air(original, marked, feather):
    """Replace only the marked craft and trail with the surrounding sky."""
    mask = marked.filter(ImageFilter.MaxFilter(feather * 2 + 1)).filter(ImageFilter.GaussianBlur(feather / 2))
    bounds = mask.getbbox()
    restored, stock, m = original.copy(), original.load(), mask.load()
    out = restored.load()
    left, top, right, bottom = bounds
    for x in range(left, right):
        y = top
        while y < bottom:
            if not m[x, y]:
                y += 1
                continue
            start = y
            while y < bottom and m[x, y]:
                y += 1
            span = y - start + 1
            above, below = stock[x, max(0, start - 1)], stock[x, min(original.height - 1, y)]
            for py in range(start, y):
                t, blend = (py - start + 1) / span, m[x, py] / 255
                out[x, py] = tuple(round(a * (1 - blend) + (b * (1 - t) + c * t) * blend)
                                   for a, b, c in zip(stock[x, py], above, below))
    return restored


def prepare_sky(source, destination, result):
    from scripts.tablet_media import save_image

    silhouette = [(0, .45), (.20, .31), (.38, .16), (.60, .13), (.78, .26), (1, .43), (.95, .67),
                  (.69, .79), (.57, .88), (.37, .92), (.25, .77), (.06, .68)]
    city = Image.open(source / 'scene-city.jpg').convert('RGB')
    violet = Image.open(source / 'scene-violet-horizon.jpg').convert('RGB')
    if city.size != (1448, 1086) or violet.size != (3840, 1920):
        raise ValueError('This cutout layout was measured for the current city and violet backgrounds')
    for name, image in (('city', city), ('violet-horizon', violet)):
        mask = Image.new('L', image.size)
        if name == 'city':
            boxes = [(663, 125, 722, 150), (1207, 87, 1280, 118), (696, 236, 747, 255),
                     (1117, 271, 1157, 292), (805, 296, 838, 312)]
            for index, box in enumerate(boxes, 17):
                peel_craft(image, mask, box, silhouette, result, index)
            feather = 8
        else:
            shape = [(0.02, .96), (.28, .65), (.32, .58), (.57, .40), (.69, .15), (.84, .01), (.93, .02),
                     (.96, .73), (.91, .78), (.53, .91), (.19, .97)]
            peel_craft(image, mask, (1544, 390, 1620, 494), shape, result, 16)
            ImageDraw.Draw(mask).line([(0, 18), (200, 64), (400, 120), (650, 190), (800, 220), (950, 247),
                                      (1100, 282), (1250, 332), (1380, 377), (1480, 411), (1560, 443), (1591, 451)],
                                     fill=255, width=49, joint='curve')
            feather = 17
        clean = paint_clear_air(image, mask, feather)
        save_image(clean, destination / f'scene-{name}.jpg', quality=96)


def stage_catalogue(source, out, paradise):
    """Keep the source catalogue's settings, replacing only the prepared scene entries."""
    source = Path(source)
    manifest = json.loads((source / 'scenes.json').read_text())
    scenes = manifest['scenes']
    for name, entry in scenes.items():
        if name in {'city', 'violet-horizon', 'paradise'} or name.startswith(('neon-district', 'midnight-video-club')):
            entry['wildlife'] = True
    city = scenes['city']['live']
    city['clouds'].update(amount=.54, breath=.61, speed=.51)
    city['craft'] = [
        {'kind': 'drone', 'from': [-.16, .380], 'via': [.44, .295], 'to': [1.13, .318], 'size': .011,
         'end_size': .008, 'seconds': 28, 'every': 64, 'delay': 9, 'colour': [.34, .70, 1]},
        {'kind': 'drone', 'from': [1.12, .300], 'via': [.55, .328], 'to': [-.15, .400], 'size': .010,
         'end_size': .008, 'seconds': 23, 'every': 64, 'delay': 34, 'colour': [1, .36, .20]},
    ]
    for row in city['lamps']['rows']:
        row.update(count=11, height=.021, y=.718)
    violet = scenes['violet-horizon']['live']
    violet['clouds'].update(amount=.98, breath=.73, direction=12, speed=.78,
                            regions=[[0, .016, 1, .21], [0, .22, .87, .38]])
    violet['water'].update(amount=1.25, scale=1.08, speed=1.18, feather=.012, glints=.82, glint_size=.52,
                           glint_density=.42, horizon=.902, regions=[[0, .902, 1, 1]])
    violet['lights'].update(amount=1.4, speed=.60, cell=11, out=.26)
    violet['craft'] = [
        {'kind': 'ship', 'from': [1.15, .24], 'via': [.40, .46], 'to': [-.15, .40], 'size': .022,
         'end_size': .011, 'seconds': 24, 'every': 64, 'delay': 18, 'bob': .001, 'colour': [1, .32, .70]},
        {'kind': 'drone', 'from': [-.12, .445], 'via': [.49, .402], 'to': [1.14, .48], 'size': .015,
         'end_size': .008, 'seconds': 22, 'every': 64, 'delay': 37, 'bob': .001, 'colour': [.43, .87, 1]},
    ]
    beach = scenes['paradise']
    beach['live'].pop('craft', None)
    beach['live']['water'].update(amount=.5, speed=1, glints=.98)
    beach['live']['clouds'] = {'amount': .27, 'speed': 1, 'breath': 0, 'regions': [[.626,.429,.767,.611]], 'feather': .014}
    for name, house in scenes.items():
        if not name.startswith('midnight-video-club'):
            continue
        effects = house.setdefault('live', {})
        if name.endswith('-night'):
            effects['water'] = {'amount': .63, 'speed': .87, 'glints': .36, 'glint_size': .66,
                                'regions': [[.236,.417,.807,.592]], 'feather': .012}
        else:
            effects['clouds'] = {'amount': .37, 'speed': 1, 'breath': 0,
                                 'regions': [[.632,.237,.800,.398]], 'feather': .024}
    if paradise:
        generated = json.loads((paradise / 'scenes.json').read_text())['scenes']['paradise']
        beach.update(media=generated['media'], still=generated['still'])
        for name in ('scene-paradise.jpg', 'scene-paradise.webm', 'thumb-paradise.webp'):
            shutil.copyfile(paradise / name, out / name)
    _write_atomically(out / 'scenes.json', lambda target: Path(target).write_text(json.dumps(manifest, separators=(',', ':'))), MAX_IMAGE_BYTES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--sky-sources', type=Path, help='existing private City and Violet Horizon pictures')
    parser.add_argument('--forward-paradise', type=Path, help='output from the forward-only Paradise encoder')
    parser.add_argument('--dogs', type=Path, help='four-by-four generated dog contact sheet')
    args = parser.parse_args()
    image = atlas(args.source, args.dogs)
    if args.sky_sources:
        prepare_sky(args.sky_sources, args.destination.parent, image)
    _write_atomically(args.destination, lambda target: image.save(target, format='PNG', optimize=True), MAX_IMAGE_BYTES)
    if args.sky_sources:
        stage_catalogue(args.sky_sources, args.destination.parent, args.forward_paradise)


if __name__ == '__main__':
    main()
