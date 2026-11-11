"""The atlas of the tablet's VERSUS scene (scripts/prepare_game_fighting.py): every frame the scene (game-fighting.js) asks for is there, drawn crisp (no partial alpha) and anchored
(a fighter's anchor is the floor's centre), the art keeps the board's rules for the originals, the moves' reach matches what is drawn, the files are written atomically with owner-only
permissions inside the folder given, the manifest entry is what the tablet server accepts, and nothing reads a ROM, Downloads or the network. The art is original, drawn with the
board's own toolkit; Tony's optional private jungle stage is never needed here: the tests use a FICTIONAL stage made inside the test, and never read the real private folder."""
import contextlib
import inspect
import io
import json
import math
import re
import stat
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts import prepare_game_fighting as prepare
from scripts import tablet_media as media
from token_tv import tablet_server

ROOT = Path(__file__).resolve().parents[1]
SCENE = (ROOT / 'token_tv/tablet_web/game-fighting.js').read_text(encoding='utf-8')
SCRIPT = (ROOT / 'scripts/prepare_game_fighting.py').read_text(encoding='utf-8')
CODE = SCRIPT.split('"""', 2)[2]                          # the script without its docstring


def js_table(name):
    """`const NAME = { key: 3, other: 4 };` of the scene as {key: 3, ...}."""
    block = re.search(rf'const {name} = \{{(.*?)\}};', SCENE, re.S).group(1)
    return {key: int(value) for key, value in re.findall(r'(\w+): (\d+)', block)}


def js_frames():
    block = re.search(r'const FRAMES = \{(.*?)\n  \};', SCENE, re.S).group(1)
    return {who: {key: int(value) for key, value in re.findall(r'(\w+): (\d+)', re.search(rf'{who}: \{{([^}}]*)\}}', block).group(1))} for who in ('codex', 'claude')}


def js_actor_frames():
    block = re.search(r'const ACTOR_FRAMES = \{(.*?)\};', SCENE, re.S).group(1)
    return {key: int(value) for key, value in re.findall(r"'?([\w-]+)'?: (\d+)", block)}


def js_tweens():
    block = re.search(r'const TWEEN_NAMES = \{(.*?)\n  \};', SCENE, re.S).group(1)
    return {who: re.findall(r"'([\w-]+)'", re.search(rf'{who}: \[([^\]]*)\]', block).group(1)) for who in ('codex', 'claude')}


def js_list(name):
    return re.findall(r"'([\w-]+)'", re.search(rf'const {name} = \[(.*?)\];', SCENE, re.S).group(1))


def js_moves():
    """{fighter: {move: {'seq': [...], 'hit': n, 'reach': n, 'anim': name}}} read from the scene's MOVES table."""
    block = re.search(r'const MOVES = \{(.*?)\n  \};', SCENE, re.S).group(1)
    out = {}
    for who in ('codex', 'claude'):
        body = re.search(rf'{who}: \{{(.*?)\n    \}},?', block, re.S).group(1)
        out[who] = {}
        for line in body.splitlines():
            m = re.match(r"\s*(\w+): \{ anim: '(\w+)', seq: \[([^\]]*)\], steps: \[([^\]]*)\](?:, hit: (\d+), reach: (\d+))?", line)
            if m:
                tokens = [v.strip().strip("'") for v in m.group(3).split(',')]                     # a frame index, or the name of an in-between frame (a string)
                out[who][m.group(1)] = {'anim': m.group(2), 'seq': [int(v) if v.isdigit() else v for v in tokens], 'hit': int(m.group(5)) if m.group(5) else None, 'reach': int(m.group(6)) if m.group(6) else None}
    return out


