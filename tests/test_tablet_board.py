"""The tablet's remote for the small screen: what it sends, what it refuses and what it makes of the answers.

Nothing here touches the real monitor (port 8787), the tablet service (8666/8667) or the board. The remote only ever talks to a
stand-in control room on a port the system picks, or to the real control-room routes over a pretend board; a guard around
`socket.connect` fails any test that tries one of the real ports.
"""
import copy
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from token_tv import tablet_board
from token_tv.board_control import BoardControl, NightMode, night_settings
from token_tv.tablet_board import BoardRemote, clean_status, clean_value

FORBIDDEN_PORTS = (8787, 8666, 8667)
_guard = None

DEFAULT_SCENES = ('game-boy', 'paradise', 'code-forge', 'surf', 'dials', 'arcade', 'cockpit', 'countdown')
SCENE_NAMES = {'game-boy': 'Game Boy', 'paradise': 'Paradise', 'code-forge': 'Neon City', 'surf': 'Tidal Rush', 'dials': 'Token Run',
               'arcade': 'Versus', 'cockpit': 'Platform', 'countdown': 'City', 'versus-train': 'Versus \N{MIDDLE DOT} Night Train'}
NIGHT = {'enabled': True, 'start': '23:00', 'end': '07:30', 'level': 25}
# "07:30" written with the digits of another script: the control room's \d accepts it, the remote does not.
ARABIC_TIME = '0\N{ARABIC-INDIC DIGIT SEVEN}:3\N{ARABIC-INDIC DIGIT ZERO}'
SHAPE ={'state', 'page', 'controls', 'rotation', 'speed', 'night', 'firmware', 'slots'}
SECRET = 'SECRET-0123456789abcdef'     # planted in every error body: it must never come back out


def setUpModule():
    global _guard

    def refuse_real_services(sock, address, *rest):
        if isinstance(address, tuple) and len(address) > 1 and address[1] in FORBIDDEN_PORTS:
            raise AssertionError(f'a test tried to connect to port {address[1]}, which belongs to a real service')
        return real_connect(sock, address, *rest)

    real_connect = socket.socket.connect
    _guard = mock.patch.object(socket.socket, 'connect', refuse_real_services)
    _guard.start()


def tearDownModule():
    _guard.stop()


def connected_status(**changes):
    """What the control room's /board/status says for a healthy board with the eight default screens confirmed."""
    status = {'state': 'connected', 'page': 1, 'showing_connection': False, 'rotation_minutes': 30, 'speed_percent': 100,
              'per_screen_speed': True, 'touch_controls': True, 'card_supported': True, 'mode_hold_seconds': 2,
              'connect_hold_seconds': 5, 'controls': True, 'clock_synced': True,
              'scene_ids': list(DEFAULT_SCENES), 'scene_delivered_ids': list(DEFAULT_SCENES), 'scene_pending': [False] * 8,
              'scene_catalog': [{'id': key, 'name': name, 'archived': False} for key, name in SCENE_NAMES.items()],
              'scene_settings_error': False, 'night': dict(NIGHT), 'night_supported': True, 'night_applied': True}
    status.update(changes)
    return status


def expected_status(**changes):
    """What the remote makes of `connected_status()`."""
    status = {'state': 'ok', 'page': 1, 'controls': True, 'rotation': 30, 'speed': 100, 'night': dict(NIGHT), 'firmware': None,
              'slots': [{'index': index, 'name': SCENE_NAMES[scene]} for index, scene in enumerate(DEFAULT_SCENES)]}
    status.update(changes)
    return status


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StandIn:
    """A stand-in for the monitor's control room. It records every request and, unless a test's `hook` answers first, serves
    GET /board/status and POST /board/page|rotation|speed|night the way token_tv/live.py does (same Host, Origin, size, type and
    shape checks, same HTML error pages), keeping the state in `self.status`."""

    def __init__(self):
        self.lock = threading.Lock()
        self.requests = []                 # {'method', 'path', 'headers': [(name, value)], 'body': bytes}
        self.active = 0
        self.max_active = 0
        self.release = threading.Event()   # set at teardown: wakes every handler that holds a request on purpose
        self.hook = None                   # function(handler, record) -> True when it answered by itself
        self.status = connected_status()
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def log_message(self, *args):
                pass

            def do_GET(self):
                stand_in.serve(self, b'')

            def do_POST(self):
                stand_in.serve(self, self.rfile.read(int(self.headers.get('Content-Length') or 0)))

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.handle_error = lambda request, client: None      # a client that gave up is not the stand-in's fault
        self.port = self.server.server_port
        self.base = f'http://127.0.0.1:{self.port}'
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def sent(self, method=None):
        with self.lock:
            return [record for record in self.requests if method in (None, record['method'])]

    def serve(self, handler, body):
        record = {'method': handler.command, 'path': handler.path,
                  'headers': [(name, value) for name, value in handler.headers.items()], 'body': body}
        with self.lock:
            self.requests.append(record)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.hook is None or not self.hook(handler, record):
                self.answer(handler, record)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with self.lock:
                self.active -= 1

    def reply(self, handler, code, body=b'', content_type='application/json; charset=utf-8', extra=()):
        handler.send_response(code)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Length', str(len(body)))
        for name, value in extra:
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(body)

    def refuse(self, handler, code):
        self.reply(handler, code, f'<html><body>Invalid display control {SECRET}\nTraceback (most recent call last)</body></html>'.encode(),
                   'text/html;charset=utf-8')

    def answer(self, handler, record):
        headers = {name.lower(): value for name, value in record['headers']}
        host = urlparse('http://' + headers.get('host', ''))
        if host.hostname != '127.0.0.1' or host.port != self.port:
            return self.refuse(handler, 403)
        if record['method'] == 'GET':
            if record['path'] == '/board/status':
                return self.reply(handler, 200, json.dumps(self.status).encode())
            return self.refuse(handler, 404)
        command = record['path'].rsplit('/', 1)[-1]
        if record['path'] != '/board/' + command or command not in ('page', 'rotation', 'speed', 'night'):
            return self.refuse(handler, 404)
        origin = headers.get('origin')
        if origin and urlparse(origin).netloc != headers.get('host'):
            return self.refuse(handler, 403)
        try:
            length = int(headers.get('content-length', '0'))
            if not 0 < length <= 1024 or headers.get('content-type', '').split(';')[0] != 'application/json':
                raise ValueError('Invalid JSON request')
            data = json.loads(record['body'])
            if not isinstance(data, dict) or set(data) != {'value'}:
                raise ValueError('Invalid display control')
            self.apply(command, data['value'])
        except ValueError:
            return self.refuse(handler, 400)
        self.reply(handler, 200, json.dumps(self.status).encode())

    def apply(self, command, value):
        if command == 'night':
            self.status['night'] = night_settings(value)
        elif type(value) is not int or value not in {'page': range(8), 'rotation': (0, 30, 60), 'speed': (75, 100, 125)}[command]:
            raise ValueError('Unsupported value')
        elif command == 'page':
            self.status['page'] = value
        else:
            self.status['rotation_minutes' if command == 'rotation' else 'speed_percent'] = value


