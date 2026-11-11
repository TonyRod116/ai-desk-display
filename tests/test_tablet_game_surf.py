"""The files of the tablet's TIDAL RUSH scene (scripts/prepare_game_surf.py): the plate becomes a clean small-palette backdrop with a class map and the geometry the scene reads, the foam
brushes the scene falls back on are all there and crisp, the atlas, its JSON and the thumbnail follow the game contract and are private, the manifest entry is what the tablet server
accepts and REPLACES the previous entry of `surf`, bad plates and geometry fail closed, and nothing reads a ROM, Downloads or the network. The plate here is FICTIONAL, drawn by code:
the real one is private Gemini art that never enters Git, docs or tests."""
import contextlib
import io
import json
import re
import stat
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts import prepare_game_surf as prepare
from scripts import tablet_media as media
from token_tv import tablet_server

ROOT = Path(__file__).resolve().parents[1]
SCENE = (ROOT / 'token_tv/tablet_web/game-surf.js').read_text(encoding='utf-8')
SCRIPT = (ROOT / 'scripts/prepare_game_surf.py').read_text(encoding='utf-8')


def fictional_geometry():
    """A made-up geometry for a made-up picture: a round tube mouth in a big wave on the right, a sun on the left."""
    return {
        'crop': {'y0': 60, 'x0': 0, 'width': None}, 'colors': 24, 'merge': 12,
        'sky': {'top': '#102060', 'strength': 0.5, 'rows': 70},
        'horizon': 130, 'sun': {'x': 44, 'y': 118, 'r': 20}, 'centre': [130, 140], 'hole': [130, 130, 30, 20], 'tip': [82, 132], 'path': [24, 80],
        'lip': [[150, 50], [120, 60], [100, 80], [88, 110]],
        'line': [[110, 190], [125, 175], [140, 160], [152, 145], [158, 130], [154, 112], [144, 100]],
        'foot': [[10, 220], [80, 205], [160, 170]],
        'water': [[200, 40], [150, 46], [112, 62], [96, 90], [90, 122], [100, 150], [118, 150], [140, 128], [156, 130], [152, 160], [130, 190], [90, 205], [0, 215], [0, 320], [200, 320]],
    }


