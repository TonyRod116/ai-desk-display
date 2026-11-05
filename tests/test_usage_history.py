"""History and forecast: web only, numbers only, honest about gaps (Tony, 2026-11-03)."""
import copy
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from token_tv import usage_history as uh
from token_tv.live import explain_readers, handler
from token_tv.state import UsageStore
from token_tv.usage_history import UsageHistory, forecast, readings, segments

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0
H, D = 3600, 86400


def line(start, end, step, used0, per_hour, reset):
    """Readings every `step` seconds from `start` to `end`, the used percent rising `per_hour` points an hour."""
    points, t = [], start
    while t <= end + 1e-6:
        points.append((t, used0 + per_hour * (t - start) / H, reset))
        t += step
    return points


def five_hours(per_hour=20.0, used_now=60.0, minutes=60, reset_in=3 * H):
    """The last `minutes` of a 5-hour window, ending now at `used_now`."""
    start = NOW - minutes * 60
    return line(start, NOW, 180, used_now - per_hour * minutes / 60, per_hour, NOW + reset_in)


def snapshot(rows):
    return {'schema': 1, 'updated_at': NOW, 'accounts': {row['key']: row for row in rows}}


def account(key, provider, windows, age=30, status='ok', **extra):
    return dict({'key': key, 'alias': key.upper(), 'provider': provider, 'status': status, 'fetched_at': NOW - age,
                 'windows': [{'label': label, 'used_percent': used, 'resets_at': NOW + left} for label, used, left in windows]}, **extra)