class FakeBoard:
    """What BoardControl asks of a BoardDisplay, with the behaviour of a board, in memory (there is no network in it)."""

    def __init__(self, **info):
        self.lock = threading.RLock()
        self.state = {'page': 1, 'info': 0, 'rotation_minutes': 0, 'board_controls': 1, 'animation_speed': 100,
                      'per_screen_speed': True, 'animation_speeds': [100] * 8, 'touch_controls': 1, 'mode_hold_seconds': 2,
                      'connect_hold_seconds': 5, 'selection_memory': True, 'clock_synced': True, 'card': 1, 'brightness': 1,
                      'bright': 100}
        self.state.update(info)
        self.last_info = copy.deepcopy(self.state)
        self.last_seen = time.monotonic()
        self.calls = []
        self.offline = False

    def info(self):
        if self.offline:
            raise OSError('offline')
        self.last_info = copy.deepcopy(self.state)
        self.last_seen = time.monotonic()
        return copy.deepcopy(self.state)

    def show(self, number):
        self.calls.append(('show', number))
        self.state['page'] = number + 1

    def configure(self, cycle=None, speed=None, speed_page=None, **others):
        assert not others
        self.calls.append(('configure', cycle, speed, speed_page))
        if cycle is not None:
            self.state['rotation_minutes'] = cycle
        if speed is not None:
            page = self.state['page'] - 1 if speed_page is None else speed_page
            self.state['animation_speeds'][page] = speed
            if page == self.state['page'] - 1:
                self.state['animation_speed'] = speed


# What each command may be, in the control room's own words (board_control.execute, night_settings).
ACCEPTED = ([('page', n) for n in range(8)] + [('rotation', n) for n in (0, 30, 60)] + [('speed', n) for n in (75, 100, 125)]
            + [('night', {'enabled': enabled, 'start': start, 'end': end, 'level': level})
               for enabled in (True, False) for start, end in (('23:00', '07:30'), ('00:00', '23:59'), ('08:00', '08:00'))
               for level in (5, 25, 100)])
GOOD_NIGHT = {'enabled': True, 'start': '22:15', 'end': '06:45', 'level': 10}
REFUSED = (
    [('page', v) for v in (-1, 8, 9, 100, 2 ** 31, True, False, 1.0, 0.5, '1', '', None, [1], {}, (1,))]
    + [('rotation', v) for v in (-30, 1, 15, 29, 31, 45, 59, 61, 90, 120, True, False, 30.0, '30', '', None, [30])]
    + [('speed', v) for v in (0, 50, 74, 76, 99, 101, 124, 126, 150, 200, -100, True, False, 100.0, '100', '', None, [100],
                              {'percent': 100, 'page': 0}, {'percent': 125, 'page': 7}, {'percent': 100}, {'value': 100})]
    + [('night', v) for v in (None, [], 'on', 'off', 1, True, {}, {'enabled': True}, {**GOOD_NIGHT, 'extra': 1},
                              {k: v for k, v in GOOD_NIGHT.items() if k != 'end'}, {**GOOD_NIGHT, 'enabled': 1},
                              {**GOOD_NIGHT, 'enabled': 'true'}, {**GOOD_NIGHT, 'enabled': None}, {**GOOD_NIGHT, 'level': 0},
                              {**GOOD_NIGHT, 'level': 4}, {**GOOD_NIGHT, 'level': 101}, {**GOOD_NIGHT, 'level': -5},
                              {**GOOD_NIGHT, 'level': True}, {**GOOD_NIGHT, 'level': '25'}, {**GOOD_NIGHT, 'level': 25.0},
                              {**GOOD_NIGHT, 'start': '24:00'}, {**GOOD_NIGHT, 'start': '7:30'}, {**GOOD_NIGHT, 'start': '07:60'},
                              {**GOOD_NIGHT, 'end': '07:30\n'}, {**GOOD_NIGHT, 'end': ' 07:30'}, {**GOOD_NIGHT, 'end': 730},
                              {**GOOD_NIGHT, 'end': None}, {**GOOD_NIGHT, 'start': '07-30'}, {**GOOD_NIGHT, 'start': '0730'},
                              {**GOOD_NIGHT, 'start': ''}, {**GOOD_NIGHT, 'end': '7:3'},
                              {**GOOD_NIGHT, 'start': ARABIC_TIME})]
    + [(name, 1) for name in ('scene', 'order', 'touch', 'brightness', 'config', 'show', 'pages', 'PAGE', 'page ', ' page', '',
                              'night/', '../page')]
    + [(name, 1) for name in (None, 1, ['page'], ('page',), b'page', {'page': 1})])


class ValidationTests(unittest.TestCase):
    def test_every_allowed_value_passes_and_comes_back_as_a_fresh_copy(self):
        for name, value in ACCEPTED:
            with self.subTest(name=name, value=value):
                cleaned = clean_value(name, value)
                self.assertEqual(cleaned, value)
                if name == 'night':
                    self.assertIsNot(cleaned, value)
                    self.assertEqual(list(cleaned), ['enabled', 'start', 'end', 'level'])

    def test_everything_else_is_refused(self):
        for name, value in REFUSED:
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                clean_value(name, value)

    def test_the_other_routes_of_the_control_room_are_not_part_of_the_remote(self):
        self.assertEqual(tablet_board.COMMANDS, ('page', 'rotation', 'speed', 'night'))
        for name in ('scene', 'order', 'touch'):                                 # real routes of /board, deliberately left out
            with self.subTest(name=name), self.assertRaises(ValueError):
                clean_value(name, {'slot': 0, 'scene': 'surf'})

    def test_a_night_schedule_is_rebuilt_not_passed_through(self):
        class Sneaky(dict):
            pass
        source = Sneaky(GOOD_NIGHT)
        cleaned = clean_value('night', source)
        self.assertIs(type(cleaned), dict)
        source['level'] = 99
        self.assertEqual(cleaned['level'], 10)


