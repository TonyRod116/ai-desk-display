"""The monitor looks for a board whose address moved, carefully, with fakes (Tony, 2026-11-03)."""
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from token_tv import board as board_module
from token_tv.board import (FIND_AFTER_SECONDS, FIND_EVERY_SECONDS, FIND_LOG, FIND_WORKERS, BoardDisplay, BoardLocator,
                            find_boards, save_board_config, subnet_hosts)
from token_tv.local_usage import LocalPolicy

TOKEN = '0123456789abcdef'
OLD = 'http://192.168.1.60'


class World:
    """What answers on the network: url -> (model, token the device accepts)."""
    def __init__(self, devices=None):
        self.devices = dict(devices or {})
        self.finds = []
        self.pings = []
        self.policy = None
        self.windows = []   # what the network guard allowed at the moment of each scan probe and each token call

    def make(self, url, token):
        world = self

        class Candidate:
            def info(self):
                if url not in world.devices:
                    raise OSError('no route')
                return {'model': world.devices[url][0], 'paired': True}

            def ping(self):
                world.windows.append(world.policy.scan if world.policy else None)
                world.pings.append((url, token))
                if url not in world.devices:
                    raise OSError('no route')
                if world.devices[url][1] != token:
                    raise HTTPError(url, 401, 'token', {}, None)
                return '11111111'
        return Candidate()

    def find(self, hosts, port=80, timeout=0.8, workers=64):
        self.windows.append(self.policy.scan if self.policy else None)
        self.finds.append({'hosts': list(hosts), 'port': port, 'timeout': timeout, 'workers': workers})
        return [h for h in hosts if f'http://{h}' + (f':{port}' if port != 80 else '') in self.devices
                and self.devices[f'http://{h}' + (f':{port}' if port != 80 else '')][0] == 'tokentv-board']


