"""Weekly health, actual knockouts and native-pixel fighting-stage animation."""
import struct
import unittest
from copy import deepcopy
from unittest.mock import patch
from PIL import Image, ImageColor

from token_tv import board_anim, board_arcade_stage as stage
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_arcade import render_arcade, HEALTH_RED, HEALTH_AMBER, HEALTH_GREEN, STEP_MS
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


class VersusTests(unittest.TestCase):
    def setUp(self):
        local = patch('token_tv.board_arcade.local_stage.load', return_value=None)
        local.start()
        self.addCleanup(local.stop)

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
    def test_eight_pose_guards_keep_older_boards_and_first_frame_compatible(self, _):
        from token_tv.board_pages import render_board_pages
        data = versus_sample()
        old = render_board_pages(data, anim=True, anim_frames=4)[5]
        new = render_board_pages(data, anim=True, anim_frames=8)[5]
        offset = 153608
        self.assertEqual(old[:offset], new[:offset])
        self.assertEqual(new[offset:offset+4], b'ANIM')
        old_spec = board_anim.decode(old[offset+8:])
        spec = board_anim.decode(new[offset+8:])
        for provider, previous, current in zip(('codex', 'claude'), old_spec['sprites'][:2], spec['sprites'][:2]):
            self.assertEqual(len(previous['frames']), 4)
            self.assertEqual(len(current['frames']), 8)
            self.assertEqual(previous['frames'][0], current['frames'][0])
            self.assertEqual(len({tuple(frame) for frame in current['frames']}), 8)
            self.assertTrue(100 <= current['step_ms'] <= 250)
            self.assertTrue(all(dx == dy == 0 for _,dx,dy in current['script']))
            self.assertEqual(current['script'][0][0], 0)
            self.assertTrue(all(186 <= current['y'] + 2 * frame.getbbox()[3] - 1 <= 195
                                for frame in stage._stance_sprite(provider, False, current['step_ms'], 8)['frames']))
            # Closing the cycle changes fewer pixels than the biggest normal
            # transition, so neither fighter snaps back to the opening pose.
            frames = current['frames']
            changes = [sum(a != b for a,b in zip(first, second))
                       for first,second in zip(frames, frames[1:] + frames[:1])]
            self.assertLessEqual(changes[-1], max(changes[:-1]))
        self.assertNotEqual(spec['sprites'][0]['step_ms'], spec['sprites'][1]['step_ms'])
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
        quota=(178,35,221,38)
        time=(178,39,221,42)
        self.assertNotEqual(a.crop(quota).tobytes(),b.crop(quota).tobytes())
        self.assertEqual(a.crop(time).tobytes(),b.crop(time).tobytes())
        self.assertEqual(a.crop(quota).tobytes(),c.crop(quota).tobytes())
        self.assertNotEqual(a.crop(time).tobytes(),c.crop(time).tobytes())
        self.assertNotEqual(a.crop(quota).tobytes(),d.crop(quota).tobytes())
        self.assertNotEqual(a.crop(time).tobytes(),d.crop(time).tobytes())

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
    def test_whole_body_stances_and_background_animate_without_overlap(self, _):
        bg,payload=render_arcade(versus_sample(),animated=True)
        spec=board_anim.decode(payload)
        self.assertEqual(len(spec['sprites']),4)
        self.assertLessEqual(len(payload),40000)
        self.assertEqual(spec['meteor']['period_ms'],14000)
        self.assertGreaterEqual(len(spec['stars']),10)
        self.assertTrue(all(y<110 for x,y,*_ in spec['stars']))
        boxes=[]
        self.assertEqual([s['step_ms'] for s in spec['sprites']], [300,400,STEP_MS,STEP_MS])
        for s in spec['sprites']:
            self.assertTrue(all(dx == dy == 0 for _,dx,dy in s['script']))
            self.assertGreaterEqual(len({tuple(frame) for frame in s['frames']}),3)
            boxes.append((s['x'],s['y'],s['x']+s['w']*2,s['y']+s['h']*2))
        for i,a in enumerate(boxes):
            self.assertTrue(0 <= a[0] < a[2] <= 320 and 80 <= a[1] < a[3] <= 196)
            for b in boxes[i+1:]:
                self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])
        frames=[compose(bg,spec,k) for k in range(8)]
        self.assertNotEqual(frames[0],frames[1])
        self.assertNotEqual(frames[0],frames[4])
        # Heads and bodies move together and the legs or tentacles flex too;
        # freezing the face was visibly separating it from the body.
        for left,right in ((26,108),(216,298)):
            changed=sum(frames[0][y*320+x] != frames[1][y*320+x]
                        for y in range(112,196) for x in range(left,right))
            self.assertGreater(changed,300,(left,changed))
        for left,top,right,bottom in ((46,136,86,166),(242,138,276,166)):
            changed=sum(frames[0][y*320+x] != frames[1][y*320+x]
                        for y in range(top,bottom) for x in range(left,right))
            self.assertGreater(changed,50,(left,changed))
        for left,right in ((26,108),(216,298)):
            changed=sum(frames[0][y*320+x] != frames[1][y*320+x]
                        for y in range(176,196) for x in range(left,right))
            self.assertGreater(changed,15,(left,changed))
        for first,second in zip(frames,frames[1:]+frames[:1]):
            self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(first,second)) if i//320>=196))
        # At no point may twinkling stars overwrite a fighter sprite box.
        self.assertTrue(all(not any(a[0] <= x < a[2] and a[1] <= y < a[3] for a in boxes[:2])
                            for x,y,*_ in spec['stars']))
        with patch('time.time',return_value=NOW+1):
            self.assertEqual(render_arcade(versus_sample(),animated=True)[1],payload)

    def test_both_fighters_and_knockouts_land_in_the_middle_of_the_wooden_deck(self):
        # The wood runs from y=176 to y=205. Check the soles/shadows, not just
        # the tops of the sprites: moving them down is a visible layout change.
        for provider in ('codex','claude'):
            with self.subTest(provider=provider):
                normal_bottom=stage.FIGHTER_Y + stage.fighter(provider).getbbox()[3]-1
                fallen_bottom=stage.FIGHTER_Y + 67 + stage.fallen(provider).getbbox()[3]-1
                self.assertTrue(186 <= normal_bottom <= 195)
                self.assertTrue(186 <= fallen_bottom <= 198)
                sprite=stage._stance_sprite(provider,False,STEP_MS)
                for frame in sprite['frames']:
                    bottom=sprite['y'] + frame.getbbox()[3]*2-1
                    self.assertTrue(186 <= bottom <= 195, (provider,bottom))

    @patch('time.time', return_value=NOW)
    def test_fighters_have_distinct_idle_poses_and_independently_moving_lead_hands(self, _):
        bg,payload=render_arcade(versus_sample(),animated=True)
        spec=board_anim.decode(payload)
        frames=[compose(bg,spec,k) for k in range(8)]
        for index,(left,right,hand_left,hand_right) in enumerate(((26,108,86,108),(216,298,216,240))):
            sprite=spec['sprites'][index]
            self.assertEqual(len({tuple(f) for f in sprite['frames']}),4)
            bodies=[tuple(frame[y*320+x] for y in range(112,180) for x in range(left,right)) for frame in frames]
            hands=[tuple(frame[y*320+x] for y in range(122,154) for x in range(hand_left,hand_right)) for frame in frames]
            self.assertEqual(len(set(bodies)),4)
            self.assertGreaterEqual(len(set(hands)),3)

    def test_each_hand_can_move_separately_from_the_face_and_feet(self):
        for provider,lead,rear,face in (
                ('codex',(55,15,90,51),(5,44,31,68),(30,41,56,59)),
                ('claude',(8,15,38,51),(70,40,94,65),(42,42,68,58))):
            with self.subTest(provider=provider):
                still=stage._guarded_fighter(provider)
                lead_moved=stage._guarded_fighter(provider,guard_dx=2,guard_dy=-4)
                rear_moved=stage._guarded_fighter(provider,rear_dx=-2,rear_dy=4)
                for box,moved in ((lead,lead_moved),(rear,rear_moved)):
                    before,after=still.crop(box).tobytes(),moved.crop(box).tobytes()
                    changed=sum(before[i:i+4] != after[i:i+4] for i in range(0,len(before),4))
                    self.assertGreater(changed,100,(provider,box,changed))
                for pose in (lead_moved,rear_moved):
                    self.assertEqual(still.crop(face).tobytes(),pose.crop(face).tobytes())
                    self.assertEqual(still.crop((0,75,95,94)).tobytes(),
                                     pose.crop((0,75,95,94)).tobytes())

    def test_codex_face_and_lightning_stay_intact_in_every_guard_pose(self):
        # Sprite scaling must not leave a fragment of the old bolt or prompt
        # behind, clip either detail, or let them drift apart from the head.
        sprite=stage._stance_sprite('codex',False,STEP_MS)
        colours=((211,255,255),(187,250,255),(247,190,79),(255,242,167))
        expected={}
        origins=[]
        for frame in sprite['frames']:
            pose_origins=[]
            for colour in colours:
                points={(x,y) for y in range(frame.height) for x in range(frame.width)
                        if frame.getpixel((x,y))[:3] == colour
                        and frame.getpixel((x,y))[3]}
                self.assertTrue(points,colour)
                left,top=min(x for x,_ in points),min(y for _,y in points)
                right,bottom=max(x for x,_ in points),max(y for _,y in points)
                self.assertTrue(0 < left <= right < frame.width-1)
                self.assertTrue(0 <= top <= bottom < frame.height-1)
                shape={(x-left,y-top) for x,y in points}
                if colour in expected:
                    self.assertEqual(shape,expected[colour],colour)
                else:
                    expected[colour]=shape
                pose_origins.append((left,top))
            origins.append(pose_origins)
        first=origins[0]
        for pose in origins[1:]:
            for index in range(1,len(colours)):
                self.assertEqual((pose[index][0]-pose[0][0],pose[index][1]-pose[0][1]),
                                 (first[index][0]-first[0][0],first[index][1]-first[0][1]))

    def test_fighting_guard_flexes_vertically_without_a_diagonal_slide(self):
        # Track features fixed to the heads through every complete sprite pose.
        # The planted fighters breathe at different heights, but do not drift
        # sideways as a rigid shape on each rise and fall.
        poses={}
        for provider,colour,y_limit in (
                ('codex',(211,255,255),30),('claude',(210,83,71),15)):
            sprite=stage._stance_sprite(provider,False,STEP_MS)
            positions=[]
            for frame in sprite['frames']:
                points=[(x,y) for y in range(y_limit) for x in range(frame.width)
                        if frame.getpixel((x,y))[:3] == colour and frame.getpixel((x,y))[3]]
                self.assertTrue(points,provider)
                positions.append((min(x for x,_ in points),min(y for _,y in points)))
            self.assertEqual(len({x for x,_ in positions}),1,provider)
            self.assertGreaterEqual(len({y for _,y in positions}),3,provider)
            poses[provider]=[y-positions[0][1] for _,y in positions]
        self.assertLess(min(poses['codex']),0)
        self.assertGreater(max(poses['claude']),0)

    @patch('time.time', return_value=NOW)
    def test_clouds_keep_drifting_in_one_direction_across_the_loop(self, _):
        _,payload=render_arcade(versus_sample(),animated=True)
        cloud=board_anim.decode(payload)['sprites'][3]
        self.assertEqual(cloud['x'],110)
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
        codex = stage.fighter('codex').getchannel('A')
        claude = stage.fighter('claude').getchannel('A')

        def sections(alpha, y):
            row = [alpha.getpixel((x, y)) > 0 for x in range(alpha.width)]
            return sum(v and (x == 0 or not row[x-1]) for x, v in enumerate(row))

        # Above the shadows Codex is compact, while Claude has several
        # separated tentacles, not another mirrored human fighter.
        self.assertLessEqual(sections(codex, 80), 2)
        self.assertGreaterEqual(sections(claude, 80), 4)
        self.assertNotEqual(codex.tobytes(), claude.tobytes())
        codex_ko = stage.fallen('codex')
        claude_ko = stage.fallen('claude')
        self.assertEqual(codex_ko.size, claude_ko.size)
        self.assertNotEqual(codex_ko.tobytes(), claude_ko.tobytes())

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


if __name__ == '__main__': unittest.main()
