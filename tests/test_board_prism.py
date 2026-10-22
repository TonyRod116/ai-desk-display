"""A new luminous page fits the board without moving or animating any reading."""
import copy
import struct
import unittest
from unittest.mock import patch

from token_tv import board_anim
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_pages import FACES, PAGE_NAMES, frame_size, render_board_pages, rgb565_frame
from test_board_forge import NOW, compose, sample


class PrismTests(unittest.TestCase):
    def test_optical_background_and_first_pose_preserve_native_detail(self):
        from PIL import Image
        from pathlib import Path
        from token_tv.board_prism import render_prism
        root = Path(__file__).resolve().parents[1] / 'token_tv/assets'
        with Image.open(root / 'prism-optics.png') as source:
            native = source.convert('RGB')
        with patch('time.time', return_value=NOW):
            background, payload = render_prism(sample(), animated=True)
            static = render_prism(sample())
        self.assertEqual(background.crop((160, 0, 320, 240)).tobytes(), native.tobytes())
        spec = board_anim.decode(payload)
        # First pose is the high-resolution crystal itself, not a doubled icon.
        self.assertTrue(all(word == board_anim.KEY for word in spec['sprites'][0]['frames'][0]))
        self.assertEqual(rgb565_frame(background), rgb565_frame(static))
        pixels = native.load()
        self.assertTrue(any(pixels[x,y] != pixels[x+1,y] for y in range(45,165) for x in range(10,145,2)))

    def test_luminous_poses_fit_the_engine_and_the_first_matches_the_static_fallback(self):
        from token_tv.board_prism import render_prism
        with patch('time.time', return_value=NOW):
            data = sample()
            static = render_prism(data)
            background, payload = render_prism(data, animated=True)
            spec = board_anim.decode(payload)
            words = compose(background, spec, 0)
            self.assertEqual(struct.pack('<76800H', *words), rgb565_frame(static)[8:])
            self.assertEqual(len({struct.pack('<76800H', *compose(background, spec, i))
                                  for i in range(4)}), 4)
            frame = rgb565_frame(background, anim=payload)
            self.assertEqual(frame_size(frame), (320, 240))
            self.assertLessEqual(len(frame), MAX_PAGE_BYTES)
            self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
            self.assertFalse(spec['stars'])
            self.assertIsNone(spec['meteor'])
            for sprite in spec['sprites']:
                for _, dx, dy in sprite['script']:
                    # The whole restored box, including transparent pixels, avoids the HUD.
                    self.assertGreaterEqual(sprite['x'] + dx, 160)
                    self.assertGreaterEqual(sprite['y'] + dy, 40)
                    self.assertLessEqual(sprite['x'] + dx + 2 * sprite['w'], 320)
                    self.assertLessEqual(sprite['y'] + dy + 2 * sprite['h'], 178)
            with patch('time.time', return_value=NOW + 1):
                self.assertEqual(render_prism(data, animated=True), (background, payload))

    def test_readings_are_weekly_unknown_is_distinct_and_only_claude_has_session_bars(self):
        from token_tv.board_prism import render_prism
        cases = [sample(0, hearts=0), sample(100, hearts=3), sample(session=False),
                 sample(hearts=None), {'accounts': {}}]
        changed_reset = copy.deepcopy(cases[0])
        changed_reset['accounts']['codex']['windows'][0]['resets_at'] += 86400
        cases.append(changed_reset)
        with patch('time.time', return_value=NOW):
            images, payloads = zip(*(render_prism(data, animated=True) for data in cases))
            self.assertTrue(all(payload == payloads[0] for payload in payloads))
            self.assertEqual(len({im.crop((0, 40, 160, 240)).tobytes() for im in images}), len(images))
            self.assertTrue(all(im.crop((160, 0, 320, 240)).tobytes() ==
                                images[0].crop((160, 0, 320, 240)).tobytes() for im in images[1:]))
            self.assertNotEqual(render_prism(sample(hearts=0)).tobytes(),
                                render_prism(sample(hearts=None)).tobytes())
            old_hearts = sample(hearts=None)
            old_hearts['accounts']['claude']['banked_resets']['last_known'] = 1
            self.assertNotEqual(render_prism(old_hearts).tobytes(), render_prism(sample(hearts=1)).tobytes())
            self.assertNotEqual(render_prism(sample(hearts=3)).tobytes(), render_prism(sample(hearts=4)).tobytes())
            with_session = render_prism(sample())
            without = render_prism(sample(session=False))
            self.assertEqual(with_session.crop((0, 40, 160, 140)).tobytes(),
                             without.crop((0, 40, 160, 140)).tobytes())
            self.assertNotEqual(with_session.crop((0, 140, 160, 240)).tobytes(),
                                without.crop((0, 140, 160, 240)).tobytes())
            different_session = sample()
            different_session['accounts']['claude']['windows'][1]['used_percent'] = 98
            self.assertEqual(render_prism(different_session).crop((0, 145, 160, 210)).tobytes(),
                             with_session.crop((0, 145, 160, 210)).tobytes())


if __name__ == '__main__':
    unittest.main()
