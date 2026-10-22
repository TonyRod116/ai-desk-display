import unittest
from token_tv.sample import snapshot


class RemainingTests(unittest.TestCase):
    def test_hearts_count_saved_resets_and_never_derive_them_from_quota(self):
        from token_tv.personal_faces import reset_heart_fills
        self.assertEqual(reset_heart_fills(3), [1, 1, 1])
        self.assertEqual(reset_heart_fills(1), [1, 0, 0])
        self.assertEqual(reset_heart_fills(0), [0, 0, 0])
        self.assertEqual(reset_heart_fills(5), [1, 1, 1])
        self.assertIsNone(reset_heart_fills(None))

    def test_remaining_uses_the_weekly_window(self):
        from token_tv.personal_faces import remaining_reading
        row = snapshot(0, [('claude_a', 'CLAUDE', 'claude', [('5H', 25, 3600), ('WEEK', 80, 7200)])])['accounts']['claude_a']
        remaining, period, old, _ = remaining_reading(row)
        self.assertEqual(remaining, 20)
        self.assertIn(period, ('WK', 'WEEK'))
        self.assertFalse(old)
        self.assertEqual(row['windows'][0]['used_percent'], 25)

    def test_unknown_is_not_full_and_old_stays_old(self):
        from token_tv.personal_faces import remaining_reading
        row = {'status': 'auth_required', 'windows': []}
        self.assertIsNone(remaining_reading(row)[0])
        row = snapshot(0, [('codex_a', 'CODEX', 'codex', [('WEEK', 100, 3600)])])['accounts']['codex_a']
        row['status'] = 'stale'
        self.assertEqual(remaining_reading(row)[0], 0)
        self.assertTrue(remaining_reading(row)[2])

    def test_classic_gameboy_really_uses_two_colors(self):
        from token_tv.personal_faces import render_gameboy
        frame = render_gameboy(snapshot())
        self.assertEqual(frame.size, (240, 240))
        self.assertLessEqual(len(frame.getcolors(240 * 240)), 2)
