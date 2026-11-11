"""The atlas of the tablet's TOKEN RUN scene (scripts/prepare_game_token_run.py): every sprite the scene (game-token-run.js) asks for is there, drawn crisp (no partial
alpha), anchored at its foot, in ladders of sizes a road can scale through; the files are written atomically with owner-only permissions inside the folder given, the manifest
entry is what the tablet server accepts, and nothing reads a ROM, Downloads or the network. The art is the board's own code-drawn art: nothing private is needed."""
import contextlib
import io
import json
import re
import stat
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts import prepare_game_token_run as prepare
from scripts import tablet_media as media
from token_tv import tablet_server

ROOT = Path(__file__).resolve().parents[1]
SCENE = (ROOT / 'token_tv/tablet_web/game-token-run.js').read_text(encoding='utf-8')
SCRIPT = (ROOT / 'scripts/prepare_game_token_run.py').read_text(encoding='utf-8')


def scene_constants():
    """What the scene's JavaScript asks of the atlas: the kinds of roadside thing, the rival colours."""
    kinds_block = re.search(r'const KINDS = \{(.*?)\};', SCENE, re.S).group(1)
    kinds = re.findall(r'(\w+):\s*\d+', kinds_block)
    colours = re.search(r"RIVAL_NAMES = \[(.*?)\]", SCENE).group(1)
    return kinds, re.findall(r"'(\w+)'", colours)


class SpriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames, cls.ladders = prepare.build_sprites()

    def test_every_kind_the_scene_draws_has_a_ladder_and_every_frame_it_names_exists(self):
        kinds, colours = scene_constants()
        self.assertGreaterEqual(len(kinds), 15)
        for kind in kinds:
            self.assertIn(kind, self.ladders, f'the scene places {kind} but the atlas has no ladder of it')
            self.assertGreaterEqual(len(self.ladders[kind]), 4 if kind != 'bridge' else 6, kind)
        for colour in colours:
            self.assertIn(f'rival-{colour}', self.ladders)
            self.assertEqual(len(self.ladders[f'rival-{colour}']), len(prepare.RIVAL_WIDTHS))
        for lean in range(5):
            for phase in range(4):
                self.assertIn(f'car-{lean}-{phase}', self.frames)
        for kind in ('gull-s', 'gull-m'):
            self.assertEqual(sorted(self.ladders[kind]), [f'{kind}-{k}' for k in range(3)], 'three wing poses')
        self.assertGreaterEqual(len(self.ladders['cloud']), 6)
        for needed in re.findall(r"atlas\.frame\('([\w-]+)'\)", SCENE):
            self.assertIn(needed, self.frames)

    def test_ladders_run_smallest_to_biggest_with_no_jump_bigger_than_about_forty_percent(self):
        for name in ('palm0', 'palm1', 'pine', 'house0', 'house1', 'rock0', 'sign0', 'billboard', 'boat', 'bush', 'post'):
            heights = [self.frames[n][0].height for n in self.ladders[name]]
            self.assertEqual(heights, sorted(heights), name)
            for small, big in zip(heights, heights[1:]):
                self.assertLessEqual(big / small, 1.45, f'{name}: {small} -> {big}')
            self.assertLessEqual(heights[0], 12, f'{name} starts small enough for the far distance')
        for colour in ('blue', 'yellow'):
            widths = [self.frames[n][0].width for n in self.ladders[f'rival-{colour}']]
            self.assertEqual(widths, sorted(widths))
            self.assertLessEqual(max(b / a for a, b in zip(widths, widths[1:])), 1.5)
        names = self.ladders['palm0']
        self.assertTrue(all(re.fullmatch(r'palm0-\d{3}', n) for n in names))

    def test_every_sprite_is_crisp_pixel_art_with_its_anchor_on_the_picture_and_at_its_foot(self):
        for name, (picture, anchor) in self.frames.items():
            self.assertEqual(picture.mode, 'RGBA', name)
            alphas = {value for _, value in picture.getchannel('A').getcolors()}
            self.assertLessEqual(alphas, {0, 255}, f'{name} has soft edges: nothing may be anti-aliased or resampled')
            self.assertIn(255, alphas, name)
            self.assertTrue(0 <= anchor[0] < picture.width and 0 <= anchor[1] < picture.height, f'{name} anchor {anchor} outside {picture.size}')
            self.assertIsNotNone(picture.getbbox())
            if name.startswith(('palm', 'pine', 'bush', 'rock', 'house', 'block', 'post', 'sign', 'billboard', 'lamp', 'parasol', 'rival', 'car', 'bridge')):
                self.assertGreaterEqual(anchor[1], picture.height - 6, f'{name}: the ground point is near the bottom of the picture')
                self.assertLessEqual(abs(anchor[0] - picture.width // 2), 3, f'{name}: centred on its ground point')

    def test_sprites_use_the_boards_palette_and_a_few_hundred_frames_fit_a_small_atlas(self):
        positions, atlas = prepare.pack(self.frames)
        self.assertLessEqual(atlas.width, 4096)
        self.assertLessEqual(atlas.height, 1024, 'a sheet the tablet can keep in memory')
        self.assertGreater(len(self.frames), 250)
        rgb = lambda tone: tuple(int(tone[i:i + 2], 16) for i in (1, 3, 5))
        used = lambda names: {px[:3] for n in names for _, px in self.frames[n][0].getcolors(100000) if px[3] == 255}
        palms = used(self.ladders['palm0'])
        for tone in prepare.board_drive.PALM_TONES:
            self.assertIn(rgb(tone), palms, f'the palms keep the board\'s tone {tone}')
        self.assertIn((0xef, 0x34, 0x3d), used(['car-2-0']), 'the convertible keeps the board\'s red')
        self.assertIn(rgb('#ff633e'), used(['car-2-0']))

    def test_the_red_convertible_leans_without_moving_its_tyres(self):
        straight = self.frames['car-2-0'][0]
        left, right = self.frames['car-0-0'][0], self.frames['car-4-0'][0]
        self.assertEqual(straight.size, left.size)
        bottom = straight.height - 9
        for lean, picture in ((-1, left), (1, right)):
            tyres = [tuple(picture.getpixel((x, y))) for y in range(bottom, picture.height) for x in range(picture.width)]
            same = [tuple(straight.getpixel((x, y))) for y in range(bottom, straight.height) for x in range(straight.width)]
            self.assertEqual(tyres, same, 'the planted rows (tyres and shadow) are identical in every pose')
        top = 3
        self.assertNotEqual([straight.getpixel((x, top)) for x in range(straight.width)], [left.getpixel((x, top)) for x in range(left.width)], 'the body shears')

    def test_packing_keeps_every_frame_whole_apart_and_inside_the_sheet(self):
        positions, atlas = prepare.pack(self.frames)
        boxes = []
        for name, (x, y) in positions.items():
            w, h = self.frames[name][0].size
            self.assertTrue(0 <= x and 0 <= y and x + w <= atlas.width and y + h <= atlas.height, name)
            self.assertEqual(atlas.crop((x, y, x + w, y + h)).tobytes(), self.frames[name][0].tobytes(), f'{name} is intact in the sheet')
            boxes.append((x, y, x + w, y + h, name))
        boxes.sort()
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                if b[0] >= a[2]:
                    break
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], f'{a[4]} overlaps {b[4]}')


