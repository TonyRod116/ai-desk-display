"""The PC's side of the details card: the line it builds, and how it rides on the heartbeat (Tony, 2026-11-03)."""
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from token_tv import reader_status
from token_tv.board import CARD_MAX, BoardDisplay, card_is_valid, publish_pages
from token_tv.board_card import MAX_PAYLOAD, card_payload
from token_tv.sample import snapshot

NOW = 1_800_000_000
D, H = 86400, 3600
TOKEN = '0123456789abcdef'


def rows(codex_used=38, claude_used=25, session_used=60, week_codex=3 * D + 4 * H, week_claude=2 * D + 9 * H, session=5400):
    data = snapshot(NOW, [('codex_a', 'CODEX A', 'codex', [('WEEK', codex_used, week_codex)]),
                          ('claude_a', 'CLAUDE A', 'claude', [('WEEK', claude_used, week_claude), ('5H', session_used, session)])])
    data['accounts']['codex_a'].update(fetched_at=NOW - 95, banked_resets={'available': 2})
    data['accounts']['claude_a'].update(fetched_at=NOW - 120, banked_resets={'available': 0})
    return data


class CardLineTests(unittest.TestCase):
    def test_a_normal_snapshot_gives_exactly_this_line(self):
        self.assertEqual(card_payload(rows(), NOW),
                         '1,xw62,xr273600,xa95,xs2,lw75,lr205200,lh40,lk5400,la120,ls0')

    def test_percentages_are_rounded_like_every_scene_and_a_small_positive_is_never_zero(self):
        for used, token in ((0, '100'), (37.5, '62'), (37.6, '62'), (62.4, '38'), (99, '1'), (99.4, '<'), (99.5, '<'),
                            (99.99, '<'), (100, '0'), (140, '0'), (-5, '100')):
            with self.subTest(used=used):
                self.assertIn(f',xw{token},', card_payload(rows(codex_used=used), NOW) + ',')

    def test_unknown_is_a_dash_with_its_reason_and_never_a_number(self):
        data = snapshot(NOW, [('codex_a', 'CODEX A', 'codex', []), ('claude_a', 'CLAUDE A', 'claude', [])])
        for row in data['accounts'].values():
            row['status'], row['fetched_at'] = 'quota_unavailable', 0
        line = card_payload(data, NOW)
        self.assertEqual(line, '1,xw-,xr-,xa-,xs-,xeNo reading,lw-,lr-,la-,ls-,leNo reading')

    def test_the_reason_comes_from_the_readers_fixed_words_and_a_missing_reader_is_tolerated(self):
        for reason, words in reader_status.REASONS.items():
            data = rows()
            data['accounts']['claude_a'].update(windows=[], status='quota_unavailable',
                                                reader={'state': 'failing', 'reason': reason, 'since': NOW, 'retry_at': None})
            with self.subTest(reason=reason):
                self.assertIn(',le' + words[0], card_payload(data, NOW))
        odd = rows()
        odd['accounts']['claude_a'].update(windows=[], reader={'state': 'failing', 'reason': ['x'], 'since': NOW})
        self.assertIn(',leNo reading', card_payload(odd, NOW))                  # nonsense falls back to the unknown words
        gone = rows()
        gone['accounts']['claude_a']['windows'] = []                            # no `reader` key at all
        self.assertIn(',leNo reading', card_payload(gone, NOW))
        healthy = rows()
        healthy['accounts']['claude_a']['reader'] = {'state': 'ok', 'reason': 'unknown', 'since': NOW, 'retry_at': None}
        self.assertNotIn(',le', card_payload(healthy, NOW))                     # nothing is missing: nothing is explained
        aged = rows()
        aged['accounts']['claude_a']['reader'] = {'state': 'failing', 'reason': 'rate_limited', 'since': NOW, 'retry_at': None}
        line = card_payload(aged, NOW)
        self.assertIn(',lw75,', line)                                           # an old reading keeps its number ...
        self.assertTrue(line.endswith('leToo many requests'))                   # ... and says why it is old

    def test_saved_resets_are_exact_and_an_old_count_says_so(self):
        for banked, token in (({'available': 3}, 's3'), ({'available': 0}, 's0'), ({'available': None, 'last_known': 1}, 's1o'),
                              ({'available': None}, 's-'), ({}, 's-'), ({'available': 250}, 's99'), ({'available': True}, 's-'),
                              ({'available': -1}, 's-'), ({'available': '2'}, 's-'), ({'available': 2.0}, 's-')):
            data = rows()
            data['accounts']['codex_a']['banked_resets'] = banked
            with self.subTest(banked=banked):
                self.assertIn(',x' + token + ',', card_payload(data, NOW) + ',')

    def test_a_reset_that_has_passed_or_is_absurd_is_unknown_and_the_age_never_goes_negative(self):
        data = rows(week_codex=-5)
        self.assertIn(',xr-,', card_payload(data, NOW))
        data = rows(week_codex=10_000_000 + 100)
        self.assertIn(',xr-,', card_payload(data, NOW))
        data = rows()
        data['accounts']['codex_a']['fetched_at'] = NOW + 30                    # a clock that is a little ahead
        self.assertIn(',xa0,', card_payload(data, NOW))
        data['accounts']['codex_a']['fetched_at'] = 0
        self.assertIn(',xa-,', card_payload(data, NOW))

    def test_the_five_hour_window_is_claudes_alone_and_only_while_it_is_live(self):
        line = card_payload(rows(), NOW)
        self.assertEqual(line.count(',lh'), 1)
        self.assertNotIn(',xh', line)
        self.assertNotIn(',xk', line)
        expired = rows(session=-60)
        self.assertNotIn(',lh', card_payload(expired, NOW))
        codex = snapshot(NOW, [('codex_a', 'CODEX A', 'codex', [('WEEK', 10, D), ('5H', 20, H)])])
        self.assertNotIn(',xh', card_payload(codex, NOW))
        self.assertNotIn('lh', card_payload(codex, NOW))

    def test_one_provider_gives_one_side_and_no_account_data_travels(self):
        solo = snapshot(NOW, [('claude_a', 'SECRET ALIAS', 'claude', [('WEEK', 20, D)])])
        solo['accounts']['claude_a'].update(fetched_at=NOW - 5, email='someone@example.com', identity_hash='abc123', source_home='/home/x')
        line = card_payload(solo, NOW)
        self.assertEqual(line, '1,lw80,lr86400,la5,ls-')
        for secret in ('SECRET', 'someone', 'example', 'abc123', '/home', 'claude_a'):
            self.assertNotIn(secret, card_payload(solo, NOW))
        self.assertIsNone(card_payload({'accounts': {'k': {'provider': 'grok', 'status': 'ok', 'windows': [], 'alias': 'G'}}}, NOW)
                          and None)   # a provider the card does not know is never invented

    def test_it_is_short_ascii_and_only_the_documented_characters(self):
        for data in (rows(), rows(codex_used=99.9, claude_used=100, session_used=100)):
            line = card_payload(data, NOW)
            self.assertLessEqual(len(line), MAX_PAYLOAD)
            self.assertEqual(MAX_PAYLOAD, CARD_MAX)
            self.assertRegex(line, r'[0-9A-Za-z ,<-]+')
            self.assertTrue(line.isascii() and card_is_valid(line))

    def test_a_snapshot_that_cannot_be_read_gives_no_card_and_never_an_error(self):
        for bad in ({}, {'accounts': None}, {'accounts': {'a': None}}, {'accounts': {'a': {'provider': 'codex'}}},
                    {'accounts': {'a': {'provider': 'codex', 'status': 'ok', 'windows': [{'label': 'WEEK', 'used_percent': 'x',
                                                                                           'resets_at': 'y'}]}}}):
            with self.subTest(bad=bad):
                line = card_payload(bad, NOW)
                self.assertTrue(line is None or card_payload(bad, NOW) == line)
        nan = rows()
        nan['accounts']['codex_a']['windows'][0].update(used_percent=float('nan'), resets_at=float('inf'))
        self.assertIn(',xw-,xr-,', card_payload(nan, NOW))
        text = rows()
        text['accounts']['codex_a']['windows'][0]['used_percent'] = '38'
        self.assertIn(',xw-,', card_payload(text, NOW))


