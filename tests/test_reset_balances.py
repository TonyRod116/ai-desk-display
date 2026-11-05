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

    def test_a_count_is_current_to_three_minutes_then_kept_old_for_72_hours(self):
        import time
        from unittest.mock import patch
        from token_tv.reset_balances import FRESH_SECONDS, LAST_KNOWN_SECONDS, ResetBalances
        self.assertEqual((FRESH_SECONDS, LAST_KNOWN_SECONDS), (180, 72 * 3600))
        with tempfile.TemporaryDirectory() as directory:
            store = ResetBalances(Path(directory) / 'resets.json', [{'provider': 'codex', 'source_home': '/example'}])
            now = int(time.time())   # whole seconds: the stored date is truncated, and the boundaries are exact
            store.set_count('codex', 2, source='codex_cli', observed_at=now)
            for age, available, last_known, source in ((0, 2, None, 'codex_cli'), (180, 2, None, 'codex_cli'),
                                                       (181, None, 2, 'stale'), (3600, None, 2, 'stale'),
                                                       (LAST_KNOWN_SECONDS, None, 2, 'stale'),
                                                       (LAST_KNOWN_SECONDS + 1, None, None, 'stale')):
                with self.subTest(age=age), patch('token_tv.reset_balances.time.time', return_value=now + age):
                    reading = store.snapshot(('codex',))['codex']
                    self.assertEqual((reading['available'], reading.get('last_known'), reading['source']),
                                     (available, last_known, source))   # `available` is unknown for every consumer past 180 s
                    self.assertIsNotNone(reading['confirmed_at'])

    def test_an_expired_grant_is_never_shown_as_old(self):
        import time
        from unittest.mock import patch
        from token_tv.reset_balances import ResetBalances
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resets.json'
            store = ResetBalances(path, [{'provider': 'claude', 'source_home': '/example/claude'}])
            now = time.time()
            organization = 'a' * 64
            store.set_count('claude', 1, source='claude_web', observed_at=now, valid_until=int(now + 250),
                            organization_hash=organization)
            for age, available, last_known in ((100, 1, None), (200, None, 1), (300, None, None), (900, None, None)):
                with self.subTest(age=age), patch('token_tv.reset_balances.time.time', return_value=now + age):
                    reading = store.snapshot(('claude',), organization)['claude']   # the grant ends at +250
                    self.assertEqual((reading['available'], reading.get('last_known')), (available, last_known))
            with patch('token_tv.reset_balances.time.time', return_value=now + 200):
                self.assertEqual(store.snapshot(('claude',), organization)['claude']['valid_until'], int(now + 250))

    def test_a_current_failure_clears_the_old_count_and_an_old_observation_is_not_recorded(self):
        import time
        from unittest.mock import patch
        from token_tv.reset_balances import MAX_AGE_SECONDS, ResetBalances
        with tempfile.TemporaryDirectory() as directory:
            store = ResetBalances(Path(directory) / 'resets.json', [{'provider': 'codex', 'source_home': '/example'}])
            now = time.time()
            store.set_count('codex', 2, source='codex_cli', observed_at=now - 300)   # recorded, and shown old at once
            self.assertEqual(store.snapshot(('codex',))['codex'].get('last_known'), 2)
            for observed in (now - MAX_AGE_SECONDS - 5, now + 5):
                with self.subTest(observed=observed), self.assertRaises(ValueError):
                    store.set_count('codex', 1, source='codex_cli', observed_at=observed)
            self.assertEqual(store.snapshot(('codex',))['codex'].get('last_known'), 2)   # a rejected write changed nothing
            store.set_count('codex', None, source='codex_cli')                            # a current failure
            cleared = store.snapshot(('codex',))['codex']
            self.assertEqual((cleared['available'], 'last_known' in cleared), (None, False))

    def test_the_browser_readers_state_is_not_part_of_a_rows_balance(self):
        from token_tv.reset_balances import attach_balances
        snapshot = {'accounts': {'c': {'provider': 'claude'}, 'x': {'provider': 'codex'}}}
        attach_balances(snapshot, {'claude': {'available': 1, 'source': 'claude_web', 'reader': {'state': 'ok'}},
                                   'codex': {'available': 2, 'source': 'codex_cli'}})
        self.assertEqual(snapshot['accounts']['c']['banked_resets'], {'available': 1, 'source': 'claude_web'})
        self.assertEqual(snapshot['accounts']['x']['banked_resets'], {'available': 2, 'source': 'codex_cli'})

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