class WriteTests(unittest.TestCase):
    def run_script(self, directory, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = prepare.main(['--out', str(directory), *extra])
        return code, json.loads(out.getvalue())

    def test_the_three_files_follow_the_game_contract_and_are_private(self):
        with tempfile.TemporaryDirectory() as folder:
            code, summary = self.run_script(folder)
            self.assertEqual(code, 0)
            directory = Path(folder)
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ['scene-token-run.json', 'scene-token-run.png', 'thumb-token-run.webp'], 'no manifest unless asked, no temporary files left')
            for path in directory.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
            png, data = directory / 'scene-token-run.png', json.loads((directory / 'scene-token-run.json').read_text(encoding='utf-8'))
            self.assertLessEqual(png.stat().st_size, 8 * 1024 * 1024)
            self.assertLessEqual((directory / 'scene-token-run.json').stat().st_size, 512 * 1024)
            with Image.open(png) as atlas:
                self.assertEqual(atlas.mode, 'RGBA')
                self.assertEqual(list(atlas.size), data['size'])
                self.assertLessEqual(max(atlas.size), 4096)
                for name, (x, y, w, h) in data['frames'].items():
                    self.assertTrue(x + w <= atlas.width and y + h <= atlas.height, name)
                    self.assertIsNotNone(atlas.crop((x, y, x + w, y + h)).getchannel('A').getbbox(), f'{name} is not an empty rectangle')
            self.assertEqual(set(data['anchors']), set(data['frames']))
            for ladder, names in data['ladders'].items():
                self.assertTrue(all(name in data['frames'] for name in names), ladder)
                heights = [data['frames'][name][3] for name in names]
                self.assertEqual(heights, sorted(heights), f'{ladder} is listed smallest first')
            self.assertEqual((data['version'], data['scene']), (1, 'token-run'))
            with Image.open(directory / 'thumb-token-run.webp') as thumb:
                self.assertEqual(thumb.size, (240, 160))
            self.assertEqual((summary['frames'], summary['manifest']), (len(data['frames']), False))

    def test_the_manifest_entry_is_what_the_server_accepts_and_other_scenes_stay(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            media.update_manifest('surf', media.scene_entry('crt', 'scene-surf.webm', 'video', 640, 480, fps=15), directory)
            self.run_script(directory, '--manifest')
            manifest = json.loads((directory / 'scenes.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(manifest['scenes']), ['surf', 'token-run'], 'the other scene is kept')
            entry = manifest['scenes']['token-run']
            self.assertEqual(entry['look'], 'game')
            self.assertEqual(entry['data'], 'scene-token-run.json')
            self.assertEqual((entry['media']['kind'], entry['media']['file']), ('image', 'scene-token-run.png'))
            catalogue = tablet_server.scene_catalog(directory)
            self.assertIn('token-run', catalogue['scenes'])
            info = catalogue['info']['token-run']
            self.assertEqual((info['look'], info['data'], info['media']['url']), ('game', '/assets/scene-token-run.json', '/assets/scene-token-run.png'))
            self.assertEqual((info['media']['width'], info['media']['height']), tuple(json.loads((directory / 'scene-token-run.json').read_text())['size']))
            self.assertEqual(stat.S_IMODE((directory / 'scenes.json').stat().st_mode), 0o600)

    def test_running_it_twice_gives_the_same_bytes_and_replaces_files_in_place(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.run_script(directory)
            first = {p.name: p.read_bytes() for p in directory.iterdir()}
            self.run_script(directory)
            second = {p.name: p.read_bytes() for p in directory.iterdir()}
            self.assertEqual(first, second)
            self.assertEqual(sorted(second), ['scene-token-run.json', 'scene-token-run.png', 'thumb-token-run.webp'])

    def test_nothing_is_written_outside_the_folder_and_a_missing_folder_is_made_private(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'private' / 'tablet'
            self.run_script(target)
            self.assertTrue((target / 'scene-token-run.png').is_file())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ['private'])
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                prepare.main([])                                  # --out is required: there is no default folder that could hit the real private one by accident

    def test_a_thumbnail_of_the_scene_is_a_picture_of_a_road_by_the_sea(self):
        frames, _ = prepare.build_sprites()
        thumb = prepare.thumbnail(frames)
        self.assertEqual((thumb.size, thumb.mode), ((240, 160), 'RGB'))
        top, bottom = thumb.getpixel((20, 10)), thumb.getpixel((20, 150))
        self.assertGreater(top[2], top[0], 'a blue sky at the top')
        self.assertNotEqual(top, bottom)
        colours = {thumb.getpixel((x, y)) for x in range(0, 240, 4) for y in range(0, 160, 4)}
        self.assertGreater(len(colours), 25, 'not a flat picture')


class BoundaryTests(unittest.TestCase):
    def test_the_script_reads_no_rom_no_downloads_and_never_uses_the_network_or_another_program(self):
        for forbidden in ('/mnt/', 'Downloads', '.rom', '.smc', '.sfc', 'urllib', 'requests', 'socket', 'subprocess', 'http://', 'https://', 'gemini', 'agy', 'getenv', 'environ'):
            self.assertNotIn(forbidden, SCRIPT, forbidden)
        for forbidden in ('fetch(', 'XMLHttpRequest', 'WebSocket', 'readings(', 'localStorage', 'eval(', 'new Function'):
            self.assertNotIn(forbidden, SCENE, f'the scene must not use {forbidden}')

    def test_the_scene_shows_no_quota_and_no_numbers_and_no_text(self):
        self.assertNotRegex(SCENE, r'fillText|strokeText|\.font\s*=', 'no text is drawn in the picture')
        self.assertNotIn('remaining', SCENE)
        self.assertNotIn('resets_at', SCENE)
        for name, (picture, _) in prepare.build_sprites()[0].items():
            self.assertFalse(name.startswith(('digit', 'number', 'text')), name)


if __name__ == '__main__':
    unittest.main()
