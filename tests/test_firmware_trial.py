"""The board's self-check: trial builds, rollback to the previous image, and the watchdog's arming.

Compiles the real block of main.cpp (between the "build trial, rollback and watchdog" markers) under sanitizers and runs
simulated boots against a fake NVS, two fake OTA slots and fake reset reasons. See firmware/board/tools/trial_harness.py.
"""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_harness():
    spec = importlib.util.spec_from_file_location('trial_harness', ROOT / 'firmware/board/tools/trial_harness.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class BuildTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = load_harness()
        cls.directory = tempfile.TemporaryDirectory()
        cls.exe = cls.harness.build(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_mode(self, mode):
        result = subprocess.run([str(self.exe), mode], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, mode + '\n' + result.stdout + result.stderr)

    def test_every_path_of_the_trial_and_the_rollback(self):
        for mode in self.harness.MODES:
            with self.subTest(mode=mode):
                self.run_mode(mode)

    def test_the_watchdog_is_two_minutes_and_the_firmware_feeds_it_in_every_long_path(self):
        cpp = (ROOT / 'firmware/board/src/main.cpp').read_text()
        self.assertIn('static const uint32_t WATCHDOG_SECONDS = 120;', cpp)
        loop = cpp[cpp.index('\nvoid loop() {'):]
        self.assertTrue(loop.split('\n', 2)[2].lstrip().startswith('feedWatchdog();'), 'loop() feeds first')
        for name in ('static void servicePageAnimation()', 'static void handlePageUpload()', 'static void handleUpdateUpload()'):
            body = cpp[cpp.index(name):]
            body = body[:body.index('\n}\n')]
            self.assertIn('feedWatchdog();', body, name)
        # The setup portal waits for a person and must never be watched.
        portal = cpp[cpp.index('static void onPortal('):]
        self.assertIn('pauseWatchdog();', portal[:portal.index('\n}\n')])

    def test_info_reports_the_trial_the_build_and_the_watchdog(self):
        cpp = (ROOT / 'firmware/board/src/main.cpp').read_text()
        info = cpp[cpp.index('static void handleInfo()'):cpp.index('// POST /ping answers')]
        for field in ('trial', 'strikes', 'fallback', 'rolled', 'build', 'wdt'):
            self.assertIn('\\"%s\\":' % field, info)


class InfoTextTests(unittest.TestCase):
    """handleInfo() is one long concatenation; one missing comma would silently break every PC and the control room."""
    @staticmethod
    def top_level_parts(source):
        parts, depth, current, i, in_string = [], 0, '', 0, False
        while i < len(source):
            ch = source[i]
            if in_string:
                current += ch
                if ch == '\\':
                    current += source[i + 1]
                    i += 1
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
                current += ch
            elif ch in '([':
                depth += 1
                current += ch
            elif ch in ')]':
                depth -= 1
                current += ch
            elif ch == '+' and depth == 0:
                parts.append(current.strip())
                current = ''
            else:
                current += ch
            i += 1
        parts.append(current.strip())
        return parts

    def test_the_text_the_board_answers_with_is_valid_json_and_carries_every_field(self):
        cpp = (ROOT / 'firmware/board/src/main.cpp').read_text()
        body = cpp[cpp.index('static void handleInfo()'):cpp.index('// POST /ping answers')]
        statement = body[body.index('String body =') + len('String body ='):body.index('server.send(200, "application/json", body);')]
        pieces = [json.loads(part) if re.fullmatch(r'"(?:\\.|[^"\\])*"', part) else '0'
                  for part in self.top_level_parts(statement.rstrip().rstrip(';'))]
        data = json.loads(''.join(pieces))               # every expression stands in as the number 0
        for field in ('model', 'fw', 'pages', 'paired', 'up', 'rst', 'rssi', 'silent', 'srest', 'page', 'info', 'active', 'anim',
                      'anim_frames', 'free_heap', 'board_controls', 'touch_controls', 'selection_memory', 'clock_synced', 'trial',
                      'strikes', 'fallback', 'rolled', 'build', 'wdt', 'brightness', 'bright', 'bright_now', 'card', 'card_shown',
                      'card_age', 'card_bad'):
            self.assertIn(field, data)
