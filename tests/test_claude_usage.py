import json
import importlib.util
import io
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from token_tv.claude_usage import ClaudeUsageReader, native_record, reader_env
from token_tv.local_usage import local_row
from token_tv.live import DisplayPreferences, handler
from token_tv.sources import SourceError


FAKE_CLIENT = '''#!PYTHON
import json, os, select, sys, time
screen = ('Claude Code v' + os.environ['FAKE_VERSION'] + '\\n'
          'warning: Safe mode: all customizations are disabled\\n'
          + os.getcwd() + '\\nmanual mode on\\n')
if os.environ.get('FAKE_SECOND_VERSION'):
    # A second header after a screen clear, without any safe-mode marker.
    screen += '\\x1b[2J\\x1b[HClaude Code v' + os.environ['FAKE_SECOND_VERSION'] + '\\n'
sys.stdout.write(screen + '$$ ')
sys.stdout.flush()
if not select.select([sys.stdin], [], [], 3)[0]:
    sys.exit(0)
if sys.stdin.readline().strip() == '/usage':
    open(os.environ['FAKE_MARKER'], 'w').close()
    if os.environ.get('FAKE_SILENT_CACHE'):
        print('Total cost: $0.00', flush=True)
        time.sleep(.5)
    now = time.time()
    when = int(now) + 3600
    if os.environ.get('FAKE_NO_WRITE'):
        # The client found a young cache and reused it: it prints the usage view but writes no newer date.
        print('Total cost: $0.00', flush=True)
        time.sleep(float(os.environ.get('FAKE_STAY', '40')))
        sys.exit(0)
    cache = {'oauthAccount': {'accountUuid': 'demo-owner'},
             'cachedUsageUtilization': {'accountUuid': 'demo-owner', 'fetchedAtMs': now * 1000,
                 'utilization': {'five_hour': {'utilization': 5, 'resets_at': when},
                                 'seven_day': {'utilization': 66, 'resets_at': when + 86400}}}}
    with open(os.path.join(os.environ['FAKE_ROOT'], '.claude.json'), 'w') as handle:
        json.dump(cache, handle)
    if not os.environ.get('FAKE_SILENT_CACHE'):
        print('Total cost: $0.00')
        sys.stdout.flush()
    time.sleep(5)
'''


