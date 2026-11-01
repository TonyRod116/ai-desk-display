"""Animated previews use sample pages and never contact the display."""
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from token_tv import board_anim, board_beach, board_scroll
from token_tv.board_control import BoardControl
from token_tv.board_pages import rgb565_frame


class AnimatedPreviewTests(unittest.TestCase):
    def result(self, frame):
        control = BoardControl(None)
        control.update_frames([frame])
        data, mime = control.preview_animation(0)
        if mime == 'image/png':
            self.skipTest('This Pillow build does not support animated WebP')
        self.assertEqual(mime, 'image/webp')
        return Image.open(BytesIO(data)), control

    def test_native_sprites_animate_but_still_screens_remain_still(self):
        background = Image.new('RGB', (320, 240), '#102030')
        moving = Image.new('RGBA', (8, 8), '#f082ed')
        payload = board_anim.encode(sprites=[{'x': 40, 'y': 50, 'frames': [moving],
                                              'script': [(0, 0, 0), (0, 20, 0)], 'step_ms': 200}])
        preview, control = self.result(rgb565_frame(background, anim=payload))
        self.assertGreater(preview.n_frames, 1)
        first = preview.convert('RGB')
        preview.seek(preview.n_frames // 2)
        self.assertIsNotNone(ImageChops.difference(first, preview.convert('RGB')).getbbox())
        again = control.preview_animation(0)
        self.assertEqual(len(control.animated_previews.cache), 1)
        self.assertTrue(again[0])
        still, _ = self.result(rgb565_frame(background))
        self.assertEqual(still.n_frames, 1)

    def test_scrolling_world_is_animated(self):
        background = Image.new('RGB', (320, 240), '#0754aa')
        preview, _ = self.result(rgb565_frame(background, scroll=board_scroll.encode(1)))
        self.assertGreater(preview.n_frames, 2)
        first = preview.convert('RGB')
        preview.seek(preview.n_frames // 3)
        self.assertIsNotNone(ImageChops.difference(first, preview.convert('RGB')).getbbox())

    def test_beach_water_is_animated(self):
        background = Image.new('RGB', (320, 240), '#407080')
        palette = tuple(board_anim.rgb565((i, i, 255)) for i in range(256))
        stride = board_beach.WIDTH * board_beach.HEIGHT
        frames = b''.join(bytes([i * 25]) * stride for i in range(board_beach.FRAMES))
        payload = board_beach.encode((None, palette, frames), version=2)
        preview, _ = self.result(rgb565_frame(background, waves=payload))
        self.assertGreater(preview.n_frames, 2)
        first = preview.convert('RGB')
        preview.seek(preview.n_frames // 3)
        self.assertIsNotNone(ImageChops.difference(first, preview.convert('RGB')).getbbox())

    def test_new_beach_preview_matches_water_and_boat_clocks(self):
        from token_tv.board_preview import _sequence
        background = Image.new('RGB', (320, 240), '#407080')
        palette = tuple(board_anim.rgb565((i, i, 255)) for i in range(256))
        frames = bytes(board_beach.WIDTH * board_beach.HEIGHT * board_beach.FRAMES)
        payload = board_beach.encode((None, palette, frames), version=3)
        with patch.object(board_beach, 'render_words', return_value=[0] * (320 * 240)) as draw:
            sequence, duration = _sequence(rgb565_frame(background, waves=payload))
            self.assertEqual(sum(1 for _ in sequence), 64)
        self.assertEqual(duration, 100)
        for i, call in enumerate(draw.call_args_list):
            self.assertEqual(call.args[2], i * 2 % 64)
            self.assertEqual(call.kwargs['boat_step'], i)

    def test_smooth_beach_preview_preserves_the_three_point_two_second_loop(self):
        from token_tv.board_preview import _sequence
        background = Image.new('RGB', (320, 240), '#407080')
        palette = tuple(board_anim.rgb565((i, i, 255)) for i in range(256))
        stride = board_beach.WIDTH * board_beach.HEIGHT
        old = bytes(stride * board_beach.FRAMES)
        smooth = b''.join(bytes([min(i, 48 - i)]) * stride for i in range(48))
        payload = board_beach.encode((None, palette, old, None, (palette, smooth)), version=4)
        with patch.object(board_beach, 'render_words', return_value=[0] * (320 * 240)) as draw:
            sequence, duration = _sequence(rgb565_frame(background, waves=payload))
            self.assertEqual(sum(1 for _ in sequence), 64)
        self.assertEqual(duration, 100)
        for i, call in enumerate(draw.call_args_list):
            self.assertEqual(call.args[2], i * 12)
        self.assertEqual(draw.call_args_list[32].args[2] % (48 * 8), 0)

    def test_missing_webp_support_falls_back_to_a_still_without_board_access(self):
        control = BoardControl(None)
        control.update_frames([rgb565_frame(Image.new('RGB', (320, 240), '#123456'))])
        with patch('token_tv.board_preview._encode', side_effect=OSError('WebP unavailable')):
            data, mime = control.preview_animation(0)
        self.assertEqual(mime, 'image/png')
        self.assertEqual(Image.open(BytesIO(data)).format, 'PNG')


if __name__ == '__main__':
    unittest.main()
