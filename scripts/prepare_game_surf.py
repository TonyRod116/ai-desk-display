"""Prepare the private files of the tablet's real-time TIDAL RUSH scene (`token_tv/tablet_web/game-surf.js`), offline.

The scene animates everything that lives (the surfer, the spray, the foam, the gulls, the boat, the palms, the clouds) in code. What it stands in front of is a BACKDROP picture:
the sunset, the sun, the sea with its glitter and the huge curling wave. Tony allowed his own Gemini CLI (text prompts only, his credits) for new art; this script turns such a
"plate" into the scene's atlas. The plate and everything made from it stay PRIVATE (never in Git, docs or tests). Without a plate the scene draws a calmer built-in backdrop and
this script has nothing to prepare, so it fails closed:

    nice -n 15 ionice -c 3 .venv/bin/python -B scripts/prepare_game_surf.py --plates DIR --out DIR [--manifest]

DIR (`--plates`) holds `wave.jpg` (or .png) and `geometry.json`, which says how to crop it and where things are (everything in the final 200 x 320 picture):

    {"crop": {"y0": 147, "x0": 0, "width": null},      the part of the plate that becomes the picture (the width is cut to the picture's 5:8 shape from y0)
     "horizon": 141, "sun": {"x": 40, "y": 120, "r": 22}, "centre": [118, 128], "hole": [118, 128, 40, 34], "tip": [70, 147],
     "path": [20, 80], "line": [[x, y], ...], "lip": [[x, y], ...], "foot": [[x, y], ...],
     "water": [[x, y], ...],                           the wave's silhouette (a closed polygon); above the horizon the rest is sky, below it sea
     "sky": {"top": "#241058", "strength": 0.6, "rows": 80},   optional: the zenith is darkened toward this colour so that stars show
     "colors": 40, "merge": 14}                         the palette size and how close two colours must be to be merged

It writes into `--out`:

    scene-surf.png      the atlas, 200 px wide: `plate` (the picture in its small palette), `maps` (red = class: 0 still, 1 sky, 2 sea, 3 water) and the foam brushes
                        (red = tone, alpha = opacity in four crisp steps)
    scene-surf.json     {"frames": {"plate", "maps", "foam-puff-0", ...}, "geometry": {...}, "brushes": {...}, "scene": "surf", "version": 2}
    thumb-surf.webp     240 x 160 picture for the scene picker (the backdrop and a small surfer)

`--manifest` also adds the scene to the tablet's `scenes.json` in `--out` through `scripts.tablet_media`, REPLACING the previous entry of `surf`. Nothing is written outside `--out`;
no ROM, no game art, no network, no service.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import tablet_media as media  # noqa: E402

NAME = 'surf'
W, H = 200, 320
CLS_STILL, CLS_SKY, CLS_SEA, CLS_WATER = 0, 1, 2, 3
STYLES = {                                   # style: (sizes, noise scale x, noise scale y)
    'puff': (((9, 7), (14, 10), (21, 13), (30, 17)), .20, .26),
    'streak': (((13, 4), (20, 5), (32, 6), (48, 7)), .07, .55),
    'sheet': (((18, 6), (28, 8), (40, 10)), .09, .50),
}
ALPHAS = (0, 120, 200, 255)                  # no soft edges: foam has four opacities
CLEAR = (0, 0, 0, 0)
GEOMETRY_KEYS = ('horizon', 'sun', 'centre', 'hole', 'tip', 'path', 'lip', 'line', 'foot')    # what the scene reads (the scene validates it again)
PLATE_NAMES = ('wave.jpg', 'wave.jpeg', 'wave.png')
PALM_NAMES = ('palm.jpg', 'palm.jpeg', 'palm.png')               # optional: a palm crown on a flat magenta background, for the top left corner
KEY = (255, 0, 255)


class PlateError(ValueError):
    """The plate or its geometry is missing or wrong: nothing is written."""


class Noise:
    """Smooth value noise on a 64 x 64 lattice from a seed (the same idea as the scene's own)."""

    def __init__(self, seed):
        rng = random.Random(seed)
        self.grid = [rng.random() for _ in range(4096)]

    def _at(self, x, y):
        return self.grid[((y & 63) << 6) + (x & 63)]

    def value(self, x, y):
        xi, yi = math.floor(x), math.floor(y)
        fx, fy = x - xi, y - yi
        u, v = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        top = self._at(xi, yi) * (1 - u) + self._at(xi + 1, yi) * u
        bottom = self._at(xi, yi + 1) * (1 - u) + self._at(xi + 1, yi + 1) * u
        return top * (1 - v) + bottom * v

    def fbm(self, x, y, octaves=3):
        total = weight = 0.0
        amplitude, frequency = .5, 1.0
        for _ in range(octaves):
            total += amplitude * self.value(x * frequency, y * frequency)
            weight += amplitude
            amplitude *= .5
            frequency *= 2.03
        return total / weight


def clamp(value, low, high):
    return low if value < low else high if value > high else value


# ---- the foam brushes (unchanged idea: ragged, streaky blobs of tone and alpha, never round bubbles) --------------------------------------------------------------------------

def brush(noise, width, height, style, seed):
    """One foam brush: a ragged ellipse (a long taper for a streak, a flat sheet) eaten and lit by noise; returns an RGBA picture (red/green/blue = tone, alpha = opacity)."""
    _, sx, sy = STYLES[style]
    image = Image.new('RGBA', (width, height), CLEAR)
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            nx, ny = (x + .5) / width * 2 - 1, (y + .5) / height * 2 - 1
            if style == 'streak':
                envelope = 1 - (abs(nx) ** 2.2 * .8 + ny * ny * 1.1)
            elif style == 'sheet':
                envelope = 1 - (nx * nx * .7 + abs(ny) ** 1.6 * 1.3)
            else:
                envelope = 1 - (nx * nx * .95 + ny * ny * 1.25)
            tail = .18 * (nx + 1) * .5 if style == 'streak' else 0
            m = envelope * 1.0 + (noise.fbm(x * sx + seed * 7.3, y * sy + seed * 3.1) - .5) * 1.4 - tail
            if m <= .08:
                continue
            edge = clamp(1 - m * 2.1, 0, 1)                                     # 1 at the ragged rim, 0 in the core: the rim is eaten into lace, the core stays whole
            lace = noise.fbm(x * .55 + seed * 2.3, y * .75 + seed * 1.7, 2)
            if lace < .22 + .46 * edge:
                continue
            alpha = ALPHAS[3] if m > .55 else ALPHAS[2] if m > .3 else ALPHAS[1]
            tone = int(clamp(110 + 160 * clamp((m - .08) / .7, 0, 1) - (30 if ny > .4 else 0) - (34 if lace < .4 else 0) + (noise.value(x * .5, y * .5 + seed) - .5) * 30, 0, 255))
            pixels[x, y] = (tone, tone, tone, alpha)
    return image


def build_brushes():
    """({frame name: RGBA picture}, in a fixed order); every brush is deterministic."""
    noise = Noise(0x5ea)
    frames = {}
    for style, (sizes, _, _) in STYLES.items():
        for i, (w, h) in enumerate(sizes):
            frames[f'foam-{style}-{i}'] = brush(noise, w, h, style, i + len(style))
    return frames


# ---- the backdrop: crop, scale, tint, quantise, classify -----------------------------------------------------------------------------------------------------------------------

def _hex(value):
    text = str(value).lstrip('#')
    if len(text) != 6:
        raise PlateError(f'not a colour: {value!r}')
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def _number(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise PlateError(f'geometry {what} must be a number from {low} to {high}')
    return value


def _points(value, what, low=2, high=400):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise PlateError(f'geometry {what} must be a list of {low} to {high} points')
    out = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise PlateError(f'geometry {what} holds a bad point')
        out.append([_number(point[0], -60, W + 60, what), _number(point[1], -60, H + 60, what)])
    return out


def check_geometry(data):
    """Validate the geometry file (strictly: this is private data, but a typo must not become a broken scene) and return the cleaned geometry and the build options."""
    if not isinstance(data, dict):
        raise PlateError('geometry.json must hold an object')
    crop = data.get('crop') or {}
    options = {
        'y0': int(_number(crop.get('y0', 0), 0, 4000, 'crop.y0')), 'x0': int(_number(crop.get('x0', 0), 0, 4000, 'crop.x0')),
        'width': None if crop.get('width') is None else int(_number(crop['width'], 64, 4000, 'crop.width')),
        'colors': int(_number(data.get('colors', 40), 8, 64, 'colors')), 'merge': _number(data.get('merge', 14), 0, 60, 'merge'),
        'water': _points(data.get('water'), 'water', 4), 'sky': None,
    }
    sky = data.get('sky')
    if sky:
        options['sky'] = {'top': _hex(sky.get('top', '#241058')), 'strength': _number(sky.get('strength', .6), 0, 1, 'sky.strength'), 'rows': int(_number(sky.get('rows', 80), 1, H, 'sky.rows'))}
    geometry = {'horizon': int(_number(data.get('horizon'), 40, H - 40, 'horizon'))}
    sun = data.get('sun') or {}
    geometry['sun'] = {'x': _number(sun.get('x'), -20, W + 20, 'sun.x'), 'y': _number(sun.get('y'), 0, H, 'sun.y'), 'r': _number(sun.get('r'), 3, 59, 'sun.r')}
    geometry['centre'] = _points([data.get('centre')], 'centre', 1, 1)[0]
    hole = data.get('hole')
    if not isinstance(hole, list) or len(hole) != 4:
        raise PlateError('geometry hole must be [cx, cy, rx, ry]')
    geometry['hole'] = [_number(v, 5, 400, 'hole') for v in hole]
    geometry['tip'] = _points([data.get('tip')], 'tip', 1, 1)[0]
    path = data.get('path')
    if not isinstance(path, list) or len(path) != 2:
        raise PlateError('geometry path must be [x0, x1]')
    geometry['path'] = [_number(v, -20, W + 20, 'path') for v in path]
    geometry['lip'] = _points(data.get('lip'), 'lip')
    geometry['line'] = _points(data.get('line'), 'line', 4)
    geometry['foot'] = _points(data.get('foot'), 'foot')
    palm = data.get('palm')
    options['palm'] = None
    if palm:
        if not isinstance(palm, dict):
            raise PlateError('geometry palm must be an object')
        options['palm'] = {'width': int(_number(palm.get('width', 72), 24, 140, 'palm.width')), 'colors': int(_number(palm.get('colors', 16), 6, 32, 'palm.colors')),
                           'x': int(_number(palm.get('x', 0), -60, W, 'palm.x')), 'y': int(_number(palm.get('y', 0), -60, H, 'palm.y')), 'key': int(_number(palm.get('key', 90), 20, 200, 'palm.key'))}
        geometry['palm'] = {'x': options['palm']['x'], 'y': options['palm']['y']}
    return geometry, options


def find_plate(folder, names=PLATE_NAMES, required=True):
    for name in names:
        path = Path(folder) / name
        if path.is_file():
            return path
    if required:
        raise PlateError(f'no wave.jpg or wave.png in {folder}')
    return None


def crop_scale(image, options):
    """The part of the plate that becomes the picture: from (x0, y0), as wide as asked (or to the plate's edge), 5:8, scaled by averaging boxes to 200 x 320."""
    pw, ph = image.size
    x0, y0 = options['x0'], options['y0']
    width = options['width'] or (pw - x0)
    height = round(width * H / W)
    if x0 + width > pw or y0 >= ph or width < 80 or y0 + height > ph + height // 4:
        raise PlateError(f'the crop ({x0}, {y0}, {width} x {height}) does not fit the plate ({pw} x {ph})')
    if y0 + height > ph:                                                       # a little short at the bottom (it is hidden by the dock): mirror the last rows
        extra = y0 + height - ph
        tall = Image.new(image.mode, (pw, ph + extra))
        tall.paste(image, (0, 0))
        tall.paste(image.crop((0, ph - extra, pw, ph)).transpose(Image.Transpose.FLIP_TOP_BOTTOM), (0, ph))
        image = tall
    return image.crop((x0, y0, x0 + width, y0 + height)).resize((W, H), Image.Resampling.BOX)


def classify(geometry, water):
    """Class of every pixel: water inside the silhouette, sky above the horizon outside it, sea below. Returns bytes (W * H)."""
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in water], fill=1)
    horizon = geometry['horizon']
    classes = bytearray(W * H)
    data = mask.tobytes()
    for y in range(H):
        for x in range(W):
            i = y * W + x
            classes[i] = CLS_WATER if data[i] else (CLS_SKY if y < horizon else CLS_SEA)
    return bytes(classes)


