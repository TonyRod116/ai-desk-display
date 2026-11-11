import unittest

from token_tv.tablet_snapshot import tablet_snapshot


NOW = 100_000


def row(provider, used=20, **extra):
    entry = {'provider': provider, 'status': 'ok', 'identity_verified': True,
             'quota_origin': provider + '_official_cli', 'fetched_at': NOW - 40,
             'windows': [{'label': 'WEEK', 'used_percent': used, 'resets_at': NOW + 8000}],
             'banked_resets': {'available': 1, 'confirmed_at': NOW - 40, 'source': 'codex_cli'}}
    if provider == 'codex':
        entry['ordinary_usage_allowed'] = True
    entry.update(extra)
    return entry


class TabletSnapshotTests(unittest.TestCase):
    def test_uses_week_remaining_and_omits_private_fields(self):
        claude = row('claude', 25, windows=[
            {'label': 'WEEK', 'used_percent': 25, 'resets_at': NOW + 8000},
            {'label': '5H', 'used_percent': 60, 'resets_at': NOW + 3600},
        ], email='private@example.test', secret='private')
        data = {'accounts': {'claude_a': claude, 'codex_a': row('codex', 80)}}
        result = tablet_snapshot(data, NOW)
        self.assertEqual(result['providers']['claude']['weekly']['remaining'], 75)
        self.assertEqual(result['providers']['claude']['session']['remaining'], 40)
        self.assertEqual(result['providers']['codex']['weekly']['remaining'], 20)
        self.assertNotIn('private', str(result))
        self.assertNotIn('claude_a', str(result))

    def test_expired_session_does_not_hide_a_valid_week(self):
        claude = row('claude', windows=[
            {'label': 'WEEK', 'used_percent': 25, 'resets_at': NOW + 8000},
            {'label': '5H', 'used_percent': 60, 'resets_at': NOW - 1},
        ])
        result = tablet_snapshot({'accounts': {'c': claude}}, NOW)['providers']['claude']
        self.assertEqual(result['weekly']['remaining'], 75)
        self.assertIsNone(result['session'])

    def test_old_quota_wrong_identity_and_expired_week_are_unknown(self):
        variants = [row('codex', fetched_at=NOW - 481),
                    row('codex', identity_verified=False),
                    row('codex', windows=[{'label': 'WEEK', 'used_percent': 42, 'resets_at': NOW - 1}])]
        for item in variants:
            with self.subTest(item=item):
                self.assertIsNone(tablet_snapshot({'accounts': {'x': item}}, NOW)['providers']['codex']['weekly'])

    def test_aged_quota_and_saved_resets_are_marked(self):
        item = row('codex', fetched_at=NOW - 240,
                   banked_resets={'available': None, 'last_known': 2, 'confirmed_at': NOW - 240, 'source': 'stale'})
        result = tablet_snapshot({'accounts': {'x': item}}, NOW)['providers']['codex']
        self.assertTrue(result['aged'])
        self.assertEqual(result['resets'], {'count': 2, 'old': True})

    def test_unavailable_reset_count_differs_from_a_real_zero(self):
        unknown = row('claude', banked_resets={'available': None, 'source': 'unknown'})
        zero = row('claude', banked_resets={'available': 0, 'source': 'claude_not_eligible'})
        get_count = lambda item: tablet_snapshot({'accounts': {'x': item}}, NOW)['providers']['claude']['resets']['count']
        self.assertIsNone(get_count(unknown))
        self.assertEqual(get_count(zero), 0)

    def test_codex_credits_only_when_verified_week_is_exhausted(self):
        exhausted = row('codex', 100, ordinary_usage_allowed=False, credits_balance='4.65')
        result = tablet_snapshot({'accounts': {'x': exhausted}}, NOW)['providers']['codex']
        self.assertEqual(result['weekly']['remaining'], 0)
        self.assertEqual(result['credits'], '4.65')
        not_exhausted = row('codex', 99, credits_balance='4.65')
        self.assertIsNone(tablet_snapshot({'accounts': {'x': not_exhausted}}, NOW)['providers']['codex']['credits'])

    def test_multiple_accounts_do_not_silently_switch_identity(self):
        data = {'accounts': {'one': row('claude', 20), 'other': row('claude', 50)}}
        self.assertIsNone(tablet_snapshot(data, NOW)['providers']['claude']['weekly'])


if __name__ == '__main__':
    unittest.main()