class ForecastTests(unittest.TestCase):
    def test_a_steady_pace_says_when_the_five_hours_run_out(self):
        result = forecast(five_hours(per_hour=20, used_now=60), '5H', NOW)
        self.assertEqual(result['state'], 'runs_out')
        self.assertAlmostEqual(result['seconds'], 2 * H, delta=60)      # 40 points left at 20 an hour
        self.assertAlmostEqual(result['at'], NOW + 2 * H, delta=60)
        self.assertAlmostEqual(result['pace_per_hour'], 20, delta=0.5)
        self.assertEqual(result['end_used'], 100.0)

    def test_a_slow_pace_lasts_until_the_reset(self):
        result = forecast(five_hours(per_hour=4, used_now=60), '5H', NOW)
        self.assertEqual(result['state'], 'lasts')
        self.assertIsNone(result['seconds'])
        self.assertIsNone(result['at'])
        self.assertAlmostEqual(result['end_used'], 60 + 4 * 3, delta=0.5)   # three hours to the reset

    def test_the_week_uses_the_last_day(self):
        reset = NOW + 3 * D
        slow = line(NOW - 4 * D, NOW - D - 600, 1200, 5, 0.1, reset)         # three quiet days...
        fast = line(NOW - D, NOW, 600, slow[-1][1], 3.0, reset)               # ...then a busy day: 72 points
        result = forecast(slow + fast, 'WEEK', NOW)
        self.assertAlmostEqual(result['pace_per_hour'], 3.0, delta=0.2)       # not the average of four days
        self.assertEqual(result['state'], 'runs_out')
        remaining = 100 - fast[-1][1]
        self.assertAlmostEqual(result['seconds'], remaining / 3.0 * H, delta=600)
        self.assertLess(result['at'], reset)

    def test_the_five_hours_use_only_the_last_hour(self):
        reset = NOW + 2 * H
        quiet = line(NOW - 3 * H, NOW - H - 180, 180, 10, 1.0, reset)
        busy = line(NOW - H, NOW, 180, quiet[-1][1], 30.0, reset)
        self.assertAlmostEqual(forecast(quiet + busy, '5H', NOW)['pace_per_hour'], 30.0, delta=1.0)

    def test_flat_usage_says_nothing(self):
        self.assertIsNone(forecast(five_hours(per_hour=0), '5H', NOW))

    def test_thin_evidence_says_nothing(self):
        self.assertIsNone(forecast(five_hours(minutes=10), '5H', NOW))                # ten minutes of a 60-minute look-back
        self.assertIsNone(forecast(five_hours(minutes=60)[-2:], '5H', NOW))           # two readings
        reset = NOW + 3 * D
        self.assertIsNone(forecast(line(NOW - 6 * H, NOW, 600, 20, 2.0, reset), 'WEEK', NOW))   # six hours of a day
        self.assertIsNotNone(forecast(line(NOW - 13 * H, NOW, 600, 20, 2.0, reset), 'WEEK', NOW))

    def test_an_old_last_reading_says_nothing(self):
        points = five_hours()
        self.assertIsNotNone(forecast(points, '5H', NOW + 10 * 60))
        self.assertIsNone(forecast(points, '5H', NOW + 16 * 60))      # the reader stopped: unknown now, not "still rising"

    def test_a_gap_breaks_the_line_and_the_pace_is_never_stretched_across_it(self):
        reset = NOW + 3 * H
        before = line(NOW - 3 * H, NOW - 2 * H, 180, 10, 30.0, reset)             # an hour of fast use, then an outage
        after = line(NOW - 40 * 60, NOW, 180, before[-1][1], 6.0, reset)          # forty minutes later it is back
        joined = forecast(before + after, '5H', NOW)
        alone = forecast(after, '5H', NOW)
        self.assertEqual(joined, alone)
        self.assertAlmostEqual(joined['pace_per_hour'], 6.0, delta=0.5)
        short = line(NOW - 20 * 60, NOW, 180, before[-1][1], 6.0, reset)
        self.assertIsNone(forecast(before + short, '5H', NOW))            # twenty minutes since the outage: too thin to say
        steps = [t for t, *_ in before + after]
        self.assertGreater(max(b - a for a, b in zip(steps, steps[1:])), uh.GAP)

    def test_a_reset_starts_a_new_window(self):
        old_reset, new_reset = NOW - 30 * 60, NOW + 5 * H
        old = line(NOW - 5 * H, NOW - 35 * 60, 180, 5, 30.0, old_reset)           # the window that just ended
        fresh = line(NOW - 40 * 60, NOW, 180, 2, 6.0, new_reset)
        result = forecast(old + fresh, '5H', NOW)
        self.assertEqual(result, forecast(fresh, '5H', NOW))
        self.assertAlmostEqual(result['pace_per_hour'], 6.0, delta=0.5)
        self.assertIsNone(forecast(old + fresh[-2:], '5H', NOW))           # two readings of the new window: nothing yet

    def test_usage_that_falls_restarts_the_evidence(self):
        reset = NOW + 3 * H
        high = line(NOW - H, NOW - 30 * 60, 180, 80, 20.0, reset)
        low = line(NOW - 29 * 60, NOW, 180, 20, 6.0, reset)               # the count dropped: not the same count any more
        self.assertEqual(forecast(high + low, '5H', NOW), forecast(low, '5H', NOW))

    def test_an_exhausted_or_ended_window_says_nothing(self):
        self.assertIsNone(forecast(five_hours(per_hour=10, used_now=100), '5H', NOW))
        self.assertIsNone(forecast(five_hours(reset_in=-5), '5H', NOW))

    def test_bad_input_is_ignored_not_trusted(self):
        junk = [(float('nan'), 5, NOW + H), (NOW, float('inf'), NOW + H), ('x', 1, 2), (NOW, -3, NOW + H), (NOW, 101, NOW + H), None, (1,)]
        self.assertIsNone(forecast(junk, '5H', NOW))
        self.assertEqual(forecast(five_hours() + junk, '5H', NOW), forecast(five_hours(), '5H', NOW))
        self.assertIsNone(forecast(five_hours(), 'BUDGET', NOW))
        self.assertIsNone(forecast([], 'WEEK', NOW))


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state' / 'usage-history.jsonl'
        self.history = UsageHistory(self.path)

    def lines(self):
        return [json.loads(text) for text in self.path.read_text().splitlines()] if self.path.exists() else []

    def reading(self, used, at=NOW, week=40.0, provider='claude'):
        return snapshot([account(provider + '_a', provider, [('5H', used, 2 * H), ('WEEK', week, 3 * D)], age=NOW - at)])

    def test_it_keeps_the_first_reading_then_only_changes_and_heartbeats(self):
        self.assertEqual(self.history.record(self.reading(20), NOW), 2)                    # both windows, first time
        self.assertEqual(self.history.record(self.reading(21, NOW + 60), NOW + 60), 0)      # changed, but under three minutes
        self.assertEqual(self.history.record(self.reading(21, NOW + 200), NOW + 200), 1)    # changed, three minutes later
        self.assertEqual(self.history.record(self.reading(21, NOW + 500), NOW + 500), 0)    # the same: nothing to say
        self.assertEqual(self.history.record(self.reading(21, NOW + 900), NOW + 900), 2)    # ten minutes: "still the same" heartbeat
        self.assertEqual([(x['w'], x['u']) for x in self.lines()],
                         [('5H', 20.0), ('WEEK', 40.0), ('5H', 21.0), ('5H', 21.0), ('WEEK', 40.0)])

    def test_a_new_window_is_written_at_once(self):
        self.history.record(self.reading(97), NOW)
        again = snapshot([account('claude_a', 'claude', [('5H', 1, 5 * H), ('WEEK', 41, 3 * D)], age=-30)])
        self.assertEqual(self.history.record(again, NOW + 30), 1)       # a new five-hour window half a minute later; the week only moved
        self.assertEqual([x['u'] for x in self.lines() if x['w'] == '5H'], [97.0, 1.0])

    def test_it_never_repeats_a_line_after_a_restart(self):
        self.history.record(self.reading(20), NOW)
        again = UsageHistory(self.path)
        self.assertEqual(again.record(self.reading(20), NOW), 0)
        self.assertEqual(len(self.lines()), 2)

    def test_the_time_is_the_readings_own_not_the_polls(self):
        self.history.record(self.reading(20, at=NOW - 100), NOW)
        self.assertEqual({x['t'] for x in self.lines()}, {int(NOW - 100)})
        self.assertEqual(self.history.record(self.reading(20, at=NOW - 100), NOW + 60), 0)   # a stopped reader writes nothing new

    def test_unknown_stale_or_ambiguous_readings_are_not_recorded(self):
        windows = [('WEEK', 30, 3 * D)]
        for row in (account('a', 'claude', windows, status='quota_unavailable'), account('a', 'claude', windows, status='stale'),
                    account('a', 'claude', [], status='ok'), account('a', 'claude', windows, age=uh.MAX_READING_AGE + 1),
                    account('a', 'claude', windows, age=-120), account('a', 'claude', [('BUDGET', 10, D)]),
                    account('a', 'claude', [('WEEK', 30, -5)]), account('a', 'claude', [('WEEK', None, D)]),
                    account('a', 'claude', [('WEEK', float('nan'), D)]), account('a', 'claude', [('WEEK', 130, D)])):
            self.assertEqual(self.history.record(snapshot([row]), NOW), 0, row)
        two = snapshot([account('a', 'claude', windows), account('b', 'claude', windows), account('c', 'codex', windows)])
        self.assertEqual(self.history.record(two, NOW), 1)                              # two Claude accounts: skipped; one Codex: kept
        self.assertEqual({x['p'] for x in self.lines()}, {'codex'})

    def test_the_file_holds_numbers_only_and_is_private(self):
        row = account('claude_a', 'claude', [('5H', 20, 2 * H), ('WEEK', 40, 3 * D)], alias='PRIVATE ALIAS', email='me@example.com',
                      source_home='/home/someone/.claude', reader={'state': 'failing', 'reason': 'login_required'})
        self.history.record(snapshot([row]), NOW)
        raw = self.path.read_text()
        for secret in ('PRIVATE ALIAS', 'me@example.com', '/home/someone', 'claude_a', 'login_required', 'CLAUDE_A'):
            self.assertNotIn(secret, raw)
        for record in self.lines():
            self.assertEqual(set(record), {'t', 'p', 'w', 'u', 'r'})
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.path.parent).st_mode), 0o700)

    def test_an_old_file_with_loose_permissions_is_made_private(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('')
        os.chmod(self.path, 0o644)
        self.history.record(self.reading(20), NOW)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_a_corrupt_line_costs_only_that_line(self):
        self.path.parent.mkdir(parents=True)
        good = uh._line('claude', 'WEEK', NOW - 2 * H, 30, NOW + 3 * D)
        self.path.write_bytes((good + 'not json at all\n{"t": 1, "p":\n\x00\x01\x02\n[1,2,3]\n"text"\n'
                               + uh._line('claude', 'WEEK', NOW - H, 31, NOW + 3 * D) + '{"t":123,"p":"claude","w":"WE').encode('utf-8', 'replace'))
        found = self.history.payload(NOW)['windows']['claude']['WEEK']
        self.assertEqual(sum(len(part) for part in found['segments']), 2)

    def test_a_line_cut_short_by_a_crash_does_not_swallow_the_next_one(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(uh._line('claude', 'WEEK', NOW - 2 * H, 30, NOW + 3 * D) + '{"t":123,"p":"claude","w":"WE')
        self.history.write('claude', 'WEEK', NOW - H, 31, NOW + 3 * D)       # a write without the compaction that `record` starts with
        found = self.history.payload(NOW)['windows']['claude']['WEEK']
        self.assertEqual([p[1] for part in found['segments'] for p in part], [30.0, 31.0])

    def test_compaction_drops_old_and_corrupt_lines_and_nothing_else(self):
        self.path.parent.mkdir(parents=True)
        old = uh._line('claude', 'WEEK', NOW - 31 * D, 10, NOW - 24 * D)
        fresh = [uh._line('claude', 'WEEK', NOW - 5 * D + i * 600, 10 + i, NOW + 2 * D) for i in range(3)]
        self.path.write_text(old + 'garbage\n' + ''.join(fresh))
        self.history.record(self.reading(20), NOW)
        raw = self.path.read_text().splitlines()
        self.assertNotIn(old.strip(), raw)
        self.assertNotIn('garbage', raw)
        for text in fresh:
            self.assertIn(text.strip(), raw)

    def test_a_clean_file_is_not_rewritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(uh._line('claude', 'WEEK', NOW - H, 10, NOW + 2 * D))
        before = os.stat(self.path)
        self.history.record(snapshot([]), NOW)
        after = os.stat(self.path)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))

    def test_it_never_disturbs_the_monitor(self):
        blocker = Path(self.directory.name) / 'a-file'
        blocker.write_text('x')
        for bad_path in (blocker / 'inside.jsonl', Path(self.directory.name)):   # under a file, and a directory itself
            history = UsageHistory(bad_path)
            self.assertEqual(history.record(self.reading(20), NOW), 0)
            self.assertEqual(history.payload(NOW)['windows'], {})
        for junk in (None, 5, 'x', [], {'accounts': 5}, {'accounts': {'a': None}}, {'accounts': {'a': {'provider': 7, 'windows': 3}}},
                     {'accounts': {'a': {'provider': 'claude', 'status': 'ok', 'fetched_at': 'now', 'windows': [None, 1, {'label': 'WEEK'}]}}}):
            self.assertEqual(self.history.record(junk, NOW), 0)

    def test_recording_does_not_change_the_snapshot_it_is_given(self):
        data = snapshot([account('claude_a', 'claude', [('5H', 20, 2 * H), ('WEEK', 40, 3 * D)], reader={'state': 'ok'}),
                         account('codex_a', 'codex', [('WEEK', 10, 3 * D)])])
        before = copy.deepcopy(data)
        self.history.record(data, NOW)
        self.history.payload(NOW)
        self.assertEqual(data, before)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.history = UsageHistory(Path(self.directory.name) / 'usage-history.jsonl')

    def fill(self, provider, label, points):
        for t, used, reset in points:
            self.history.write(provider, label, t, used, reset)

    def test_nothing_recorded_is_an_empty_answer(self):
        self.assertEqual(self.history.payload(NOW), {'schema': 1, 'now': int(NOW), 'windows': {}})

    def test_it_returns_the_current_window_and_its_forecast(self):
        self.fill('claude', '5H', five_hours(per_hour=20, used_now=60))
        found = self.history.payload(NOW)['windows']['claude']['5H']
        self.assertEqual(found['resets_at'], int(NOW + 3 * H))
        self.assertEqual(found['length'], 5 * H)
        self.assertEqual(len(found['segments']), 1)
        self.assertEqual(found['segments'][0][-1], [int(NOW), 60.0])
        self.assertEqual(found['forecast']['state'], 'runs_out')

    def test_a_gap_is_a_break_in_the_line_not_a_straight_segment(self):
        reset = NOW + 3 * H
        self.fill('claude', '5H', line(NOW - 90 * 60, NOW - 60 * 60, 180, 10, 6.0, reset) + line(NOW - 20 * 60, NOW, 180, 20, 6.0, reset))
        found = self.history.payload(NOW)['windows']['claude']['5H']
        self.assertEqual(len(found['segments']), 2)
        self.assertGreater(found['segments'][1][0][0] - found['segments'][0][-1][0], uh.GAP)

    def test_only_the_current_window_is_drawn(self):
        old = NOW - 20 * 60
        self.fill('claude', '5H', line(NOW - 5 * H, NOW - 40 * 60, 180, 5, 15.0, old) + line(NOW - 10 * 60, NOW, 180, 1, 6.0, NOW + 5 * H))
        found = self.history.payload(NOW)['windows']['claude']['5H']
        self.assertEqual(len(found['segments']), 1)
        self.assertLessEqual(found['segments'][0][-1][1], 3)
        self.assertGreater(found['segments'][0][0][0], NOW - 11 * 60)

    def test_an_ended_window_is_left_out(self):
        self.fill('claude', '5H', five_hours(reset_in=-30))
        self.assertEqual(self.history.payload(NOW)['windows'], {})

    def test_a_dense_week_is_thinned_but_keeps_its_ends_and_its_breaks(self):
        reset = NOW + 2 * D
        first = line(NOW - 5 * D, NOW - 3 * D, 60, 1, 0.05, reset)
        second = line(NOW - 2 * D, NOW, 60, 6, 0.05, reset)             # 2 880 readings a minute apart: two days gap
        self.fill('codex', 'WEEK', first + second)
        found = self.history.payload(NOW)['windows']['codex']['WEEK']
        self.assertEqual(len(found['segments']), 2)
        self.assertLessEqual(sum(len(s) for s in found['segments']), uh.MAX_POINTS + 4)
        self.assertEqual(found['segments'][-1][-1][0], int(NOW))
        self.assertEqual(found['segments'][0][0][0], int(first[0][0]))

    def test_segments_start_a_new_part_where_the_count_falls(self):
        parts = segments([(NOW, 50, NOW + H), (NOW + 60, 51, NOW + H), (NOW + 120, 10, NOW + H), (NOW + 180, 12, NOW + H)], 5 * H)
        self.assertEqual([[p[1] for p in part] for part in parts], [[50.0, 51.0], [10.0, 12.0]])

    def test_readings_follow_the_monitor_snapshot_shape(self):
        data = snapshot([account('claude_a', 'claude', [('WEEK', 31.5, 3 * D), ('5H', 12, 2 * H)], age=45),
                         account('grok_a', 'grok', [('BUDGET', 61, 6 * D)])])
        self.assertEqual(sorted(readings(data, NOW)), sorted([('claude', 'WEEK', NOW - 45, 31.5, NOW + 3 * D), ('claude', '5H', NOW - 45, 12.0, NOW + 2 * H)]))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.history = UsageHistory(Path(self.directory.name) / 'usage-history.jsonl')
        for t, used, reset in five_hours(per_hour=20, used_now=60):
            self.history.write('claude', '5H', t, used, reset)

        def fetch(account_):
            return {'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'status': 'ok', 'fetched_at': NOW, 'windows': [],
                    'identity_verified': False, 'reader': {'state': 'failing', 'reason': 'login_required', 'since': NOW - 60, 'retry_at': None}}
        self.store = UsageStore([{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude'}], fetch=fetch)
        self.store.refresh()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.store, history=self.history))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop)
        self.root = f'http://127.0.0.1:{self.server.server_port}'

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def get(self, path, headers=None, method=None, data=None):
        return urlopen(Request(self.root + path, headers=headers or {}, method=method, data=data))

    def test_history_is_served_to_the_page_itself(self):
        self.history.clock = lambda: NOW
        with self.get('/history', {'Sec-Fetch-Site': 'same-origin'}) as response:
            body = json.load(response)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertTrue(response.headers['Content-Type'].startswith('application/json'))
        self.assertEqual(body['schema'], 1)
        self.assertEqual(body['windows']['claude']['5H']['forecast']['state'], 'runs_out')

    def test_history_sits_behind_the_same_guards_as_the_other_readings(self):
        for headers in ({'Host': 'evil.example'}, {'Host': f'127.0.0.1:{self.server.server_port + 1}'},
                        {'Origin': 'http://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            with self.assertRaises(HTTPError) as caught:
                self.get('/history', headers)
            self.assertEqual(caught.exception.code, 403, headers)
        for method in ('POST', 'PUT', 'DELETE'):
            with self.assertRaises(HTTPError) as caught:
                self.get('/history', {'Content-Type': 'application/json'}, method, b'{}')
            self.assertIn(caught.exception.code, (404, 501), method)

    def test_a_server_without_history_answers_with_nothing_to_show(self):
        other = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.store))
        thread = threading.Thread(target=other.serve_forever)
        thread.start()
        try:
            with urlopen(f'http://127.0.0.1:{other.server_port}/history') as response:
                self.assertEqual(json.load(response)['windows'], {})
        finally:
            other.shutdown()
            other.server_close()
            thread.join()

    def test_the_dashboard_gets_the_reader_sentence_and_nothing_else_does(self):
        with self.get('/snapshot') as response:
            row = json.load(response)['accounts']['claude_a']
        self.assertEqual(row['reader']['reason'], 'login_required')
        self.assertIn('/login', row['reader']['text'])
        self.assertNotIn('text', self.store.snapshot()['accounts']['claude_a']['reader'])   # the store, and so the board, never sees it
        copy_ = {'accounts': {'a': {'reader': {'state': 'ok', 'reason': None}}, 'b': {}, 'c': {'reader': 7}}}
        explain_readers(copy_)
        self.assertEqual(copy_['accounts']['a']['reader'], {'state': 'ok', 'reason': None})


