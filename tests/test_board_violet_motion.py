"""Violet's new traffic and reflections stay bounded and backwards compatible."""
import math
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from token_tv import board_anim, board_cyber_scenes as city
from token_tv.board_pages import rgb565_frame
from test_board_platform import sample


class VioletMotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        image = Image.new('RGB', (320, 240), (120, 50, 150))
        draw = ImageDraw.Draw(image)
        for y in range(218, 240):
            for x in range(320):
                # Fictional reflected buildings: fine columns and water bands.
                draw.point((x, y), fill=(30 + (x * 11 + y * 3) % 170,
                                          50 + (x * 5 + y * 9) % 150,
                                          90 + (x * 7 + y * 5) % 150))
        draw.polygon(((113, 62), (123, 48), (123, 59), (117, 63)), fill=(0, 15, 35))
        image.save(directory / city.FILES['violet-horizon'])
        self.patch = patch.object(city, 'ART', directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        city._cached_backdrop.cache_clear()
        self.addCleanup(city._cached_backdrop.cache_clear)

    def scene(self, extended):
        return city.render_city('violet-horizon', sample(), animated=True,
                                extended_anim=extended)

    def test_older_board_keeps_its_existing_four_effects(self):
        old_image, old_payload = self.scene(False)
        default_image, default_payload = city.render_city('violet-horizon', sample(), animated=True)
        self.assertEqual(len(board_anim.decode(old_payload)['sprites']), 4)
        self.assertEqual(old_payload, default_payload)
        self.assertEqual(old_image.tobytes(), default_image.tobytes())
        simple = {'x': 0, 'y': 0, 'frames': [Image.new('RGBA', (1, 1))],
                  'script': [(0, 0, 0)], 'step_ms': 125}
        with self.assertRaises(ValueError):
            board_anim.encode(sprites=[simple] * 5)

    def test_extended_scene_has_smooth_reflections_and_two_distinct_ship_journeys(self):
        _, payload = self.scene(True)
        sprites = board_anim.decode(payload)['sprites']
        self.assertEqual(len(sprites), 8)
        self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
        water, outgoing_a, outgoing_b, incoming = sprites[4:]
        self.assertEqual((water['x'], water['y'], water['w'], water['h']), (74, 218, 88, 11))
        self.assertEqual(len(water['frames']), 8)
        self.assertEqual(len({tuple(f) for f in water['frames']}), 8)
        self.assertEqual((len(water['script']), water['step_ms']), (16, 125))
        for ship in (outgoing_a, outgoing_b, incoming):
            self.assertEqual((len(ship['script']), ship['step_ms']), (128, 125))
            self.assertEqual(ship['script'][0][0], 0)  # starts off-screen/clear
            self.assertLessEqual(ship['w'], 96)
            self.assertLessEqual(ship['h'], 96)
        self.assertNotEqual(outgoing_a['frames'], incoming['frames'])
        self.assertEqual((incoming['w'], incoming['h'], len(incoming['frames'])), (32, 19, 7))

        def active(sprite):
            return [(i, sprite['x'] + dx, sprite['y'] + dy)
                    for i, (frame, dx, dy) in enumerate(sprite['script']) if frame]

        first, second, approach = map(active, (outgoing_a, outgoing_b, incoming))
        self.assertLess(first[0][1], 0)         # the outgoing ship enters from the left
        self.assertGreaterEqual(second[-1][1], 300)
        self.assertGreater(approach[0][1], 290) # the second comes from the distant right
        self.assertLessEqual(approach[-1][2] + incoming['h'] * 2, 0)  # completely above the camera
        self.assertLess(first[-1][1], second[0][1])
        self.assertLess(second[-1][0], approach[0][0])

        def visible_bounds(sprite, entry):
            index, x, y = entry
            frame = sprite['frames'][sprite['script'][index][0]]
            pixels = [(x + 2 * (i % sprite['w']), y + 2 * (i // sprite['w']))
                      for i, colour in enumerate(frame) if colour != board_anim.KEY]
            self.assertTrue(pixels)
            return (min(p[0] for p in pixels), min(p[1] for p in pixels),
                    max(p[0] for p in pixels) + 2, max(p[1] for p in pixels) + 2)

        # A scripted clear pose is only selected after the last lit pixel has
        # crossed the screen edge, and the first pose starts fully beyond it.
        self.assertLessEqual(visible_bounds(outgoing_a, first[0])[2], 0)
        self.assertGreaterEqual(visible_bounds(outgoing_b, second[-1])[0], 320)
        self.assertGreaterEqual(visible_bounds(incoming, approach[0])[0], 320)
        self.assertLessEqual(visible_bounds(incoming, approach[-1])[3], 0)
        # The most detailed pose must be visible in full before it exits.
        self.assertTrue(any(incoming['script'][entry[0]][0] == 6
                            and 0 <= visible_bounds(incoming, entry)[1]
                            and visible_bounds(incoming, entry)[3] <= 240
                            for entry in approach))
        self.assertEqual(math.lcm(*(len(s['script']) * s['step_ms'] for s in sprites)), 32000)

    def test_background_no_longer_leaves_the_original_ship_fixed_in_the_sky(self):
        old_image, _ = self.scene(False)
        new_image, _ = self.scene(True)
        self.assertNotEqual(old_image.crop((112, 47, 126, 65)).tobytes(),
                            new_image.crop((112, 47, 126, 65)).tobytes())
        self.assertEqual(old_image.crop((0, 140, 320, 218)).tobytes(),
                         new_image.crop((0, 140, 320, 218)).tobytes())
        self.assertNotEqual(old_image.crop((74, 218, 250, 240)).tobytes(),
                            new_image.crop((74, 218, 250, 240)).tobytes())

    def test_water_reflects_the_real_position_and_colours_of_buildings(self):
        image = Image.new('RGB', (320, 240), (12, 16, 30))
        draw = ImageDraw.Draw(image)
        draw.rectangle((90, 138, 110, 217), fill=(230, 45, 90))
        draw.rectangle((194, 138, 214, 217), fill=(35, 160, 245))
        before = image.copy()
        city._reflect_violet_city(image)
        pink = image.getpixel((100, 225))
        blue = image.getpixel((204, 225))
        gap = image.getpixel((150, 225))
        self.assertGreater(pink[0], blue[0] * 2)
        self.assertGreater(blue[2], pink[2])
        self.assertGreater(pink[0], gap[0] * 2)
        self.assertGreater(blue[2], gap[2] * 2)
        for box in ((0, 0, 320, 218), (0, 218, 74, 240), (250, 218, 320, 240)):
            self.assertIsNone(ImageChops.difference(image.crop(box), before.crop(box)).getbbox())

    def test_trimming_transparent_margins_preserves_every_visible_pixel(self):
        frames = [Image.new('RGBA', (8, 7)) for _ in range(2)]
        ImageDraw.Draw(frames[0]).rectangle((2, 1, 3, 3), fill=(250, 80, 160, 255))
        ImageDraw.Draw(frames[1]).rectangle((4, 2, 6, 5), fill=(80, 200, 250, 255))
        original = {'x': 18, 'y': 24, 'frames': frames,
                    'script': [(0, -3, 4), (1, 5, -2)], 'step_ms': 125}
        compact = city._trim_transparent(original)
        self.assertEqual((compact['x'], compact['y'], compact['frames'][0].size), (22, 26, (5, 5)))

        def shown(sprite, step):
            index, dx, dy = sprite['script'][step]
            frame = sprite['frames'][index]
            return {(sprite['x'] + dx + 2 * (i % frame.width),
                     sprite['y'] + dy + 2 * (i // frame.width), colour)
                    for i, colour in enumerate(board_anim.sprite_words(frame))
                    if colour != board_anim.KEY}

        for step in range(2):
            self.assertEqual(shown(original, step), shown(compact, step))

    @patch('time.time', return_value=2_000_000_000)
    def test_tower_lights_are_also_reflected_when_quota_changes(self, _):
        bright, _ = city.render_city('violet-horizon', sample(used=0),
                                     animated=True, extended_anim=True)
        dim, _ = city.render_city('violet-horizon', sample(used=100),
                                  animated=True, extended_anim=True)
        water_below_codex = (200, 218, 213, 240)
        self.assertIsNotNone(ImageChops.difference(bright.crop(water_below_codex),
                                                  dim.crop(water_below_codex)).getbbox())

    def test_skyline_uses_a_few_existing_lights_that_turn_on_and_off(self):
        image = Image.new('RGB', (320, 240), (18, 15, 32))
        draw = ImageDraw.Draw(image)
        points = [(20, 152), (38, 164), (58, 178), (82, 190)]
        for x, y in points:
            draw.rectangle((x, y, x + 1, y + 1), fill=(105, 190, 250))
        sprite = city._natural_violet_lights(image, (16, 148, 86, 52), offset=0)
        self.assertIsNotNone(sprite)
        self.assertEqual(sprite['step_ms'], 8000)
        frames = sprite['frames']
        positions = [((x - 16) // 2, (y - 148) // 2) for x, y in points]
        for frame in frames:
            self.assertEqual(frame.getchannel('A').histogram()[255], 4)
        for current, following in zip(frames, frames[1:] + frames[:1]):
            changes = [sum(following.getpixel(p)[:3]) - sum(current.getpixel(p)[:3]) for p in positions]
            self.assertEqual(sum(change > 0 for change in changes), 1)
            self.assertEqual(sum(change < 0 for change in changes), 1)
        other = city._natural_violet_lights(image, (16, 148, 86, 52), offset=1)

        def shown(effect, milliseconds):
            step = (milliseconds // effect['step_ms']) % len(effect['script'])
            return effect['frames'][effect['script'][step][0]].tobytes()

        previous = [shown(effect, 0) for effect in (sprite, other)]
        for milliseconds in range(4000, 32001, 4000):
            current = [shown(effect, milliseconds) for effect in (sprite, other)]
            self.assertEqual(sum(a != b for a, b in zip(previous, current)), 1)
            previous = current
        self.assertIsNone(city._natural_violet_lights(Image.new('RGB', image.size), (16, 148, 86, 52)))

    def test_detailed_scene_stays_within_board_limit_with_textured_clouds(self):
        image = Image.new('RGB', (320, 240), (120, 50, 150))
        pixels = image.load()
        for y in range(74, 130):
            for x in range(320):
                wave = round(25 * math.sin(x * .23 + y * .11))
                pixels[x, y] = (120 + wave, 60 + wave // 4, 180 + wave)
        city._reflect_violet_city(image)
        payload = city.motion('violet-horizon', image, extended_anim=True,
                              ship=city._lift_violet_ship(image))
        self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)

    def test_painted_contrail_is_lifted_with_the_craft(self):
        image = Image.new('RGB', (320, 240), (125, 35, 150))
        ImageDraw.Draw(image).line((0, 23, 120, 55), fill=(80, 195, 255), width=2)
        before = image.copy()
        city._lift_violet_ship(image)
        old = sum(before.getpixel((x, round(23 + x * .266))) == (80, 195, 255) for x in range(110))
        new = sum(image.getpixel((x, round(23 + x * .266))) == (80, 195, 255) for x in range(110))
        self.assertGreater(old, 40)
        self.assertLess(new, old // 4)
        self.assertEqual(image.getpixel((150, 50)), before.getpixel((150, 50)))

    def test_gallery_preview_keeps_the_whole_slow_cycle(self):
        from token_tv.board_preview import _sequence
        image, payload = self.scene(True)
        frame = rgb565_frame(image, anim=payload)
        sequence, duration = _sequence(frame)
        self.assertEqual(duration, 250)
        base = Image.frombytes('RGB', (320, 240), frame[8:8 + 320 * 240 * 2], 'raw', 'BGR;16')
        cards = [city.card_box('violet-horizon', provider) for provider in ('codex', 'claude')]
        protected = [(left, top, right + 1, bottom + 1) for left, top, right, bottom in cards]
        protected += [(0, 230, 34, 240), (253, 230, 320, 240)]
        count = 0
        for preview in sequence:
            for box in protected:
                self.assertIsNone(ImageChops.difference(base.crop(box), preview.crop(box)).getbbox(),
                                  f'animation overlaps a reading or navigation indicator: {box}')
            count += 1
        self.assertEqual(count, 128)

    def test_archive_receives_extended_motion_only_when_requested(self):
        from token_tv.board_scenes import render_archive
        for capable, count in ((False, 4), (True, 8)):
            with self.subTest(extended_anim=capable):
                _, payload = render_archive('violet-horizon', sample(), animated=True,
                                            extended_anim=capable)
                self.assertEqual(len(board_anim.decode(payload)['sprites']), count)

    @unittest.skipUnless(shutil.which('g++'), 'needs g++')
    def test_native_engine_keeps_overlapping_flight_paths_clean_through_the_full_loop(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'firmware/board/tools'))
        import anim_harness

        image, payload = self.scene(True)
        spec = board_anim.decode(payload)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            page = root / 'page.bin'
            page.write_bytes(rgb565_frame(image, anim=payload))
            result = subprocess.run([str(exe), str(page), temp, '32000', '500', 'precise'],
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('readAnim=1 sprites=8', result.stdout)
            self.assertLess(int(re.search(r'region=(\d+)', result.stdout).group(1)), 12000)
            for elapsed in range(0, 32001, 500):
                words = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
                # The generic animation engine throttles its real work to
                # 40 ms; a capture between ticks sees the preceding pose.
                drawn_at = elapsed // 40 * 40
                for sprite in spec['sprites']:
                    frame, dx, dy = sprite['script'][(drawn_at // sprite['step_ms']) % len(sprite['script'])]
                    for i, colour in enumerate(sprite['frames'][frame]):
                        if colour == board_anim.KEY:
                            continue
                        x = sprite['x'] + dx + 2 * (i % sprite['w'])
                        y = sprite['y'] + dy + 2 * (i // sprite['w'])
                        for yy in (y, y + 1):
                            for xx in (x, x + 1):
                                if 0 <= xx < 320 and 0 <= yy < 240:
                                    words[yy * 320 + xx] = colour
                expected = struct.pack('<76800H', *words)
                actual = (root / f'screen_{elapsed // 500}.bin').read_bytes()
                self.assertEqual(actual, expected, f'elapsed {elapsed} ms')


if __name__ == '__main__':
    unittest.main()
