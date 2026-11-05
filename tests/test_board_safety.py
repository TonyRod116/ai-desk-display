"""What `token-tv board --check` says about the build trial, the watchdog and a doubtful wifi reading (firmware 42)."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from token_tv.board import health_text, signal_text

TOKEN = '0123456789abcdef'
OLD = {'model': 'tokentv-board', 'fw': 'ai-desk-display 41', 'w': 320, 'h': 240, 'paired': True, 'up': 3725, 'rst': 4,
       'taps': 12, 'longs': 1, 'rssi': -61, 'silent': 42, 'renews': 2, 'srest': 1, 'page': 3, 'info': 0, 'active': 8, 'pages': 8}


class Info(BaseHTTPRequestHandler):
    reply = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps(self.reply).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CheckTests(unittest.TestCase):
    def test_the_signal_is_a_fact_only_when_it_is_believable(self):
        self.assertEqual(signal_text(-61), 'wifi signal -61 dBm')
        self.assertEqual(signal_text(-10), 'wifi signal -10 dBm')
        for doubtful in (-9, -2, 5):
            with self.subTest(rssi=doubtful):
                text = signal_text(doubtful)
                self.assertIn('implausible', text)
                self.assertNotIn('wifi signal ' + str(doubtful) + ' dBm', text)
        for none in (0, None, '-50', True, 1.5):                      # no reading, or not a number at all
            with self.subTest(rssi=none):
                self.assertIsNone(signal_text(none))

    def test_older_firmware_gets_the_same_sentence_as_before(self):
        text = health_text(OLD)
        for expected in ('Up 62 min', 'crash', '12 taps', '1 long presses', '-61 dBm', 'last heard 42 s ago', 'renewed 2x',
                         'cycling 8 of 8', 'showing page 3'):
            self.assertIn(expected, text)
        for unexpected in ('trial', 'confirmed', 'watchdog', 'previous image'):
            self.assertNotIn(unexpected, text)
        self.assertEqual(health_text({'model': 'tokentv-board', 'fw': 'tokentv-board 5'}), '')

    def test_a_build_on_trial_a_confirmed_build_and_a_rollback_are_told_apart(self):
        trial = health_text({**OLD, 'trial': 1, 'strikes': 2, 'build': '3fa9c1d2e4b5', 'fallback': 1, 'rolled': 0, 'wdt': 120})
        self.assertIn('build 3fa9c1d2e4b5 is on trial (2 of 3 crashes counted)', trial)
        self.assertIn('a previous image is ready to go back to', trial)
        self.assertIn('watchdog 120 s', trial)
        confirmed = health_text({**OLD, 'trial': 0, 'strikes': 0, 'build': '3fa9c1d2e4b5', 'fallback': 0, 'rolled': 0, 'wdt': 120})
        self.assertIn('build 3fa9c1d2e4b5 confirmed', confirmed)
        self.assertIn('no previous image to go back to', confirmed)
        self.assertNotIn('is on trial', confirmed)
        fallback = health_text({**OLD, 'trial': 0, 'strikes': 0, 'build': '9e411bf810ab', 'rolled': 1, 'fallback': 0})
        self.assertIn('running because the newer build failed three times', fallback)
        odd = health_text({**OLD, 'trial': 1, 'strikes': 'many', 'build': 7, 'wdt': 'x'})   # nonsense is not echoed
        self.assertIn('is on trial (0 of 3', odd)
        self.assertNotIn('many', odd)

    def test_the_backlight_and_the_details_card_are_reported_in_plain_words(self):
        text = health_text({**OLD, 'brightness': 1, 'bright': 25, 'bright_now': 15, 'card': 1, 'card_age': 12, 'card_bad': 2})
        self.assertIn('backlight 15% (scheduled 25%)', text)
        self.assertIn('details card received 12 s ago', text)
        self.assertIn('2 details lines refused', text)
        text = health_text({**OLD, 'brightness': 1, 'bright': 100, 'bright_now': 100, 'card': 1, 'card_age': -1, 'card_bad': 0})
        self.assertIn('backlight 100%', text)
        self.assertNotIn('scheduled', text)
        self.assertIn('no details card received yet', text)
        self.assertNotIn('refused', text)
        for odd in ({'brightness': 1, 'bright': 'x', 'bright_now': 5}, {'brightness': 0, 'bright': 5, 'bright_now': 5},
                    {'card': 1, 'card_age': 'x'}, {'card': 2, 'card_age': 3}):
            with self.subTest(odd=odd):
                text = health_text({**OLD, **odd})
                self.assertNotIn('backlight', text)
                self.assertNotIn('details', text)
        self.assertNotIn('backlight', health_text(OLD))                         # firmware 41 says nothing of either

    def test_the_free_memory_is_reported_so_an_install_can_be_compared_with_the_one_before(self):
        self.assertIn('166 kB of memory free', health_text({**OLD, 'free_heap': 170000}))
        for odd in (0, -1, '170000', None, True):
            with self.subTest(odd=odd):
                self.assertNotIn('memory', health_text({**OLD, 'free_heap': odd}))
        self.assertNotIn('memory', health_text(OLD))

    def test_check_prints_a_doubtful_signal_as_doubtful(self):
        from token_tv.cli import main
        Info.reply = {**OLD, 'rssi': -2}
        server = ThreadingHTTPServer(('127.0.0.1', 0), Info)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({
                'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source_home': '/tmp/demo'}],
                'local_only': True, 'board_display': {'url': f'http://127.0.0.1:{server.server_port}', 'token': TOKEN}}))
            with patch('sys.stdout', new_callable=StringIO) as out:
                self.assertEqual(main(['board', '--config', str(path), '--check']), 0)
        self.assertIn('implausible', out.getvalue())
        self.assertNotIn('wifi signal -2 dBm', out.getvalue())
        self.assertNotIn(TOKEN, out.getvalue())


if __name__ == '__main__':
    unittest.main()