class ClaudeUsageTests(unittest.TestCase):
    def read_with_reused_cache(self, age):
        """The stand-in client never fetches; the cache on disk is `age` seconds old when the run starts."""
        import time
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'claude-home'
            root.mkdir()
            script = Path(directory) / 'fake-claude'
            script.write_text(FAKE_CLIENT.replace('PYTHON', sys.executable))
            script.chmod(0o700)
            data = self.cache()
            when = int(time.time()) + 7200
            data['cachedUsageUtilization'].update(fetchedAtMs=(time.time() - age) * 1000)
            data['cachedUsageUtilization']['utilization'] = {'five_hour': {'utilization': 5, 'resets_at': when},
                                                             'seven_day': {'utilization': 66, 'resets_at': when + 86400}}
            (root / '.claude.json').write_text(json.dumps(data))
            reader = ClaudeUsageReader(root, Path(directory) / 'workspace')
            reader.cli = str(script)
            reader.env.update(FAKE_VERSION='2.1.296', FAKE_MARKER=str(Path(directory) / 'sent'), FAKE_ROOT=str(root),
                              FAKE_NO_WRITE='1', FAKE_STAY='40')
            began = time.monotonic()
            with patch.object(reader, 'authenticate'), patch('token_tv.claude_usage.REUSE_AFTER', 1):
                record = reader.read()
            return record, time.monotonic() - began

    def test_a_cache_the_client_reused_is_accepted_while_young_and_refused_once_old(self):
        young, seconds = self.read_with_reused_cache(25)
        self.assertFalse(young['stale'])
        self.assertLess(seconds, 10)                                              # no waiting out the full 30 s
        self.assertEqual(young['windows'][-1]['used_percent'], 66)
        self.assertLess(abs(young['fetched_at'] - (__import__('time').time() - 25)), 5)   # still dated when it was really fetched
        old, _ = self.read_with_reused_cache(150)
        self.assertTrue(old['stale'])                                             # older than 90 s: not a reading to show

    def read_with_fake_client(self, version, second_version=None, silent_cache=False):
        """Run the real reader against a stand-in client; return (result, usage_was_sent)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'claude-home'
            root.mkdir()
            marker = Path(directory) / 'usage-sent'
            script = Path(directory) / 'fake-claude'
            script.write_text(FAKE_CLIENT.replace('PYTHON', sys.executable))
            script.chmod(0o700)
            reader = ClaudeUsageReader(root, Path(directory) / 'workspace')
            reader.cli = str(script)
            reader.env.update(FAKE_VERSION=version, FAKE_MARKER=str(marker), FAKE_ROOT=str(root))
            if second_version:
                reader.env['FAKE_SECOND_VERSION'] = second_version
            if silent_cache:
                reader.env['FAKE_SILENT_CACHE'] = '1'
            with patch.object(reader, 'authenticate'):
                try:
                    result = reader.read()
                except SourceError as error:
                    result = error.code
            return result, marker.exists()

    def test_fresh_cache_after_last_terminal_output_is_not_discarded_as_stale(self):
        record, sent = self.read_with_fake_client('2.1.296', silent_cache=True)
        self.assertTrue(sent)
        self.assertFalse(record['stale'])
        self.assertEqual(record['windows'][-1]['used_percent'], 66)

    def test_patch_releases_of_the_reviewed_series_still_receive_usage(self):
        for version in ('2.1.293', '2.1.296', '2.1.350'):
            with self.subTest(version=version):
                record, sent = self.read_with_fake_client(version)
                self.assertTrue(sent)
                self.assertEqual([w['label'] for w in record['windows']], ['5H', 'WEEK'])
                self.assertFalse(record['stale'])

    def test_unreviewed_client_series_receives_no_command_and_says_why(self):
        for version in ('2.2.0', '3.0.1', '1.9.9'):
            with self.subTest(version=version):
                result, sent = self.read_with_fake_client(version)
                self.assertEqual(result, 'unsupported_client_version')
                self.assertFalse(sent)

    def test_a_later_screen_is_recognized_on_its_own_not_by_earlier_markers(self):
        # Safe-mode markers from an earlier screen must not vouch for a different
        # header drawn after a screen clear, whatever its version.
        for first, second, code in (('2.1.296', '2.2.0', 'unsupported_client_version'),
                                    ('2.1.296', '2.1.297', 'client_not_ready')):
            with self.subTest(second=second):
                result, sent = self.read_with_fake_client(first, second)
                self.assertEqual(result, code)
                self.assertFalse(sent)

    def test_collector_logs_the_fixed_failure_reason_but_never_error_text(self):
        spec = importlib.util.spec_from_file_location('claude_collector_reason',
            Path(__file__).parents[1] / 'scripts/claude_usage_collector.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        account = {'key': 'claude', 'alias': 'CLAUDE', 'provider': 'claude',
                   'source_home': '/tmp/demo-claude'}
        config = {'automatic_claude_usage': True, 'accounts': [account]}
        for failure, expected in ((SourceError('unsupported_client_version'), 'unsupported_client_version'),
                                  (RuntimeError('PRIVATE ERROR'), 'RuntimeError')):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                reader = MagicMock()
                reader.read.side_effect = [failure]
                class Event:
                    done = False
                    def is_set(self): return self.done
                    def set(self): self.done = True
                    def wait(self, seconds): self.done = True
                with patch('sys.argv', ['collector', '--config', str(Path(directory) / 'config.json')]), \
                     patch.object(collector, 'load_config', return_value=config), \
                     patch.object(collector, 'ClaudeUsageReader', return_value=reader), \
                     patch.object(collector, 'notify_display', return_value=True), \
                     patch.object(collector.threading, 'Event', Event), \
                     patch.object(collector.signal, 'signal'), \
                     patch('sys.stdout', new_callable=io.StringIO) as output:
                    collector.main()
                self.assertIn(f'({expected})', output.getvalue())
                self.assertNotIn('PRIVATE', output.getvalue())

    def cache(self):
        return {'oauthAccount': {'accountUuid': 'demo-owner'},
                'cachedUsageUtilization': {'accountUuid': 'demo-owner', 'fetchedAtMs': 1000000,
                    'utilization': {'five_hour': {'utilization': 5, 'resets_at': 2000},
                                    'seven_day': {'utilization': 66, 'resets_at': 3000}}}}

    def test_original_fetch_date_is_preserved_and_failed_refresh_is_old(self):
        record = native_record(self.cache(), '/tmp/demo-claude', since=1010, now=1020)
        self.assertEqual(record['fetched_at'], 1000)
        self.assertTrue(record['stale'])
        row = local_row({'key':'demo', 'alias':'DEMO', 'provider':'claude'}, record, now=1020)
        self.assertEqual(row['status'], 'quota_unavailable')
        self.assertEqual(row['windows'], [])
        self.assertEqual(row['last_success_at'], 1000)

    def test_zero_utilization_is_data_and_missing_is_not_zero(self):
        data = self.cache()
        data['cachedUsageUtilization']['utilization']['five_hour']['utilization'] = 0
        record = native_record(data, '/tmp/demo-claude', since=999, now=1001)
        self.assertEqual(record['windows'][0]['used_percent'], 0)
        self.assertFalse(record['stale'])
        self.assertIsNone(native_record({}, '/tmp/demo-claude', since=999, now=1001))

    def test_partial_malformed_quota_does_not_hide_a_failed_weekly_reading(self):
        for invalid in ('invalid', {'utilization': 'invalid', 'resets_at': 3000},
                        {'utilization': 66, 'resets_at': None}):
            with self.subTest(invalid=invalid):
                data = self.cache()
                data['cachedUsageUtilization']['utilization']['seven_day'] = invalid
                self.assertIsNone(native_record(data, '/tmp/demo-claude', since=999, now=1001))

    def test_collector_retries_each_minute_after_failure_or_a_lost_notification(self):
        spec = importlib.util.spec_from_file_location('claude_collector_recovery',
            Path(__file__).parents[1] / 'scripts/claude_usage_collector.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            account = {'key': 'claude', 'alias': 'CLAUDE', 'provider': 'claude',
                       'source_home': '/tmp/demo-claude'}
            config = {'automatic_claude_usage': True, 'accounts': [account]}
            first = native_record(self.cache(), account['source_home'], since=999, now=1001)
            changed = self.cache()
            changed['cachedUsageUtilization']['utilization']['seven_day']['utilization'] = 71
            last = native_record(changed, account['source_home'], since=999, now=1001)
            reader = MagicMock()
            reader.read.side_effect = [first, RuntimeError('PRIVATE ERROR'), last]
            observations, waits = [], []
            class Event:
                done = False
                def is_set(self): return self.done
                def set(self): self.done = True
                def wait(self, seconds):
                    waits.append(seconds)
                    self.done = len(observations) == 3
            def notified():
                observations.append(json.loads((Path(directory) / 'offline/claude-official.json').read_text()))
                return len(observations) != 1
            with patch('sys.argv', ['collector', '--config', str(path)]), \
                 patch.object(collector, 'load_config', return_value=config), \
                 patch.object(collector, 'ClaudeUsageReader', return_value=reader), \
                 patch.object(collector, 'notify_display', side_effect=notified), \
                 patch.object(collector.threading, 'Event', Event), \
                 patch.object(collector.signal, 'signal'), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                collector.main()
            self.assertNotIn('PRIVATE', output.getvalue())
            self.assertIn('recovered with a fresh reading', output.getvalue())
            self.assertEqual(waits, [60, 60, 60])
            self.assertEqual([r['windows'][-1]['used_percent'] if r['windows'] else None
                              for r in observations], [66, None, 71])
            self.assertTrue(all(r['source'] == 'claude_official_cli' for r in observations))

    def load_collector(self, name):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts/claude_usage_collector.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        return collector

    def run_collector(self, collector, directory, reads, trace=None, waits=None):
        """Run the loop once per entry of `reads` (records or exceptions); return what each pass left in the shared file."""
        account = {'key': 'claude', 'alias': 'CLAUDE', 'provider': 'claude', 'source_home': '/tmp/demo-claude'}
        config = {'automatic_claude_usage': True, 'accounts': [account]}
        reader = MagicMock()
        reader.read.side_effect = reads
        reader.trace = trace if trace is not None else {}
        seen = []
        class Event:
            done = False
            def is_set(self): return self.done
            def set(self): self.done = True
            def wait(self, seconds):
                if waits is not None:
                    waits.append(seconds)
                path = Path(directory) / 'offline/claude-official.json'
                seen.append(json.loads(path.read_text()) if path.exists() else None)
                self.done = len(seen) == len(reads)
        with patch('sys.argv', ['collector', '--config', str(Path(directory) / 'config.json')]), \
             patch.object(collector, 'load_config', return_value=config), \
             patch.object(collector, 'ClaudeUsageReader', return_value=reader), \
             patch.object(collector, 'notify_display', return_value=True), \
             patch.object(collector.threading, 'Event', Event), \
             patch.object(collector.signal, 'signal'), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            collector.main()
        return seen, output.getvalue()

    def fresh_record(self, age=0):
        import time
        data = self.cache()
        when = int(time.time()) + 7200
        data['cachedUsageUtilization'].update(fetchedAtMs=(time.time() - age) * 1000)
        data['cachedUsageUtilization']['utilization'] = {'five_hour': {'utilization': 5, 'resets_at': when},
                                                         'seven_day': {'utilization': 66, 'resets_at': when + 86400}}
        return native_record(data, '/tmp/demo-claude', since=time.time() - age - 5)

    def test_one_failed_poll_keeps_a_reading_younger_than_the_hold_but_not_an_older_one(self):
        collector = self.load_collector('claude_collector_hold')
        for age, kept in ((5, True), (collector.HOLD_SECONDS + 10, False)):
            with self.subTest(age=age), tempfile.TemporaryDirectory() as directory:
                good = self.fresh_record(age)
                seen, output = self.run_collector(collector, directory, [good, SourceError('native_refresh_unconfirmed')])
                self.assertEqual(seen[0]['windows'][-1]['used_percent'], 66)
                self.assertEqual(bool(seen[1]['windows']), kept)               # the reading stays only while inside the limit
                self.assertEqual('keeping the last reading' in output, kept)
                if kept:
                    self.assertEqual(seen[1]['fetched_at'], seen[0]['fetched_at'])   # never re-dated: its own fetch time rules
        self.assertLess(collector.HOLD_SECONDS, 180)                              # always less than the monitor's own 180 s limit

    def test_a_different_login_or_client_series_blanks_at_once_even_with_a_fresh_reading(self):
        collector = self.load_collector('claude_collector_blank')
        for code in ('identity_mismatch', 'unsupported_client_version', 'unexpected_model_activity'):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                seen, output = self.run_collector(collector, directory, [self.fresh_record(), SourceError(code)])
                self.assertEqual(seen[1]['windows'], [])
                self.assertIn('shown as unknown', output)

    def test_a_lost_login_keeps_the_reading_only_until_the_hold_runs_out(self):
        collector = self.load_collector('claude_collector_login')
        with tempfile.TemporaryDirectory() as directory:
            seen, output = self.run_collector(collector, directory, [self.fresh_record(), SourceError('subscription_login_required')])
            self.assertTrue(seen[1]['windows'])
            self.assertIn('(subscription_login_required)', output)

    def test_rate_limited_usage_waits_longer_and_resumes_normal_polling_after_recovery(self):
        collector = self.load_collector('claude_collector_backoff')
        limited = lambda: SourceError('official_quota_unavailable')
        waits = []
        with tempfile.TemporaryDirectory() as directory:
            seen, _ = self.run_collector(collector, directory,
                [limited(), limited(), limited(), limited(), self.fresh_record(), limited(),
                 SourceError('client_not_ready')],
                trace={'hints': ['rate limit', 'error']}, waits=waits)
        self.assertEqual(waits, [300, 600, 900, 900, 60, 300, 60])
        self.assertTrue(all(not row['windows'] for row in seen[:4]))
        self.assertTrue(seen[4]['windows'])

    def test_the_failure_trace_keeps_only_fixed_words_numbers_and_flags(self):
        collector = self.load_collector('claude_collector_trace')
        trace = {'seconds': 30.0, 'sent': True, 'model_free': True, 'client_exited': False, 'screen_bytes': 1234,
                 'hints': ['current week']}
        with tempfile.TemporaryDirectory() as directory:
            self.run_collector(collector, directory, [RuntimeError('PRIVATE ERROR user@example.com')], trace)
            lines = (Path(directory) / 'state/claude-reader/failures.jsonl').read_text().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry['reason'], 'RuntimeError')
            self.assertEqual(entry['hints'], ['current week'])
            self.assertNotIn('PRIVATE', lines[0])
            self.assertNotIn('example.com', lines[0])
            self.assertEqual((Path(directory) / 'state/claude-reader/failures.jsonl').stat().st_mode & 0o777, 0o600)

    def test_the_reader_traces_a_run_without_keeping_any_screen_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'claude-home'
            root.mkdir()
            script = Path(directory) / 'fake-claude'
            script.write_text(FAKE_CLIENT.replace('PYTHON', sys.executable))
            script.chmod(0o700)
            reader = ClaudeUsageReader(root, Path(directory) / 'workspace')
            reader.cli = str(script)
            reader.env.update(FAKE_VERSION='2.1.296', FAKE_MARKER=str(Path(directory) / 'sent'), FAKE_ROOT=str(root))
            with patch.object(reader, 'authenticate'):
                reader.read()
            self.assertEqual(set(reader.trace), {'seconds', 'sent', 'model_free', 'client_exited', 'screen_bytes', 'hints',
                                                 'cache_age_at_end', 'cache_age_at_start'})
            self.assertTrue(reader.trace['sent'] and reader.trace['model_free'])
            self.assertTrue(set(reader.trace['hints']) <= set(__import__('token_tv.claude_usage', fromlist=['x']).SCREEN_HINTS))

    def test_foreign_expired_and_future_native_cache_is_rejected(self):
        data = self.cache()
        data['cachedUsageUtilization']['accountUuid'] = 'another-owner'
        self.assertIsNone(native_record(data, '/tmp/demo', 999, now=1001))
        data = self.cache()
        self.assertIsNone(native_record(data, '/tmp/demo', 999, now=5000))
        self.assertIsNone(native_record(data, '/tmp/demo', 999, now=900))
        data['cachedUsageUtilization']['utilization']['seven_day']['resets_at'] = 900
        self.assertIsNone(native_record(data, '/tmp/demo', 999, now=1001))

    def test_a_rolled_over_five_hour_window_is_dropped_but_the_week_survives(self):
        # The five-hour window renews every 5 h; right after that, its reset is
        # missing or in the past. That used to void the whole reading (and the
        # display) for a minute or more, although only the 5H number is unknown.
        for reset in (900, None):
            with self.subTest(five_hour_reset=reset):
                data = self.cache()
                data['cachedUsageUtilization']['utilization']['five_hour']['resets_at'] = reset
                record = native_record(data, '/tmp/demo', 999, now=1001)
                self.assertEqual([w['label'] for w in record['windows']], ['WEEK'])
                self.assertEqual(record['windows'][0]['used_percent'], 66)
                self.assertFalse(record['stale'])

    def test_the_week_itself_must_still_have_a_live_reset(self):
        for reset in (900, None):
            with self.subTest(week_reset=reset):
                data = self.cache()
                data['cachedUsageUtilization']['utilization']['seven_day']['resets_at'] = reset
                self.assertIsNone(native_record(data, '/tmp/demo', 999, now=1001))

    def test_api_or_third_party_auth_never_qualifies_for_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = ClaudeUsageReader('/tmp/demo-claude', directory)
            for method, provider in (('api_key','firstParty'), ('claude.ai','thirdParty')):
                result = SimpleNamespace(returncode=0, stdout=json.dumps(
                    {'loggedIn':True,'authMethod':method,'apiProvider':provider,'subscriptionType':'max'}))
                with patch('token_tv.claude_usage.subprocess.run', return_value=result):
                    with self.assertRaises(SourceError):
                        reader.authenticate()
            result = SimpleNamespace(returncode=0, stdout=json.dumps(
                {'loggedIn':True,'authMethod':'claude.ai','apiProvider':'firstParty','subscriptionType':'max'}))
            with patch('token_tv.claude_usage.subprocess.run', return_value=result):
                reader.authenticate()

    def test_disabled_collector_never_creates_an_official_client(self):
        spec = importlib.util.spec_from_file_location('claude_collector_disabled',
            Path(__file__).parents[1]/'scripts/claude_usage_collector.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        with patch('sys.argv',['collector']), \
             patch.object(collector,'load_config',return_value={'automatic_claude_usage':False}), \
             patch.object(collector,'ClaudeUsageReader') as reader:
            collector.main()
        reader.assert_not_called()

    def test_usage_notification_only_refreshes_local_cache_and_rejects_foreign_origin(self):
        for local in (True, False):
            with self.subTest(local_only=local), tempfile.TemporaryDirectory() as directory:
                prefs = DisplayPreferences(Path(directory)/'config.json',
                                           {'accounts':[], 'local_only':local})
                store = MagicMock(snapshot=lambda: {'accounts':{},'updated_at':0})
                server = ThreadingHTTPServer(('127.0.0.1',0),handler(store,prefs))
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                endpoint = f'http://127.0.0.1:{server.server_port}/display/usage-refresh'
                try:
                    request = Request(endpoint,data=b'{}',headers={'Content-Type':'application/json'})
                    if local:
                        with urlopen(request) as response:
                            self.assertEqual(response.status,200)
                        self.assertTrue(prefs.consume_quota_refresh())
                    else:
                        with self.assertRaises(HTTPError) as error:
                            urlopen(request)
                        self.assertEqual(error.exception.code,400)
                    for body, origin in ((b'{"query_provider":true}',None),(b'{}','https://attacker.example')):
                        headers={'Content-Type':'application/json'}
                        if origin:headers['Origin']=origin
                        with self.assertRaises(HTTPError) as error:
                            urlopen(Request(endpoint,data=body,headers=headers))
                        self.assertIn(error.exception.code,(400,403))
                        self.assertFalse(prefs.consume_quota_refresh())
                    store.refresh.assert_not_called()
                finally:
                    server.shutdown();server.server_close();thread.join()

    def test_stop_between_authentication_and_terminal_starts_no_new_client(self):
        event = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            reader = ClaudeUsageReader('/tmp/demo-claude', directory)
            with patch.object(reader, 'authenticate', side_effect=event.set), \
                 patch('token_tv.claude_usage.subprocess.Popen') as process:
                with self.assertRaises(SourceError) as error:
                    reader.read(cancel_event=event)
        self.assertEqual(error.exception.code, 'cancelled')
        process.assert_not_called()

    def test_refresh_arriving_during_consumption_remains_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = DisplayPreferences(Path(directory)/'config.json', {'accounts':[]})
            original_lock = prefs.lock
            requested = []
            class InterleavingLock:
                def __enter__(self):
                    original_lock.acquire()
                def __exit__(self, *args):
                    original_lock.release()
                    if not requested:
                        requested.append(True)
                        prefs.request_quota_refresh()
            prefs.lock = InterleavingLock()
            self.assertFalse(prefs.consume_quota_refresh())
            self.assertTrue(prefs.consume_quota_refresh())
            self.assertFalse(prefs.consume_quota_refresh())

    def test_inherited_secrets_providers_and_injection_are_removed(self):
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY':'fake-secret',
                'ANTHROPIC_BASE_URL':'https://example.invalid', 'NODE_OPTIONS':'fake-injection',
                'HTTPS_PROXY':'http://example.invalid', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1'}):
            env = reader_env('/tmp/demo-claude')
        for key in ('ANTHROPIC_API_KEY','ANTHROPIC_BASE_URL','NODE_OPTIONS','HTTPS_PROXY',
                    'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'):
            self.assertNotIn(key, env)
        self.assertEqual(env['DISABLE_TELEMETRY'], '1')
