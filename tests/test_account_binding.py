import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from token_tv import codex_resets
from token_tv.claude_usage import ClaudeUsageReader, native_record
from token_tv.local_usage import atomic_json, fetch_local, origin_id
from token_tv.reset_balances import ResetBalances
from token_tv.sources import SourceError


EMAIL = 'owner@example.test'
OTHER = 'other@example.test'
ROOT = '/example/native-home'


def account(provider, email=EMAIL):
    return {'key': provider, 'alias': provider.upper(), 'provider': provider,
            'source_home': ROOT, 'email': email}


def claude_cache(email=EMAIL):
    return {'oauthAccount': {'accountUuid': 'owner-id', 'emailAddress': email},
            'cachedUsageUtilization': {'accountUuid': 'owner-id', 'fetchedAtMs': 1000000,
                'utilization': {'seven_day': {'utilization': 20, 'resets_at': 10000}}}}


class AccountBindingTests(unittest.TestCase):
    def test_identity_is_part_of_cache_origin_without_exporting_email(self):
        bound = origin_id(ROOT, EMAIL)
        self.assertNotEqual(bound, origin_id(ROOT))
        self.assertNotEqual(bound, origin_id(ROOT, OTHER))
        self.assertEqual(bound, origin_id(ROOT, ' OWNER@EXAMPLE.TEST '))
        self.assertNotIn(EMAIL, bound)

    def test_claude_rejects_another_or_unidentified_native_login_before_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = ClaudeUsageReader(ROOT, directory, expected_email=EMAIL)
            for email in (OTHER, None):
                result = SimpleNamespace(returncode=0, stdout=json.dumps(
                    {'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty',
                     'subscriptionType': 'max', 'email': email}))
                with patch('token_tv.claude_usage.subprocess.run', return_value=result), \
                     patch('token_tv.claude_usage.subprocess.Popen') as process:
                    with self.assertRaises(SourceError) as error:
                        reader.read()
                self.assertEqual(error.exception.code, 'identity_mismatch')
                process.assert_not_called()

    def test_claude_accepts_only_the_expected_auth_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = ClaudeUsageReader(ROOT, directory, expected_email=EMAIL)
            result = SimpleNamespace(returncode=0, stdout=json.dumps(
                {'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty',
                 'subscriptionType': 'max', 'email': ' OWNER@EXAMPLE.TEST '}))
            with patch('token_tv.claude_usage.subprocess.run', return_value=result):
                reader.authenticate()

    def test_claude_cache_must_match_identity_even_after_an_authentication_race(self):
        for email in (OTHER, None):
            self.assertIsNone(native_record(claude_cache(email), ROOT, 999, now=1001,
                                           expected_email=EMAIL))
        record = native_record(claude_cache(), ROOT, 999, now=1001, expected_email=EMAIL)
        self.assertEqual(record['origin'], origin_id(ROOT, EMAIL))
        self.assertTrue(record['identity_verified'])
        self.assertNotIn(EMAIL, json.dumps(record))

    def test_codex_wrong_or_missing_account_is_rejected_before_any_quota_get(self):
        for email in (OTHER, None):
            rpc = MagicMock()
            rpc.call.side_effect = [{}, {'account': {'type': 'chatgpt', 'email': email}}]
            with patch.object(codex_resets, 'RPC', return_value=rpc):
                with self.assertRaises(SourceError) as error:
                    codex_resets.CodexResetReader(ROOT, expected_email=EMAIL)
            self.assertEqual(error.exception.code, 'identity_mismatch')
            self.assertNotIn('account/rateLimits/read', [c.args[0] for c in rpc.call.call_args_list])
            rpc.close.assert_called_once()

    def test_codex_account_change_cannot_expose_new_accounts_quota_or_hearts(self):
        for method in ('read', 'read_snapshot'):
            rpc = MagicMock()
            rpc.call.side_effect = [{}, {'account': {'type': 'chatgpt', 'email': EMAIL}},
                                   {'account': {'type': 'chatgpt', 'email': OTHER}}]
            with patch.object(codex_resets, 'RPC', return_value=rpc):
                reader = codex_resets.CodexResetReader(ROOT, expected_email=EMAIL)
                try:
                    with self.assertRaises(SourceError) as error:
                        getattr(reader, method)()
                finally:
                    reader.close()
            self.assertEqual(error.exception.code, 'identity_mismatch')
            self.assertNotIn('account/rateLimits/read', [c.args[0] for c in rpc.call.call_args_list])

    def test_codex_publishes_only_a_sanitized_identity_bound_observation(self):
        rpc = MagicMock()
        identity = {'account': {'type': 'chatgpt', 'email': EMAIL}}
        data = {'rateLimits': {'limitId': 'codex', 'primary': {'usedPercent': 25,
                'resetsAt': 10000, 'windowDurationMins': 10080}},
                'ordinaryUsageAllowed': True, 'rateLimitResetCredits': {'availableCount': 1}}
        rpc.call.side_effect = [{}, identity, identity, data, identity]
        with patch.object(codex_resets, 'RPC', return_value=rpc), \
             patch.object(codex_resets.time, 'time', return_value=1000):
            reader = codex_resets.CodexResetReader(ROOT, expected_email=EMAIL)
            try:
                observation = reader.read_snapshot()
            finally:
                reader.close()
        self.assertEqual(observation['quota']['origin'], origin_id(ROOT, EMAIL))
        self.assertEqual(observation['available_resets'], 1)
        self.assertTrue(observation['quota']['identity_verified'])
        self.assertNotIn(EMAIL, json.dumps(observation))

    def test_codex_login_change_during_the_get_discards_both_quota_and_hearts(self):
        for method in ('read', 'read_snapshot'):
            rpc = MagicMock()
            identity = {'account': {'type': 'chatgpt', 'email': EMAIL}}
            rpc.call.side_effect = [{}, identity, identity,
                                   {'rateLimitResetCredits': {'availableCount': 3}},
                                   {'account': {'type': 'chatgpt', 'email': OTHER}}]
            with patch.object(codex_resets, 'RPC', return_value=rpc):
                reader = codex_resets.CodexResetReader(ROOT, expected_email=EMAIL)
                try:
                    with self.assertRaises(SourceError) as error:
                        getattr(reader, method)()
                finally:
                    reader.close()
            self.assertEqual(error.exception.code, 'identity_mismatch')
            self.assertEqual([c.args[0] for c in rpc.call.call_args_list].count('account/rateLimits/read'), 1)

    def test_official_cache_cannot_cross_accounts_at_the_same_native_home(self):
        for provider in ('claude', 'codex'):
            for owner in (None, OTHER, EMAIL):
                with self.subTest(provider=provider, owner=owner), tempfile.TemporaryDirectory() as directory:
                    record = {'source': provider + '_official_cli', 'origin': origin_id(ROOT, owner),
                              'fetched_at': 1000, 'ordinary_usage_allowed': True, 'identity_verified': True,
                              'windows': [{'label': 'WEEK', 'used_percent': 25, 'resets_at': 10000}]}
                    atomic_json(Path(directory) / (provider + '-official.json'), record)
                    with patch('token_tv.local_usage.time.time', return_value=1001):
                        row = fetch_local(account(provider), directory, official_claude=True,
                                          official_codex=True)
                    self.assertEqual(bool(row['windows']), owner == EMAIL)
                    self.assertEqual(row['identity_verified'], owner == EMAIL)

    def test_failed_native_login_does_not_claim_a_verified_identity(self):
        for provider in ('claude', 'codex'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                record = {'source': provider + '_official_cli', 'origin': origin_id(ROOT, EMAIL),
                          'fetched_at': 0, 'windows': [], 'stale': True}
                atomic_json(Path(directory) / (provider + '-official.json'), record)
                row = fetch_local(account(provider), directory, official_claude=True, official_codex=True)
                self.assertFalse(row['identity_verified'])
                self.assertEqual(row['windows'], [])

    def test_legacy_sessions_are_not_identity_verified_and_cannot_be_a_fallback(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('token_tv.local_usage.codex_record') as sessions:
            row = fetch_local(account('codex'), directory)
        self.assertEqual(row['windows'], [])
        sessions.assert_not_called()

    def test_saved_hearts_cannot_cross_accounts_or_unbound_old_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hearts.json'
            selected = ResetBalances(path, [account('codex')])
            selected.set_count('codex', 1, source='codex_cli')
            self.assertEqual(selected.snapshot()['codex']['available'], 1)
            other = ResetBalances(path, [account('codex', OTHER)])
            self.assertIsNone(other.snapshot()['codex']['available'])
            unbound = account('codex')
            del unbound['email']
            self.assertIsNone(ResetBalances(path, [unbound]).snapshot()['codex']['available'])
            self.assertNotIn(EMAIL, path.read_text())


if __name__ == '__main__':
    unittest.main()
