import hashlib
import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

from token_tv.local_usage import atomic_json


class PrepareClaudeBankTests(unittest.TestCase):
    def prepared(self, root):
        from scripts.prepare_claude_bank import prepare
        config_path, pin_path = root/'config.json', root/'pin.json'
        config = {'local_only': True, 'automatic_claude_resets': True, 'accounts': [
            {'key': 'claude', 'alias': 'Claude', 'provider': 'claude', 'source_home': '/synthetic/claude', 'email': 'demo@example.invalid'}]}
        atomic_json(config_path, config)
        atomic_json(pin_path, {'account_hash': hashlib.sha256(b'demo@example.invalid').hexdigest(),
                               'organization_id': '11111111-1111-1111-1111-111111111111'})
        prepare(config_path, pin_path, root/'extension')
        return root/'extension', root/'claude-bank-bridge.json', config_path, pin_path

    def test_rerunning_the_preparer_keeps_the_secret_unless_the_pairing_changed(self):
        from scripts.prepare_claude_bank import prepare
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extension, bridge, config_path, pin_path = self.prepared(root)
            first = json.loads(bridge.read_text())
            pairing = (extension/'pairing.js').read_text()
            prepare(config_path, pin_path, extension)
            self.assertEqual(json.loads(bridge.read_text()), first)
            self.assertEqual((extension/'pairing.js').read_text(), pairing)
            bridge.write_text('not json')                       # the one way a plain re-run loses it: an unreadable bridge file
            prepare(config_path, pin_path, extension)
            self.assertNotEqual(json.loads(bridge.read_text())['secret'], first['secret'])

    def test_code_only_sync_updates_the_extension_and_never_touches_the_pairing(self):
        from scripts.prepare_claude_bank import CODE, sync_code
        source = Path(__file__).resolve().parents[1]/'integrations/claude-bank'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extension, bridge, _, _ = self.prepared(root)
            (extension/'reader.mjs').write_text('// the code Arc has been running\n')
            (extension/'manifest.json').write_text('{"version": "1.0.0"}')
            before = {name: ((extension/name).read_bytes(), (extension/name).stat().st_mtime_ns) for name in ('pairing.js',)}
            before['bridge'] = (bridge.read_bytes(), bridge.stat().st_mtime_ns)
            secret = json.loads(bridge.read_text())['secret']
            os.chmod(extension/'pairing.js', 0)                 # even unreadable: it is never opened
            try:
                changed = sync_code(extension)
            finally:
                os.chmod(extension/'pairing.js', 0o600)
            self.assertEqual(sorted(changed), ['manifest.json', 'reader.mjs'])
            for name in CODE:
                self.assertEqual((extension/name).read_bytes(), (source/name).read_bytes(), name)
                self.assertEqual((extension/name).stat().st_mode & 0o777, 0o600, name)
            self.assertEqual(((extension/'pairing.js').read_bytes(), (extension/'pairing.js').stat().st_mtime_ns), before['pairing.js'])
            self.assertEqual((bridge.read_bytes(), bridge.stat().st_mtime_ns), before['bridge'])
            self.assertIn(secret, (extension/'pairing.js').read_text())
            self.assertEqual(sync_code(extension), [])
            self.assertEqual(sorted(path.name for path in extension.iterdir()), sorted(CODE + ('pairing.js',)), 'no stray files')
            self.assertEqual(json.loads((extension/'manifest.json').read_text())['version'], '1.1.0')

    def test_code_only_sync_refuses_anything_that_is_not_a_prepared_copy(self):
        from scripts.prepare_claude_bank import sync_code
        source = Path(__file__).resolve().parents[1]/'integrations/claude-bank'
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory)/'empty'
            empty.mkdir()
            for destination in (empty, Path(directory)/'missing', source):
                with self.subTest(destination=destination.name), self.assertRaises(ValueError):
                    sync_code(destination)
            self.assertEqual(list(empty.iterdir()), [])

    def test_code_only_sync_runs_from_the_command_line_without_config_or_pin_and_prints_no_secret(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            extension, bridge, _, _ = self.prepared(Path(directory))
            (extension/'background.js').write_text('// old\n')
            secret = json.loads(bridge.read_text())['secret']
            env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(root), 'HOME': directory}   # no private config in reach
            run = lambda *args: subprocess.run([sys.executable, '-B', str(root/'scripts/prepare_claude_bank.py'), *args],
                                               env=env, cwd=directory, capture_output=True, text=True)
            done = run('--sync-code', '--destination', str(extension))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('background.js', done.stdout); self.assertIn('Reload the extension', done.stdout)
            self.assertNotIn(secret, done.stdout + done.stderr)
            self.assertIn('already current', run('--sync-code', '--destination', str(extension)).stdout)
            refused = run('--sync-code', '--config', 'x', '--destination', str(extension))
            self.assertNotEqual(refused.returncode, 0)
            missing = run('--sync-code', '--destination', directory + '/nowhere')
            self.assertNotEqual(missing.returncode, 0); self.assertIn('Not updated', missing.stderr)
            self.assertNotEqual(run('--destination', str(extension)).returncode, 0)      # a full preparation still needs its inputs


if __name__ == '__main__':
    unittest.main()
