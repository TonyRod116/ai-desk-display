"""Local browser controls use the paired board safely and report confirmed state."""
import json
from io import BytesIO
import struct
import threading
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

from token_tv.board import BoardDisplay
from token_tv.board_control import BoardControl
from token_tv.board_scenes import BoardScenes
from token_tv.live import handler
from token_tv.state import UsageStore


class FakeBoard:
    def __init__(self, controls=1):
        self.lock = threading.RLock()
        self.last_info = None
        self.last_seen = 0
        self.state = {'page': 1, 'rotation_minutes': 0, 'animation_speed': 100,
                      'board_controls': controls, 'clock_synced': True,
                      'per_screen_speed': True, 'animation_speeds': [100] * 8,
                      'touch_controls': 1, 'mode_hold_seconds': 2, 'connect_hold_seconds': 5}
        self.calls = []

    def info(self):
        self.calls.append('info')
        self.last_info = dict(self.state)
        self.last_seen = time.monotonic()
        return dict(self.state)

    def show(self, page):
        self.calls.append(('show', page))
        self.state['page'] = page + 1
        self.state['animation_speed'] = self.state['animation_speeds'][page]

    def configure(self, cycle=None, speed=None, speed_page=None, mode_hold=None, connect_hold=None):
        self.calls.append(('configure', cycle, speed))
        if cycle is not None:
            self.state['rotation_minutes'] = cycle
        if speed is not None:
            page = self.state['page'] - 1 if speed_page is None else speed_page
            self.state['animation_speeds'][page] = speed
            if self.state['page'] - 1 == page:
                self.state['animation_speed'] = speed
        if mode_hold is not None:
            self.state['mode_hold_seconds'] = mode_hold
            self.state['connect_hold_seconds'] = connect_hold


