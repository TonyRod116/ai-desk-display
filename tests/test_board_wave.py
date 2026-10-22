"""Full-ocean movement, stationary foreground and real native-engine safety."""

import copy
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import ImageColor

from tests.test_board_forge import NOW, sample
from token_tv import board_wave as wave
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_pages import frame_size, render_board_pages, rgb565_frame
from token_tv.board_paradise import render_paradise

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'firmware'/'board'/'tools'))


def scene(data):
    with patch('time.time', return_value=NOW):
        image, payload = render_paradise(data, waves=True)
    background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
    return image, payload, background, wave.decode(payload)


class OceanTests(unittest.TestCase):
    def test_only_paradise_changes_and_old_firmware_keeps_its_animation(self):
        with patch('time.time', return_value=NOW):
            old = render_board_pages(sample(), stars=True, anim=True)
            new = render_board_pages(sample(), stars=True, anim=True, waves=True)
        self.assertEqual(old[:1]+old[2:], new[:1]+new[2:])
        self.assertEqual(old[1][153608:153612], b'ANIM')
        self.assertEqual(new[1][153608:153612], b'WAVE')
        self.assertEqual(old[1][:153608], new[1][:153608])
        self.assertLessEqual(len(new[1]), MAX_PAGE_BYTES)
        self.assertEqual(frame_size(new[1]), (320,240))
        for broken in (new[1][:-1], new[1]+b'x'):
            self.assertIsNone(frame_size(broken))

    def test_water_moves_at_all_depths_and_behind_glass_but_every_ink_pixel_is_exact(self):
        _, _, bg, ocean = scene(sample())
        peak = wave.render_words(bg,ocean,32)
        self.assertEqual(peak[:320*wave.TOP], bg[:320*wave.TOP])
        def changed(box):
            x0,y0,x1,y1 = box
            return sum(max(abs(a-b) for a,b in zip(wave.rgb(bg[y*320+x]),wave.rgb(peak[y*320+x]))) >= 3
                       for y in range(y0,y1) for x in range(x0,x1))
        self.assertGreater(changed((316,126,320,148)), 40)  # distant sea
        self.assertGreater(changed((145,155,183,178)), 400)  # middle water
        self.assertGreater(changed((90,208,183,239)), 1500)  # foreground
        self.assertGreater(changed((192,150,198,215)), 120)  # through the glass
        self.assertEqual(changed((0,124,25,239)),0)  # far dry beach
        for i in range(320*wave.ROWS):
            if ocean['keep'][i//8] & (1 << (i%8)):
                self.assertEqual(bg[320*wave.TOP+i],peak[320*wave.TOP+i])
        self.assertEqual(wave.render_words(bg,ocean,wave.STEPS),bg)
        # Measure the photographic foam's leading edge, including the old dry sand.
        def foam_edge(words,y):
            return max((sum(abs(a-b) for a,b in zip(wave.rgb(words[y*320+x]),wave.rgb(words[y*320+x+2]))),x)
                       for x in range(25,100))[1]
        for y in (206,220):
            self.assertGreaterEqual(foam_edge(bg,y)-foam_edge(peak,y),30)

    def test_unknown_old_hearts_and_session_remain_fixed_during_the_wave(self):
        missing = sample(hearts=None)
        old = copy.deepcopy(missing)
        old['accounts']['claude']['banked_resets']['last_known'] = 1
        for data in (sample(0,hearts=0),missing,old,sample(hearts=4),sample(session=False),{'accounts':{}}):
            _,_,bg,ocean = scene(data)
            for step in (1,16,32,48,63):
                got = wave.render_words(bg,ocean,step)
                for i in range(320*wave.ROWS):
                    if ocean['keep'][i//8] & (1 << (i%8)):
                        self.assertEqual(got[320*wave.TOP+i],bg[320*wave.TOP+i])

    def test_moving_water_keeps_instrument_contrast_above_four_and_a_half(self):
        from token_tv.board_paradise import COLORS, INK, MUTED
        _,_,bg,ocean = scene(sample())
        def luminance(c):
            channels = [v/255 for v in wave.rgb(c)]
            linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
            return sum(a*b for a,b in zip(linear,(.2126,.7152,.0722)))
        darkest = min(luminance(wave.blend(c,ocean['glass_colour'],156)) for c in ocean['palette'])
        for colour in (*COLORS.values(),INK,MUTED):
            ink = luminance(wave.word(ImageColor.getrgb(colour)))
            self.assertGreaterEqual((darkest+.05)/(ink+.05),4.5)

    def test_resets_fit_inside_both_rounded_panels_with_a_margin(self):
        from token_tv.board_art import Scene, SS, _row
        from token_tv.board_paradise import _instrument
        from token_tv.themes import face
        with patch('time.time', return_value=NOW):
            for provider,y in (('codex',37),('claude',137)):
                canvas = Scene()
                with patch.object(canvas,'text',wraps=canvas.text) as text:
                    _instrument(canvas,_row(sample(),provider),provider,y)
                bottom = y+(101 if provider=='claude' else 93)
                for call in text.call_args_list[-2:]:
                    xy,label,font,size,colour = call.args
                    bbox = canvas.d.textbbox((xy[0]*SS,xy[1]*SS),label,
                                            font=face(font,size*SS),anchor=call.kwargs['anchor'])
                    self.assertGreaterEqual(bbox[0]/SS,195)
                    self.assertLessEqual(bbox[2]/SS,310)
                    self.assertLessEqual(bbox[3]/SS,bottom-5)
                    if provider=='claude':
                        self.assertGreaterEqual(bbox[1]/SS,y+79)  # below both session bars


@unittest.skipUnless(shutil.which('g++'),'needs native compiler')
class NativeOceanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import anim_harness
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name)
        cls.exe = anim_harness.build(cls.folder)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_scene(self,image,payload,name,total):
        folder = self.folder/name
        folder.mkdir()
        path = folder/'page.tvf'
        # Deliberately bypass the PC validator here to challenge the actual firmware parser.
        raw = rgb565_frame(image)+b'WAVE'+struct.pack('<I',len(payload))+payload
        path.write_bytes(raw)
        result = subprocess.run([str(self.exe),str(path),str(folder),str(total),'100'],
                                capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stderr,'')  # ASAN + UBSAN
        return folder,result.stdout

    def test_real_firmware_matches_every_native_pixel_for_two_cycles_known_and_unknown(self):
        for name,data in (('known',sample()),('unknown',{'accounts':{}})):
            image,payload,bg,ocean = scene(data)
            folder,receipt = self.run_scene(image,payload,name,12800)
            self.assertIn('wave=1',receipt)
            self.assertIn('region=2560',receipt)
            for step in range(64):
                expected = struct.pack('<76800H',*wave.render_words(bg,ocean,step))
                for cycle in (0,64):
                    got = (folder/f'screen_{step+cycle}.bin').read_bytes()
                    self.assertEqual(got,expected,f'{name} step {step+cycle}')
            self.assertEqual((folder/'screen_12800.bin').read_bytes(),struct.pack('<76800H',*bg))

    def test_malformed_oceans_leave_the_page_static_and_release_memory(self):
        image,payload,bg,_ = scene(sample())
        bad_version = bytes([2])+payload[1:]
        bad_row = bytearray(payload)
        struct.pack_into('<H',bad_row,wave.HEADER.size,320)
        bad_steps = bytearray(payload)
        struct.pack_into('<H',bad_steps,8,0)
        for i,bad in enumerate((payload[:11],payload[:-1],payload+b'x',bad_version,bytes(bad_row),bytes(bad_steps))):
            folder,receipt = self.run_scene(image,bad,f'invalid{i}',200)
            self.assertIn('readAnim=0',receipt)
            self.assertIn('wave=0',receipt)
            self.assertEqual((folder/'screen_200.bin').read_bytes(),struct.pack('<76800H',*bg))
