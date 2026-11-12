import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from token_tv.tablet_offline import OfflineBundle, OfflineUnavailable


class OfflineManifestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'scene-surf.png').write_bytes(b'fictional-artwork')
        (self.root / 'thumb-surf.webp').write_bytes(b'fictional-thumbnail')
        (self.root / 'auth.json').write_text('not-an-asset')
        self.routes = {'/assets/scene-surf.png': ('@scene-surf.png', 'image/png'),
                       '/assets/thumb-surf.webp': ('@thumb-surf.webp', 'image/webp'),
                       '/app.js': ('app.js', 'text/javascript')}
        self.scenes = {'scenes': ['surf'], 'info': {'surf': {'media': {'url': '/assets/scene-surf.png'}}}}
        self.bundle = OfflineBundle(self.root, self.routes)

    def test_inventory_contains_only_referenced_fixed_art_and_catalogues(self):
        result = self.bundle.manifest(self.scenes, [])
        paths = {row['path'] for row in result['files']}
        self.assertEqual(paths, {'/assets/scene-surf.png', '/assets/thumb-surf.webp', '/api/scenes', '/api/photos'})
        self.assertEqual(result['total'], sum(row['size'] for row in result['files']))
        self.assertNotIn('auth.json', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(len(result['revision']), 64)
        catalog = next(row for row in result['files'] if row['path'] == '/api/scenes')
        expected = json.dumps(self.scenes, separators=(',', ':'), allow_nan=False).encode()
        self.assertEqual(catalog['sha256'], hashlib.sha256(expected).hexdigest())

    def test_an_art_update_changes_hash_and_revision(self):
        first = self.bundle.manifest(self.scenes, [])
        self.assertEqual(first, self.bundle.manifest(self.scenes, []))
        (self.root / 'scene-surf.png').write_bytes(b'changed-fictional-artwork')
        self.assertNotEqual(first['revision'], self.bundle.manifest(self.scenes, [])['revision'])

    def test_arbitrary_paths_code_and_missing_or_symlink_assets_are_refused(self):
        for route in ('/assets/../auth.json', '/assets/auth.json', '/assets/missing.png', '/app.js'):
            with self.subTest(route=route):
                value = {'scenes': [], 'info': {'image': '/assets/' + route if route == '/app.js' else route}}
                with self.assertRaises(OfflineUnavailable): self.bundle.manifest(value, [])
        target = self.root / 'scene-surf.png'
        target.unlink()
        target.symlink_to(self.root / 'auth.json')
        with self.assertRaises(OfflineUnavailable): self.bundle.manifest(self.scenes, [])

    def test_total_and_item_limits_are_enforced(self):
        with patch('token_tv.tablet_offline.MAX_TOTAL', 1):
            with self.assertRaises(OfflineUnavailable): self.bundle.manifest(self.scenes, [])
        with patch('token_tv.tablet_offline.MAX_FILES', 1):
            with self.assertRaises(OfflineUnavailable): self.bundle.manifest(self.scenes, [])
        with patch('token_tv.tablet_offline.MAX_FILE', 1):
            with self.assertRaises(OfflineUnavailable): self.bundle.manifest(self.scenes, [])

    def test_concurrent_inventory_fails_without_blocking_other_requests(self):
        with self.bundle._lock:
            with self.assertRaises(OfflineUnavailable): self.bundle.manifest(self.scenes, [])
