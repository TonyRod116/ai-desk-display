"""The over-the-wifi update keeps its physical gate (token AND the connection screen) and feeds the watchdog."""
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class UpdateGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('update_harness', ROOT / 'firmware/board/tools/update_harness.py')
        cls.harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.harness)
        cls.directory = tempfile.TemporaryDirectory()
        cls.exe = cls.harness.build(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_gate_and_the_install_path(self):
        for mode in self.harness.MODES:
            with self.subTest(mode=mode):
                result = subprocess.run([str(self.exe), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, mode + '\n' + result.stdout + result.stderr)

    def test_the_gate_is_exactly_the_token_and_the_connection_screen(self):
        cpp = (ROOT / 'firmware/board/src/main.cpp').read_text()
        self.assertEqual(cpp.count('updateAllowed = authorized() && showingInfo;'), 1)
        # Nothing else may ever set the flag to anything but false.
        self.assertEqual([m for m in re.findall(r'updateAllowed\s*=\s*([^;]+);', cpp) if m != 'false'],
                         ['authorized() && showingInfo'])
