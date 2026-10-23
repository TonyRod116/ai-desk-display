"""Bridge lamps show weekly quota; the city itself stays lit and the traffic stays native."""
import copy
import struct
import unittest
from unittest.mock import patch

from PIL import ImageChops

from test_board_forge import NOW, compose, sample
from token_tv import board_anim
from token_tv.board_neon_bridge import render_neon_bridge
from token_tv.board_pages import rgb565_frame


class NeonBridgeTests(unittest.TestCase):
    def render(self, left=57, right=4, data=None, animated=False):
        if data is None:
            data = sample(used=100-left)
            data['accounts']['claude']['windows'][0]['used_percent'] = 100-right
        with patch('time.time', return_value=NOW):
            return render_neon_bridge(data, animated=animated)

    def test_week_changes_only_its_bridge_half_and_sign_not_the_towers(self):
        full = self.render(100, 100)
        for left, right, bounds in ((0, 100, (68, 164, 177, 200)),
                                    (100, 0, (179, 164, 289, 200))):
            with self.subTest(left=left, right=right):
                empty = self.render(left, right)
                changed = ImageChops.difference(full, empty).getbbox()
                self.assertIsNotNone(changed)
                self.assertGreaterEqual(changed[0], bounds[0])
                self.assertGreaterEqual(changed[1], bounds[1])
                self.assertLessEqual(changed[2], bounds[2])
                self.assertLessEqual(changed[3], bounds[3])
                self.assertEqual(full.crop((0, 0, 320, 164)).tobytes(),
                                 empty.crop((0, 0, 320, 164)).tobytes())

    def test_remaining_light_retracts_to_the_outer_ends_at_half_and_low_quota(self):
        for provider, bounds, extreme in (('codex', (72, 169, 176, 174), 'left'),
                                         ('claude', (181, 169, 285, 174), 'right')):
            base = self.render(0, 0).crop(bounds)
            counts = []
            for remaining in (0, 4, 25, 50, 57, 100):
                values = (remaining, 0) if provider == 'codex' else (0, remaining)
                current = self.render(*values).crop(bounds)
                # Independent optical observation: scan for powered lamp apertures.
                columns = [x for x in range(current.width) if any(
                    max(current.getpixel((x, y))) >= 180
                    and max(current.getpixel((x, y))) - max(base.getpixel((x, y))) >= 100
                    for y in range(current.height))]
                counts.append(len(columns))
                if not remaining:
                    self.assertEqual(columns, [])
                    continue
                self.assertGreaterEqual(len(columns), 3, 'Even 4% must be visible')
                if remaining <= 57:
                    limit = current.width * remaining / 100
                    if extreme == 'left':
                        self.assertLessEqual(max(columns), limit + 1)
                        self.assertLessEqual(min(columns), 1)
                    else:
                        self.assertGreaterEqual(min(columns), current.width - limit - 2)
                        self.assertGreaterEqual(max(columns), current.width - 2)
            self.assertEqual(counts, sorted(set(counts)))

    def test_unknown_and_stale_are_distinct_from_zero_and_full(self):
        missing = sample(session=False)
        stale = copy.deepcopy(missing)
        for row in missing['accounts'].values():
            row['windows'] = []
        for row in stale['accounts'].values():
            row['status'] = 'stale'
        unknown = self.render(data=missing)
        self.assertNotEqual(unknown.tobytes(), self.render(0, 0, data=sample(used=100, session=False)).tobytes())
        self.assertNotEqual(unknown.tobytes(), self.render(data=sample(used=0, session=False)).tobytes())
        self.assertEqual(unknown.tobytes(), self.render(data=stale).tobytes())

    def test_session_never_supplies_the_week_and_expiry_preserves_weekly_lamps(self):
        data = sample(used=43)
        missing_week = copy.deepcopy(data)
        missing_week['accounts']['claude']['windows'] = [data['accounts']['claude']['windows'][1]]
        before = self.render(data=data)
        unknown = self.render(data=missing_week)
        self.assertNotEqual(before.crop((179, 164, 289, 187)).tobytes(),
                            unknown.crop((179, 164, 289, 187)).tobytes())
        for window in data['accounts']['claude']['windows']:
            if window['label'] == '5H':
                window['resets_at'] = NOW - 1
        expired = self.render(data=data)
        self.assertEqual(expired.tobytes(), self.render(data=sample(used=43, session=False)).tobytes())
        self.assertEqual(before.crop((68, 164, 289, 175)).tobytes(),
                         expired.crop((68, 164, 289, 175)).tobytes())
        box = ImageChops.difference(before, expired).getbbox()
        self.assertGreaterEqual(box[0], 239)
        self.assertGreaterEqual(box[1], 184)  # antialiasing around the lower sign edge
        self.assertLessEqual(box[2], 289)
        self.assertLessEqual(box[3], 200)

    def test_animation_does_not_depend_on_quota_or_wall_clock_and_matches_still(self):
        payloads = []
        for left, right in ((100, 100), (57, 4), (0, 0)):
            image, payload = self.render(left, right, animated=True)
            spec = board_anim.decode(payload)
            self.assertEqual(struct.pack('<76800H', *compose(image, spec, 0)),
                             rgb565_frame(self.render(left, right))[8:])
            self.assertLess(len(payload), 2000)
            self.assertEqual(len(spec['sprites']), 4)
            for sprite in spec['sprites']:
                self.assertLess(sprite['y'] + sprite['h'] * 2, 164)
            payloads.append(payload)
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(payloads[1], payloads[2])
        with patch('time.time', return_value=NOW+1):
            self.assertEqual(render_neon_bridge(sample(), animated=True)[1], payloads[0])

    def test_sprite_restoration_boxes_are_disjoint_and_traffic_has_hidden_loop_seams(self):
        _, payload = self.render(animated=True)
        specs = board_anim.decode(payload)['sprites']
        boxes = []
        for sprite in specs:
            poses = [(sprite['x'] + dx, sprite['y'] + dy) for _, dx, dy in sprite['script']]
            boxes.append((min(x for x, _ in poses), min(y for _, y in poses),
                          max(x for x, _ in poses) + 2 * sprite['w'],
                          max(y for _, y in poses) + 2 * sprite['h']))
            if any(dx for _, dx, _ in sprite['script']):
                for step in (0, -1):
                    frame = sprite['script'][step][0]
                    self.assertTrue(all(p == board_anim.KEY for p in sprite['frames'][frame]))
                for frame, dx, _ in sprite['script']:
                    if 148 <= sprite['x'] + dx <= 220:
                        self.assertTrue(any(p != board_anim.KEY for p in sprite['frames'][frame]))
        for i, a in enumerate(boxes):
            for b in boxes[i+1:]:
                self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