class BoardControlTests(unittest.TestCase):
    def test_platform_library_preview_uses_the_current_scrolling_generation(self):
        from token_tv.board_preview import BASE
        from token_tv.board_scroll import decode
        control = BoardControl(None)
        control.archive_preview('cockpit', {'accounts': {}})
        frame = control.archive_frames['cockpit']
        self.assertEqual(frame[BASE:BASE + 4], b'SCRO')
        # Generation 4 uses optional local original artwork; installations
        # without it safely fall back to generation 2, never generation 1.
        self.assertIn(decode(frame[BASE + 8:])['version'], (2, 4))

    def test_real_board_client_validates_remote_controls(self):
        board = BoardDisplay('http://192.168.1.2', '0123456789abcdef')
        calls = []
        board.request = lambda path, **kwargs: (calls.append(path) or (200, b'OK'))
        board.configure(cycle=30, speed=125)
        self.assertEqual(calls, ['/config?cycle=30&speed=125'])
        board.configure(speed=75, speed_page=6, mode_hold=1, connect_hold=7)
        self.assertEqual(calls[-1], '/config?speed=75&speedpage=6&holdmode=1&holdconnect=7')
        for value in (True, -1, 1, '30'):
            with self.assertRaises(ValueError):
                board.configure(cycle=value)
        for value in (True, 0, 150, '100'):
            with self.assertRaises(ValueError):
                board.configure(speed=value)
        for mode, connect in ((0, 5), (2, 4), (5, 5), (True, 5), (1, 11)):
            with self.assertRaises(ValueError):
                board.configure(mode_hold=mode, connect_hold=connect)

    def test_commands_require_capability_and_confirmation(self):
        board = FakeBoard()
        control = BoardControl(board)
        self.assertEqual(control.execute('page', 3)['page'], 3)
        self.assertEqual(control.execute('rotation', 60)['rotation_minutes'], 60)
        self.assertEqual(control.execute('speed', 125)['speed_percent'], 125)
        self.assertEqual(control.execute('touch', {'mode': 3, 'connect': 7})['connect_hold_seconds'], 7)
        self.assertEqual(control.execute('page', 0)['speed_percent'], 100)
        self.assertEqual(control.execute('page', 3)['speed_percent'], 125)
        board.state['board_controls'] = 0
        with self.assertRaises(ValueError):
            control.execute('rotation', 30)
        self.assertEqual(control.execute('page', 0)['page'], 0)
        self.assertNotIn(('configure', 30, None), board.calls)
        for command, invalid in (('page', True), ('page', 8), ('speed', 1000), ('rotation', -1)):
            with self.assertRaises(ValueError):
                control.execute(command, invalid)
        for invalid in ({'mode': 1, 'connect': 4}, {'mode': 1, 'connect': True}, {'mode': 1}):
            with self.assertRaises(ValueError):
                control.execute('touch', invalid)

    def test_status_does_not_interrupt_an_active_board_transfer(self):
        board = FakeBoard()
        board.info()
        control = BoardControl(board)
        held = threading.Event()
        release = threading.Event()
        def transfer():
            with board.lock:
                held.set()
                release.wait(2)
        thread = threading.Thread(target=transfer)
        thread.start()
        self.assertTrue(held.wait(1))
        before = len(board.calls)
        self.assertEqual(control.status()['state'], 'busy')
        self.assertEqual(len(board.calls), before)
        release.set()
        thread.join()

    def test_offline_status_does_not_claim_the_last_seen_page_is_current(self):
        board = FakeBoard()
        board.info()
        def disconnected():
            raise OSError('offline')
        board.info = disconnected
        board.last_seen -= 16
        status = BoardControl(board).status()
        self.assertEqual(status['state'], 'offline')
        self.assertIsNone(status['page'])
        self.assertIsNone(status['speed_percent'])
        self.assertFalse(status['controls'])

    def test_connection_screen_is_reported_separately_from_remembered_scene(self):
        board = FakeBoard()
        board.state['info'] = 1
        status = BoardControl(board).status()
        self.assertTrue(status['showing_connection'])
        self.assertEqual(status['page'], 0)  # remembered page, not currently shown

    def test_a_setting_is_not_reported_saved_without_board_confirmation(self):
        board = FakeBoard()
        board.configure = lambda **kwargs: None
        with self.assertRaisesRegex(OSError, 'did not confirm'):
            BoardControl(board).execute('speed', 125)

    def test_speed_targets_the_screen_the_user_selected_even_if_touch_changes_it(self):
        board = FakeBoard()
        control = BoardControl(board)
        result = control.execute('speed', {'page': 6, 'percent': 75})
        self.assertEqual(result['page'], 0)
        self.assertEqual(result['speed_percent'], 100)
        self.assertEqual(board.state['animation_speeds'][6], 75)
        control.execute('page', 6)
        self.assertEqual(board.state['animation_speed'], 75)
        for bad in ({'page': True, 'percent': 75}, {'page': 8, 'percent': 75}, {'page': 0, 'percent': True}):
            with self.assertRaises(ValueError):
                control.execute('speed', bad)

    def test_previews_use_in_memory_frames_and_never_touch_board(self):
        board = FakeBoard()
        control = BoardControl(board)
        frame = b'TVF1' + struct.pack('<HH', 320, 240) + b'\x00\xf8' * (320 * 240)
        control.update_frames([frame])
        preview = control.preview(0)
        self.assertTrue(preview.startswith(b'\x89PNG'))
        self.assertEqual(Image.open(BytesIO(preview)).getpixel((0, 0)), (255, 0, 0))
        self.assertIsNone(control.preview(1))
        self.assertEqual(board.calls, [])

    def test_animated_surf_preview_includes_the_surfer_without_changing_the_frame(self):
        from PIL import ImageChops
        from token_tv.board_pages import rgb565_frame
        from token_tv.board_surf import render_surf
        from token_tv.sample import snapshot
        demo = snapshot(time.time(), [('codex', 'CODEX', 'codex', [('WEEK', 30, 4000)]),
                                      ('claude', 'CLAUDE', 'claude', [('WEEK', 20, 4000)])])
        background, animation = render_surf(demo, animated=True)
        frame = rgb565_frame(background, anim=animation)
        board, control = FakeBoard(), BoardControl(None)
        control.board = board
        control.update_frames([frame])
        preview = Image.open(BytesIO(control.preview(0))).convert('RGB')
        base = Image.frombytes('RGB', (320, 240), frame[8:8 + 320 * 240 * 2], 'raw', 'BGR;16')
        self.assertIsNotNone(ImageChops.difference(preview, base).getbbox())
        expected = render_surf(demo)
        # Quantize both sides to the board's RGB565 palette before comparing.
        still = rgb565_frame(expected)
        expected = Image.frombytes('RGB', (320, 240), still[8:], 'raw', 'BGR;16')
        self.assertIsNone(ImageChops.difference(preview, expected).getbbox())
        self.assertEqual(control.frames[0], frame)
        self.assertEqual(board.calls, [])


