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
