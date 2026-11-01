"""The platform camera moves on the board while the usage HUD stays fixed."""
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
from token_tv.board_pages import frame_size, render_board_pages, rgb565_frame
from token_tv.board_platform import render_platform
from test_board_platform import NOW, sample


class ScrollingWorldTests(unittest.TestCase):
    def test_camera_adds_intermediate_frames_without_changing_travel_speed(self):
        self.assertEqual(board_scroll.FRAME_MS, 60)
        self.assertEqual(board_scroll.FRAME_MS * 2, board_scroll.STEP_MS)
        spec = board_scroll.decode(board_scroll.encode())
        background = [0] * (320 * 240)
        first = board_scroll.render_words(background, spec, 0)
        halfway = board_scroll.render_words(background, spec, 1)
        old_step = board_scroll.render_words(background, spec, 2)
        for y in (58, 90, 120):
            for x in range(140, 316, 4):
                self.assertEqual(halfway[y * 320 + x], first[y * 320 + x + 2])
                self.assertEqual(old_step[y * 320 + x], first[y * 320 + x + 4])

    @patch('time.time', return_value=NOW)
    def test_world_moves_forward_and_wraps_without_changing_hud(self, _):
        image, payload = render_platform(sample(), animated=True, scroll=True)
        spec = board_scroll.decode(payload)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        zero = board_scroll.render_words(background, spec, 0)
        self.assertEqual(zero, background)
        one = board_scroll.render_words(background, spec, 1)
        self.assertEqual(zero[:320*board_scroll.TOP], one[:320*board_scroll.TOP])
        # The landscape itself travels left while the camera advances right.
        for y in (58, 90, 120):
            for x in range(140, 316, 4):  # safely outside the rider's rectangle
                self.assertEqual(one[y*320+x],zero[y*320+x+2])
        self.assertNotEqual(zero[320*board_scroll.TOP:], one[320*board_scroll.TOP:])
        period = board_scroll.W * 2 // board_scroll.SPEED
        self.assertEqual(zero, board_scroll.render_words(background, spec, period))
        self.assertLess(len(payload), 80000)

    @patch('time.time', return_value=NOW)
    def test_capability_negotiates_the_new_format_without_touching_other_pages(self, _):
        data = sample()
        old = render_board_pages(data, anim=True)
        new = render_board_pages(data, anim=True, scroll=True)
        self.assertEqual(old[:6]+old[7:], new[:6]+new[7:])
        self.assertEqual(new[6][153608:153612], b'SCRO')
        self.assertEqual(frame_size(new[6]), (320, 240))
        self.assertEqual(old[6][153608:153612], b'ANIM')
        for cut in (1, 20, 100):
            self.assertIsNone(frame_size(new[6][:-cut]))

    @patch('time.time', return_value=NOW)
    def test_bad_headers_are_rejected(self, _):
        _, payload = render_platform(sample(), animated=True, scroll=True)
        for bad in (b'', payload[:-1], b'\x02'+payload[1:]):
            with self.assertRaises((ValueError, struct.error)):
                board_scroll.decode(bad)

    def test_older_boards_never_receive_the_new_trailer_by_guessing_a_version(self):
        board=BoardDisplay('http://192.168.1.50','0123456789abcdef')
        with patch.object(board,'info',return_value={'paired':True,'anim':1,'anim_frames':8}):
            board.ensure_paired()
        self.assertFalse(board.scroll)
        with patch.object(board,'info',return_value={'paired':True,'anim':1,'scroll':1}):
            board.ensure_paired()
        self.assertTrue(board.scroll)
        with patch.object(board,'info',return_value={'paired':True,'anim':1,'scroll':0}):
            board.ensure_paired()
        self.assertFalse(board.scroll)

    def test_rider_clears_each_obstacle_and_lands_on_the_slope(self):
        spec=board_scroll.decode(board_scroll.encode())
        for enemy in (105, 361):
            enemy_top=board_scroll.TOP+2*(spec['heights'][enemy+6]-15)
            crossings=0
            for tick in range(board_scroll.W*2//board_scroll.SPEED):
                enemy_x=2*(enemy-(tick*board_scroll.SPEED//2)%board_scroll.W)
                if enemy_x < board_scroll.ACTOR_X+board_scroll.ACTOR_W and enemy_x+28>board_scroll.ACTOR_X:
                    crossings+=1
                    self.assertLessEqual(board_scroll.actor_y(spec,tick)+board_scroll.ACTOR_H,enemy_top)
            self.assertGreater(crossings,0)
    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    @patch('time.time', return_value=NOW)
    def test_real_firmware_matches_reference_across_the_seam_and_preserves_the_hud(self, _):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'firmware/board/tools'))
        import anim_harness
        image, payload=render_platform(sample(),animated=True,scroll=True)
        spec=board_scroll.decode(payload)
        background=list(struct.unpack('<76800H',rgb565_frame(image)[8:]))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            exe=anim_harness.build(path)
            page=path/'page.bin'
            page.write_bytes(rgb565_frame(image,scroll=payload))
            period=board_scroll.W*2//board_scroll.SPEED
            result=subprocess.run([str(exe),str(page),tmp,str((period+4)*board_scroll.FRAME_MS),
                                   str(board_scroll.FRAME_MS)],
                                  capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stderr[-1200:])
            self.assertIn('readAnim=1',result.stdout)
            for tick in (0,1,2,31,32,37,49,50,97,98,127,128,191,254,255,256,257,259,
                         383,510,511,512,513,515):
                native=(path/f'screen_{tick}.bin').read_bytes()
                reference=board_scroll.render_words(background,spec,tick)
                self.assertEqual(native,struct.pack('<76800H',*reference),f'frame {tick}')
            self.assertEqual((path/'screen_0.bin').read_bytes(),(path/'screen_512.bin').read_bytes())

    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    @patch('time.time', return_value=NOW)
    def test_real_firmware_rejects_malformed_scroll_payload(self, _):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'firmware/board/tools'))
        import anim_harness
        image, payload=render_platform(sample(),animated=True,scroll=True)
        frame=bytearray(rgb565_frame(image,scroll=payload))
        # Valid outer size, invalid world height in the inner header.
        frame[153616+4]=0xff
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);exe=anim_harness.build(path);page=path/'bad.bin'
            page.write_bytes(frame)
            result=subprocess.run([str(exe),str(page),tmp,'120','120'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr[-1200:])
            self.assertIn('readAnim=0',result.stdout)


if __name__ == '__main__':
    unittest.main()
