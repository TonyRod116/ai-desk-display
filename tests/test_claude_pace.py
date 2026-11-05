"""How often the Claude reader asks, what makes it back off, and when the status line stands in for a client start.

Tony, 2026-11-03: every poll started a whole Claude Code client; a rate limit kept the failures coming every minute; and
nothing used the numbers the status line already captures. The loop runs here on a clock that moves only when it waits.
"""
import importlib.util
import io
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_claude_usage as base
from token_tv.claude_usage import (REUSE_SECONDS, STATUSLINE_MAX_AGE, ClaudeUsageReader, native_record, rate_limited_until,
                                   statusline_record)
from token_tv.local_usage import OFFICIAL_FRESH_SECONDS, capture_claude, fetch_local, origin_id
from token_tv.reader_status import REASONS
from token_tv.sources import SourceError

ROOT = '/tmp/demo-claude'
SCRIPT = Path(__file__).parents[1] / 'scripts/claude_usage_collector.py'
EMAIL = 'owner@example.invalid'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    return collector


class Clock:
    """Stands in for the collector's `time`: it only moves when the loop waits."""
    def __init__(self):
        self.now = self.start = float(int(time.time()))

    def time(self):
        return self.now

    def monotonic(self):
        return self.now


def native(now, age=0):
    """A fresh native record as the client leaves it, dated relative to `now`."""
    when = int(now) + 7200
    data = {'oauthAccount': {'accountUuid': 'demo-owner'},
            'cachedUsageUtilization': {'accountUuid': 'demo-owner', 'fetchedAtMs': (now - age) * 1000,
                'utilization': {'five_hour': {'utilization': 5, 'resets_at': when},
                                'seven_day': {'utilization': 66, 'resets_at': when + 86400}}}}
    return native_record(data, ROOT, since=now - age - 5, now=now)


def write_capture(directory, fetched_at, week=True, five=True, source_home=ROOT, reset_in=7200):
    """The status line's capture, written by the real writer (two callbacks, the second one advancing)."""
    path = Path(directory) / 'offline/claude.json'
    limits = {}
    if five:
        limits['five_hour'] = {'used_percentage': 30, 'resets_at': int(fetched_at) + reset_in}
    if week:
        limits['seven_day'] = {'used_percentage': 41, 'resets_at': int(fetched_at) + reset_in + 86400}
    data = {'session_id': 'demo', 'cost': {'total_api_duration_ms': 100}, 'context_window': {'total_output_tokens': 100},
            'rate_limits': limits}
    capture_claude(data, path, now=int(fetched_at) - 30, source_home=source_home)
    data['cost']['total_api_duration_ms'], data['context_window']['total_output_tokens'] = 200, 200
    capture_claude(data, path, now=int(fetched_at), source_home=source_home)


def drive(directory, reads, clock=None, passes=None, authenticate=None, tick=None, account=None):
    """The collector's loop. `reads` are what successive client starts do: a record, an exception, a function of the clock, or a
    pair (that, trace) where trace is the screen facts the reader would leave (a dict, or a function of the clock). It ends after
    `passes` waits, or when every read has been used. Returns what happened."""
    collector = load('claude_collector_pace')
    clock = clock or Clock()
    account = account or {'key': 'claude', 'alias': 'CLAUDE', 'provider': 'claude', 'source_home': ROOT}
    config = {'automatic_claude_usage': True, 'accounts': [account]}
    offline = Path(directory) / 'offline'
    run = SimpleNamespace(attempts=[], waits=[], statuses=[], files=[], alerts=MagicMock(), reader=MagicMock(), clock=clock)
    script = iter(reads)

    def read(cancel_event=None):
        run.attempts.append(clock.now)
        item = next(script)
        outcome, trace = item if isinstance(item, tuple) else (item, {})
        run.reader.trace = trace(clock.now) if callable(trace) else dict(trace)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(clock.now) if callable(outcome) else outcome
    run.reader.read.side_effect = read
    run.reader.trace = {}
    if authenticate is not None:
        run.reader.authenticate.side_effect = authenticate

    class Event:
        done = False
        def is_set(self): return self.done
        def set(self): self.done = True
        def wait(self, seconds):
            run.waits.append(seconds)
            for name, bucket in (('claude-reader-status.json', run.statuses), ('claude-official.json', run.files)):
                found = offline / name
                bucket.append(json.loads(found.read_text()) if found.exists() else None)
            if tick:
                tick(clock)
            clock.now += seconds
            self.done = len(run.waits) >= passes if passes else len(run.attempts) >= len(reads)
    with patch('sys.argv', ['collector', '--config', str(Path(directory) / 'config.json')]), \
         patch.object(collector, 'load_config', return_value=config), \
         patch.object(collector, 'ClaudeUsageReader', return_value=run.reader), \
         patch.object(collector, 'notify_display', return_value=True), \
         patch.object(collector, 'Alerts', return_value=run.alerts), \
         patch.object(collector, 'time', clock), \
         patch.object(collector.threading, 'Event', Event), patch.object(collector.signal, 'signal'), \
         patch('sys.stdout', new_callable=io.StringIO) as output:
        collector.main()
    run.output = output.getvalue()
    run.collector = collector
    run.gaps = [b - a for a, b in zip(run.attempts, run.attempts[1:])]
    return run


