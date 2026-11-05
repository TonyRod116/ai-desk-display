import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from token_tv import local_usage
from token_tv.claude_backup import FILE, SOURCE, quota_record, store, with_backup
from token_tv.local_usage import atomic_json, fetch_local, origin_id
from token_tv.state import UsageStore

NOW = 100000
EMAIL = 'demo@example.invalid'
ACCOUNT = {'key': 'claude', 'alias': 'Claude', 'provider': 'claude', 'source_home': '/synthetic/claude', 'email': EMAIL}
ORIGIN = origin_id(ACCOUNT['source_home'], EMAIL)
# Worker A's 180/480 s tiers (docs/plans/2026-11-03-improvements.md) arrive in the same merge as this file.
TIERS = hasattr(local_usage, 'OFFICIAL_FRESH_SECONDS')


def record(source, fetched, week=40.0, five=12.5, origin=ORIGIN, **changes):
    windows = [{'label': 'WEEK', 'used_percent': week, 'resets_at': NOW + 86400, 'duration_minutes': 10080}]
    if five is not None:
        windows.insert(0, {'label': '5H', 'used_percent': five, 'resets_at': NOW + 3600, 'duration_minutes': 300})
    return dict({'fetched_at': fetched, 'windows': windows, 'origin': origin, 'source': source, 'stale': False,
                 'identity_verified': True}, **changes)


