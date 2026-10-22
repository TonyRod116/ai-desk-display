import importlib.util
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import urlopen

from token_tv import cli, codex_resets, live
from token_tv.local_usage import atomic_json, fetch_local, local_row, origin_id
from token_tv.personal_faces import remaining_reading
from token_tv.reset_balances import ResetBalances
from token_tv.state import UsageStore


def limits(used=0, reset=10000, duration=10080):
    return {'limitId': 'codex', 'primary': {'usedPercent': used,
            'windowDurationMins': duration, 'resetsAt': reset}, 'secondary': None}


def record(root, used=0, fetched=1000):
    return {'fetched_at': fetched, 'source': 'codex_official_cli', 'origin': origin_id(root),
            'windows': [{'label': 'WEEK', 'used_percent': used, 'resets_at': 10000,
                         'duration_minutes': 10080}], 'stale': False, 'ordinary_usage_allowed': True}


def account(root):
    return {'key': 'codex_a', 'alias': 'CODEX', 'provider': 'codex', 'source_home': str(root)}


def collector():
    path = Path(__file__).parents[1] / 'scripts/codex_reset_collector.py'
    spec = importlib.util.spec_from_file_location('codex_usage_collector_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexUsageTests(unittest.TestCase):
    def test_quota_and_hearts_share_one_account_get_with_no_model_or_redemption(self):
        rpc = MagicMock()
        rpc.call.side_effect = [{}, {'account': {'type': 'chatgpt'}},
                                {'account': {'type': 'chatgpt'}},
                                {'rateLimits': limits(), 'ordinaryUsageAllowed': True, 'rateLimitResetCredits': {'availableCount': 0},
                                 'accountId': 'PRIVATE-ACCOUNT', 'secret': 'PRIVATE-TOKEN'}]
        rpc.call.side_effect = list(rpc.call.side_effect) + [{'account': {'type': 'chatgpt'}}]
        with patch.object(codex_resets, 'RPC', return_value=rpc), patch.object(codex_resets.time, 'time', return_value=1000):
            reader = codex_resets.CodexResetReader('/example/codex')
            result = reader.read_snapshot()
            reader.close()
        self.assertEqual(result['available_resets'], 0)
        self.assertEqual(result['quota']['windows'][0]['used_percent'], 0)
        self.assertNotIn('PRIVATE-', json.dumps(result))
        self.assertEqual([c.args[0] for c in rpc.call.call_args_list],
                         ['initialize', 'account/read', 'account/read', 'account/rateLimits/read', 'account/read'])

    def test_native_account_change_to_api_auth_prevents_a_quota_request(self):
        rpc = MagicMock()
        rpc.call.side_effect = [{}, {'account': {'type': 'chatgpt'}}, {'account': {'type': 'apiKey'}}]
        with patch.object(codex_resets, 'RPC', return_value=rpc):
            reader = codex_resets.CodexResetReader('/example/codex')
            with self.assertRaises(codex_resets.SourceError):
                reader.read_snapshot()
            reader.close()
        self.assertNotIn('account/rateLimits/read', [c.args[0] for c in rpc.call.call_args_list])

    def test_codex_bucket_wins_over_other_provider_limits(self):
        other = dict(limits(100), limitId='other-model')
        data = {'rateLimits': other, 'rateLimitsByLimitId': {'other-model': other, 'codex': limits(0)}}
        value = codex_resets.quota_record(data, '/example', now=1000)
        self.assertEqual(value['windows'][0]['used_percent'], 0)
        self.assertEqual(value['fetched_at'], 1000)
        self.assertEqual(codex_resets.quota_record({'rateLimits': other}, '/example', now=1000)['windows'], [])

    def test_missing_invalid_and_expired_windows_do_not_mean_a_full_refill(self):
        for data in ({}, {'rateLimits': limits(True)}, {'rateLimits': limits(reset=900)},
                     {'rateLimits': {'limitId': 'codex', 'primary': 'invalid'}},
                     {'rateLimits': dict(limits(), secondary={'usedPercent': 'bad'})}):
            with self.subTest(data=data):
                value = codex_resets.quota_record(data, '/example', now=1000)
                self.assertEqual(value['windows'], [])

    def test_exhausted_short_window_is_retained_alongside_the_weekly_reading(self):
        rates = limits(100, duration=300)
        rates['secondary'] = limits(30)['primary']
        value = codex_resets.quota_record({'rateLimits': rates}, '/example', now=1000)
        value['ordinary_usage_allowed'] = True
        row = local_row(account('/example'), value, now=1000)
        from token_tv.themes import reading
        self.assertEqual(reading(row)[0], 100)
        self.assertEqual(reading(row)[1], '5H')
        self.assertEqual(remaining_reading(row)[0], 70)
        self.assertEqual(remaining_reading(row)[1], 'WK')

    def test_fresh_official_quota_replaces_old_sessions_without_using_the_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'codex'
            cache = Path(directory) / 'cache'
            atomic_json(cache / 'codex-official.json', record(root))
            with patch('token_tv.local_usage.time.time', return_value=1020), \
                 patch('token_tv.local_usage.codex_record', side_effect=AssertionError('Session scanning forbidden')):
                row = fetch_local(account(root), cache, official_codex=True)
        self.assertEqual(remaining_reading(row)[0], 100)
        self.assertEqual(row['quota_origin'], 'codex_official_cli')

    def test_missing_official_cache_cannot_fall_back_to_session_percentages(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('token_tv.local_usage.codex_record', side_effect=AssertionError('No fallback')):
                row = fetch_local(account('/example'), directory, official_codex=True)
        self.assertIsNone(remaining_reading(row)[0])

    def test_foreign_official_cache_does_not_show_another_accounts_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            atomic_json(Path(directory) / 'codex-official.json', record('/another-home'))
            row = fetch_local(account('/chosen-home'), directory, official_codex=True)
        self.assertEqual(row['windows'], [])

    def test_old_official_quota_disappears_instead_of_looking_like_46_percent(self):
        row = local_row(account('/example'), record('/example', used=54), now=1200)
        self.assertEqual(row['status'], 'quota_unavailable')
        self.assertIsNone(remaining_reading(row)[0])
        self.assertEqual(row['error_code'], 'quota_refresh_overdue')

    def test_reader_stopping_expires_the_snapshot_even_without_a_refresh(self):
        a = account('/example')
        row = local_row(a, record('/example', used=54), now=1000)
        store = UsageStore([a], fetch=lambda _: row)
        with patch('token_tv.state.time.time', return_value=1000):
            store.refresh()
        with patch('token_tv.state.time.time', return_value=1200):
            expired = store.snapshot()['accounts'][a['key']]
        self.assertIsNone(remaining_reading(expired)[0])
        self.assertEqual(expired['status'], 'quota_unavailable')

    def test_reset_passing_expires_an_in_memory_reading(self):
        a = account('/example')
        value = record('/example')
        value['windows'][0]['resets_at'] = 1050
        row = local_row(a, value, now=1000)
        store = UsageStore([a], fetch=lambda _: row)
        with patch('token_tv.state.time.time', return_value=1000):
            store.refresh()
        with patch('token_tv.state.time.time', return_value=1060):
            self.assertEqual(store.snapshot()['accounts'][a['key']]['windows'], [])

    def test_backend_block_or_unknown_permission_never_becomes_a_refill(self):
        a = account('/example')
        value = local_row(a, record('/example'), now=1000)
        store = UsageStore([a], fetch=lambda _: value)
        with patch('token_tv.state.time.time', return_value=1000):
            store.refresh()
            for permission in (False, None):
                raw = record('/example')
                raw['ordinary_usage_allowed'] = permission
                value = local_row(a, raw, now=1000)
                store.refresh()
                row = store.snapshot()['accounts'][a['key']]
                self.assertEqual(row['windows'], [])
                self.assertIsNone(remaining_reading(row)[0])
                self.assertEqual(row['status'], 'usage_blocked' if permission is False else 'quota_unavailable')

    def test_confirmed_exhaustion_survives_snapshots_then_expires(self):
        a = account('/example')
        raw = record('/example', used=100)
        raw['ordinary_usage_allowed'] = False
        row = local_row(a, raw, now=1000)
        self.assertEqual(row['status'], 'ok')
        self.assertIs(row['ordinary_usage_allowed'], False)
        store = UsageStore([a], fetch=lambda _: row)
        with patch('token_tv.state.time.time', return_value=1000):
            store.refresh()
        for instant in (1000, 1060, 1180):
            with patch('token_tv.state.time.time', return_value=instant):
                self.assertEqual(remaining_reading(store.snapshot()['accounts'][a['key']])[0], 0)
        with patch('token_tv.state.time.time', return_value=1181):
            self.assertIsNone(remaining_reading(store.snapshot()['accounts'][a['key']])[0])

    def test_blocked_zero_requires_fresh_explicit_week_and_future_reset(self):
        for change in ('stale', 'old', 'reset_passed', 'reset_missing', 'permission_unknown',
                       'almost_zero', 'no_week'):
            with self.subTest(change=change):
                raw = record('/example', used=100)
                raw['ordinary_usage_allowed'] = False
                if change == 'stale': raw['stale'] = True
                if change == 'old': raw['fetched_at'] = 800
                if change == 'reset_passed': raw['windows'][0]['resets_at'] = 1000
                if change == 'reset_missing': raw['windows'][0]['resets_at'] = None
                if change == 'permission_unknown': raw['ordinary_usage_allowed'] = None
                if change == 'almost_zero': raw['windows'][0]['used_percent'] = 99.9
                if change == 'no_week': raw['windows'][0]['label'] = '5H'
                self.assertIsNone(remaining_reading(local_row(account('/example'), raw, now=1000))[0])

    def test_exhausted_cache_identity_failure_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            a = dict(account('/example'), email='test@example.invalid')
            raw = record('/example', used=100)
            raw.update(origin=origin_id('/example', a['email']), identity_verified=True,
                       ordinary_usage_allowed=False)
            path = Path(directory) / 'codex-official.json'
            store = UsageStore([a], fetch=lambda _: fetch_local(a, directory, official_codex=True))
            with patch('time.time', return_value=1000):
                for change, expected in (('zero', 0), ('failed', None), ('foreign', None), ('recovered', 75)):
                    current = dict(raw)
                    if change == 'failed': current.update(windows=[], stale=True)
                    if change == 'foreign': current['origin'] = origin_id('/other')
                    if change == 'recovered':
                        current.update(ordinary_usage_allowed=True,
                                       windows=record('/example', used=25)['windows'])
                    atomic_json(path, current)
                    store.refresh()
                    row = store.snapshot()['accounts'][a['key']]
                    self.assertEqual(remaining_reading(row)[0], expected)
                    self.assertEqual(row['identity_verified'], expected is not None)

    def test_each_quota_reading_notifies_even_if_hearts_do_not_change(self):
        module = collector()
        readings = []
        with tempfile.TemporaryDirectory() as directory:
            a = account(Path(directory) / 'codex')
            path = Path(directory) / 'offline/codex-official.json'
            balances = ResetBalances(Path(directory) / 'reset-balances.json', [a])
            def notified():
                readings.append(json.loads(path.read_text())['windows'][0]['used_percent'])
                return True
            for used in (0, 27, 100):
                module.publish_reading(balances, 0, record(a['source_home'], used), path, notify=notified)
        self.assertEqual(readings, [0, 27, 100])

    def test_worker_recovers_after_failure_and_failed_notification(self):
        module = collector()
        events = []
        reader = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            a = account(Path(directory) / 'codex')
            config = {'automatic_codex_resets': True, 'accounts': [a]}
            path = Path(directory) / 'config.json'
            cache = Path(directory) / 'offline/codex-official.json'
            reader.read_snapshot.side_effect = [
                {'available_resets': 0, 'quota': record(a['source_home'], 0)},
                RuntimeError('PRIVATE ERROR'),
                {'available_resets': 0, 'quota': record(a['source_home'], 20)}]
            class Event:
                done = False
                def is_set(self): return self.done
                def set(self): self.done = True
                def wait(self, seconds): self.done = len(events) == 3
            def notify():
                events.append(json.loads(cache.read_text())['windows'])
                return len(events) != 1
            with patch('sys.argv', ['collector', '--config', str(path)]), \
                 patch.object(module, 'load_config', return_value=config), \
                 patch.object(module, 'CodexResetReader', return_value=reader) as create, \
                 patch.object(module, 'notify_display', side_effect=notify), \
                 patch.object(module.threading, 'Event', Event), patch.object(module.signal, 'signal'):
                module.main()
            self.assertEqual(create.call_count, 2)
        self.assertEqual([w[0]['used_percent'] if w else None for w in events], [0, None, 20])

    def test_health_does_not_report_success_when_codex_quota_is_old(self):
        from http.server import ThreadingHTTPServer
        a = account('/example')
        value = local_row(a, record('/example', used=54), now=1000)
        store = UsageStore([a], fetch=lambda _: value)
        store.refresh()
        server = ThreadingHTTPServer(('127.0.0.1', 0), live.handler(store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(f'http://127.0.0.1:{server.server_port}/health')
            self.assertEqual(error.exception.code, 503)
            body = json.load(error.exception)
            self.assertEqual(body['status'], 'degraded')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_health_requires_publication_when_a_clock_is_configured(self):
        from http.server import ThreadingHTTPServer
        a = account('/example')
        value = local_row(a, record('/example'), now=1000)
        store = UsageStore([a], fetch=lambda _: value)
        preferences = MagicMock()
        preferences.config = {'device_url': 'http://127.0.0.1'}
        preferences.reset_snapshot.return_value = {}
        with patch('token_tv.state.time.time', return_value=1000):
            store.refresh()
            server = ThreadingHTTPServer(('127.0.0.1', 0), live.handler(store, preferences))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for status, expected in (('queued', 503), ('preview_only', 503), ('error', 503), ('ok', 200)):
                    preferences.snapshot.return_value = {'style': 'retro', 'status': status}
                    try:
                        response = urlopen(f'http://127.0.0.1:{server.server_port}/health')
                    except HTTPError as response_error:
                        response = response_error
                    with response:
                        self.assertEqual(response.status, expected, status)
                preferences.config = {}
                preferences.snapshot.return_value = {'style': 'retro', 'status': 'preview_only'}
                with urlopen(f'http://127.0.0.1:{server.server_port}/health') as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_local_doctor_uses_the_same_official_sources_as_the_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            a = account(Path(directory) / 'codex')
            config = {'local_only': True, 'automatic_codex_resets': True,
                      'automatic_claude_usage': True, 'accounts': [a]}
            args = SimpleNamespace(config=str(Path(directory) / 'config.json'), live=False)
            cache = Path(directory) / 'offline/codex-official.json'
            with patch.object(cli, 'read_config', return_value=config), \
                 patch('sys.addaudithook'), patch('sys.stdout', new_callable=io.StringIO) as output, \
                 patch('token_tv.local_usage.time.time', return_value=1000), \
                 patch('token_tv.local_usage.codex_record', side_effect=AssertionError('No session fallback')):
                self.assertEqual(cli.doctor(args), 1)
                self.assertNotIn('local data: OK', output.getvalue())
                atomic_json(cache, record(a['source_home']))
                from token_tv.reset_balances import ResetBalances
                ResetBalances(Path(directory)/'reset-balances.json', [a]).set_count('codex', 0, source='codex_cli')
                self.assertEqual(cli.doctor(args), 0)
                blocked = record(a['source_home'])
                blocked['ordinary_usage_allowed'] = False
                atomic_json(cache, blocked)
                self.assertEqual(cli.doctor(args), 1)
                self.assertIn('USAGE_BLOCKED', output.getvalue())