class ParityWithTheControlRoomTests(unittest.TestCase):
    """The remote's rules are a copy of board_control.execute / night_settings. These run both on the same values, so a change
    to the control room's limits fails here instead of silently drifting."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.control = BoardControl(FakeBoard(), None, NightMode(Path(self.directory.name) / 'night.json'))

    def control_room_accepts(self, name, value):
        try:
            self.control.execute(name, value)
        except ValueError:
            return False
        except OSError:
            return True                      # it got past the value check and met the (pretend) board
        return True

    def remote_accepts(self, name, value):
        try:
            clean_value(name, value)
        except ValueError:
            return False
        return True

    def test_the_same_verdict_on_every_value_of_the_four_commands(self):
        # Where the remote is stricter on purpose: the per-page speed form it never sends, and digits of other scripts in a time.
        stricter = [('speed', {'percent': 100, 'page': 0}), ('speed', {'percent': 125, 'page': 7}),
                    ('night', {**GOOD_NIGHT, 'start': ARABIC_TIME})]
        for name, value in ACCEPTED + REFUSED:
            if name not in ('page', 'rotation', 'speed', 'night'):
                continue
            theirs, mine = self.control_room_accepts(name, value), self.remote_accepts(name, value)
            with self.subTest(name=name, value=value):
                if (name, value) in stricter:
                    self.assertTrue(theirs)
                    self.assertFalse(mine)
                else:
                    self.assertEqual(mine, theirs)

    def test_the_remote_is_never_looser_than_the_control_room(self):
        for name, value in ACCEPTED + REFUSED:
            if self.remote_accepts(name, value):
                with self.subTest(name=name, value=value):
                    self.assertTrue(self.control_room_accepts(name, value))

    def test_the_limits_are_the_control_rooms_limits(self):
        import token_tv.board as board
        import token_tv.board_control as control
        self.assertEqual(tablet_board.PAGES, board.PAGES)
        self.assertEqual(tablet_board.NIGHT_LEVELS, control.NIGHT_LEVEL_RANGE)
        self.assertEqual(tablet_board.ROTATIONS, (0, 30, 60))
        self.assertEqual(tablet_board.SPEEDS, (75, 100, 125))


class StatusShapeTests(unittest.TestCase):
    def test_a_healthy_board_in_the_fixed_shape(self):
        self.assertEqual(clean_status(connected_status()), expected_status())

    def test_the_states(self):
        cases = (('connected', 1, 'ok'), ('busy', 1, 'ok'), ('busy', None, 'unavailable'), ('busy', 8, 'unavailable'),
                 ('offline', None, 'offline'), ('offline', 3, 'offline'), ('not_configured', None, 'not_configured'),
                 ('connecting', 1, None), ('', 1, None), (None, 1, None), (['connected'], 1, None), ('CONNECTED', 1, None))
        for word, page, state in cases:
            with self.subTest(word=word, page=page):
                result = clean_status(connected_status(state=word, page=page))
                if state is None:
                    self.assertIsNone(result)
                else:
                    self.assertEqual(result['state'], state)
                    self.assertIn(result['state'], tablet_board.STATES)

    def test_anything_that_is_not_a_status_is_nothing(self):
        for raw in (None, [], 'ok', 3, [connected_status()], {}, {'page': 1}, {'state': None}):
            with self.subTest(raw=raw):
                self.assertIsNone(clean_status(raw))

    def test_what_belongs_to_the_board_is_unknown_when_the_board_is_not_there(self):
        for word in ('offline', 'not_configured'):
            result = clean_status(connected_status(state=word, firmware='44'))          # a leftover reading is no evidence
            with self.subTest(word=word):
                self.assertEqual((result['page'], result['controls'], result['rotation'], result['speed'], result['firmware']),
                                 (None, False, None, None, None))
                self.assertEqual(result['night'], NIGHT)                           # the schedule and the screens are the PC's own
                self.assertEqual(len(result['slots']), 8)

    def test_a_busy_monitor_keeps_the_last_known_board_facts(self):
        result = clean_status(connected_status(state='busy', page=4))
        self.assertEqual((result['state'], result['page'], result['controls'], result['rotation'], result['speed']),
                         ('ok', 4, True, 30, 100))

    def test_odd_values_become_unknown_never_something_else(self):
        for page in (None, -1, 8, 99, True, False, 1.0, 1.5, '1', [1], {}):
            with self.subTest(page=page):
                result = clean_status(connected_status(page=page))
                self.assertEqual(result['state'], 'ok')
                self.assertIsNone(result['page'])
        for key, field, values in (('rotation_minutes', 'rotation', (None, 15, 45, 90, -30, True, 30.0, '30', [30])),
                                   ('speed_percent', 'speed', (None, 0, 50, 90, 150, True, 100.0, '100', [100]))):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertIsNone(clean_status(connected_status(**{key: value}))[field])
        for value in (None, 1, 'true', 'yes', 0, [], {}):
            with self.subTest(controls=value):
                self.assertIs(clean_status(connected_status(controls=value))['controls'], False)

    def test_the_connection_screen_is_not_a_page(self):
        self.assertIsNone(clean_status(connected_status(page=2, showing_connection=True))['page'])
        self.assertEqual(clean_status(connected_status(page=2, showing_connection=False))['page'], 2)
        self.assertEqual(clean_status(connected_status(page=2, showing_connection='yes'))['page'], 2)   # only a true True counts
        self.assertEqual(clean_status(connected_status(state='busy', page=2, showing_connection=True))['state'], 'ok')

    def test_night_is_shown_only_where_the_control_room_shows_it(self):
        for supported in (False, None, 1, 'true', 0):
            with self.subTest(night_supported=supported):
                self.assertIsNone(clean_status(connected_status(night_supported=supported))['night'])
        self.assertIsNone(clean_status({k: v for k, v in connected_status().items() if k != 'night'})['night'])
        for bad in (None, {}, 'on', {**NIGHT, 'level': 0}, {**NIGHT, 'extra': 1}, {**NIGHT, 'start': '25:00'}):
            with self.subTest(night=bad):
                self.assertIsNone(clean_status(connected_status(night=bad))['night'])

    def test_slots_name_what_the_monitor_confirmed_on_the_board(self):
        delivered = list(DEFAULT_SCENES)
        delivered[2] = None                                             # not confirmed yet (CHECKING in the control room)
        delivered[3] = 'versus-train'
        delivered[4] = 'a-scene-nobody-lists'
        result = clean_status(connected_status(scene_delivered_ids=delivered))
        self.assertEqual([slot['name'] for slot in result['slots']],
                         ['Game Boy', 'Paradise', None, 'Versus - Night Train', None, 'Versus', 'Platform', 'City'])
        self.assertEqual([slot['index'] for slot in result['slots']], list(range(8)))
        self.assertEqual({tuple(slot) for slot in result['slots']}, {('index', 'name')})

    def test_slots_follow_what_is_confirmed_not_what_is_wanted(self):
        wanted = list(DEFAULT_SCENES)
        wanted[1] = 'versus-train'                                     # chosen in the control room, not on the board yet
        pending = [False, True] + [False] * 6
        result = clean_status(connected_status(scene_ids=wanted, scene_pending=pending))
        self.assertEqual(result['slots'][1]['name'], 'Paradise')

    def test_slots_are_unknown_when_nothing_is_confirmed_or_the_lists_are_wrong(self):
        for changes in ({'scene_delivered_ids': [None] * 8}, {'scene_delivered_ids': []}, {'scene_delivered_ids': None},
                        {'scene_delivered_ids': 'game-boy'}, {'scene_delivered_ids': [1, 2, 3]}, {'scene_catalog': []},
                        {'scene_catalog': None}, {'scene_catalog': 'x'}, {'scene_catalog': [None, 1, 'x', {}, {'id': 1, 'name': 2}]}):
            with self.subTest(changes=changes):
                self.assertIsNone(clean_status(connected_status(**changes))['slots'])

    def test_a_long_list_is_cut_at_eight_and_names_are_short_ascii(self):
        catalog = [{'id': 'a', 'name': '<b>Evil</b> "name" & \x00\n tabs\t' + 'x' * 100},
                   {'id': 'b', 'name': '\N{CYRILLIC SMALL LETTER A}\N{CYRILLIC SMALL LETTER BE}'},
                   {'id': 'c', 'name': '  Spaced   out  '},
                   {'id': 'd', 'name': 'Caf\N{LATIN SMALL LETTER E WITH ACUTE}'}]
        result = clean_status(connected_status(scene_delivered_ids=['a', 'b', 'c', 'd'] * 5, scene_catalog=catalog))
        self.assertEqual(len(result['slots']), 8)
        names = [slot['name'] for slot in result['slots'][:4]]
        self.assertEqual(names, ['bEvil/b name tabs' + 'x' * 15, None, 'Spaced out', 'Caf'])
        for name in names:
            if name:
                self.assertTrue(name.isascii() and name.isprintable() and len(name) <= 32 and not set(name) & set('<>"&\''))

    def test_the_firmware_text_is_shown_when_the_monitor_gives_it_and_cleaned(self):
        for raw, shown in (('44', '44'), ('43 beta', '43 beta'), ('<script>alert(1)</script>', 'scriptalert(1)/s'),
                           ('x' * 40, 'x' * 16), ('', None), ('\n', None), (44, None), (None, None), (['44'], None)):
            with self.subTest(raw=raw):
                self.assertEqual(clean_status(connected_status(firmware=raw))['firmware'], shown)
        self.assertIsNone(clean_status(connected_status())['firmware'])        # the control room reports none today

    def test_nothing_else_passes_through(self):
        raw = connected_status(token='0123456789abcdef', url='http://192.168.1.60', board_display={'token': SECRET}, extra=[1, 2])
        result = clean_status(raw)
        self.assertEqual(set(result), SHAPE)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn('0123456789abcdef', json.dumps(result))
        self.assertNotIn('192.168', json.dumps(result))
        self.assertEqual(json.loads(json.dumps(result)), result)                # plain JSON types only


UNKNOWN = {'state': 'unavailable', 'page': None, 'controls': False, 'rotation': None, 'speed': None, 'night': None,
           'firmware': None, 'slots': None}


def free_port():
    """A port nothing listens on (the system just handed it out and it is closed again)."""
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def only(method, hook):
    return lambda handler, record: record['method'] == method and hook(handler, record)


class FakeResponse(io.BytesIO):
    status = 200

    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}


class FakeOpener:
    """Records what it is asked and answers with a fixed body: no socket is involved."""

    def __init__(self, body=None):
        self.body = json.dumps(connected_status()).encode() if body is None else body
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        return FakeResponse(self.body)


class ConstructionTests(unittest.TestCase):
    def test_the_default_address_is_the_monitor_and_a_fake_opener_shows_what_would_be_asked(self):
        opener = FakeOpener()
        remote = BoardRemote(opener=opener)                       # the real address, never connected to: the opener is a fake
        self.assertEqual(remote.status(), expected_status())
        ((request, timeout),) = opener.calls
        self.assertEqual((request.get_method(), request.full_url, timeout), ('GET', 'http://127.0.0.1:8787/board/status', 8))
        self.assertEqual(request.get_header('Host'), '127.0.0.1:8787')
        self.assertIsNone(request.data)
        self.assertFalse(request.has_header('Origin'))
        opener.calls.clear()
        self.assertTrue(remote.command('night', NIGHT)['ok'])
        ((request, timeout),) = opener.calls
        self.assertEqual((request.get_method(), request.full_url), ('POST', 'http://127.0.0.1:8787/board/night'))
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(request.get_header('Host'), '127.0.0.1:8787')
        self.assertEqual(request.data, b'{"value":{"enabled":true,"start":"23:00","end":"07:30","level":25}}')

    def test_only_a_loopback_address_with_a_port_is_accepted(self):
        for base in ('http://localhost:8787', 'https://127.0.0.1:8787', 'http://127.0.0.1', 'http://127.0.0.1:', 'http://127.0.0.1:0',
                     'http://127.0.0.1:65536', 'http://127.0.0.1:123456', 'http://127.0.0.1:8787/board', 'http://127.0.0.1:8787/?x=1',
                     'http://127.0.0.2:8787', 'http://192.168.1.2:8787', 'http://user@127.0.0.1:8787', 'http://[::1]:8787',
                     'http://127.0.0.1:8787@evil.example', 'http://127.0.0.1:8787\n', '127.0.0.1:8787', '', None, 8787,
                     b'http://127.0.0.1:8787'):
            with self.subTest(base=base), self.assertRaises(ValueError):
                BoardRemote(base, opener=FakeOpener())
        for base, host in (('http://127.0.0.1:8787/', '127.0.0.1:8787'), ('http://127.0.0.1:1', '127.0.0.1:1'),
                           ('http://127.0.0.1:65535', '127.0.0.1:65535'), ('http://127.0.0.1:08787', '127.0.0.1:8787')):
            opener = FakeOpener()
            BoardRemote(base, opener=opener).status()
            with self.subTest(base=base):
                self.assertEqual(opener.calls[0][0].get_header('Host'), host)
                self.assertEqual(opener.calls[0][0].full_url, 'http://' + host + '/board/status')

    def test_unreasonable_timeouts_and_gaps_are_refused(self):
        for options in ({'timeout': 0}, {'timeout': -1}, {'timeout': 61}, {'timeout': None}, {'timeout': '8'}, {'timeout': True},
                        {'timeout': float('nan')}, {'timeout': float('inf')}, {'min_gap': -0.1}, {'min_gap': 3601},
                        {'min_gap': None}, {'min_gap': '1'}, {'min_gap': True}, {'min_gap': float('nan')}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                BoardRemote(opener=FakeOpener(), **options)
        BoardRemote(opener=FakeOpener(), timeout=0.2, min_gap=0)

    def test_the_guard_really_stops_a_connection_to_a_real_service(self):
        for port in FORBIDDEN_PORTS:
            with self.subTest(port=port), socket.socket() as sock, self.assertRaises(AssertionError):
                sock.connect(('127.0.0.1', port))


class RemoteCase(unittest.TestCase):
    """A remote wired to a stand-in control room, with a clock the test moves by hand."""

    def setUp(self):
        self.stand_in = StandIn()
        self.addCleanup(self.stand_in.close)
        self.clock = Clock()
        self.remote = self.make()

    def make(self, **options):
        options.setdefault('timeout', 3)
        options.setdefault('min_gap', 1.0)
        return BoardRemote(self.stand_in.base, clock=self.clock, **options)

    def answer_with(self, code):
        def hook(handler, record):
            self.stand_in.refuse(handler, code)
            return True
        return hook

    def answer_body(self, body, code=200, extra=()):
        def hook(handler, record):
            self.stand_in.reply(handler, code, body, extra=extra)
            return True
        return hook

    @staticmethod
    def headers(record):
        return {name.lower(): value for name, value in record['headers']}


class WireTests(RemoteCase):
    def test_status_is_a_plain_get_of_one_fixed_path(self):
        self.assertEqual(self.remote.status(), expected_status())
        (request,) = self.stand_in.sent()
        headers = self.headers(request)
        self.assertEqual((request['method'], request['path'], request['body']), ('GET', '/board/status', b''))
        self.assertEqual(headers['host'], f'127.0.0.1:{self.stand_in.port}')
        for name in ('origin', 'cookie', 'authorization', 'x-token', 'referer', 'content-type', 'content-length'):
            self.assertNotIn(name, headers)

    def test_every_command_is_one_post_with_json_and_a_body_that_holds_only_the_value(self):
        for index, (name, value) in enumerate((('page', 3), ('rotation', 60), ('speed', 125), ('night', {**NIGHT, 'level': 40}))):
            self.clock.now += 5
            result = self.remote.command(name, value)
            with self.subTest(name=name):
                self.assertTrue(result['ok'], result)
                posts = self.stand_in.sent('POST')
                self.assertEqual(len(posts), index + 1)
                request = posts[-1]
                headers = self.headers(request)
                self.assertEqual((request['method'], request['path']), ('POST', '/board/' + name))
                self.assertEqual(headers['host'], f'127.0.0.1:{self.stand_in.port}')
                self.assertEqual(headers['content-type'], 'application/json')
                self.assertEqual(int(headers['content-length']), len(request['body']))
                self.assertTrue(0 < len(request['body']) <= 1024)
                self.assertEqual(set(json.loads(request['body'])), {'value'})
                self.assertEqual(json.loads(request['body'])['value'], value)
                for forbidden in ('origin', 'cookie', 'authorization', 'x-token', 'referer'):
                    self.assertNotIn(forbidden, headers)

    def test_the_exact_bytes_of_the_body(self):
        for name, value, body in (('page', 0, b'{"value":0}'), ('page', 7, b'{"value":7}'), ('rotation', 30, b'{"value":30}'),
                                  ('speed', 75, b'{"value":75}'),
                                  ('night', {'level': 5, 'end': '00:00', 'start': '01:02', 'enabled': False},   # any key order in
                                   b'{"value":{"enabled":false,"start":"01:02","end":"00:00","level":5}}')):   # the same order out
            self.clock.now += 5
            self.assertTrue(self.remote.command(name, value)['ok'])
            with self.subTest(name=name, value=value):
                self.assertEqual(self.stand_in.sent('POST')[-1]['body'], body)

    def test_only_these_five_paths_are_ever_requested(self):
        for name, value in ACCEPTED:
            self.clock.now += 20
            self.remote.status()
            self.assertTrue(self.remote.command(name, value)['ok'])
        for name, value in REFUSED:
            self.remote.command(name, value)
        seen = {(record['method'], record['path']) for record in self.stand_in.sent()}
        self.assertEqual(seen, {('GET', '/board/status'), ('POST', '/board/page'), ('POST', '/board/rotation'),
                                ('POST', '/board/speed'), ('POST', '/board/night')})

    def test_environment_proxies_are_not_used(self):
        proxies = {key: 'http://127.0.0.1:9' for key in ('http_proxy', 'HTTP_PROXY', 'all_proxy', 'ALL_PROXY')}
        with mock.patch.dict(os.environ, {**proxies, 'no_proxy': '', 'NO_PROXY': ''}):
            remote = self.make()
            self.assertEqual(remote.status()['state'], 'ok')
            self.clock.now += 5
            self.assertTrue(remote.command('page', 2)['ok'])
        self.assertEqual(len(self.stand_in.sent()), 2)

    def test_redirects_are_not_followed_and_nothing_is_sent_on_to_where_they_point(self):
        elsewhere = StandIn()
        self.addCleanup(elsewhere.close)
        for code in (301, 302, 303, 307, 308):
            def hook(handler, record, code=code):
                handler.send_response(code)
                handler.send_header('Location', elsewhere.base + '/board/status')
                handler.send_header('Content-Length', '0')
                handler.end_headers()
                return True
            self.stand_in.hook = hook
            self.clock.now += 20
            with self.subTest(code=code):
                self.assertEqual(self.remote.status(), UNKNOWN)
                self.assertEqual(self.remote.command('page', 2), {'ok': False, 'status': None, 'error': 'unavailable'})
        self.assertEqual(elsewhere.sent(), [])


class CacheTests(RemoteCase):
    def test_one_real_request_per_fifteen_seconds(self):
        first = self.remote.status()
        self.assertEqual(first, expected_status())
        self.assertEqual(len(self.stand_in.sent()), 1)
        self.stand_in.status['page'] = 5
        for seconds in (0, 1, 7.5, 14.9, 14.999):
            self.clock.now = 1000.0 + seconds
            self.assertEqual(self.remote.status(), first)                    # still what it said at 1000.0
        self.assertEqual(len(self.stand_in.sent()), 1)
        self.clock.now = 1015.0
        self.assertEqual(self.remote.status()['page'], 5)                    # fifteen seconds old: it asks again
        self.assertEqual(len(self.stand_in.sent()), 2)
        self.clock.now = 1029.9
        self.remote.status()
        self.assertEqual(len(self.stand_in.sent()), 2)                       # and the new answer counts from its own moment
        self.clock.now = 1030.0
        self.remote.status()
        self.assertEqual(len(self.stand_in.sent()), 3)

    def test_what_is_handed_out_is_a_copy(self):
        first = self.remote.status()
        first['night']['level'] = 99
        first['slots'][0]['name'] = 'Changed'
        first['slots'].append('junk')
        first['page'] = 7
        self.assertEqual(self.remote.status(), expected_status())

    def test_a_failure_is_remembered_for_the_same_time_so_a_dead_monitor_is_not_hammered(self):
        self.stand_in.hook = self.answer_with(503)
        for _ in range(5):
            self.assertEqual(self.remote.status(), UNKNOWN)
        self.assertEqual(len(self.stand_in.sent()), 1)
        self.stand_in.hook = None
        self.clock.now = 1014.0
        self.assertEqual(self.remote.status(), UNKNOWN)
        self.assertEqual(len(self.stand_in.sent()), 1)
        self.clock.now = 1015.0
        self.assertEqual(self.remote.status(), expected_status())                # and it recovers on the next real request
        self.assertEqual(len(self.stand_in.sent()), 2)

    def test_a_monitor_that_is_not_running_is_unavailable_and_asked_once_per_window(self):
        class Counting:
            calls = 0
            inner = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def open(self, request, timeout=None):
                self.calls += 1
                return self.inner.open(request, timeout=timeout)
        opener = Counting()
        remote = BoardRemote(f'http://127.0.0.1:{free_port()}', timeout=3, clock=self.clock, opener=opener)
        for _ in range(4):
            self.assertEqual(remote.status(), UNKNOWN)
        self.assertEqual(opener.calls, 1)
        self.clock.now += 15
        remote.status()
        self.assertEqual(opener.calls, 2)

    def test_a_command_drops_the_cache_but_a_refused_one_does_not(self):
        self.remote.status()
        self.assertEqual(self.remote.command('page', 99)['error'], 'invalid')
        self.assertEqual(self.remote.command('mystery', 1)['error'], 'invalid')
        self.remote.status()
        self.assertEqual(len(self.stand_in.sent('GET')), 1)                      # nothing happened, so nothing was dropped
        result = self.remote.command('page', 4)
        self.assertEqual((result['ok'], result['status']['page']), (True, 4))
        self.assertEqual(self.remote.status()['page'], 4)
        self.assertEqual(len(self.stand_in.sent('GET')), 2)                      # the command dropped it: asked again at once

    def test_a_command_that_failed_drops_the_cache_too_because_the_board_may_have_changed(self):
        self.remote.status()
        self.stand_in.hook = only('POST', self.answer_with(503))
        self.assertEqual(self.remote.command('page', 4)['error'], 'unavailable')
        self.remote.status()
        self.assertEqual(len(self.stand_in.sent('GET')), 2)

    def test_a_status_asked_before_a_command_ended_is_not_kept_after_it(self):
        entered, proceed = threading.Event(), threading.Event()

        def hook(handler, record):
            if record['method'] == 'GET':
                body = json.dumps(self.stand_in.status).encode()                 # what the monitor knew when it was asked
                entered.set()
                proceed.wait(5)
                self.stand_in.reply(handler, 200, body)
                return True
            return False
        self.stand_in.hook = hook
        old = []
        thread = threading.Thread(target=lambda: old.append(self.remote.status()))
        thread.start()
        self.assertTrue(entered.wait(5))
        self.assertTrue(self.remote.command('page', 6)['ok'])                    # ends while the status request is still open
        proceed.set()
        thread.join(5)
        self.assertEqual(old[0]['page'], 1)                                      # the caller that asked got what was true then
        self.stand_in.hook = None
        self.assertEqual(self.remote.status()['page'], 6)                        # but it was not kept for the next fifteen seconds
        self.assertEqual(len(self.stand_in.sent('GET')), 2)

    def test_simultaneous_status_calls_share_one_request(self):
        entered, proceed = threading.Event(), threading.Event()

        def hook(handler, record):
            entered.set()
            proceed.wait(5)
            return False
        self.stand_in.hook = only('GET', hook)
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.remote.status())) for _ in range(5)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(5))
        proceed.set()
        for thread in threads:
            thread.join(5)
        self.assertEqual(len(self.stand_in.sent('GET')), 1)
        self.assertEqual(results, [expected_status()] * 5)


class CommandTests(RemoteCase):
    def test_a_command_the_control_room_confirms(self):
        self.assertEqual(self.remote.command('rotation', 60), {'ok': True, 'status': expected_status(rotation=60), 'error': None})
        self.clock.now += 5
        night = {'enabled': False, 'start': '22:00', 'end': '06:00', 'level': 10}
        self.assertEqual(self.remote.command('night', night),
                         {'ok': True, 'status': expected_status(rotation=60, night=night), 'error': None})

    def test_a_refused_value_never_causes_a_request(self):
        for name, value in REFUSED:
            with self.subTest(name=name, value=value):
                self.assertEqual(self.remote.command(name, value), {'ok': False, 'status': None, 'error': 'invalid'})
        self.assertEqual(self.stand_in.sent(), [])

    def test_the_gap_between_commands(self):
        self.assertTrue(self.remote.command('page', 1)['ok'])                    # at 1000.0
        for now in (1000.0, 1000.5, 1000.999):
            self.clock.now = now
            self.assertEqual(self.remote.command('page', 2), {'ok': False, 'status': None, 'error': 'busy'})
        self.assertEqual(len(self.stand_in.sent('POST')), 1)                     # a refused command sends nothing
        self.clock.now = 1001.0
        self.assertTrue(self.remote.command('page', 2)['ok'])
        self.assertEqual(len(self.stand_in.sent('POST')), 2)

    def test_the_gap_counts_from_the_end_of_the_previous_command_not_its_start(self):
        def slow(handler, record):
            self.clock.advance(0.8)                                              # the board took 0.8 s to confirm
            return False
        self.stand_in.hook = only('POST', slow)
        self.assertTrue(self.remote.command('page', 1)['ok'])                    # starts at 1000.0, ends at 1000.8
        self.clock.now = 1001.2                                                  # 1.2 s after the start, 0.4 s after the end
        self.assertEqual(self.remote.command('page', 2)['error'], 'busy')
        self.clock.now = 1001.9
        self.assertTrue(self.remote.command('page', 2)['ok'])

    def test_a_refusal_neither_starts_nor_restarts_the_gap(self):
        self.assertEqual(self.remote.command('page', 99)['error'], 'invalid')
        self.assertTrue(self.remote.command('page', 1)['ok'])                    # an invalid value did not make this wait
        self.clock.now = 1000.6
        self.assertEqual(self.remote.command('page', 2)['error'], 'busy')
        self.clock.now = 1001.0
        self.assertTrue(self.remote.command('page', 2)['ok'])                   # counted from the command, not from the refusal

    def test_a_gap_of_zero_allows_commands_back_to_back(self):
        remote = self.make(min_gap=0)
        for page in (1, 2, 3):
            self.assertTrue(remote.command('page', page)['ok'])

    def test_a_failed_command_also_counts_for_the_gap(self):
        self.stand_in.hook = only('POST', self.answer_with(503))
        self.assertEqual(self.remote.command('page', 1)['error'], 'unavailable')
        self.stand_in.hook = None
        self.clock.now = 1000.5
        self.assertEqual(self.remote.command('page', 1)['error'], 'busy')
        self.clock.now = 1001.0
        self.assertTrue(self.remote.command('page', 1)['ok'])

    def test_a_command_that_times_out_says_so_in_one_word(self):
        remote = self.make(timeout=0.3)

        def hold(handler, record):
            self.stand_in.release.wait(10)
            return True
        self.stand_in.hook = only('POST', hold)
        started = time.monotonic()
        self.assertEqual(remote.command('page', 1), {'ok': False, 'status': None, 'error': 'timeout'})
        self.assertLess(time.monotonic() - started, 3)
        self.stand_in.hook = hold
        self.assertEqual(remote.status(), UNKNOWN)                               # a status that gets no answer is just unavailable

    def test_a_slow_trickle_does_not_hold_the_remote_longer_than_its_timeout(self):
        remote = self.make(timeout=0.4)

        def trickle(handler, record):
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/json')
            handler.send_header('Content-Length', '50')
            handler.end_headers()
            for _ in range(50):                                                  # one byte every 0.1 s: no single read times out
                handler.wfile.write(b' ')
                handler.wfile.flush()
                if self.stand_in.release.wait(0.1):
                    break
            return True
        self.stand_in.hook = only('POST', trickle)
        started = time.monotonic()
        self.assertEqual(remote.command('page', 1)['error'], 'timeout')
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(remote._command.locked())                               # and the lock came back


class BadAnswerTests(RemoteCase):
    """Whatever the monitor (or something pretending to be it) says, only fixed words and the fixed shape come out."""

    def cases(self):
        deep = b'[' * 30000 + b']' * 30000                                       # inside the size cap, but deeper than JSON can go
        good = json.dumps(connected_status())
        return [('400', self.answer_with(400), 'rejected'),
                *[(str(code), self.answer_with(code), 'unavailable') for code in (403, 404, 409, 500, 502, 503)],
                ('204', self.answer_body(b'', 204), 'unavailable'),
                ('202 with a good body', self.answer_body(good.encode(), 202), 'unavailable'),
                ('html', self.answer_body(b'<html>nope</html>'), 'unavailable'),
                ('empty', self.answer_body(b''), 'unavailable'),
                *[('json ' + body.decode(), self.answer_body(body), 'unavailable')
                  for body in (b'null', b'[]', b'"connected"', b'123', b'true', b'{}', b'{"state":"weird"}', b'{"state":null}',
                               b'{"state":"connected"', b'[{"state":"connected"}]')],
                ('not utf-8', self.answer_body(b'\xff\xfe{"state":"connected"}'), 'unavailable'),
                ('too deep', self.answer_body(deep), 'unavailable'),
                ('dropped connection', lambda handler, record: True, 'unavailable')]

    def test_every_bad_answer_is_unavailable_or_rejected_and_leaks_nothing(self):
        remote = self.make(min_gap=0)
        for label, hook, word in self.cases():
            self.stand_in.hook = hook
            self.clock.now += 20
            with self.subTest(label=label):
                status, result = remote.status(), remote.command('page', 2)
                self.assertEqual(status, UNKNOWN)
                self.assertEqual(result, {'ok': False, 'status': None, 'error': word})
                self.assertIn(result['error'], tablet_board.ERRORS)
                self.assertNotIn(SECRET, json.dumps([status, result]))

    def test_a_monitor_that_is_not_running(self):
        remote = BoardRemote(f'http://127.0.0.1:{free_port()}', timeout=3, min_gap=0)
        self.assertEqual(remote.status(), UNKNOWN)
        self.assertEqual(remote.command('page', 2), {'ok': False, 'status': None, 'error': 'unavailable'})

    def test_an_answer_over_the_size_cap_is_refused_and_one_at_the_cap_is_not(self):
        remote = self.make(min_gap=0)
        status = json.dumps({**connected_status(), 'pad': ''}).encode()

        def padded(size):
            body = json.dumps({**connected_status(), 'pad': 'x' * (size - len(status))}).encode()
            self.assertEqual(len(body), size)
            return body
        for size, state in ((tablet_board.RESPONSE_LIMIT, 'ok'), (tablet_board.RESPONSE_LIMIT + 1, 'unavailable'),
                            (200_000, 'unavailable')):
            self.stand_in.hook = self.answer_body(padded(size))
            self.clock.now += 20
            with self.subTest(size=size):
                self.assertEqual(remote.status()['state'], state)
                self.assertEqual(remote.command('page', 1)['ok'], state == 'ok')

    def test_a_declared_size_over_the_cap_is_refused_without_waiting_for_the_body(self):
        remote = self.make(timeout=3, min_gap=0)

        def promise(handler, record):
            handler.send_response(200)
            handler.send_header('Content-Length', '70000')
            handler.end_headers()
            handler.wfile.flush()
            self.stand_in.release.wait(10)                                       # ... and never delivers it
            return True
        self.stand_in.hook = promise
        started = time.monotonic()
        self.assertEqual(remote.status(), UNKNOWN)
        self.assertEqual(remote.command('page', 1)['error'], 'unavailable')      # a refusal, not the 'timeout' of waiting
        self.assertLess(time.monotonic() - started, 2)

    def test_an_endless_body_without_a_length_is_cut_at_the_cap(self):
        remote = self.make(min_gap=0)

        def endless(handler, record):
            handler.send_response(200)
            handler.end_headers()
            for _ in range(40):
                handler.wfile.write(b' ' * 8192)
            return True
        self.stand_in.hook = endless
        self.assertEqual(remote.status(), UNKNOWN)
        self.assertEqual(remote.command('page', 1)['error'], 'unavailable')


class SerializationTests(RemoteCase):
    def hold_first_post(self):
        entered, proceed = threading.Event(), threading.Event()

        def hook(handler, record):
            entered.set()
            proceed.wait(5)
            return False
        self.stand_in.hook = only('POST', hook)
        return entered, proceed

    def test_a_second_command_while_one_is_running_is_refused_at_once_and_never_overlaps(self):
        entered, proceed = self.hold_first_post()
        first = []
        thread = threading.Thread(target=lambda: first.append(self.remote.command('page', 2)))
        thread.start()
        self.assertTrue(entered.wait(5))
        started = time.monotonic()
        self.assertEqual(self.remote.command('page', 3), {'ok': False, 'status': None, 'error': 'busy'})
        self.assertEqual(self.remote.command('night', NIGHT), {'ok': False, 'status': None, 'error': 'busy'})
        self.assertLess(time.monotonic() - started, 1)                           # it did not wait for the first
        proceed.set()
        thread.join(5)
        self.assertTrue(first[0]['ok'])
        self.assertEqual(first[0]['status']['page'], 2)
        posts = self.stand_in.sent('POST')
        self.assertEqual([json.loads(record['body'])['value'] for record in posts], [2])
        self.assertEqual(self.stand_in.max_active, 1)
        self.assertFalse(self.remote._command.locked())

    def test_two_threads_released_together_make_exactly_one_request(self):
        barrier = threading.Barrier(2)
        results = []

        def run(value):
            barrier.wait(5)
            results.append(self.remote.command('page', value))
        threads = [threading.Thread(target=run, args=(value,)) for value in (2, 5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(sorted(result['error'] or 'ok' for result in results), ['busy', 'ok'])
        self.assertEqual(len(self.stand_in.sent('POST')), 1)
        self.assertEqual(self.stand_in.max_active, 1)

    def test_a_status_is_not_held_up_by_a_command_in_flight(self):
        entered, proceed = self.hold_first_post()
        thread = threading.Thread(target=lambda: self.remote.command('page', 2))
        thread.start()
        self.assertTrue(entered.wait(5))
        started = time.monotonic()
        self.assertEqual(self.remote.status()['state'], 'ok')
        self.assertLess(time.monotonic() - started, 1)
        proceed.set()
        thread.join(5)


class RealRoutesTests(unittest.TestCase):
    """The remote against the control room's REAL routes (token_tv.live.handler over a BoardControl) with a pretend board."""

    def setUp(self):
        from token_tv import board_scenes
        from token_tv.board_scenes import NEW_SCENES, BoardScenes
        from token_tv.live import handler
        from token_tv.state import UsageStore
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        # The scene list normally asks whether Tony's private pictures exist; a test must not look at them.
        patcher = mock.patch.object(board_scenes, 'available', lambda scene: scene not in NEW_SCENES)
        patcher.start()
        self.addCleanup(patcher.stop)
        root = Path(self.directory.name)
        self.board = FakeBoard()
        self.scenes = BoardScenes(root / 'scenes.json', threading.Event())
        self.confirm(range(8))
        self.changed = threading.Event()
        self.night = NightMode(root / 'night.json', self.changed)
        self.serve(BoardControl(self.board, self.scenes, self.night), handler, UsageStore([]))

    def serve(self, control, handler, store):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(store, board_control=control))
        server.handle_error = lambda request, client: None
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.remote = BoardRemote(f'http://127.0.0.1:{server.server_port}', timeout=3, min_gap=0)

    def confirm(self, slots):
        for slot in slots:
            self.scenes.confirm_slot(slot, self.scenes.ids[slot])

    def test_the_status_is_the_fixed_shape_with_the_real_names_of_the_screens(self):
        self.assertEqual(self.remote.status(), expected_status(page=0, rotation=0, speed=100))

    def test_screens_the_monitor_has_not_confirmed_have_no_name(self):
        self.scenes.delivered[:] = [None] * 8
        self.confirm((1, 4))
        self.assertEqual([slot['name'] for slot in self.remote.status()['slots']],
                         [None, 'Paradise', None, None, 'Token Run', None, None, None])
        self.scenes.delivered[:] = [None] * 8
        self.remote = BoardRemote(self.remote._base, timeout=3, min_gap=0)
        self.assertIsNone(self.remote.status()['slots'])

    def test_a_screen_chosen_but_not_yet_delivered_is_named_as_what_is_on_the_board(self):
        self.scenes.select({'slot': 2, 'scene': 'surf'})                       # wanted: Tidal Rush; the board still holds Neon City
        slots = self.remote.status()['slots']
        self.assertEqual(slots[2]['name'], 'Neon City')

    def test_each_command_reaches_the_pretend_board_and_comes_back_confirmed(self):
        result = self.remote.command('page', 3)
        self.assertEqual((result['ok'], result['status']['page']), (True, 3))
        self.assertIn(('show', 3), self.board.calls)
        result = self.remote.command('rotation', 60)
        self.assertEqual((result['ok'], result['status']['rotation']), (True, 60))
        self.assertIn(('configure', 60, None, None), self.board.calls)
        result = self.remote.command('speed', 125)
        self.assertEqual((result['ok'], result['status']['speed']), (True, 125))
        self.assertIn(('configure', None, 125, 3), self.board.calls)           # per-screen firmware: the page on display, index 3
        self.assertEqual(self.board.state['animation_speeds'], [100, 100, 100, 125, 100, 100, 100, 100])
        night = {'enabled': True, 'start': '21:30', 'end': '06:15', 'level': 35}
        self.changed.clear()
        result = self.remote.command('night', night)
        self.assertEqual((result['ok'], result['status']['night']), (True, night))
        self.assertEqual(self.night.settings(), night)
        self.assertTrue(self.changed.is_set())                                  # the monitor will tell the board within a pass

    def test_on_firmware_without_per_screen_speed_the_percent_goes_to_every_page(self):
        self.board.state['per_screen_speed'] = False
        result = self.remote.command('speed', 75)
        self.assertEqual((result['ok'], result['status']['speed']), (True, 75))
        self.assertIn(('configure', None, 75, None), self.board.calls)

    def test_firmware_that_has_no_controls_says_so_and_rejects_rotation_and_speed(self):
        self.board.state.pop('board_controls')
        self.board.info()                                                        # the control room reads what the board last said
        status = self.remote.status()
        self.assertEqual((status['state'], status['controls']), ('ok', False))
        self.assertEqual(self.remote.command('rotation', 30), {'ok': False, 'status': None, 'error': 'rejected'})
        self.assertEqual(self.remote.command('speed', 100), {'ok': False, 'status': None, 'error': 'rejected'})
        self.assertTrue(self.remote.command('page', 1)['ok'])                   # choosing a page works on any firmware

    def test_a_board_that_cannot_dim_has_no_night_schedule_to_show(self):
        self.board.state['brightness'] = 0
        self.board.info()
        self.assertIsNone(self.remote.status()['night'])

    def test_an_offline_board_keeps_the_pc_side_facts_and_loses_the_board_side_ones(self):
        self.board.offline = True
        self.board.last_seen = time.monotonic() - 100
        status = self.remote.status()
        self.assertEqual((status['state'], status['page'], status['controls'], status['rotation'], status['speed']),
                         ('offline', None, False, None, None))
        self.assertEqual(status['night'], NIGHT)
        self.assertEqual(len(status['slots']), 8)
        result = self.remote.command('page', 2)                                  # the control room could not confirm: 503
        self.assertEqual(result, {'ok': False, 'status': None, 'error': 'unavailable'})
        self.assertTrue(self.remote.command('night', {**NIGHT, 'level': 50})['ok'])      # the schedule is the PC's own, kept anyway

    def test_a_monitor_without_a_board_is_not_configured(self):
        from token_tv.live import handler
        from token_tv.state import UsageStore
        self.serve(BoardControl(None, self.scenes, self.night), handler, UsageStore([]))
        status = self.remote.status()
        self.assertEqual((status['state'], status['page'], status['controls'], status['night']), ('not_configured', None, False, None))
        self.assertEqual(self.remote.command('page', 2)['error'], 'unavailable')

    def test_a_busy_board_with_a_known_page_is_still_ok_and_the_night_schedule_does_not_wait_for_it(self):
        with self.board.lock:                                                    # the monitor is "sending a page"
            status = self.remote.status()
            self.assertEqual((status['state'], status['page'], status['controls']), ('ok', 0, True))
            result = self.remote.command('night', {**NIGHT, 'level': 60})        # saved on the PC, no need for the board
            self.assertEqual((result['ok'], result['status']['state'], result['status']['night']['level']), (True, 'ok', 60))

    def test_a_command_that_times_out_may_still_be_carried_out_by_the_monitor_later(self):
        remote = BoardRemote(self.remote._base, timeout=0.4, min_gap=0)
        self.board.lock.acquire()                                                # a page transfer holds the board
        try:
            self.assertEqual(remote.command('page', 6), {'ok': False, 'status': None, 'error': 'timeout'})
            self.assertNotIn(('show', 6), self.board.calls)
        finally:
            self.board.lock.release()
        deadline = time.monotonic() + 5
        while ('show', 6) not in self.board.calls and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIn(('show', 6), self.board.calls)                            # ... and so it did, after the caller had given up


if __name__ == '__main__':
    unittest.main()
