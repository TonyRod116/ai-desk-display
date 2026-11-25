"""Contract tests for the tablet's DEEP BLUE underwater scene preparation and server registration."""
import json
import stat
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts import prepare_game_underwater as prepare
from token_tv import tablet_server


class UnderwaterPrepTests(unittest.TestCase):
    def test_underwater_is_registered_in_tablet_server_scenes(self):
        self.assertIn('underwater', tablet_server.SCENES)
        self.assertIn('/game-underwater.js', tablet_server._STATIC)
        self.assertIn('/assets/scene-underwater.png', tablet_server._STATIC)
        self.assertIn('/assets/scene-underwater.json', tablet_server._STATIC)
        self.assertIn('/assets/thumb-underwater.webp', tablet_server._STATIC)

    def test_prepare_writes_private_atlas_and_valid_manifest_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            summary = prepare.write(directory, with_manifest=True)
            self.assertEqual(summary['size'], list(prepare.ATLAS_SIZE))
            self.assertEqual(summary['view'], list(prepare.VIEW))
            self.assertTrue(summary['manifest'])
            for name in ('scene-underwater.png', 'scene-underwater.json', 'thumb-underwater.webp', 'scenes.json'):
                path = directory / name
                self.assertTrue(path.is_file(), name)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, name)
            with Image.open(directory / 'scene-underwater.png') as atlas:
                self.assertEqual(atlas.size, prepare.ATLAS_SIZE)
                self.assertEqual(atlas.mode, 'RGBA')
            with Image.open(directory / 'thumb-underwater.webp') as thumb:
                self.assertEqual(thumb.size, (240, 160))
            catalog = tablet_server.scene_catalog(directory)
            self.assertIn('underwater', catalog['scenes'])
            info = catalog['info']['underwater']
            self.assertEqual(info['look'], 'game')
            self.assertEqual(info['media']['url'], '/assets/scene-underwater.png')
            self.assertEqual(info['data'], '/assets/scene-underwater.json')
            data = json.loads((directory / 'scene-underwater.json').read_text(encoding='utf-8'))
            self.assertEqual((data['version'], data['scene'], data['size']), (3, 'underwater', list(prepare.ATLAS_SIZE)))
            for key in ('bg', 'fg', 'caustic_mask', 'room_left_lit', 'room_right_lit', 'occ_left', 'occ_right', 'diver_0_r', 'diver_11_r', 'diver_0_l', 'whale_0_r', 'whale_7_r', 'manta_0_r', 'shark_0_r', 'dolphin_0_r', 'dolphin_9_r', 'turtle_0_r', 'turtle_9_r', 'octo_0', 'octo_9', 'jelly_pink_0', 'jelly_pink_7', 'jelly_cyan_0', 'chest_0', 'chest_4', 'clam_0', 'clam_4', 'fish_teal_0_r', 'fish_teal_5_r'):
                self.assertIn(key, data['frames'], key)


if __name__ == '__main__':
    unittest.main()
