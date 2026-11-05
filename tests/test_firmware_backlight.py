"""Night mode on the board: PWM backlight, dimming after ten silent minutes, wake by touch, boot state."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class BacklightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('backlight_harness', ROOT / 'firmware/board/tools/backlight_harness.py')
        cls.harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.harness)
        cls.directory = tempfile.TemporaryDirectory()
        cls.exe = cls.harness.build(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_every_backlight_path(self):
        for mode in self.harness.MODES:
            with self.subTest(mode=mode):
                result = subprocess.run([str(self.exe), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, mode + '\n' + result.stdout + result.stderr)

    def test_boot_state_is_sane_and_the_capability_is_advertised(self):
        cpp = (ROOT / 'firmware/board/src/main.cpp').read_text()
        setup = cpp[cpp.index('\nvoid setup() {'):cpp.index('\nvoid loop() {')]
        # The saved level (default 100, clamped) exists before the panel is initialised, and the PWM starts straight after it.
        self.assertLess(setup.index('brightLevel = clampLevel(prefs.getInt("bright", 100));'), setup.index('tft.init();'))
        self.assertEqual(setup.index('startBacklight();') - setup.index('tft.init();'), len('tft.init();\n  '))
        info = cpp[cpp.index('static void handleInfo()'):cpp.index('// POST /ping answers')]
        for field in ('brightness', 'bright', 'bright_now'):
            self.assertIn('\\"%s\\":' % field, info)
        # Nothing else drives the pin: a second writer would fight the PWM.
        self.assertNotIn('digitalWrite(TFT_BL', cpp)
        self.assertNotIn('pinMode(TFT_BL', cpp)
