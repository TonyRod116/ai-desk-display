"""The train uses fictional pictures here; personal art never enters tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from scripts import prepare_tablet_express as express
from token_tv import tablet_server


class TrainJourneyTests(unittest.TestCase):
    def setUp(self):
        self.cabin = Image.new('RGB', express.SIZE, (66, 44, 32))
        draw = ImageDraw.Draw(self.cabin)
        draw.rectangle((170, 180, 500, 630), fill=(0, 255, 255))
        draw.rectangle((320, 540, 350, 630), fill=(160, 120, 60))  # lamp in front of the glass
        self.landscape = Image.new('RGB', (900, 500), (50, 100, 140))
        draw = ImageDraw.Draw(self.landscape)
        for x in range(0, 900, 100):
            draw.rectangle((x, 100, x + 60, 500), fill=(20 + x // 6, 110, 70))

    def test_window_moves_but_cabin_and_lamp_stay_in_front_and_loop_closes(self):
        for part in express.PARTS:
            with self.subTest(part=part):
                journey = express.TrainJourney(self.cabin, self.landscape, part)
                start, middle, end = (journey.frame(t) for t in (0, .25, 1))
                self.assertIsNone(ImageChops.difference(start, end).getbbox())
                self.assertIsNotNone(ImageChops.difference(start, middle).getbbox())
                self.assertEqual(start.getpixel((20, 20)), middle.getpixel((20, 20)))
                # The lamp remains in front of the enlarged window.
                self.assertEqual(start.getpixel((335, 730)), middle.getpixel((335, 730)))
                self.assertNotEqual(start.getpixel((250, 260)), (0, 255, 255))

    def test_window_is_larger_and_near_scenery_travels_faster(self):
        original = express.window_mask(self.cabin).getbbox()
        journey = express.TrainJourney(self.cabin, self.landscape, 'day')
        enlarged = journey.mask.getbbox()
        self.assertGreater(enlarged[2] - enlarged[0], (original[2] - original[0]) * 1.25)
        offsets = [journey.offsets(phase) for phase in (0, .1, .3, .6, .9)]
        self.assertTrue(all(a[0] < b[0] and a[1] < b[1] for a, b in zip(offsets, offsets[1:])))
        far0, near0 = offsets[0]
        far1, near1 = offsets[1]
        self.assertGreater(near1 - near0, 8 * (far1 - far0))
        self.assertEqual(journey.offsets(0), journey.offsets(1))

    def test_foreground_keeps_speed_and_repeats_far_less(self):
        plants = Image.new('RGB', (500, 300), (255, 0, 255))
        ImageDraw.Draw(plants).rectangle((120, 120, 230, 299), fill=(35, 100, 30))
        journey = express.TrainJourney(self.cabin, self.landscape, 'day', plants)
        old_width = journey.near.width / 8
        old_speed = 56 * old_width / 60
        new_speed = express.NEAR_CYCLES * journey.near.width / express.DEFAULT_SECONDS
        self.assertAlmostEqual(old_speed, new_speed)
        self.assertEqual(journey.near.width, old_width * 8)
        self.assertEqual(journey.offsets(0), journey.offsets(1))

    def test_distant_view_is_half_speed_without_slowing_the_near_trees(self):
        journey = express.TrainJourney(self.cabin, self.landscape, 'day')
        far, near = journey.offsets(60 / express.DEFAULT_SECONDS)
        self.assertAlmostEqual(far, journey.land.width * 60 / 240 / 2)
        self.assertAlmostEqual(near, journey.near.width * 28 * 60 / 240)

    def test_new_far_ridge_moves_slower_left_and_wraps_with_the_existing_layers(self):
        for part in express.PARTS:
            with self.subTest(part=part):
                journey = express.TrainJourney(self.cabin, self.landscape, part)
                mid, near = journey.offsets(.3)
                distant = journey.distant_offset(.3)
                self.assertGreater(distant, 0)
                self.assertLess(distant, mid * .5)
                self.assertGreater(near, mid)
                self.assertGreater(journey.distant_offset(.6), distant)
                self.assertEqual(journey.distant_offset(0), journey.distant_offset(1))
                self.assertIsNone(ImageChops.difference(journey.frame(0), journey.frame(1)).getbbox())
                self.assertEqual(journey.middle_fade.getpixel((0, 0)), 0)
                self.assertEqual(journey.middle_fade.getpixel((0, journey.height - 1)), 255)

    def test_distant_strip_blends_its_join_without_compressing_the_source(self):
        strip = Image.new('RGB', (1024, 3))
        for x in range(strip.width):
            ImageDraw.Draw(strip).line((x, 0, x, 2), fill=(x // 4 % 256, 40, 80))
        tile = express.distant_panorama(strip)
        self.assertEqual(tile.width, 224, 'half the previous 448-pixel circuit')
        self.assertLessEqual(abs(tile.getpixel((0, 1))[0] - tile.getpixel((tile.width - 1, 1))[0]), 1)
        self.assertEqual(express.scroll(tile, 0, 100).tobytes(), express.scroll(tile, tile.width, 100).tobytes())

    def test_extra_landscape_is_longer_and_wraps(self):
        extension = Image.new('RGB', self.landscape.size, (80, 150, 200))
        tile = express.extended_panorama(self.landscape, 500, extension)
        old = express.looping_panorama(self.landscape, 500)
        self.assertGreater(tile.width, old.width * 1.65)
        self.assertEqual(tile.getpixel((0, 200)), tile.getpixel((tile.width - 1, 200)))
        self.assertAlmostEqual((tile.width / express.DEFAULT_SECONDS) / (old.width / 60), .85 * 120 / express.DEFAULT_SECONDS, delta=.002)

    def test_carriage_jostle_is_subtle_smooth_and_loopable(self):
        frame_count = express.DEFAULT_SECONDS * 24
        positions = [express.carriage_jostle(i / frame_count) for i in range(frame_count + 1)]
        self.assertTrue(all(abs(x) < 1 and abs(y) < 1.5 for x, y in positions))
        self.assertTrue(any(abs(y) > .5 for _, y in positions))
        self.assertEqual(positions[0], positions[-1])
        self.assertLess(max(abs(b[1] - a[1]) for a, b in zip(positions, positions[1:])), .6)

    def test_trackside_motion_blur_wraps_and_preserves_transparency(self):
        tile = Image.new('RGBA', (32, 2), (0, 0, 0, 0))
        ImageDraw.Draw(tile).rectangle((0, 0, 3, 1), fill=(50, 160, 80, 255))
        blurred = express.trackside_blur(tile, distance=6)
        self.assertEqual(blurred.size, tile.size)
        self.assertGreater(blurred.getpixel((5, 0))[3], 0)
        self.assertEqual(blurred.getpixel((20, 0))[3], 0)
        self.assertEqual(express.scroll(blurred, 0, 32).tobytes(), express.scroll(blurred, 32, 32).tobytes())

    def test_scroll_reveals_pixels_to_the_right_so_scenery_moves_left(self):
        tile = Image.new('RGB', (100, 1))
        for x in range(100):
            tile.putpixel((x, 0), (x, 0, 0))
        self.assertEqual(express.scroll(tile, 10, 20).getpixel((5, 0)), express.scroll(tile, 15, 20).getpixel((0, 0)))
        self.assertEqual(express.scroll(tile, 0, 20).tobytes(), express.scroll(tile, 100, 20).tobytes())

    def test_scenery_joins_without_translucent_ghosts(self):
        source = Image.new('RGB', (4, 1))
        for x in range(4):
            source.putpixel((x, 0), (x * 60, 0, 0))
        tile = express.looping_panorama(source, 1)
        self.assertEqual(tile.getpixel((0, 0)), tile.getpixel((tile.width - 1, 0)))
        self.assertEqual(tile.getpixel((tile.width // 2 - 1, 0)), tile.getpixel((tile.width // 2, 0)))

    def test_a_missing_window_is_rejected(self):
        with self.assertRaises(ValueError):
            express.TrainJourney(Image.new('RGB', express.SIZE, 'black'), self.landscape, 'day')

    def test_generated_trackside_plants_have_a_clean_transparent_background(self):
        plants = Image.new('RGB', (500, 300), (255, 0, 255))
        ImageDraw.Draw(plants).rectangle((120, 120, 230, 299), fill=(35, 100, 30))
        keyed = express.key_foreground(plants, 'day')
        self.assertEqual(keyed.getpixel((20, 20))[3], 0)
        self.assertEqual(keyed.getpixel((160, 100))[3], 255)
        journey = express.TrainJourney(self.cabin, self.landscape, 'day', plants)
        self.assertIsNone(ImageChops.difference(journey.frame(0), journey.frame(1)).getbbox())
        self.assertIsNotNone(ImageChops.difference(journey.frame(0), journey.frame(.1)).getbbox())

    def test_previews_do_not_publish_or_write_a_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            cabin, view = out / 'cabin.png', out / 'view.png'
            self.cabin.save(cabin)
            self.landscape.save(view)
            express.prepare(cabin, {part: view for part in express.PARTS}, out, previews=True)
            self.assertTrue((out / 'preview-infinite-express-night-3.jpg').exists())
            self.assertFalse((out / 'scenes.json').exists())
            self.assertFalse((out / 'scene-infinite-express.webm').exists())

    def test_day_render_updates_the_default_for_older_clients(self):
        def fake_encode(frames, fps, destination, **_options):
            images = list(frames)
            destination.write_bytes(b'fictional video')
            return images[0].width, images[0].height, len(images)

        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            cabin, view = out / 'cabin.png', out / 'view.png'
            self.cabin.save(cabin)
            self.landscape.save(view)
            with patch.object(express.media, 'encode_webm', side_effect=fake_encode):
                express.prepare(cabin, {'day': view}, out, fps=1, seconds=1, parts=('day',))
            manifest = json.loads((out / 'scenes.json').read_text())['scenes']
            self.assertIn('infinite-express', manifest)
            self.assertEqual((out / 'scene-infinite-express.webm').read_bytes(),
                             (out / 'scene-infinite-express-day.webm').read_bytes())
            self.assertTrue((out / 'scene-infinite-express.jpg').exists())
            self.assertTrue((out / 'thumb-infinite-express.webp').exists())
            self.assertEqual(manifest['infinite-express']['media']['file'], 'scene-infinite-express.webm')

    def test_variant_urls_are_allowlisted_but_not_choices(self):
        for part in express.PARTS:
            name = 'infinite-express-' + part
            self.assertNotIn(name, tablet_server.SCENES)
            self.assertIn('/assets/scene-' + name + '.webm', tablet_server._STATIC)
        self.assertNotIn('/assets/scene-infinite-express-secret.webm', tablet_server._STATIC)


if __name__ == '__main__':
    unittest.main()