def fictional_plate(size=(768, 1376)):
    """A gradient sky, a flat sea, a sun and a teal blob: nothing that anyone drew."""
    image = Image.new('RGB', size)
    draw = ImageDraw.Draw(image)
    horizon = int(size[1] * 0.45)
    for y in range(size[1]):
        k = y / horizon
        colour = (int(60 + 190 * min(k, 1)), int(40 + 120 * min(k, 1) ** 2), int(140 - 60 * min(k, 1))) if y < horizon else (40 + (y - horizon) // 30, 30, 90 + (y - horizon) // 20)
        draw.line((0, y, size[0], y), fill=colour)
    draw.ellipse((100, horizon - 150, 360, horizon + 110), fill=(255, 160, 40))
    draw.polygon([(768, 120), (560, 200), (420, horizon + 60), (500, 900), (768, 1376)], fill=(20, 170, 170))
    draw.ellipse((470, 520, 700, 760), fill=(10, 80, 130))
    return image


def fictional_palm(size=(300, 400)):
    """A green blob and a brown stick on a flat magenta background (a stand-in for a palm crown: nothing that anyone drew)."""
    image = Image.new('RGB', size, (255, 0, 255))
    draw = ImageDraw.Draw(image)
    draw.line((0, 0, 120, 120), fill=(110, 70, 30), width=18)
    draw.ellipse((90, 80, 280, 220), fill=(16, 110, 80))
    draw.ellipse((120, 110, 200, 160), fill=(40, 170, 110))
    draw.ellipse((100, 100, 130, 130), fill=(130, 80, 40))
    return image


def write_plates(folder, geometry=None, size=(768, 1376), name='wave.png', palm=False):
    folder = Path(folder)
    fictional_plate(size).save(folder / name)
    data = geometry or fictional_geometry()
    if palm:
        fictional_palm().save(folder / 'palm.png')
        data = {**data, 'palm': {'width': 60, 'x': 2, 'y': 0, 'colors': 12}}
    (folder / 'geometry.json').write_text(json.dumps(data), encoding='utf-8')
    return folder


class GeometryTests(unittest.TestCase):
    def test_a_good_geometry_is_cleaned_and_a_bad_one_is_refused(self):
        geometry, options = prepare.check_geometry(fictional_geometry())
        self.assertEqual(geometry['horizon'], 130)
        self.assertEqual(sorted(geometry), sorted(prepare.GEOMETRY_KEYS))
        self.assertEqual((options['y0'], options['colors'], options['merge']), (60, 24, 12))
        self.assertEqual(options['sky']['rows'], 70)
        broken = {
            'not an object': [],
            'no horizon': {k: v for k, v in fictional_geometry().items() if k != 'horizon'},
            'horizon outside': {**fictional_geometry(), 'horizon': 5},
            'horizon text': {**fictional_geometry(), 'horizon': 'high'},
            'nan': {**fictional_geometry(), 'horizon': float('nan')},
            'bool as a number': {**fictional_geometry(), 'colors': True},
            'too many colours': {**fictional_geometry(), 'colors': 200},
            'no water': {k: v for k, v in fictional_geometry().items() if k != 'water'},
            'short water': {**fictional_geometry(), 'water': [[1, 1], [2, 2]]},
            'bad point': {**fictional_geometry(), 'water': [[1, 1], [2, 2], [3, 3], 'x']},
            'point far away': {**fictional_geometry(), 'lip': [[1, 1], [9999, 5]]},
            'line too short': {**fictional_geometry(), 'line': [[1, 1], [2, 2]]},
            'sun too big': {**fictional_geometry(), 'sun': {'x': 40, 'y': 100, 'r': 400}},
            'sky too strong': {**fictional_geometry(), 'sky': {'top': '#000000', 'strength': 3, 'rows': 10}},
            'sky colour': {**fictional_geometry(), 'sky': {'top': 'nonsense', 'strength': .5, 'rows': 10}},
            'hole shape': {**fictional_geometry(), 'hole': [1, 2, 3]},
            'path shape': {**fictional_geometry(), 'path': [1]},
            'palm not an object': {**fictional_geometry(), 'palm': 5},
            'palm too small': {**fictional_geometry(), 'palm': {'width': 3}},
            'palm too many colours': {**fictional_geometry(), 'palm': {'width': 60, 'colors': 400}},
            'palm far away': {**fictional_geometry(), 'palm': {'width': 60, 'x': 9999}},
        }
        for name, data in broken.items():
            with self.assertRaises(prepare.PlateError, msg=name):
                prepare.check_geometry(data)

    def test_the_geometry_the_scene_reads_is_the_geometry_the_script_writes(self):
        for key in prepare.GEOMETRY_KEYS:
            self.assertTrue(f'given.{key}' in SCENE or f"'{key}'" in SCENE, f'the scene reads geometry.{key}')
        classes = re.search(r'const CLS = \{ STILL: (\d), SKY: (\d), SEA: (\d), WATER: (\d), FORE: (\d) \};', SCENE)
        self.assertIsNotNone(classes)
        stills, sky, sea, water, fore = (int(v) for v in classes.groups())
        self.assertEqual((stills, sky, sea, water), (prepare.CLS_STILL, prepare.CLS_SKY, prepare.CLS_SEA, prepare.CLS_WATER))
        self.assertNotIn(fore, (prepare.CLS_STILL, prepare.CLS_SKY, prepare.CLS_SEA, prepare.CLS_WATER), 'the cliff class is set by the scene and never by the script')
        self.assertIn('json.frames.plate', SCENE)
        self.assertIn('json.frames.maps', SCENE)
        self.assertEqual((prepare.W, prepare.H), (200, 320))
        self.assertIn('const W = 200, H = 320;', SCENE)


class BackdropTests(unittest.TestCase):
    def setUp(self):
        self.geometry, self.options = prepare.check_geometry(fictional_geometry())

    def test_the_crop_is_five_by_eight_scaled_to_the_picture_and_a_short_bottom_is_mirrored(self):
        plate = fictional_plate()
        picture = prepare.crop_scale(plate, self.options)
        self.assertEqual(picture.size, (200, 320))
        tall = prepare.crop_scale(plate, {**self.options, 'y0': 200})                       # 200 + 1229 > 1376: the last 53 rows are mirrored
        self.assertEqual(tall.size, (200, 320))
        with self.assertRaises(prepare.PlateError):
            prepare.crop_scale(plate, {**self.options, 'y0': 900})                           # far too low
        with self.assertRaises(prepare.PlateError):
            prepare.crop_scale(plate, {**self.options, 'width': 10})

    def test_every_pixel_has_a_class_water_inside_the_silhouette_sky_above_the_horizon_sea_below(self):
        classes = prepare.classify(self.geometry, self.options['water'])
        self.assertEqual(len(classes), 200 * 320)
        self.assertEqual(set(classes), {prepare.CLS_SKY, prepare.CLS_SEA, prepare.CLS_WATER})
        at = lambda x, y: classes[y * 200 + x]
        self.assertEqual(at(10, 10), prepare.CLS_SKY)
        self.assertEqual(at(10, 129), prepare.CLS_SKY)
        self.assertEqual(at(10, 131), prepare.CLS_SEA)
        self.assertEqual(at(190, 300), prepare.CLS_WATER)
        self.assertEqual(at(120, 168), prepare.CLS_SEA, 'outside the silhouette and under the horizon')
        self.assertEqual(at(60, 60), prepare.CLS_SKY, 'outside the silhouette and above the horizon')

    def test_the_zenith_is_darkened_but_only_sky_pixels_and_most_at_the_top(self):
        classes = prepare.classify(self.geometry, self.options['water'])
        picture = Image.new('RGB', (200, 320), (200, 100, 120))
        tinted = prepare.tint_sky(picture, classes, self.options['sky'])
        self.assertLess(sum(tinted.getpixel((10, 0))), sum(tinted.getpixel((10, 40))))
        self.assertLess(sum(tinted.getpixel((10, 40))), sum(tinted.getpixel((10, 69))))
        self.assertEqual(tinted.getpixel((10, 69)), (200, 100, 120), 'nothing below the tint rows')
        self.assertEqual(tinted.getpixel((190, 60)), (200, 100, 120), 'the wave is not tinted')
        self.assertEqual(tinted.getpixel((10, 200)), (200, 100, 120), 'the sea is not tinted')
        self.assertIs(prepare.tint_sky(picture, classes, None), picture)

    def test_quantising_makes_a_small_clean_palette_and_folds_near_colours_together(self):
        image = Image.new('RGB', (64, 64))
        pixels = image.load()
        for y in range(64):
            for x in range(64):
                pixels[x, y] = (200 + (x % 3), 50 + (y % 2), 90) if x < 32 else (20, 120 + (y % 3), 150)
        out = prepare.quantise(image, 16, 14)
        self.assertLessEqual(len(out.getcolors(1 << 20)), 3, 'near-identical colours were merged')
        crisp = prepare.quantise(fictional_plate((200, 320)), 24, 10)
        self.assertLessEqual(len(crisp.getcolors(1 << 20)), 24)
        self.assertEqual(crisp.tobytes(), prepare.quantise(fictional_plate((200, 320)), 24, 10).tobytes(), 'deterministic')

    def test_the_whole_backdrop(self):
        picture, classes = prepare.build_backdrop(fictional_plate(), self.geometry, self.options)
        self.assertEqual((picture.size, picture.mode, len(classes)), ((200, 320), 'RGB', 64000))
        self.assertLessEqual(len(picture.getcolors(1 << 20)), 24)
        self.assertGreater(len(picture.getcolors(1 << 20)), 6, 'not a flat picture')


class PalmTests(unittest.TestCase):
    def test_a_palm_on_magenta_becomes_a_sprite_with_a_hard_alpha_a_small_palette_and_no_magenta_fringe(self):
        _, options = prepare.check_geometry({**fictional_geometry(), 'palm': {'width': 60, 'colors': 12}})
        sprite = prepare.key_palm(fictional_palm(), options['palm'])
        self.assertEqual((sprite.size, sprite.mode), ((60, 80), 'RGBA'))
        alphas = {a for _, (_, _, _, a) in sprite.getcolors(100000)}
        self.assertEqual(alphas, {0, 255}, 'the alpha is only ever 0 or 255, so the browser never premultiplies it')
        opaque = [c for count, c in sprite.getcolors(100000) if c[3]]
        self.assertLessEqual(len(opaque), 12)
        for r, g, b, _ in opaque:
            self.assertFalse(r > 170 and b > 170 and g < 120, 'no magenta is left in the sprite')
        pixels = sprite.load()
        self.assertEqual(pixels[59, 79][3], 0, 'the background corner is transparent')
        self.assertEqual(pixels[0, 0][3] and pixels[0, 0][:3] != (255, 0, 255), True, 'the trunk at the corner is kept')
        covered = sum(1 for y in range(80) for x in range(60) if pixels[x, y][3])
        self.assertTrue(250 < covered < 4000, covered)

    def test_a_picture_that_is_all_background_is_refused(self):
        _, options = prepare.check_geometry({**fictional_geometry(), 'palm': {'width': 60}})
        with self.assertRaises(prepare.PlateError):
            prepare.key_palm(Image.new('RGB', (100, 100), (255, 0, 255)), options['palm'])

    def test_the_jpeg_noise_around_the_key_colour_is_keyed_out_too(self):
        _, options = prepare.check_geometry({**fictional_geometry(), 'palm': {'width': 60, 'colors': 12}})
        noisy = fictional_palm()
        pixels = noisy.load()
        for y in range(noisy.height):
            for x in range(noisy.width):
                if pixels[x, y] == (255, 0, 255) and (x * 7 + y * 3) % 5 == 0:
                    pixels[x, y] = (240, 20, 245)
        sprite = prepare.key_palm(noisy, options['palm'])
        self.assertEqual(sprite.getpixel((59, 79))[3], 0)


class BrushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = prepare.build_brushes()

    def test_every_brush_the_scene_asks_for_exists_with_the_sizes_it_falls_back_to(self):
        sizes = re.search(r'return \{ puff: set\(\'puff\', (\[.*?\])\), streak: set\(\'streak\', (\[.*?\])\), sheet: set\(\'sheet\', (\[.*?\])\) \};', SCENE, re.S)
        self.assertIsNotNone(sizes, 'the scene\'s built-in brushes')
        for style, text in zip(('puff', 'streak', 'sheet'), sizes.groups()):
            expected = [tuple(pair) for pair in json.loads(text)]
            self.assertEqual(expected, [self.frames[f'foam-{style}-{i}'].size for i in range(len(expected))], f'{style}: the atlas and the built-in brushes share their sizes')
            self.assertNotIn(f'foam-{style}-{len(expected)}', self.frames)
        self.assertEqual(len(self.frames), 11)
        self.assertIn('`foam-${style}-${i}`', SCENE, 'the scene reads the atlas brushes under these names')

    def test_brushes_are_crisp_ragged_and_lacy_never_round_bubbles(self):
        for name, picture in self.frames.items():
            self.assertEqual(picture.mode, 'RGBA', name)
            alphas = {value for _, value in picture.getchannel('A').getcolors()}
            self.assertLessEqual(alphas, {0, 120, 200, 255}, f'{name}: four opacities and no soft edges')
            self.assertIn(255, alphas, f'{name} has a solid core')
            if picture.width * picture.height >= 60:
                self.assertTrue(alphas & {120, 200}, f'{name} has a feathered rim')
            raw = picture.tobytes()
            tones = {raw[i] for i in range(0, len(raw), 4) if raw[i + 3]}
            self.assertGreater(len(tones), 8 if picture.width * picture.height >= 60 else 3, f'{name} has light and shade, not a flat blob')
            pixels = picture.load()
            if picture.width * picture.height >= 150:
                covered = sum(1 for y in range(picture.height) for x in range(picture.width) if pixels[x, y][3])
                self.assertLess(covered, 0.9 * picture.width * picture.height, f'{name}: ragged, not a full rectangle')

    def test_streaks_are_long_and_flat_sheets_are_wide_and_puffs_are_roundish(self):
        for i in range(len(prepare.STYLES['streak'][0])):
            w, h = self.frames[f'foam-streak-{i}'].size
            self.assertGreaterEqual(w / h, 3)
        for i in range(len(prepare.STYLES['sheet'][0])):
            w, h = self.frames[f'foam-sheet-{i}'].size
            self.assertGreaterEqual(w / h, 2.5)
        for i in range(len(prepare.STYLES['puff'][0])):
            w, h = self.frames[f'foam-puff-{i}'].size
            self.assertLessEqual(w / h, 2)
        for style in ('puff', 'streak', 'sheet'):
            widths = [self.frames[f'foam-{style}-{i}'].width for i in range(len(prepare.STYLES[style][0]))]
            self.assertEqual(widths, sorted(widths))
            self.assertGreater(widths[-1], 2 * widths[0], f'{style} grows through its sizes')

    def test_packing_keeps_every_frame_whole_apart_and_under_the_backdrop(self):
        positions, height = prepare.pack(self.frames, top=2 * 320 + 1)
        self.assertLessEqual(height, 4096)
        boxes = []
        for name, (x, y) in positions.items():
            w, h = self.frames[name].size
            self.assertTrue(0 <= x and 2 * 320 + 1 <= y and x + w <= 200 and y + h <= height, name)
            boxes.append((x, y, x + w, y + h, name))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], f'{a[4]} overlaps {b[4]}')

    def test_the_same_seed_gives_the_same_brushes(self):
        again = prepare.build_brushes()
        self.assertEqual({k: v.tobytes() for k, v in again.items()}, {k: v.tobytes() for k, v in self.frames.items()})


