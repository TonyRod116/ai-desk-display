import unittest
from unittest.mock import patch, MagicMock

from token_tv.codex_resets import available_resets, CodexResetReader


class CodexResetTests(unittest.TestCase):
    def test_failed_and_recovered_readings_each_notify_the_clock(self):
        import importlib.util
        from pathlib import Path
        spec=importlib.util.spec_from_file_location('reset_collector',Path(__file__).parents[1]/'scripts/codex_reset_collector.py')
        collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
        balances=MagicMock();notify=MagicMock(return_value=True);last=object()
        for count in (1,None,1): last=collector.publish_count(balances,count,last,notify)
        self.assertEqual(notify.call_count,3)
        notify=MagicMock(side_effect=[False,True]);last=object()
        for count in (1,1):last=collector.publish_count(balances,count,last,notify)
        self.assertEqual(notify.call_count,2)
        self.assertEqual(last,1)

    def test_recovery_retries_after_failed_unknown_notification(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            'reset_collector_recovery',
            Path(__file__).parents[1] / 'scripts/codex_reset_collector.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        balances = MagicMock()
        notify = MagicMock(side_effect=[False, True])
        last = collector.publish_count(balances, None, 1, notify)
        last = collector.publish_count(balances, 1, last, notify)
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(last, 1)

    def test_disabled_collector_never_creates_a_client(self):
        import importlib.util
        from pathlib import Path
        spec=importlib.util.spec_from_file_location('reset_collector_disabled',Path(__file__).parents[1]/'scripts/codex_reset_collector.py')
        collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
        with patch('sys.argv',['collector']),patch.object(collector,'load_config',return_value={}),patch.object(collector,'CodexResetReader') as reader:
            collector.main()
        reader.assert_not_called()
    def test_saved_reset_count_comes_from_the_documented_summary(self):
        self.assertEqual(available_resets({'rateLimitResetCredits': {'availableCount': 1}}), 1)
        self.assertEqual(available_resets({'rateLimitResetCredits': {'availableCount': 0}}), 0)
        self.assertIsNone(available_resets({'rateLimits': {'credits': {'balance': 1}}}))
        self.assertIsNone(available_resets({'rateLimitResetCredits': {'availableCount': True}}))

    def test_reading_does_not_redeem_a_reset_or_start_a_model(self):
        rpc = MagicMock()
        rpc.call.side_effect = [{}, {'account': {'type': 'chatgpt'}},
                                {'account': {'type': 'chatgpt'}},
                                {'rateLimitResetCredits': {'availableCount': 1}},
                                {'account': {'type': 'chatgpt'}}]
        with patch('token_tv.codex_resets.RPC', return_value=rpc):
            reader = CodexResetReader('/example/codex')
            self.assertEqual(reader.read(), 1)
            reader.close()
        self.assertEqual([call.args[0] for call in rpc.call.call_args_list],
                         ['initialize', 'account/read', 'account/read', 'account/rateLimits/read', 'account/read'])

    def test_transient_error_holds_fresh_codex_reading_and_retries_quickly(self):
        import importlib.util
        import io
        import json
        import tempfile
        import time
        from contextlib import redirect_stdout
        from pathlib import Path
        from token_tv.local_usage import atomic_json, origin_id
        from token_tv.sources import SourceError
        spec = importlib.util.spec_from_file_location('reset_collector_hold', Path(__file__).parents[1] / 'scripts/codex_reset_collector.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'codex'
            cfg = {'automatic_codex_resets': True, 'accounts': [{'key': 'codex_a', 'alias': 'CODEX', 'provider': 'codex', 'source_home': str(root)}]}
            cache = Path(directory) / 'offline/codex-official.json'
            now = time.time()
            fresh = {'fetched_at': now - 30, 'source': 'codex_official_cli', 'origin': origin_id(root),
                     'windows': [{'label': 'WEEK', 'used_percent': 25, 'resets_at': now + 3600, 'duration_minutes': 10080}],
                     'stale': False, 'ordinary_usage_allowed': True}
            atomic_json(cache, fresh)
            self.assertIsNotNone(collector.held_reading(cache, origin_id(root), now))
            self.assertIsNone(collector.held_reading(cache, origin_id('/other'), now))
            self.assertIsNone(collector.held_reading(cache, origin_id(root), now + collector.HOLD_SECONDS + 10))
            waits, reader = [], MagicMock()
            recovered = {**fresh, 'fetched_at': now + 10, 'windows': [{'label': 'WEEK', 'used_percent': 26, 'resets_at': now + 3600, 'duration_minutes': 10080}]}
            reader.read_snapshot.side_effect = [SourceError('timeout'), {'available_resets': 1, 'quota': recovered}]
            class Event:
                done = False
                def is_set(self): return self.done
                def set(self): self.done = True
                def wait(self, seconds):
                    waits.append(seconds)
                    if len(waits) == 1:
                        self.assertEqual(json.loads(cache.read_text())['windows'][0]['used_percent'], 25)
                    self.done = len(waits) == 2
            Event.assertEqual = self.assertEqual
            output = io.StringIO()
            with redirect_stdout(output), \
                 patch('sys.argv', ['collector', '--config', str(Path(directory) / 'config.json')]), \
                 patch.object(collector, 'load_config', return_value=cfg), \
                 patch.object(collector, 'CodexResetReader', return_value=reader), \
                 patch.object(collector, 'notify_display', return_value=True) as notify, \
                 patch.object(collector, 'Alerts'), \
                 patch.object(collector.threading, 'Event', Event), \
                 patch.object(collector.signal, 'signal'):
                collector.main()
            self.assertEqual(waits, [collector.RETRY_FIRST_SECONDS, collector.POLL_SECONDS])
            self.assertEqual(notify.call_count, 1)
            self.assertEqual(json.loads(cache.read_text())['windows'][0]['used_percent'], 26)
            self.assertIn('(timeout)', output.getvalue())
            self.assertIn('keeping the last reading', output.getvalue())
            self.assertIn('recovered with a fresh reading', output.getvalue())

    def test_identity_or_login_error_blanks_codex_reading_immediately(self):
        import importlib.util
        import json
        import tempfile
        import time
        from pathlib import Path
        from token_tv.local_usage import atomic_json, origin_id
        from token_tv.sources import SourceError
        spec = importlib.util.spec_from_file_location('reset_collector_blank', Path(__file__).parents[1] / 'scripts/codex_reset_collector.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        for code in ('identity_mismatch', 'subscription_login_required'):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'codex'
                cfg = {'automatic_codex_resets': True, 'accounts': [{'key': 'codex_a', 'alias': 'CODEX', 'provider': 'codex', 'source_home': str(root)}]}
                cache = Path(directory) / 'offline/codex-official.json'
                now = time.time()
                fresh = {'fetched_at': now - 10, 'source': 'codex_official_cli', 'origin': origin_id(root),
                         'windows': [{'label': 'WEEK', 'used_percent': 25, 'resets_at': now + 3600, 'duration_minutes': 10080}],
                         'stale': False, 'ordinary_usage_allowed': True}
                atomic_json(cache, fresh)
                reader = MagicMock()
                reader.read_snapshot.side_effect = [SourceError(code)]
                class Event:
                    done = False
                    def is_set(self): return self.done
                    def set(self): self.done = True
                    def wait(self, seconds): self.done = True
                with patch('sys.argv', ['collector', '--config', str(Path(directory) / 'config.json')]), \
                     patch.object(collector, 'load_config', return_value=cfg), \
                     patch.object(collector, 'CodexResetReader', return_value=reader), \
                     patch.object(collector, 'notify_display', return_value=True), \
                     patch.object(collector, 'Alerts'), \
                     patch.object(collector.threading, 'Event', Event), \
                     patch.object(collector.signal, 'signal'):
                    collector.main()
                saved = json.loads(cache.read_text())
                self.assertTrue(saved['stale'])
                self.assertEqual(saved['windows'], [])
