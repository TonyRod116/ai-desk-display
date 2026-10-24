"""The firmware's scene-animation engine, run on the PC against a simulated board (needs g++)."""
import copy
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'firmware' / 'board' / 'tools'))

from PIL import Image

from token_tv import board_anim
from token_tv.board_arcade import render_arcade
from token_tv.board_city import render_countdown
from token_tv.board_dials import render_dials
from token_tv.board_forge import render_forge
from token_tv.board_prism import render_prism
from token_tv.board_surf import render_surf
from token_tv.board_paradise import render_paradise
from token_tv.board_pages import rgb565_frame
from token_tv.local_usage import local_row
from token_tv.state import UsageStore

NOW = 1000


def snapshot():
    rows = {}
    for provider in ('claude', 'codex'):
        account = {'key': provider, 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo'}
        windows = [{'label': 'WEEK', 'used_percent': 54, 'duration_minutes': 10080, 'resets_at': NOW + 5 * 86400}]
        if provider == 'claude':
            windows.insert(0, {'label': '5H', 'used_percent': 41, 'duration_minutes': 300, 'resets_at': NOW + 7200})
        record = {'source': provider + '_official_cli', 'fetched_at': NOW, 'stale': False,
                  'ordinary_usage_allowed': True, 'windows': windows}
        rows[provider] = local_row(account, record, now=NOW)
    store = UsageStore([{'key': k, 'alias': k, 'provider': k} for k in rows], fetch=lambda a: rows[a['key']])
    store.refresh()
    with patch('token_tv.state.time.time', return_value=NOW):
        return store.snapshot()


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class AnimationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import anim_harness
        cls.directory = tempfile.mkdtemp()
        cls.exe = anim_harness.build(cls.directory)
        with patch('time.time', return_value=NOW), patch('token_tv.state.time.time', return_value=NOW):
            cls.image, payload = render_arcade(snapshot(), animated=True)
        cls.spec = board_anim.decode(payload)
        cls.background = list(struct.unpack('<76800H', rgb565_frame(cls.image)[8:8 + 153600]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def payload(self, sprites_only):
        sprites = []
        for sprite in self.spec['sprites']:
            frames = []
            for words in sprite['frames']:
                frame = Image.new('RGBA', (sprite['w'], sprite['h']), (0, 0, 0, 0))
                for i, word in enumerate(words):
                    if word != board_anim.KEY:
                        frame.putpixel((i % sprite['w'], i // sprite['w']),
                                       (((word >> 11) & 31) << 3, ((word >> 5) & 63) << 2, (word & 31) << 3, 255))
                frames.append(frame)
            sprites.append({'x': sprite['x'], 'y': sprite['y'], 'frames': frames, 'script': sprite['script'],
                            'step_ms': sprite['step_ms']})
        return board_anim.encode(sprites, [] if sprites_only else self.spec['stars'],
                                 None if sprites_only else self.spec['meteor'])

    def run_engine(self, payload, milliseconds, image=None, capture_ms=250):
        out = Path(self.directory) / ('run_%d_%d' % (len(payload), milliseconds))
        out.mkdir(exist_ok=True)
        page = out / 'page.bin'
        page.write_bytes(rgb565_frame(self.image if image is None else image, anim=payload))
        result = subprocess.run([str(self.exe), str(page), str(out), str(milliseconds), str(capture_ms)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertEqual(result.stderr.strip(), '', result.stderr[-1500:])      # no sanitizer report
        return out

    def expected(self, step, background=None, spec=None, elapsed_ms=None):
        words = list(self.background if background is None else background)
        for sprite in (self.spec if spec is None else spec)['sprites']:
            tick = step if elapsed_ms is None else elapsed_ms // sprite['step_ms']
            frame, dx, dy = sprite['script'][tick % len(sprite['script'])]
            data = sprite['frames'][frame]
            for sy in range(sprite['h']):
                for sx in range(sprite['w']):
                    word = data[sy * sprite['w'] + sx]
                    if word == board_anim.KEY:
                        continue
                    for ky in (0, 1):
                        for kx in (0, 1):
                            px, py = sprite['x'] + dx + sx * 2 + kx, sprite['y'] + dy + sy * 2 + ky
                            if 0 <= px < 320 and 0 <= py < 240:                       # a sprite may enter or leave the screen
                                words[py * 320 + px] = word
        return words

    def test_space_ufo_leaves_no_trails_or_damaged_readings_across_two_flybys(self):
        from token_tv.board_space import render_cockpit
        with patch('time.time', return_value=NOW):
            image,payload=render_cockpit(snapshot(),animated=True)
        spec=board_anim.decode(payload)
        background=list(struct.unpack('<76800H',rgb565_frame(image)[8:]))
        # Twinkle pixels are independent; all other pixels must match exactly.
        star_pixels={(y+dy)*320+x+dx for x,y,*_ in spec['stars'] for dx in (0,1) for dy in (0,1)}
        out=self.run_engine(payload,140*64,image=image,capture_ms=140)
        visible=[]
        for step in range(64):
            got=struct.unpack('<76800H',(out/f'screen_{step}.bin').read_bytes())
            expected=self.expected(step,background,spec)
            self.assertTrue(all(a==b or i in star_pixels for i,(a,b) in enumerate(zip(got,expected))),step)
            visible.append(sum(a!=b for i,(a,b) in enumerate(zip(got,background)) if i not in star_pixels))
        self.assertGreater(max(visible),100)
        self.assertEqual(min(visible),0)  # the pause restores the whole ship footprint

    def test_smooth_city_air_traffic_preserves_background_and_quota_pixels(self):
        from token_tv.board_neon_bridge import render_neon_bridge as render_neon_smooth
        for missing in (False, True):
            with patch('time.time', return_value=NOW):
                data=snapshot()
                if missing:
                    for row in data['accounts'].values():
                        row['windows']=[];row['status']='quota_unavailable'
                image,payload=render_neon_smooth(data,animated=True)
            spec=board_anim.decode(payload)
            background=list(struct.unpack('<76800H',rgb565_frame(image)[8:]))
            # Two full cycles of the slow neon, including independent window/traffic clocks.
            out=self.run_engine(payload,44800,image=image,capture_ms=140)
            for step in range(320):
                self.assertEqual((out/f'screen_{step}.bin').read_bytes(),
                    struct.pack('<76800H',*self.expected(step,background,spec,elapsed_ms=step*140)))

    def test_every_pose_is_exactly_the_background_plus_that_pose_and_nothing_is_left_behind(self):
        capture = self.spec['sprites'][0]['step_ms']
        out = self.run_engine(self.payload(True), capture*12, capture_ms=capture)
        for step in range(12):
            got = struct.unpack('<76800H', (out / ('screen_%d.bin' % step)).read_bytes())
            self.assertEqual(struct.pack('<76800H', *got),
                             struct.pack('<76800H', *self.expected(step)), 'step %d' % step)

    def test_knockouts_and_recovery_never_leave_fighters_or_badges_behind(self):
        from test_board_versus import versus_sample, NOW as SAMPLE_NOW
        for left,right in ((0,73),(73,0),(0,0),(None,0),(73,73)):
            with self.subTest(left=left,right=right), patch('time.time',return_value=SAMPLE_NOW):
                image,payload=render_arcade(versus_sample(left,right),animated=True)
                spec=board_anim.decode(payload)
                background=list(struct.unpack('<76800H',rgb565_frame(image)[8:]))
                # Include the moving train scenery for every KO and recovery state.
                with patch.object(self,'spec',spec):
                    clean=self.payload(True)
                capture=spec['sprites'][0]['step_ms']
                out=self.run_engine(clean,capture*32,image=image,capture_ms=capture)
                for step in range(32):
                    self.assertEqual((out/f'screen_{step}.bin').read_bytes(),
                                     struct.pack('<76800H',*self.expected(step,background,spec)),
                                     f'KO state {left}/{right}, step {step}')

    def test_train_runs_cleanly_over_many_cycles_without_leaving_any_pixels_behind(self):
        # Isolate long-running city composition. The independent test below
        # exercises the full sky and proves the meteor's restoration corridor.
        out = self.run_engine(self.payload(True), 20000)
        got = struct.unpack('<76800H', (out / 'screen_79.bin').read_bytes())     # the last full step before 20 s
        # Harness captures the last 20ms tick of each 250ms bucket, not its start.
        want = self.expected(79, elapsed_ms=(80*250-1)//20*20)
        stars = {(s[0] + dx, s[1] + dy) for s in self.spec['stars'] for dx in (0, 1) for dy in (0, 1)}
        stray = [i for i, (a, b) in enumerate(zip(got, want)) if a != b and (i % 320, i // 320) not in stars]
        self.assertEqual(stray, [])                                               # only star blocks may differ

    def test_versus_meteor_is_occasional_clears_and_never_overwrites_hud_or_fighters(self):
        out = self.run_engine(self.payload(False), 45000)
        stars = {((y+dy)*320+x+dx) for x,y,*_ in self.spec['stars']
                 for dx in (0,1) for dy in (0,1)}
        # Includes the previous-frame restoration box, tail and head. This
        # corridor is above VS and between both providers' readings.
        corridor = {y*320+x for y in range(36,92) for x in range(50,156)}
        moving=[]
        for step in range(180):
            got=struct.unpack('<76800H',(out/f'screen_{step}.bin').read_bytes())
            expected=self.expected(step, elapsed_ms=((step+1)*250-1)//20*20)
            changes={i for i,(a,b) in enumerate(zip(got,expected)) if a!=b}-stars
            self.assertFalse(changes-corridor, f'Outside sky at frame {step}')
            protected={y*320+x for y in range(54,82) for x in range(6,82)}
            protected.update(y*320+x for y in range(30,42) for x in range(62,119))
            self.assertFalse(changes & protected, f'Meteor crossed quota/reserves at {step}')
            moving.append(bool(changes))
        starts=[i for i,active in enumerate(moving) if active and (i==0 or not moving[i-1])]
        self.assertGreaterEqual(len(starts),2)
        self.assertLessEqual(len(starts),5)
        self.assertTrue(all(b-a>=40 for a,b in zip(starts,starts[1:])))
        self.assertLess(sum(moving),30)  # Most of the time the meteor is absent.
        self.assertFalse(moving[-1])   # Restored sky, no permanent trail.

    def test_driving_scene_repeats_cleanly_and_preserves_every_instrument_pixel_on_firmware_seven(self):
        for data in (snapshot(), {'accounts': {}}):
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                image, payload = render_dials(data, animated=True)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = spec['sprites'][0]['step_ms']
                steps = max(len(sprite['script']) for sprite in spec['sprites']) * 2     # two cycles of the slowest
                out = self.run_engine(payload, capture * steps, image=image, capture_ms=capture)
                for step in range(steps):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    self.assertEqual(list(got), self.expected(step, background, spec), f'road step {step}')

    def test_the_city_animation_repeats_cleanly_on_firmware_seven(self):
        for data in (snapshot(), {'accounts': {}}):
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                image, payload = render_countdown(data, animated=True)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = spec['sprites'][0]['step_ms']
                steps = max(len(sprite['script']) for sprite in spec['sprites']) * 2          # two cycles
                out = self.run_engine(payload, capture * steps, image=image, capture_ms=capture)
                for step in range(steps):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    self.assertEqual(list(got), self.expected(step, background, spec), f'city step {step}')

    def test_cyberpunk_skyline_and_air_traffic_repeat_without_ghosts_or_erasing_quota_instruments(self):
        for data in (snapshot(), {'accounts': {}}):
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                image, payload = render_forge(data, animated=True)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = spec['sprites'][0]['step_ms']
                steps = max(len(sprite['script']) for sprite in spec['sprites']) * 2
                out = self.run_engine(payload, capture * steps, image=image, capture_ms=capture)
                for step in range(steps):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    self.assertEqual(list(got), self.expected(step, background, spec), f'forge step {step}')

    def test_tropical_water_and_palm_repeat_without_trails_or_erasing_quota_instruments(self):
        for data in (snapshot(), {'accounts': {}}):
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                image, payload = render_paradise(data, animated=True)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = spec['sprites'][0]['step_ms']
                steps = max(len(sprite['script']) for sprite in spec['sprites']) * 2
                out = self.run_engine(payload, capture * steps, image=image, capture_ms=capture)
                for step in range(steps):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    self.assertEqual(list(got), self.expected(step, background, spec), f'paradise step {step}')

    def test_crystal_repeats_without_ghosts_or_erasing_weekly_readings_and_resets(self):
        for data in (snapshot(), {'accounts': {}}):
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                image, payload = render_prism(data, animated=True)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = spec['sprites'][0]['step_ms']
                steps = len(spec['sprites'][0]['script']) * 2
                out = self.run_engine(payload, capture * steps, image=image, capture_ms=capture)
                for step in range(steps):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    self.assertEqual(list(got), self.expected(step, background, spec), f'crystal step {step}')

    def test_surf_repeats_without_ghosts_or_erasing_weekly_readings_and_resets(self):
        for data in (snapshot(), {'accounts': {}}):
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                image, payload = render_surf(data, animated=True)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = spec['sprites'][0]['step_ms']
                steps = max(len(sprite['script']) for sprite in spec['sprites']) * 2   # the gulls' 32 steps, twice
                out = self.run_engine(payload, capture * steps, image=image, capture_ms=capture)
                for step in range(steps):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    self.assertEqual(struct.pack('<76800H', *got),
                                     struct.pack('<76800H', *self.expected(step, background, spec)),
                                     f'surf step {step}')


if __name__ == '__main__':
    unittest.main()
