"""Why a reading is missing (Tony, 2026-11-03): fixed ids, written by the readers, merged into each row by the monitor."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from token_tv import reader_status as rs
from token_tv.claude_usage import SCREEN_HINTS
from token_tv.local_usage import atomic_json, fetch_local, origin_id
from token_tv.state import UsageStore

NOW = 1_800_000_000


def account(provider):
    return {'key': provider + '_a', 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo/' + provider}


class ReasonTests(unittest.TestCase):
    def test_the_real_organization_block_message_is_recognised(self):
        # "Your organization has disabled Claude subscription access for Claude Code": hints are substrings of the lowercased screen.
        screen = 'Your organization has disabled Claude subscription access for Claude Code'.lower()
        hints = [word for word in SCREEN_HINTS if word in screen]
        self.assertEqual(hints, ['organization has disabled'])
        self.assertEqual(rs.reason_for('client_not_ready', hints), 'org_blocked')
        self.assertEqual(rs.reason_for('official_quota_unavailable', hints + ['error']), 'org_blocked')   # a block explains more
        self.assertEqual(rs.reason_for('client_not_ready', ['organization disabled']), 'reader_stuck')   # the old, wrong word

    def test_a_limit_explains_more_than_the_step_that_failed_and_codes_map_to_fixed_ids(self):
        for words in (['rate limit'], ['429', 'error'], ['too many requests']):
            self.assertEqual(rs.reason_for('native_refresh_unconfirmed', words), 'rate_limited')
        for code, expected in (('subscription_login_required', 'login_required'), ('auth_unavailable', 'login_required'),
                               ('identity_mismatch', 'wrong_account'), ('unsupported_client_version', 'client_version'),
                               ('unexpected_model_activity', 'model_activity'), ('native_refresh_unconfirmed', 'reader_stuck'),
                               ('timeout', 'reader_stuck'), ('cli_unavailable', 'reader_stuck'), ('RuntimeError', 'unknown'), (None, 'unknown')):
            self.assertEqual(rs.reason_for(code, ['error']), expected, code)
        self.assertTrue(set(rs.RATE_LIMIT) <= set(SCREEN_HINTS) and rs.ORG_BLOCK in SCREEN_HINTS)
        self.assertEqual({rs.reason_for(c) for c in rs._CODES} - set(rs.REASONS), set())

    def test_every_reason_has_short_and_long_english_words_and_an_unknown_id_says_no_reading(self):
        for reason, (short, long) in rs.REASONS.items():
            self.assertTrue(short and long, reason)
            self.assertLessEqual(len(short), 18, reason)                      # it has to fit the board's detail card
            self.assertEqual((rs.short_reason(reason), rs.long_reason(reason)), (short, long))
        self.assertEqual(rs.short_reason('made-up'), 'No reading')


class StatusFileTests(unittest.TestCase):
    def test_a_status_round_trips_and_only_fixed_words_and_numbers_leave_the_reader(self):
        ok = rs.status_record('ok', 'rate_limited', since=NOW - 50, now=NOW, next_at=NOW + 120)
        self.assertEqual(rs.reader_state(ok, NOW + 10), {'state': 'ok', 'reason': None, 'since': NOW - 50, 'retry_at': None})
        failing = rs.status_record('failing', 'rate_limited', since=NOW - 50, retry_at=NOW + 600, next_at=NOW + 120, now=NOW)
        self.assertEqual(rs.reader_state(failing, NOW + 10),
                         {'state': 'failing', 'reason': 'rate_limited', 'since': NOW - 50, 'retry_at': NOW + 600})
        self.assertTrue(all(value is None or type(value) in (int, str) for value in failing.values()))
        self.assertEqual(rs.status_record('failing', 'user@example.com PRIVATE', now=NOW)['reason'], 'unknown')
        with self.assertRaises(ValueError):
            rs.status_record('sleeping')

    def test_a_missing_malformed_or_abandoned_status_says_nothing(self):
        good = rs.status_record('failing', 'login_required', since=NOW, next_at=NOW + 120, now=NOW)
        self.assertIsNone(rs.reader_state(None, NOW))
        self.assertIsNone(rs.reader_state({}, NOW))
        self.assertIsNone(rs.reader_state(dict(good, schema=2), NOW))
        self.assertIsNone(rs.reader_state(dict(good, state='asleep'), NOW))
        self.assertIsNone(rs.reader_state(dict(good, updated_at='yesterday'), NOW))
        self.assertIsNone(rs.reader_state(good, NOW - 120))                               # written in the future (clock skew)
        self.assertIsNotNone(rs.reader_state(good, NOW + 120 + rs.STATUS_GRACE_SECONDS))  # still its own turn plus a grace
        self.assertIsNone(rs.reader_state(good, NOW + 121 + rs.STATUS_GRACE_SECONDS))     # the reader stopped writing
        # Odd values inside a good file are cleaned, never trusted.
        odd = rs.reader_state(dict(good, reason='<b>x</b>', since='soon', retry_at=NOW + 10 * 86400), NOW)
        self.assertEqual((odd['reason'], odd['retry_at']), ('unknown', None))
        self.assertEqual(odd['since'], NOW)
        self.assertEqual(rs.reader_state(dict(good, retry_at=NOW - 3600), NOW)['retry_at'], None)       # a backoff long over

    def test_publish_is_atomic_private_and_survives_a_full_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            rs.publish_status(directory, 'claude', 'failing', 'org_blocked', NOW - 5, None, NOW + 120, NOW)
            path = Path(directory) / rs.STATUS_FILES['claude']
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['reason'], 'org_blocked')
            with patch('token_tv.local_usage.atomic_json', side_effect=OSError('disk full')):
                rs.publish_status(directory, 'claude', 'ok', None, NOW, None, NOW + 120, NOW)       # must not raise
            self.assertEqual(rs.last_state(directory, 'codex'), (None, 0))
            with patch('token_tv.reader_status.time.time', return_value=NOW + 30):
                self.assertEqual(rs.last_state(directory, 'claude'), ('failing', NOW - 5))          # a quick restart resumes it


class MonitorMergeTests(unittest.TestCase):
    def official(self, provider):
        return {'source': provider + '_official_cli', 'origin': origin_id('/demo/' + provider), 'fetched_at': NOW,
                'ordinary_usage_allowed': True, 'stale': False,
                'windows': [{'label': 'WEEK', 'used_percent': 20, 'duration_minutes': 10080, 'resets_at': NOW + 86400}]}

    def test_the_row_carries_reader_only_for_official_sources_and_tolerates_its_absence(self):
        with tempfile.TemporaryDirectory() as directory, patch('token_tv.local_usage.time.time', return_value=NOW + 10), \
             patch('token_tv.reader_status.time.time', return_value=NOW + 10):
            for provider in ('claude', 'codex'):
                atomic_json(Path(directory) / (provider + '-official.json'), self.official(provider))
            plain = fetch_local(account('claude'), directory, official_claude=True, official_codex=True)
            self.assertNotIn('reader', plain)                                                         # nothing known: absent
            rs.publish_status(directory, 'claude', 'failing', 'rate_limited', NOW - 30, NOW + 300, NOW + 120, NOW)
            rs.publish_status(directory, 'codex', 'ok', None, NOW - 900, None, NOW + 60, NOW)
            claude = fetch_local(account('claude'), directory, official_claude=True, official_codex=True)
            codex = fetch_local(account('codex'), directory, official_claude=True, official_codex=True)
            self.assertEqual(claude['reader'], {'state': 'failing', 'reason': 'rate_limited', 'since': NOW - 30, 'retry_at': NOW + 300})
            self.assertEqual(codex['reader'], {'state': 'ok', 'reason': None, 'since': NOW - 900, 'retry_at': None})
            self.assertEqual(claude['windows'][0]['used_percent'], 20)                                # the reading itself is untouched
            # The failing reason is shown while a reading is still held (aged), and the snapshot keeps it for the dashboard.
            store = UsageStore([account('claude')], fetch=lambda a: fetch_local(a, directory, official_claude=True))
            store.refresh()
            self.assertEqual(store.snapshot()['accounts']['claude_a']['reader']['reason'], 'rate_limited')
            # Not an official source: nothing is merged, whatever files exist.
            other = fetch_local(account('claude'), directory)
            self.assertNotIn('reader', other)

    def test_a_blank_row_still_says_why(self):
        with tempfile.TemporaryDirectory() as directory, patch('token_tv.local_usage.time.time', return_value=NOW + 900), \
             patch('token_tv.reader_status.time.time', return_value=NOW + 900):
            rs.publish_status(directory, 'claude', 'failing', 'login_required', NOW, None, NOW + 1000, NOW + 880)
            row = fetch_local(account('claude'), directory, official_claude=True)
        self.assertEqual(row['windows'], [])
        self.assertEqual(row['reader']['reason'], 'login_required')
        self.assertEqual(row['quota_origin'], 'claude_official_cli')


if __name__ == '__main__':
    unittest.main()