class FakeBoard:
    def __init__(self, url=OLD):
        self.base_url, self.token, self.moves = url, TOKEN, []

    def set_address(self, url):
        self.base_url = url
        self.moves.append(url)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class LocatorTests(unittest.TestCase):
    def locator(self, devices=None, url=OLD, **options):
        self.world = World(devices)
        self.clock = Clock()
        self.logs, self.saved = [], []
        self.board = FakeBoard(url)
        return BoardLocator(self.board, lambda new, token: self.saved.append((new, token)), options.pop('policy', None),
                            log=self.logs.append, clock=self.clock, find=self.world.find, make=self.world.make, **options)

    def go_silent(self, locator, seconds):
        locator.failed()
        self.clock.now += seconds

    def test_it_waits_ten_minutes_of_silence_and_looks_at_most_once_an_hour(self):
        locator = self.locator()
        self.assertEqual((FIND_AFTER_SECONDS, FIND_EVERY_SECONDS), (600, 3600))
        locator.failed()
        for second in (0, 1, 300, 599):
            self.clock.now = 1000 + second
            self.assertIsNone(locator.search())
            self.assertEqual(self.world.finds, [], second)                 # nothing is scanned before ten minutes
        self.clock.now = 1000 + 600
        locator.failed()                                                    # more failed passes do not restart the clock
        self.assertIsNone(locator.search())
        self.assertEqual(len(self.world.finds), 1)
        self.assertEqual(self.logs, [FIND_LOG['search'], FIND_LOG['none']])
        for second in (601, 1200, 4199):                                    # not again for an hour, however many passes fail
            self.clock.now = 1000 + second
            locator.failed()
            locator.search()
            self.assertEqual(len(self.world.finds), 1, second)
        self.clock.now = 1000 + 600 + 3600
        locator.search()
        self.assertEqual(len(self.world.finds), 2)

    def test_a_pass_that_reaches_the_board_resets_the_ten_minutes(self):
        locator = self.locator()
        locator.failed()
        self.clock.now += 500
        locator.reached()
        self.clock.now += 500
        locator.failed()
        self.clock.now += 599
        locator.search()
        self.assertEqual(self.world.finds, [])
        self.clock.now += 1
        locator.search()
        self.assertEqual(len(self.world.finds), 1)

    def test_it_looks_only_at_the_saved_addresss_own_24_with_a_few_workers(self):
        locator = self.locator()
        self.go_silent(locator, 601)
        locator.search()
        call = self.world.finds[0]
        self.assertEqual(len(call['hosts']), 254)
        self.assertTrue(all(h.startswith('192.168.1.') for h in call['hosts']))
        self.assertEqual((call['port'], call['workers'], call['timeout'] <= 1), (80, FIND_WORKERS, True))
        self.assertLessEqual(FIND_WORKERS, 8)
        other_port = self.locator(url='http://10.20.30.40:8080')
        self.go_silent(other_port, 601)
        other_port.search()
        self.assertTrue(all(h.startswith('10.20.30.') for h in self.world.finds[0]['hosts']))
        self.assertEqual(self.world.finds[0]['port'], 8080)

    def test_a_board_that_reports_the_model_and_takes_the_saved_token_is_followed_and_saved(self):
        policy = LocalPolicy('http://192.168.1.50', OLD)
        locator = self.locator({'http://192.168.1.74': ('tokentv-board', TOKEN)}, policy=policy)
        self.world.policy = policy
        self.go_silent(locator, 601)
        self.assertEqual(locator.search(), 'http://192.168.1.74')
        for window in self.world.windows:                                   # the guard was open, for this /24 and port, for the scan and the call
            self.assertEqual((str(window[0]), window[1]), ('192.168.1.0/24', 80))
        self.assertEqual(len(self.world.windows), 2)
        self.assertEqual(self.saved, [('http://192.168.1.74', TOKEN)])      # through the same saver `--find` uses
        self.assertEqual(self.board.moves, ['http://192.168.1.74'])
        self.assertTrue(policy.allowed_host('192.168.1.74', 80))            # the guard follows it ...
        self.assertFalse(policy.allowed_host('192.168.1.60', 80))           # ... and forgets the old address
        self.assertTrue(policy.allowed_host('192.168.1.50', 80))            # the clock is untouched
        self.assertIsNone(policy.scan)                                      # and the search window has closed
        self.assertIsNone(locator.unreachable_since)
        self.assertEqual(self.logs, [FIND_LOG['search'], FIND_LOG['found']])
        for line in self.logs:                                              # fixed words only
            self.assertNotIn(TOKEN, line)
            self.assertNotIn('192.168', line)

    def test_a_device_with_the_model_name_that_refuses_the_token_is_never_accepted(self):
        locator = self.locator({'http://192.168.1.74': ('tokentv-board', 'f' * 16)})
        self.go_silent(locator, 601)
        self.assertIsNone(locator.search())
        self.assertEqual(self.saved, [])
        self.assertEqual(self.board.moves, [])
        self.assertEqual(self.logs[-1], FIND_LOG['none'])
        self.assertEqual(self.world.pings, [('http://192.168.1.74', TOKEN)])  # the one harmless authenticated call
        other = self.locator({'http://192.168.1.75': ('something-else', TOKEN)})   # a device that is not a board is never even asked
        self.go_silent(other, 601)
        self.assertIsNone(other.search())
        self.assertEqual(self.world.pings, [])

    def test_two_boards_that_accept_the_token_change_nothing(self):
        locator = self.locator({'http://192.168.1.74': ('tokentv-board', TOKEN), 'http://192.168.1.75': ('tokentv-board', TOKEN)})
        self.go_silent(locator, 601)
        self.assertIsNone(locator.search())
        self.assertEqual((self.saved, self.board.moves), ([], []))
        self.assertEqual(self.logs[-1], FIND_LOG['several'])

    def test_a_board_still_at_its_saved_address_has_not_moved_so_nothing_is_scanned(self):
        locator = self.locator({OLD: ('tokentv-board', TOKEN)})            # slow or busy, but there
        self.go_silent(locator, 601)
        self.assertIsNone(locator.search())
        self.assertEqual(self.world.finds, [])
        self.assertEqual(self.logs, [])
        self.assertIsNone(locator.unreachable_since)

    def test_an_answer_from_outside_the_subnet_is_ignored(self):
        locator = self.locator({'http://192.168.2.9': ('tokentv-board', TOKEN)})
        locator.find = lambda hosts, **kw: ['192.168.2.9']
        self.go_silent(locator, 601)
        self.assertIsNone(locator.search())
        self.assertEqual(self.world.pings, [])

    def test_a_crowd_of_boards_is_not_called_one_by_one(self):
        crowd = {f'http://192.168.1.{n}': ('tokentv-board', TOKEN) for n in range(100, 110)}
        locator = self.locator(crowd)
        self.go_silent(locator, 601)
        self.assertIsNone(locator.search())
        self.assertEqual(len(self.world.pings), 4)                          # a few at most: ten boards in one house is a puzzle, not a find
        self.assertEqual(self.logs[-1], FIND_LOG['several'])

    def test_a_failed_save_still_follows_the_board_and_says_so_in_fixed_words(self):
        locator = self.locator({'http://192.168.1.74': ('tokentv-board', TOKEN)})
        locator.save = lambda url, token: (_ for _ in ()).throw(OSError('disk full'))
        self.go_silent(locator, 601)
        self.assertEqual(locator.search(), 'http://192.168.1.74')
        self.assertEqual(self.board.moves, ['http://192.168.1.74'])
        self.assertEqual(self.logs[-1], FIND_LOG['unsaved'])

    def test_nothing_that_goes_wrong_escapes_the_monitors_loop(self):
        locator = self.locator()
        locator.find = lambda *a, **k: (_ for _ in ()).throw(PermissionError('blocked'))
        self.go_silent(locator, 601)
        self.assertIsNone(locator.search())
        self.assertEqual(self.logs[-1], FIND_LOG['error'])
        self.assertEqual(self.saved, [])

    def test_every_log_line_is_fixed_words(self):
        for line in FIND_LOG.values():
            self.assertNotRegex(line, r'\d')
            self.assertNotIn('token:', line.lower())


