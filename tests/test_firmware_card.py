"""The board's details card: the firmware's real parser, formatting and drawing, fed by the PC's real builder.

The card's block of main.cpp is compiled under the sanitizers. Drawing uses TFT_eSPI's own font tables when the PlatformIO
library folder exists (it does after any build of the firmware); set TOKEN_TV_CARD_PNG_DIR to keep the captures.
"""
import importlib.util
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from token_tv.board_card import card_payload
from token_tv.sample import snapshot

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000
D, H = 86400, 3600


def load_harness():
    spec = importlib.util.spec_from_file_location('card_harness', ROOT / 'firmware/board/tools/card_harness.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fictional(codex_used=38, claude_used=25, session_used=60, week_codex=3 * D + 4 * H, week_claude=2 * D + 9 * H, session=5400):
    data = snapshot(NOW, [('codex_a', 'CODEX A', 'codex', [('WEEK', codex_used, week_codex)]),
                          ('claude_a', 'CLAUDE A', 'claude', [('WEEK', claude_used, week_claude), ('5H', session_used, session)])])
    data['accounts']['codex_a'].update(fetched_at=NOW - 95, banked_resets={'available': 2})
    data['accounts']['claude_a'].update(fetched_at=NOW - 120, banked_resets={'available': 0})
    return data


def rgb565(colour):
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class CardParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = load_harness()
        cls.directory = tempfile.TemporaryDirectory()
        cls.exe = cls.harness.build(cls.directory.name, fonts=False)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_exe(self, *args, stdin=None):
        result = subprocess.run([str(self.exe), *args], capture_output=True, text=True, input=stdin)
        self.assertEqual(result.returncode, 0, ' '.join(args) + '\n' + result.stdout + result.stderr)
        return result.stdout

    def parse(self, line):
        out = self.run_exe('parse', line).splitlines()
        if out[0] == 'REJECTED':
            return None
        return out[1:3]

    def test_a_good_line_is_taken_exactly(self):
        sides = self.parse('1,xw62,xr259000,xa95,xs2,lw75,lr259000,lh40,lk5400,la120,ls-,leSign-in needed')
        self.assertEqual(sides[0], 'present=1 week=62 hours=-1 weekReset=259000 hoursReset=-1 age=95 saved=2 old=0 why=[]')
        self.assertEqual(sides[1], 'present=1 week=75 hours=40 weekReset=259000 hoursReset=5400 age=120 saved=-1 old=0 why=[Sign-in needed]')
        edge = self.parse('1,xw<,xs0o,lw0,ls99,lh100,lk99999,lr9999999,la99999')
        self.assertEqual(edge[0], 'present=1 week=101 hours=-1 weekReset=-1 hoursReset=-1 age=-1 saved=0 old=1 why=[]')
        self.assertEqual(edge[1], 'present=1 week=0 hours=100 weekReset=9999999 hoursReset=99999 age=99999 saved=99 old=0 why=[]')
        self.assertEqual(self.parse('1,lw-')[0], 'present=0 week=-1 hours=-1 weekReset=-1 hoursReset=-1 age=-1 saved=-1 old=0 why=[]')

    def test_any_malformed_line_is_refused_whole(self):
        bad = ['', '1', '1,', '1,x', '1,xw', '2,xw5', '11,xw5', '1xw5', ' 1,xw5', '0,xw5', '1,,xw5', '1,xw5,', ',1,xw5',
               '1,xw101', '1,xw100x', '1,xw-5', '1,xw+5', '1,xw5.0', '1,xw1e2', '1,xw 5', '1,xw5,xw6', '1,xw5,xw5',
               '1,zw5', '1,XW5', '1,xW5', '1,xq5', '1,x5', '1,w5', '1,xr10000000', '1,xr-1', '1,xk100000', '1,xa100000',
               '1,xr123456789', '1,xs100', '1,xs2oo', '1,xs-o', '1,xso', '1,xs2x', '1,xh101', '1,xe', '1,xeABCDEFGHIJKLMNOPQR',
               '1,xeSign;in', '1,xeNo 100%', '1,xe<b>', '1,xeA,B', '1,xe\x01', '1,xe\xc3\xa9', '1,xw5\t', '1,xw5\n',
               '1,' + 'xw5,' * 40, '1,xw' + '9' * 300, '1,xw5' + ' ' * 300]
        for line in bad:
            with self.subTest(line=line[:40]):
                self.assertIsNone(self.parse(line))

    def test_a_refused_line_changes_nothing_and_never_breaks_the_heartbeat(self):
        self.run_exe('keeps_the_previous_card')

    def test_the_words_for_numbers_and_the_countdowns(self):
        self.run_exe('formats')

    def test_twenty_thousand_mutated_lines_stay_inside_the_bounds_without_a_crash(self):
        self.assertIn('accepted', self.run_exe('fuzz'))

    def test_everything_the_pc_builds_is_taken_and_everything_it_cannot_is_not_sent(self):
        rng = random.Random(11)
        lines = []
        for _ in range(400):
            codex = rng.choice([None, [], [('WEEK', rng.choice([0, 0.3, 37.5, 99.6, 100]), rng.randrange(-100, 10 * D))]])
            claude = rng.choice([None, [], [('WEEK', rng.choice([0, 12, 100]), rng.randrange(-100, 6 * D)),
                                            ('5H', rng.choice([0, 40, 100]), rng.randrange(-100, 5 * H))]])
            accounts = [(k, a, p, w) for k, a, p, w in (('codex_a', 'CODEX A', 'codex', codex), ('claude_a', 'CLAUDE A', 'claude', claude))
                        if w is not None]
            data = snapshot(NOW, accounts or [('codex_a', 'CODEX A', 'codex', [])])
            for row in data['accounts'].values():
                row['fetched_at'] = NOW - rng.choice([0, 30, 200, 470, 9999])
                row['banked_resets'] = rng.choice([{}, {'available': rng.randrange(0, 5)}, {'available': None, 'last_known': 1}])
                if rng.random() < 0.4:
                    row['reader'] = {'state': rng.choice(['ok', 'failing']), 'reason': rng.choice(
                        ['login_required', 'org_blocked', 'rate_limited', 'unknown', 'never heard of it', None, 5]),
                        'since': NOW, 'retry_at': None}
            line = card_payload(data, NOW)
            self.assertTrue(line is None or len(line) <= 200)
            if line is not None:
                lines.append(line)
        self.assertGreater(len(lines), 300)
        answers = self.run_exe('lines', stdin='\n'.join(lines) + '\n').split()
        self.assertEqual(answers, ['OK'] * len(lines))


@unittest.skipUnless(shutil.which('g++') and load_harness().fonts_available(),
                     'needs g++ and the TFT_eSPI fonts that a firmware build installs')
class CardDrawingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = load_harness()
        cls.directory = tempfile.TemporaryDirectory()
        cls.exe = cls.harness.build(cls.directory.name, fonts=True)
        cls.keep = os.environ.get('TOKEN_TV_CARD_PNG_DIR')

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def draw(self, name, snap, elapsed=0):
        line = '-' if snap is None else card_payload(snap, NOW)
        raw = Path(self.directory.name) / f'{name}.rgb565'
        result = subprocess.run([str(self.exe), 'render', str(raw), str(elapsed), line], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, name + '\n' + result.stdout + result.stderr)  # 3: off the margins, 4: overlap
        strings = [row.split(' ', 3) for row in result.stdout.splitlines() if ' font' in row]
        texts = [row[3][1:-1] for row in strings]
        if self.keep:
            from PIL import Image
            image = Image.frombytes('RGB', (320, 240), raw.read_bytes(), 'raw', 'BGR;16')
            image.save(Path(self.keep) / f'card-{name}.png')
        return texts, {row[3][1:-1]: int(row[2], 16) for row in strings}

    def test_the_normal_card_has_every_exact_number_in_the_providers_own_colours(self):
        texts, colours = self.draw('normal', fictional())
        for expected in ('CODEX', '62%', 'week left, resets in 3d 4h', '2 saved resets, updated 1 min ago', 'CLAUDE', '75%',
                         'week left, resets in 2d 9h', '5 hours 40% left, resets in 1h 30m', '0 saved resets, updated 2 min ago',
                         'Tap to close'):
            self.assertIn(expected, texts)
        self.assertEqual(colours['CODEX'], rgb565('#ffd23f'))          # the same yellow and stone as every scene
        self.assertEqual(colours['62%'], rgb565('#ffd23f'))
        self.assertEqual(colours['CLAUDE'], rgb565('#cfc6b4'))
        self.assertEqual(colours['75%'], rgb565('#cfc6b4'))

    def test_the_countdowns_and_the_age_run_from_the_moment_the_line_arrived(self):
        texts, _ = self.draw('later', fictional(), elapsed=125)
        for expected in ('week left, resets in 3d 3h', '5 hours 40% left, resets in 1h 27m', '2 saved resets, updated 3 min ago',
                         '0 saved resets, updated 4 min ago'):
            self.assertIn(expected, texts)

    def test_unknown_is_never_zero_and_the_reason_is_in_words(self):
        unknown = snapshot(NOW, [('codex_a', 'CODEX A', 'codex', []), ('claude_a', 'CLAUDE A', 'claude', [])])
        for row in unknown['accounts'].values():
            row['status'], row['fetched_at'] = 'quota_unavailable', 0
        texts, _ = self.draw('unknown', unknown)
        self.assertEqual(texts.count('--'), 2)
        self.assertEqual(texts.count('No reading'), 2)
        self.assertFalse([t for t in texts if '0%' in t or t == '0'])
        self.assertFalse([t for t in texts if 'saved' in t or 'updated' in t])    # nothing known: nothing said about it
        failing = fictional()
        claude = failing['accounts']['claude_a']
        claude.update(windows=[], status='quota_unavailable',
                      reader={'state': 'failing', 'reason': 'login_required', 'since': NOW - 60, 'retry_at': None},
                      banked_resets={'available': None, 'last_known': 1})
        texts, colours = self.draw('failing', failing)
        self.assertIn('Sign-in needed', texts)
        self.assertIn('1 saved reset (old)', texts)
        self.assertEqual(texts.count('--'), 1)                           # only Claude's week is missing; Codex keeps its number
        self.assertIn('62%', texts)

    def test_a_small_positive_reading_is_not_shown_as_zero_and_a_real_zero_is(self):
        texts, _ = self.draw('almost-empty', fictional(codex_used=99.5, claude_used=100, session_used=100, week_codex=2400,
                                                       week_claude=D + 100, session=250))
        self.assertIn('<1%', texts)
        self.assertIn('0%', texts)
        self.assertIn('5 hours 0% left, resets in 4 min', texts)
        self.assertIn('week left, resets in 40 min', texts)

    def test_every_colour_follows_the_panels_red_blue_option(self):
        from PIL import Image
        swapped = self.harness.build(self.directory.name, fonts=True, swap_rb=True)
        colours = {}
        for name, exe in (('plain', self.exe), ('swapped', swapped)):
            raw = Path(self.directory.name) / f'{name}.rgb565'
            line = card_payload(fictional(), NOW)
            result = subprocess.run([str(exe), 'render', str(raw), '0', line], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            image = Image.frombytes('RGB', (320, 240), raw.read_bytes(), 'raw', 'BGR;16')
            colours[name] = {c for _, c in image.getcolors(1 << 16)}
        swap = lambda c: (c[2], c[1], c[0])                                        # noqa: E731
        self.assertEqual(colours['swapped'], {swap(c) for c in colours['plain']})
        self.assertGreater(len(colours['plain']), 5)
        self.assertNotEqual(colours['swapped'], colours['plain'])                  # the test can tell the two apart

    def test_before_any_line_arrives_it_says_so_honestly(self):
        texts, _ = self.draw('no-details-yet', None)
        self.assertIn('No details yet', texts)
        self.assertFalse([t for t in texts if '%' in t])

    def test_a_line_that_stopped_coming_is_not_shown_as_current_after_ten_minutes(self):
        texts, _ = self.draw('ten-minutes', fictional(), elapsed=600)
        self.assertIn('62%', texts)
        texts, _ = self.draw('eleven-minutes', fictional(), elapsed=601)
        self.assertIn('Details out of date', texts)
        self.assertFalse([t for t in texts if '%' in t])
        self.assertNotIn('No details yet', texts)

    def test_the_longest_card_still_fits_between_the_margins(self):
        data = fictional()
        data['accounts']['claude_a']['reader'] = {'state': 'failing', 'reason': 'rate_limited', 'since': NOW, 'retry_at': None}
        for key in ('codex_a', 'claude_a'):
            data['accounts'][key]['banked_resets'] = {'available': None, 'last_known': 99}
            data['accounts'][key]['fetched_at'] = NOW - 86000        # the board takes ages up to 99999 s: "updated 23h 54m ago" is too wide for one line
        for elapsed in (0, 125, 400, 600):
            with self.subTest(elapsed=elapsed):
                texts, _ = self.draw('longest', data, elapsed=elapsed)          # the harness refuses text outside 12..308 px or overlapping
                self.assertIn('Too many requests', texts)
                self.assertTrue(any(t.startswith('99 saved resets (old)') for t in texts))

    def test_when_everything_is_wrong_at_once_the_card_gives_up_the_hint_before_it_gives_up_a_line(self):
        data = fictional()
        for key, reason in (('codex_a', 'org_blocked'), ('claude_a', 'rate_limited')):
            data['accounts'][key]['reader'] = {'state': 'failing', 'reason': reason, 'since': NOW, 'retry_at': None}
            data['accounts'][key]['banked_resets'] = {'available': None, 'last_known': 99}
        short = fictional()
        for key in ('codex_a', 'claude_a'):
            data['accounts'][key]['fetched_at'] = NOW - 95
        texts, _ = self.draw('everything', data)                                # seven lines: all of them, and no hint
        self.assertNotIn('Tap to close', texts)
        for expected in ('Access blocked', 'Too many requests', '5 hours 40% left, resets in 1h 30m', 'week left, resets in 3d 4h',
                         'week left, resets in 2d 9h', '99 saved resets (old), updated 1 min ago'):
            self.assertIn(expected, texts)
        for key in ('codex_a', 'claude_a'):                                     # nine lines would not fit: the second lines go first
            data['accounts'][key]['fetched_at'] = NOW - 86000
        texts, _ = self.draw('everything-old', data)
        self.assertNotIn('Tap to close', texts)
        self.assertEqual(len([t for t in texts if t.startswith('99 saved resets (old)')]), 2)
        self.assertFalse([t for t in texts if t.startswith('updated')])
        for expected in ('Access blocked', 'Too many requests', '5 hours 40% left, resets in 1h 30m'):
            self.assertIn(expected, texts)
        texts, _ = self.draw('normal-again', short)
        self.assertIn('Tap to close', texts)                                    # with room to spare the hint stays


if __name__ == '__main__':
    unittest.main()
