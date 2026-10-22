"""Weekly health states, saved-reset reserves and genuine zero-only knockouts."""
import struct
import unittest
from unittest.mock import patch
from PIL import Image, ImageColor, ImageDraw

from token_tv import board_anim
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_arcade import render_arcade, HEALTH_RED, HEALTH_AMBER, HEALTH_GREEN, _fighter_specs, _scene, _city, _stage
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


def capture_fighters(data):
    captured = []
    def capture(left, right):
        fighters = _fighter_specs(left, right)
        captured.extend(fighters)
        return fighters
    with patch('token_tv.board_arcade._fighter_specs', side_effect=capture):
        image, payload = render_arcade(data, animated=True)
    return image, payload, captured


class VersusTests(unittest.TestCase):
    @patch('time.time', return_value=NOW)
    def test_health_colors_at_exact_boundaries_for_both_providers(self, _):
        for value, bands in ((.1,HEALTH_RED),(20,HEALTH_RED),(20.1,HEALTH_AMBER),
                             (50,HEALTH_AMBER),(50.1,HEALTH_GREEN),(100,HEALTH_GREEN)):
            image = render_arcade(versus_sample(value,value))
            for xy in ((112,18),(206,18)):
                self.assertEqual(image.getpixel(xy),ImageColor.getrgb(bands['mid']),value)

    @patch('time.time', return_value=NOW)
    def test_only_confirmed_zero_falls_and_recovery_restores_the_fighter(self, _):
        for left,right in ((0,73),(73,0),(0,0),(None,0),(0,None),(None,None),(.1,.1)):
            bg,payload,fighters = capture_fighters(versus_sample(left,right))
            spec = board_anim.decode(payload)
            for value,sprite in zip((left,right),fighters):
                if value == 0:
                    self.assertEqual(len(sprite['frames']),1)
                    self.assertEqual(set(sprite['script']),{(0,0,0)})
                else:
                    self.assertEqual(len(sprite['frames']),3)
            if (left == 0) != (right == 0):
                survivor = fighters[1 if left == 0 else 0]
                self.assertTrue(all(frame != 2 and dx == dy == 0 for frame,dx,dy in survivor['script']))
            self.assertLessEqual(len(rgb565_frame(bg,anim=payload)),MAX_PAGE_BYTES)
            self.assertEqual(struct.pack('<76800H',*compose(bg,spec,0)),
                             rgb565_frame(render_arcade(versus_sample(left,right)))[8:])
        _,_,restored = capture_fighters(versus_sample(73,73))
        self.assertTrue(all(any(frame == 2 for frame,_,_ in s['script']) for s in restored))

    @patch('time.time', return_value=NOW)
    def test_old_zero_and_missing_week_never_knock_out(self, _):
        old = versus_sample(0,0)
        for row in old['accounts'].values():
            row['status'] = 'error'
        missing_week = versus_sample(0,0)
        for row in missing_week['accounts'].values():
            row['windows'] = [w for w in row['windows'] if w['label'] != 'WEEK']
        for data in (old,missing_week):
            _,_,fighters = capture_fighters(data)
            self.assertTrue(all(len(s['frames']) == 3 for s in fighters))

    @patch('time.time', return_value=NOW)
    def test_train_moves_across_the_large_city_without_touching_readings(self, _):
        bg,payload=render_arcade(versus_sample(),animated=True)
        spec=board_anim.decode(payload)
        self.assertEqual(len(spec['sprites']),2)
        self.assertEqual(spec['meteor']['period_ms'],14000)
        self.assertGreaterEqual(len(spec['stars']),10)
        self.assertLessEqual(len(spec['stars']),18)
        self.assertTrue(all(y<118 for x,y,*_ in spec['stars']))
        self.assertEqual([sum(min(2,x*3//320)==zone for x,y,*_ in spec['stars']) for zone in range(3)],[6,6,6])
        self.assertLessEqual(len(payload),40000)
        boxes=[]
        for s in spec['sprites']:
            self.assertLessEqual(s['w'],96)
            self.assertLessEqual(s['h'],96)
            boxes.append((s['x']+min(dx for _,dx,_ in s['script']),
                          s['y']+min(dy for _,_,dy in s['script']),
                          s['x']+s['w']*2+max(dx for _,dx,_ in s['script']),
                          s['y']+s['h']*2+max(dy for _,_,dy in s['script'])))
        for i,a in enumerate(boxes):
            for b in boxes[i+1:]:
                self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])
        # Scenery changes substantially at each step, even with both fighters KO.
        down,p=render_arcade(versus_sample(0,0),animated=True)
        down_spec=board_anim.decode(p)
        frames=[compose(down,down_spec,k) for k in range(3)]
        for first,second in zip(frames,frames[1:]+frames[:1]):
            changed=[i for i,(a,b) in enumerate(zip(first,second)) if a!=b]
            self.assertGreater(sum(120<=i//320<180 for i in changed),4000)
            self.assertTrue(all(120<=i//320<202 for i in changed))
        # Sprite payload cannot depend on elapsed PC time or trigger uploads for motion.
        with patch('time.time',return_value=NOW+1):
            self.assertEqual(render_arcade(versus_sample(),animated=True)[1],payload)

    @patch('time.time', return_value=NOW)
    def test_knocked_out_pixels_stay_fixed_while_the_city_passes_behind(self, _):
        bg,payload,fighters=capture_fighters(versus_sample(0,0))
        spec=board_anim.decode(payload)
        for step in range(3):
            words=compose(bg,spec,step)
            for fighter in fighters:
                pose=fighter['frames'][0]
                for y in range(pose.height):
                    for x in range(pose.width):
                        pixel=pose.getpixel((x,y))
                        if pixel[3]>=128:
                            for dy in (0,1):
                                for dx in (0,1):
                                    index=(fighter['y']+y*2+dy)*320+fighter['x']+x*2+dx
                                    self.assertEqual(words[index],board_anim.rgb565(pixel))

    def test_city_layers_translate_in_one_direction_with_a_seamless_loop(self):
        # These bands contain only their corresponding architecture layer.
        scenes=[_scene(k) for k in range(4)]
        self.assertEqual(scenes[0].tobytes(),scenes[3].tobytes())
        # Translate only the moving layer. Gaps now reveal a stationary skyline,
        # so the complete composite must not translate those background pixels.
        layers=[]
        for phase in range(4):
            layer=Image.new('RGBA',(160,120));_city(ImageDraw.Draw(layer),phase)
            layers.append(layer.crop((0,60,160,101)))
        for a,b in zip(layers,layers[1:]):
            self.assertEqual(a.crop((6,0,160,7)).tobytes(),b.crop((0,0,154,7)).tobytes())
            # Near buildings and their windows advance twice as far.
            # Distinct lit facade anchors move 12 logical pixels per pose.
            bright = (88,214,207,255)
            xs_a={x for x in range(12,160) if a.getpixel((x,10))==bright}
            xs_b={x+12 for x in range(148) if b.getpixel((x,10))==bright}
            self.assertEqual(xs_a,xs_b)
            self.assertTrue(xs_a)

    def test_gaps_reveal_the_stationary_buildings_in_every_pose(self):
        background=Image.new('RGBA',(160,120));_stage(ImageDraw.Draw(background))
        for phase in range(3):
            moving=Image.new('RGBA',(160,120));_city(ImageDraw.Draw(moving),phase)
            scene=_scene(phase)
            revealed=0
            for y in range(60,89):
                for x in range(160):
                    if moving.getpixel((x,y))[3]==0:
                        self.assertEqual(scene.getpixel((x,y-60)),background.getpixel((x,y)))
                        if background.getpixel((x,y)) != (67,35,81,255):revealed+=1
            self.assertGreater(revealed,100)

    @patch('time.time', return_value=NOW)
    def test_saved_reserves_do_not_derive_from_quota_or_cause_ko(self, _):
        full=versus_sample(73,73)
        empty=versus_sample(73,73)
        for row in empty['accounts'].values():
            row['banked_resets']['available']=0
        a,pa=render_arcade(full,animated=True);b,pb=render_arcade(empty,animated=True)
        self.assertEqual(pa,pb)
        self.assertNotEqual(a.crop((62,30,114,42)).tobytes(),b.crop((62,30,114,42)).tobytes())
        unknown=versus_sample(73,73)
        for row in unknown['accounts'].values():
            row['banked_resets']['available']=None
        self.assertNotEqual(render_arcade(unknown).tobytes(),render_arcade(empty).tobytes())


if __name__ == '__main__':
    unittest.main()