class PolicyTests(unittest.TestCase):
    def test_the_search_window_allows_one_24_on_one_port_and_only_while_open(self):
        policy = LocalPolicy('http://192.168.1.50', OLD)
        self.assertFalse(policy.allowed_host('192.168.1.99', 80))
        with policy.scanning('192.168.1.60', 80):
            for host, port, allowed in (('192.168.1.1', 80, True), ('192.168.1.254', 80, True), ('192.168.1.99', None, True),
                                        ('192.168.2.1', 80, False), ('192.168.1.99', 8080, False), ('8.8.8.8', 80, False),
                                        ('example.com', 80, False), ('10.0.0.1', 80, False)):
                with self.subTest(host=host, port=port):
                    self.assertEqual(policy.allowed_host(host, port), allowed)
            policy.audit('socket.connect', (None, ('192.168.1.7', 80)))                 # allowed inside
            with self.assertRaises(PermissionError):
                policy.audit('socket.connect', (None, ('192.168.2.7', 80)))
            policy.audit('socket.getaddrinfo', ('192.168.1.7', 80, 0, 1))
        with self.assertRaises(PermissionError):                                          # closed again
            policy.audit('socket.connect', (None, ('192.168.1.7', 80)))
        with self.assertRaises(ValueError):
            policy.scanning('8.8.8.8', 80)
        with self.assertRaises(ValueError):
            policy.scanning('::1', 80)

    def test_a_window_that_ends_with_an_error_still_closes(self):
        policy = LocalPolicy(None, OLD)
        with self.assertRaises(RuntimeError):
            with policy.scanning('192.168.1.60'):
                raise RuntimeError('boom')
        self.assertIsNone(policy.scan)

    def test_following_the_board_replaces_only_its_own_entry(self):
        policy = LocalPolicy('http://192.168.1.50', OLD)
        policy.set_board_url('http://192.168.1.74:8080')
        self.assertTrue(policy.allowed_host('192.168.1.74', 8080))
        self.assertFalse(policy.allowed_host('192.168.1.74', 80))
        self.assertFalse(policy.allowed_host('192.168.1.60', 80))
        self.assertTrue(policy.allowed_host('192.168.1.50', 80))
        for bad in ('http://8.8.8.8', 'https://192.168.1.74', 'http://0.0.0.0'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                policy.set_board_url(bad)
        self.assertTrue(policy.allowed_host('192.168.1.74', 8080))                       # a refused address changes nothing
        solo = LocalPolicy(None, OLD)                                                     # a board without a clock
        solo.set_board_url('http://192.168.1.75')
        self.assertEqual([(str(a), p) for a, p in solo.endpoints], [('192.168.1.75', 80)])


class Fake(BaseHTTPRequestHandler):
    """A board on loopback: /info says what it is, /ping wants the token."""
    token = TOKEN

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({'model': 'tokentv-board', 'fw': 'ai-desk-display 42', 'paired': True}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        ok = self.headers.get('X-Token') == self.token
        body = b'11111111' if ok else b'token'
        self.send_response(200 if ok else 401)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RealPartsTests(unittest.TestCase):
    def test_the_whole_search_with_the_real_client_a_real_server_and_the_real_saver(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fake)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        port = server.server_port
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({
                'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source_home': '/tmp/demo'}],
                'local_only': True, 'display_style': 'orbit',
                'board_display': {'url': f'http://127.0.0.2:{port}', 'token': TOKEN}}))
            os.chmod(path, 0o644)
            board = BoardDisplay(f'http://127.0.0.2:{port}', TOKEN)       # the board "moved" from .2 to .1 (both loopback)
            clock, logs = Clock(), []
            locator = BoardLocator(board, lambda url, token: save_board_config(path, url, token), log=logs.append, clock=clock)
            locator.failed()
            clock.now += 601
            with patch.object(board_module, 'subnet_hosts', side_effect=lambda a: ['127.0.0.1', '127.0.0.2', '127.0.0.3']):
                self.assertEqual(locator.search(), f'http://127.0.0.1:{port}')
            self.assertEqual(board.base_url, f'http://127.0.0.1:{port}')
            saved = json.loads(path.read_text())
            self.assertEqual(saved['board_display'], {'url': f'http://127.0.0.1:{port}', 'token': TOKEN})
            self.assertEqual(saved['display_style'], 'orbit')                # everything else is kept
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(logs, [FIND_LOG['search'], FIND_LOG['found']])
            self.assertFalse(any(TOKEN in line for line in logs))
            Fake.token = 'f' * 16                                            # the same board refusing our token is not accepted
            try:
                again = BoardDisplay(f'http://127.0.0.2:{port}', TOKEN)
                second = BoardLocator(again, lambda url, token: self.fail('must not save'), log=logs.append, clock=clock)
                second.failed()
                clock.now += 601
                with patch.object(board_module, 'subnet_hosts', side_effect=lambda a: ['127.0.0.1']):
                    self.assertIsNone(second.search())
                self.assertEqual(again.base_url, f'http://127.0.0.2:{port}')
            finally:
                Fake.token = TOKEN

    def test_the_cli_and_the_monitor_share_one_saver_and_one_scanner(self):
        from token_tv import cli
        calls = []
        with patch.object(board_module, 'save_board_config', side_effect=lambda *a: calls.append(a)):
            cli._save_board('x.json', 'http://192.168.1.74', TOKEN)
        self.assertEqual(calls, [('x.json', 'http://192.168.1.74', TOKEN)])
        # `--find` keeps its own wide, fast scan; the monitor's is slow on purpose.
        with patch.object(board_module, 'ThreadPoolExecutor') as pool:
            pool.return_value.__enter__.return_value.map.return_value = []
            find_boards(['192.168.1.1'], workers=3)
            find_boards(['192.168.1.1'])
        self.assertEqual([c.kwargs['max_workers'] for c in pool.call_args_list], [3, 64])
        self.assertEqual(len(subnet_hosts('192.168.1.60')), 254)

    def test_a_config_that_would_not_validate_is_never_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            original = json.dumps({'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude',
                                                 'source_home': '/tmp/demo'}], 'local_only': True})
            path.write_text(original)
            with self.assertRaises(ValueError):
                save_board_config(path, 'http://8.8.8.8', TOKEN)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(sorted(os.listdir(directory)), ['config.json'])    # no temporary file left


if __name__ == '__main__':
    unittest.main()