class BoardHttpTests(unittest.TestCase):
    def setUp(self):
        self.board = FakeBoard()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.changed = threading.Event()
        self.scenes = BoardScenes(Path(self.directory.name) / 'scenes.json', self.changed)
        self.store = UsageStore([])
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.store, board_control=BoardControl(self.board, self.scenes)))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.root = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, path, data, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        return urlopen(Request(self.root + path, json.dumps(data).encode(), headers))

    def test_dashboard_catalog_is_local_and_never_contacts_the_board(self):
        with urlopen(self.root + '/board/catalog') as response:
            catalog = json.load(response)
        self.assertTrue(catalog['scene_ids'])
        self.assertIn('deep-space', [scene['id'] for scene in catalog['scene_catalog']])
        self.assertEqual(self.board.calls, [])
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.root + '/board/catalog', headers={'Origin': 'https://example.com'}))
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.board.calls, [])

    def test_controls_are_local_and_report_device_confirmed_results(self):
        with urlopen(self.root + '/board/status') as response:
            self.assertEqual(json.load(response)['page'], 0)
        with self.post('/board/page', {'value': 6}, self.root) as response:
            self.assertEqual(json.load(response)['page'], 6)
        with self.post('/board/rotation', {'value': 30}, self.root) as response:
            self.assertEqual(json.load(response)['rotation_minutes'], 30)
        with self.post('/board/speed', {'value': 75}, self.root) as response:
            self.assertEqual(json.load(response)['speed_percent'], 75)
        with self.post('/board/speed', {'value': {'page': 4, 'percent': 125}}, self.root) as response:
            self.assertEqual(json.load(response)['speed_percent'], 75)  # selected scene is still 6
        self.assertEqual(self.board.state['animation_speeds'][4], 125)
        with self.post('/board/touch', {'value': {'mode': 1, 'connect': 8}}, self.root) as response:
            self.assertEqual(json.load(response)['connect_hold_seconds'], 8)

    def test_cross_origin_and_malformed_controls_are_rejected(self):
        for path, data, origin, expected in (
            ('/board/page', {'value': 1}, 'https://attacker.example', 403),
            ('/board/page', {'value': True}, self.root, 400),
            ('/board/speed', {'value': 500}, self.root, 400),
            ('/board/rotation', {'value': 30, 'extra': 1}, self.root, 400),
            ('/board/touch', {'value': {'mode': 1, 'connect': 4}}, self.root, 400),
            ('/board/scene', {'value': {'slot': 6, 'scene': 'deep-space'}}, 'https://attacker.example', 403),
            ('/board/scene', {'value': {'slot': 6, 'scene': '../private'}}, self.root, 400),
        ):
            with self.assertRaises(HTTPError) as caught:
                self.post(path, data, origin)
            self.assertEqual(caught.exception.code, expected)
        self.assertFalse(any(isinstance(call, tuple) for call in self.board.calls))

    def test_scene_selection_is_queued_without_changing_the_active_page(self):
        with self.post('/board/scene', {'value': {'slot': 6, 'scene': 'deep-space'}}, self.root) as response:
            status = json.load(response)
        self.assertEqual(status['scene_ids'][6], 'deep-space')
        self.assertTrue(status['scene_pending'][6])
        self.assertTrue(self.changed.is_set())
        self.assertEqual(self.board.calls, [])

        with urlopen(self.root + '/board/library/deep-space.png') as response:
            self.assertTrue(response.read().startswith(b'\x89PNG'))
        with urlopen(self.root + '/board/library/code-editor.png') as response:
            self.assertTrue(response.read().startswith(b'\x89PNG'))
        with urlopen(self.root + '/board/library/deep-space.webp') as response:
            mime = response.headers['Content-Type']
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            preview = Image.open(BytesIO(response.read()))
            if mime == 'image/webp':
                self.assertGreater(preview.n_frames, 1)
            else:
                self.assertEqual((mime, preview.format), ('image/png', 'PNG'))
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.root + '/board/library/deep-space.webp',
                            headers={'Origin': 'https://attacker.example'}))
        self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.root + '/board/library/deep-space.png',
                            headers={'Sec-Fetch-Site': 'cross-site'}))
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.board.calls, [])

    def test_scene_order_is_saved_once_without_contacting_the_display(self):
        before = list(self.scenes.snapshot())
        order = [1, 0, 2, 3, 4, 5, 6, 7]
        with self.post('/board/order', {'value': {'expected': before, 'order': order}}, self.root) as response:
            status = json.load(response)
        self.assertEqual(status['scene_ids'], [before[i] for i in order])
        self.assertTrue(self.changed.is_set())
        self.assertEqual(self.board.calls, [])
        with self.assertRaises(HTTPError) as caught:
            self.post('/board/order', {'value': {'expected': before, 'order': order}}, self.root)
        self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(HTTPError) as caught:
            self.post('/board/order', {'value': {'expected': status['scene_ids'], 'order': order}}, 'https://attacker.example')
        self.assertEqual(caught.exception.code, 403)

    def test_library_http_uses_cached_real_readings_and_available_credits(self):
        from tests.test_board_credits import sample as credit_sample
        from token_tv import board_cyber_scenes as city
        sample = credit_sample(balance='137.5')
        with patch.object(self.store, 'snapshot', return_value=sample), \
             patch.object(city, 'backdrop', return_value=Image.new('RGB', (320, 240), '#301845')), \
             patch.object(city, 'sign', wraps=city.sign) as signs, \
             patch('time.time', return_value=1000):
            with urlopen(self.root + '/board/library/neon-district.png') as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertTrue(response.read().startswith(b'\x89PNG'))
        codex, claude = signs.call_args_list
        self.assertEqual(codex.args[1:4], ('codex', 0, '137.5'))
        self.assertEqual(claude.args[1], 'claude')