class BoardNeverReceivesTheHistoryTests(unittest.TestCase):
    """Tony: the forecast goes on the web only, never on the board."""

    BOARD_FILES = sorted(list((ROOT / 'token_tv').glob('board*.py')) + [ROOT / 'token_tv' / 'personal_faces.py', ROOT / 'token_tv' / 'display.py'])

    def test_no_board_or_face_code_mentions_the_history(self):
        self.assertGreater(len(self.BOARD_FILES), 20)
        for path in self.BOARD_FILES:
            text = path.read_text()
            for word in ('usage_history', 'UsageHistory', 'forecast', '/history'):
                self.assertNotIn(word, text, f'{path.name} mentions {word}')

    def test_importing_every_board_module_does_not_import_the_history(self):
        names = [f'token_tv.{path.stem}' for path in self.BOARD_FILES] + ['token_tv.board_pages']
        code = ('import importlib, sys\n'
                f'for name in {names!r}:\n    importlib.import_module(name)\n'
                "assert 'token_tv.usage_history' not in sys.modules, 'the board code pulled in the history'\n"
                'print("clean", len(sys.modules))\n')
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn('clean', result.stdout)

    def test_the_monitor_hands_the_board_nothing_from_the_history(self):
        source = (ROOT / 'token_tv' / 'live.py').read_text()
        call = re.search(r'render_board_pages\((?:[^()]|\([^()]*\))*\)', source).group(0)
        self.assertNotIn('history', call.lower())
        self.assertEqual(len(re.findall(r'usage_history\.record\(', source)), 1)
        self.assertIn('usage_history.record(snapshot)', source.split('render_board_pages(')[0])     # recorded before, read-only

    def test_board_pages_are_identical_with_or_without_a_history(self):
        from token_tv.board_pages import render_board_pages
        from token_tv.sample import snapshot as sample_snapshot
        data = sample_snapshot(NOW)
        data['accounts'] = {key: row for key, row in data['accounts'].items() if key in ('claude_a', 'codex_a')}   # one account each: recorded
        pristine = copy.deepcopy(data)
        with tempfile.TemporaryDirectory() as directory, patch('time.time', return_value=NOW):
            history = UsageHistory(Path(directory) / 'usage-history.jsonl', clock=lambda: NOW)
            plain = render_board_pages(data, scene_ids=['game-boy'] * 8)
            with patch.object(UsageHistory, 'record', side_effect=AssertionError('the board asked the history to record')), \
                    patch.object(UsageHistory, 'payload', side_effect=AssertionError('the board asked the history for a payload')):
                during = render_board_pages(data, scene_ids=['game-boy'] * 8)
            for t, used, reset in five_hours(per_hour=20, used_now=60):
                history.write('claude', '5H', t, used, reset)
            self.assertGreater(history.record(data, NOW), 0)
            self.assertIn('claude', history.payload(NOW)['windows'])
            after = render_board_pages(data, scene_ids=['game-boy'] * 8)
        self.assertEqual(data, pristine)
        self.assertEqual(plain, during)
        self.assertEqual(plain, after)


if __name__ == '__main__':
    unittest.main()
