"""Tony, 2026-11-03: an official reading is normal up to 180 s, kept with the discreet dot up to 480 s, unknown after that.

Both providers; the dot is the existing end-of-row mark of the saved resets and nothing else is added.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from token_tv.board_arcade import render_arcade
from token_tv.board_art import render_countdown
from token_tv.board_dials import render_dials
from token_tv.board_forge import render_forge
from token_tv.board_gameboy import render_gameboy_board
from token_tv.board_paradise import render_paradise
from token_tv.board_platform import render_platform
from token_tv.board_surf import render_surf
from token_tv.local_usage import (OFFICIAL_FRESH_SECONDS, OFFICIAL_MAX_AGE_SECONDS, atomic_json, expire_official_quota,
                                  fetch_local, local_row, origin_id)
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.sample import snapshot
from token_tv.state import UsageStore

NOW = 1_800_000_000
PAGES = {'gameboy': render_gameboy_board, 'paradise': render_paradise, 'code-forge': render_forge, 'surf': render_surf,
         'dials': render_dials, 'arcade': render_arcade, 'cockpit': render_platform, 'countdown': render_countdown}


def account(provider):
    return {'key': provider, 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo/' + provider}


def record(provider, source=None, fetched=NOW, week=20):
    return {'source': source or provider + '_official_cli', 'origin': origin_id('/demo/' + provider), 'fetched_at': fetched,
            'ordinary_usage_allowed': True, 'stale': False,
            'windows': [{'label': '5H', 'used_percent': 95, 'duration_minutes': 300, 'resets_at': NOW + 7200},
                        {'label': 'WEEK', 'used_percent': week, 'duration_minutes': 10080, 'resets_at': NOW + 6 * 86400}]}


class TiersTests(unittest.TestCase):
    def test_the_limits_are_the_ones_tony_approved(self):
        self.assertEqual((OFFICIAL_FRESH_SECONDS, OFFICIAL_MAX_AGE_SECONDS), (180, 480))

    def test_each_age_is_normal_aged_or_unknown_for_both_providers_and_the_status_line_source(self):
        for provider, source in (('claude', 'claude_official_cli'), ('claude', 'claude_official_statusline'),
                                 ('codex', 'codex_official_cli')):
            for age, outcome in ((0, 'normal'), (179, 'normal'), (180, 'normal'), (181, 'aged'), (479, 'aged'), (480, 'aged'),
                                 (481, 'unknown'), (3600, 'unknown')):
                with self.subTest(source=source, age=age):
                    row = local_row(account(provider), record(provider, source), now=NOW + age)
                    self.assertEqual(row['quota_origin'], source)
                    self.assertEqual(remaining_reading(row)[0] is not None, outcome != 'unknown')
                    self.assertEqual(row.get('reading_aged', False), outcome == 'aged')
                    self.assertEqual(row['status'], 'quota_unavailable' if outcome == 'unknown' else 'ok')
                    if outcome == 'unknown':
                        self.assertEqual(row['windows'], [])
                        self.assertNotIn('reading_aged', row)

    def test_what_blanks_a_reading_at_once_still_does(self):
        # A passed reset, a missing week, a failed refresh: aged or not, they are unknown immediately.
        week_gone = record('claude')
        week_gone['windows'] = week_gone['windows'][:1]
        passed = record('claude')
        passed['windows'][1]['resets_at'] = NOW + 100
        failed = dict(record('claude'), stale=True)
        for raw, age in ((week_gone, 0), (passed, 200), (failed, 0)):
            row = local_row(account('claude'), raw, now=NOW + age)
            self.assertEqual(row['windows'], [])
            self.assertNotIn('reading_aged', row)

    def test_the_session_bars_and_the_week_keep_showing_while_aged(self):
        row = local_row(account('claude'), record('claude'), now=NOW + 400)
        self.assertTrue(row['reading_aged'])
        self.assertEqual(remaining_reading(row)[0], 80)
        self.assertIsNotNone(session_pace(row))            # the five-hour bars show everything they showed
        store = UsageStore([account('claude')], fetch=lambda _: local_row(account('claude'), record('claude'), now=NOW))
        with patch('token_tv.state.time.time', return_value=NOW):
            store.refresh()
        with patch('token_tv.state.time.time', return_value=NOW + 200):
            shown = store.snapshot()['accounts']['claude']
        self.assertTrue(shown['reading_aged'])
        self.assertEqual(shown['weekly_percent'], 20)
        self.assertEqual(shown['session_percent'], 95)

    def test_expire_official_quota_clears_the_mark_when_a_row_is_refreshed(self):
        row = local_row(account('codex'), record('codex'), now=NOW + 300)
        self.assertTrue(row['reading_aged'])
        row['fetched_at'] = NOW + 290                        # a newer observation of the same row
        expire_official_quota(row, NOW + 300)
        self.assertNotIn('reading_aged', row)

    def test_an_unofficial_row_is_never_marked(self):
        row = {'quota_origin': 'something_else', 'fetched_at': 0, 'windows': [{'label': 'WEEK', 'used_percent': 1}], 'status': 'ok'}
        expire_official_quota(row, NOW)
        self.assertNotIn('reading_aged', row)
        self.assertEqual(row['status'], 'ok')


class SourceTests(unittest.TestCase):
    def test_the_monitor_accepts_the_status_line_source_for_claude_only(self):
        with tempfile.TemporaryDirectory() as directory:
            for provider, source, accepted in (('claude', 'claude_official_statusline', True), ('claude', 'claude_official_cli', True),
                                               ('claude', 'codex_official_cli', False), ('claude', 'claude_statusline', False),
                                               ('codex', 'claude_official_statusline', False), ('codex', 'codex_official_cli', True)):
                atomic_json(Path(directory) / (provider + '-official.json'), record(provider, source))
                with self.subTest(provider=provider, source=source), patch('token_tv.local_usage.time.time', return_value=NOW + 5):
                    row = fetch_local(account(provider), directory, official_claude=True, official_codex=True)
                    self.assertEqual(bool(row['windows']), accepted)
                    self.assertEqual(row['quota_origin'], source if accepted else provider + '_official_cli')


class HeartsTests(unittest.TestCase):
    def test_a_known_count_beside_an_aged_reading_is_old_and_nothing_else_changes(self):
        self.assertEqual(banked_hearts({'banked_resets': {'available': 2}}), (2, False))
        self.assertEqual(banked_hearts({'banked_resets': {'available': 2}, 'reading_aged': True}), (2, True))
        self.assertEqual(banked_hearts({'banked_resets': {'available': 0}, 'reading_aged': True}), (0, True))
        self.assertEqual(banked_hearts({'banked_resets': {'available': 2}, 'reading_aged': False}), (2, False))
        # Unknown stays unknown (no invented count) and an old count stays old.
        self.assertEqual(banked_hearts({'banked_resets': {'available': None}, 'reading_aged': True}), (None, False))
        self.assertEqual(banked_hearts({'reading_aged': True}), (None, False))
        self.assertEqual(banked_hearts({'banked_resets': {'available': None, 'last_known': 1}, 'reading_aged': True}), (1, True))


def case(hearts, aged=False, last_known=None):
    data = snapshot(now=NOW, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', 27, 6 * 86400 + 8 * 3600)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', 27, 5 * 86400 + 16 * 3600), ('5H', 41, 7200)])])
    for row in data['accounts'].values():
        row['banked_resets'] = ({'available': hearts, 'confirmed_at': NOW, 'source': 'manual'} if last_known is None
                                else {'available': None, 'last_known': last_known})
        if aged:
            row['reading_aged'] = True
    return data


def draw(render, data):
    with patch('time.time', return_value=NOW):
        image = render(data)
    return (image[0] if isinstance(image, tuple) else image).convert('RGB')


class BoardTests(unittest.TestCase):
    def test_the_dot_at_the_end_of_the_reset_row_is_the_only_sign_of_an_aged_reading_on_every_page(self):
        for name, render in PAGES.items():
            with self.subTest(page=name):
                fresh, aged = draw(render, case(2)), draw(render, case(2, aged=True))
                self.assertNotEqual(fresh.tobytes(), aged.tobytes())            # there is a sign...
                # ...and it is exactly what an old count already gets on that page: no new mark was invented anywhere.
                self.assertEqual(aged.tobytes(), draw(render, case(None, last_known=2)).tobytes())


if __name__ == '__main__':
    unittest.main()
