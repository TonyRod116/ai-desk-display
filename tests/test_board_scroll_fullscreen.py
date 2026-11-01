"""The moving game world reaches the top without losing the usage HUD."""
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from token_tv import board_scroll
from token_tv.board import BoardDisplay
from token_tv.board_pages import render_board_pages, rgb565_frame
from token_tv.board_platform import _hud, render_platform
from test_board_platform import NOW, sample
from test_board_scroll_original import sample_assets


class FullscreenScrollTests(unittest.TestCase):
    def tearDown(self):
        board_scroll.encode.cache_clear()

    def test_new_capability_is_negotiated_explicitly(self):
        board = BoardDisplay('http://192.168.1.50', '0123456789abcdef')
        with patch.object(board, 'info', return_value={'paired': True, 'scroll': 4}):
            board.ensure_paired()
        self.assertEqual(board.scroll, 4)

    @patch('time.time', return_value=NOW)
    def test_scenery_moves_behind_a_fixed_hud_and_wraps(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            world = Image.new('RGB', (512, 96), (20, 50, 80))
            draw = ImageDraw.Draw(world)
            for x in range(0, 512, 16):
                draw.rectangle((x, 0, x + 7, 95), fill=(80, 110, 140))
            world.save(root / 'world.png')
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                image, payload = render_platform(sample(), animated=True, scroll=4)
                spec = board_scroll.decode(payload)
                self.assertEqual(spec['version'], 4)
                self.assertLessEqual(len(payload), 80000)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                initial = board_scroll.render_words(background, spec, 0)
                moved = board_scroll.render_words(background, spec, 6)
                wrapped = board_scroll.render_words(background, spec, 384)
                self.assertEqual(initial, background)
                self.assertEqual(initial, wrapped)
                self.assertNotEqual(initial[45 * 320 + 300], moved[45 * 320 + 300])
                hud = Image.new('RGBA', (320, 48))
                _hud(hud, sample())
                mask = hud.getchannel('A')
                opaque = [i for i, alpha in enumerate(mask.tobytes()) if alpha == 255]
                self.assertGreater(len(opaque), 1000)
                self.assertTrue(all(initial[i] == moved[i] for i in opaque))

    def test_missing_private_art_uses_existing_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(board_scroll, 'ORIGINAL_ASSETS', Path(tmp)):
            board_scroll.encode.cache_clear()
            _, payload = render_platform(sample(), animated=True, scroll=4)
            self.assertEqual(board_scroll.decode(payload)['version'], 2)

    def test_many_hud_colours_still_fit_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            hud = Image.new('RGBA', (320, 48))
            for x in range(256):
                hud.putpixel((x, 1), (x, 255 - x, (x * 23) % 256, 255))
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                payload = board_scroll.encode_fullscreen(hud)
                spec = board_scroll.decode(payload)
                self.assertEqual(spec['version'], 4)
                self.assertLessEqual(len(payload), 80000)
                frame = board_scroll.render_words([0] * (320 * 240), spec, 0)
                self.assertGreater(len(set(frame[320:320 + 256])), 20)

    @patch('time.time', return_value=NOW)
    def test_other_pages_and_credit_badge_remain_correct(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_assets(root)
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', root):
                board_scroll.encode.cache_clear()
                data = sample(used=100)
                data['accounts']['codex'].update(quota_origin='codex_official_cli',
                                                  identity_verified=True, status='ok',
                                                  credits_balance='137.5')
                old = render_board_pages(data, anim=True, scroll=3)
                new = render_board_pages(data, anim=True, scroll=4)
                self.assertEqual(old[:6] + old[7:], new[:6] + new[7:])
                page = new[6]
                spec = board_scroll.decode(page[153616:])
                static = list(struct.unpack('<76800H', page[8:153608]))
                first = board_scroll.render_words(static, spec, 0)
                later = board_scroll.render_words(static, spec, 80)
                self.assertEqual(first, static)
                for y in range(18, 31):
                    self.assertEqual(first[y * 320 + 12:y * 320 + 83],
                                     later[y * 320 + 12:y * 320 + 83])

    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    @patch('time.time', return_value=NOW)
    def test_firmware_inserts_half_frames_without_speeding_up_or_crossing_blocks(self, _):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'firmware/board/tools'))
        import anim_harness
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / 'assets'
            assets.mkdir()
            sample_assets(assets)
            world = Image.new('RGB', (512, 96))
            draw = ImageDraw.Draw(world)
            for x in range(512):
                draw.line((x, 0, x, 95), fill=(0, 24 + (x % 13) * 14, 40 + (x % 2) * 140))
            world.save(assets / 'world.png')
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', assets):
                board_scroll.encode.cache_clear()
                image, payload = render_platform(sample(), animated=True, scroll=4)
                spec = board_scroll.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                executable = anim_harness.build(root)
                page = root / 'page.bin'
                page.write_bytes(rgb565_frame(image, scroll=payload))
                result = subprocess.run([str(executable), str(page), tmp, '6600', '30', 'precise'],
                                        capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr[-1200:])

                def frame(index):
                    return struct.unpack('<76800H', (root / f'screen_{index}.bin').read_bytes())

                first, halfway, one = frame(0), frame(1), frame(2)
                # The landscape advances 2 pixels at 30 ms and 4 at 60 ms;
                # the same distance in the same time as before.
                row = 80 * 320
                self.assertNotEqual(first[row + 140:row + 300], halfway[row + 140:row + 300])
                self.assertEqual(halfway[row + 140:row + 300], first[row + 142:row + 302])
                self.assertEqual(one[row + 140:row + 300], first[row + 144:row + 304])
                for old_tick in (1, 2, 53, 55, 56, 60, 103, 104, 105, 110):
                    self.assertEqual(frame(old_tick * 2),
                                     tuple(board_scroll.render_words(background, spec, old_tick)))

                actor_colours = set(spec['actor']) - {0xF81F}
                def actor_top(index):
                    pixels = frame(index)
                    return next(y for y in range(48, 240)
                                if any(pixels[y * 320 + x] in actor_colours for x in range(40, 96)))

                # The jump gains an actual in-between height, rather than
                # repeating a pose or completing the arc in half the time.
                y1, middle, y2 = (actor_top(i) for i in (110, 111, 112))
                self.assertEqual(middle, (y1 + y2) // 2)
                self.assertNotIn(middle, (y1, y2))
                # At the half-frames around the hit, Mario's head stays below
                # the block until it rises, including the instant of contact.
                for index in range(204, 215):
                    camera = index * 2
                    block_left = 157 * 3 - camera
                    if block_left < 96 and block_left + 48 > 40:
                        block_bottom = 144 - (3 if index // 2 in (104, 105) else 0)
                        self.assertGreaterEqual(actor_top(index), block_bottom, index)

                # Rendering a frame can take more than 30 ms on the real LCD.
                # One-pixel timeline steps keep the motion even when a frame
                # falls between two of the previous 30 ms positions.
                result = subprocess.run([str(executable), str(page), tmp, '6600', '15', 'precise'],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr[-1200:])
                for index in (1, 2, 3, 4):
                    self.assertEqual(frame(index)[row + 140:row + 300],
                                     first[row + 140 + index:row + 300 + index])
                for index in range(204 * 2, 215 * 2):
                    block_left = 157 * 3 - index
                    if block_left < 96 and block_left + 48 > 40:
                        block_bottom = 144 - (3 if index // 4 in (104, 105) else 0)
                        self.assertGreaterEqual(actor_top(index), block_bottom, index)
                for index in range(200, 280):
                    shell_left = 651 - (10 * (index // 4) + (10 * (index % 4)) // 4)
                    if shell_left < 96 and shell_left + 32 > 40:
                        self.assertLessEqual(actor_top(index) + 64, 187, index)

                # The per-screen speed setting still scales elapsed time; the
                # extra frames must not silently override it.
                for speed, capture, old_tick in ((75, 40, 1), (125, 120, 5)):
                    result = subprocess.run([str(executable), str(page), tmp, str(capture * 2),
                                             str(capture), 'precise', str(speed)],
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr[-1200:])
                    self.assertEqual(frame(2), tuple(board_scroll.render_words(background, spec, old_tick)))

    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    @patch('time.time', return_value=NOW)
    def test_actual_firmware_matches_top_overlay_and_complete_loop(self, _):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'firmware/board/tools'))
        import anim_harness
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / 'assets'
            assets.mkdir()
            sample_assets(assets)
            with patch.object(board_scroll, 'ORIGINAL_ASSETS', assets):
                board_scroll.encode.cache_clear()
                image, payload = render_platform(sample(), animated=True, scroll=4)
                spec = board_scroll.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                executable = anim_harness.build(root)
                page = root / 'page.bin'
                page.write_bytes(rgb565_frame(image, scroll=payload))
                result = subprocess.run([str(executable), str(page), tmp, str(385 * board_scroll.FRAME_MS),
                                         str(board_scroll.FRAME_MS)], capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr[-1200:])
                self.assertIn('readAnim=1', result.stdout)
                for tick in (0, 1, 2, 53, 57, 60, 68, 103, 104, 105, 110, 191, 192,
                             246, 260, 295, 296, 297, 311, 383, 384):
                    actual = (root / f'screen_{tick}.bin').read_bytes()
                    expected = board_scroll.render_words(background, spec, tick)
                    self.assertEqual(actual, struct.pack('<76800H', *expected), f'frame {tick}')
                self.assertEqual((root / 'screen_0.bin').read_bytes(), (root / 'screen_384.bin').read_bytes())


if __name__ == '__main__':
    unittest.main()
