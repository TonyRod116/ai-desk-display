"""The optional quest art is private; exercise the screen with fictional pixels."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from token_tv import board_anim, board_zelda
from token_tv.board_pages import rgb565_frame
from token_tv.board_scenes import available, render_archive
from token_tv.sample import snapshot
from tests.test_board_forge import compose

NOW = 2_000_000_000


def sample(used=27):
    data = snapshot(now=NOW, sample=[
        ('codex','CODEX','codex',[('WEEK',used,6 * 86400)]),
        ('claude','CLAUDE','claude',[('WEEK',used,5 * 86400),('5H',41,7200)])])
    for provider in ('codex','claude'):
        data['accounts'][provider]['banked_resets'] = {'available':2}
    return data


def sprite_box(sprite):
    dx = [step[1] for step in sprite['script']]
    dy = [step[2] for step in sprite['script']]
    return (sprite['x'] + min(dx), sprite['y'] + min(dy),
            sprite['x'] + max(dx) + 2 * sprite['w'], sprite['y'] + max(dy) + 2 * sprite['h'])


def overlaps(a,b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class QuestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'walk.png'
        # Distinct made-up poses; no game file or personal picture is read by a test.
        strip = Image.new('RGBA', (192, 26))
        d = ImageDraw.Draw(strip)
        for i in range(8):
            d.rectangle((i * 24 + 6,4,i * 24 + 17,22), fill=(40 + i * 20, 180, 90, 255))
        strip.save(self.path)
        art = patch.object(board_zelda, 'ART', self.path)
        private_paths = [patch.object(board_zelda, key, Path(self.directory.name) / name)
                         for key, name in (('LANDSCAPE', 'landscape.png'), ('ACTION', 'action.png'),
                                           ('GUARD', 'guard.png'))]
        clock = patch('time.time', return_value=NOW)
        for item in (art, clock, *private_paths):
            item.start()
            self.addCleanup(item.stop)
        for cached in (board_zelda._cached_walk, board_zelda._cached_landscape, board_zelda._cached_strip):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)

    def test_optional_local_scene_falls_back_safely_when_incomplete(self):
        self.assertIsNone(board_zelda._local_art())
        Image.new('RGB', (320, 240), '#547443').save(board_zelda.LANDSCAPE)
        for path, width, height in ((board_zelda.ACTION, 29, 30), (board_zelda.GUARD, 24, 24)):
            sheet = Image.new('RGBA', (width * 8, height))
            d = ImageDraw.Draw(sheet)
            for i in range(8):
                d.rectangle((i * width + 5, 5, i * width + 16, 20), fill=(30 + i * 25, 180, 70, 255))
            sheet.save(path)
        before = board_zelda.art_version()
        self.assertEqual(before[0], 'scene')
        for limit in (4, 8):
            image, payload = board_zelda.render_quest(sample(), animated=True, anim_frames=limit)
            sprites = board_anim.decode(payload)['sprites']
            self.assertEqual(len(sprites), 2)
            self.assertTrue(all(len(sprite['script']) == 32 and sprite['step_ms'] == 80 for sprite in sprites))
            self.assertTrue(all(sprite['script'][0] == sprite['script'][-1] for sprite in sprites))
            self.assertEqual(image.getpixel((160, 180)), (84, 116, 67))
        Image.new('RGB', (320, 240), '#4c7655').save(board_zelda.LANDSCAPE)
        self.assertNotEqual(board_zelda.art_version(), before)
        board_zelda.ACTION.unlink()
        self.assertIsNone(board_zelda._local_art())
        self.assertTrue(available('zelda'))
        _, payload = board_zelda.render_quest(sample(), animated=True)
        self.assertEqual(len(board_anim.decode(payload)['sprites']), 3)

    def test_the_scene_uses_a_bundled_traveller_when_private_art_is_missing_or_bad(self):
        self.assertTrue(available('zelda'))
        self.assertTrue(available('game-boy'))
        self.assertEqual(len(board_zelda._walk()), 8)
        Image.new('RGBA', (4, 4)).save(self.path)
        self.assertIsNone(board_zelda.art_version())
        self.assertTrue(available('zelda'))
        self.assertEqual(len(board_zelda._walk()), 8)
        self.path.unlink()
        self.assertTrue(available('zelda'))
        # No local picture or game file is required to render the scene.
        self.assertEqual(render_archive('zelda', sample())[0].size, (320,240))

    def test_animation_loops_without_crossing_the_hud_or_other_sprites(self):
        for frames in (4,8):
            static = board_zelda.render_quest(sample(), anim_frames=frames)
            image, payload = board_zelda.render_quest(sample(), animated=True, anim_frames=frames)
            decoded = board_anim.decode(payload)
            self.assertLess(len(payload), board_anim.MAX_PAYLOAD)
            self.assertEqual(len(decoded['sprites']), 3)
            self.assertTrue(all(len(s['frames']) <= frames for s in decoded['sprites']))
            self.assertEqual(struct.pack('<76800H', *compose(image, decoded, 0)), rgb565_frame(static)[8:])
            boxes = [sprite_box(s) for s in decoded['sprites']]
            for i, box in enumerate(boxes):
                self.assertTrue(0 <= box[0] < box[2] <= 320 and 49 <= box[1] < box[3] <= 240, box)
                for other in boxes[i + 1:]:
                    self.assertFalse(overlaps(box,other), (box,other))
            script = decoded['sprites'][0]['script']
            for a,b in zip(script,script[1:] + script[:1]):
                self.assertLessEqual(abs(a[1] - b[1]),2)
                self.assertLessEqual(abs(a[2] - b[2]),2)
            self.assertNotEqual(compose(image, decoded, 0), compose(image, decoded, 4))

    def test_weekly_life_meters_drain_from_the_top_on_both_sides(self):
        for provider, strip in (('codex', (8, 30, 16, 92)), ('claude', (304, 30, 312, 92))):
            with self.subTest(provider=provider):
                pictures = []
                for used in (100, 50, 0):
                    data = sample()
                    data['accounts'][provider]['windows'][0]['used_percent'] = used
                    pictures.append(board_zelda.render_quest(data).crop(strip))
                empty, half, full = pictures
                upper, lower = (0, 0, 8, 27), (0, 38, 8, 62)
                self.assertIsNone(ImageChops.difference(empty.crop(upper), half.crop(upper)).getbbox())
                self.assertIsNotNone(ImageChops.difference(empty.crop(lower), half.crop(lower)).getbbox())
                self.assertIsNotNone(ImageChops.difference(half.crop(upper), full.crop(upper)).getbbox())
                self.assertIsNone(ImageChops.difference(half.crop(lower), full.crop(lower)).getbbox())

    def test_bush_action_has_a_complete_repeatable_cycle(self):
        for limit in (4, 8):
            _, payload = board_zelda.render_quest(sample(), animated=True, anim_frames=limit)
            action = board_anim.decode(payload)['sprites'][0]
            frames = [frame for frame, _, _ in action['script']]
            self.assertEqual(len(frames), 32)
            self.assertEqual(frames[0], frames[-1])
            self.assertEqual(set(frames), set(range(limit)))
            self.assertGreater(len({tuple(frame) for frame in action['frames']}), 2)

    def test_each_provider_and_credits_are_independent(self):
        normal = sample(used=40)
        codex = copy.deepcopy(normal)
        codex['accounts']['codex']['windows'][0]['used_percent'] = 100
        codex['accounts']['codex'].update(quota_origin='codex_official_cli', identity_verified=True,
                                           credits_balance='12.5')
        a = board_zelda.render_quest(normal)
        b = board_zelda.render_quest(codex)
        self.assertIsNotNone(ImageChops.difference(a.crop((0,0,160,48)), b.crop((0,0,160,48))).getbbox())
        self.assertIsNone(ImageChops.difference(a.crop((160,0,320,48)), b.crop((160,0,320,48))).getbbox())
        unknown = copy.deepcopy(codex)
        del unknown['accounts']['codex']['credits_balance']
        c = board_zelda.render_quest(unknown)
        self.assertIsNotNone(ImageChops.difference(b.crop((0,0,160,48)), c.crop((0,0,160,48))).getbbox())

    def test_old_claude_session_does_not_look_fresh(self):
        data = sample()
        old = copy.deepcopy(data)
        old['accounts']['claude']['status'] = 'stale'
        without = copy.deepcopy(data)
        without['accounts']['claude']['windows'] = without['accounts']['claude']['windows'][:1]
        self.assertEqual(board_zelda.render_quest(old).crop((239,81,300,93)).tobytes(),
                         board_zelda.render_quest(without).crop((239,81,300,93)).tobytes())

    def test_quest_keeps_every_reading_and_unknown_distinct_from_zero(self):
        from tests.test_board_data_grammar import NOW as GRAMMAR_NOW, PAIRS
        with patch('time.time', return_value=GRAMMAR_NOW):
            for label, (before, after) in PAIRS.items():
                with self.subTest(reading=label):
                    self.assertNotEqual(board_zelda.render_quest(before).tobytes(),
                                        board_zelda.render_quest(after).tobytes())

    def test_five_hour_bars_change_in_five_percent_and_quarter_hour_steps(self):
        data = sample()
        small_change = copy.deepcopy(data)
        session = small_change['accounts']['claude']['windows'][1]
        session['used_percent'] = 42
        session['resets_at'] += 60
        self.assertEqual(board_zelda.render_quest(data).tobytes(),
                         board_zelda.render_quest(small_change).tobytes())

        quota_step = copy.deepcopy(data)
        quota_step['accounts']['claude']['windows'][1]['used_percent'] = 46
        time_step = copy.deepcopy(data)
        time_step['accounts']['claude']['windows'][1]['resets_at'] += 900
        self.assertNotEqual(board_zelda.render_quest(data).tobytes(),
                            board_zelda.render_quest(quota_step).tobytes())
        self.assertNotEqual(board_zelda.render_quest(data).tobytes(),
                            board_zelda.render_quest(time_step).tobytes())


if __name__ == '__main__':
    unittest.main()
