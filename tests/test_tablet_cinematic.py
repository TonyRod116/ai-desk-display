"""The two portrait films use only supplied stills, with repeatable, closed loops."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from scripts import prepare_tablet_cinematic as film
from token_tv import tablet_server


class CinematicTests(unittest.TestCase):
    def setUp(self):
        # Fictional art only: no private files or readings in the tests.
        self.picture = Image.new('RGB', (448, 600), (35, 53, 69))

    def test_the_loop_has_motion_and_the_same_start_and_end(self):
        for name in film.NAMES:
            scene = film.Cinematic(name, self.picture)
            first, middle, end = scene.frame(0), scene.frame(.37), scene.frame(1)
            self.assertIsNone(ImageChops.difference(first, end).getbbox(), name)
            self.assertIsNotNone(ImageChops.difference(first, middle).getbbox(), name)
            self.assertEqual(first.size, film.SIZE)
            self.assertEqual(first.getpixel((5, 5)), self.picture.getpixel((0, 0)), 'the fixed room stays still')

    def test_preview_writes_only_the_requested_scene_to_an_explicit_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / 'fictional.png'
            self.picture.save(source)
            film.prepare('infinite-express', source, folder, previews=True)
            self.assertTrue((folder / 'scene-infinite-express.jpg').is_file())
            self.assertTrue((folder / 'thumb-infinite-express.webp').is_file())
            self.assertTrue((folder / 'preview-infinite-express-3.jpg').is_file())
            self.assertFalse((folder / 'scenes.json').exists())

    def test_both_scenes_are_explicit_allowlisted_assets(self):
        for name in film.NAMES:
            self.assertIn(name, tablet_server.SCENES)
            for filename in (f'scene-{name}.webm', f'scene-{name}.jpg', f'thumb-{name}.webp'):
                self.assertIn('/assets/' + filename, tablet_server._STATIC)
        self.assertNotIn('/assets/scene-unknown.webm', tablet_server._STATIC)


if __name__ == '__main__':
    unittest.main()