def tint_sky(image, classes, sky):
    """Darken the zenith toward a deep violet so that stars show (only sky pixels, strongest at the top row)."""
    if not sky:
        return image
    out = image.copy()
    px, top = out.load(), sky['top']
    for y in range(min(sky['rows'], H)):
        k = sky['strength'] * (1 - y / sky['rows']) ** 1.3
        for x in range(W):
            if classes[y * W + x] == CLS_SKY:
                r, g, b = px[x, y]
                px[x, y] = (round(r + (top[0] - r) * k), round(g + (top[1] - g) * k), round(b + (top[2] - b) * k))
    return out


def quantise(image, colors, merge):
    """A small clean palette: median-cut to `colors`, then colours closer than `merge` (RGB distance) fold into the more frequent one. Returns an RGB picture."""
    q = image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = q.getpalette()[:colors * 3]
    counts = {}
    for index in q.tobytes():
        counts[index] = counts.get(index, 0) + 1
    order = sorted(counts, key=lambda k: (-counts[k], k))
    kept, target = [], {}
    for index in order:
        colour = tuple(palette[index * 3:index * 3 + 3])
        home = next((k for k in kept if math.dist(colour, tuple(palette[k * 3:k * 3 + 3])) <= merge), None)
        if home is None:
            kept.append(index)
            home = index
        target[index] = tuple(palette[home * 3:home * 3 + 3])
    out = Image.new('RGB', image.size)
    out.putdata([target[i] for i in q.tobytes()])
    return out


