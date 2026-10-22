import json
import tempfile
import unittest
from pathlib import Path


class ResetBalanceTests(unittest.TestCase):
    def test_unknown_and_confirmed_zero_are_different(self):
        from token_tv.reset_balances import ResetBalances
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resets.json'
            store = ResetBalances(path, [{'provider': 'claude', 'source_home': '/example/claude'}])
            self.assertIsNone(store.snapshot()['claude']['available'])
            store.set_count('claude', 0)
            self.assertEqual(store.snapshot()['claude']['available'], 0)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_counts_remain_separate_and_do_not_change_on_quota_reset(self):
        from token_tv.reset_balances import ResetBalances
        accounts = [{'provider': p, 'source_home': '/example/' + p} for p in ('claude', 'codex')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resets.json'
            store = ResetBalances(path, accounts)
            store.set_count('claude', 0)
            store.set_count('codex', 1)
            resumed = ResetBalances(path, accounts)
            self.assertEqual(resumed.snapshot()['claude']['available'], 0)
            self.assertEqual(resumed.snapshot()['codex']['available'], 1)
            self.assertEqual(resumed.snapshot()['codex']['source'], 'user_confirmed')
            foreign = ResetBalances(path, [{'provider': 'codex', 'source_home': '/another/home'}])
            self.assertIsNone(foreign.snapshot()['codex']['available'])

    def test_invalid_count_cannot_change_an_existing_balance(self):
        from token_tv.reset_balances import ResetBalances
        with tempfile.TemporaryDirectory() as directory:
            store = ResetBalances(Path(directory) / 'resets.json', [{'provider': 'codex', 'source_home': '/example'}])
            store.set_count('codex', 1)
            for count in (True, -1, 1.5, '1', 1000):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    store.set_count('codex', count)
            self.assertEqual(store.snapshot()['codex']['available'], 1)

    def test_a_stale_automatic_count_is_kept_as_last_known_but_never_as_fresh(self):
        import time
        from unittest.mock import patch
        from token_tv.reset_balances import LAST_KNOWN_SECONDS, ResetBalances
        with tempfile.TemporaryDirectory() as directory:
            store = ResetBalances(Path(directory) / 'resets.json', [{'provider': 'codex', 'source_home': '/example'}])
            now = time.time()
            store.set_count('codex', 2, source='codex_cli', observed_at=now)
            fresh = store.snapshot(('codex',))['codex']
            self.assertEqual((fresh['available'], 'last_known' in fresh), (2, False))
            for age, expected in ((200, 2), (3600, 2), (LAST_KNOWN_SECONDS - 60, 2), (LAST_KNOWN_SECONDS + 60, None)):
                with self.subTest(age=age), patch('token_tv.reset_balances.time.time', return_value=now + age):
                    stale = store.snapshot(('codex',))['codex']
                    self.assertIsNone(stale['available'])             # everything that reads `available` sees unknown
                    self.assertEqual(stale['source'], 'stale')
                    self.assertEqual(stale.get('last_known'), expected)

    def test_an_expired_grant_is_never_shown_as_last_known(self):
        import time
        from unittest.mock import patch
        from token_tv.reset_balances import ResetBalances
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resets.json'
            store = ResetBalances(path, [{'provider': 'claude', 'source_home': '/example/claude'}])
            now = time.time()
            organization = 'a' * 64
            store.set_count('claude', 1, source='claude_web', observed_at=now, valid_until=int(now + 600),
                            organization_hash=organization)
            with patch('token_tv.reset_balances.time.time', return_value=now + 300):   # stale but the grant is alive
                alive = store.snapshot(('claude',), organization)['claude']
            self.assertEqual((alive['available'], alive.get('last_known')), (None, 1))
            with patch('token_tv.reset_balances.time.time', return_value=now + 900):   # the grant has expired
                gone = store.snapshot(('claude',), organization)['claude']
            self.assertEqual((gone['available'], 'last_known' in gone), (None, False))

    def test_hearts_mark_the_last_known_count_old_and_never_invent_one(self):
        from token_tv.personal_faces import banked_hearts
        self.assertEqual(banked_hearts({'banked_resets': {'available': 2}}), (2, False))
        self.assertEqual(banked_hearts({'banked_resets': {'available': None, 'last_known': 1}}), (1, True))
        self.assertEqual(banked_hearts({'banked_resets': {'available': None}}), (None, False))
        self.assertEqual(banked_hearts({}), (None, False))
        self.assertEqual(banked_hearts({'banked_resets': {'available': None, 'last_known': True}}), (None, False))

    def test_manual_count_cannot_masquerade_as_automatic(self):
        from token_tv.reset_balances import ResetBalances
        with tempfile.TemporaryDirectory() as directory:
            store=ResetBalances(Path(directory)/'resets.json',[{'provider':'codex','source_home':'/example'}])
            store.set_count('codex',1)
            self.assertIsNone(store.snapshot(['codex'])['codex']['available'])
            store.set_count('codex',1,source='codex_cli')
            self.assertEqual(store.snapshot(['codex'])['codex']['available'],1)