def fictional_stage(directory):
    """A made-up private stage (a gradient with blocks) and four-frame ambient pieces, in the sizes the board's loader insists on."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stage = Image.new('RGB', (320, 240), (20, 27, 52))
    for y in range(24, 223):
        for x in range(0, 320):
            stage.putpixel((x, y), ((x * 3) % 256, (y * 2) % 256, (x + y) % 256))
    stage.save(directory / 'stage.png')
    for index, (w, h) in enumerate(((25, 14), (27, 14))):
        for frame in range(4):
            piece = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            piece.putpixel((frame + 1, 3), (255, 255, 255, 255))
            piece.save(directory / f'ambient-{index}-{frame}.png')
    return directory


class SpriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames, cls.anims, cls.stages = prepare.build_sprites(None)

    def test_every_move_every_effect_and_every_fan_the_scene_asks_for_exists_with_the_count_it_expects(self):
        for who, moves in js_frames().items():
            self.assertEqual(sorted(moves), sorted(k for k in self.anims[who] if k != 'tw'), f'{who}: the same moves in the scene and the atlas')
            for move, count in moves.items():
                names = self.anims[who][move]
                self.assertEqual(len(names), count, f'{who} {move}: the scene expects {count} frames')
                self.assertEqual(names, [f'{who}-{move}-{k}' for k in range(count)])
                for name in names:
                    self.assertIn(name, self.frames)
        for kind, count in js_table('FX_FRAMES').items():
            self.assertEqual(len(self.anims['fx'][kind]), count, kind)
        for who, names in js_tweens().items():                                                   # the in-between frames the moves ease through
            self.assertEqual(sorted(self.anims[who]['tw']), sorted(f'{who}-tw-{n}' for n in names), f'{who}: the in-between frames')
        for kind, count in js_actor_frames().items():                                            # the stages' little actors and props
            self.assertEqual(self.anims['actors'][kind], [f'act-{kind}-{k}' for k in range(count)], kind)
            for name in self.anims['actors'][kind]:
                self.assertIn(name, self.frames)
        self.assertEqual(sorted(self.anims['actors']), sorted(js_actor_frames()))
        kinds, poses = js_list('CROWD_KINDS'), js_list('CROWD_POSES')
        self.assertEqual(sorted(self.anims['crowd']), sorted(kinds))
        for kind in kinds:
            self.assertEqual(self.anims['crowd'][kind], [f'crowd-{kind}-{pose}' for pose in poses])
        for who in ('codex', 'claude'):
            self.assertEqual(self.anims['proj'][who], [f'proj-{who}-{k}' for k in range(4)], 'the scene animates a projectile with four frames')

    def test_every_frame_name_written_in_the_scene_is_in_the_atlas(self):
        wanted = set(re.findall(r"'((?:prop|boat|gull|cloud|crowd|fx|proj|codex|claude|act)-[\w-]+)'", SCENE))
        prefixes = {name for name in wanted if name.endswith('-')}                  # 'fx-stars-' + n: a name the scene finishes itself
        wanted -= prefixes | {'codex-idle', 'claude-idle'}
        self.assertGreaterEqual(len(wanted), 8)
        for name in wanted:
            self.assertIn(name, self.frames, f'the scene draws {name}')
        for prefix in prefixes:
            self.assertTrue(any(name.startswith(prefix) for name in self.frames), f'the scene draws {prefix}<n>')
        self.assertIn('fx-stars-', prefixes)
        for k in range(4):
            self.assertIn(f'fx-stars-{k}', self.frames)
        for kind in ('lantern', 'barrel', 'crate', 'bollard', 'ship'):
            self.assertIn(f'prop-{kind}', self.frames)
        self.assertEqual(self.anims['gulls']['fly'], ['gull-0', 'gull-1', 'gull-2'])
        self.assertEqual(len(self.anims['clouds']['cumulus']), 4)
        self.assertEqual(self.stages, {}, 'no private stage: no jungle')

    def test_every_sprite_is_crisp_pixel_art_with_its_anchor_on_the_picture(self):
        for name, (picture, anchor) in self.frames.items():
            self.assertEqual(picture.mode, 'RGBA', name)
            alphas = {value for _, value in picture.getchannel('A').getcolors()}
            self.assertLessEqual(alphas, {0, 255}, f'{name} has soft edges: nothing may be anti-aliased or resampled')
            self.assertIn(255, alphas, name)
            slack = 20 if name.startswith(('codex-', 'claude-')) else 0                  # a thrown fighter has no shadow under it: its floor point is a little below the picture
            self.assertTrue(0 <= anchor[0] < picture.width and 0 <= anchor[1] <= picture.height + slack, f'{name} anchor {anchor} outside {picture.size}')
            self.assertIsNotNone(picture.getbbox())

    def test_a_fighter_is_anchored_at_the_floor_under_its_middle_and_stands_about_eighty_pixels_tall(self):
        for who in ('codex', 'claude'):
            for move, names in self.anims[who].items():
                for name in names:
                    picture, (ax, ay) = self.frames[name]
                    self.assertGreaterEqual(picture.height - ay, -20, f'{name}: it is never far over the floor line')
                    self.assertLessEqual(picture.height - ay, 14, f'{name}: nothing hangs far below the floor')
                    self.assertIn(name, prepare.SHADOWS, f'{name}: the scene draws its shadow from these numbers')
                    self.assertGreaterEqual(picture.width, 60, name)
                    self.assertLessEqual(picture.width, 180, name)
        for who in ('codex', 'claude'):
            tall = self.frames[f'{who}-idle-0'][1][1]
            self.assertTrue(66 <= tall <= 82, f'{who} stands {tall} pixels tall: much bigger than the board\'s 48 and still fits the page with the dock up')
        codex, claude = self.frames['codex-idle-0'], self.frames['claude-idle-0']
        self.assertTrue(70 <= codex[0].width <= 90 and 70 <= claude[0].width <= 90)

    def test_blows_reach_as_far_as_the_scene_thinks_they_do(self):
        for who, moves in js_moves().items():
            facing = 1 if who == 'codex' else -1
            for move, data in moves.items():
                if data['hit'] is None:
                    continue
                name = self.anims[who][data['anim']][data['seq'][data['hit']]]
                picture, (ax, ay) = self.frames[name]
                drawn = picture.width - ax if facing > 0 else ax
                self.assertLessEqual(abs(drawn - data['reach']), 8, f'{who} {move}: the scene says the blow reaches {data["reach"]} pixels, the art draws {drawn}')

    def test_the_whip_is_the_longest_thing_and_a_jab_is_not_a_heavy_punch(self):
        extent = lambda name: self.frames[name][1][0]
        self.assertGreater(extent('claude-whip-3'), extent('claude-heavy-3'))
        self.assertGreater(extent('claude-heavy-3'), extent('claude-jab-2') - 4)
        reach = lambda name: self.frames[name][0].width - self.frames[name][1][0]
        self.assertGreater(reach('codex-heavy-3'), reach('codex-jab-2'))
        self.assertGreater(reach('codex-jab-2'), reach('codex-idle-0') + 15)

    def test_the_two_fighters_keep_their_own_colours(self):
        used = lambda name: {px[:3] for _, px in self.frames[name][0].getcolors(100000) if px[3] == 255}
        codex, claude = used('codex-idle-0'), used('claude-idle-0')
        self.assertIn(prepare.bf.SHELL[2], codex)
        self.assertIn(prepare.bf.PROMPT, codex, 'the prompt is its expression')
        self.assertIn(prepare.bf.BOLT[2], codex, 'the lightning bolt on its crown')
        self.assertIn(prepare.bf.ORANGE[2], claude)
        self.assertIn(prepare.bf.CREAM, claude, 'the starburst on its forehead')
        self.assertFalse(codex & set(prepare.bf.ORANGE), 'Codex has no orange')
        self.assertFalse(claude & set(prepare.bf.SHELL[1:3]), 'Claude has no blue')

    def test_nothing_crosses_codexs_screen_in_any_standing_pose(self):
        """The board's rule, held at the pose data: the lead glove is beside the shell and never over the terminal (a pose that lies or tumbles is excluded)."""
        for move, poses in prepare.CODEX.items():
            for k, pose in enumerate(poses):
                if pose.get('rot') and abs(pose['rot']) > 12:
                    continue
                top = pose.get('rise', 0.0) + pose.get('sag', 0.0)
                cx, cy = 21.5 + pose.get('lean', 0.0), 21.5 + top
                screen = (cx - 0.5 + pose.get('shear', 0.0) * 0.3, cy - 1.5, 11.0, 7.5)
                if pose.get('reach') is not None:
                    glove = (pose['reach'] - 1, cy + 4 - 0.5)
                else:
                    glove = (pose.get('lead', (44, 20))[0] - 1, pose.get('lead', (44, 20))[1])
                over_x = min(glove[0] + 5.9, screen[0] + screen[2]) - max(glove[0] - 5.9, screen[0] - screen[2])
                over_y = min(glove[1] + 5.5, screen[1] + screen[3]) - max(glove[1] - 5.5, screen[1] - screen[3])
                self.assertFalse(over_x > 2.0 and over_y > 2.0, f'codex {move}-{k}: the lead glove at {glove} is over the screen at {screen[:2]}')

    def test_the_layers_of_the_originals_are_drawn_in_the_boards_order(self):
        """Codex: rear arm, legs, lead arm, then the shell, belt, screen and bolt, the lead glove LAST. Claude: its screen-left arm (or whip) BEFORE its body and its screen-right arm AFTER."""
        text = inspect.getsource(prepare.codex)
        order = ['# rear arm', 'legs.sort', "rig.limb(g, shoulder", '# the cloud shell', 'screen_face', 'bolt_image', 'glove(lead_fist']
        positions = [text.index(item) for item in order]
        self.assertEqual(positions, sorted(positions), 'Codex is drawn back to front: its lead arm leaves from behind the body and its fist is last')
        text = inspect.getsource(prepare.claude)
        lead, body, rear, face = text.index("if p['whip'] is not None"), text.index('rig.ellipsoid(s, cx, cy, 16, 12.5'), text.index('# the rear arm, in front of the body'), text.index('claude_face(')
        self.assertTrue(lead < body < rear < face, 'the left arm passes behind the body, the right one in front, the face on top')

    def test_a_lying_fighter_is_lower_than_a_standing_one_and_a_tumbling_one_is_rotated_not_resampled(self):
        for who in ('codex', 'claude'):
            lying, standing = self.frames[f'{who}-kd-4'][0], self.frames[f'{who}-idle-0'][0]
            self.assertLess(lying.height, standing.height * 0.85, f'{who} lies down')
            self.assertGreater(self.frames[f'{who}-kd-1'][1][1], self.frames[f'{who}-idle-0'][1][1] + 15, f'{who} is thrown high in the air')

    def test_ladders_of_clouds_and_the_crowd_are_small_things(self):
        for name in self.anims['clouds']['cumulus']:
            self.assertLessEqual(self.frames[name][0].height, 36)
        for kind, names in self.anims['crowd'].items():
            for name in names:
                picture, (ax, ay) = self.frames[name]
                self.assertTrue(16 <= picture.width <= 40 and 18 <= picture.height <= 40, f'{name} {picture.size}')
                self.assertTrue(abs(ax - picture.width // 2) <= 4 and picture.height - ay <= 6, f'{name} is anchored at its feet')

    def test_packing_keeps_every_frame_whole_apart_and_inside_the_sheet(self):
        positions, atlas = prepare.pack(self.frames)
        self.assertLessEqual(atlas.width, 4096)
        self.assertLessEqual(atlas.height, 1100, 'a sheet the tablet can keep in memory')
        self.assertGreater(len(self.frames), 150)
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


class PrivateStageTests(unittest.TestCase):
    def test_a_valid_private_stage_becomes_one_more_stage_in_the_atlas_and_only_there(self):
        with tempfile.TemporaryDirectory() as folder:
            art = prepare.private_stage(fictional_stage(Path(folder) / 'arcade'))
            self.assertIsNotNone(art)
            frames, anims, stages = prepare.build_sprites(art)
            self.assertEqual(sorted(stages), ['jungle'])
            entry = stages['jungle']
            self.assertEqual(entry['frame'], 'stage-jungle')
            self.assertEqual(entry['size'], [320, 199], 'the picture rows of the 320 x 240 stage, without the board\'s flat bands')
            self.assertEqual(frames['stage-jungle'][0].size, (320, 199))
            self.assertEqual(frames['stage-jungle'][0].getpixel((0, 0))[:3], ((0 * 3) % 256, (24 * 2) % 256, (0 + 24) % 256), 'the crop starts at row 24')
            self.assertEqual(len(entry['ambient']), 2)
            for piece in entry['ambient']:
                self.assertEqual(len(piece['frames']), 4)
                self.assertEqual(piece['script'], [0, 1, 2, 3, 2, 1])
                for name in piece['frames']:
                    self.assertIn(name, frames)
            self.assertTrue(0 < entry['floor'] < entry['size'][1])
            self.assertEqual(sorted(anims), sorted(prepare.build_sprites(None)[1]), 'the animations do not change')

    def test_a_missing_or_wrongly_sized_private_stage_is_simply_not_there(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(prepare.private_stage(Path(folder) / 'nothing'))
            wrong = Path(folder) / 'wrong'
            wrong.mkdir()
            Image.new('RGB', (100, 100)).save(wrong / 'stage.png')
            self.assertIsNone(prepare.private_stage(wrong))
            _, _, stages = prepare.build_sprites(None)
            self.assertEqual(stages, {})


class WriteTests(unittest.TestCase):
    def run_script(self, directory, *extra):
        with tempfile.TemporaryDirectory() as empty, contextlib.redirect_stdout(io.StringIO()) as out:
            code = prepare.main(['--out', str(directory), '--private', str(Path(empty) / 'none'), *extra])
        return code, json.loads(out.getvalue())

    def test_the_three_files_follow_the_game_contract_and_are_private(self):
        with tempfile.TemporaryDirectory() as folder:
            code, summary = self.run_script(folder)
            self.assertEqual(code, 0)
            directory = Path(folder)
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ['scene-fighting.json', 'scene-fighting.png', 'thumb-fighting.webp'], 'no manifest unless asked, no temporary files left')
            for path in directory.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
            png, data = directory / 'scene-fighting.png', json.loads((directory / 'scene-fighting.json').read_text(encoding='utf-8'))
            self.assertLessEqual(png.stat().st_size, 8 * 1024 * 1024)
            self.assertLessEqual((directory / 'scene-fighting.json').stat().st_size, 512 * 1024)
            with Image.open(png) as atlas:
                self.assertEqual(atlas.mode, 'RGBA')
                self.assertEqual(list(atlas.size), data['size'])
                self.assertLessEqual(max(atlas.size), 4096)
                for name, (x, y, w, h) in data['frames'].items():
                    self.assertTrue(x + w <= atlas.width and y + h <= atlas.height, name)
                    self.assertIsNotNone(atlas.crop((x, y, x + w, y + h)).getchannel('A').getbbox(), f'{name} is not an empty rectangle')
            self.assertEqual(set(data['anchors']), set(data['frames']))
            for group, kinds in data['anims'].items():
                for kind, names in kinds.items():
                    names = names if isinstance(names, list) else [n for v in names.values() for n in v]
                    self.assertTrue(all(name in data['frames'] for name in names), f'{group} {kind}')
            self.assertEqual((data['version'], data['scene'], data['stages']), (1, 'fighting', {}))
            self.assertEqual(data['scale'], 1.6)
            with Image.open(directory / 'thumb-fighting.webp') as thumb:
                self.assertEqual(thumb.size, (240, 160))
            self.assertEqual((summary['frames'], summary['manifest'], summary['jungle']), (len(data['frames']), False, False))

    def test_the_manifest_entry_is_what_the_server_accepts_and_other_scenes_stay(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            media.update_manifest('surf', media.scene_entry('crt', 'scene-surf.webm', 'video', 640, 480, fps=15), directory)
            self.run_script(directory, '--manifest')
            manifest = json.loads((directory / 'scenes.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(manifest['scenes']), ['fighting', 'surf'], 'the other scene is kept')
            entry = manifest['scenes']['fighting']
            self.assertEqual(entry['look'], 'game')
            self.assertEqual(entry['data'], 'scene-fighting.json')
            self.assertEqual((entry['media']['kind'], entry['media']['file']), ('image', 'scene-fighting.png'))
            catalogue = tablet_server.scene_catalog(directory)
            self.assertIn('fighting', catalogue['scenes'])
            info = catalogue['info']['fighting']
            self.assertEqual((info['look'], info['data'], info['media']['url']), ('game', '/assets/scene-fighting.json', '/assets/scene-fighting.png'))
            self.assertEqual((info['media']['width'], info['media']['height']), tuple(json.loads((directory / 'scene-fighting.json').read_text())['size']))
            self.assertEqual(stat.S_IMODE((directory / 'scenes.json').stat().st_mode), 0o600)

    def test_running_it_twice_gives_the_same_bytes_and_replaces_files_in_place(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.run_script(directory)
            first = {p.name: p.read_bytes() for p in directory.iterdir()}
            self.run_script(directory)
            second = {p.name: p.read_bytes() for p in directory.iterdir()}
            self.assertEqual(first, second)
            self.assertEqual(sorted(second), ['scene-fighting.json', 'scene-fighting.png', 'thumb-fighting.webp'])

    def test_with_a_private_stage_the_atlas_holds_it_and_still_fits_the_contract(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as art:
            fictional_stage(Path(art) / 'arcade')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                prepare.main(['--out', folder, '--private', str(Path(art) / 'arcade')])
            summary = json.loads(out.getvalue())
            data = json.loads((Path(folder) / 'scene-fighting.json').read_text(encoding='utf-8'))
            self.assertTrue(summary['jungle'])
            self.assertEqual(sorted(data['stages']), ['jungle'])
            self.assertLessEqual(max(data['size']), 4096)
            self.assertLessEqual(Path(folder, 'scene-fighting.png').stat().st_size, 8 * 1024 * 1024)

    def test_nothing_is_written_outside_the_folder_and_a_missing_folder_is_made_private(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'private' / 'tablet'
            self.run_script(target)
            self.assertTrue((target / 'scene-fighting.png').is_file())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ['private'])
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                prepare.main([])                                  # --out is required: there is no default folder that could hit the real private one by accident

    def test_the_contact_sheet_is_only_written_where_it_is_asked_for(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as elsewhere:
            sheet = Path(elsewhere) / 'sheet.png'
            self.run_script(folder, '--sheet', str(sheet))
            self.assertTrue(sheet.is_file())
            with Image.open(sheet) as picture:
                self.assertGreater(picture.width, 500)
            self.assertNotIn('sheet.png', [p.name for p in Path(folder).iterdir()])

    def test_a_thumbnail_of_the_scene_is_a_harbour_with_the_two_fighters(self):
        frames, _, _ = prepare.build_sprites(None)
        thumb = prepare.thumbnail(frames)
        self.assertEqual((thumb.size, thumb.mode), ((240, 160), 'RGB'))
        top, bottom = thumb.getpixel((20, 2)), thumb.getpixel((20, 150))
        self.assertGreater(top[2], top[0], 'a blue sky at the top')
        self.assertGreater(bottom[0], bottom[2], 'a wooden pier at the bottom')
        colours = {thumb.getpixel((x, y)) for x in range(0, 240, 3) for y in range(0, 160, 3)}
        self.assertGreater(len(colours), 40, 'not a flat picture')


class BoundaryTests(unittest.TestCase):
    def test_the_script_reads_no_rom_no_downloads_and_never_uses_the_network_or_another_program(self):
        for forbidden in ('/mnt/', 'Downloads', '.rom', '.smc', '.sfc', 'urllib', 'requests', 'socket', 'subprocess', 'http://', 'https://', 'gemini', 'agy', 'getenv', 'environ', 'expanduser'):
            self.assertNotIn(forbidden, SCRIPT, forbidden)
        for forbidden in ('fetch(', 'XMLHttpRequest', 'WebSocket', 'localStorage', 'eval(', 'new Function'):
            self.assertNotIn(forbidden, SCENE, f'the scene must not use {forbidden}')

    def test_the_only_private_file_the_script_may_read_is_the_boards_own_optional_stage_through_its_loader(self):
        self.assertIn('board_arcade_local', CODE)
        self.assertNotIn('stage.png', CODE, 'the file names live in the board\'s loader, not here')
        self.assertNotIn('.local/share', CODE)
        self.assertNotIn('ambient-', CODE.replace("f'stage-jungle-amb-", ''), 'the ambient pieces are read by the board\'s loader too')

    def test_the_scene_draws_the_matchs_own_hit_points_and_never_quota(self):
        self.assertNotRegex(SCENE, r'fillText|strokeText|\.font\s*=', 'text is drawn with the scene\'s own pixel font')
        for forbidden in ('remaining', 'resets_at', 'providers', 'weekly', 'session'):
            self.assertNotIn(forbidden, SCENE, forbidden)
        self.assertNotIn('readings(', SCENE)
        for name in prepare.build_sprites(None)[0]:
            self.assertFalse(name.startswith(('digit', 'number', 'text', 'quota')), name)


class StageArtTests(unittest.TestCase):
    """The stages' actors, props, in-between poses and the numbers the scene reads from the atlas (attachment points, shadows): fictional, drawn here, nothing private."""

    @classmethod
    def setUpClass(cls):
        cls.frames, cls.anims, cls.stages = prepare.build_sprites(None)
        cls.points = dict(prepare.POINTS)

    def test_every_actor_is_a_small_crisp_picture_anchored_where_the_scene_stands_it(self):
        for kind, names in self.anims['actors'].items():
            self.assertTrue(names, kind)
            for name in names:
                picture, (ax, ay) = self.frames[name]
                self.assertLessEqual(max(picture.size), 110, f'{name} is a small sprite, not a backdrop')
                self.assertTrue(0 <= ax < picture.width and 0 <= ay <= picture.height, f'{name} anchor {(ax, ay)} in {picture.size}')
        for name in self.anims['actors']['stall']:
            picture, (ax, ay) = self.frames[name]
            self.assertEqual(ay, picture.height - 1, f'{name} stands on its counter line')
            self.assertGreaterEqual(picture.width, 48)
        for kind in ('noodle', 'grill'):
            for name in self.anims['actors'][kind]:
                picture, (ax, ay) = self.frames[name]
                self.assertEqual(ay, picture.height, f'{name} is a bust that ends at the counter top')

    def test_attachment_points_lie_on_the_pictures_they_belong_to(self):
        self.assertTrue(self.points, 'some frames carry points')
        for name, pts in self.points.items():
            picture, (ax, ay) = self.frames[name]
            for dx, dy in pts:
                x, y = ax + dx, ay + dy
                self.assertTrue(-4 <= x <= picture.width + 4 and -4 <= y <= picture.height + 4, f'{name}: point {(dx, dy)} is at {(x, y)} in {picture.size}')
        for k in range(4):                                                                           # a rod's tip is on the fisherman's drawing and the line starts there
            picture, (ax, ay) = self.frames[f'act-fisher-{k}']
            (dx, dy), = self.points[f'act-fisher-{k}']
            self.assertGreater(dx, 8, 'the tip is out over the water')
            self.assertLess(ay + dy, picture.height // 2, 'and high above the crate')
        for k in range(4):                                                                           # a stall's window and its sign are inside the stall, the sign inside the window
            picture, (ax, ay) = self.frames[f'act-stall-{k}']
            window0, window1, sign0, sign1 = self.points[f'act-stall-{k}']
            self.assertTrue(window0[0] < sign0[0] and sign1[0] < window1[0] and window0[1] < sign0[1] and sign1[1] < window1[1], f'stall {k}: the sign is in the window')
            self.assertGreaterEqual(sign1[0] - sign0[0], 29, f'stall {k}: the sign is wide enough for a five-letter word')

    def test_blending_poses_is_exact_at_the_ends_and_smooth_between(self):
        a, b = {'rise': 0.0, 'lead': (44, 20), 'face': 'idle'}, {'rise': -2.0, 'lead': (36, 28), 'reach': 60, 'face': 'strike'}
        same = prepare.blend_pose(prepare.CODEX_DEFAULTS, a, a, 0.5)
        self.assertEqual((same['rise'], same['lead'], same['face']), (0.0, (44, 20), 'idle'))
        start, end = prepare.blend_pose(prepare.CODEX_DEFAULTS, a, b, 0.0, 'b'), prepare.blend_pose(prepare.CODEX_DEFAULTS, a, b, 1.0, 'b')
        self.assertEqual((start['rise'], start['lead']), (0.0, (44, 20)))
        self.assertEqual((end['rise'], end['lead'], end['reach']), (-2.0, (36, 28), 60))
        middle = prepare.blend_pose(prepare.CODEX_DEFAULTS, a, b, 0.5)
        self.assertAlmostEqual(middle['rise'], -1.0)
        self.assertEqual(middle['lead'], (40.0, 24.0))
        arms = prepare.blend_pose(prepare.CLAUDE_DEFAULTS, {'lead': [(-12, 9), (-20, 8), (-30, 7), (-40, 7)]}, {'lead': [(-12, 9), (-18, 6), (-19, 0), (-17, -4), (-14, -9)]}, 0.5)
        self.assertEqual(len(arms['lead']), 5, 'arms of different lengths blend along their length')
        self.assertEqual(arms['lead'][0], (-12.0, 9.0))

    def test_the_in_between_frames_sit_between_the_poses_they_join(self):
        width = lambda name: self.frames[name][0].width
        for who in ('codex', 'claude'):
            low, high = sorted((width(f'{who}-idle-0'), width(f'{who}-jab-1')))
            self.assertTrue(low - 6 <= width(f'{who}-tw-jab-in') <= high + 6, f'{who}: the jab\'s lead-in is between the idle pose and the first reach')
            self.assertIn(f'{who}-tw-hit-out', self.frames)
            for name in self.anims[who]['tw']:
                self.assertTrue(60 <= self.frames[name][0].width <= 140, name)
        self.assertGreater(width('claude-tw-whip-out'), width('claude-idle-0'), 'the whip is still out a little as it comes back')

    def test_shadows_and_points_are_written_for_the_scene(self):
        for who in ('codex', 'claude'):
            for move, names in self.anims[who].items():
                for name in names:
                    offset, half, strength = prepare.SHADOWS[name]
                    self.assertTrue(10 <= half <= 40 and 0.0 <= strength <= 1.0 and abs(offset) < 30, f'{name}: {prepare.SHADOWS[name]}')
        with tempfile.TemporaryDirectory() as folder:
            prepare.write(folder, private=Path(folder) / 'none')
            data = json.loads((Path(folder) / 'scene-fighting.json').read_text(encoding='utf-8'))
            self.assertTrue(data['points'] and data['shadows'])
            self.assertEqual(set(data['shadows']) & set(data['frames']), set(data['shadows']))
            self.assertLess((Path(folder) / 'scene-fighting.json').stat().st_size, 200 * 1024, 'the JSON stays far under the 512 KiB limit')
            self.assertLess((Path(folder) / 'scene-fighting.png').stat().st_size, 1024 * 1024, 'and the atlas far under 8 MiB')

    def test_the_new_art_module_reads_no_rom_no_downloads_and_never_uses_the_network(self):
        text = (ROOT / 'scripts/fighting_stage_art.py').read_text(encoding='utf-8')
        code = text.split('"""', 2)[2]
        for forbidden in ('urllib', 'requests', 'socket', 'subprocess', 'http://', 'https://', 'Downloads', '/mnt/c', '.nes', '.smc', '.sfc', '.gba', 'os.system', 'open('):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertIn('ORIGINAL', text)


if __name__ == '__main__':
    unittest.main()
