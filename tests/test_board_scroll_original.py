"""Original-art scrolling stays bounded and compatible with older boards."""
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from token_tv import board_scroll
from token_tv.board import BoardDisplay
from token_tv.board_platform import render_platform
from token_tv.board_pages import render_board_pages, rgb565_frame
from test_board_platform import NOW, sample


def sample_assets(root):
    """Artificial images; the user's private game art never enters the tests."""
    Image.new('RGB', (512, 96), (22, 44, 66)).save(root / 'world.png')
    for i in range(8):
        Image.new('RGBA', (28, 32), (160 + i, 20, 10, 255)).save(root / f'rider-{i}.png')
    Image.new('RGBA', (8, 16), (240, 190, 5, 255)).save(root / 'coin.png')
    Image.new('RGBA', (16, 16), (210, 10, 10, 255)).save(root / 'shell.png')
    Image.new('RGBA', (16, 16), (50, 60, 70, 255)).save(root / 'used-block.png')
    for i in range(2):
        Image.new('RGB', (16, 18), (22, 44, 66)).save(root / f'block-bg-{i}.png')
    (root / 'heights.bin').write_bytes(bytes([77]) * 512)


class OriginalScrollTests(unittest.TestCase):
    def tearDown(self):
        board_scroll.encode.cache_clear()

    def test_popped_coin_has_the_same_scale_and_is_centred_over_each_hit_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                spec = board_scroll.decode(board_scroll.encode(3))
                colour = spec['coin'][0]
                for tick in (104, 296):
                    canvas = [0] * (320 * 240)
                    camera = tick * board_scroll.ZOOM_CAMERA_SPEED % (board_scroll.W * 3)
                    board_scroll._zoom_block_effect(canvas, spec, tick, camera)
                    block = 157 if tick < 192 else 413
                    left = block * 3 - camera
                    actual = [x for x in range(320) if canvas[65 * 320 + x] == colour]
                    self.assertEqual(actual, list(range(left + 12, left + 36)))

    def test_coin_spins_rises_and_falls_before_a_brief_sparkle(self):
        """The block reward is a quick spin and arc, not a coin frozen in the air."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                spec = board_scroll.decode(board_scroll.encode(3))
                colour = spec['coin'][0]
                shapes = []
                for tick in range(104, 111):
                    canvas = [0] * (320 * 240)
                    camera = tick * board_scroll.ZOOM_CAMERA_SPEED % (board_scroll.W * 3)
                    board_scroll._zoom_block_effect(canvas, spec, tick, camera)
                    pixels = [(x, y) for y in range(board_scroll.TOP, 96) for x in range(320)
                              if canvas[y * 320 + x] == colour]
                    self.assertTrue(pixels, tick)
                    shapes.append((max(x for x, _ in pixels) - min(x for x, _ in pixels) + 1,
                                   max(y for _, y in pixels)))
                widths = [width for width, _ in shapes]
                bottoms = [bottom for _, bottom in shapes]
                self.assertGreater(widths[0], widths[1])
                self.assertGreater(widths[1], widths[2])
                self.assertGreater(widths[3], widths[2])
                self.assertGreater(bottoms[0], bottoms[2])
                self.assertGreater(bottoms[2], bottoms[4])
                self.assertGreater(bottoms[6], bottoms[4])

                canvas = [0] * (320 * 240)
                camera = 111 * board_scroll.ZOOM_CAMERA_SPEED % (board_scroll.W * 3)
                board_scroll._zoom_block_effect(canvas, spec, 111, camera)
                self.assertNotIn(colour, canvas)
                self.assertIn(0xffff, canvas)  # brief glint where the coin was collected
                canvas = [0] * (320 * 240)
                board_scroll._zoom_block_effect(canvas, spec, 114, 114 * board_scroll.ZOOM_CAMERA_SPEED)
                self.assertNotIn(0xffff, canvas)

    def test_old_board_and_missing_art_keep_working(self):
        board = BoardDisplay('http://192.168.1.50', '0123456789abcdef')
        with patch.object(board, 'info', return_value={'paired': True, 'scroll': 3}):
            board.ensure_paired()
        self.assertEqual(board.scroll, 3)
        with tempfile.TemporaryDirectory() as tmp, patch.object(board_scroll, 'ORIGINAL_ASSETS', Path(tmp)):
            board_scroll.encode.cache_clear()
            _, payload = render_platform(sample(), animated=True, scroll=3)
            self.assertEqual(board_scroll.decode(payload)['version'], 2)

    def test_private_originals_round_trip_without_changing_legacy_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                payload = board_scroll.encode(3)
                spec = board_scroll.decode(payload)
                self.assertEqual((spec['version'], spec['actor_w'], spec['actor_h'], spec['frames']), (3, 56, 64, 8))
                self.assertEqual(len(spec['coin']), 8 * 16)
                self.assertEqual(len(spec['shell']), 16 * 16)
                self.assertLessEqual(len(payload), 80000)
                self.assertEqual(board_scroll.encode(1)[0], 1)
                self.assertEqual(board_scroll.encode(2)[0], 2)

                # Check every frame of the complete repeating scene, including
                # wraparound: neither the shell nor any block is penetrated.
                contacts = []
                for tick in range(384):
                    camera = (tick * 4) % 1536
                    actor_top = board_scroll.actor_y(spec, tick)
                    left = 651 - 10 * (tick % 192)
                    if left < 96 and left + 32 > 40:
                        self.assertLessEqual(actor_top + 64, 187)
                    target = 157 if tick < 192 else 413
                    for block in (157, 173, 189, 413, 429, 445):
                        left = (block * 3 - camera) % 1536
                        if left > 1200:
                            left -= 1536
                        raised = block == target and tick % 192 in (104, 105)
                        bottom = 144 - (3 if raised else 0)
                        if left < 96 and left + 48 > 40:
                            self.assertGreaterEqual(actor_top, bottom)
                            if raised and actor_top == bottom:
                                contacts.append((tick, block))
                self.assertEqual(contacts, [(104, 157), (296, 413)])
                jump = [board_scroll.jump_height(spec, tick) for tick in range(54, 67)]
                self.assertEqual(len(jump), 13)
                self.assertEqual(max(jump), 99)
                self.assertEqual(jump[0], 0)
                self.assertEqual(jump[-1], 0)
                self.assertGreater(len({board_scroll.actor_frame(spec, tick) for tick in range(55, 66)}), 1)
                # The hit changes the block into its used appearance until it
                # leaves the view, rather than reverting on the next frame.
                for tick in (104, 110, 120, 130):
                    left = 157 * 3 - tick * 4
                    if 0 <= left + 20 < 320:
                        frame = board_scroll.render_words([0] * (320 * 240), spec, tick)
                        self.assertEqual(frame[116 * 320 + left + 20], (6 << 11) | (15 << 5) | 8)

    def test_corrupt_assets_do_not_crash_the_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            (root / 'rider-0.png').write_bytes(b'not an image')
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                _, payload = render_platform(sample(), animated=True, scroll=3)
                self.assertEqual(board_scroll.decode(payload)['version'], 2)

    @patch('time.time', return_value=NOW)
    def test_other_seven_pages_are_unchanged(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                old = render_board_pages(sample(), anim=True, scroll=2)
                new = render_board_pages(sample(), anim=True, scroll=3)
                self.assertEqual(old[:6] + old[7:], new[:6] + new[7:])

    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    def test_firmware_matches_reference_during_jump_hit_and_loop(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'firmware/board/tools'))
        import anim_harness
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                image, payload = render_platform(sample(), animated=True, scroll=3)
                spec = board_scroll.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                executable = anim_harness.build(root)
                page = root / 'page.bin'
                page.write_bytes(rgb565_frame(image, scroll=payload))
                result = subprocess.run([str(executable), str(page), tmp, str(385 * board_scroll.FRAME_MS),
                                         str(board_scroll.FRAME_MS)], capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr[-1200:])
                self.assertIn('readAnim=1', result.stdout)
                for tick in (0, 1, 53, 57, 58, 60, 68, 75, 78, 81, 98, 102, 103, 104, 105,
                             106, 110, 119, 120, 191, 192, 246, 251, 260, 270, 295, 296,
                             297, 302, 311, 383, 384):
                    actual = (root / f'screen_{tick}.bin').read_bytes()
                    expected = board_scroll.render_words(background, spec, tick)
                    self.assertEqual(actual, struct.pack('<76800H', *expected), f'frame {tick}')
                self.assertEqual((root / 'screen_0.bin').read_bytes(), (root / 'screen_384.bin').read_bytes())


if __name__ == '__main__':
    unittest.main()