class ClaudeBackupTests(unittest.TestCase):
    def read(self, directory, official=None, browser=None, now=NOW):
        if official is not None:
            atomic_json(Path(directory)/'claude-official.json', official)
        if browser is not None:
            atomic_json(Path(directory)/FILE, browser)
        with patch('token_tv.local_usage.time.time', return_value=now):
            return fetch_local(ACCOUNT, directory, official_claude=True)

    def test_the_official_reading_wins_while_it_is_current_even_if_the_browser_is_newer(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory, record('claude_official_cli', NOW - 90, week=10), record(SOURCE, NOW - 5, week=99))
            self.assertEqual((row['quota_origin'], row['status']), ('claude_official_cli', 'ok'))
            self.assertEqual([w['used_percent'] for w in row['windows']], [12.5, 10.0])

    def test_the_browser_reading_stands_in_when_the_official_one_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory, browser=record(SOURCE, NOW - 40, week=33))
            self.assertEqual((row['quota_origin'], row['status'], row['identity_verified']), (SOURCE, 'ok', True))
            self.assertEqual((row['fetched_at'], row['last_success_at']), (NOW - 40, NOW - 40))
            self.assertEqual([(w['label'], w['used_percent']) for w in row['windows']], [('5H', 12.5), ('WEEK', 33.0)])
            self.assertEqual((row['key'], row['alias'], row['provider'], row['source']), ('claude', 'Claude', 'claude', 'local'))
            self.assertNotIn('error_code', row)

    def test_it_stands_in_when_the_official_reading_failed_or_is_stale(self):
        failed = {'fetched_at': 0, 'windows': [], 'origin': ORIGIN, 'source': 'claude_official_cli', 'stale': True}
        for official in (failed, record('claude_official_cli', NOW - 2000), record('claude_official_cli', NOW - 20, stale=True),
                         record('claude_official_cli', NOW - 20, origin='someone else')):
            with self.subTest(official=official['fetched_at']), tempfile.TemporaryDirectory() as directory:
                row = self.read(directory, official, record(SOURCE, NOW - 20, week=33))
                self.assertEqual((row['quota_origin'], row['status']), (SOURCE, 'ok'))
                self.assertEqual(row['windows'][-1]['used_percent'], 33.0)

    def test_nothing_current_means_unknown_never_a_number_from_either(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory, record('claude_official_cli', NOW - 2000), record(SOURCE, NOW - 2000))
            self.assertEqual((row['windows'], row['status'], row['quota_origin']), ([], 'quota_unavailable', 'claude_official_cli'))
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory)
            self.assertEqual((row['windows'], row['status'], row['quota_origin']), ([], 'quota_unavailable', 'claude_official_cli'))

    def test_a_browser_reading_that_cannot_be_trusted_is_ignored(self):
        bad = {'another account': record(SOURCE, NOW - 20, origin=origin_id('/synthetic/claude', 'other@example.invalid')),
               'the official source name': record('claude_official_cli', NOW - 20),
               'a made-up source': record('claude_statusline', NOW - 20),
               'from the future': record(SOURCE, NOW + 600),
               'no dated fetch': record(SOURCE, None),
               'week passed': dict(record(SOURCE, NOW - 20), windows=[{'label': 'WEEK', 'used_percent': 5, 'resets_at': NOW - 1, 'duration_minutes': 10080}]),
               'no week': dict(record(SOURCE, NOW - 20), windows=[{'label': '5H', 'used_percent': 5, 'resets_at': NOW + 60, 'duration_minutes': 300}]),
               'no windows': dict(record(SOURCE, NOW - 20), windows=[]),
               'windows not a list': dict(record(SOURCE, NOW - 20), windows='all of them')}
        for name, browser in bad.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                row = self.read(directory, browser=browser)
                self.assertEqual((row['windows'], row['quota_origin']), ([], 'claude_official_cli'))
        for junk in ('not json', '[]', '"text"', '7', ''):
            with self.subTest(junk=junk), tempfile.TemporaryDirectory() as directory:
                (Path(directory)/FILE).write_text(junk)
                self.assertEqual(self.read(directory)['windows'], [])

    def test_a_rolled_over_five_hour_window_is_dropped_alone_and_the_week_stays(self):
        with tempfile.TemporaryDirectory() as directory:
            browser = record(SOURCE, NOW - 20)
            browser['windows'][0]['resets_at'] = NOW - 1
            row = self.read(directory, browser=browser)
            self.assertEqual([w['label'] for w in row['windows']], ['WEEK'])
            self.assertEqual(row['quota_origin'], SOURCE)

    def test_the_browser_reading_expires_by_itself_like_the_official_one(self):
        with tempfile.TemporaryDirectory() as directory:
            atomic_json(Path(directory)/FILE, record(SOURCE, NOW - 10))
            fetch = lambda account: fetch_local(account, directory, official_claude=True)
            usage = UsageStore([ACCOUNT], fetch=fetch)
            with patch('token_tv.local_usage.time.time', return_value=NOW), patch('token_tv.state.time.time', return_value=NOW):
                usage.refresh()
                self.assertEqual(usage.snapshot()['accounts']['claude']['weekly_percent'], 40.0)
            with patch('token_tv.local_usage.time.time', return_value=NOW + 1000), patch('token_tv.state.time.time', return_value=NOW + 1000):
                shown = usage.snapshot()['accounts']['claude']       # the poller stopped: nothing refreshed, nothing stays
                self.assertEqual((shown['windows'], shown['status'], shown['weekly_percent']), ([], 'quota_unavailable', None))
            with patch('token_tv.local_usage.time.time', return_value=NOW + 20), patch('token_tv.state.time.time', return_value=NOW + 20):
                usage.refresh()
                self.assertEqual(usage.snapshot()['accounts']['claude']['quota_origin'], SOURCE)
            (Path(directory)/FILE).unlink()
            with patch('token_tv.local_usage.time.time', return_value=NOW + 30), patch('token_tv.state.time.time', return_value=NOW + 30):
                usage.refresh()
                gone = usage.snapshot()['accounts']['claude']       # a failed refresh never revives the earlier numbers
                self.assertEqual((gone['windows'], gone['quota_origin']), ([], 'claude_official_cli'))

    def test_only_claude_uses_it_and_only_beside_the_official_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            atomic_json(Path(directory)/FILE, record(SOURCE, NOW - 10))
            with patch('token_tv.local_usage.time.time', return_value=NOW):
                self.assertEqual(fetch_local(ACCOUNT, directory)['windows'], [])           # the official reader is off
                codex = dict(ACCOUNT, key='codex', provider='codex', source_home='/synthetic/codex')
                row = fetch_local(codex, directory, official_codex=True)
            self.assertEqual((row['windows'], row['quota_origin']), ([], 'codex_official_cli'))

    def test_the_official_readers_why_it_is_failing_stays_with_the_row(self):
        with tempfile.TemporaryDirectory() as directory:
            atomic_json(Path(directory)/FILE, record(SOURCE, NOW - 10))
            official = fetch_local(ACCOUNT, directory, official_claude=True)
            official['reader'] = {'state': 'failing', 'reason': 'login_required'}
            with patch('token_tv.local_usage.time.time', return_value=NOW):
                row = with_backup(official, ACCOUNT, directory)
            self.assertEqual((row['quota_origin'], row['reader']['reason']), (SOURCE, 'login_required'))

    @unittest.skipUnless(TIERS, 'needs worker A\'s 180/480 s freshness tiers')
    def test_the_same_180_480_rule_applies_to_the_browser_reading(self):
        for age, aged in ((100, False), (180, False), (181, True), (300, True), (480, True)):
            with self.subTest(age=age), tempfile.TemporaryDirectory() as directory:
                row = self.read(directory, browser=record(SOURCE, NOW - age))
                self.assertEqual((row['quota_origin'], bool(row['windows']), bool(row.get('reading_aged'))), (SOURCE, True, aged))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.read(directory, browser=record(SOURCE, NOW - 481))['windows'], [])

    @unittest.skipUnless(TIERS, 'needs worker A\'s 180/480 s freshness tiers')
    def test_an_aged_official_reading_gives_way_only_to_a_younger_browser_one(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory, record('claude_official_cli', NOW - 300, week=10), record(SOURCE, NOW - 30, week=33))
            self.assertEqual((row['quota_origin'], row['windows'][-1]['used_percent'], bool(row.get('reading_aged'))), (SOURCE, 33.0, False))
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory, record('claude_official_cli', NOW - 300, week=10), record(SOURCE, NOW - 400, week=33))
            self.assertEqual((row['quota_origin'], row['windows'][-1]['used_percent'], bool(row.get('reading_aged'))), ('claude_official_cli', 10.0, True))
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory, record('claude_official_cli', NOW - 450, week=10), record(SOURCE, NOW - 250, week=33))
            self.assertEqual((row['quota_origin'], row['windows'][-1]['used_percent'], bool(row.get('reading_aged'))), (SOURCE, 33.0, True))
        with tempfile.TemporaryDirectory() as directory:
            row = self.read(directory, record('claude_official_cli', NOW - 100, week=10), record(SOURCE, NOW - 5, week=33))
            self.assertEqual(row['quota_origin'], 'claude_official_cli')

    def test_a_quota_record_needs_a_dated_and_bounded_reading(self):
        week = {'utilization': 40, 'resets_at': 2000}
        good = {'five_hour': {'utilization': 1, 'resets_at': 1800}, 'seven_day': week}
        self.assertEqual(quota_record(good, 1500, ORIGIN)['fetched_at'], 1500)
        self.assertEqual(quota_record(good, 1500, ORIGIN)['source'], 'claude_browser')
        for provider_at in (0, -5, float('nan'), float('inf'), 1999, 2000):
            with self.subTest(provider_at=provider_at):
                self.assertIsNone(quota_record(good, provider_at, ORIGIN))
        for quota in (None, [], {}, {'seven_day': None}, dict(good, extra=1), {'seven_day': dict(week, extra=1)}):
            with self.subTest(quota=quota):
                self.assertIsNone(quota_record(quota, 1500, ORIGIN))

    def test_the_stored_reading_is_atomic_private_and_never_goes_back_in_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'offline'/FILE
            first = quota_record({'seven_day': {'utilization': 40, 'resets_at': 2000}}, 1500, ORIGIN)
            older = quota_record({'seven_day': {'utilization': 1, 'resets_at': 2000}}, 1400, ORIGIN)
            newer = quota_record({'seven_day': {'utilization': 50, 'resets_at': 2000}}, 1600, ORIGIN)
            other = quota_record({'seven_day': {'utilization': 7, 'resets_at': 2000}}, 1000, 'another account')
            self.assertTrue(store(path, first))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(store(path, older))
            self.assertEqual(local_usage.read_record(path)['fetched_at'], 1500)
            self.assertTrue(store(path, newer))
            self.assertTrue(store(path, other), 'a different account replaces it whatever the date')
            self.assertEqual(local_usage.read_record(path)['origin'], 'another account')
            self.assertEqual([item.name for item in path.parent.iterdir()], [FILE], 'no temporary file is left behind')


if __name__ == '__main__':
    unittest.main()
