"""The optional local stage is private, safe to omit and preserves real HUD semantics."""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from token_tv import board_anim, board_arcade_local
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_arcade import HEALTH_AMBER, render_arcade
from token_tv.board_pages import rgb565_frame
from test_board_forge import NOW, compose
from test_board_versus import versus_sample


class LocalArcadeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path_patch = patch.object(board_arcade_local, 'ART_DIRECTORY', self.directory)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def artwork(self):
        Image.new('RGB', (320, 240), '#6291b0').save(self.directory / 'stage.png')
        for index, (_, _, w, h) in enumerate(board_arcade_local.EFFECTS):
            for frame in range(board_arcade_local.EFFECT_FRAMES):
                layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
                if frame:
                    layer.putpixel((5 + frame, 3), (250, 230, 100, 255))
                layer.save(self.directory / f'ambient-{index}-{frame}.png')

    @patch('time.time', return_value=NOW)
    def test_missing_or_damaged_art_falls_back_to_bundled_stage(self, _):
        fallback, payload = render_arcade(versus_sample(), animated=True)
        self.assertIsNotNone(board_anim.decode(payload)['meteor'])
        self.artwork()
        (self.directory / 'ambient-1-3.png').unlink()
        again, other = render_arcade(versus_sample(), animated=True)
        self.assertEqual(fallback.tobytes(), again.tobytes())
        self.assertEqual(payload, other)
        Image.new('RGB', (2, 2)).save(self.directory / 'stage.png')
        self.assertIsNone(board_arcade_local.load())

    @patch('time.time', return_value=NOW)
    def test_private_stage_keeps_quota_ko_and_resident_animation(self, _):
        self.artwork()
        data = versus_sample(25, 0)
        for frames in (4, 8):
            with self.subTest(frames=frames):
                background, payload = render_arcade(data, animated=True, anim_frames=frames)
                spec = board_anim.decode(payload)
                self.assertEqual(len(spec['sprites']), 4)
                self.assertIsNone(spec['meteor'])
                self.assertEqual(spec['stars'], [])
                self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD if frames == 8 else 40000)
                self.assertLessEqual(len(rgb565_frame(background, anim=payload)), MAX_PAGE_BYTES)
                self.assertEqual(spec['sprites'][1]['w'], 1)  # confirmed Claude zero is KO
                self.assertEqual(background.getpixel((142, 24)),
                                 tuple(bytes.fromhex(HEALTH_AMBER['mid'][1:])))
                self.assertEqual(tuple(compose(background, spec, 0)),
                                 tuple(struct.unpack('<76800H', rgb565_frame(render_arcade(data))[8:])))
                if frames == 8:
                    # No duel without an opponent. A board with eight frames moves the supplied backdrop's two
                    # neighbouring pieces as ONE sprite, which frees the slot the exchange needs.
                    self.assertEqual((spec['sprites'][2]['w'], spec['sprites'][2]['h']), (1, 1))
                    ambient = [spec['sprites'][3]]
                    self.assertEqual((ambient[0]['x'], ambient[0]['w']), (110, 52))
                else:
                    ambient = spec['sprites'][2:]
                for sprite in ambient:
                    self.assertGreaterEqual(len({tuple(frame) for frame in sprite['frames']}), 3)
                boxes = [(s['x'], s['y'], s['x'] + 2*s['w'], s['y'] + 2*s['h'])
                         for s in spec['sprites']]
                for i, (left, top, right, bottom) in enumerate(boxes):
                    for a, b, c, d in boxes[i + 1:]:
                        self.assertFalse(left < c and a < right and top < d and b < bottom)

    @patch('time.time', return_value=NOW)
    def test_merging_the_backdrop_pieces_changes_no_pixel_of_their_animation(self, _):
        # The two pieces share a row and a timing, so one 52 x 14 sprite must show exactly what two sprites showed.
        self.artwork()
        data = versus_sample()
        _, merged = render_arcade(data, animated=True, anim_frames=8)
        _, separate = render_arcade(data, animated=True, anim_frames=4)
        one = board_anim.decode(merged)['sprites'][3]
        left, right = board_anim.decode(separate)['sprites'][2:4]
        self.assertEqual((one['step_ms'], one['script']), (left['step_ms'], left['script']))
        for k, frame in enumerate(one['frames']):
            for y in range(14):
                self.assertEqual(frame[y * 52:y * 52 + 25], left['frames'][k][y * 25:(y + 1) * 25])
                self.assertEqual(frame[y * 52 + 25:(y + 1) * 52], right['frames'][k][y * 27:(y + 1) * 27])
