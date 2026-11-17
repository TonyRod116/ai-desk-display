"""Public flight demo fixtures are generated from code, without cartridge art."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from scripts import prepare_game_blue_lightning_demo as flight
from scripts import sample_tablet, tablet_media
from token_tv import tablet_server


class FlightDemoTests(unittest.TestCase):
    def test_demo_prepares_discoverable_game_and_preserves_existing_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = flight.prepare_assets(root)
            tablet_media.update_manifest('blue-lightning', entry, root)
            catalogue = tablet_server.scene_catalog(root)
            self.assertIn('blue-lightning', catalogue['scenes'])
            self.assertEqual(catalogue['info']['blue-lightning']['look'], 'game')
            data = json.loads((root / 'scene-blue-lightning.json').read_text())
            self.assertEqual(data['asset_origin'], 'procedural_demo')
            self.assertEqual(data['atlas_sha256'], hashlib.sha256((root / 'scene-blue-lightning.png').read_bytes()).hexdigest())
            with Image.open(root / 'scene-blue-lightning.png') as atlas:
                self.assertEqual(list(atlas.size), data['size'])
                for name, (x, y, w, h) in data['frames'].items():
                    self.assertTrue(0 <= x < x + w <= atlas.width)
                    self.assertTrue(0 <= y < y + h <= atlas.height)
                    self.assertEqual(len(data['anchors'][name]), 2)
            before = (root / 'scene-blue-lightning.png').read_bytes()
            with self.assertRaises(FileExistsError):
                flight.prepare_assets(root)
            self.assertEqual((root / 'scene-blue-lightning.png').read_bytes(), before)

    def test_normal_sample_mode_includes_the_fictional_flight_scene(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(tablet_server, 'SCENES', ('blue-lightning',)):
            sample_tablet.prepare_scenes(temp)
            catalogue = tablet_server.scene_catalog(temp)
            self.assertEqual(catalogue['scenes'], ['blue-lightning'])
            self.assertEqual(catalogue['info']['blue-lightning']['look'], 'game')
            self.assertIn('/game-blue-lightning.js', tablet_server._STATIC)
            html = (tablet_server.WEB / 'index.html').read_text()
            self.assertIn('src="/game-blue-lightning.js"', html)
            self.assertIn("'blue-lightning':['Blue Lightning','Blue Lightning']", (tablet_server.WEB / 'app.js').read_text())

    def test_scene_publication_rejects_invalid_catalogues_before_creating_assets(self):
        for raw in ('{bad json', '{"version":2,"version":2,"scenes":{}}', '{"version":1,"scenes":{}}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'scenes.json').write_text(raw)
                with self.assertRaises(ValueError):
                    flight.prepare_scene(root)
                self.assertEqual((root / 'scenes.json').read_text(), raw)
                self.assertFalse(list(root.glob('scene-blue-lightning.*')))

    def test_scene_publication_preserves_other_entries_and_refuses_an_existing_flight(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unrelated = {'version': 2, 'scenes': {'fictional-scene': {'preserve': [1, 2, 3]}}}
            (root / 'scenes.json').write_text(json.dumps(unrelated))
            flight.prepare_scene(root)
            result = json.loads((root / 'scenes.json').read_text())
            self.assertEqual(result['scenes']['fictional-scene'], unrelated['scenes']['fictional-scene'])
            for path in root.glob('scene-blue-lightning.*'):
                path.unlink()
            (root / 'thumb-blue-lightning.webp').unlink()
            before = (root / 'scenes.json').read_bytes()
            with self.assertRaises(FileExistsError):
                flight.prepare_scene(root)
            self.assertEqual((root / 'scenes.json').read_bytes(), before)
            self.assertFalse(list(root.glob('scene-blue-lightning.*')))

    def test_two_scene_preparations_share_one_catalogue_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def prepare(_index):
                try:
                    flight.prepare_scene(root)
                    return 'prepared'
                except FileExistsError:
                    return 'already_exists'
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertCountEqual(list(pool.map(prepare, range(2))), ['prepared', 'already_exists'])
            self.assertEqual(json.loads((root / 'scenes.json').read_text())['scenes']['blue-lightning']['look'], 'game')
            self.assertEqual(len(list(root.glob('scene-blue-lightning.*'))), 2)

    def test_failed_catalogue_write_removes_only_its_new_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = '{"version":2,"scenes":{"unrelated":{"keep":true}}}'
            (root / 'scenes.json').write_text(raw)
            original_write = tablet_media._write_atomically
            def fail_catalogue(path, writer, limit):
                if Path(path).name == 'scenes.json':
                    raise OSError('fictional catalogue failure')
                return original_write(path, writer, limit)
            with patch.object(tablet_media, '_write_atomically', side_effect=fail_catalogue):
                with self.assertRaises(OSError):
                    flight.prepare_scene(root)
            self.assertEqual((root / 'scenes.json').read_text(), raw)
            self.assertFalse(list(root.glob('scene-blue-lightning.*')))
            self.assertFalse(list(root.glob('thumb-blue-lightning.*')))


if __name__ == '__main__':
    unittest.main()
