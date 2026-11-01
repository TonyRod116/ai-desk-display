"""The new cities use fictional quota samples and bounded native animations."""
import math
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from token_tv import board_anim, board_cyber_scenes as city
from token_tv.board_control import BoardControl, preview_image
from token_tv.board_pages import rgb565_frame
from token_tv.sample import snapshot
from token_tv.board_scenes import BoardScenes


class CyberSceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        for filename in city.FILES.values():
            Image.new('RGB', (640, 480), (192, 96, 192)).save(directory / filename)
        self.patch = patch.object(city, 'ART', directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        city._cached_backdrop.cache_clear()
        self.addCleanup(city._cached_backdrop.cache_clear)
        self.data = snapshot(time.time(), [
            ('codex', 'CODEX', 'codex', [('WEEK', 50, 86400)]),
            ('claude', 'CLAUDE', 'claude', [('WEEK', 25, 86400)]),
        ])

    def test_leds_grow_from_the_bottom_with_remaining_quota(self):
        for scene, rails in city.RAILS.items():
            for provider, (x, top, bottom) in rails.items():
                with self.subTest(scene=scene, provider=provider):
                    levels = []
                    for remaining in (0, 50, 100):
                        image = Image.new('RGB', (320, 240), (8, 12, 16))
                        city.rail(image, provider, (x, top, bottom), remaining)
                        levels.append(sum(sum(image.getpixel((x, y))) for y in range(top, bottom)))
                    self.assertLess(levels[0], levels[1])
                    self.assertLess(levels[1], levels[2])
                    halfway = Image.new('RGB', (320, 240), (8, 12, 16))
                    city.rail(halfway, provider, (x, top, bottom), 50)
                    self.assertGreater(sum(halfway.getpixel((x, bottom - 2))), sum(halfway.getpixel((x, top + 2))))

    def test_tower_rails_are_on_the_two_central_right_towers(self):
        left = city.RAILS['violet-horizon']['codex']
        right = city.RAILS['violet-horizon']['claude']
        self.assertEqual((left[0], right[0]), (206, 247))
        self.assertLess(left[1], left[2])
        self.assertLess(right[1], right[2])

    def test_rooftop_people_fill_up_from_their_feet_independently(self):
        def draw(codex, claude):
            image = Image.new('RGB', (320, 240), (8, 12, 16))
            city.figures(image, {'codex': codex, 'claude': claude})
            return image
        empty = draw(0, 0)
        pink = draw(50, 0)
        blue = draw(0, 100)
        pink_difference = ImageChops.difference(empty, pink).getbbox()
        blue_difference = ImageChops.difference(empty, blue).getbbox()
        self.assertTrue(106 <= pink_difference[0] < pink_difference[2] <= 131)
        self.assertTrue(123 <= blue_difference[0] < blue_difference[2] <= 150)
        self.assertGreater(pink_difference[1], 185)  # At half, the upper body is dark.
        self.assertLess(blue_difference[1], 185)     # At full, the head is lit.

    def test_stale_reading_is_unknown_not_an_empty_quota(self):
        for scene in city.FILES:
            with self.subTest(scene=scene):
                row = self.data['accounts']['claude']
                row['status'] = 'stale'
                old = city.render_city(scene, self.data)
                row['status'], row['windows'] = 'ok', []
                unknown = city.render_city(scene, self.data)
                self.assertIsNone(ImageChops.difference(old, unknown).getbbox())
                row['windows'] = [{'label': 'WEEK', 'used_percent': 100, 'resets_at': time.time() + 86400}]
                empty = city.render_city(scene, self.data)
                self.assertIsNotNone(ImageChops.difference(empty, unknown).getbbox())

    def test_both_city_animations_are_distinct_bounded_and_loop_together(self):
        payloads = []
        for scene in city.FILES:
            with self.subTest(scene=scene):
                image, payload = city.render_city(scene, self.data, animated=True)
                motion = board_anim.decode(payload)
                self.assertEqual(image.size, (320, 240))
                self.assertLess(len(payload), board_anim.MAX_PAYLOAD)
                self.assertEqual(len(motion['sprites']), 4)
                self.assertEqual(motion['stars'], [])
                self.assertIsNone(motion['meteor'])
                payloads.append(payload)
                bounds = []
                for index, sprite in enumerate(motion['sprites']):
                    period = 3200 if scene == 'neon-district' else (4000 if index < 2 else 32000)
                    self.assertEqual(len(sprite['script']) * sprite['step_ms'], period)
                    self.assertLessEqual(abs(sprite['script'][0][1] - sprite['script'][-1][1]), 1)
                    self.assertLessEqual(sprite['w'], 96)
                    self.assertLessEqual(sprite['h'], 96)
                    # A uniform sky has no cloud texture to move; all other
                    # effects must contain actual lit pixels in this fixture.
                    if scene != 'violet-horizon' or index >= 2:
                        self.assertTrue(any(any(pixel != board_anim.KEY for pixel in frame)
                                            for frame in sprite['frames']))
                    bounds.append((sprite['x'], sprite['y'], sprite['x'] + sprite['w'] * 2,
                                   sprite['y'] + sprite['h'] * 2))
                    for _, dx, dy in sprite['script']:
                        self.assertGreaterEqual(sprite['x'] + dx, 0)
                        self.assertGreaterEqual(sprite['y'] + dy, 0)
                        self.assertLessEqual(sprite['x'] + dx + 2 * sprite['w'], 320)
                        self.assertLessEqual(sprite['y'] + dy + 2 * sprite['h'], 217)
                    for frame in sprite['frames']:
                        for i, pixel in enumerate(frame):
                            if pixel == board_anim.KEY:
                                continue
                            x = sprite['x'] + i % sprite['w'] * 2
                            y = sprite['y'] + i // sprite['w'] * 2
                            if scene == 'neon-district' and y >= 180:
                                self.assertFalse(106 <= x < 150, (x, y))
                            if scene == 'violet-horizon' and y >= 109:
                                self.assertFalse(204 <= x <= 210 or 245 <= x <= 250, (x, y))
                # The device restores each sprite's rectangle when it advances.
                # Overlapping rectangles would erase the other animation.
                for i, a in enumerate(bounds):
                    for b in bounds[i + 1:]:
                        self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or
                                        a[3] <= b[1] or b[3] <= a[1], (a, b))
        self.assertNotEqual(payloads[0], payloads[1])

    def test_violet_windows_stay_lit_and_change_slowly_one_building_at_a_time(self):
        _, payload = city.render_city('violet-horizon', self.data, animated=True)
        windows = board_anim.decode(payload)['sprites'][2:]

        def lit(sprite, milliseconds):
            step = (milliseconds // sprite['step_ms']) % len(sprite['script'])
            frame = sprite['frames'][sprite['script'][step][0]]
            return {i for i, pixel in enumerate(frame) if pixel != board_anim.KEY}

        for sprite in windows:
            frames = [lit(sprite, f * sprite['step_ms']) for f in range(len(sprite['script']))]
            self.assertGreaterEqual(min(map(len, frames)), 10)
            self.assertGreaterEqual(len(set.intersection(*frames)), 8)
        previous = [lit(sprite, 0) for sprite in windows]
        for time_ms in range(4000, 32001, 4000):
            current = [lit(sprite, time_ms) for sprite in windows]
            changes = [a != b for a, b in zip(previous, current)]
            self.assertEqual(sum(changes), 1, time_ms)
            for old, new in zip(previous, current):
                if old != new:
                    self.assertTrue(old & new)
                    self.assertGreaterEqual(len(old - new), 1)
                    self.assertGreaterEqual(len(new - old), 1)
            previous = current
        self.assertEqual(previous, [lit(sprite, 0) for sprite in windows])

    def test_violet_gallery_preview_uses_the_complete_slow_cycle(self):
        from token_tv.board_preview import _sequence
        image, payload = city.render_city('violet-horizon', self.data, animated=True)
        sequence, duration = _sequence(rgb565_frame(image, anim=payload))
        self.assertEqual(duration, 500)
        self.assertEqual(sum(1 for _ in sequence), 64)

    def test_clouds_move_original_texture_without_darkening_the_sky(self):
        image = Image.new('RGB', (320, 240))
        for y in range(60, 135):
            for x in range(320):
                image.putpixel((x, y), (140 + round(25 * math.sin(x / 8 + y / 14)),
                                        60 + round(12 * math.cos(x / 10)),
                                        185 + round(25 * math.sin(x / 9 + y / 15))))
        for area in ((0, 80, 176, 44), (272, 74, 48, 54)):
            sprite = city._cloud_sprite(image, area)
            self.assertTrue(any(frame.getbbox() for frame in sprite['frames'][1:]))
            original = image.crop((area[0], area[1], area[0] + area[2], area[1] + area[3]))
            original = original.resize((area[2] // 2, area[3] // 2), Image.Resampling.BOX)
            for frame in sprite['frames']:
                for y in range(frame.height):
                    for x in range(frame.width):
                        pixel = frame.getpixel((x, y))
                        if pixel[3]:
                            self.assertGreaterEqual(sum(pixel[:3]), sum(original.getpixel((x, y))) - 3)

    def test_both_city_signs_use_readings_and_exhausted_codex_credits(self):
        from tests.test_board_credits import sample as credit_sample
        data = credit_sample(balance='137.5')
        for scene in city.FILES:
            with self.subTest(scene=scene), patch('time.time', return_value=1000), \
                    patch.object(city, 'sign', wraps=city.sign) as signs:
                city.render_city(scene, data)
                codex, claude = signs.call_args_list
                self.assertEqual(codex.args[1:4], ('codex', 0, '137.5'))
                self.assertEqual(claude.args[1], 'claude')
                self.assertIsNone(claude.args[3])

    def test_gallery_uses_current_snapshot_and_invalidates_stale_cache(self):
        control = BoardControl(None)
        first = control.archive_preview('neon-district', self.data)
        changed = deepcopy(self.data)
        changed['accounts']['codex']['windows'][0]['used_percent'] = 95
        second = control.archive_preview('neon-district', changed)
        self.assertNotEqual(first, second)
        changed['accounts']['codex']['status'] = 'stale'
        stale = control.archive_preview('neon-district', changed)
        changed['accounts']['codex']['windows'] = []
        changed['accounts']['codex']['status'] = 'ok'
        self.assertEqual(stale, control.archive_preview('neon-district', changed))
        with patch.object(city, 'sign', wraps=city.sign) as signs:
            BoardControl(None).archive_preview('violet-horizon')
        self.assertEqual([call.args[2] for call in signs.call_args_list], [None, None])

    def test_missing_private_image_is_an_explicit_fallback(self):
        city._cached_backdrop.cache_clear()
        (Path(self.temp.name) / city.FILES['violet-horizon']).unlink()
        image = city.render_city('violet-horizon', self.data)
        self.assertEqual(image.size, (320, 240))
        # An explanatory message is drawn in the otherwise dark empty backdrop.
        self.assertIsNotNone(ImageChops.difference(image.crop((20, 95, 300, 125)),
                                                   Image.new('RGB', (280, 30), '#101521')).getbbox())
        Image.new('RGB', (640, 480), (80, 30, 100)).save(Path(self.temp.name) / city.FILES['violet-horizon'])
        restored = city.render_city('violet-horizon', self.data)
        self.assertNotEqual(restored.getpixel((100, 50)), image.getpixel((100, 50)))

    def test_uninstalled_photo_is_not_offered_but_selected_slots_are_preserved(self):
        scene = 'violet-horizon'
        file = Path(self.temp.name) / city.FILES[scene]
        store = BoardScenes(Path(self.temp.name) / 'choices.json', threading.Event())
        store.select({'slot': 0, 'scene': scene})
        file.unlink()
        self.assertEqual(store.snapshot()[0], scene)
        self.assertIn(scene, [item['id'] for item in store.status()['scene_catalog']])
        fresh = BoardScenes(Path(self.temp.name) / 'other-choices.json', threading.Event())
        self.assertNotIn(scene, [item['id'] for item in fresh.status()['scene_catalog']])
        with self.assertRaises(ValueError):
            fresh.select({'slot': 0, 'scene': scene})

    def test_gallery_preview_refreshes_when_a_local_photo_is_replaced(self):
        scene = 'neon-district'
        path = Path(self.temp.name) / city.FILES[scene]
        control = BoardControl(None)
        original = control.archive_preview(scene)
        Image.new('RGB', (640, 480), (120, 30, 90)).save(path)
        replaced = control.archive_preview(scene)
        self.assertNotEqual(original, replaced)


if __name__ == '__main__':
    unittest.main()
