"""Scenes are tested with invented pixels, never the owner's photographs."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from scripts import prepare_tablet_peaceful_house as scene
from token_tv import tablet_server


class HouseTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', scene.SIZE, (120, 150, 180))
        draw = ImageDraw.Draw(self.image)
        for y in range(0, scene.SIZE[1], 6):
            draw.line((0, y, scene.SIZE[0], y), fill=(30 + y % 150, 80, 100), width=3)

    def test_four_lights_and_seamless_motion_confined_to_water(self):
        for kind in scene.SCENES:
            for part in scene.PARTS:
                with self.subTest(kind=kind, part=part):
                    film = scene.PeacefulHouse(self.image, part, kind)
                    first, later, end = (film.frame(t) for t in (0, .125, 1))
                    difference = ImageChops.difference(first, later)
                    self.assertIsNotNone(difference.getbbox())
                    self.assertIsNone(ImageChops.difference(first, end).getbbox())
                    self.assertEqual(first.getpixel((10, 10)), later.getpixel((10, 10)))
                    allowed = ImageChops.lighter(film.mask, film.sky)
                    outside = allowed.point(lambda value: 255 if value == 0 else 0)
                    self.assertIsNone(ImageChops.multiply(difference.convert('L'), outside).getbbox())
            day = ImageStat.Stat(scene.PeacefulHouse(self.image, 'day', kind).base).mean
            night = ImageStat.Stat(scene.PeacefulHouse(self.image, 'night', kind).base).mean
            self.assertGreater(sum(day), sum(night) * 1.25)

    def test_previews_are_private_and_do_not_publish_a_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            source = out / 'fictional.png'
            self.image.save(source)
            for kind, name in scene.SCENES.items():
                scene.prepare(source, out, previews=True, kind=kind)
                self.assertTrue((out / f'preview-{name}-night-3.jpg').is_file())
            self.assertFalse((out / 'scenes.json').exists())

    def test_optional_generated_highlights_remain_inside_the_water(self):
        lights = Image.new('RGB', (100, 60), (0, 0, 0))
        ImageDraw.Draw(lights).line((10, 30, 90, 30), fill=(240, 250, 255), width=2)
        for kind in scene.SCENES:
            film = scene.PeacefulHouse(self.image, 'day', kind, lights)
            first, later = film.frame(0), film.frame(.125)
            self.assertIsNone(ImageChops.difference(first, film.frame(1)).getbbox())
            allowed = ImageChops.lighter(film.mask, film.sky)
            outside = allowed.point(lambda value: 255 if value == 0 else 0)
            self.assertIsNone(ImageChops.multiply(ImageChops.difference(first, later).convert('L'), outside).getbbox())

    def test_birds_are_in_the_open_sky_and_house_waves_cycle_faster(self):
        film = scene.PeacefulHouse(self.image, 'day', 'house')
        self.assertEqual(film.sky.getpixel((10, 10)), 0)
        self.assertEqual(film.sky.getpixel((300, 300)), 255)
        self.assertIsNone(ImageChops.difference(film.frame(0), film.frame(1)).getbbox())
        film.glints = []
        water = (250, 450, 400, 520)
        self.assertIsNone(ImageChops.difference(film.frame(0).crop(water), film.frame(1 / 3).crop(water)).getbbox())
        self.assertIsNotNone(ImageChops.difference(film.frame(0).crop(water), film.frame(1 / 6).crop(water)).getbbox())

    def test_night_lights_both_side_windows_and_moon_reflection(self):
        # A fictional room: cool water in both panes, warm wall, and a blue
        # sky behind the moon. Frames and the interior remain separate.
        source = Image.new('RGB', scene.SIZE, (170, 150, 125))
        draw = ImageDraw.Draw(source)
        for left, right in ((20, 76), (615, 668)):
            draw.rectangle((left, 214, right, 546), fill=(100, 160, 210))
        draw.rectangle((158, 197, 545, 705), fill=(100, 160, 210))
        mask = scene.house_window_mask(source)
        self.assertGreater(mask.getpixel((30, 440)), 200)
        self.assertGreater(mask.getpixel((620, 440)), 200)
        self.assertLess(mask.getpixel((140, 440)), 10)
        night = scene.PeacefulHouse(source, 'night', 'house')
        self.assertGreater(sum(night.base.getpixel((272, 277))), sum(night.base.getpixel((220, 277))))
        self.assertLess(sum(night.base.getpixel((30, 440))), sum(source.getpixel((30, 440))) * .72)
        self.assertGreater(night.base.getpixel((30, 440))[2], night.base.getpixel((30, 440))[0])
        self.assertIsNone(ImageChops.difference(night.frame(0), night.frame(1)).getbbox())
        reflection = ImageChops.difference(night.frame(0), night.frame(.2)).crop((240, 440, 310, 600))
        self.assertIsNotNone(reflection.getbbox())

    def test_breaker_advances_fades_and_recedes_without_a_loop_jump(self):
        early, _ = scene.shore_wave_state(.15 / 3)
        breaking, _ = scene.shore_wave_state(.68 / 3)
        retreat, _ = scene.shore_wave_state(.90 / 3)
        self.assertGreater(breaking, early)
        self.assertLess(retreat, breaking)
        self.assertAlmostEqual(scene.shore_wave_state(0)[1], 0)
        self.assertAlmostEqual(scene.shore_wave_state(1)[1], 0)
        self.assertEqual(scene.shore_wave_state(0), scene.shore_wave_state(1))

    def test_recorded_ocean_uses_real_frames_and_stays_inside_the_water(self):
        with tempfile.TemporaryDirectory() as directory:
            for i in range(16):
                image = Image.new('RGB', (100, 50), (20 + i * 4, 100, 150))
                ImageDraw.Draw(image).line((0, i * 3, 99, i * 3), fill=(245, 245, 245), width=2)
                image.save(Path(directory) / f'frame-{i:04}.jpg')
            ocean = scene.PhotographicOcean(directory, overlap=4)
            self.assertIsNone(ImageChops.difference(ocean.frame(0), ocean.frame(1)).getbbox())
            self.assertIsNotNone(ImageChops.difference(ocean.frame(0), ocean.frame(.5)).getbbox())
            midpoint = ocean.frame(3.5 / ocean.length).getpixel((0, 0))[0]
            self.assertGreater(midpoint, ocean.frame(3 / ocean.length).getpixel((0, 0))[0])
            self.assertLess(midpoint, ocean.frame(4 / ocean.length).getpixel((0, 0))[0])
            with Image.open(Path(directory) / 'frame-0003.jpg') as before, Image.open(Path(directory) / 'frame-0004.jpg') as after:
                self.assertIsNone(ImageChops.difference(ocean.frame((ocean.length - 1) / ocean.length), before.convert('RGB')).getbbox())
                self.assertIsNone(ImageChops.difference(ocean.frame(0), after.convert('RGB')).getbbox())
            for part in scene.PARTS:
                film = scene.PeacefulHouse(self.image, part, ocean=ocean)
                first, later = film.frame(0), film.frame(.5)
                self.assertIsNone(ImageChops.difference(first, film.frame(1)).getbbox())
                self.assertIsNotNone(ImageChops.difference(first, later).getbbox())
                allowed = ImageChops.lighter(film.ocean_mask, film.sky)
                if film.reflection is not None:
                    allowed = ImageChops.lighter(allowed, film.reflection.mask)
                outside = allowed.point(lambda value: 255 if value == 0 else 0)
                self.assertIsNone(ImageChops.multiply(ImageChops.difference(first, later).convert('L'), outside).getbbox())

    def test_recorded_ocean_requires_a_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                scene.PhotographicOcean(directory)

    def test_reflection_paths_use_the_actual_light_positions_and_only_visible_sea(self):
        for part in ('dusk','night'):
            effect = scene.SeaReflection(part)
            self.assertEqual(effect.point, scene.HOUSE_LIGHTS[part]['point'])
            field = Image.new('RGB', scene.SIZE, (30,65,90))
            first, later = effect.layer(field,0), effect.layer(field,.23)
            self.assertIsNotNone(ImageChops.difference(first,later).getbbox())
            self.assertIsNone(ImageChops.difference(first,effect.layer(field,1)).getbbox())
            outside = scene.water_mask().point(lambda v:255 if v==0 else 0)
            self.assertIsNone(ImageChops.multiply(first.getchannel('A'),outside).getbbox())
            alpha=first.getchannel('A'); lo,hi=round(.42*scene.SIZE[1]),round(.61*scene.SIZE[1])
            sums=[ImageStat.Stat(alpha.crop((x,lo,x+1,hi))).sum[0] for x in range(scene.SIZE[0])]
            centroid=sum(x*v for x,v in enumerate(sums))/sum(sums)
            self.assertAlmostEqual(centroid,scene.HOUSE_LIGHTS[part]['point'][0]*scene.SIZE[0],delta=10)

    def test_water_can_run_faster_without_speeding_up_distant_birds(self):
        film=scene.PeacefulHouse(self.image,'dusk')
        first=film.frame(.1,atmosphere_phase=.2)
        later=film.frame(.4,atmosphere_phase=.2)
        outside=film.mask.point(lambda v:255 if v==0 else 0)
        self.assertIsNone(ImageChops.multiply(ImageChops.difference(first,later).convert('L'),outside).getbbox())

    def test_recorded_ocean_does_not_repeat_frames_from_float_rounding(self):
        # Each frame is a different shade, so a duplicate reveals a missed
        # source frame when the encoded and source frame rates agree.
        with tempfile.TemporaryDirectory() as directory:
            for i in range(144):
                Image.new('RGB', (2, 2), (i, i, i)).save(Path(directory) / f'frame-{i:04}.jpg', quality=100)
            ocean = scene.PhotographicOcean(directory, overlap=8)
            before_fade = ocean.length - ocean.overlap
            values = [ocean.frame(i / ocean.length).getpixel((0, 0))[0] for i in range(before_fade)]
            self.assertEqual(values, list(range(8, 8 + before_fade)))

    def test_variants_are_allowlisted_but_not_extra_choices(self):
        for parent in scene.SCENES.values():
            self.assertIn(parent, tablet_server.SCENES)
            for part in scene.PARTS:
                name = parent + '-' + part
                self.assertNotIn(name, tablet_server.SCENES)
                self.assertIn('/assets/scene-' + name + '.webm', tablet_server._STATIC)
        self.assertNotIn('/assets/scene-neon-district-secret.webm', tablet_server._STATIC)


class NightLightingTests(unittest.TestCase):
    def test_mountain_night_does_not_draw_a_threshold_seam_across_the_slope(self):
        source = Image.new('RGB', scene.SIZE, (170, 184, 205))
        pen = ImageDraw.Draw(source)
        for x in range(220, 320):
            pen.line((x, 200, x, 240), fill=(168 + (x - 220) // 4, 184 + (x - 220) // 4, 205 + (x - 220) // 4))
        result = scene.night_mountain(source)
        deltas = [max(abs(a - b) for a, b in zip(result.getpixel((x, 220)), result.getpixel((x + 1, 220)))) for x in range(220, 319)]
        self.assertLessEqual(max(deltas), 3, 'a smooth mountain gradient stays smooth in moonlight')

    def test_mountain_night_has_a_moon_and_warm_lights_without_replacing_the_scene(self):
        # Fictional neutral interior with a blue sky in the upper window.
        source = Image.new('RGB', scene.SIZE, (170, 150, 130))
        ImageDraw.Draw(source).rectangle((140, 0, 365, 250), fill=(215, 232, 247))
        night = scene.grade(source, 'night', 'mountain')
        moon = night.getpixel((195, 116))
        nearby_sky = night.getpixel((230, 116))
        lamp = night.getpixel((168, 333))
        self.assertGreater(sum(moon), sum(nearby_sky) + 60)
        self.assertGreater(lamp[0], lamp[2] + 40)
        # Indoor wood stays visibly warmer than the sky; neither is blanked.
        room = night.getpixel((500, 900))
        self.assertGreater(room[0], room[2])
        self.assertGreater(sum(room), 100)
        self.assertGreater(nearby_sky[2], nearby_sky[0])

    def test_house_night_has_warm_interior_and_cool_exterior(self):
        source = Image.new('RGB', scene.SIZE, (180, 170, 155))
        ImageDraw.Draw(source).rectangle((158, 197, 545, 705), fill=(120, 170, 220))
        night = scene.grade(source, 'night', 'house')
        room = night.getpixel((350, 900))
        sea = night.getpixel((400, 500))
        self.assertGreater(room[0] - room[2], 40)
        self.assertGreater(sea[2] - sea[0], 20)
        self.assertGreater(sum(room), 260)


if __name__ == '__main__':
    unittest.main()