def build_backdrop(plate, geometry, options):
    """(the picture in its palette, the class map) for a plate image and a checked geometry."""
    picture = crop_scale(plate.convert('RGB'), options)
    classes = classify(geometry, options['water'])
    picture = tint_sky(picture, classes, options['sky'])
    return quantise(picture, options['colors'], options['merge']), classes


def key_palm(image, spec):
    """A sprite from a picture on a flat magenta background: the key colour (and its jpeg fringe) becomes transparent, the rest is scaled by averaging the opaque pixels of each box, a pixel
    is opaque when more than half of its box is, and the colours are quantised to a small palette. Returns an RGBA picture whose alpha is only ever 0 or 255 (the browser then never
    premultiplies it)."""
    image = image.convert('RGB')
    width, height = spec['width'], max(1, round(image.height * spec['width'] / image.width))
    px, sw, sh = image.load(), image.width, image.height
    limit = spec['key'] ** 2 * 3
    opaque = Image.new('L', image.size, 0)
    mask = opaque.load()
    for y in range(sh):
        for x in range(sw):
            r, g, b = px[x, y]
            keyed = (r - KEY[0]) ** 2 + (g - KEY[1]) ** 2 + (b - KEY[2]) ** 2 < limit or (r > 170 and b > 170 and g < 120)
            mask[x, y] = 0 if keyed else 255
    out = []
    for oy in range(height):
        for ox in range(width):
            x0, x1, y0, y1 = ox * sw // width, max(ox * sw // width + 1, (ox + 1) * sw // width), oy * sh // height, max(oy * sh // height + 1, (oy + 1) * sh // height)
            r = g = b = n = 0
            total = (x1 - x0) * (y1 - y0)
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    if mask[xx, yy]:
                        pr, pg, pb = px[xx, yy]
                        r, g, b, n = r + pr, g + pg, b + pb, n + 1
            out.append((r // n, g // n, b // n, 255) if n * 2 > total else None)
    colours = [c[:3] for c in out if c]
    if not colours:
        raise PlateError('the palm picture is empty after keying out its background')
    strip = Image.new('RGB', (len(colours), 1))
    strip.putdata(colours)
    small = list(quantise(strip, spec['colors'], 14).getdata())
    sprite = Image.new('RGBA', (width, height), CLEAR)
    pixels, k = sprite.load(), 0
    for i, c in enumerate(out):
        if c:
            pixels[i % width, i // width] = (*small[k], 255)
            k += 1
    return sprite


# ---- the atlas -------------------------------------------------------------------------------------------------------------------------------------------------------------------

def pack(frames, width=W, gutter=1, top=0):
    """Shelf-pack the pictures, tallest first, below row `top`: ({name: (x, y)}, the height used)."""
    order = sorted(frames, key=lambda name: (-frames[name].height, name))
    x, y, shelf = 0, top, 0
    positions = {}
    for name in order:
        w, h = frames[name].size
        if x + w + gutter > width:
            x, y, shelf = 0, y + shelf + gutter, 0
        positions[name] = (x, y)
        x += w + gutter
        shelf = max(shelf, h)
    return positions, y + shelf


def build_atlas(picture, classes, brushes, palm=None):
    """(atlas picture RGBA, frames) with the plate at the top, the class maps under it and the brushes under those."""
    brushes = dict(brushes)
    if palm is not None:
        brushes['palm'] = palm
    positions, height = pack(brushes, top=2 * H + 1)
    atlas = Image.new('RGBA', (W, height), CLEAR)
    atlas.paste(picture.convert('RGBA'), (0, 0))
    maps = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    maps.putdata([(c, 0, 0, 255) for c in classes])
    atlas.paste(maps, (0, H))
    frames = {'plate': [0, 0, W, H], 'maps': [0, H, W, H]}
    for name, position in positions.items():
        atlas.paste(brushes[name], position)
        frames[name] = [*position, *brushes[name].size]
    return atlas, frames


def draw_surfer(draw, x, y, scale):
    """A tiny slender surfer in coral on an orange board (for the thumbnail), drawn with Pillow at (x, y) = the deck's middle."""
    s = scale
    draw.line((x - 13 * s, y + 3 * s, x + 12 * s, y - 2 * s), fill='#f28a2c', width=int(2.4 * s))
    draw.line((x - 13 * s, y + 4 * s, x + 12 * s, y - 1 * s), fill='#a8441c', width=max(1, int(s)))
    draw.line((x - 4 * s, y - 9 * s, x - 6 * s, y + 1 * s), fill='#c98a66', width=max(1, int(1.6 * s)))
    draw.line((x + 1 * s, y - 9 * s, x + 4 * s, y - 1 * s), fill='#eeb68c', width=max(1, int(1.6 * s)))
    draw.polygon([(x - 6 * s, y - 20 * s), (x - 1 * s, y - 20 * s), (x + 2 * s, y - 9 * s), (x - 4 * s, y - 9 * s)], fill='#f0685a')
    draw.ellipse((x - 6 * s, y - 27 * s, x - 1 * s, y - 21 * s), fill='#eeb68c')
    draw.rectangle((x - 5 * s, y - 28 * s, x - 1 * s, y - 25 * s), fill='#3a2418')
    draw.line((x - 5 * s, y - 18 * s, x - 11 * s, y - 14 * s), fill='#eeb68c', width=max(1, int(1.6 * s)))
    draw.line((x - 1 * s, y - 18 * s, x + 6 * s, y - 20 * s), fill='#eeb68c', width=max(1, int(1.6 * s)))


def thumbnail(picture, geometry, palm=None):
    """A 240 x 160 picture for the scene picker: the part of the backdrop that the dock leaves visible with the palm in its corner, a surfer on the wave and two gulls."""
    picture = picture.copy()
    if palm is not None:
        at = geometry.get('palm', {'x': 0, 'y': 0})
        picture.paste(palm.convert('RGB'), (at['x'], at['y']), palm.getchannel('A'))
    top = max(0, min(H - 134, geometry['horizon'] - 98))
    view = picture.crop((0, top, W, top + 134)).resize((240, 160), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(view)
    sx, sy = 240 / W, 160 / 134
    base = geometry['line'][len(geometry['line']) // 3]
    draw_surfer(draw, max(40, min(200, (base[0] + 22) * sx)), max(60, min(138, (base[1] + 10 - top) * sy)), 1.55)       # always inside the picture
    for gx, gy in ((70, 30), (96, 20)):
        draw.line((gx - 5, gy, gx, gy - 3), fill='#3a1850', width=2)
        draw.line((gx, gy - 3, gx + 5, gy), fill='#3a1850', width=2)
    return view


def write(plates, out, with_manifest=False):
    """Read the plate, build the atlas, its JSON and the thumbnail into `out` (owner-only files, atomically); optionally add the scene to `out/scenes.json`."""
    plates, out = Path(plates), Path(out)
    plate_path = find_plate(plates)
    try:
        raw = json.loads((plates / 'geometry.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise PlateError(f'geometry.json in {plates} is missing or not JSON: {error}')
    geometry, options = check_geometry(raw)
    with Image.open(plate_path) as image:
        picture, classes = build_backdrop(image, geometry, options)
    palm = None
    palm_path = find_plate(plates, PALM_NAMES, required=False)
    if options['palm'] and palm_path:
        with Image.open(palm_path) as image:
            palm = key_palm(image, options['palm'])
    else:
        geometry.pop('palm', None)
    brushes = build_brushes()
    atlas, frames = build_atlas(picture, classes, brushes, palm)
    data = {'version': 2, 'scene': NAME, 'size': list(atlas.size), 'frames': frames, 'geometry': geometry,
            'brushes': {style: [f'foam-{style}-{i}' for i in range(len(STYLES[style][0]))] for style in STYLES}}
    png, json_path, thumb = out / f'scene-{NAME}.png', out / f'scene-{NAME}.json', out / f'thumb-{NAME}.webp'
    if atlas.width > 4096 or atlas.height > 4096:
        raise PlateError('The atlas is bigger than the game contract allows (4096 px)')
    media._write_atomically(png, lambda target: atlas.save(target, format='PNG', optimize=True), media.MAX_IMAGE_BYTES)
    media._write_atomically(json_path, lambda target: target.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True), encoding='utf-8'), 512 * 1024)
    media.save_thumbnail(thumbnail(picture, geometry, palm), thumb)
    if with_manifest:
        media.update_manifest(NAME, media.scene_entry('game', png.name, 'image', atlas.width, atlas.height, data=json_path.name), out)
    return {'atlas': str(png), 'frames': len(frames), 'size': list(atlas.size), 'bytes': png.stat().st_size, 'colors': len(picture.getcolors(1 << 20)), 'manifest': bool(with_manifest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--plates', type=Path, required=True, help='folder with wave.jpg|png and geometry.json (private art, never in Git)')
    parser.add_argument('--out', type=Path, required=True, help='folder to write into (the tablet\'s private folder, or a scratch folder)')
    parser.add_argument('--manifest', action='store_true', help='also add the scene to scenes.json in that folder (replacing the previous entry of surf)')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(write(args.plates, args.out, args.manifest)))
    except PlateError as error:
        print(f'prepare_game_surf: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
