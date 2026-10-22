import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from token_tv.display import render_page
from token_tv.local_usage import atomic_json, fetch_local, local_row, origin_id
from token_tv.personal_faces import remaining_reading, session_hours, session_pace_line, session_remaining
from token_tv.state import UsageStore
from token_tv.themes import Canvas

FACES = ('game-boy', 'game-boy-pocket', 'retro', 'amber-terminal', 'orbit')


def account(provider):
    return {'key': provider, 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo/' + provider}


def observation(provider, weekly=20):
    return {'source': provider + '_official_cli', 'origin': origin_id('/demo/' + provider),
            'fetched_at': 1000, 'ordinary_usage_allowed': True, 'stale': False,
            'windows': [{'label': '5H', 'used_percent': 95, 'duration_minutes': 300, 'resets_at': 8200},
                        {'label': 'WEEK', 'used_percent': weekly, 'duration_minutes': 10080,
                         'resets_at': 1000 + 6 * 86400 + 20 * 3600}]}


class WeeklyQuotaTests(unittest.TestCase):
    def test_weekly_percentage_and_countdown_share_the_same_window(self):
        for provider in ('claude', 'codex'):
            with self.subTest(provider=provider), patch('token_tv.display.time.time', return_value=1000):
                row = local_row(account(provider), observation(provider), now=1000)
                value, period, old, reset = remaining_reading(row)
                self.assertEqual(value, 80)
                self.assertIn(period, ('WK', 'WEEK'))
                self.assertFalse(old)
                self.assertEqual(reset, '6d 20h')

    def test_missing_week_is_unknown_instead_of_replaced_by_five_hour_quota(self):
        for provider in ('claude', 'codex'):
            raw = observation(provider)
            raw['windows'] = raw['windows'][:1]
            row = local_row(account(provider), raw, now=1000)
            self.assertIsNone(remaining_reading(row)[0])
            self.assertEqual(remaining_reading(row)[3], '--')
            self.assertEqual(row['status'], 'quota_unavailable')

    def test_zero_weekly_use_is_a_known_full_week(self):
        for provider in ('claude', 'codex'):
            row = local_row(account(provider), observation(provider, weekly=0), now=1000)
            self.assertEqual(remaining_reading(row)[0], 100)

    def test_missing_week_is_unavailable_in_local_sources_too(self):
        for provider, source in (('claude', 'claude_statusline'), ('codex', 'codex_session')):
            with self.subTest(provider=provider):
                raw = observation(provider)
                raw['source'] = source
                raw['windows'] = raw['windows'][:1]
                row = local_row(account(provider), raw, now=1000)
                self.assertEqual(row['status'], 'quota_unavailable')
                self.assertEqual(row['windows'], [])
        row = local_row(account('grok'), raw, now=1000)
        self.assertEqual(row['status'], 'ok')

    def test_all_five_faces_draw_weekly_numbers_and_weekly_reset(self):
        rows = {p: local_row(account(p), observation(p), now=1000) for p in ('claude', 'codex')}
        original_text = Canvas.text
        for style in ('game-boy', 'game-boy-pocket', 'retro', 'amber-terminal', 'orbit'):
            texts = []
            def observe_text(canvas, position, text, *args, **kwargs):
                texts.append(text)
                return original_text(canvas, position, text, *args, **kwargs)
            with self.subTest(style=style), patch.object(Canvas, 'text', observe_text), \
                 patch('token_tv.display.time.time', return_value=1000):
                render_page({'accounts': rows}, 0, style)
            self.assertTrue(any(value in texts for value in ('80%', '80')), texts)
            normalized = [value.casefold() for value in texts]
            self.assertTrue(any(value in normalized for value in ('6d 20h', '6d20h')), texts)
            self.assertNotIn('2h 0m', normalized)
            self.assertNotIn('2h0m', normalized)

    def test_session_remaining_is_claude_only_fresh_and_known(self):
        def remaining(provider, change=None, now=1000):
            raw = observation(provider)
            if change:
                change(raw)
            return session_remaining(local_row(account(provider), raw, now=now), now=now)
        def renewed(raw):                      # the five-hour reset has just passed
            raw['fetched_at'] = 8900
            raw['windows'][1]['resets_at'] = 8900 + 6 * 86400
        self.assertEqual(remaining('claude'), 5)                                     # 95% used
        self.assertEqual(remaining('claude', lambda r: r['windows'][0].update(used_percent=100)), 0)
        self.assertIsNone(remaining('codex'))                                        # not Claude
        self.assertIsNone(remaining('claude', lambda r: r['windows'].pop(0)))        # unknown is not 0
        self.assertIsNone(remaining('claude', lambda r: r.update(stale=True)))       # failed refresh
        self.assertIsNone(remaining('claude', lambda r: r.update(fetched_at=600)))   # older than 180 s
        self.assertIsNone(remaining('claude', renewed, now=8950))

    def test_session_hours_is_the_time_left_clamped_to_the_five_hour_window(self):
        def hours(provider='claude', resets_at=1000 + 5400, now=1000, change=None):
            raw = observation(provider)
            raw['windows'][0]['resets_at'] = resets_at
            if change:
                change(raw)
            return session_hours(local_row(account(provider), raw, now=now), now=now)
        self.assertAlmostEqual(hours(), 1.5)
        self.assertEqual(hours(resets_at=1000 + 9 * 3600), 5.0)                      # never more than the window
        self.assertIsNone(hours('codex'))
        self.assertIsNone(hours(change=lambda r: r['windows'].pop(0)))               # unknown stays unknown
        self.assertIsNone(hours(change=lambda r: r.update(stale=True)))

    def test_session_line_is_a_quota_bar_above_a_time_bar_and_they_never_overlap(self):
        class Recorder:
            def __init__(self):
                self.rects, self.points = [], []
            def rectangle(self, xy, fill=None, outline=None, width=1):
                self.rects.append((tuple(xy), fill))
            def point(self, xy, fill=None):
                self.points.append((xy, fill))
        class Cv:
            def __init__(self):
                self.draw = Recorder()

        def drawn(pace, row=3):
            cv = Cv()
            session_pace_line(cv, 10, 50, 216, pace, 'QUOTA', 'TRACK', 'TIME', row=row)
            quota = [xy for xy, color in cv.draw.rects if color == 'QUOTA']
            time_ = [xy for xy, color in cv.draw.rects if color == 'TIME']
            return quota, time_, cv.draw.points
        seg = (216 - 16) / 5                                    # 40 px per hour
        width = lambda rect: rect[2] - rect[0] + 1

        quota, time_, points = drawn((100, 5))
        self.assertEqual((len(quota), len(time_)), (5, 5))     # all the quota, all five hours
        self.assertTrue(points)                                 # the faint track is always drawn

        quota, time_, _ = drawn((50, 1.5))                      # half the quota, 1h30 left
        self.assertEqual(len(quota), 3)                         # two whole hours and half of the third
        self.assertEqual(len(time_), 2)                         # one whole hour and half of the second
        self.assertAlmostEqual(width(time_[1]), seg / 2, delta=2)   # halfway through the second: ~1h30
        self.assertLess(max(r[3] for r in quota), min(r[1] for r in time_))  # separate rows

        # The case a tick inside the bar used to hide: more quota left than time left.
        for pace in ((95, 1.5), (100, 0.25), (60, 2)):
            quota, time_, _ = drawn(pace)
            self.assertTrue(quota and time_, pace)
            self.assertLess(max(r[3] for r in quota), min(r[1] for r in time_), pace)

        no_quota, still_time, _ = drawn((0, 2))                 # a spent quota is a known zero
        self.assertEqual(no_quota, [])
        self.assertEqual(len(still_time), 2)
        # Quota moves in 5% steps and time in quarter hours: nothing changes every minute.
        self.assertEqual(drawn((51, 1.51)), drawn((55, 1.5)))
        self.assertNotEqual(drawn((50, 1.7)), drawn((50, 1.5)))
        self.assertNotEqual(drawn((50, 1.5)), drawn((60, 1.5)))
        self.assertEqual(drawn(None), ([], [], []))             # unknown draws nothing at all
        compact_quota, compact_time, _ = drawn((50, 1.5), row=1)
        self.assertLess(max(r[3] for r in compact_quota), min(r[1] for r in compact_time))

    def test_time_left_moves_only_the_session_line(self):
        from PIL import ImageChops
        from token_tv.personal_faces import RENDERERS as PERSONAL
        from token_tv.themes import RENDERERS as THEMES
        renderers = {'retro': THEMES['retro'], **PERSONAL}

        def snapshot(resets_at):
            raw = observation('claude')
            raw['windows'][0]['resets_at'] = resets_at
            return {'accounts': {'codex': local_row(account('codex'), observation('codex'), now=1000),
                                 'claude': local_row(account('claude'), raw, now=1000)}}
        for style in FACES:
            with self.subTest(style=style), patch('token_tv.display.time.time', return_value=1000):
                short = renderers[style](snapshot(1000 + 3600)).convert('RGB')
                long = renderers[style](snapshot(1000 + 4 * 3600)).convert('RGB')
                box = ImageChops.difference(short, long).getbbox()
                self.assertIsNotNone(box, 'the tick must move with the time left')
                self.assertGreaterEqual(box[1], 150, 'only the session line under Claude\'s row changes')

    def test_session_line_is_the_only_change_on_every_face(self):
        # Claude's five-hour session is drawn as a discreet dotted twin of the weekly
        # bar. Nothing else may move: the weekly number, bar and reset stay as they were.
        from PIL import ImageChops
        from token_tv.personal_faces import RENDERERS as PERSONAL
        from token_tv.themes import RENDERERS as THEMES
        renderers = {'retro': THEMES['retro'], **PERSONAL}

        def snapshot(provider, change=None):
            raw = observation(provider)
            if change:
                change(raw)
            return {'accounts': {'codex': local_row(account('codex'), observation('codex'), now=1000),
                                 provider: local_row(account(provider), raw, now=1000)}}
        for style in FACES:
            with self.subTest(style=style), patch('token_tv.display.time.time', return_value=1000):
                known = renderers[style](snapshot('claude')).convert('RGB')
                unknown = renderers[style](snapshot('claude', lambda r: r['windows'].pop(0))).convert('RGB')
                box = ImageChops.difference(known, unknown).getbbox()
                self.assertIsNotNone(box, 'a known session must draw its line')
                self.assertGreaterEqual(box[1], 100, 'only inside Claude\'s lower row')
                # Codex never gets the line, even with a five-hour window in its data.
                codex = renderers[style](snapshot('codex')).convert('RGB')
                codex_without = renderers[style](snapshot('codex', lambda r: r['windows'].pop(0))).convert('RGB')
                self.assertIsNone(ImageChops.difference(codex, codex_without).getbbox())

    def test_both_official_readings_expire_in_memory_if_the_reader_stops(self):
        for provider in ('claude', 'codex'):
            a = account(provider)
            row = local_row(a, observation(provider), now=1000)
            store = UsageStore([a], fetch=lambda _: row)
            with patch('token_tv.state.time.time', return_value=1000):
                store.refresh()
            with patch('token_tv.state.time.time', return_value=1200):
                expired = store.snapshot()['accounts'][provider]
            self.assertEqual(expired['status'], 'quota_unavailable')
            self.assertEqual(expired['windows'], [])
            self.assertIsNone(remaining_reading(expired)[0])

    def test_claude_week_survives_the_five_hour_reset_but_codex_is_unchanged(self):
        # Observation: 5H resets at 8200, WEEK at 1000 + 6d 20h. Look at it at 8201,
        # right after the five-hour renewal, with a reading no older than 180 s.
        for provider in ('claude', 'codex'):
            with self.subTest(provider=provider):
                raw = observation(provider)
                raw['fetched_at'] = 8100
                raw['windows'][1]['resets_at'] = 8100 + 6 * 86400
                row = local_row(account(provider), raw, now=8201)
                a = account(provider)
                store = UsageStore([a], fetch=lambda _: row)
                with patch('token_tv.state.time.time', return_value=8201):
                    store.refresh()
                    shown = store.snapshot()['accounts'][provider]
                if provider == 'claude':
                    self.assertEqual([w['label'] for w in shown['windows']], ['WEEK'])
                    self.assertEqual(shown['status'], 'ok')
                    self.assertEqual(remaining_reading(shown)[0], 80)
                    self.assertIsNone(shown['session_percent'])
                else:
                    self.assertEqual(shown['windows'], [])
                    self.assertEqual(shown['status'], 'quota_unavailable')

    def test_claude_unconfirmed_resets_never_become_a_known_weekly_reading(self):
        # A five-hour window without a reset is unknown and dropped. A week without
        # its own reset is not a reading at all, whatever the five-hour window says.
        raw = observation('claude')
        raw['fetched_at'] = 8100
        raw['windows'][0]['resets_at'] = None
        raw['windows'][1]['resets_at'] = 8100 + 6 * 86400
        row = local_row(account('claude'), raw, now=8150)
        self.assertEqual([w['label'] for w in row['windows']], ['WEEK'])
        for five_hour_reset in (None, 8000, 9000):
            with self.subTest(five_hour_reset=five_hour_reset):
                raw = observation('claude')
                raw['fetched_at'] = 8100
                raw['windows'][0]['resets_at'] = five_hour_reset
                raw['windows'][1]['resets_at'] = None
                row = local_row(account('claude'), raw, now=8150)
                self.assertEqual(row['windows'], [])
                self.assertEqual(row['status'], 'quota_unavailable')
                a = account('claude')
                store = UsageStore([a], fetch=lambda _: row)
                with patch('token_tv.state.time.time', return_value=8150):
                    store.refresh()
                    snapshot = store.snapshot()['accounts']['claude']
                self.assertIsNone(snapshot['weekly_percent'])
                self.assertEqual(snapshot['windows'], [])

    def test_claude_week_does_not_survive_its_own_reset_or_a_stale_reading(self):
        raw = observation('claude')
        raw['fetched_at'] = 8100
        raw['windows'][1]['resets_at'] = 8200
        self.assertEqual(local_row(account('claude'), raw, now=8201)['windows'], [])
        raw = observation('claude')
        self.assertEqual(local_row(account('claude'), raw, now=1000 + 181)['windows'], [])

    def test_claude_cached_refresh_does_not_present_old_percentages(self):
        a = account('claude')
        fresh = local_row(a, observation('claude'), now=1000)
        store = UsageStore([a], fetch=lambda _: fresh)
        with patch('token_tv.state.time.time', return_value=1000):
            store.refresh()
            raw = observation('claude')
            raw['stale'] = True
            fresh = local_row(a, raw, now=1000)
            store.refresh()
            self.assertEqual(store.snapshot()['accounts']['claude']['windows'], [])

    def test_a_missing_claude_cache_cannot_recover_previous_percentages(self):
        a = account('claude')
        with tempfile.TemporaryDirectory() as directory, patch('token_tv.local_usage.time.time', return_value=1000):
            cache = Path(directory) / 'claude-official.json'
            atomic_json(cache, observation('claude'))
            store = UsageStore([a], fetch=lambda item: fetch_local(item, directory, official_claude=True))
            store.refresh()
            cache.unlink()
            store.refresh()
            row = store.snapshot()['accounts']['claude']
            self.assertEqual(row['windows'], [])
            self.assertEqual(row['quota_origin'], 'claude_official_cli')
