"""Weekly health, actual knockouts and native-pixel fighting-stage animation."""
import struct
import unittest
from copy import deepcopy
from unittest.mock import patch
from PIL import Image, ImageColor

from token_tv import board_anim, board_arcade_fighters as fighters, board_arcade_stage as stage
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_arcade import (render_arcade, meter_left, METER_WIDTH, HEALTH_RED, HEALTH_AMBER, HEALTH_GREEN,
                                   STEP_MS)
from token_tv.board_pages import rgb565_frame
from test_board_forge import sample, NOW, compose


def versus_sample(codex=73, claude=73):
    data = sample()
    for provider, value in (('codex',codex),('claude',claude)):
        if value is None:
            del data['accounts'][provider]
        else:
            data['accounts'][provider]['windows'][0]['used_percent'] = 100-value
    return data


def rendered_knockouts(data):
    with patch('token_tv.board_arcade.stage.draw_fighters', wraps=stage.draw_fighters) as draw:
        image, payload = render_arcade(data, animated=True)
    return image, payload, draw.call_args.args[1:3]


def picture(sprite, frame):
    """{(x, y): word} of the opaque pixels of one frame of a decoded sprite, in sprite pixels."""
    return {(i % sprite['w'], i // sprite['w']): word for i, word in enumerate(sprite['frames'][frame])
            if word != board_anim.KEY}


def duel(codex=73, claude=73, frames=8):
    with patch('time.time', return_value=NOW):
        image, payload = render_arcade(versus_sample(codex, claude), animated=True, anim_frames=frames)
    return image, payload, board_anim.decode(payload)


def box_of(sprite):
    """The screen box a sprite can ever touch, offsets included: the engine restores all of it on every beat."""
    dx = [d for _, d, _ in sprite['script']]
    dy = [d for _, _, d in sprite['script']]
    return (sprite['x'] + min(dx), sprite['y'] + min(dy),
            sprite['x'] + 2 * sprite['w'] + max(dx), sprite['y'] + 2 * sprite['h'] + max(dy))


def feature(sprite, step, colours, rows):
    """Top-left of the pixels of `colours` in the given rows of the picture shown at `step`, in logical pixels."""
    frame, dx, _ = sprite['script'][step]
    points = [xy for xy, word in picture(sprite, frame).items() if word in colours and rows[0] <= xy[1] < rows[1]]
    return (min(x for x, _ in points) + dx / 2, min(y for _, y in points)) if points else None


class VersusTests(unittest.TestCase):
    def setUp(self):
        local = patch('token_tv.board_arcade.local_stage.load', return_value=None)
        local.start()
        self.addCleanup(local.stop)

    def test_claude_left_arm_is_behind_and_right_arm_in_front_in_every_pose(self):
        # Place distinct markers where each arm would cross the body. The body
        # must cover the left marker, while the right one must remain visible.
        for name, pose in fighters.CLAUDE_POSES.items():
            with self.subTest(pose=name):
                cx = fighters.CLAUDE_BOX[0] + 1 + 23 + pose.get('lean', 0)
                cy = fighters.CLAUDE_BOX[1] + 17 + pose.get('rise', 0)
                left, right = (cx - 4, cy + 3), (cx + 9, cy + 3)
                left_marker, right_marker = (1, 2, 3), (4, 5, 6)
                def mark_arm(grid, pts, r0, r1, **kwargs):
                    if (r0, r1) == (3.4, 1.5):
                        grid.put(*left, left_marker)
                    elif (r0, r1) == (3.0, 1.4):
                        grid.put(*right, right_marker)
                def mark_whip(grid, root, tip_x, **kwargs):
                    grid.put(*left, left_marker)
                grid = fighters.Grid(fighters.LW, fighters.LH)
                with patch.object(fighters, '_tentacle', side_effect=mark_arm), \
                     patch.object(fighters, '_whip', side_effect=mark_whip):
                    fighters._claude(grid, *fighters.CLAUDE_BOX[:2], **pose)
                self.assertNotEqual(grid.get(*left), left_marker)
                self.assertEqual(grid.get(*right), right_marker)

    @patch('time.time', return_value=NOW)
    def test_fighter_names_are_centered_over_their_reset_bars(self, _):
        from token_tv.board_art import CODEX, CLAUDE
        image = render_arcade(versus_sample())
        for name, colour, left, right in (('Codex', CODEX, 42, 105),
                                          ('Claude', CLAUDE, 214, 274)):
            text_colour = ImageColor.getrgb(colour)
            letters = [x for y in range(38, 51) for x in range(left, right)
                       if image.getpixel((x, y)) == text_colour]
            borders = [x for x in range(left, right)
                       if image.getpixel((x, 54)) == ImageColor.getrgb('#6a5a8a')]
            self.assertTrue(letters, name)
            self.assertTrue(borders, name)
            self.assertLessEqual(abs((min(letters) + max(letters)) / 2 -
                                     (min(borders) + max(borders)) / 2), 2, name)

    @patch('time.time', return_value=NOW)
    def test_private_scenery_remains_visible_behind_the_scoreboard(self, _):
        from token_tv.board_arcade_local import EFFECTS
        background = Image.new('RGB', (320, 240), '#527eaa')
        effects = [[Image.new('RGBA', (w, h), (0, 0, 0, 0)) for _ in range(4)]
                   for _, _, w, h in EFFECTS]
        with patch('token_tv.board_arcade.local_stage.load', return_value=(background, effects)):
            image = render_arcade(versus_sample())
        self.assertEqual(image.getpixel((150, 65)), background.getpixel((150, 65)))

    @patch('time.time', return_value=NOW)
    def test_four_pose_boards_keep_the_first_pose_and_get_a_breathing_loop(self, _):
        from token_tv.board_pages import render_board_pages
        data = versus_sample()
        old = render_board_pages(data, anim=True, anim_frames=4)[5]
        new = render_board_pages(data, anim=True, anim_frames=8)[5]
        offset = 153608
        self.assertEqual(old[:offset], new[:offset])           # the same stored page, so the same first pose
        self.assertEqual(new[offset:offset+4], b'ANIM')
        self.assertLessEqual(len(old) - offset - 8, 40000)     # what a board without eight frames can hold
        self.assertLessEqual(len(new) - offset - 8, board_anim.MAX_PAYLOAD)
        old_spec = board_anim.decode(old[offset+8:])
        spec = board_anim.decode(new[offset+8:])
        self.assertEqual([len(s['frames']) for s in old_spec['sprites'][:2]], [2, 2])
        self.assertTrue(all(len(s['frames']) <= 4 for s in old_spec['sprites']))
        self.assertEqual([len(s['frames']) for s in spec['sprites'][:3]], [6, 7, 8])
        for previous, current in zip(old_spec['sprites'][:2], spec['sprites'][:2]):
            self.assertEqual(previous['frames'][0], current['frames'][0])      # the same picture at the start
            self.assertEqual((previous['x'], previous['y']), (current['x'], current['y']))
            self.assertEqual(previous['script'][0], current['script'][0])
            self.assertEqual(len(previous['script']), 8)
        self.assertEqual(old_spec['sprites'][2]['w'], 5)       # a four-pose board still moves the lantern
        # Whatever the board can hold, the animated first pose is exactly what a board without ANIM shows.
        stored = Image.frombytes('RGB', (320, 240), new[8:offset], 'raw', 'BGR;16')
        for frames_spec in (old_spec, spec):
            self.assertEqual(struct.pack('<76800H', *compose(stored, frames_spec, 0)),
                             rgb565_frame(render_arcade(data))[8:])
        self.assertLessEqual(len(new), MAX_PAGE_BYTES)
        # A confirmed zero remains an unmoving KO even on the newer board.
        fallen = render_board_pages(versus_sample(0,73), anim=True, anim_frames=8)[5]
        self.assertEqual(len(board_anim.decode(fallen[offset+8:])['sprites'][0]['frames']), 1)

    @patch('time.time', return_value=NOW)
    def test_session_meter_distinguishes_quota_time_and_unknown(self, _):
        full=versus_sample()
        session=next(w for w in full['accounts']['claude']['windows'] if w['label']=='5H')
        session['used_percent']=0
        session['resets_at']=NOW+4*3600
        spent=deepcopy(full)
        next(w for w in spent['accounts']['claude']['windows'] if w['label']=='5H')['used_percent']=100
        later=deepcopy(full)
        next(w for w in later['accounts']['claude']['windows'] if w['label']=='5H')['resets_at']=NOW+15*60
        missing=deepcopy(full)
        missing['accounts']['claude']['windows']=[w for w in missing['accounts']['claude']['windows']
                                                  if w['label']!='5H']
        a,b,c,d=(render_arcade(data) for data in (full,spent,later,missing))
        left = meter_left('73%')                                        # two thin rows in the dark strip beside Claude's percentage
        quota=(left,4,left+METER_WIDTH,7)
        time=(left,8,left+METER_WIDTH,11)
        self.assertNotEqual(a.crop(quota).tobytes(),b.crop(quota).tobytes())
        self.assertEqual(a.crop(time).tobytes(),b.crop(time).tobytes())
        self.assertEqual(a.crop(quota).tobytes(),c.crop(quota).tobytes())
        self.assertNotEqual(a.crop(time).tobytes(),c.crop(time).tobytes())
        self.assertNotEqual(a.crop(quota).tobytes(),d.crop(quota).tobytes())
        self.assertNotEqual(a.crop(time).tobytes(),d.crop(time).tobytes())

    @patch('time.time', return_value=NOW)
    def test_session_meter_stays_clear_of_the_week_label_the_percentage_and_the_name(self, _):
        # Tony, 2026-11-03: the two rows collided with the word CLAUDE. They now live in the dark score strip, 8 px before
        # Claude's percentage (whatever its width: '100%' is the widest) and clear of WEEK, the name and every other reading.
        from token_tv.themes import face
        week_right = 160 + 16 + 1                                       # WEEK is centred on 160 and 32 px wide, plus its edge
        for claude, text in ((.5, '<1%'), (7, '7%'), (73, '73%'), (100, '100%')):
            data = versus_sample(claude=claude)
            left = meter_left(text)
            percentage_left = 293 - round(face('press-start-2p.ttf', 15).getlength(text))
            self.assertEqual(percentage_left - 8, left + METER_WIDTH, text)
            self.assertGreaterEqual(left - week_right, 8, text)
            plain = render_arcade(data)
            lit = [(x, y) for y in range(0, 16) for x in range(left, left + METER_WIDTH)
                   if plain.getpixel((x, y)) in (ImageColor.getrgb('#cfc6b4'), ImageColor.getrgb('#4a3a70'))]
            self.assertTrue(lit, text)
            self.assertTrue(all(4 <= y <= 10 for _, y in lit), text)
            # nothing else is drawn in the meter's strip: removing the session leaves only the dark strip behind
            data['accounts']['claude']['windows'] = [w for w in data['accounts']['claude']['windows'] if w['label'] != '5H']
            without = render_arcade(data)
            changed = {(x, y) for y in range(240) for x in range(320) if plain.getpixel((x, y)) != without.getpixel((x, y))}
            self.assertTrue(changed and all(left <= x < left + METER_WIDTH and 4 <= y <= 10 for x, y in changed), text)

    @patch('time.time', return_value=NOW)
    def test_names_keep_a_dark_halo_so_they_read_over_any_scenery_without_a_panel(self, _):
        from token_tv.board_art import CODEX, CLAUDE
        from token_tv.board_arcade_local import EFFECTS
        halo = ImageColor.getrgb('#1a1538')
        for backdrop in ('#ffffff', '#c8d8f0', '#7a5a2a', '#101010'):
            background = Image.new('RGB', (320, 240), backdrop)
            effects = [[Image.new('RGBA', (w, h), (0, 0, 0, 0)) for _ in range(4)] for _, _, w, h in EFFECTS]
            with patch('token_tv.board_arcade.local_stage.load', return_value=(background, effects)):
                image = render_arcade(versus_sample())
            for name, colour, left, right in (('Codex', CODEX, 42, 105), ('Claude', CLAUDE, 214, 274)):
                letter = ImageColor.getrgb(colour)
                letters = {(x, y) for y in range(36, 52) for x in range(left, right) if image.getpixel((x, y)) == letter}
                self.assertGreater(len(letters), 40, name)
                for x, y in letters:
                    for dx in (-2, -1, 0, 1, 2):
                        for dy in (-2, -1, 0, 1, 2):
                            if dx * dx + dy * dy <= 5 and (x + dx, y + dy) not in letters:
                                self.assertEqual(image.getpixel((x + dx, y + dy)), halo, (name, backdrop, x + dx, y + dy))

    @patch('time.time', return_value=NOW)
    def test_health_colors_at_exact_boundaries_for_both_providers(self, _):
        for value, bands in ((.1,HEALTH_RED),(20,HEALTH_RED),(20.1,HEALTH_AMBER),
                             (50,HEALTH_AMBER),(50.1,HEALTH_GREEN),(100,HEALTH_GREEN)):
            image = render_arcade(versus_sample(value,value))
            for xy in ((142,24),(176,24)):
                self.assertEqual(image.getpixel(xy),ImageColor.getrgb(bands['mid']),value)

    @patch('time.time', return_value=NOW)
    def test_health_bars_remain_anchored_to_the_centre_as_quota_drains(self, _):
        image = render_arcade(versus_sample(25,25))
        amber, empty = ImageColor.getrgb(HEALTH_AMBER['mid']), ImageColor.getrgb('#4d2034')
        self.assertEqual(image.getpixel((142,24)), amber)
        self.assertEqual(image.getpixel((176,24)), amber)
        self.assertEqual(image.getpixel((20,24)), empty)
        self.assertEqual(image.getpixel((300,24)), empty)

    @patch('time.time', return_value=NOW)
    def test_only_confirmed_zero_falls_and_recovery_restores_fighters(self, _):
        for left,right in ((0,73),(73,0),(0,0),(None,0),(0,None),(None,None),(.1,.1)):
            with self.subTest(left=left, right=right):
                bg,payload,down = rendered_knockouts(versus_sample(left,right))
                self.assertEqual(down,(left == 0,right == 0))
                spec = board_anim.decode(payload)
                for index, value in enumerate((left,right)):
                    visible = [word for frame in spec['sprites'][index]['frames'] for word in frame
                               if word != board_anim.KEY]
                    self.assertEqual(bool(visible), value != 0)
                    if value == 0:
                        self.assertEqual((spec['sprites'][index]['w'],spec['sprites'][index]['h']),(1,1))
                self.assertLessEqual(len(rgb565_frame(bg,anim=payload)),MAX_PAGE_BYTES)
                self.assertEqual(struct.pack('<76800H',*compose(bg,spec,0)),
                                 rgb565_frame(render_arcade(versus_sample(left,right)))[8:])
        _,_,down = rendered_knockouts(versus_sample(73,73))
        self.assertEqual(down,(False,False))

    @patch('time.time', return_value=NOW)
    def test_old_zero_and_missing_week_never_knock_out(self, _):
        old = versus_sample(0,0)
        for row in old['accounts'].values(): row['status'] = 'error'
        missing_week = versus_sample(0,0)
        for row in missing_week['accounts'].values():
            row['windows'] = [w for w in row['windows'] if w['label'] != 'WEEK']
        for data in (old,missing_week):
            _,_,down = rendered_knockouts(data)
            self.assertEqual(down,(False,False))

    @patch('time.time', return_value=NOW)
    def test_duel_sprites_never_overlap_each_other_the_scoreboard_or_the_meteor(self, _):
        bg, payload, spec = duel()
        self.assertEqual(len(spec['sprites']), 4)
        self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
        self.assertEqual(spec['meteor']['period_ms'], 14000)
        self.assertGreaterEqual(len(spec['stars']), 10)
        self.assertTrue(all(y < 106 for x, y, *_ in spec['stars']))
        boxes = [box_of(s) for s in spec['sprites']]
        for i, a in enumerate(boxes):
            # below the scoreboard and the shooting star's corridor (x 105-214, y 38-99), above the footer
            self.assertTrue(0 <= a[0] < a[2] <= 320 and 108 <= a[1] < a[3] <= 205, a)
            for b in boxes[i+1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], (a, b))
        # the three actors share one beat, so an exchange stays in step; the cloud keeps its own, slower one
        self.assertEqual({s['step_ms'] for s in spec['sprites'][:3]}, {STEP_MS})
        self.assertEqual({len(s['script']) for s in spec['sprites'][:3]}, {32})
        self.assertEqual(spec['sprites'][3]['step_ms'], 2 * STEP_MS)
        frames = [compose(bg, spec, k) for k in range(32)]
        self.assertGreaterEqual(len({tuple(f) for f in frames}), 10)
        # Motion is decoration: nothing above the fighters or below the arena ever changes (no life-bar flicker).
        for first, second in zip(frames, frames[1:] + frames[:1]):
            self.assertTrue(all(a == b for i, (a, b) in enumerate(zip(first, second)) if i // 320 < 108 or i // 320 >= 206))
        # At no point may twinkling stars overwrite a sprite box.
        self.assertTrue(all(not any(a[0] <= x < a[2] and a[1] <= y < a[3] for a in boxes) for x, y, *_ in spec['stars']))
        with patch('time.time', return_value=NOW + 1):
            self.assertEqual(render_arcade(versus_sample(), animated=True, anim_frames=8)[1], payload)

    def test_both_fighters_and_knockouts_land_in_the_middle_of_the_wooden_deck(self):
        # The wood runs from y=176 to y=205. Check the soles and the shadows of every picture, not just the tops of
        # the sprites: moving them down is a visible layout change.
        programs, _, _ = fighters._programs()
        for provider, box in (('codex', fighters.CODEX_BOX), ('claude', fighters.CLAUDE_BOX)):
            with self.subTest(provider=provider):
                for frame in programs[provider][0]:
                    self.assertTrue(196 <= box[1] * 2 + frame.getbbox()[3] * 2 - 1 <= 205)
                lying = fighters.fallen(provider)
                self.assertTrue(196 <= box[3] * 2 - (lying.height - lying.getbbox()[3]) * 2 - 1 <= 205)

    @patch('time.time', return_value=NOW)
    def test_fighters_breathe_with_their_own_rhythm_and_stay_planted(self, _):
        bg, payload, spec = duel()
        codex, claude = spec['sprites'][:2]
        rhythms = [[s['script'][i][0] for i in range(8)] for s in (codex, claude)]       # the opening breaths
        self.assertNotEqual(*rhythms)
        for sprite, rhythm in zip((codex, claude), rhythms):
            first, second = (picture(sprite, k) for k in sorted(set(rhythm))[:2])
            self.assertNotEqual(first, second)
            # soles and shadow do not move when the body breathes: the last four rows agree
            feet = lambda p: {xy: c for xy, c in p.items() if xy[1] >= sprite['h'] - 4}
            self.assertEqual(feet(first), feet(second))

    @patch('time.time', return_value=NOW)
    def test_hands_and_burst_appear_in_the_middle_only_during_a_short_exchange(self, _):
        bg, payload, spec = duel()
        middle = spec['sprites'][2]
        shown = [bool(picture(middle, k)) for k, _, _ in middle['script']]
        self.assertFalse(any(shown[:8]) or any(shown[20:]))      # breathing before and after
        self.assertTrue(8 <= sum(shown) <= 12)                   # occasional: well under half of the 3.8 s loop
        for step in (i for i, (_, _, burst, _) in enumerate(fighters._duel()) if burst == 1):
            white = [xy for xy, word in picture(middle, middle['script'][step][0]).items() if word == 0xFFFF]
            self.assertGreaterEqual(len(white), 6)               # the generic burst has a white core
            self.assertTrue(all(8 <= x <= 22 and 5 <= y <= 17 for x, y in white))   # in the heart of the box

    @patch('time.time', return_value=NOW)
    def test_contact_holds_both_bodies_for_two_beats_while_the_burst_grows(self, _):
        bg, payload, spec = duel()
        codex, claude, middle = spec['sprites'][:3]
        steps = fighters._duel()
        for flash in (i for i, step in enumerate(steps) if step[2] == 0):
            self.assertEqual(steps[flash + 1][2], 1)
            for body in (codex, claude):
                self.assertEqual(body['script'][flash], body['script'][flash + 1])      # hit-stop: nobody moves
            small, big = (picture(middle, middle['script'][flash + k][0]) for k in (0, 1))
            self.assertGreater(len(big), len(small))

    def test_every_pose_stays_inside_its_own_sprite_box(self):
        boxes = (fighters.CODEX_BOX, fighters.CLAUDE_BOX, fighters.MIDDLE_BOX)
        for step, (codex, claude, burst, _) in enumerate(fighters._duel()):
            scene = fighters._scene(codex, claude, burst)
            stray = [(x, y) for y in range(scene.h) for x in range(scene.w) if scene.p[y][x] is not None
                     and not any(b[0] <= x < b[2] and b[1] <= y < b[3] for b in boxes)]
            self.assertEqual(stray, [], (step, codex, claude, burst))
            if burst is None and codex in ('C0', 'C1') and claude in ('K0', 'K2'):
                self.assertIsNone(scene.image(fighters.MIDDLE_BOX).getbbox(), step)      # breathing leaves the middle empty

    @patch('time.time', return_value=NOW)
    def test_codex_face_and_lightning_stay_intact_in_every_pose(self, _):
        # The prompt and the bolt are drawn once per pose at sprite resolution: no pose may lose, clip or distort them.
        bg, payload, spec = duel()
        codex = spec['sprites'][0]
        prompt, bolt = board_anim.rgb565(fighters.PROMPT), {board_anim.rgb565(c) for c in fighters.BOLT[2:]}
        shapes = []
        for k in range(len(codex['frames'])):
            pixels = picture(codex, k)
            self.assertGreaterEqual(sum(word == prompt for word in pixels.values()), 8, k)
            points = {xy for xy, word in pixels.items() if word in bolt and xy[1] < 14}      # not the belt's buckle
            left, top = min(x for x, _ in points), min(y for _, y in points)
            self.assertTrue(0 < left and 0 <= top and max(x for x, _ in points) < codex['w'] - 1, k)
            shapes.append({(x - left, y - top) for x, y in points})
        self.assertTrue(all(shape == shapes[0] for shape in shapes))

    @patch('time.time', return_value=NOW)
    def test_breathing_flexes_vertically_and_the_loop_never_jumps(self, _):
        # Track features fixed to each head: Codex's bolt and Claude's starburst. While the fighters breathe they rise and
        # settle without drifting sideways; during the exchange they never move farther than a lunge; the wrap is a
        # breath like any other.
        bg, payload, spec = duel()
        codex, claude = spec['sprites'][:2]
        steps = fighters._duel()
        tracks = {
            'codex': [feature(codex, k, {board_anim.rgb565(c) for c in fighters.BOLT[2:]}, (0, 14)) for k in range(32)],
            'claude': [feature(claude, k, {board_anim.rgb565(fighters.CREAM)}, (0, 18)) for k in range(32)]}
        breathing = [k for k in range(32) if not (8 <= k < 8 + len(fighters.EXCHANGE))]
        for name, track in tracks.items():
            self.assertEqual(len({track[k][0] for k in breathing}), 1, name)         # no sideways drift
            self.assertGreaterEqual(len({track[k][1] for k in breathing}), 2, name)  # but it does breathe
            for k in range(32):
                (x0, y0), (x1, y1) = track[k], track[(k + 1) % 32]
                self.assertLessEqual(abs(x1 - x0), 7, (name, k))
                self.assertLessEqual(abs(y1 - y0), 3, (name, k))
                if k in breathing and (k + 1) % 32 in breathing:
                    self.assertLessEqual(abs(y1 - y0) + abs(x1 - x0), 2, (name, k))    # every breath is a small move
        for step in (steps[0], steps[-1]):                                                # it ends where it begins
            self.assertTrue(step[0] in ('C0', 'C1') and step[1] in ('K0', 'K2'))

    @patch('time.time', return_value=NOW)
    def test_clouds_keep_drifting_in_one_direction_across_the_loop(self, _):
        _, payload = render_arcade(versus_sample(),animated=True,anim_frames=8)
        cloud=board_anim.decode(payload)['sprites'][3]
        self.assertEqual((cloud['x'],cloud['y']),(128,112))
        self.assertEqual(len(cloud['frames']),4)
        width,height=cloud['w'],cloud['h']
        for a,b in zip(cloud['frames'],cloud['frames'][1:]+cloud['frames'][:1]):
            self.assertEqual([a[y*width+x+4] for y in range(height) for x in range(9,width-13)],
                             [b[y*width+x] for y in range(height) for x in range(9,width-13)])
        self.assertGreater(sum(word != board_anim.KEY for word in cloud['frames'][0]),20)
        self.assertTrue(all(frame[y*width] == frame[y*width+width-1] == board_anim.KEY
                            for frame in cloud['frames'] for y in range(height)))

    @patch('time.time', return_value=NOW)
    def test_stage_has_real_one_pixel_detail(self, _):
        image=render_arcade(versus_sample())
        # The scenery keeps native detail while the complete fighters animate
        # at the board's two-pixel sprite resolution.
        for left,top,right,bottom in ((2,112,60,162),(260,112,318,162)):
            fine=sum(image.getpixel((x,y)) != image.getpixel((x+1,y)) or
                     image.getpixel((x,y)) != image.getpixel((x,y+1))
                     for y in range(top,bottom,2) for x in range(left,right,2))
            self.assertGreater(fine,100,(left,top,fine))

    def test_mascots_keep_distinct_nonhuman_silhouettes_including_ko(self):
        programs, _, _ = fighters._programs()
        codex, claude = (programs[name][0][0].getchannel('A') for name in ('codex', 'claude'))

        def sections(alpha, y):
            row = [alpha.getpixel((x, y)) > 0 for x in range(alpha.width)]
            return sum(v and (x == 0 or not row[x-1]) for x, v in enumerate(row))

        # Above the shadows Codex stands on two sturdy legs, while Claude has several separated tentacles, not
        # another mirrored human fighter.
        self.assertTrue(all(sections(codex, y) <= 2 for y in range(35, 43)))
        self.assertTrue(all(sections(claude, y) >= 3 for y in range(35, 41)))
        self.assertNotEqual(codex.tobytes(), claude.tobytes())
        codex_ko = fighters.fallen('codex')
        claude_ko = fighters.fallen('claude')
        self.assertEqual(codex_ko.size, claude_ko.size)
        self.assertNotEqual(codex_ko.tobytes(), claude_ko.tobytes())

    @patch('time.time', return_value=NOW)
    def test_a_survivor_only_breathes_and_never_attacks_a_knockout(self, _):
        for left, right in ((0, 73), (73, 0)):
            with self.subTest(left=left, right=right):
                bg, payload, spec = duel(left, right)
                codex, claude, middle = spec['sprites'][:3]
                alive, down = (claude, codex) if left == 0 else (codex, claude)
                self.assertEqual((down['w'], down['h']), (1, 1))
                self.assertEqual((middle['w'], middle['h']), (1, 1))     # no hands, whip or burst without an opponent
                self.assertEqual(len(alive['frames']), 2)
                self.assertEqual(len(alive['script']), 8)
                self.assertTrue(all(dx == dy == 0 for _, dx, dy in alive['script']))

    @patch('time.time', return_value=NOW)
    def test_saved_reserves_do_not_derive_from_quota_or_cause_ko(self, _):
        full=versus_sample(73,73)
        empty=versus_sample(73,73)
        for row in empty['accounts'].values(): row['banked_resets']['available']=0
        a,pa=render_arcade(full,animated=True);b,pb=render_arcade(empty,animated=True)
        self.assertEqual(pa,pb)
        self.assertNotEqual(a.crop((48,52,104,64)).tobytes(),b.crop((48,52,104,64)).tobytes())
        unknown=versus_sample(73,73)
        for row in unknown['accounts'].values(): row['banked_resets']['available']=None
        self.assertNotEqual(render_arcade(unknown).tobytes(),render_arcade(empty).tobytes())

    @patch('time.time', return_value=NOW)
    def test_claude_unknown_and_old_dot_precedes_the_fixed_reserve_bars(self, _):
        for fresh, uncertain in (({'available': 0}, {'available': None}),
                                 ({'available': 2}, {'available': None, 'last_known': 2})):
            known, marked = versus_sample(), versus_sample()
            known['accounts']['claude']['banked_resets'] = fresh
            marked['accounts']['claude']['banked_resets'] = uncertain
            a, b = render_arcade(known), render_arcade(marked)
            changes = {(x, y) for y in range(240) for x in range(320)
                       if a.getpixel((x, y)) != b.getpixel((x, y))}
            # A single logical pixel sits to the left, and the reserve bars
            # themselves remain exactly where they were.
            self.assertEqual(changes, {(x, y) for x in (210, 211) for y in (58, 59)})

    @patch('time.time', return_value=NOW)
    def test_old_claude_extra_reserves_keep_both_plus_and_dot(self, _):
        sample = versus_sample()
        sample['accounts']['claude']['banked_resets'] = {'available': None, 'last_known': 4}
        image = render_arcade(sample)
        self.assertEqual(image.getpixel((210, 58)), ImageColor.getrgb('#6a5a8a'))
        # The '+' is left of the dot; it must not cover the indicator or bars.
        self.assertTrue(any(image.getpixel((x, y)) == ImageColor.getrgb('#b9a8e0')
                            for y in range(52, 65) for x in range(190, 208)))


class CodexFaceTests(unittest.TestCase):
    def test_nothing_ever_crosses_the_terminal_that_is_codexs_face(self):
        # Tony, 2026-11-03: "el de codex tiene el brazo derecho en medio de la cara".
        from token_tv import board_arcade_fighters as fighters
        ox, oy = fighters.CODEX_BOX[:2]
        for name, pose in fighters.CODEX_POSES.items():
            with self.subTest(pose=name):
                x = int(ox + 21.5 + pose.get('lean', 0) - 11.5 + pose.get('shear', 0.0) * 0.3)
                y = int(oy + 21.5 + pose.get('rise', 0) + pose.get('sag', 0) - 9)
                alone = fighters.Grid(fighters.LW, fighters.LH)
                fighters._screen(alone, x, y, pose.get('face', 'idle'))
                box = (x, y, x + fighters.SCREEN_W, y + fighters.SCREEN_H)
                drawn, screen = fighters._pose('codex', name).image(box).convert('RGBA'), alone.image(box).convert('RGBA')
                for py in range(3, screen.height):            # the lightning's foot rests on the top of the bezel, by design
                    for px in range(screen.width):
                        if screen.getpixel((px, py))[3]:      # its two cut corners show the shell, as they always did
                            self.assertEqual(drawn.getpixel((px, py)), screen.getpixel((px, py)), (px, py))


if __name__ == '__main__': unittest.main()