def limited(code, *words, **extra):
    return SourceError(code) if code != 'RuntimeError' else RuntimeError('PRIVATE ERROR user@example.com'), {'hints': list(words), **extra}


class BackoffTests(unittest.TestCase):
    def test_any_rate_limit_word_backs_off_whatever_the_failure_code_and_a_good_reading_resumes_the_cadence(self):
        # Tony, 2026-11-03: the recent failures were 'native_refresh_unconfirmed' with 'rate limit' and kept polling every minute.
        reads = [limited('official_quota_unavailable', 'rate limit', 'error'), limited('native_refresh_unconfirmed', '429'),
                 limited('client_not_ready', 'too many requests'), limited('RuntimeError', 'rate limit'),
                 native, limited('usage_view_not_confirmed', '429'), limited('timeout', 'rate limit')]
        with tempfile.TemporaryDirectory() as directory:
            run = drive(directory, reads)
        self.assertEqual(run.gaps, [300, 600, 900, 900, 120, 300])    # 5 min, doubling to 15; the good reading resets it
        self.assertIn('Retry in 300 seconds', run.output)
        self.assertNotIn('PRIVATE', run.output)

    def test_failures_without_a_rate_limit_word_keep_the_normal_cadence(self):
        reads = [limited('native_refresh_unconfirmed', 'error', 'failed to'), limited('official_quota_unavailable', 'error'),
                 limited('client_not_ready'), limited('RuntimeError', 'try again')]
        with tempfile.TemporaryDirectory() as directory:
            run = drive(directory, reads)
        self.assertEqual(run.gaps, [120, 120, 120])
        self.assertNotIn('Retry in', run.output)

    def test_a_moment_the_service_names_is_honoured_published_and_bounded(self):
        ahead = lambda seconds: (lambda now: {'hints': ['rate limit'], 'retry_at': int(now) + seconds})
        for named, expected in ((1000, 1005),          # honoured, with a few seconds of margin
                                (30, 120),             # never faster than the normal cadence
                                (7 * 3600, 300),       # more than six hours: not believed, the exponential wait instead
                                (-60, 300)):           # already past: ignored
            with self.subTest(named=named), tempfile.TemporaryDirectory() as directory:
                run = drive(directory, [(SourceError('official_quota_unavailable'), ahead(named)), native])
                self.assertEqual(run.gaps, [expected])
                if named == 1000:
                    status = run.statuses[0]
                    self.assertEqual((status['state'], status['reason'], status['retry_at']),
                                     ('failing', 'rate_limited', int(run.clock.start) + 1005))
                    self.assertIn('Retry in 1005 seconds', run.output)

    def test_the_status_line_keeps_publishing_while_the_client_waits_out_a_limit(self):
        # A rate limit stops the /usage client, not the status line's own numbers: they cost the service nothing.
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            write_capture(directory, clock.start + 100)       # a capture that is recent for the second pass (t+120)
            run = drive(directory, [limited('official_quota_unavailable', 'rate limit'), native], clock=clock)
        self.assertEqual(run.gaps, [300])                     # the client was not started in between
        self.assertEqual([s['state'] for s in run.statuses[:3]], ['failing', 'ok', 'failing'])
        self.assertEqual(run.files[1]['source'], 'claude_official_statusline')
        self.assertEqual(run.files[2]['source'], 'claude_official_statusline')   # held, aging, not wiped by the skipped poll
        self.assertEqual(run.statuses[2]['retry_at'], int(clock.start) + 300)

    def test_status_alerts_and_trace_use_fixed_words_only(self):
        reads = [native, limited('native_refresh_unconfirmed', 'rate limit'), limited('RuntimeError', 'organization has disabled'), native]
        with tempfile.TemporaryDirectory() as directory:
            run = drive(directory, reads)
            self.assertEqual((Path(directory) / 'offline/claude-reader-status.json').stat().st_mode & 0o777, 0o600)
            text = (Path(directory) / 'offline/claude-reader-status.json').read_text()
        steps = lambda items: [x for i, x in enumerate(items) if i == 0 or x != items[i - 1]]   # one entry per change
        self.assertEqual(steps([(s['state'], s['reason']) for s in run.statuses]),
                         [('ok', None), ('failing', 'rate_limited'), ('failing', 'org_blocked'), ('ok', None)])
        since = {s['reason']: s['since'] for s in run.statuses if s['state'] == 'failing'}
        self.assertEqual(since['rate_limited'], since['org_blocked'])                 # one outage, one start
        self.assertNotIn('PRIVATE', json.dumps(run.statuses) + text)
        self.assertTrue(set(s['reason'] for s in run.statuses) <= set(REASONS) | {None})
        calls = steps([(c.args[0], c.args[1]) for c in run.alerts.observe.call_args_list])
        self.assertEqual(calls, [(True, None), (False, 'rate_limited'), (False, 'org_blocked'), (True, None)])


