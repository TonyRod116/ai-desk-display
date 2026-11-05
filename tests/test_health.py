"""/health says 503 only when quota is unavailable or the display publication is unconfirmed (Tony, 2026-11-03).

An unknown saved-reset bank kept it at 503 for 19 days and hid real trouble; it is a warning now.
"""
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.request import urlopen

from token_tv import live
from token_tv.state import UsageStore


def row(provider, status='ok'):
    return {'key': provider, 'alias': provider.upper(), 'provider': provider, 'status': status, 'fetched_at': time.time(),
            'windows': [{'label': 'WEEK', 'used_percent': 20, 'resets_at': time.time() + 86400, 'duration_minutes': 10080}]}


class HealthTests(unittest.TestCase):
    def health(self, statuses=None, display='ok', banks=None, clock=True, automatic=('claude', 'codex')):
        statuses = statuses or {'claude': 'ok', 'codex': 'ok'}
        rows = {provider: row(provider, status) for provider, status in statuses.items()}
        store = UsageStore([{'key': p, 'alias': p, 'provider': p} for p in rows], fetch=lambda account: rows[account['key']])
        store.refresh()
        preferences = MagicMock()
        preferences.config = {'device_url': 'http://127.0.0.1'} if clock else {}
        preferences.reset_snapshot.return_value = {}
        preferences.snapshot.return_value = {
            'style': 'retro', 'status': display if clock else 'preview_only', 'automatic_reset_providers': list(automatic),
            'saved_resets': banks if banks is not None else {'claude': {'available': 1}, 'codex': {'available': 0}}}
        server = ThreadingHTTPServer(('127.0.0.1', 0), live.handler(store, preferences))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            try:
                response = urlopen(f'http://127.0.0.1:{server.server_port}/health')
            except HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_everything_in_order_is_200_with_no_warnings_and_the_old_fields(self):
        status, body = self.health()
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['warnings'], [])
        self.assertEqual(set(body), {'status', 'updated_at', 'providers', 'display_status', 'saved_resets', 'warnings'})
        self.assertEqual(body['providers'], {'claude': 'ok', 'codex': 'ok'})
        self.assertEqual(body['display_status'], 'ok')
        self.assertEqual(body['saved_resets'], {'claude': 'ok', 'codex': 'ok'})        # the existing field keeps its meaning

    def test_an_unknown_saved_reset_bank_is_a_warning_not_a_failure(self):
        status, body = self.health(banks={'claude': {'available': None}, 'codex': {'available': 2}})
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['warnings'], ['claude_saved_resets_unknown'])
        self.assertEqual(body['saved_resets'], {'claude': 'unknown', 'codex': 'ok'})
        status, body = self.health(banks={})
        self.assertEqual((status, sorted(body['warnings'])), (200, ['claude_saved_resets_unknown', 'codex_saved_resets_unknown']))
        status, body = self.health(banks={}, automatic=())                              # nothing automatic: nothing to warn about
        self.assertEqual((status, body['warnings'], body['saved_resets']), (200, [], {}))

    def test_unavailable_quota_is_still_a_503(self):
        for broken in ('quota_unavailable', 'stale', 'error', 'auth_required', 'usage_blocked'):
            status, body = self.health(statuses={'claude': broken, 'codex': 'ok'})
            self.assertEqual((status, body['status']), (503, 'degraded'), broken)
            self.assertEqual(body['providers']['claude'], broken)

    def test_an_unconfirmed_display_publication_is_still_a_503(self):
        for display in ('queued', 'error', 'preview_only'):
            status, body = self.health(display=display)
            self.assertEqual((status, body['status'], body['display_status']), (503, 'degraded', display), display)
        status, body = self.health(clock=False)                                         # no clock configured: preview is right
        self.assertEqual(status, 200)

    def test_trouble_and_a_warning_together_report_both(self):
        status, body = self.health(statuses={'claude': 'quota_unavailable', 'codex': 'ok'}, banks={'claude': {'available': None}})
        self.assertEqual((status, body['status']), (503, 'degraded'))
        self.assertIn('claude_saved_resets_unknown', body['warnings'])


if __name__ == '__main__':
    unittest.main()
