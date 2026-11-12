"""The public handheld demo uses only generated stand-ins, never cartridge art."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from scripts import prepare_game_handheld as handheld
from scripts import tablet_media, sample_tablet
from token_tv import tablet_server


class HandheldPrepareTests(unittest.TestCase):
    def test_scene_is_discoverable_and_does_not_overwrite_existing_art(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = handheld.prepare_assets(root)
            tablet_media.update_manifest('game-boy', entry, root)
            with Image.open(root / 'scene-game-boy.png') as image:
                self.assertEqual(image.size, (16, 16))
            info = tablet_server.scene_catalog(root)
            self.assertEqual(info['scenes'], ['game-boy'])
            self.assertEqual(info['info']['game-boy']['look'], 'game')
            self.assertNotIn('data', info['info']['game-boy'])
            with self.assertRaises(FileExistsError):
                handheld.prepare_assets(root)


    def test_fictional_tablet_demo_prepares_the_handheld_engine(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(tablet_server, 'SCENES', ('game-boy',)):
            sample_tablet.prepare_scenes(temp)
            catalog = tablet_server.scene_catalog(temp)
            self.assertEqual(catalog['scenes'], ['game-boy'])
            self.assertEqual(catalog['info']['game-boy']['look'], 'game')



if __name__ == '__main__':
    unittest.main()
