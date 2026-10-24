"""The cockpit page (7): two glass orbs in deep space, readable numbers, a sky the firmware can twinkle."""
import math
import struct
import unittest
from unittest.mock import patch

from PIL import Image

from token_tv import board_art, board_space
from token_tv import board_anim
from token_tv.board_art import FLARE, free_stars
from token_tv.board_pages import PAGE_NAMES, render_board_pages, rgb565_frame
from token_tv.sample import snapshot

NOW = 2000000000


def sample(used=27, session=True):
    data = snapshot(now=NOW, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', used, 6 * 86400 + 8 * 3600)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', used, 5 * 86400 + 16 * 3600)] +
         ([('5H', 41, 7200)] if session else []))])
    for provider in ('codex', 'claude'):
        data['accounts'][provider]['banked_resets'] = {'available': 2, 'confirmed_at': NOW, 'source': 'manual'}
    return data


def luminance(colour):
    channels = [v / 255 for v in colour[:3]]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


def bare():
    return board_space.space_backdrop().resize((board_art.W, board_art.H), Image.Resampling.LANCZOS).convert('RGB')


class SpaceCockpitTests(unittest.TestCase):
    @patch('time.time', return_value=NOW)
    def test_ufo_preserves_the_readings_and_matches_the_static_first_pose(self, _):
        from test_board_forge import compose
        image, payload = board_space.render_cockpit(sample(), animated=True)
        spec = board_anim.decode(payload)
        self.assertLess(len(payload), 40000)
        self.assertEqual(struct.pack('<76800H',*compose(image,spec,0)),
                         rgb565_frame(board_space.render_cockpit(sample()))[8:])
        sprite = spec['sprites'][0]
        self.assertEqual(len(sprite['script']),32)
        self.assertTrue(all(w == board_anim.KEY for w in sprite['frames'][-1]))
        for _,dx,dy in sprite['script']:
            x0,y0 = sprite['x']+dx,sprite['y']+dy
            x1,y1 = x0+sprite['w']*2,y0+sprite['h']*2
            self.assertGreaterEqual(y0,15)
            for cx,cy in board_space.CENTRES.values():
                nearest = (max(x0,min(cx,x1)),max(y0,min(cy,y1)))
                self.assertGreater(math.dist(nearest,(cx,cy)),73)
        for x,y,*_ in spec['stars']:
            self.assertFalse(114 <= x <= 206 and 12 <= y <= 42)
        self.assertEqual(render_board_pages(sample(),stars=True,anim=True)[6],rgb565_frame(image,anim=payload))

    def test_the_page_is_deterministic_and_real_readings_change_it(self):
        with patch('time.time', return_value=NOW):
            first, second = board_space.render_cockpit(sample()), board_space.render_cockpit(sample())
            unknown = board_space.render_cockpit({'accounts': {}})
        self.assertEqual(first.size, (320, 240))
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertNotEqual(first.tobytes(), unknown.tobytes())

    def test_the_sky_really_is_a_nebula_with_violet_magenta_and_teal_gas(self):
        image = bare()
        families = {'violet': 0, 'magenta': 0, 'teal': 0}
        for r, g, b in image.getdata():
            if b > 90 and b > r + 30 and b > g + 40:
                families['violet'] += 1
            elif r > 70 and b > 70 and g < min(r, b) - 25:
                families['magenta'] += 1
            elif g > 70 and b > 70 and r < min(g, b) - 30:
                families['teal'] += 1
        for name, count in families.items():
            self.assertGreater(count, 600, name)

    def test_labels_and_the_title_keep_a_readable_contrast_over_the_nebula(self):
        image = bare()
        label = board_art._rgb(board_space.LABEL)
        for name, (x0, y0, x1, y1) in {'left labels': (28, 160, 136, 224), 'right labels': (184, 160, 292, 224),
                                       'title row': (10, 4, 310, 14)}.items():
            pixels = sorted((image.getpixel((x, y)) for y in range(y0, y1) for x in range(x0, x1)), key=luminance)
            p98 = pixels[int(len(pixels) * .98)]
            self.assertGreaterEqual(contrast(label, p98), 4.5, name)

    def test_the_orbs_keep_the_numbers_readable_and_are_lit_from_the_upper_left(self):
        with patch('time.time', return_value=NOW):
            image = board_space.render_cockpit(sample())
        for provider, (cx, cy) in board_space.CENTRES.items():
            ring = [image.getpixel((round(cx + math.cos(math.radians(a)) * 24), round(cy + math.sin(math.radians(a)) * 24)))
                    for a in range(0, 360, 15) if not 60 <= a <= 120]          # not across the "%" under the number
            for pixel in ring:                                               # white digits sit on a dark orb (the highlight is the brightest part)
                self.assertGreaterEqual(contrast((255, 255, 255), pixel), 4.5, (provider, pixel))
            lit = image.getpixel((round(cx + math.cos(math.radians(225)) * 28), round(cy + math.sin(math.radians(225)) * 28)))
            dark = image.getpixel((round(cx + math.cos(math.radians(45)) * 28), round(cy + math.sin(math.radians(45)) * 28)))
            self.assertGreater(luminance(lit), luminance(dark) * 1.5, provider)

    def test_each_provider_keeps_its_own_colour_and_no_traffic_lights(self):
        with patch('time.time', return_value=NOW):
            image = board_space.render_cockpit(sample(used=40))             # 60% left: the band reaches past 12 o'clock
        for provider, (cx, cy) in board_space.CENTRES.items():
            angle = math.radians(200)                                        # lower left, inside the filled part
            r, g, b = image.getpixel((round(cx + math.cos(angle) * 53), round(cy + math.sin(angle) * 53)))
            if provider == 'codex':
                self.assertTrue(r > 150 and r > g > b + 40, (r, g, b))        # golden
            else:
                self.assertTrue(abs(r - g) < 40 and abs(g - b) < 50 and r > 110, (r, g, b))   # stone, never green or red

    def test_the_stars_twinkle_without_touching_anything_drawn_on_top(self):
        with patch('time.time', return_value=NOW):
            image = board_space.render_cockpit(sample())
        stars = free_stars(image, backdrop=board_space.space_backdrop, field=board_space.star_field)
        self.assertGreater(len(stars), 100)
        self.assertLessEqual(len(stars), 128)
        pixels = [(x + dx, y + dy) for x, y, _ in stars for dx, dy in FLARE]
        self.assertEqual(len(pixels), len(set(pixels)))                       # no two crosses share a pixel
        for x, y, _ in stars:
            self.assertTrue(2 <= x < 318 and 2 <= y < 238 and not (x > 218 and y > 218))   # on screen, off the marker
            self.assertTrue(all(math.dist((x, y), centre) > 58 for centre in board_space.CENTRES.values()))
        covered = bare()
        covered.putpixel((stars[0][0] + 2, stars[0][1]), (255, 0, 0))
        self.assertNotIn(stars[0][:2], [s[:2] for s in free_stars(covered, backdrop=board_space.space_backdrop,
                                                                  field=board_space.star_field)])

    def test_the_board_gets_the_cockpits_own_stars(self):
        with patch('time.time', return_value=NOW):
            frames = render_board_pages(sample(), stars=True)
        cockpit = frames[PAGE_NAMES.index('cockpit')]
        at = 8 + 320 * 240 * 2
        self.assertEqual(cockpit[at:at + 4], b'STAR')
        self.assertGreater(struct.unpack('<H', cockpit[at + 4:at + 6])[0], 100)


if __name__ == '__main__':
    unittest.main()
