"""The firmware's scene-animation engine, run on the PC against a simulated board (needs g++)."""
import copy
import math
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
        local = patch('token_tv.board_arcade.local_stage.load', return_value=None)
        local.start()
        cls.addClassCleanup(local.stop)
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

    def test_cyber_scenes_restore_the_background_through_two_complete_loops(self):
        from token_tv.board_cyber_scenes import render_city
        for scene in ('violet-horizon', 'neon-district'):
            with self.subTest(scene=scene), patch('time.time', return_value=NOW), \
                    patch('token_tv.board_cyber_scenes.backdrop', return_value=Image.new('RGB', (320, 240), '#c060c0')):
                image, payload = render_city(scene, snapshot(), animated=True)
            spec = board_anim.decode(payload)
            background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
            star_pixels = {(y+dy)*320+x+dx for x, y, *_ in spec['stars'] for dx in (0, 1) for dy in (0, 1)}
            capture = 4000 if scene == 'violet-horizon' else 400
            out = self.run_engine(payload, capture * 16, image=image, capture_ms=capture)
            visible = []
            for step in range(16):
                elapsed = ((step + 1) * capture - 1) // 40 * 40
                got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                expected = self.expected(step, background, spec, elapsed_ms=elapsed)
                self.assertTrue(all(a == b or i in star_pixels for i, (a, b) in enumerate(zip(got, expected))), step)
                visible.append(sum(a != b for i, (a, b) in enumerate(zip(got, background)) if i not in star_pixels))
            self.assertGreater(max(visible), 20)
            for step in range(8):
                self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                                 (out / f'screen_{step + 8}.bin').read_bytes(),
                                 f'{scene}: full cycle at {step}')

    def test_platform_actors_repeat_without_trails_or_erasing_the_score(self):
        from token_tv.board_platform import render_platform
        for limit in (4,8):
            with self.subTest(frame_limit=limit), patch('time.time', return_value=NOW):
                image,payload=render_platform(snapshot(),animated=True,anim_frames=limit)
            spec=board_anim.decode(payload)
            background=list(struct.unpack('<76800H',rgb565_frame(image)[8:]))
            # Two Mario loops, with the cloud, coins and dinosaur on their own clocks.
            capture=200
            out=self.run_engine(payload,capture*64,image=image,capture_ms=capture)
            for step in range(64):
                elapsed=((step+1)*capture-1)//40*40
                self.assertEqual((out/f'screen_{step}.bin').read_bytes(),
                                 struct.pack('<76800H',*self.expected(step,background,spec,elapsed_ms=elapsed)),
                                 f'platform frame {step}, limit {limit}')
            self.assertEqual((out/'screen_0.bin').read_bytes(),(out/'screen_32.bin').read_bytes())

    def test_local_arcade_backdrop_and_distinct_guards_leave_no_trails(self):
        from token_tv.board_arcade_local import EFFECTS
        backdrop = Image.new('RGB', (320, 240), '#5a8cb2')
        effects = []
        for _, _, width, height in EFFECTS:
            frames = []
            for frame in range(4):
                layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
                if frame:
                    layer.putpixel((frame + 3, 3), (250, 210, 100, 255))
                frames.append(layer)
            effects.append(frames)
        with patch('time.time', return_value=NOW), \
                patch('token_tv.board_arcade.local_stage.load', return_value=(backdrop, effects)):
            image, payload = render_arcade(snapshot(), animated=True)
        spec = board_anim.decode(payload)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        capture = 200
        out = self.run_engine(payload, capture * 48, image=image, capture_ms=capture)
        for step in range(48):
            elapsed = ((step + 1) * capture - 1) // 40 * 40
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                             struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed)),
                             f'local arcade frame {step}')

    def test_eight_pose_local_guards_leave_no_trails_or_damage_to_the_hud(self):
        from token_tv.board_arcade_local import EFFECTS
        background_art = Image.new('RGB', (320, 240), '#5a8cb2')
        effects = [[Image.new('RGBA', (w, h), (0, 0, 0, 0)) for _ in range(4)]
                   for _, _, w, h in EFFECTS]
        with patch('time.time', return_value=NOW), \
                patch('token_tv.board_arcade.local_stage.load', return_value=(background_art, effects)):
            image, payload = render_arcade(snapshot(), animated=True, anim_frames=8)
        spec = board_anim.decode(payload)
        # Codex, Claude and the middle box of the exchange, then the supplied backdrop's two pieces as ONE sprite.
        self.assertEqual([len(sprite['frames']) for sprite in spec['sprites']], [6, 7, 8, 4])
        self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        capture = 120
        out = self.run_engine(payload, capture * 64, image=image, capture_ms=capture)         # two full loops
        for step in range(64):
            elapsed = ((step + 1) * capture - 1) // 40 * 40
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                             struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed)),
                             f'eight-pose arcade frame {step}')

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

    def test_the_duel_repeats_exactly_and_neither_burst_nor_recoil_leaves_a_trace(self):
        # Tony, 2026-11-03: a short exchange with hit-stop and a burst. Two full loops of the real engine, pixel by pixel,
        # with every sprite restoring its whole box (the recoil moves Claude's box too).
        with patch('time.time', return_value=NOW):
            image, payload = render_arcade(snapshot(), animated=True, anim_frames=8)
        spec = board_anim.decode(payload)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        with patch.object(self, 'spec', spec):
            clean = self.payload(True)            # sprites only: no twinkling star or shooting star to tell apart
        capture = 120
        out = self.run_engine(clean, capture * 64, image=image, capture_ms=capture)
        for step in range(64):
            elapsed = ((step + 1) * capture - 1) // 40 * 40
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                             struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed)),
                             f'duel step {step}')
        for step in range(32):
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(), (out / f'screen_{step + 32}.bin').read_bytes(),
                             f'the loop closes at beat {step}')
        shown = [struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes()) for step in range(32)]
        self.assertGreaterEqual(len({tuple(frame) for frame in shown}), 12)      # a loop with real motion in it
        # Outside the sprites' boxes (scoreboard, arena edges, footer) not one pixel ever differs from the page.
        for frame in shown:
            for y in list(range(0, 108)) + list(range(205, 240)):
                self.assertEqual(frame[y * 320:(y + 1) * 320], tuple(background[y * 320:(y + 1) * 320]), y)

    def test_every_pose_is_exactly_the_background_plus_that_pose_and_nothing_is_left_behind(self):
        capture = 150
        cycle = math.lcm(*(len(s['script'])*s['step_ms'] for s in self.spec['sprites']))
        steps = cycle * 2 // capture
        out = self.run_engine(self.payload(True), capture*steps, capture_ms=capture)
        for step in range(steps):
            got = struct.unpack('<76800H', (out / ('screen_%d.bin' % step)).read_bytes())
            # The harness records the last 20ms sample in each interval, and
            # the firmware updates at most every 40ms. Actors have separate
            # clocks, so one shared step index cannot describe their poses.
            elapsed = ((step+1)*capture-1)//40*40
            self.assertEqual(struct.pack('<76800H', *got),
                             struct.pack('<76800H', *self.expected(step,elapsed_ms=elapsed)), 'step %d' % step)

    def test_knockouts_and_recovery_never_leave_fighters_or_badges_behind(self):
        from test_board_versus import versus_sample, NOW as SAMPLE_NOW
        for (left,right),frames in ((pair,frames) for pair in ((0,73),(73,0),(0,0),(None,0),(73,73)) for frames in (4,8)):
            with self.subTest(left=left,right=right,frames=frames), patch('time.time',return_value=SAMPLE_NOW):
                image,payload=render_arcade(versus_sample(left,right),animated=True,anim_frames=frames)
                spec=board_anim.decode(payload)
                background=list(struct.unpack('<76800H',rgb565_frame(image)[8:]))
                # Exercise the other resident scenery for every KO and recovery state.
                with patch.object(self,'spec',spec):
                    clean=self.payload(True)
                capture=150
                cycle=math.lcm(*(len(s['script'])*s['step_ms'] for s in spec['sprites']))
                steps=cycle//capture
                out=self.run_engine(clean,capture*steps,image=image,capture_ms=capture)
                for step in range(steps):
                    elapsed=((step+1)*capture-1)//40*40
                    self.assertEqual((out/f'screen_{step}.bin').read_bytes(),
                                     struct.pack('<76800H',*self.expected(step,background,spec,elapsed_ms=elapsed)),
                                     f'KO state {left}/{right}, {frames} frames, step {step}')

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
        # Includes the previous-frame restoration box, tail and head. The
        # path crosses open sky between the portraits and session meters.
        corridor = {y*320+x for y in range(38,100) for x in range(105,214)}
        protected = {y*320+x for y in range(0,36) for x in range(320)}
        protected.update(y*320+x for y in range(36,70) for x in range(4,112))
        protected.update(y*320+x for y in range(36,80) for x in range(194,316))
        moving=[]
        for step in range(180):
            got=struct.unpack('<76800H',(out/f'screen_{step}.bin').read_bytes())
            expected=self.expected(step, elapsed_ms=((step+1)*250-1)//20*20)
            changes={i for i,(a,b) in enumerate(zip(got,expected)) if a!=b}-stars
            self.assertFalse(changes-corridor, f'Outside sky at frame {step}')
            self.assertFalse(changes & protected, f'Meteor crossed quota/reserves at {step}')
            moving.append(bool(changes))
        starts=[i for i,active in enumerate(moving) if active and (i==0 or not moving[i-1])]
        self.assertGreaterEqual(len(starts),2)
        self.assertLessEqual(len(starts),5)
        self.assertTrue(all(b-a>=40 for a,b in zip(starts,starts[1:])))
        self.assertLess(sum(moving),30)  # Most of the time the meteor is absent.
        self.assertFalse(moving[-1])   # Restored sky, no permanent trail.

    def test_driving_scene_repeats_cleanly_and_preserves_every_instrument_pixel_on_firmware_fourteen(self):
        for data in (snapshot(), {'accounts': {}}):
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                image, payload = render_dials(data, animated=True)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = spec['sprites'][0]['step_ms']
                cycle_ms = math.lcm(*(len(s['script']) * s['step_ms'] for s in spec['sprites']))
                steps = cycle_ms // capture * 2  # two joint cycles, including independently timed palms
                out = self.run_engine(payload, capture * steps, image=image, capture_ms=capture)
                for step in range(steps):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    self.assertEqual(list(got), self.expected(step, background, spec, elapsed_ms=step*capture), f'road step {step}')

    def test_the_city_animation_repeats_cleanly_with_four_and_eight_frame_cars(self):
        for data, frame_limit in ((snapshot(), 4), ({'accounts': {}}, 4), (snapshot(), 8), ({'accounts': {}}, 8)):
            with self.subTest(known=bool(data['accounts']), frame_limit=frame_limit), patch('time.time', return_value=NOW):
                image, payload = render_countdown(data, animated=True, anim_frames=frame_limit)
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
        # Four sprites on two clocks: the surfer and the lip move every beat (150 ms), the current of the face and of the crest every
        # second beat. Two full loops (64 beats) of the real engine, pixel by pixel, in the eight-picture and the four-picture version.
        for data, frames in ((snapshot(), 8), ({'accounts': {}}, 8), (snapshot(), 4)):
            with self.subTest(known=bool(data['accounts']), frames=frames), patch('time.time', return_value=NOW):
                image, payload = render_surf(data, animated=True, anim_frames=frames)
                spec = board_anim.decode(payload)
                background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                capture = 150
                out = self.run_engine(payload, capture * 64, image=image, capture_ms=capture)
                for step in range(64):
                    got = struct.unpack('<76800H', (out / f'screen_{step}.bin').read_bytes())
                    elapsed = ((step + 1) * capture - 1) // 40 * 40
                    self.assertEqual(struct.pack('<76800H', *got),
                                     struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed)),
                                     f'surf step {step}')
                for step in range(32):                                   # the loop closes: nothing jumps at the wrap
                    self.assertEqual((out / f'screen_{step}.bin').read_bytes(), (out / f'screen_{step + 32}.bin').read_bytes(),
                                     f'surf: the loop closes at beat {step}')

    def test_surf_gulls_fly_two_loops_without_trails_or_erasing_the_wave(self):
        with patch('time.time', return_value=NOW):
            image, payload = render_surf(snapshot(), animated=True, extended_anim=True)
        spec = board_anim.decode(payload)
        self.assertEqual(len(spec['sprites']), 6)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        capture = 300
        out = self.run_engine(payload, capture * 128, image=image, capture_ms=capture)
        for step in range(128):
            elapsed = ((step + 1) * capture - 1) // 40 * 40
            expected = struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed))
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(), expected, f'surf gull step {step}')
        for step in range(64):
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                             (out / f'screen_{step + 64}.bin').read_bytes(), f'surf gull loop {step}')

    def test_quest_sprites_leave_no_trails_or_damage_to_the_hud_over_two_loops(self):
        from token_tv.board_zelda import render_quest
        poses = tuple(Image.new('RGBA', (24,26), (50 + i * 20, 180, 70, 255)) for i in range(8))
        for limit in (4,8):
            with self.subTest(frame_limit=limit), patch('time.time', return_value=NOW), \
                    patch('token_tv.board_zelda._walk', return_value=poses):
                image, payload = render_quest(snapshot(), animated=True, anim_frames=limit)
            spec = board_anim.decode(payload)
            background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
            capture = 200
            out = self.run_engine(payload, capture * 64, image=image, capture_ms=capture)
            for step in range(64):
                elapsed = ((step + 1) * capture - 1) // 40 * 40
                expected = struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed))
                self.assertEqual((out / f'screen_{step}.bin').read_bytes(), expected, f'quest step {step}')
            for step in range(32):
                self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                                 (out / f'screen_{step + 32}.bin').read_bytes(), f'quest loop {step}')


    def test_quest_action_restores_the_background_across_two_loops(self):
        from token_tv.board_zelda import render_quest
        with patch('time.time', return_value=NOW), \
                patch('token_tv.board_zelda.ART', Path('/nonexistent/quest-art.png')), \
                patch('token_tv.board_zelda._local_art', return_value=None):
            image, payload = render_quest(snapshot(), animated=True)
        spec = board_anim.decode(payload)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        capture = 200
        out = self.run_engine(payload, capture * 64, image=image, capture_ms=capture)
        for step in range(64):
            elapsed = ((step + 1) * capture - 1) // 40 * 40
            expected = struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed))
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(), expected, f'quest step {step}')
        for step in range(32):
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                             (out / f'screen_{step + 32}.bin').read_bytes(), f'quest loop {step}')

    def test_custom_quest_scene_restores_each_sprite_across_two_loops(self):
        from token_tv.board_zelda import render_quest
        action = tuple(Image.new('RGBA', (29, 30), (50 + i * 20, 180, 70, 255)) for i in range(8))
        guard = tuple(Image.new('RGBA', (24, 24), (70, 50 + i * 20, 180, 255)) for i in range(8))
        local = (Image.new('RGB', (320, 240), '#517b51'), action, guard)
        with patch('time.time', return_value=NOW), patch('token_tv.board_zelda._local_art', return_value=local):
            image, payload = render_quest(snapshot(), animated=True)
        spec = board_anim.decode(payload)
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        capture = 80
        out = self.run_engine(payload, capture * 64, image=image, capture_ms=capture)
        for step in range(64):
            elapsed = ((step + 1) * capture - 1) // 40 * 40
            expected = struct.pack('<76800H', *self.expected(step, background, spec, elapsed_ms=elapsed))
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(), expected, f'custom quest step {step}')
        for step in range(32):
            self.assertEqual((out / f'screen_{step}.bin').read_bytes(),
                             (out / f'screen_{step + 32}.bin').read_bytes(), f'custom quest loop {step}')


if __name__ == '__main__':
    unittest.main()
