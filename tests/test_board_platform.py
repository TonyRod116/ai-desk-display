"""The platform level keeps real usage readable and animates on the board."""
import copy
import struct
import unittest
from unittest.mock import patch

from token_tv import board_anim
from token_tv.board_credits import BOXES, apply_credit_badges
from token_tv.board_pages import PAGE_NAMES, frame_size, render_board_pages, rgb565_frame
from token_tv.board_platform import render_platform
from token_tv.sample import snapshot
from test_board_forge import compose

NOW = 2_000_000_000


def sample(used=27, session=True, resets=2):
    result = snapshot(now=NOW, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', used, 6 * 86400 + 8 * 3600)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', used, 5 * 86400 + 16 * 3600)] +
         ([('5H', 41, 7200)] if session else []))])
    for provider in ('codex', 'claude'):
        result['accounts'][provider]['banked_resets'] = {'available': resets}
    return result


def sprite_box(sprite):
    dx = [0] + [step[1] for step in sprite['script']]
    dy = [0] + [step[2] for step in sprite['script']]
    return (sprite['x'] + min(dx), sprite['y'] + min(dy),
            sprite['x'] + max(dx) + 2 * sprite['w'],
            sprite['y'] + max(dy) + 2 * sprite['h'])


def overlaps(a,b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class PlatformTests(unittest.TestCase):
    @patch('time.time', return_value=NOW)
    def test_page_seven_uses_the_level_and_old_firmware_gets_its_first_pose(self, _):
        data=sample()
        static=render_platform(data)
        self.assertEqual(static.size,(320,240))
        for limit in (4,8):
            image,payload=render_platform(data,animated=True,anim_frames=limit)
            spec=board_anim.decode(payload)
            self.assertLess(len(payload),40000)
            self.assertEqual(len(spec['sprites']),4)
            self.assertTrue(all(len(s['frames'])<=limit for s in spec['sprites']))
            self.assertEqual(struct.pack('<76800H',*compose(image,spec,0)),rgb565_frame(static)[8:])
            frame=render_board_pages(data,anim=True,anim_frames=limit)[PAGE_NAMES.index('cockpit')]
            self.assertEqual(frame,rgb565_frame(image,anim=payload))
            self.assertEqual(frame_size(frame),(320,240))
        self.assertEqual(render_board_pages(data)[6],rgb565_frame(static))

    @patch('time.time', return_value=NOW)
    def test_sprite_restoration_cannot_erase_another_actor_or_the_hud(self, _):
        _,payload=render_platform(sample(),animated=True)
        sprites=board_anim.decode(payload)['sprites']
        boxes=[sprite_box(s) for s in sprites]
        for i,box in enumerate(boxes):
            self.assertTrue(0<=box[0]<box[2]<=320 and 0<=box[1]<box[3]<=240,box)
            self.assertGreaterEqual(box[1],48)
            for other in boxes[i+1:]:
                self.assertFalse(overlaps(box,other),(box,other))
            self.assertFalse(overlaps(box,BOXES['cockpit']))
        mario=sprites[0]
        self.assertGreater(len(set(mario['script'])),20)
        # The motion wraps continuously: no actor silently teleports to start.
        for previous,current in zip(mario['script'],mario['script'][1:]+mario['script'][:1]):
            self.assertLessEqual(abs(current[1]-previous[1]),3)
            self.assertLessEqual(abs(current[2]-previous[2]),5)

    @patch('time.time', return_value=NOW)
    def test_each_week_and_reset_updates_only_its_own_score(self, _):
        baseline=sample()
        original=render_platform(baseline)
        for provider,own,other in (('codex',(0,0,160,48),(160,0,320,48)),
                                   ('claude',(160,0,320,48),(0,0,160,48))):
            for change in ('used','reset'):
                data=copy.deepcopy(baseline)
                week=data['accounts'][provider]['windows'][0]
                if change=='used':week['used_percent']=83
                else:week['resets_at']+=86400
                image=render_platform(data)
                self.assertNotEqual(image.crop(own).tobytes(),original.crop(own).tobytes(),(provider,change))
                self.assertEqual(image.crop(other).tobytes(),original.crop(other).tobytes(),(provider,change))
        self.assertNotEqual(render_platform({'accounts':{}}).crop((0,0,160,48)).tobytes(),
                            render_platform(sample(used=100)).crop((0,0,160,48)).tobytes())

    @patch('time.time', return_value=NOW)
    def test_five_hour_meter_disappears_when_unknown_or_expired_but_week_remains(self, _):
        live=sample()
        without=sample(session=False)
        expired=copy.deepcopy(live)
        expired['accounts']['claude']['windows'][1]['resets_at']=NOW-1
        live_image=render_platform(live)
        missing_image=render_platform(without)
        expired_image=render_platform(expired)
        meter=(240,18,306,30)
        self.assertNotEqual(live_image.crop(meter).tobytes(),missing_image.crop(meter).tobytes())
        self.assertEqual(expired_image.crop((160,0,320,48)).tobytes(),missing_image.crop((160,0,320,48)).tobytes())
        self.assertEqual(live_image.crop((160,30,320,48)).tobytes(),missing_image.crop((160,30,320,48)).tobytes())

    @patch('time.time', return_value=NOW)
    def test_an_old_week_is_marked_old_and_never_shows_a_session_as_fresh(self, _):
        data=sample()
        old=copy.deepcopy(data)
        old['accounts']['claude']['status']='stale'
        current=render_platform(data)
        stale=render_platform(old)
        self.assertNotEqual(current.crop((226,3,250,14)).tobytes(),stale.crop((226,3,250,14)).tobytes())
        without=render_platform(sample(session=False))
        self.assertEqual(stale.crop((240,18,306,30)).tobytes(),without.crop((240,18,306,30)).tobytes())

    @patch('time.time', return_value=NOW)
    def test_exhausted_credits_replace_the_codex_number_without_touching_claude_or_the_actors(self, _):
        data=sample(used=100)
        data['accounts']['codex'].update(quota_origin='codex_official_cli',identity_verified=True,
                                        status='ok',credits_balance='137.5')
        image,payload=render_platform(data,animated=True)
        original=image.copy()
        apply_credit_badges([image],['cockpit'],data)
        x0,y0,x1,y1=BOXES['cockpit']
        self.assertNotEqual(original.crop((x0,y0,x1+1,y1+1)).tobytes(),image.crop((x0,y0,x1+1,y1+1)).tobytes())
        self.assertEqual(original.crop((160,0,320,240)).tobytes(),image.crop((160,0,320,240)).tobytes())
        self.assertEqual(original.crop((0,34,320,240)).tobytes(),image.crop((0,34,320,240)).tobytes())
        for sprite in board_anim.decode(payload)['sprites']:
            self.assertFalse(overlaps(sprite_box(sprite),BOXES['cockpit']))


if __name__=='__main__':
    unittest.main()
