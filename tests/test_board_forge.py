"""Fine photographic skyline and aerial traffic beside stable weekly instruments."""
import copy
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from token_tv import board_anim
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_pages import FACES, PAGE_NAMES, frame_size, render_board_pages, rgb565_frame
from token_tv.sample import snapshot

NOW = 2000000000


def sample(used=27, session=True, hearts=2):
    data = snapshot(now=NOW, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', used, 6 * 86400 + 8 * 3600)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', used, 5 * 86400 + 16 * 3600)] +
         ([('5H', 41, 7200)] if session else []))])
    for provider in ('codex', 'claude'):
        data['accounts'][provider]['banked_resets'] = {'available': hearts, 'confirmed_at': NOW, 'source': 'manual'}
    return data


def compose(background, spec, step):
    """Reference composition in screen pixels, independent of the renderer."""
    words = list(struct.unpack('<76800H', rgb565_frame(background)[8:]))
    for sprite in spec['sprites']:
        frame, dx, dy = sprite['script'][step % len(sprite['script'])]
        for index, word in enumerate(sprite['frames'][frame]):
            if word == board_anim.KEY:
                continue
            x = sprite['x'] + dx + index % sprite['w'] * 2
            y = sprite['y'] + dy + index // sprite['w'] * 2
            for yy in (y, y + 1):
                for xx in (x, x + 1):
                    words[yy * 320 + xx] = word
    return words


