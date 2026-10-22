"""Page transfers must service animation without weakening auth or stale data."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'firmware/board/tools/transfer_harness.py'
        spec = importlib.util.spec_from_file_location('transfers', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.directory = tempfile.TemporaryDirectory()
        cls.exe = module.build(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_transfers_keep_drawing_and_preserve_bytes_and_safety_gates(self):
        for mode in ('read', 'upload', 'stall', 'disconnect', 'unauthorized', 'info', 'firmware', 'stale'):
            with self.subTest(mode=mode):
                result = subprocess.run([str(self.exe), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_touch_is_serviced_during_slow_transfers(self):
        for mode in ('touch_read', 'touch_upload', 'touch_info', 'touch_mode', 'touch_connect'):
            with self.subTest(mode=mode):
                result = subprocess.run([str(self.exe), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
