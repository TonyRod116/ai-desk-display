import unittest
from unittest.mock import patch
from PIL import Image

from token_tv.board_credits import apply_credit_badges, BOXES
from token_tv.board_pages import PAGE_NAMES, render_board_pages
from token_tv.board_anim import decode, KEY
from token_tv.sample import snapshot


def sample(week=100, balance='137.5'):
    data = snapshot(now=1000, sample=[('codex', 'CODEX', 'codex', [('WEEK', week, 4000)]),
                                       ('claude', 'CLAUDE', 'claude', [('WEEK', 10, 4000)])])
    data['accounts']['codex'].update(quota_origin='codex_official_cli', identity_verified=True,
                                      status='ok', credits_balance=balance)
    return data


class BoardCreditTests(unittest.TestCase):
    def test_badge_only_changes_each_codex_instrument_when_week_exhausted(self):
        originals = [Image.new('RGB', (320, 240), '#303030') for _ in PAGE_NAMES]
        controls = [im.copy() for im in originals]
        apply_credit_badges(controls, PAGE_NAMES, sample(99))
        self.assertTrue(all(a.tobytes() == b.tobytes() for a, b in zip(originals, controls)))
        apply_credit_badges(originals, PAGE_NAMES, sample())
        for image, name in zip(originals, PAGE_NAMES):
            x0,y0,x1,y1 = BOXES[name]
            with self.subTest(name=name):
                self.assertNotEqual(image.getpixel((x0+3,y0+3)), (48,48,48))
                self.assertEqual(image.getpixel((319,239)), (48,48,48))

    def test_fighting_game_animated_stars_and_meteor_do_not_overwrite_balance(self):
        with patch('time.time', return_value=1000):
            frames = render_board_pages(sample(), anim=True)
        frame = frames[PAGE_NAMES.index('arcade')]
        at = 8 + 320*240*2
        animation = decode(frame[at+8:])
        x0,y0,x1,y1 = BOXES['arcade']
        self.assertFalse(any(x0 <= star[0] <= x1 and y0 <= star[1] <= y1 for star in animation['stars']))
        self.assertGreater(animation['meteor']['x0'], x1)
        for sprite in animation['sprites']:
            for f,dx,dy in sprite['script']:
                left,top = sprite['x']+dx,sprite['y']+dy
                for y in range(max(y0,top), min(y1+1,top+2*sprite['h'])):
                    for x in range(max(x0,left), min(x1+1,left+2*sprite['w'])):
                        self.assertEqual(sprite['frames'][f][((y-top)//2)*sprite['w']+(x-left)//2], KEY)