class CodeForgeTests(unittest.TestCase):
    def test_smooth_variant_keeps_the_users_original_city_and_crop(self):
        from PIL import Image
        from token_tv.board_neon_smooth import backdrop
        path=Path(__file__).resolve().parents[1]/'token_tv/assets/neon-city.png'
        with Image.open(path) as original:
            self.assertEqual(backdrop().crop((0,24,174,240)).tobytes(),
                             original.convert('RGB').tobytes())

    def test_forge_replaces_orbit_in_the_third_board_slot_only(self):
        from token_tv.board_neon_bridge import render_neon_bridge as render_forge
        self.assertEqual(PAGE_NAMES, ('game-boy', 'paradise', 'code-forge', 'surf', 'dials',
                                      'arcade', 'cockpit', 'countdown'))
        self.assertIn('orbit', FACES)  # the clock's separate album is unchanged
        self.assertNotIn('code-forge', FACES)
        with patch('time.time', return_value=NOW):
            data = sample()
            background, payload = render_forge(data, animated=True)
            pages = render_board_pages(data, stars=True, anim=True)
            self.assertEqual(pages[2], rgb565_frame(background, anim=payload))
            self.assertEqual(len(pages), 8)

    def test_four_distinct_pixel_poses_match_static_fallback_and_fit_the_existing_protocol(self):
        from token_tv.board_forge import render_forge
        with patch('time.time', return_value=NOW):
            data = sample()
            static = render_forge(data)
            background, payload = render_forge(data, animated=True)
            spec = board_anim.decode(payload)
            # Leave at least as much device RAM as the original 27.7 KB forge scene.
            self.assertLessEqual(len(payload), 27000)
            self.assertEqual(struct.pack('<76800H', *compose(background, spec, 0)), rgb565_frame(static)[8:])
            self.assertEqual(len({struct.pack('<76800H', *compose(background, spec, i)) for i in range(4)}), 4)
            with patch('time.time', return_value=NOW + 1):
                self.assertEqual(render_forge(data, animated=True)[1], payload)
            frame = rgb565_frame(background, anim=payload)
            self.assertEqual(frame_size(frame), (320, 240))
            self.assertLessEqual(len(frame), MAX_PAGE_BYTES)
            self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
            pixels = static.load()
            # the user requested finer native detail in the art, while instruments
            # keep the exact 2x bitmap geometry for readability.
            self.assertTrue(all(pixels[x, y] == pixels[x + 1, y] == pixels[x, y + 1] == pixels[x + 1, y + 1]
                                for y in range(16, 240, 2) for x in range(178, 320, 2)))
            self.assertTrue(any(pixels[x, y] != pixels[x + 1, y] or pixels[x, y] != pixels[x, y + 1]
                                for y in range(32, 120, 2) for x in range(2, 174, 2)))
            # The user's fine source image must survive natively; do not reduce
            # it to the old procedural scene's few flat colours or 2x blocks.
            self.assertGreater(len(background.crop((0, 24, 174, 240)).getcolors(76800)), 1024)
            from PIL import Image
            with Image.open(Path(__file__).resolve().parents[1] / 'token_tv/assets/neon-city.png') as photo:
                self.assertEqual(photo.size, (174, 216))
                self.assertEqual(photo.info, {})
                self.assertEqual(background.crop((0, 24, 174, 240)).tobytes(), photo.convert('RGB').tobytes())

    def test_weekly_quota_session_reset_times_and_unknown_hearts_are_readings_not_decoration(self):
        from token_tv.board_forge import render_forge
        cases = [sample(0, hearts=0), sample(100, hearts=3), sample(session=False),
                 sample(hearts=None), {'accounts': {}}]
        changed_reset = copy.deepcopy(cases[0])
        changed_reset['accounts']['codex']['windows'][0]['resets_at'] += 86400
        cases.append(changed_reset)
        with patch('time.time', return_value=NOW):
            images = [render_forge(data, animated=True)[0] for data in cases]
            payloads = [render_forge(data, animated=True)[1] for data in cases]
        self.assertTrue(all(p == payloads[0] for p in payloads))
        self.assertEqual(len({image.crop((178, 16, 320, 240)).tobytes() for image in images}), len(images))
        self.assertTrue(all(image.crop((0, 32, 176, 236)).tobytes() == images[0].crop((0, 32, 176, 236)).tobytes()
                            for image in images[1:]))
        # Unknown saved resets are visually distinct from a confirmed empty bank.
        with patch('time.time', return_value=NOW):
            self.assertNotEqual(render_forge(sample(hearts=0)).tobytes(),
                                render_forge(sample(hearts=None)).tobytes())
            previous_hearts = sample(hearts=None)
            previous_hearts['accounts']['claude']['banked_resets']['last_known'] = 1
            self.assertNotEqual(render_forge(previous_hearts).tobytes(), render_forge(sample(hearts=1)).tobytes())
            self.assertNotEqual(render_forge(sample(hearts=3)).tobytes(), render_forge(sample(hearts=4)).tobytes())
            with_session, without = render_forge(sample()), render_forge(sample(session=False))
            self.assertEqual(with_session.crop((178, 16, 320, 128)).tobytes(), without.crop((178, 16, 320, 128)).tobytes())
            self.assertNotEqual(with_session.crop((178, 128, 320, 240)).tobytes(), without.crop((178, 128, 320, 240)).tobytes())
        # Firmware restores the WHOLE sprite box. Even transparent texels must avoid the HUD.
        for sprite in board_anim.decode(payloads[0])['sprites']:
            for frame, dx, dy in sprite['script']:
                self.assertTrue(0 <= sprite['x'] + dx and sprite['x'] + dx + sprite['w'] * 2 <= 176)
                self.assertTrue(32 <= sprite['y'] + dy and sprite['y'] + dy + sprite['h'] * 2 <= 236)
                for i, word in enumerate(sprite['frames'][frame]):
                    if word == board_anim.KEY:
                        continue
                    x = sprite['x'] + dx + i % sprite['w'] * 2
                    y = sprite['y'] + dy + i // sprite['w'] * 2
                    self.assertTrue(0 <= x < 175 and 32 <= y < 235)

    def test_equal_weekly_bars_are_much_larger_than_claudes_five_hour_bars(self):
        from token_tv.board_forge import render_forge
        full, empty = sample(0), sample(100)
        session_empty = copy.deepcopy(full)
        full['accounts']['claude']['windows'][1]['used_percent'] = 0
        session_empty['accounts']['claude']['windows'][1]['used_percent'] = 100
        with patch('time.time', return_value=NOW):
            filled_image = render_forge(full)
            empty_image = render_forge(empty)
            session_image = render_forge(session_empty)

        def changed(first, second, box):
            before, after = first.crop(box), second.crop(box)
            a, b = before.load(), after.load()
            return before.size, [a[x, y] != b[x, y] for y in range(before.height) for x in range(before.width)]

        week_size, codex_mask = changed(filled_image, empty_image, (188, 84, 306, 100))
        claude_size, claude_mask = changed(filled_image, empty_image, (188, 194, 306, 210))
        session_size, session_mask = changed(filled_image, session_image, (206, 212, 282, 216))
        self.assertEqual(week_size, claude_size)
        self.assertEqual(codex_mask, claude_mask)
        self.assertTrue(all(any(codex_mask[y * week_size[0]:(y + 1) * week_size[0]])
                            for y in range(week_size[1])))
        self.assertTrue(all(any(session_mask[y * session_size[0]:(y + 1) * session_size[0]])
                            for y in range(session_size[1])))
        self.assertGreaterEqual(week_size[1], session_size[1] * 3)
        self.assertLess(session_size[0], week_size[0] * 0.75)

    def test_opposite_air_traffic_and_neon_lights_animate_without_changing_quota_instruments(self):
        from token_tv.board_forge import render_forge
        with patch('time.time', return_value=NOW):
            background, payload = render_forge(sample(), animated=True)
        spec = board_anim.decode(payload)
        self.assertEqual(spec['stars'], [])
        self.assertIsNone(spec['meteor'])
        vehicles = [sprite for sprite in spec['sprites']
                  if any(dx or dy for _, dx, dy in sprite['script'])]
        self.assertEqual(len(vehicles), 2)
        vehicle = vehicles[0]
        steps = len(vehicle['script'])
        self.assertGreaterEqual(steps, 8)
        self.assertGreater(len({(dx, dy) for _, dx, dy in vehicle['script']}), 7)
        self.assertTrue(any(dx > 0 for _, dx, dy in vehicles[0]['script']))
        self.assertTrue(any(dx < 0 for _, dx, dy in vehicles[1]['script']))
        self.assertTrue(all(abs(dy) <= 1 for sprite in vehicles for _, dx, dy in sprite['script']))
        self.assertLessEqual(max(sprite['w'] for sprite in vehicles) * 2, 36)
        poses = [compose(background, spec, i) for i in range(steps)]

        def region(words, box):
            x0, y0, x1, y1 = box
            return tuple(word for y in range(y0, y1) for word in words[y * 320 + x0:y * 320 + x1])

        # Upper and lower flying lanes cross in opposite directions. Pulsing
        # signs stay on the source buildings, away from the readings.
        for box in ((0, 84, 176, 98), (0, 118, 176, 138)):
            self.assertGreaterEqual(len({region(p, box) for p in poses}), steps - 4)
        for box in ((16, 36, 42, 58), (24, 170, 44, 192)):
            self.assertGreaterEqual(len({region(p, box) for p in poses}), 3)
        static = list(struct.unpack('<76800H', rgb565_frame(background)[8:]))
        for pose in poses:
            self.assertEqual(region(pose, (178, 16, 320, 240)), region(static, (178, 16, 320, 240)))
        # Restoring a moving vehicle's full box must never erase another sprite.
        for step in range(steps):
            boxes = []
            for sprite in spec['sprites']:
                _, dx, dy = sprite['script'][step % len(sprite['script'])]
                x, y = sprite['x'] + dx, sprite['y'] + dy
                boxes.append((x, y, x + sprite['w'] * 2, y + sprite['h'] * 2))
            for i, first in enumerate(boxes):
                for second in boxes[i + 1:]:
                    self.assertTrue(first[2] <= second[0] or second[2] <= first[0]
                                    or first[3] <= second[1] or second[3] <= first[1])


if __name__ == '__main__':
    unittest.main()
