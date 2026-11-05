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
        clock = patch('time.time', return_value=NOW)
        art.start(); clock.start()
        self.addCleanup(art.stop); self.addCleanup(clock.stop)
        board_zelda._cached_walk.cache_clear()
        self.addCleanup(board_zelda._cached_walk.cache_clear)

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
            self.assertLess(len(payload), 20000)
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
        self.assertEqual(board_zelda.render_quest(old).crop((254,18,316,31)).tobytes(),
                         board_zelda.render_quest(without).crop((254,18,316,31)).tobytes())

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
