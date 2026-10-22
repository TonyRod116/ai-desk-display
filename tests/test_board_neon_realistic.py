"""Weekly facade ownership, honest data states, and continuous occluded traffic."""
import copy
import unittest
from unittest.mock import patch
from PIL import ImageChops
from test_board_forge import sample, NOW
from token_tv.board_neon_realistic import render_neon_realistic, backdrop
from token_tv import board_anim


class RealisticCityTests(unittest.TestCase):
    def render(self, data):
        with patch('time.time', return_value=NOW):
            return render_neon_realistic(data)

    def test_week_changes_only_the_owning_facade(self):
        full = sample(used=0)
        before = self.render(full)
        for provider, bounds in [('codex', (0, 0, 115, 240)), ('claude', (254, 0, 320, 240))]:
            changed = copy.deepcopy(full)
            changed['accounts'][provider]['windows'][0]['used_percent'] = 100
            after = self.render(changed)
            box = ImageChops.difference(before, after).getbbox()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box[0], bounds[0])
            self.assertLessEqual(box[2], bounds[2])
            self.assertGreater(sum(before.crop(bounds).convert('L').tobytes()),
                               sum(after.crop(bounds).convert('L').tobytes()))

    def test_unknown_is_not_exhausted_and_session_cannot_replace_week(self):
        exhausted = self.render(sample(used=100))
        data = sample(used=100)
        for account in data['accounts'].values():
            account['windows'] = [w for w in account['windows'] if w['label'] != 'WEEK']
        self.assertIsNotNone(ImageChops.difference(self.render(data), exhausted).getbbox())

    def test_sky_and_street_keep_the_original_photograph(self):
        image = self.render(sample())
        self.assertEqual(image.crop((115, 0, 254, 240)).tobytes(),
                         backdrop().crop((115, 0, 254, 240)).tobytes())

    def test_cars_never_switch_off_in_open_air(self):
        with patch('time.time', return_value=NOW):
            _, payload = render_neon_realistic(sample(), animated=True)
        specs = board_anim.decode(payload)['sprites']
        for s in specs:
            for frame, dx, dy in s['script']:
                x = s['x'] + dx
                if 148 <= x <= 220:
                    self.assertTrue(any(p != board_anim.KEY for p in s['frames'][frame]),
                                    f'Car disappears inside the open sky at {x}')
            # The loop seam is hidden, never a visible car jumping back to its origin.
            for index in (0, -1):
                frame = s['script'][index][0]
                self.assertTrue(all(p == board_anim.KEY for p in s['frames'][frame]))

    def test_session_only_changes_the_right_sign_and_expired_session_disappears(self):
        data = sample()
        current = self.render(data)
        for window in data['accounts']['claude']['windows']:
            if window['label'] == '5H':
                window['resets_at'] = NOW - 1
        expired = self.render(data)
        absent = self.render(sample(session=False))
        self.assertIsNone(ImageChops.difference(expired, absent).getbbox())
        box = ImageChops.difference(current, absent).getbbox()
        self.assertIsNotNone(box)
        self.assertGreaterEqual(box[0], 279)
        self.assertGreaterEqual(box[1], 193)  # one-pixel antialiasing fringe
        self.assertLessEqual(box[3], 212)

    def test_native_traffic_is_occluded_at_facades_and_never_overlaps(self):
        with patch('time.time', return_value=NOW):
            _, payload = render_neon_realistic(sample(), animated=True)
        specs = board_anim.decode(payload)['sprites']
        boxes = []
        for sprite in specs:
            boxes.append((sprite['y'], sprite['y'] + 2 * sprite['h']))
            visible_positions = []
            for frame, dx, dy in sprite['script']:
                pixels = sprite['frames'][frame]
                for n, word in enumerate(pixels):
                    if word != board_anim.KEY:
                        x = sprite['x'] + dx + 2 * (n % sprite['w'])
                        self.assertGreaterEqual(x, 140)
                        self.assertLess(x, 264)
                if any(p != board_anim.KEY for p in pixels):
                    visible_positions.append(sprite['x'] + dx)
            deltas = [b - a for a, b in zip(visible_positions, visible_positions[1:])]
            self.assertTrue(all(0 < d <= 8 for d in deltas) or all(-8 <= d < 0 for d in deltas))
        self.assertTrue(boxes[0][1] <= boxes[1][0] or boxes[1][1] <= boxes[0][0])
        self.assertLess(len(payload), 27000)

    def test_top_down_lamps_preserve_material_and_foreground(self):
        from token_tv.board_neon_realistic import illuminate, facade_pixels, photograph
        original = backdrop()
        for provider in ('codex', 'claude'):
            half, empty = original.copy(), original.copy()
            illuminate(half, provider, 50)
            illuminate(empty, provider, 0)
            facade = facade_pixels(provider)
            changed = [(x,y) for x,y in facade if original.getpixel((x,y)) != empty.getpixel((x,y))]
            self.assertGreater(len(changed), 30)
            # Unlit construction must remain exactly the original photo, not greyed out.
            for x,y in facade:
                if max(photograph().getpixel((x,y))) <= 40:
                    self.assertEqual(photograph().getpixel((x,y)), empty.getpixel((x,y)))
            # The foreground buildings must never act as either weekly gauge.
            self.assertIsNone(ImageChops.difference(original.crop((0,150,46,240)),
                                                    empty.crop((0,150,46,240))).getbbox())
            upper = [p for p in changed if p[1] < 60]
            lower = [p for p in changed if 155 <= p[1] < 218]
            self.assertGreater(len(upper), 10)
            self.assertGreater(len(lower), 10)
            self.assertTrue(all(half.getpixel(p) != original.getpixel(p) for p in upper))
            self.assertTrue(all(half.getpixel(p) == original.getpixel(p) for p in lower))

    def test_selected_towers_extend_to_lower_storeys(self):
        from token_tv.board_neon_realistic import illuminate
        original = backdrop()
        for provider,box in [('codex',(51,160,108,219)),('claude',(255,160,298,219))]:
            empty=original.copy()
            illuminate(empty,provider,0)
            self.assertIsNotNone(ImageChops.difference(original.crop(box),empty.crop(box)).getbbox())
            self.assertIsNone(ImageChops.difference(original.crop((301,0,320,240)),
                                                   empty.crop((301,0,320,240))).getbbox())

    def test_city_has_more_light_while_sky_stays_original(self):
        from pathlib import Path
        from PIL import Image
        with Image.open(Path(__file__).resolve().parents[1]/'token_tv/assets/neon-city-realistic-soft.png') as raw:
            original=raw.convert('RGB')
        enriched=backdrop()
        self.assertEqual(enriched.crop((140,0,250,70)).tobytes(),
                         original.crop((140,0,250,70)).tobytes())
        for box in ((35,10,110,222),(254,17,299,222),(0,140,30,210),(300,170,320,220)):
            self.assertGreater(sum(enriched.crop(box).convert('L').tobytes()),
                               sum(original.crop(box).convert('L').tobytes()))

    def test_57_and_4_leave_no_live_lamps_above_weekly_height(self):
        from token_tv.board_neon_realistic import illuminate, facade_pixels, TOWER_HEIGHTS, unlit_photograph
        for provider,remaining in [('codex',57),('claude',4)]:
            image=backdrop().copy()
            illuminate(image,provider,remaining)
            top,bottom=TOWER_HEIGHTS[provider]
            boundary=bottom-(bottom-top)*remaining/100
            upper=[p for p in facade_pixels(provider) if p[1]<boundary-3]
            self.assertTrue(all(image.getpixel(p)==unlit_photograph().getpixel(p) for p in upper),
                            'Generated windows/glow escaped the ambient restoration layer')
            lower=[p for p in facade_pixels(provider) if p[1]>boundary+3]
            self.assertTrue(any(max(image.getpixel(p))>100 for p in lower))

    def test_unlit_plate_preserves_ambient_material_instead_of_black_clamping(self):
        from token_tv.board_neon_realistic import photograph,unlit_photograph,facade_pixels
        source,unlit=photograph(),unlit_photograph()
        for provider in ('codex','claude'):
            points=facade_pixels(provider)
            unchanged=sum(source.getpixel(p)==unlit.getpixel(p) for p in points)
            self.assertGreater(unchanged/len(points),.60)
            ambient=[p for p in points if 40<max(source.getpixel(p))<=80]
            self.assertTrue(all(source.getpixel(p)==unlit.getpixel(p) for p in ambient))

    def test_consumed_source_lamps_are_mostly_off_not_translucent(self):
        from token_tv.board_neon_realistic import photograph,unlit_photograph,facade_pixels
        source,off=photograph(),unlit_photograph()
        for provider in ('codex','claude'):
            lamps=[p for p in facade_pixels(provider) if max(source.getpixel(p))>=130]
            self.assertGreater(len(lamps),100)
            extinguished=sum(max(off.getpixel(p))<60 for p in lamps)
            self.assertGreater(extinguished/len(lamps),.95)