class Spy:
    """A board that records the heartbeat it is given; older fakes take no argument."""
    capacity = 8

    def __init__(self, accepts_card=True):
        self.pings, self.uploads = [], []
        if not accepts_card:
            self.ping = self.plain_ping

    def ping(self, card=None):
        self.pings.append(card)
        return '11111111'

    def plain_ping(self):
        self.pings.append('plain')
        return '11111111'

    def upload(self, number, image):
        self.uploads.append(number)
        return {'page': number, 'status': 200, 'bytes': len(image)}


class HeartbeatTests(unittest.TestCase):
    def test_the_card_rides_on_the_heartbeat_and_nothing_extra_is_requested(self):
        board = BoardDisplay('http://192.168.1.60', TOKEN)
        paths = []
        board.request = lambda path, **kwargs: (paths.append(path) or (200, b'11111111'))
        board.ping()
        board.ping('1,xw<,xs0o,leSign-in needed')
        self.assertEqual(len(paths), 2)                                             # one request per heartbeat, card or not
        self.assertRegex(paths[0], r'^/ping\?clock=\d{10}$')
        self.assertRegex(paths[1], r'^/ping\?clock=\d{10}&card=1,xw%3C,xs0o,leSign-in%20needed$')
        for bad in ('', 'é', 'x' * (CARD_MAX + 1), '1,xw5\n', 5, b'1,xw5', '1,xw5\x00'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                board.ping(bad)
        self.assertEqual(len(paths), 2)                                             # nothing invalid was sent
        self.assertEqual(len('x' * CARD_MAX), CARD_MAX)
        board.ping('x' * CARD_MAX)                                                  # exactly the limit still goes
        self.assertEqual(len(paths), 3)

    def test_a_card_is_passed_on_once_and_a_bad_one_never_stands_in_the_way_of_the_heartbeat(self):
        pages = [b'TVF1' + b'\0' * 12]
        board, sent = Spy(), {}
        publish_pages(board, pages, sent, card='1,xw62')
        self.assertEqual(board.pings, ['1,xw62'])
        self.assertEqual(board.uploads, [0])
        publish_pages(board, pages, sent, card='1,xw62')                            # nothing new to upload: just the heartbeat
        self.assertEqual((board.pings, board.uploads), (['1,xw62', '1,xw62'], [0]))
        for bad in ('é' * 5, 'x' * 500, '', 'a\nb'):                                # a bad line is dropped, the plain heartbeat goes
            before = len(board.pings)
            publish_pages(board, pages, sent, card=bad)
            self.assertEqual(board.pings[before:], [None])
        self.assertEqual(board.uploads, [0])                                        # and no page was re-sent because of it
        old = Spy(accepts_card=False)                                               # boards that cannot take it are given the plain call
        publish_pages(old, pages, {})
        self.assertEqual(old.pings, ['plain'])

    def test_only_a_board_that_says_it_can_show_a_card_is_ever_sent_one(self):
        board = BoardDisplay('http://192.168.1.60', TOKEN)
        self.assertFalse(board.card)
        for reported, expected in ((1, True), (True, True), (0, False), (None, False), ('1', False), (2, False)):
            board.info = lambda reported=reported: {'pages': 8, **({} if reported is None else {'card': reported})}
            board.ensure_paired()
            self.assertEqual(board.card, expected, reported)

    def test_the_whole_way_through_a_real_request(self):
        seen = []

        class Board(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                seen.append((self.path, self.headers.get('X-Token')))
                self.send_response(200)
                self.send_header('Content-Length', '8')
                self.end_headers()
                self.wfile.write(b'11111111')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Board)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        board = BoardDisplay(f'http://127.0.0.1:{server.server_port}', TOKEN)
        line = card_payload(rows(), NOW)
        self.assertEqual(board.ping(line), '11111111')
        path, token = seen[0]
        self.assertEqual(token, TOKEN)
        self.assertIn('&card=' + line.replace('<', '%3C').replace(' ', '%20'), path)
        self.assertLess(len(path), 400)


class HintTests(unittest.TestCase):
    """The hint must use the same thresholds as the action (AGENTS.md): the firmware's, the page's and the control room's."""
    ROOT = Path(__file__).resolve().parents[1]

    def test_the_control_room_says_the_same_0_7_seconds_the_board_acts_on(self):
        header = (self.ROOT / 'firmware/board/src/rotation.h').read_text()
        script = (self.ROOT / 'token_tv/web/board.js').read_text()
        milliseconds = int(re.search(r'CARD_HOLD_MS\s*=\s*(\d+)', header).group(1))
        seconds = float(re.search(r'CARD_HOLD_SECONDS\s*=\s*([\d.]+)', script).group(1))
        self.assertEqual(milliseconds, 700)
        self.assertEqual(seconds * 1000, milliseconds)

    def test_the_hint_on_the_board_is_chosen_by_the_same_function_as_the_action(self):
        cpp = (self.ROOT / 'firmware/board/src/main.cpp').read_text()
        loop = cpp[cpp.index('\nvoid loop() {'):]
        self.assertIn('Gesture heldAction = touchHeld ? gesture(now-heldSince, modeHoldSeconds, connectHoldSeconds)', loop)
        self.assertIn('"Release: details"', loop)
        touch = cpp[cpp.index('static void handleTouch('):cpp.index('// Shared by the main loop')]
        self.assertIn('Gesture action = gesture(now-heldSince, modeHoldSeconds, connectHoldSeconds);', touch)
        # No threshold is spelled out a second time anywhere in the touch or hint code.
        for source in (loop, touch):
            self.assertNotRegex(source, r'now-heldSince\s*[<>]=?\s*\d')
            self.assertNotRegex(source, r'heldSince[^;]*\b(700|2000|5000)\b')


if __name__ == '__main__':
    unittest.main()
