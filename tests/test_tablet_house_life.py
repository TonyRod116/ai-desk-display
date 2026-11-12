"""The visit is exercised with made-up sprites; no private artwork is read."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageChops
from scripts import prepare_tablet_house_life as life


class HouseLifeTests(unittest.TestCase):
    def test_recorded_water_repeats_eight_times_without_speeding_up_wildlife(self):
        # Faster water, but the bird keeps its complete 60-second visit.
        fps = life.FPS
        self.assertEqual(life.recorded_water_phase(0), 0)
        self.assertAlmostEqual(life.recorded_water_phase(fps * 3.75), .5)
        for seconds in (7.5, 15, 30, 45, 60):
            self.assertEqual(life.recorded_water_phase(fps * seconds), 0)
        self.assertGreater(life.recorded_water_phase(fps * 7.5 - 1), .99)
        self.assertEqual(life.RECORDED_SECONDS, 60)

    def test_visit_lands_and_leaves_with_no_loop_seam(self):
        self.assertIsNone(life.bird_state(0))
        self.assertIsNone(life.bird_state(1))
        incoming, perched, outgoing = (life.bird_state(p) for p in (.08, .18, .29))
        self.assertTrue(incoming['fly'])
        self.assertFalse(perched['fly'])
        self.assertTrue(outgoing['fly'])
        self.assertLess(perched['x'], incoming['x'])
        self.assertGreater(outgoing['x'], perched['x'])
        self.assertGreater(perched['y'], incoming['y'])
        self.assertGreater(perched['y'], outgoing['y'])

    def test_butterfly_is_intermittent(self):
        self.assertIsNone(life.butterfly_state(0))
        self.assertIsNone(life.butterfly_state(1))
        self.assertGreater(life.butterfly_state(.5)['alpha'], 0)

    def test_realistic_layers_keep_background_transparent_and_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('bird-0.png', 'bird-1.png', 'bird-2.png', 'bird-3.png', 'butterfly.png'):
                Image.new('RGBA', (16, 12), (120, 90, 40, 255)).save(Path(folder) / name)
            day = life.HouseLife(folder, 'day')
            self.assertIsNone(ImageChops.difference(day.frame(0), day.frame(1)).getbbox())
            self.assertIsNone(day.frame(0).getbbox())
            self.assertIsNotNone(day.frame(.18).getbbox())
            self.assertIsNotNone(day.frame(.5).getbbox())
            night = life.HouseLife(folder, 'night')
            self.assertIsNone(night.frame(.5).getbbox())


if __name__ == '__main__':
    unittest.main()