class WriteTests(unittest.TestCase):
    def run_script(self, plates, out, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = prepare.main(['--plates', str(plates), '--out', str(out), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_the_files_follow_the_game_contract_and_are_private(self):
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder:
            write_plates(plates)
            code, out, _ = self.run_script(plates, folder)
            self.assertEqual(code, 0)
            summary = json.loads(out)
            directory = Path(folder)
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ['scene-surf.json', 'scene-surf.png', 'thumb-surf.webp'], 'no manifest unless asked, no temporary files left')
            for path in directory.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
            png, data = directory / 'scene-surf.png', json.loads((directory / 'scene-surf.json').read_text(encoding='utf-8'))
            self.assertLessEqual(png.stat().st_size, 8 * 1024 * 1024)
            self.assertLessEqual((directory / 'scene-surf.json').stat().st_size, 512 * 1024)
            with Image.open(png) as atlas:
                atlas.load()
                self.assertEqual(atlas.mode, 'RGBA')
                self.assertEqual(list(atlas.size), data['size'])
                self.assertEqual(atlas.width, 200)
                self.assertLessEqual(atlas.height, 4096)
                for name, (x, y, w, h) in data['frames'].items():
                    self.assertTrue(x + w <= atlas.width and y + h <= atlas.height, name)
                plate = atlas.crop(tuple(data['frames']['plate'][:2]) + (200, 320))
                maps = atlas.crop((0, 320, 200, 640))
                self.assertEqual(data['frames']['plate'], [0, 0, 200, 320])
                self.assertEqual(data['frames']['maps'], [0, 320, 200, 320])
                self.assertEqual({a for _, (_, _, _, a) in plate.getcolors(1000000)}, {255}, 'the backdrop is opaque, so the browser never premultiplies it')
                self.assertEqual({a for _, (_, _, _, a) in maps.getcolors(1000000)}, {255})
                self.assertLessEqual({r for _, (r, _, _, _) in maps.getcolors(1000000)}, {0, 1, 2, 3}, 'the classes')
                self.assertLessEqual(len(plate.getcolors(1000000)), 24, 'a small palette')
            self.assertEqual((data['version'], data['scene']), (2, 'surf'))
            self.assertEqual(sorted(data['geometry']), sorted(prepare.GEOMETRY_KEYS))
            self.assertEqual(data['geometry']['horizon'], 130)
            for style, names in data['brushes'].items():
                self.assertTrue(all(name in data['frames'] for name in names), style)
                widths = [data['frames'][name][2] for name in names]
                self.assertEqual(widths, sorted(widths), f'{style} is listed smallest first')
            for name, (x, y, w, h) in data['frames'].items():
                if name.startswith('foam-'):
                    self.assertGreaterEqual(y, 641, 'the brushes sit under the backdrop and its maps')
            with Image.open(directory / 'thumb-surf.webp') as thumb:
                self.assertEqual(thumb.size, (240, 160))
            self.assertEqual((summary['frames'], summary['manifest']), (len(data['frames']), False))
            self.assertLessEqual(summary['colors'], 24)

    def test_a_palm_picture_adds_its_frame_and_its_place_and_nothing_without_it(self):
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as plain_plates, tempfile.TemporaryDirectory() as plain:
            write_plates(plates, palm=True)
            self.assertEqual(self.run_script(plates, folder)[0], 0)
            data = json.loads((Path(folder) / 'scene-surf.json').read_text(encoding='utf-8'))
            self.assertEqual(data['geometry']['palm'], {'x': 2, 'y': 0})
            x, y, w, h = data['frames']['palm']
            self.assertEqual((w, h), (60, 80))
            self.assertGreaterEqual(y, 641, 'the palm sits under the backdrop and its maps')
            with Image.open(Path(folder) / 'scene-surf.png') as atlas:
                atlas.load()
                crop = atlas.crop((x, y, x + w, y + h))
                self.assertEqual({a for _, (_, _, _, a) in crop.getcolors(100000)}, {0, 255})
                self.assertLessEqual(atlas.height, 4096)
            boxes = [(v[0], v[1], v[0] + v[2], v[1] + v[3], k) for k, v in data['frames'].items() if k not in ('plate', 'maps')]
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], f'{a[4]} overlaps {b[4]}')
            write_plates(plain_plates, geometry={**fictional_geometry(), 'palm': {'width': 60}})              # a palm block but no palm picture: no palm, no error
            self.assertEqual(self.run_script(plain_plates, plain)[0], 0)
            data = json.loads((Path(plain) / 'scene-surf.json').read_text(encoding='utf-8'))
            self.assertNotIn('palm', data['frames'])
            self.assertNotIn('palm', data['geometry'])

    def test_the_manifest_entry_is_what_the_server_accepts_replaces_the_old_entry_and_keeps_other_scenes(self):
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder:
            write_plates(plates)
            directory = Path(folder)
            media.update_manifest('surf', media.scene_entry('game', 'scene-surf.png', 'image', 128, 33, data='scene-surf.json'), directory)
            media.update_manifest('token-run', media.scene_entry('game', 'scene-token-run.png', 'image', 64, 64, data='scene-token-run.json'), directory)
            self.assertEqual(self.run_script(plates, directory, '--manifest')[0], 0)
            manifest = json.loads((directory / 'scenes.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(manifest['scenes']), ['surf', 'token-run'], 'the other scene is kept')
            entry = manifest['scenes']['surf']
            self.assertEqual((entry['look'], entry['data']), ('game', 'scene-surf.json'))
            self.assertEqual((entry['media']['kind'], entry['media']['file']), ('image', 'scene-surf.png'))
            self.assertEqual((entry['media']['width'], entry['media']['height']), tuple(json.loads((directory / 'scene-surf.json').read_text())['size']), 'the old size is replaced')
            catalogue = tablet_server.scene_catalog(directory)
            self.assertIn('surf', catalogue['scenes'])
            info = catalogue['info']['surf']
            self.assertEqual((info['look'], info['data'], info['media']['url']), ('game', '/assets/scene-surf.json', '/assets/scene-surf.png'))
            self.assertEqual(stat.S_IMODE((directory / 'scenes.json').stat().st_mode), 0o600)

    def test_running_it_twice_gives_the_same_bytes_and_replaces_files_in_place(self):
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder:
            write_plates(plates)
            directory = Path(folder)
            self.run_script(plates, directory)
            first = {p.name: p.read_bytes() for p in directory.iterdir()}
            self.run_script(plates, directory)
            second = {p.name: p.read_bytes() for p in directory.iterdir()}
            self.assertEqual(first, second)
            self.assertEqual(sorted(second), ['scene-surf.json', 'scene-surf.png', 'thumb-surf.webp'])

    def test_nothing_is_written_outside_the_folder_and_a_missing_folder_is_made_private(self):
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder:
            write_plates(plates)
            target = Path(folder) / 'private' / 'tablet'
            self.assertEqual(self.run_script(plates, target)[0], 0)
            self.assertTrue((target / 'scene-surf.png').is_file())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ['private'])
            self.assertEqual(sorted(p.name for p in Path(plates).iterdir()), ['geometry.json', 'wave.png'], 'the plate folder is only read')
        for argv in ([], ['--out', 'x'], ['--plates', 'x']):
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    prepare.main(argv)                              # both folders are required: there is no default that could hit the real private one by accident

    def test_a_missing_or_broken_plate_fails_closed_with_a_clear_message_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder:
            code, _, error = self.run_script(plates, folder)
            self.assertEqual(code, 2)
            self.assertIn('no wave.jpg or wave.png', error)
            Path(plates, 'wave.png').write_bytes(b'not a picture')
            Path(plates, 'geometry.json').write_text(json.dumps(fictional_geometry()), encoding='utf-8')
            with self.assertRaises(Exception):
                self.run_script(plates, folder)
            self.assertEqual(list(Path(folder).iterdir()), [], 'nothing is written')
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder:
            fictional_plate().save(Path(plates) / 'wave.png')
            code, _, error = self.run_script(plates, folder)
            self.assertEqual((code, 'geometry.json' in error), (2, True))
            Path(plates, 'geometry.json').write_text('{not json', encoding='utf-8')
            self.assertEqual(self.run_script(plates, folder)[0], 2)
            Path(plates, 'geometry.json').write_text(json.dumps({**fictional_geometry(), 'horizon': 'high'}), encoding='utf-8')
            code, _, error = self.run_script(plates, folder)
            self.assertEqual((code, 'horizon' in error), (2, True))
            Path(plates, 'geometry.json').write_text(json.dumps({**fictional_geometry(), 'crop': {'y0': 1370}}), encoding='utf-8')
            self.assertEqual(self.run_script(plates, folder)[0], 2, 'a crop that does not fit the plate')
            self.assertEqual(list(Path(folder).iterdir()), [], 'nothing is written by a refused run')

    def test_a_jpeg_plate_works_too(self):
        with tempfile.TemporaryDirectory() as plates, tempfile.TemporaryDirectory() as folder:
            fictional_plate().save(Path(plates) / 'wave.jpg', quality=90)
            Path(plates, 'geometry.json').write_text(json.dumps(fictional_geometry()), encoding='utf-8')
            self.assertEqual(self.run_script(plates, folder)[0], 0)
            self.assertTrue((Path(folder) / 'scene-surf.png').is_file())


class ThumbnailTests(unittest.TestCase):
    def test_a_thumbnail_is_the_visible_part_of_the_backdrop_with_a_small_surfer_and_gulls(self):
        geometry, options = prepare.check_geometry(fictional_geometry())
        picture, _ = prepare.build_backdrop(fictional_plate(), geometry, options)
        thumb = prepare.thumbnail(picture, geometry)
        self.assertEqual((thumb.size, thumb.mode), ((240, 160), 'RGB'))
        colours = {thumb.getpixel((x, y)) for x in range(0, 240, 3) for y in range(0, 160, 3)}
        self.assertGreater(len(colours), 10, 'not a flat picture')
        coral = sum(1 for x in range(0, 240) for y in range(0, 160) if thumb.getpixel((x, y)) == (240, 104, 90))
        self.assertGreater(coral, 10, 'a surfer in coral')
        orange = sum(1 for x in range(0, 240) for y in range(0, 160) if thumb.getpixel((x, y)) == (242, 138, 44))
        self.assertGreater(orange, 10, 'on an orange board')


class BoundaryTests(unittest.TestCase):
    def test_the_script_reads_no_rom_no_downloads_and_never_uses_the_network_or_another_program(self):
        for forbidden in ('/mnt/', 'Downloads', '.rom', '.smc', '.sfc', 'urllib', 'requests', 'socket', 'subprocess', 'http://', 'https://', 'gemini', 'agy ', 'getenv', 'environ', 'os.system'):
            self.assertNotIn(forbidden, SCRIPT, forbidden)

    def test_the_scene_shows_no_quota_and_no_numbers_and_no_text_and_has_a_built_in_backdrop(self):
        self.assertNotRegex(SCENE, r'fillText|strokeText|\.font\s*=', 'no text is drawn in the picture')
        for forbidden in ('remaining', 'resets_at', 'readings(', 'fetch(', 'XMLHttpRequest', 'WebSocket', 'localStorage', 'eval(', 'new Function'):
            self.assertNotIn(forbidden, SCENE, f'the scene must not use {forbidden}')
        self.assertNotIn('needsAtlas', SCENE, 'without its atlas the scene draws its own calmer backdrop')
        self.assertIn('function makeBackdrop', SCENE)

    def test_no_generated_art_is_in_the_repository(self):
        tracked = [p for p in (ROOT / 'tests').glob('*surf*') if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}]
        self.assertEqual(tracked, [])
        for suffix in ('*.jpg', '*.jpeg'):
            self.assertEqual([p for p in (ROOT / 'docs').rglob(suffix) if 'surf' in p.name.lower()], [])


if __name__ == '__main__':
    unittest.main()
