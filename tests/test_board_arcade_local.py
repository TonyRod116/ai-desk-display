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
        background, payload = render_arcade(data, animated=True)
        spec = board_anim.decode(payload)
        self.assertEqual(len(spec['sprites']), 4)
        self.assertIsNone(spec['meteor'])
        self.assertEqual(spec['stars'], [])
        self.assertLessEqual(len(rgb565_frame(background, anim=payload)), MAX_PAGE_BYTES)
        self.assertEqual(spec['sprites'][1]['w'], 1)  # confirmed Claude zero is KO
        self.assertEqual(background.getpixel((142, 24)),
                         tuple(bytes.fromhex(HEALTH_AMBER['mid'][1:])))
        self.assertEqual(tuple(compose(background, spec, 0)),
                         tuple(struct.unpack('<76800H', rgb565_frame(render_arcade(data))[8:])))
        for sprite in spec['sprites'][2:]:
            self.assertGreaterEqual(len({tuple(frame) for frame in sprite['frames']}), 3)
        boxes = [(s['x'], s['y'], s['x'] + 2*s['w'], s['y'] + 2*s['h'])
                 for s in spec['sprites']]
        for i, (left, top, right, bottom) in enumerate(boxes):
            for a, b, c, d in boxes[i + 1:]:
                self.assertFalse(left < c and a < right and top < d and b < bottom)
