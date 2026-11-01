"""A closer camera and a clean, bounded jump on the resident platform scene."""
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from token_tv import board_scroll
from token_tv.board import BoardDisplay
from token_tv.board_pages import render_board_pages, rgb565_frame
from token_tv.board_platform import render_platform
from test_board_platform import NOW, sample


class ZoomedPlatformTests(unittest.TestCase):
    def test_new_capability_is_opt_in_and_older_boards_keep_their_format(self):
        board = BoardDisplay('http://192.168.1.50', '0123456789abcdef')
        with patch.object(board, 'info', return_value={'paired': True, 'scroll': 2}):
            board.ensure_paired()
        self.assertEqual(board.scroll, 2)
        with patch.object(board, 'info', return_value={'paired': True, 'scroll': 1}):
            board.ensure_paired()
        self.assertEqual(board.scroll, 1)
        with patch.object(board, 'info', return_value={'paired': True}):
            board.ensure_paired()
        self.assertFalse(board.scroll)
        self.assertEqual(board_scroll.encode()[0], 1)
        self.assertEqual(board_scroll.encode(2)[0], 2)

    @patch('time.time', return_value=NOW)
    def test_other_pages_are_identical_and_the_hud_is_stationary(self, _):
        old = render_board_pages(sample(), anim=True, scroll=1)
        new = render_board_pages(sample(), anim=True, scroll=2)
        self.assertEqual(old[:6] + old[7:], new[:6] + new[7:])
        image, payload = render_platform(sample(), animated=True, scroll=2)
        spec = board_scroll.decode(payload)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        self.assertEqual(board_scroll.render_words(background, spec, 0), background)
        for tick in (1, 54, 60, 68, 80, 192, 383, 384):
            rendered = board_scroll.render_words(background, spec, tick)
            self.assertEqual(rendered[:320 * board_scroll.TOP], background[:320 * board_scroll.TOP])
        self.assertEqual(board_scroll.render_words(background, spec, 384), background)
        self.assertLess(len(payload), 80000)

    def test_rider_is_larger_and_jumps_in_one_smooth_arc(self):
        spec = board_scroll.decode(board_scroll.encode(2))
        self.assertEqual((spec['actor_w'], spec['actor_h']), (48, 54))
        self.assertEqual(spec['frames'], 5)
        for offset in (0, 192):
            elevations = [board_scroll.jump_height(spec, offset + t) for t in range(90)]
            airborne = [i for i, height in enumerate(elevations) if height > 0]
            self.assertLessEqual(len(airborne) * board_scroll.FRAME_MS, 1800)
            peak = elevations.index(max(elevations))
            self.assertEqual(elevations[:peak + 1], sorted(elevations[:peak + 1]))
            self.assertEqual(elevations[peak:], sorted(elevations[peak:], reverse=True))
            self.assertLessEqual(sum(h == max(elevations) for h in elevations), 3)
        for tick in range(384):
            self.assertGreaterEqual(board_scroll.actor_y(spec, tick), board_scroll.TOP)
        for enemy in (105, 361):
            top = board_scroll.TOP + 3 * (spec['heights'][enemy + 6] - board_scroll.ZOOM_ORIGIN - 11)
            collisions = 0
            for tick in range(384):
                dx = (enemy * 3 - tick * board_scroll.ZOOM_CAMERA_SPEED) % (board_scroll.W * 3)
                if dx > 1200:
                    dx -= 1536
                if dx < 88 and dx + 30 > 40:
                    collisions += 1
                    self.assertLessEqual(board_scroll.actor_y(spec, tick) + spec['actor_h'], top)
            self.assertGreater(collisions, 0)

    def test_blocks_are_solid_and_each_hit_releases_one_coin(self):
        spec = board_scroll.decode(board_scroll.encode(2))
        background = [0] * (320 * 240)
        contacts = []
        for tick in range(384):
            camera = tick * board_scroll.ZOOM_CAMERA_SPEED % (board_scroll.W * 3)
            # The first three image rows above Mario's cap are transparent.
            actor_top = board_scroll.actor_y(spec, tick) + 3
            target = 157 if tick < 192 else 413
            for block in (157, 171, 185, 413, 427, 441):
                left = (block * 3 - camera) % (board_scroll.W * 3)
                if left > 1200:
                    left -= 1536
                raised = block == target and tick % 192 in (104, 105)
                top = 96 - (3 if raised else 0)
                if left < 88 and left + 42 > 40:
                    self.assertFalse(actor_top < top + 42 and actor_top + 51 > top,
                                     f'actor entered block {block} on frame {tick}')
                    if actor_top == top + 42:
                        contacts.append((tick, block))
        self.assertEqual(contacts, [(104, 157), (296, 413)])
        for tick, block in ((110, 157), (302, 413)):
            self.assertEqual(board_scroll.coin_age(spec, tick), 6)
            left = (block * 3 - (tick * 4 % 1536)) % 1536
            centre = left + 21
            top = 96 - 5 - 4 * 6
            frame = board_scroll.render_words(background, spec, tick)
            self.assertEqual(frame[(top + 4) * 320 + centre - 4], 0xffd6)
        self.assertIsNone(board_scroll.coin_age(spec, 103))
        self.assertIsNone(board_scroll.coin_age(spec, 120))

    def test_rejects_corrupt_zoom_headers_and_heights(self):
        payload = board_scroll.encode(2)
        bad_width = bytearray(payload)
        bad_width[12] = 0xff
        bad_frames = bytearray(payload)
        bad_frames[18] = 0xff
        bad_height = bytearray(payload)
        bad_height[board_scroll.HEADER.size + 512] = 0
        for bad in (payload[:-1], bytes(bad_width), bytes(bad_frames), bytes(bad_height)):
            with self.assertRaises(ValueError):
                board_scroll.decode(bad)

    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    @patch('time.time', return_value=NOW)
    def test_actual_firmware_matches_the_reference_through_jump_and_wrap(self, _):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'firmware/board/tools'))
        import anim_harness
        image, payload = render_platform(sample(), animated=True, scroll=2)
        spec = board_scroll.decode(payload)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            exe = anim_harness.build(path)
            page = path / 'page.bin'
            page.write_bytes(rgb565_frame(image, scroll=payload))
            result = subprocess.run([str(exe), str(page), tmp, str(388 * board_scroll.FRAME_MS),
                                     str(board_scroll.FRAME_MS)], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-1200:])
            self.assertIn('readAnim=1', result.stdout)
            for tick in (0, 1, 2, 53, 54, 55, 60, 64, 68, 72, 78, 80, 81,
                         98, 99, 100, 101, 102, 103, 104, 105, 106, 109, 110, 119, 120, 191, 192,
                         245, 246, 247, 256, 260, 264, 270, 272, 273,
                         291, 295, 296, 297, 302, 311, 312, 382, 383, 384, 387):
                native = (path / f'screen_{tick}.bin').read_bytes()
                reference = board_scroll.render_words(background, spec, tick)
                self.assertEqual(native, struct.pack('<76800H', *reference), f'frame {tick}')
            self.assertEqual((path / 'screen_0.bin').read_bytes(), (path / 'screen_384.bin').read_bytes())

    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    @patch('time.time', return_value=NOW)
    def test_actual_firmware_rejects_corrupt_zoom_payload(self, _):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'firmware/board/tools'))
        import anim_harness
        image, payload = render_platform(sample(), animated=True, scroll=2)
        frame = bytearray(rgb565_frame(image, scroll=payload))
        frame[153616 + 12] = 0xff  # Actor width cannot exceed the validated payload.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            exe = anim_harness.build(path)
            page = path / 'bad.bin'
            page.write_bytes(frame)
            result = subprocess.run([str(exe), str(page), tmp, '120', '120'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr[-1200:])
            self.assertIn('readAnim=0', result.stdout)


if __name__ == '__main__':
    unittest.main()
