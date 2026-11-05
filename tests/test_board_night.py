"""Night mode: the schedule lives on the PC, the board is told only when the level changes."""
from datetime import datetime
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from token_tv.board import BoardDisplay
from token_tv.board_control import NIGHT_DEFAULT, BoardControl, NightMode, apply_night, night_settings
from token_tv.live import handler
from token_tv.state import UsageStore

TOKEN = '0123456789abcdef'


def at(hour, minute=0):
    return datetime(2026, 11, 3, hour, minute)


class NightScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state' / 'board-night.json'

    def test_the_default_is_on_from_23_to_0730_at_25_percent(self):
        night = NightMode(self.path)
        self.assertEqual(night.settings(), {'enabled': True, 'start': '23:00', 'end': '07:30', 'level': 25})
        self.assertEqual(night.settings(), NIGHT_DEFAULT)
        for moment, level in ((at(12), 100), (at(22, 59), 100), (at(23, 0), 25), (at(23, 59), 25), (at(0, 0), 25),
                              (at(3, 30), 25), (at(7, 29), 25), (at(7, 30), 100), (at(7, 31), 100), (at(18), 100)):
            with self.subTest(moment=moment.strftime('%H:%M')):
                self.assertEqual(night.level_at(moment), level)

    def test_windows_within_one_day_and_empty_or_disabled_ones(self):
        night = NightMode(self.path)
        night.update({'enabled': True, 'start': '13:00', 'end': '15:30', 'level': 40})
        for moment, level in ((at(12, 59), 100), (at(13), 40), (at(15, 29), 40), (at(15, 30), 100), (at(23, 30), 100)):
            with self.subTest(moment=moment.strftime('%H:%M')):
                self.assertEqual(night.level_at(moment), level)
        night.update({'enabled': True, 'start': '08:00', 'end': '08:00', 'level': 40})      # an empty window is never night
        self.assertEqual({night.level_at(at(h)) for h in range(24)}, {100})
        night.update({'enabled': False, 'start': '23:00', 'end': '07:30', 'level': 25})     # off means full light
        self.assertEqual({night.level_at(at(h)) for h in range(24)}, {100})

    def test_only_a_complete_valid_setting_is_accepted(self):
        good = {'enabled': True, 'start': '22:15', 'end': '06:45', 'level': 10}
        self.assertEqual(night_settings(good), good)
        bad = [None, [], 'on', {}, {**good, 'extra': 1}, {k: v for k, v in good.items() if k != 'end'},
               {**good, 'enabled': 1}, {**good, 'enabled': 'true'}, {**good, 'level': 0}, {**good, 'level': 4},
               {**good, 'level': 101}, {**good, 'level': True}, {**good, 'level': '25'}, {**good, 'level': 25.0},
               {**good, 'start': '24:00'}, {**good, 'start': '7:30'}, {**good, 'start': '07:60'}, {**good, 'end': '07:30\n'},
               {**good, 'end': 730}, {**good, 'end': None}, {**good, 'start': '07-30'}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                night_settings(value)

    def test_it_is_kept_privately_and_survives_a_restart(self):
        changed = threading.Event()
        night = NightMode(self.path, changed)
        self.assertFalse(self.path.exists())                           # defaults need no file
        night.update({'enabled': False, 'start': '22:00', 'end': '06:00', 'level': 15})
        self.assertTrue(changed.is_set())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(sorted(os.listdir(self.path.parent)), ['board-night.json'])   # no temporary file left behind
        self.assertEqual(NightMode(self.path).settings(), {'enabled': False, 'start': '22:00', 'end': '06:00', 'level': 15})
        changed.clear()
        before = self.path.stat().st_mtime_ns
        night.update(night.settings())                                  # the same setting again: no write, no wake-up
        self.assertFalse(changed.is_set())
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_a_damaged_file_means_the_defaults_and_a_bad_update_changes_nothing(self):
        self.path.parent.mkdir(parents=True)
        for content in ('not json', '[]', '{"enabled":true}', '{"enabled":true,"start":"99:99","end":"07:30","level":25}',
                        'x' * 5000):
            self.path.write_text(content)
            with self.subTest(content=content[:20]):
                self.assertEqual(NightMode(self.path).settings(), NIGHT_DEFAULT)
        night = NightMode(self.path)
        night.update({'enabled': True, 'start': '21:00', 'end': '05:00', 'level': 30})
        saved = self.path.read_text()
        with self.assertRaises(ValueError):
            night.update({'enabled': True, 'start': '21:00', 'end': '05:00', 'level': 0})
        self.assertEqual(self.path.read_text(), saved)
        self.assertEqual(night.settings()['level'], 30)


class FakeLamp:
    """A board that says what it reports and records what it is told."""
    def __init__(self, brightness=1, bright=100):
        self.brightness = bool(brightness)
        self.last_info = {'brightness': brightness, 'bright': bright} if brightness else {}
        self.sent = []

    def configure(self, bright=None, **others):
        assert not others
        self.sent.append(bright)
        self.last_info['bright'] = bright


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.night = NightMode(Path(self.directory.name) / 'night.json')

    def test_it_sends_only_when_the_board_says_otherwise(self):
        lamp = FakeLamp(bright=100)
        self.assertIsNone(apply_night(lamp, self.night, at(12)))
        self.assertEqual(lamp.sent, [])
        self.assertEqual(apply_night(lamp, self.night, at(23, 0)), 25)
        self.assertIsNone(apply_night(lamp, self.night, at(23, 1)))     # the board now says 25: nothing more is sent
        self.assertEqual(apply_night(lamp, self.night, at(7, 30)), 100)
        self.assertEqual(lamp.sent, [25, 100])

    def test_a_reboot_or_a_restart_of_the_monitor_needs_no_memory_of_what_was_sent(self):
        lamp = FakeLamp(bright=25)                   # the board kept its night level through a power cut ...
        self.assertEqual(apply_night(lamp, self.night, at(9)), 100)   # ... and it is morning: the monitor corrects it
        lamp = FakeLamp(bright=100)
        lamp.last_info.pop('bright')                 # a board that does not say: it is told once
        self.assertEqual(apply_night(lamp, self.night, at(12)), 100)

    def test_boards_without_the_capability_are_never_sent_anything(self):
        lamp = FakeLamp(brightness=0)
        self.assertIsNone(apply_night(lamp, self.night, at(23, 30)))
        self.assertEqual(lamp.sent, [])
        self.assertIsNone(apply_night(lamp, None, at(23, 30)))

    def test_the_real_board_client_validates_and_the_capability_comes_from_info(self):
        board = BoardDisplay('http://192.168.1.2', TOKEN)
        calls = []
        board.request = lambda path, **kwargs: (calls.append(path) or (200, b'OK'))
        board.configure(bright=25)
        board.configure(bright=0)
        board.configure(bright=100, cycle=30)
        self.assertEqual(calls, ['/config?bright=25', '/config?bright=0', '/config?cycle=30&bright=100'])
        for value in (True, -1, 101, '25', 2.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                board.configure(bright=value)
        with self.assertRaises(ValueError):                                     # nothing to change is not a request
            board.configure()
        self.assertEqual(calls[-1], '/config?cycle=30&bright=100')          # nothing invalid was sent
        board.info = lambda: {'pages': 8, 'brightness': 1}
        board.ensure_paired()
        self.assertTrue(board.brightness)
        for reported in (0, None, '1', 2):
            board.info = lambda reported=reported: {'pages': 8, **({} if reported is None else {'brightness': reported})}
            board.ensure_paired()
            self.assertFalse(board.brightness, reported)


class FakeBoardInfo:
    def __init__(self, info):
        self.lock = threading.RLock()
        self.last_info = info
        self.last_seen = 0

    def info(self):
        import time
        self.last_seen = time.monotonic()
        return dict(self.last_info)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.changed = threading.Event()
        self.night = NightMode(Path(self.directory.name) / 'night.json', self.changed)

    def test_the_control_room_saves_the_schedule_without_touching_the_board(self):
        board = FakeBoardInfo({'page': 1, 'board_controls': 1, 'brightness': 1, 'bright': 100})
        control = BoardControl(board, night=self.night)
        status = control.execute('night', {'enabled': True, 'start': '22:00', 'end': '07:00', 'level': 20})
        self.assertEqual(status['night'], {'enabled': True, 'start': '22:00', 'end': '07:00', 'level': 20})
        self.assertTrue(status['night_supported'])
        self.assertTrue(self.changed.is_set())                      # the monitor applies it on its next pass
        self.assertEqual(NightMode(self.night.path).settings()['level'], 20)
        for bad in ({'enabled': True}, {'enabled': 'yes', 'start': '22:00', 'end': '07:00', 'level': 20}, 'off', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                control.execute('night', bad)
        self.assertEqual(control.night.settings()['level'], 20)

    def test_the_status_says_whether_the_display_follows_and_hides_what_it_cannot_do(self):
        old = BoardControl(FakeBoardInfo({'page': 1, 'board_controls': 1}), night=self.night)
        self.assertFalse(old.status(refresh=False)['night_supported'])      # firmware 41: the control room hides the control
        board = FakeBoardInfo({'page': 1, 'board_controls': 1, 'brightness': 1, 'bright': 100})
        control = BoardControl(board, night=self.night)
        wanted = self.night.level_at()
        board.last_info['bright'] = wanted
        self.assertTrue(control.status(refresh=False)['night_applied'])
        board.last_info['bright'] = wanted + 1 if wanted < 100 else 50
        self.assertFalse(control.status(refresh=False)['night_applied'])
        self.assertNotIn('night', BoardControl(board).status(refresh=False))   # without a schedule object there is nothing to show
        with self.assertRaises(ValueError):
            BoardControl(board).execute('night', NIGHT_DEFAULT)

    def test_an_offline_board_keeps_its_capability_but_is_not_called_applied(self):
        board = FakeBoardInfo({'page': 1, 'board_controls': 1, 'brightness': 1, 'bright': self.night.level_at()})
        board.info = lambda: (_ for _ in ()).throw(OSError('offline'))
        board.last_seen = -1000
        status = BoardControl(board, night=self.night).status()
        self.assertEqual(status['state'], 'offline')
        self.assertTrue(status['night_supported'])


class NightHttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        night = NightMode(Path(self.directory.name) / 'night.json')
        board = FakeBoardInfo({'page': 1, 'board_controls': 1, 'brightness': 1, 'bright': 100})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(UsageStore([]), board_control=BoardControl(board, night=night)))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.root = f'http://127.0.0.1:{self.server.server_port}'
        self.night = night

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, data, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        return urlopen(Request(self.root + '/board/night', json.dumps(data).encode(), headers))

    def test_the_route_is_local_validated_and_reports_the_schedule(self):
        value = {'enabled': True, 'start': '21:30', 'end': '06:30', 'level': 35}
        with self.post({'value': value}, self.root) as response:
            self.assertEqual(json.load(response)['night'], value)
        with urlopen(self.root + '/board/status') as response:
            status = json.load(response)
        self.assertEqual(status['night'], value)
        self.assertTrue(status['night_supported'])
        for data, origin, code in (({'value': value}, 'https://attacker.example', 403),
                                   ({'value': {**value, 'level': 0}}, self.root, 400),
                                   ({'value': value, 'extra': 1}, self.root, 400),
                                   ({'value': 'off'}, self.root, 400)):
            with self.subTest(data=data), self.assertRaises(HTTPError) as caught:
                self.post(data, origin)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.night.settings(), value)


if __name__ == '__main__':
    unittest.main()
