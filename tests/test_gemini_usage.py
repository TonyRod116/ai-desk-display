import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from token_tv.gemini_usage import (
    GEMINI_FRESH_SECONDS,
    GEMINI_MAX_HOLD_SECONDS,
    GEMINI_SOURCE,
    capture_gemini,
    gemini_tablet_provider,
    parse_agy_quota,
    read_gemini_record,
)

NOW = 1_780_000_000


class GeminiUsageTests(unittest.TestCase):
    def test_parses_official_agy_gemini_weekly_and_five_hour_payload(self):
        payload = {
            'email': 'private@example.test',
            'token': 'secret-token',
            'quota': {
                'gemini-weekly': {
                    'remaining_fraction': 0.9378,
                    'reset_time': '2026-07-06T07:50:32Z',
                    'reset_in_seconds': 560580,
                },
                'gemini-5h': {
                    'remaining_fraction': 0.65,
                    'reset_in_seconds': 7200,
                },
            },
        }
        windows = parse_agy_quota(payload, NOW)
        by_label = {item['label']: item for item in windows}
        self.assertEqual(set(by_label), {'WEEK', '5H'})
        self.assertAlmostEqual(by_label['WEEK']['used_percent'], 6.22, places=2)
        self.assertAlmostEqual(by_label['5H']['used_percent'], 35.0, places=2)
        self.assertEqual(by_label['5H']['resets_at'], NOW + 7200)

    def test_capture_stores_only_sanitized_fields_and_respects_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'gemini-official.json'
            agy_home = Path(tmp) / 'agy-home'
            payload = {
                'email': 'private@example.test',
                'prompt': 'secret prompt',
                'quota': {
                    'gemini-weekly': {
                        'remaining_fraction': 0.84,
                        'reset_in_seconds': 400_000,
                    }
                },
            }
            self.assertTrue(capture_gemini(payload, cache, now=NOW, source_home=agy_home))
            raw = cache.read_text(encoding='utf-8')
            self.assertNotIn('private', raw)
            self.assertNotIn('secret', raw)
            record = read_gemini_record(cache, source_home=agy_home)
            self.assertIsNotNone(record)
            self.assertEqual(record['source'], GEMINI_SOURCE)
            self.assertIsNone(read_gemini_record(cache, source_home=Path(tmp) / 'other-home'))

    def test_fresh_then_aged_until_reset_then_unknown(self):
        record = {
            'fetched_at': NOW,
            'source': GEMINI_SOURCE,
            'windows': [
                {'label': 'WEEK', 'used_percent': 16.0, 'resets_at': NOW + 3600, 'duration_minutes': 10080},
                {'label': '5H', 'used_percent': 40.0, 'resets_at': NOW + 1200, 'duration_minutes': 300},
            ],
        }
        fresh = gemini_tablet_provider(record, NOW + GEMINI_FRESH_SECONDS)
        self.assertEqual(fresh['weekly']['remaining'], 84.0)
        self.assertEqual(fresh['session']['remaining'], 60.0)
        self.assertFalse(fresh['aged'])

        # Past fresh window, before reset: stays visible with aged flag; expired 5H drops independently.
        aged = gemini_tablet_provider(record, NOW + 1500)
        self.assertEqual(aged['weekly']['remaining'], 84.0)
        self.assertTrue(aged['aged'])
        self.assertIsNone(aged['session'])

        # The instant weekly resets_at passes: drops cleanly to honest dashes (weekly: None).
        expired = gemini_tablet_provider(record, NOW + 3600)
        self.assertIsNone(expired['weekly'])
        self.assertFalse(expired['aged'])

        # Beyond maximum hold cap, even with far-future reset: drops to unknown.
        far = dict(record, windows=[{'label': 'WEEK', 'used_percent': 10.0, 'resets_at': NOW + 30 * 86400}])
        self.assertIsNone(gemini_tablet_provider(far, NOW + GEMINI_MAX_HOLD_SECONDS + 1)['weekly'])

    def test_invalid_payloads_do_not_overwrite_previous_good_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'gemini-official.json'
            agy_home = Path(tmp) / 'agy-home'
            good = {'quota': {'gemini-weekly': {'remaining_fraction': 0.5, 'reset_in_seconds': 90_000}}}
            self.assertTrue(capture_gemini(good, cache, now=NOW, source_home=agy_home))
            self.assertFalse(capture_gemini({'quota': {'gemini-weekly': {'remaining_fraction': 1.5}}}, cache, now=NOW + 10, source_home=agy_home))
            self.assertFalse(capture_gemini({'quota': {}}, cache, now=NOW + 20, source_home=agy_home))
            record = read_gemini_record(cache, source_home=agy_home)
            self.assertEqual(record['fetched_at'], NOW)

    def test_ignores_third_party_3p_buckets_and_expired_session_does_not_clobber_live_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'gemini-official.json'
            agy_home = Path(tmp) / 'agy-home'
            # Live session captured first with both gemini-weekly and gemini-5h.
            live = {
                'quota': {
                    '3p-weekly': {'remaining_fraction': 1.0, 'reset_in_seconds': 600_000},
                    '3p-5h': {'remaining_fraction': 1.0, 'reset_in_seconds': 17_900},
                    'gemini-weekly': {'remaining_fraction': 0.80, 'reset_in_seconds': 480_000},
                    'gemini-5h': {'remaining_fraction': 0.72, 'reset_in_seconds': 15_000},
                }
            }
            self.assertTrue(capture_gemini(live, cache, now=NOW, source_home=agy_home))
            # An idle agy session later fires with an expired gemini-5h and a full 3p-5h:
            # must ignore 3p-5h and keep the still-live gemini-5h from the previous capture.
            stale = {
                'quota': {
                    '3p-5h': {'remaining_fraction': 1.0, 'reset_in_seconds': 17_900},
                    'gemini-weekly': {'remaining_fraction': 0.79, 'reset_in_seconds': 479_900},
                    'gemini-5h': {'remaining_fraction': 0.10, 'resets_at': NOW - 3600},
                }
            }
            self.assertTrue(capture_gemini(stale, cache, now=NOW + 100, source_home=agy_home))
            prov = gemini_tablet_provider(read_gemini_record(cache, source_home=agy_home), NOW + 100)
            self.assertAlmostEqual(prov['weekly']['remaining'], 79.0, places=2)
            self.assertAlmostEqual(prov['session']['remaining'], 72.0, places=2)
            self.assertEqual(prov['session']['resets_at'], NOW + 15_000)

    def test_statusline_script_writes_nothing_to_stdout_and_captures_sanitized_json(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'gemini_statusline_capture.py'
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.dumps({
                'quota': {'gemini-weekly': {'remaining_fraction': 0.77, 'reset_in_seconds': 250_000}},
                'account': {'email': 'private@example.test'},
            })
            proc = subprocess.run(
                [sys.executable, '-B', str(script), '--cache-dir', tmp],
                input=payload,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )
            self.assertEqual(proc.stdout, '')
            self.assertEqual(proc.stderr, '')
            saved = Path(tmp) / 'gemini-official.json'
            self.assertTrue(saved.is_file())
            self.assertNotIn('private', saved.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
