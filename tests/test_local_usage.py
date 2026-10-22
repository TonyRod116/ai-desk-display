import json
import tempfile
import unittest
from pathlib import Path
from token_tv.usage import window


class LocalUsageTests(unittest.TestCase):
    def test_codex_reads_only_quota_events_and_never_exports_conversation(self):
        from token_tv.local_usage import codex_record
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sessions' / 'session.jsonl'
            path.parent.mkdir()
            path.write_text('\n'.join(json.dumps(event) for event in [
                {'type': 'response_item', 'payload': {'text': 'PRIVATE-CONVERSATION'}},
                {'type': 'event_msg', 'timestamp': '2026-10-09T10:00:00Z', 'payload': {
                    'type': 'token_count', 'rate_limits': {'limit_id': 'codex', 'primary': {
                        'used_percent': 40, 'window_minutes': 10080, 'resets_at': 2000000000}},
                    'secret': 'NEVER-EXPORT'}},
            ]))
            record = codex_record(Path(directory))
        self.assertEqual(record['windows'][0]['used_percent'], 40)
        self.assertEqual(record['windows'][0]['label'], 'WEEK')
        self.assertNotIn('PRIVATE-CONVERSATION', json.dumps(record))
        self.assertNotIn('NEVER-EXPORT', json.dumps(record))

    def test_expired_reading_never_becomes_a_free_refill(self):
        from token_tv.local_usage import local_row
        account = {'key': 'claude_a', 'alias': 'CLAUDE', 'provider': 'claude'}
        record = {'fetched_at': 100, 'windows': [window('5H', 100, 120, 300)]}
        row = local_row(account, record, now=130)
        self.assertEqual(row['windows'], [])
        self.assertEqual(row['status'], 'quota_unavailable')
        record['windows'].append(window('WEEK', 0, 1000, 10080))
        row = local_row(account, record, now=130)
        self.assertEqual(row['windows'], [])
        self.assertEqual(row['status'], 'quota_unavailable')

    def test_unchanged_statusline_payload_does_not_make_old_data_fresh(self):
        from token_tv.local_usage import capture_claude
        data = {'session_id': 'PRIVATE-ID', 'cost': {'total_api_duration_ms': 120},
                'context_window': {'total_output_tokens': 100},
                'rate_limits': {'five_hour': {'used_percentage': 30, 'resets_at': 2000000000}},
                'cwd': '/private/repo', 'access_token': 'NEVER-EXPORT'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'claude.json'
            capture_claude(data, path, now=100)
            data['cost']['total_api_duration_ms'] = 130
            data['context_window']['total_output_tokens'] = 120
            capture_claude(data, path, now=150)
            capture_claude(data, path, now=300)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['fetched_at'], 150)
            self.assertNotIn('PRIVATE-ID', json.dumps(saved))
            self.assertNotIn('NEVER-EXPORT', json.dumps(saved))
            self.assertNotIn('/private/repo', json.dumps(saved))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            data['cost']['total_api_duration_ms'] = 140
            data['context_window']['total_output_tokens'] = 140
            data['rate_limits']['five_hour']['used_percentage'] = 0
            capture_claude(data, path, now=400)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['fetched_at'], 400)
            self.assertEqual(saved['windows'][0]['used_percent'], 0)

    def test_expired_window_disappearing_from_statusline_is_not_a_new_response(self):
        from token_tv.local_usage import capture_claude, local_row
        data = {'session_id': 'example', 'cost': {'total_api_duration_ms': 120},
                'context_window': {'total_output_tokens': 100},
                'rate_limits': {'five_hour': {'used_percentage': 100, 'resets_at': 120},
                                'seven_day': {'used_percentage': 0, 'resets_at': 1000}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'claude.json'
            capture_claude(data, path, now=90)
            data['cost']['total_api_duration_ms'] = 140
            data['context_window']['total_output_tokens'] = 120
            capture_claude(data, path, now=100)
            del data['rate_limits']['five_hour']
            capture_claude(data, path, now=130)
            row = local_row({'key': 'c', 'alias': 'C', 'provider': 'claude'}, json.loads(path.read_text()), now=130)
        self.assertEqual(row['windows'], [])

    def test_first_callback_from_an_old_session_cannot_overwrite_recent_quota(self):
        from token_tv.local_usage import capture_claude
        data = {'session_id': 'new-session', 'cost': {'total_api_duration_ms': 100},
                'context_window': {'total_output_tokens': 100},
                'rate_limits': {'seven_day': {'used_percentage': 50, 'resets_at': 2000000000}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'claude.json'
            capture_claude(data, path, now=100)
            data['cost']['total_api_duration_ms'] = 120
            data['context_window']['total_output_tokens'] = 120
            capture_claude(data, path, now=150)
            data['session_id'] = 'old-session'
            data['cost']['total_api_duration_ms'] = 200
            data['context_window']['total_output_tokens'] = 200
            data['rate_limits']['seven_day']['used_percentage'] = 0
            capture_claude(data, path, now=160)
            record = json.loads(path.read_text())
        self.assertEqual(record['fetched_at'], 150)
        self.assertEqual(record['windows'][0]['used_percent'], 50)

    def test_failed_request_without_new_output_cannot_refill_expired_quota(self):
        from token_tv.local_usage import capture_claude, local_row
        data = {'session_id': 'example', 'cost': {'total_api_duration_ms': 100},
                'context_window': {'total_output_tokens': 100},
                'rate_limits': {'five_hour': {'used_percentage': 100, 'resets_at': 160},
                                'seven_day': {'used_percentage': 0, 'resets_at': 1000}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'claude.json'
            capture_claude(data, path, now=100)
            data['cost']['total_api_duration_ms'] = 120
            data['context_window']['total_output_tokens'] = 120
            capture_claude(data, path, now=150)
            data['cost']['total_api_duration_ms'] = 140
            del data['rate_limits']['five_hour']
            capture_claude(data, path, now=170)
            row = local_row({'key': 'c', 'alias': 'C', 'provider': 'claude'}, json.loads(path.read_text()), now=170)
        self.assertEqual(row['windows'], [])

    def test_a_cache_from_another_source_home_is_not_displayed(self):
        from token_tv.local_usage import fetch_local, origin_id
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'claude.json'
            path.write_text(json.dumps({'origin': origin_id('/another/home'), 'fetched_at': 100,
                                        'windows': [window('WEEK', 0, 2000000000, 10080)]}))
            row = fetch_local({'key': 'c', 'alias': 'C', 'provider': 'claude', 'source_home': '/chosen/home'}, directory)
        self.assertEqual(row['windows'], [])

    def test_local_mode_rejects_ambiguous_multi_account_configuration(self):
        from token_tv.sources import load_config
        accounts = [{'key': key, 'alias': key, 'provider': 'claude', 'email': 'test@example.com',
                     'source_home': '/example/' + key} for key in ('a', 'b')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'local_only': True, 'accounts': accounts}))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_local_restore_rejects_public_address_before_a_request(self):
        from unittest.mock import patch
        from token_tv import live
        with patch('sys.argv', ['live', '--config', '/example', '--restore-display']), \
             patch.object(live, 'load_config', return_value={'local_only': True, 'device_url': 'http://8.8.8.8'}), \
             patch.object(live, 'PhotoDisplay') as display:
            with self.assertRaises(ValueError):
                live.main()
        display.assert_not_called()

    def test_security_policy_denies_external_network_credentials_and_children(self):
        from token_tv.local_usage import LocalPolicy
        policy = LocalPolicy('http://192.168.0.50')
        for event, args in [('socket.connect', (None, ('8.8.8.8', 443))),
                            ('socket.getaddrinfo', ('api.anthropic.com', 443)),
                            ('socket.sendto', (None, ('8.8.8.8', 53))),
                            ('socket.getnameinfo', (('8.8.8.8', 0), 0)),
                            ('os.system', ('example',)),
                            ('os.posix_spawn', ('example', [], {})),
                            ('os.exec', ('example', [], {})),
                            ('subprocess.Popen', ('claude', [], None, {})),
                            ('open', ('/unused/auth.json', 'r', 0))]:
            with self.subTest(event=event), self.assertRaises(PermissionError):
                policy.audit(event, args)
        policy.audit('socket.connect', (None, ('192.168.0.50', 80)))
        policy.audit('socket.connect', (None, ('127.0.0.1', 8787)))