class StatusLineTests(unittest.TestCase):
    def test_a_recent_complete_capture_stands_in_for_a_client_start_with_its_real_fetch_time(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            write_capture(directory, clock.start - 10)
            run = drive(directory, [], clock=clock, passes=1)
        self.assertEqual(run.attempts, [])                    # no client was started
        published = run.files[0]
        self.assertEqual(published['source'], 'claude_official_statusline')
        self.assertEqual(published['fetched_at'], int(clock.start) - 10)    # the capture's own time, not the poll's
        self.assertEqual(published['origin'], origin_id(ROOT))
        self.assertEqual([w['label'] for w in published['windows']], ['5H', 'WEEK'])
        self.assertEqual(run.statuses[0]['state'], 'ok')
        run.reader.authenticate.assert_called_once()

    def test_the_login_is_proved_at_most_every_ten_minutes_and_a_failed_proof_polls_normally(self):
        clock = Clock()
        refresh = lambda c: write_capture(directory, c.now + 100)     # a capture that is recent at the next pass
        with tempfile.TemporaryDirectory() as directory:
            write_capture(directory, clock.start - 5)
            run = drive(directory, [], clock=clock, passes=7, tick=refresh)    # passes at t, t+120 ... t+720
            self.assertEqual(run.attempts, [])
            self.assertEqual(run.reader.authenticate.call_count, 2)           # t and t+600
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            write_capture(directory, clock.start - 5)
            run = drive(directory, [native], clock=clock, authenticate=SourceError('identity_mismatch'))
        self.assertEqual(len(run.attempts), 1)                # the capture was not trusted: the client was asked
        self.assertEqual(run.files[0]['source'], 'claude_official_cli')

    def test_a_new_client_series_a_model_activity_or_a_different_login_is_never_covered_by_the_status_line(self):
        # AGENTS.md: these blank at once, and a new series gets no help until its screen is reviewed.
        for code in ('unsupported_client_version', 'unexpected_model_activity', 'identity_mismatch'):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                tick = lambda c: write_capture(directory, c.now + 100)       # a capture that is recent at the next pass
                run = drive(directory, [SourceError(code), SourceError(code), native], passes=4, tick=tick)
                self.assertEqual(len(run.attempts), 3)                       # the client was asked again each time, capture or not
                self.assertEqual(run.files[0]['windows'], [])                # blank at once...
                self.assertEqual(run.files[1]['windows'], [])                # ...and still blank beside a perfectly good capture
                self.assertEqual(run.files[2]['source'], 'claude_official_cli')
                self.assertEqual(run.files[3]['source'], 'claude_official_statusline')   # a good client reading ends the embargo

    def test_a_lost_login_is_proved_again_before_the_status_line_is_trusted_again(self):
        clock, ticks = Clock(), []
        with tempfile.TemporaryDirectory() as directory:
            write_capture(directory, clock.start - 5)                        # pass 1 uses it; by pass 2 it is 125 s old: the client runs
            def tick(c):
                ticks.append(c.now)
                if len(ticks) in (2, 3):
                    write_capture(directory, c.now + 100)                    # recent again for passes 3 and 4
            run = drive(directory, [SourceError('subscription_login_required'), native], clock=clock, passes=4, tick=tick,
                        authenticate=[None, SourceError('subscription_login_required')])
            self.assertEqual(run.reader.authenticate.call_count, 2)          # not one proof for ten minutes: the failure reset it
            self.assertEqual(len(run.attempts), 2)
            self.assertEqual(run.files[0]['source'], 'claude_official_statusline')
            self.assertEqual(run.files[2]['source'], 'claude_official_cli')   # the failed proof sent pass 3 to the client

    def test_a_published_capture_names_its_identity_check_honestly(self):
        clock = Clock()
        account = {'key': 'claude', 'alias': 'CLAUDE', 'provider': 'claude', 'source_home': ROOT, 'email': EMAIL}
        with tempfile.TemporaryDirectory() as directory:
            write_capture(directory, clock.start - 5)
            run = drive(directory, [], clock=clock, passes=1, account=account)
            row = fetch_local(account, Path(directory) / 'offline', official_claude=True)
        published = run.files[0]
        self.assertTrue(published['identity_verified'])
        self.assertEqual(published['identity_checked_at'], int(clock.start))
        self.assertEqual(published['origin'], origin_id(ROOT, EMAIL))
        self.assertNotIn(EMAIL, json.dumps(published))
        # The monitor accepts it as an official reading and says where it came from.
        self.assertEqual(row['quota_origin'], 'claude_official_statusline')
        self.assertEqual(row['windows'][-1]['used_percent'], 41)
        self.assertTrue(row['identity_verified'])

    def test_an_old_incomplete_foreign_or_expired_capture_is_not_used(self):
        now = int(time.time())
        def record(**change):
            with tempfile.TemporaryDirectory() as directory:
                write_capture(directory, now - 5, **{k: v for k, v in change.items() if k in ('week', 'five', 'reset_in', 'source_home')})
                data = json.loads((Path(directory) / 'offline/claude.json').read_text())
            data.update({k: v for k, v in change.items() if k in ('source', 'origin', 'fetched_at')})
            return statusline_record(data, ROOT, None, now)
        self.assertEqual([w['label'] for w in record()['windows']], ['5H', 'WEEK'])
        self.assertEqual(record()['fetched_at'], now - 5)
        for change in ({'fetched_at': now - STATUSLINE_MAX_AGE - 1}, {'fetched_at': now + 30},     # old, or from the future
                       {'week': False}, {'five': False},                                            # one window only
                       {'reset_in': -10},                                                           # resets already passed
                       {'source_home': '/another/home'}, {'source': 'local_cache_unknown'}, {'fetched_at': None}):
            self.assertIsNone(record(**change), change)
        self.assertIsNone(statusline_record(None, ROOT, None, now))
        self.assertIsNone(statusline_record({}, ROOT, None, now))


class TimingTests(unittest.TestCase):
    def test_a_normal_reading_never_ages_past_the_fresh_tier_before_the_next_one_lands(self):
        # Tony, 2026-11-03: polling every 120 s must not make the dot a regular sight (fresh tier 180 s).
        collector = load('claude_collector_timing')
        # Worst honest case for a client start: the wait, then authenticate (20 s timeout) and the client (30 s deadline).
        self.assertLess(collector.POLL_SECONDS + 20 + 30, OFFICIAL_FRESH_SECONDS)
        self.assertEqual(collector.next_wait({'fetched_at': 1000}, 1002), 120)          # a reading just fetched: the normal wait
        # A reading that is already old when published (a client cache another process fetched, up to REUSE_SECONDS, or a
        # status-line capture, up to STATUSLINE_MAX_AGE) gets a shorter wait so the next one lands before 180 s.
        self.assertLessEqual(REUSE_SECONDS, STATUSLINE_MAX_AGE)
        for age in range(0, STATUSLINE_MAX_AGE + 1):
            wait = collector.next_wait({'fetched_at': 1000 - age}, 1000)
            self.assertLessEqual(age + wait + collector.READ_SECONDS, OFFICIAL_FRESH_SECONDS, age)
            self.assertGreaterEqual(wait, 30)
        self.assertEqual(collector.next_wait({'fetched_at': 0}, 1000), 30)               # never a tight loop

    def test_the_loop_replaces_every_normal_reading_before_it_ages_past_the_fresh_tier(self):
        # The actual schedule: read (duration), publish, wait, read again. `lag` is how old the reading already was when it landed
        # (a client cache another process had fetched, REUSE_SECONDS at most; a status-line capture, STATUSLINE_MAX_AGE at most).
        for duration, lag in ((5, 0), (15, 0), (30, 0), (5, 45), (15, 45), (15, 90), (5, 100)):
            with self.subTest(duration=duration, lag=lag), tempfile.TemporaryDirectory() as directory:
                clock, landed = Clock(), []
                def read(now):
                    clock.now += duration
                    landed.append((clock.now, clock.now - lag))
                    return native(clock.now, age=lag)
                drive(directory, [read] * 6, clock=clock)
                worst = max(b[0] - a[1] for a, b in zip(landed, landed[1:]))      # its age the moment the next one lands
                self.assertLessEqual(worst, OFFICIAL_FRESH_SECONDS)

    def test_the_loop_waits_two_minutes_and_a_reused_cache_shortens_the_next_wait(self):
        reads = [native, lambda now: native(now, age=90), native]
        with tempfile.TemporaryDirectory() as directory:
            run = drive(directory, reads)
        self.assertEqual(run.waits[:3], [120, 75, 120])


class RetryAtTests(unittest.TestCase):
    def local(self, now, hours=0, minutes=0):
        return datetime.fromtimestamp(now) + timedelta(hours=hours, minutes=minutes)

    def test_twelve_and_twenty_four_hour_forms_are_read_as_local_time(self):
        now = int(time.time())
        soon = self.local(now, hours=2)
        expected = int(soon.replace(second=0, microsecond=0).timestamp())
        for text in (soon.strftime('Rate limited until %I:%M %p'), soon.strftime('rate limited until %I:%M%p').lower(),
                     soon.strftime('Rate limited until %H:%M'), soon.strftime('Rate limited until %I:%M %p (Europe/Madrid)'),
                     soon.strftime('  Rate-limited until %H:%M:00 today.'), soon.strftime('Rate limited until %I:%M %p, try again later')):
            with self.subTest(text=text):
                self.assertEqual(rate_limited_until(text, now), expected)
        top = self.local(now, hours=3).replace(minute=0, second=0, microsecond=0)
        self.assertEqual(rate_limited_until(f"rate limited until {int(top.strftime('%I'))}{top.strftime('%p').lower()}", now),
                         int(top.timestamp()))
        self.assertEqual(type(rate_limited_until(soon.strftime('Rate limited until %H:%M'), now)), int)

    def test_dates_tomorrow_and_midnight_are_understood(self):
        base_time = datetime(2026, 11, 3, 23, 50, 0)
        now = int(base_time.timestamp())
        after_midnight = int(datetime(2026, 11, 4, 0, 10).timestamp())
        self.assertEqual(rate_limited_until('Rate limited until 12:10 AM', now), after_midnight)
        self.assertEqual(rate_limited_until('Rate limited until 00:10', now), after_midnight)
        self.assertEqual(rate_limited_until('Rate limited until tomorrow at 12:10 am', now), after_midnight)
        self.assertEqual(rate_limited_until('Rate limited until Nov 4, 12:10 AM', now), after_midnight)
        self.assertEqual(rate_limited_until('Rate limited until 4 Nov 00:10', now), after_midnight)
        self.assertEqual(rate_limited_until('Rate limited until November 4th, 12:10 am', now), after_midnight)
        december = int(datetime(2026, 12, 31, 23, 50).timestamp())
        self.assertEqual(rate_limited_until('Rate limited until Jan 1, 12:10 AM', december), int(datetime(2027, 1, 1, 0, 10).timestamp()))

    def test_unparsable_past_and_distant_moments_are_ignored(self):
        now = int(datetime(2026, 11, 3, 12, 0, 0).timestamp())
        for text in ('Rate limited until soon', 'Rate limited until', 'Rate limited until 25:99', 'Rate limited until 13:00 PM',
                     'Rate limited until 0 pm', 'Rate limited until 11:55',          # five minutes ago: it would mean tomorrow
                     'Rate limited until 7:30 PM',                                   # 7.5 hours ahead: more than six
                     'Rate limited until Feb 30, 1:00 PM', 'Rate limited until Dec 25, 1:00 PM', 'nothing to see here',
                     'You are rate limited. Try again in a while.', ''):
            with self.subTest(text=text):
                self.assertIsNone(rate_limited_until(text, now))
        self.assertEqual(rate_limited_until('Rate limited until 6:00 PM', now), int(datetime(2026, 11, 3, 18, 0).timestamp()))   # exactly 6 h
        self.assertIsNone(rate_limited_until('Rate limited until 6:01 PM', now))

    def read_with_screen(self, extra, block=None):
        """Run the real reader against a stand-in client whose usage view prints `extra` and writes no new cache."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'claude-home'
            root.mkdir()
            script = Path(directory) / 'fake-claude'
            script.write_text(base.FAKE_CLIENT.replace('PYTHON', sys.executable))
            script.chmod(0o700)
            reader = ClaudeUsageReader(root, Path(directory) / 'workspace')
            reader.cli = str(script)
            reader.env.update(FAKE_VERSION='2.1.296', FAKE_MARKER=str(Path(directory) / 'sent'), FAKE_ROOT=str(root),
                              FAKE_NO_WRITE='1', FAKE_STAY='1', FAKE_EXTRA=extra)
            if block:
                reader.env['FAKE_BLOCK'] = block
            with patch.object(reader, 'authenticate'):
                try:
                    reader.read()
                except SourceError as error:
                    return error.code, reader.trace
            return None, reader.trace

    def test_the_reader_keeps_only_a_number_from_the_screen_and_resets_its_trace(self):
        soon = datetime.now() + timedelta(hours=2)
        code, trace = self.read_with_screen('Rate limited until ' + soon.strftime('%I:%M %p') + '  account PRIVATE-DETAIL')
        self.assertEqual(code, 'official_quota_unavailable')
        self.assertEqual(type(trace['retry_at']), int)
        self.assertLess(abs(trace['retry_at'] - soon.replace(second=0, microsecond=0).timestamp()), 2)
        self.assertIn('rate limit', trace['hints'])
        self.assertNotIn('PRIVATE', json.dumps(trace))
        code, trace = self.read_with_screen('All good here')
        self.assertNotIn('retry_at', trace)
        # A failure before the client opens must not inherit the last run's words.
        with tempfile.TemporaryDirectory() as directory:
            reader = ClaudeUsageReader(Path(directory) / 'home', Path(directory) / 'workspace')
            reader.trace = {'hints': ['rate limit'], 'retry_at': 123}
            with patch.object(reader, 'authenticate', side_effect=SourceError('subscription_login_required')):
                with self.assertRaises(SourceError):
                    reader.read()
            self.assertEqual(reader.trace, {})

    def test_the_organization_block_is_recognised_from_the_real_message(self):
        from token_tv.reader_status import reason_for
        code, trace = self.read_with_screen('', block='Your organization has disabled Claude subscription access for Claude Code')
        self.assertEqual(code, 'client_not_ready')
        self.assertIn('organization has disabled', trace['hints'])
        self.assertEqual(reason_for(code, trace['hints']), 'org_blocked')
        # A message wrapped over two lines still counts.
        code, trace = self.read_with_screen('', block='Your organization has\ndisabled Claude subscription access')
        self.assertIn('organization has disabled', trace['hints'])


class BackupCoversTheAlertTests(unittest.TestCase):
    def test_a_fresh_browser_reading_of_this_account_means_the_display_is_not_without_data(self):
        collector = load('claude_collector_backup')
        now = 1_800_000_000
        reading = lambda **extra: {'origin': 'same', 'windows': [{'label': 'WEEK'}], 'fetched_at': now - 100, **extra}
        with tempfile.TemporaryDirectory() as directory:
            offline = Path(directory)
            self.assertFalse(collector.covered_by_backup(offline, 'same', now))                       # no backup at all
            for record, covered in ((reading(), True), (reading(origin='other'), False), (reading(windows=[]), False),
                                    (reading(fetched_at=now - 481), False), (reading(fetched_at=now + 60), False)):
                (offline / 'claude-browser.json').write_text(json.dumps(record))
                with self.subTest(record=record):
                    self.assertEqual(collector.covered_by_backup(offline, 'same', now), covered)


if __name__ == '__main__':
    unittest.main()
