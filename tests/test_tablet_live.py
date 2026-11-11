import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts import prepare_tablet_live as prepare
from scripts import tablet_media
from token_tv import tablet_live as live
from token_tv import tablet_server

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return {
        'water': {'regions': [[0, .74, 1, 1]], 'glints': 1.2},
        'clouds': {'regions': [[[0, 0], [1, 0], [1, .6], [0, .7]]]},
        'lights': {}, 'mist': {'regions': [[0, .6, 1, .8]], 'amount': .4}, 'rain': {'amount': .3},
        'craft': [{'kind': 'gull', 'from': [-.1, .2], 'to': [1.1, .12], 'seconds': 40}],
    }


class LiveBlockTests(unittest.TestCase):
    def test_a_good_block_comes_back_clean_with_its_defaults(self):
        clean = live.live_info(sample(), 'violet-horizon')
        self.assertEqual(clean['version'], 1)
        self.assertEqual(sorted(clean), ['clouds', 'craft', 'lights', 'mist', 'rain', 'version', 'water'])
        self.assertEqual(clean['water'], {'regions': [[0, .74, 1, 1]], 'amount': 1, 'speed': 1, 'scale': 1, 'glints': 1.2, 'glint_size': 1, 'glint_density': 1, 'feather': .02, 'horizon': .74})
        self.assertEqual(clean['mist']['tint'], [.7, .76, .9])
        self.assertEqual(clean['rain']['tint'], [.7, .8, 1.0])
        self.assertEqual(clean['craft'][0]['count'], 3)
        self.assertEqual(clean['craft'][0]['every'], 68)
        self.assertEqual(clean['craft'][0]['size'], .028)
        self.assertEqual(json.loads(json.dumps(clean)), clean, 'plain JSON')

    def test_the_clean_block_is_stable(self):
        once = live.live_info(sample(), 'city')
        self.assertEqual(live.live_info(once, 'city'), once)

    def test_nothing_usable_is_none(self):
        for raw in (None, {}, [], 'wet', 5, True, {'version': 1}, {'bogus': {'regions': [[0, 0, 1, 1]]}}, {'water': {}}, {'water': 'x'}, {'water': {'regions': []}}, {'craft': []}):
            self.assertIsNone(live.live_info(raw, 'city'), repr(raw))

    def test_unknown_keys_are_dropped_and_reported(self):
        clean, problems = live.check_live({'water': {'regions': [[0, .5, 1, 1]], 'sparkle': 9}, 'fog': {'amount': 1}}, 'city')
        self.assertNotIn('sparkle', clean['water'])
        self.assertNotIn('fog', clean)
        self.assertTrue(any('fog' in p for p in problems))

    def test_a_bad_number_drops_its_effect_and_only_that(self):
        clean, problems = live.check_live({'water': {'regions': [[0, .5, 1, 1]], 'amount': 9}, 'clouds': {'regions': [[0, 0, 1, .5]], 'amount': 1}}, 'city')
        self.assertNotIn('water', clean)
        self.assertIn('clouds', clean)
        self.assertTrue(any(p.startswith('water:') for p in problems))
        for key, value in (('amount', -1), ('speed', .1), ('scale', 5), ('glints', 3), ('glint_size', 0), ('glint_density', 1.1), ('feather', 0), ('horizon', 2)):
            self.assertIsNone(live.live_info({'water': {'regions': [[0, .5, 1, 1]], key: value}}, 'city'), key)

    def test_booleans_nan_infinity_and_text_are_not_numbers(self):
        for value in (True, False, float('nan'), float('inf'), -float('inf'), '1', [1], {'a': 1}):
            self.assertIsNone(live.live_info({'rain': {'amount': value}}, 'city'), repr(value))
        self.assertIsNotNone(live.live_info({'rain': {'amount': 1}}, 'city'))
        self.assertIsNotNone(live.live_info({'rain': {'amount': 0.5}}, 'city'))

    def test_regions_stay_inside_the_picture_and_have_some_area(self):
        for region in ([0, .5, 1.1, 1], [-.1, .5, 1, 1], [.5, .5, .5, 1], [.6, 0, .4, 1], [0, 0, 1], [], 'a', [[0, 0], [1, 1]], [[0, 0], [1, 0], [2, 0]], [[0, 0], [1, 0], [.5, 0]], [[0, 0], [1], [1, 1]], [[0, 0, 1], [1, 0, 1], [1, 1, 1]]):
            self.assertIsNone(live.live_info({'water': {'regions': [region]}}, 'city'), repr(region))
        self.assertIsNotNone(live.live_info({'water': {'regions': [[[0, 0], [1, 0], [.5, 1]]]}}, 'city'))
        self.assertIsNotNone(live.live_info({'water': {'regions': [[0, 0, 1, 1]]}}, 'city'))

    def test_counts_are_bounded(self):
        many = [[0, 0, .5, .5]] * (live.MAX_REGIONS + 1)
        self.assertIsNone(live.live_info({'water': {'regions': many}}, 'city'))
        self.assertIsNotNone(live.live_info({'water': {'regions': many[:live.MAX_REGIONS]}}, 'city'))
        ring = [[.5 + .4 * math.cos(i / 5), .5 + .4 * math.sin(i / 5)] for i in range(live.MAX_POINTS + 1)]
        self.assertIsNone(live.live_info({'water': {'regions': [ring]}}, 'city'))
        self.assertIsNotNone(live.live_info({'water': {'regions': [ring[:live.MAX_POINTS]]}}, 'city'))
        craft = [{'kind': 'drone', 'from': [0, 0], 'to': [1, 0]}] * (live.MAX_CRAFT + 3)
        self.assertEqual(len(live.live_info({'craft': craft}, 'city')['craft']), live.MAX_CRAFT)

    def test_the_horizon_defaults_to_the_top_of_the_regions(self):
        self.assertEqual(live.live_info({'water': {'regions': [[0, .8, 1, 1], [0, .7, .5, 1]]}}, 'city')['water']['horizon'], .7)
        self.assertEqual(live.live_info({'water': {'regions': [[[0, .65], [1, .7], [1, 1], [0, 1]]]}}, 'city')['water']['horizon'], .65)
        self.assertEqual(live.live_info({'water': {'regions': [[0, .8, 1, 1]], 'horizon': .75}}, 'city')['water']['horizon'], .75)

    def test_water_accepts_independent_glint_size_and_density(self):
        water = live.live_info({'water': {'regions': [[0, .5, 1, 1]], 'glint_size': .48, 'glint_density': .35}}, 'paradise')['water']
        self.assertEqual((water['glint_size'], water['glint_density']), (.48, .35))
        self.assertEqual(live.live_info({'water': {'regions': [[0, .5, 1, 1]], 'glint_density': 0}}, 'paradise')['water']['glint_density'], 0)

    def test_craft_follow_their_own_rules(self):
        base = {'kind': 'ship', 'from': [-.1, .3], 'to': [1.1, .2]}
        good = live.live_info({'craft': [base]}, 'city')['craft'][0]
        self.assertEqual((good['count'], good['size'], good['seconds'], good['every'], good['colour']), (1, .03, 60, 102, [.35, .8, 1.0]))
        for bad in ({'kind': 'ufo'}, {'from': [-.5, 0]}, {'to': [2, 0]}, {'from': [.5, .5], 'to': [.5, .5]}, {'seconds': 3}, {'seconds': 1000}, {'size': .5}, {'count': 2}, {'every': 10}, {'bob': 1}, {'flap': 9}, {'colour': [2, 0, 0]}):
            self.assertIsNone(live.live_info({'craft': [{**base, **bad}]}, 'city'), repr(bad))
        gulls = live.live_info({'craft': [{'kind': 'gull', 'from': [0, 0], 'to': [1, 0], 'count': 6}]}, 'city')['craft'][0]
        self.assertEqual(gulls['count'], 6)
        swallow = {'kind': 'swallow', 'from': [-.1, .2], 'to': [1.1, .2]}
        bird = live.live_info({'craft': [swallow]}, 'paradise')['craft'][0]
        self.assertEqual((bird['count'], bird['size']), (2, .013))
        self.assertEqual(live.live_info({'craft': [{**swallow, 'count': 1}]}, 'paradise')['craft'][0]['count'], 1)
        self.assertIsNone(live.live_info({'craft': [{**swallow, 'count': 3}]}, 'paradise'))
        self.assertIsNone(live.live_info({'craft': [{'kind': 'gull', 'from': [0, 0], 'to': [1, 0], 'count': 7}]}, 'city'))
        self.assertIsNone(live.live_info({'craft': [{'kind': 'gull', 'from': [0, 0], 'to': [1, 0], 'count': 2.5}]}, 'city'))
        mixed, problems = live.check_live({'craft': [{'kind': 'ufo', 'from': [0, 0], 'to': [1, 1]}, base]}, 'city')
        self.assertEqual(len(mixed['craft']), 1, 'a bad craft is dropped alone')
        self.assertEqual(len(problems), 1)

    def test_lamps_are_rows_of_modules_for_the_weekly_quota(self):
        rows = [{'provider': 'codex', 'x': [.225, .55], 'y': .7138, 'count': 26}, {'provider': 'claude', 'x': [.5656, .8906], 'y': .7138, 'count': 26}]
        clean = live.live_info({'lamps': {'rows': rows}}, 'city')
        self.assertEqual(sorted(clean), ['lamps', 'version'])
        self.assertEqual(clean['lamps']['amount'], 1)
        codex, claude = clean['lamps']['rows']
        self.assertEqual((codex['anchor'], claude['anchor']), ('start', 'end'), "lit from each row's outer end")
        self.assertEqual((codex['colour'], claude['colour']), ([1.0, .725, .27], [.318, .863, 1.0]))
        self.assertEqual((codex['height'], codex['count']), (.0125, 26))
        self.assertEqual(live.live_info(clean, 'city'), clean, 'the clean block is stable')
        self.assertEqual(live.live_info({'lamps': {'rows': [{'provider': 'codex', 'x': [.2, .5], 'y': .7}]}}, 'city')['lamps']['rows'][0]['count'], 26)
        for bad in ({'provider': 'grok'}, {'x': [.5, .2]}, {'x': [.2, .21]}, {'x': [.2, 1.2]}, {'x': [.2]}, {'x': 'wide'}, {'y': 2}, {'y': None}, {'count': 1}, {'count': 65}, {'count': 2.5}, {'count': True},
                    {'height': .5}, {'height': 0}, {'anchor': 'middle'}, {'colour': [2, 0, 0]}):
            self.assertIsNone(live.live_info({'lamps': {'rows': [{**rows[0], **bad}]}}, 'city'), repr(bad))
        for lamps in ({}, {'rows': []}, {'rows': 'x'}, {'rows': [rows[0]] * 5}, {'rows': [rows[0]], 'amount': 3}, {'rows': ['codex']}, 'on', 7, [rows[0]]):
            self.assertIsNone(live.live_info({'lamps': lamps}, 'city'), repr(lamps))
        self.assertIsNotNone(live.live_info({'lamps': {'rows': [rows[0]] * live.MAX_LAMP_ROWS}}, 'city'), 'four rows at most')

    def test_one_bad_lamp_row_drops_the_whole_effect_and_only_that(self):
        rows = [{'provider': 'codex', 'x': [.225, .55], 'y': .7138}, {'provider': 'claude', 'x': [.5656, .8906], 'y': .7138, 'count': 1}]
        clean, problems = live.check_live({'water': {'regions': [[0, .5, 1, 1]]}, 'lamps': {'rows': rows}}, 'city')
        self.assertNotIn('lamps', clean, 'half a circuit would read as a half-empty quota')
        self.assertIn('water', clean)
        self.assertTrue(any(p.startswith('lamps:') for p in problems))

    def test_the_scene_name_is_checked(self):
        for scene in ('', 'City', 'a b', 'x' * 41, None, 5, '../x'):
            self.assertIsNone(live.live_info(sample(), scene), repr(scene))
        self.assertIsNotNone(live.live_info(sample(), 'neon-city'))

    def test_a_huge_block_is_refused(self):
        ring = [[round(.5 + .45 * math.cos(i), 4), round(.5 + .45 * math.sin(i), 4)] for i in range(live.MAX_POINTS)]
        raw = {name: {'regions': [ring] * live.MAX_REGIONS} for name in ('water', 'clouds', 'mist')}
        clean, problems = live.check_live(raw, 'city')
        self.assertIsNone(clean)
        self.assertTrue(any('larger than' in p for p in problems))

    def test_the_shipped_presets_are_valid_and_for_photo_scenes_that_exist(self):
        presets = prepare.load_presets()
        clean, problems = prepare.check_presets(presets)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(clean), sorted(presets))
        for name, block in clean.items():
            self.assertIn(name, tablet_server.SCENES)
            self.assertLessEqual(len(json.dumps(block, separators=(',', ':'))), live.MAX_BYTES)
            self.assertEqual(live.live_info(presets[name], name), block, 'the file holds exactly what is served')
        pixel = {'surf', 'token-run', 'fighting'}
        self.assertFalse(pixel & set(presets), 'the pixel looks need no live block')

    def test_the_page_and_the_server_share_their_limits(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('no node on this computer')
        script = ("const l = require(%s); console.log(JSON.stringify({limits: l.LIMITS, regions: l.MAX_REGIONS, points: l.MAX_POINTS, craft: l.MAX_CRAFT, lamps: l.LAMPS}));"
                  % json.dumps(str(ROOT / 'token_tv/tablet_web/stage-live.js')))
        page = json.loads(subprocess.run([node, '-e', script], capture_output=True, text=True, check=True, timeout=30).stdout)
        for effect, specs in live.SPECS.items():
            for key, (low, high, default) in specs.items():
                if key == 'horizon':
                    continue                                    # derived from the regions on both sides
                self.assertEqual(page['limits'][effect][key], [low, high, default], f'{effect}.{key}')
        self.assertEqual((page['regions'], page['points'], page['craft']), (live.MAX_REGIONS, live.MAX_POINTS, live.MAX_CRAFT))
        lamps = page['lamps']
        self.assertEqual((lamps['maxRows'], lamps['count'], lamps['height'], lamps['amount'], lamps['anchors'], lamps['providers']),
                         (live.MAX_LAMP_ROWS, list(live.LAMP_COUNT), list(live.LAMP_HEIGHT), list(live.LAMP_AMOUNT), list(live.LAMP_ANCHORS), list(live.LAMP_PROVIDERS)))
        self.assertEqual(lamps['colour'], {name: list(colour) for name, colour in live.LAMP_COLOUR.items()})


class PrepareToolTests(unittest.TestCase):
    def folder(self, directory):
        directory = Path(directory)
        picture = Image.new('RGB', (480, 320), (20, 24, 60))
        draw = ImageDraw.Draw(picture)
        draw.rectangle((0, 200, 480, 320), fill=(30, 90, 140))
        for x in range(10, 470, 23):
            draw.rectangle((x, 150, x + 10, 160), fill=(255, 230, 150))
        tablet_media.save_image(picture, directory / 'scene-city.jpg')
        tablet_media.save_thumbnail(picture, directory / 'thumb-city.webp')
        tablet_media.update_manifest('city', tablet_media.scene_entry('photo', 'scene-city.jpg', 'image', 480, 320, focus=(.5, .55)), directory)
        tablet_media.update_manifest('surf', tablet_media.scene_entry('crt', 'scene-surf.webm', 'video', 640, 480, fps=7, loop_seconds=2), directory)
        return directory

    def test_apply_adds_the_block_and_keeps_the_rest_of_the_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self.folder(temp)
            before = json.loads((directory / 'scenes.json').read_text())
            clean, problems = prepare.check_presets(prepare.load_presets())
            self.assertEqual(problems, [])
            written = prepare.apply_presets(directory, clean)
            self.assertEqual(written, ['city'], 'only the photo scene that exists here')
            after = json.loads((directory / 'scenes.json').read_text())
            self.assertEqual(after['scenes']['city']['live'], clean['city'])
            self.assertEqual({k: v for k, v in after['scenes']['city'].items() if k != 'live'}, before['scenes']['city'])
            self.assertEqual(after['scenes']['surf'], before['scenes']['surf'])
            self.assertEqual((directory / 'scenes.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(prepare.clear_presets(directory), ['city'])
            self.assertEqual(json.loads((directory / 'scenes.json').read_text()), before)

    def test_the_server_catalogue_carries_the_block_once_it_calls_the_validator(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self.folder(temp)
            clean, _ = prepare.check_presets(prepare.load_presets())
            prepare.apply_presets(directory, clean)
            self.assertEqual(tablet_server.scene_catalog(directory)['info']['city']['live'], clean['city'], 'the server now calls the validator and carries the block')

    def test_the_real_private_folder_needs_an_explicit_yes(self):
        with self.assertRaises(SystemExit):
            prepare.main(['--apply', '--dry-run'])
        with self.assertRaises(SystemExit):
            prepare.main(['--clear'])

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self.folder(temp)
            before = (directory / 'scenes.json').read_text()
            self.assertEqual(prepare.main(['--apply', '--dry-run', '--directory', str(directory)]), 0)
            self.assertEqual((directory / 'scenes.json').read_text(), before)

    def test_the_proposal_for_a_picture_is_always_a_valid_block(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self.folder(temp)
            with Image.open(directory / 'scene-city.jpg') as image:
                found = prepare.propose(image, 'city')
            clean, problems = live.check_live(found['proposal'], 'city')
            self.assertEqual(problems, [])
            self.assertIn('water', clean)
            self.assertIn('clouds', clean)
            self.assertGreaterEqual(found['light_spots'], 12)
            self.assertTrue(0.3 < found['horizon_candidates'][0][0] < 0.95)
            self.assertEqual(prepare.main(['--directory', str(directory), '--only', 'city']), 0)
        for plain in (Image.new('RGB', (64, 64), (0, 0, 0)), Image.new('RGB', (300, 40), (255, 255, 255))):
            self.assertIsNotNone(live.live_info(prepare.propose(plain, 'x')['proposal'], 'x'), 'even a flat picture gives something valid')

    def test_overlays_are_drawn_where_asked_and_nowhere_else(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as out:
            directory = self.folder(temp)
            before = sorted(p.name for p in directory.iterdir())
            clean, _ = prepare.check_presets(prepare.load_presets())
            prepare.apply_presets(directory, clean)
            self.assertEqual(prepare.main(['--overlay', out, '--directory', str(directory)]), 0)
            self.assertEqual([p.name for p in Path(out).iterdir()], ['overlay-city.png'])
            self.assertEqual(sorted(p.name for p in directory.iterdir()), sorted(before + []), 'nothing written next to the pictures')


if __name__ == '__main__':
    unittest.main()
