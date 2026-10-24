import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image

from token_tv import board as board_module
from token_tv.board import MAX_PAGE_BYTES, BoardDisplay, board_settings, publish_pages
from token_tv.board_pages import PAGE_NAMES, PAGE_SIZE, frame_size, render_board_pages, rgb565_frame
from token_tv.local_usage import LocalPolicy, local_row
from token_tv.sources import load_config
from token_tv.state import UsageStore

TOKEN = '0123456789abcdef'


class FakeBoard(BaseHTTPRequestHandler):
    """Stands in for the ESP32 firmware 3: same routes, pairing, token check and stored pages."""
    pages = {}
    corrupt = False
    options = []
    token = TOKEN      # None = a board that was just flashed and has not been claimed
    touching = False   # the address screen is showing: someone holds a finger on the board
    firmware = 'tokentv-board 3'
    diagnostics = {}   # firmware 6 adds up/rst/taps/longs/irq to /info
    stars = False
    updates = []

    def log_message(self, *args):
        pass

    def authorized(self, reply=True):
        ok = self.token is not None and self.headers.get('X-Token') == self.token
        if not ok and reply:
            self.send_response(401)
            self.end_headers()
        return ok

    def reply(self, body=b'OK', status=200):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/info':
            return self.reply(json.dumps({'model': 'tokentv-board', 'fw': self.firmware, 'pages': 6, 'w': 320,
                                          'h': 240, 'paired': self.token is not None,
                                          **({'stars': True} if self.stars else {}), **self.diagnostics}).encode())
        if self.path.startswith('/page?n=') and self.authorized():
            number = int(self.path.rsplit('=', 1)[1])
            if number in self.pages:
                return self.reply(self.pages[number])
            return self.reply(b'', 404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        if self.path.startswith('/pair?token='):
            if self.token is not None and not self.authorized(reply=False):
                return self.reply(b'token', 401)
            type(self).token = self.path.rsplit('=', 1)[1]
            return self.reply()
        if self.path == '/update':
            if not (self.authorized(reply=False) and self.touching):
                return self.reply(b'touch', 401)
            self.updates.append(len(body))
            type(self).firmware = 'tokentv-board 4'
            return self.reply()
        if not self.authorized():
            return
        if self.path.split('?')[0] == '/ping':
            return self.reply(''.join('1' if n in self.pages else '0' for n in range(6)).encode())
        if self.path.startswith('/show?n='):
            self.options.append('show=' + self.path.rsplit('=', 1)[1])
            return self.reply()
        if self.path.startswith('/config?'):
            self.options.append(self.path.split('?', 1)[1])
            return self.reply()
        if self.path.startswith('/page?n='):
            number = int(self.path.rsplit('=', 1)[1])
            start = body.index(b'\r\n\r\n') + 4
            end = body.rindex(b'\r\n--')
            data = body[start:end]
            self.pages[number] = data[:-1] if self.corrupt else data
            return self.reply()
        self.reply(b'', 404)


class BoardTests(unittest.TestCase):
    def serve(self):
        FakeBoard.pages, FakeBoard.corrupt, FakeBoard.options = {}, False, []
        FakeBoard.token, FakeBoard.touching, FakeBoard.firmware, FakeBoard.updates = TOKEN, False, 'tokentv-board 3', []
        FakeBoard.stars, FakeBoard.diagnostics = False, {}
        server = ThreadingHTTPServer(('127.0.0.1', 0), FakeBoard)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        return f'http://127.0.0.1:{server.server_port}'

    def jpeg(self, color=(10, 20, 30)):
        """Name kept from the JPEG days: a small valid frame."""
        return rgb565_frame(Image.new('RGB', (16, 8), color))

    def test_only_a_plain_private_address_and_the_screen_token_are_accepted(self):
        self.assertEqual(board_settings({'url': 'http://192.168.0.60/', 'token': TOKEN}), ('http://192.168.0.60', TOKEN))
        for url in ('https://192.168.0.60', 'http://8.8.8.8', 'http://example.com', 'http://user:pw@192.168.0.60',
                    'http://192.168.0.60/x', 'http://192.168.0.60?a=1', 'http://0.0.0.0'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                board_settings({'url': url, 'token': TOKEN})
        for token in ('', 'ABCDEF0123456789', '0123456789abcde', '0123456789abcdeg', None):
            with self.subTest(token=token), self.assertRaises(ValueError):
                board_settings({'url': 'http://192.168.0.60', 'token': token})
        with self.assertRaises(ValueError):
            board_settings({'url': 'http://192.168.0.60', 'token': TOKEN, 'extra': 1})

    def test_upload_is_authenticated_and_verified_by_reading_it_back(self):
        board = BoardDisplay(self.serve(), TOKEN)
        image = self.jpeg()
        receipt = board.upload(2, image)
        self.assertEqual((receipt['page'], receipt['bytes']), (2, len(image)))
        self.assertEqual(FakeBoard.pages[2], image)
        self.assertEqual(board.info()['model'], 'tokentv-board')
        board.ping()
        with self.assertRaises(HTTPError) as caught:                    # wrong token: refused
            BoardDisplay(board.base_url, 'f' * 16).ping()
        self.assertEqual(caught.exception.code, 401)

    def test_panel_options_are_sent_to_the_board_and_validated_first(self):
        from token_tv.cli import main
        board = BoardDisplay(self.serve(), TOKEN)
        board.configure(rotation=3, invert=True, swap_red_blue=False, swap_bytes=True)
        self.assertEqual(FakeBoard.options, ['rotation=3&invert=1&swaprb=0&swapbytes=1'])
        for bad in ({'rotation': 2}, {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                board.configure(**bad)
        self.assertEqual(len(FakeBoard.options), 1)                     # nothing invalid was sent
        with tempfile.TemporaryDirectory() as directory:                # and through the command line
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({
                'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source_home': '/tmp/demo'}],
                'local_only': True, 'board_display': {'url': board.base_url, 'token': TOKEN}}))
            self.assertEqual(main(['board', '--config', str(path), '--rotation', '1', '--swap-rb', '1']), 0)
            self.assertEqual(FakeBoard.options[-1], 'rotation=1&swaprb=1')

    def config_with(self, directory, board=None):
        path = Path(directory) / 'config.json'
        data = {'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source_home': '/tmp/demo'}],
                'local_only': True}
        if board:
            data['board_display'] = board
        path.write_text(json.dumps(data))
        return path

    def test_a_board_without_a_token_is_claimed_with_the_pcs_own(self):
        url = self.serve()
        FakeBoard.token = None                               # just flashed: nobody has paired it
        board = BoardDisplay(url, TOKEN)
        board.ensure_paired()
        self.assertEqual(FakeBoard.token, TOKEN)
        board.upload(0, self.jpeg())                         # and it works straight away
        FakeBoard.token = 'f' * 16                           # paired with someone else: never overwritten
        with self.assertRaises(HTTPError):
            board.pair(TOKEN)
        self.assertEqual(FakeBoard.token, 'f' * 16)
        board.ensure_paired()                                # a paired board is left alone
        self.assertEqual(FakeBoard.token, 'f' * 16)

    def test_connecting_needs_only_the_address_and_remembers_it(self):
        from token_tv.cli import main
        url = self.serve()
        FakeBoard.token = None
        with tempfile.TemporaryDirectory() as directory:
            path = self.config_with(directory)
            with patch('sys.stdout', new_callable=StringIO) as out:
                self.assertEqual(main(['board', '--config', str(path), '--url', url]), 0)
            saved = json.loads(path.read_text())['board_display']
            self.assertEqual(saved['url'], url)
            self.assertRegex(saved['token'], r'^[0-9a-f]{16}$')      # chosen by the PC, never typed
            self.assertEqual(FakeBoard.token, saved['token'])
            self.assertNotIn(saved['token'], out.getvalue())
            with patch('sys.stdout', new_callable=StringIO) as out:  # running it again changes nothing
                self.assertEqual(main(['board', '--config', str(path)]), 0)
            self.assertEqual(json.loads(path.read_text())['board_display'], saved)
            self.assertIn('Nothing to restart', out.getvalue())

    def test_a_board_paired_with_another_token_is_not_taken_over(self):
        from token_tv.cli import main
        url = self.serve()
        FakeBoard.token = 'f' * 16
        with tempfile.TemporaryDirectory() as directory:
            path = self.config_with(directory)
            before = path.read_text()
            with patch('sys.stderr', new_callable=StringIO) as err:
                self.assertEqual(main(['board', '--config', str(path), '--url', url]), 1)
            self.assertIn('restore its private pairing configuration', err.getvalue())
            self.assertNotIn('8 seconds', err.getvalue())  # long touch must never erase pairing
            self.assertEqual(path.read_text(), before)
            self.assertEqual(FakeBoard.token, 'f' * 16)

    def test_a_moved_board_is_found_on_its_network(self):
        from token_tv.board import find_boards
        url = self.serve()
        port = int(url.rsplit(':', 1)[1])
        self.assertEqual(find_boards(['127.0.0.1', '127.0.0.2'], port=port), ['127.0.0.1'])
        self.assertEqual(find_boards(['127.0.0.1'], port=1), [])

    def test_firmware_updates_need_the_token_and_a_finger_on_the_board(self):
        board = BoardDisplay(self.serve(), TOKEN)
        image = b'\xe9' + b'\0' * 120000
        with self.assertRaises(HTTPError) as caught:             # token alone is not enough
            board.update(image, wait=1)
        self.assertEqual(caught.exception.code, 401)
        self.assertEqual(FakeBoard.updates, [])
        FakeBoard.touching = True                                # the address screen is on
        before, after = board.update(image, wait=10)
        self.assertEqual((before, after), ('tokentv-board 3', 'tokentv-board 4'))
        self.assertEqual(len(FakeBoard.updates), 1)
        for bad in (b'', b'\x00' * 200000, b'\xe9' + b'\0' * 10):   # not a firmware image: never sent
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                board.update(bad, wait=1)

    def test_a_board_with_six_slots_is_never_sent_more_than_six_pages(self):
        url = self.serve()                                   # the fake board reports "pages": 6, like firmware 1 and 2
        board = BoardDisplay(url, TOKEN)
        self.assertEqual(board.capacity, 6)                  # assumed until it says otherwise
        board.ensure_paired()
        self.assertEqual(board.capacity, 6)
        pages = [self.jpeg((i * 20, 10, 10)) for i in range(8)]
        publish_pages(board, pages, {})
        self.assertEqual(sorted(FakeBoard.pages), [0, 1, 2, 3, 4, 5])
        self.assertEqual(FakeBoard.options, [])              # and nothing was refused along the way

    def test_the_two_showpieces_show_real_numbers_and_dashes_when_unknown(self):
        from token_tv.board_art import render_cockpit, render_countdown
        now = 1000
        windows = [{'label': 'WEEK', 'used_percent': 46, 'duration_minutes': 10080, 'resets_at': now + 5 * 86400},
                   {'label': '5H', 'used_percent': 18, 'duration_minutes': 300, 'resets_at': now + 4 * 3600}]
        rows = {}
        for provider in ('claude', 'codex'):
            account = {'key': provider, 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo'}
            record = {'source': provider + '_official_cli', 'fetched_at': now, 'stale': False,
                      'ordinary_usage_allowed': True, 'windows': windows if provider == 'claude' else windows[:1]}
            rows[provider] = local_row(account, record, now=now)
        store = UsageStore([{'key': k, 'alias': k, 'provider': k} for k in rows], fetch=lambda a: rows[a['key']])
        store.refresh()
        with patch('token_tv.state.time.time', return_value=now), patch('time.time', return_value=now):
            known = store.snapshot()
            for render in (render_cockpit, render_countdown):
                with self.subTest(page=render.__name__):
                    image = render(known)
                    self.assertEqual(image.size, PAGE_SIZE)
                    unknown = render({'accounts': {}})
                    self.assertEqual(unknown.size, PAGE_SIZE)
                    self.assertNotEqual(image.tobytes(), unknown.tobytes())      # real numbers change the picture
                    self.assertEqual(render(known).tobytes(), image.tobytes())  # and it is deterministic
            # three dots under each week time: one filled per saved reset, muted when only the last known
            def with_resets(codex, claude):
                snap = {'accounts': {k: dict(v) for k, v in known['accounts'].items()}}
                snap['accounts']['codex']['banked_resets'] = codex
                snap['accounts']['claude']['banked_resets'] = claude
                return render_countdown(snap).tobytes()
            none = with_resets({'available': 0}, {'available': 0})
            self.assertNotEqual(with_resets({'available': 2}, {'available': 0}), none)          # Codex's dots
            self.assertNotEqual(with_resets({'available': 0}, {'available': 3}), none)          # Claude's dots
            self.assertNotEqual(with_resets({'available': 0}, {'available': None, 'last_known': 1}), none)  # old
            self.assertNotEqual(with_resets({'available': 0}, {'available': None}),
                                with_resets({'available': 0}, {'available': 0}))               # unknown is not zero
            self.assertNotEqual(with_resets({'available': 0}, {'available': None, 'last_known': 1}),
                                with_resets({'available': 0}, {'available': 1}))               # old is not fresh
            # the countdown needs the session: without it, no rings of quota or time are drawn
            without = {'accounts': dict(known['accounts'])}
            without['accounts']['claude'] = dict(known['accounts']['claude'],
                                                 windows=[w for w in known['accounts']['claude']['windows'] if w['label'] != '5H'])
            self.assertNotEqual(render_countdown(without).tobytes(), render_countdown(known).tobytes())

    def test_the_lcd_grid_can_use_one_direction_only(self):
        from token_tv.personal_faces import lcd_grid
        image = Image.new('RGB', (8, 8), (155, 188, 15))
        vertical = lcd_grid(image, '#0f380f', strength=.25, cell=2, axes='vertical')
        horizontal = lcd_grid(image, '#0f380f', strength=.25, cell=2, axes='horizontal')
        for y in range(8):
            for x in range(8):
                self.assertEqual(vertical.getpixel((x, y)) != image.getpixel((x, y)), x % 2 == 1, (x, y))
                self.assertEqual(horizontal.getpixel((x, y)) != image.getpixel((x, y)), y % 2 == 1, (x, y))

    def test_the_lcd_grid_only_darkens_the_lines_between_pixels(self):
        from token_tv.personal_faces import lcd_grid
        paper, ink = (155, 188, 15), (15, 56, 15)
        image = Image.new('RGB', (8, 6), paper)
        image.putpixel((0, 0), ink)                               # an ink pixel in a cell corner
        grid = lcd_grid(image, '#0f380f', strength=.25, cell=2)
        self.assertEqual(grid.getpixel((0, 0)), ink)             # ink is already as dark as the shade
        self.assertEqual(grid.getpixel((0, 1)), grid.getpixel((1, 0)))   # the lines are darker than paper...
        line = grid.getpixel((1, 1))
        self.assertTrue(line[0] < paper[0] and line[1] < paper[1] and line[2] <= paper[2], line)
        self.assertEqual(grid.getpixel((2, 2)), paper)           # ...and the cell's first pixel is untouched
        self.assertEqual(grid.size, image.size)

    def test_the_game_boy_faces_have_the_grid_on_the_board_and_not_on_the_clock(self):
        from token_tv.personal_faces import render_gameboy
        snapshot = {'accounts': {}}
        plain, gridded = render_gameboy(snapshot, screen=PAGE_SIZE), render_gameboy(snapshot, screen=PAGE_SIZE, grid=True)
        self.assertNotEqual(plain.tobytes(), gridded.tobytes())
        self.assertEqual(len({plain.getpixel((x, 100)) for x in range(20)}) <= 3, True)   # flat two-colour art
        self.assertGreater(len({gridded.getpixel((x, 100)) for x in range(20)}), 1)

    def test_the_star_trailer_round_trips_and_malformed_ones_are_refused(self):
        import struct
        image = Image.new('RGB', (16, 8), (3, 8, 18))
        stars = [(1, 2, 0x1234), (5, 6, 0xFFFF)]
        frame = rgb565_frame(image, stars)
        plain = rgb565_frame(image)
        self.assertEqual(frame[:len(plain)], plain)                      # the pixels are exactly the same
        self.assertEqual(frame_size(frame), (16, 8))
        self.assertEqual(struct.unpack('<H', frame[len(plain) + 4:len(plain) + 6])[0], 2)
        self.assertEqual(struct.unpack('<HHH', frame[len(plain) + 6:len(plain) + 12]), (1, 2, 0x1234))
        self.assertIsNone(frame_size(frame[:-1]))                        # truncated trailer
        self.assertIsNone(frame_size(plain + b'JUNK123'))                # trailing junk
        self.assertIsNone(frame_size(plain + b'STAR' + struct.pack('<H', 5) + b'\0' * 6))   # count lies

    def test_the_cockpit_shows_the_session_as_two_thin_rings_inside_claudes_circle(self):
        import copy
        import math
        from token_tv import board_art, sample
        from token_tv.board_art import render_cockpit
        known = sample.snapshot(now=1000)
        unknown = copy.deepcopy(known)
        for row in unknown['accounts'].values():
            if row['provider'] == 'claude':
                row['windows'] = [w for w in row['windows'] if w['label'] != '5H']      # no session reading
        with patch('time.time', return_value=1000), patch('token_tv.state.time.time', return_value=1000):
            with_session, without = render_cockpit(known), render_cockpit(unknown)
        different = [(x, y) for y in range(with_session.height) for x in range(with_session.width)
                     if with_session.getpixel((x, y)) != without.getpixel((x, y))]
        self.assertGreater(len(different), 200)                          # the two rings are really drawn...
        centre = (238, 100)                                              # ...and only inside Claude's weekly band
        self.assertTrue(all(math.dist(p, centre) < 48 for p in different), 'something drew outside the circle')
        from token_tv import board_space
        bare = board_space.space_backdrop().resize((board_art.W, board_art.H), Image.Resampling.LANCZOS).convert('RGB')
        for y in range(218, 240):                                        # and the old panel below is gone
            for x in range(8, 312, 6):
                got, want = with_session.getpixel((x, y)), bare.getpixel((x, y))
                self.assertTrue(all(abs(a - b) < 40 for a, b in zip(got, want)), (x, y, got, want))

    def test_the_head_dot_of_the_cockpit_gauge_sits_on_the_centre_of_the_band(self):
        import math
        from token_tv import sample
        from token_tv.board_art import render_cockpit
        snap = sample.snapshot(now=1000)                                  # Claude's week: 14% left (86% used)
        with patch('time.time', return_value=1000), patch('token_tv.state.time.time', return_value=1000):
            image = render_cockpit(snap)
        angle = math.radians(135 + 270 * .14)
        def at(radius):
            return image.getpixel((round(238 + math.cos(angle) * radius), round(100 + math.sin(angle) * radius)))
        self.assertGreater(min(at(53)), 200)                              # the band is 48-58 px: its centre is 53
        self.assertLess(min(at(63)), 150)                                 # and the dot no longer pokes out past 58+5

    def arcade_snapshot(self, codex_left=46, claude_left=14, session=True, now=1000):
        rows = {}
        for provider in ('claude', 'codex'):
            account = {'key': provider, 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo'}
            left = claude_left if provider == 'claude' else codex_left
            windows = [{'label': 'WEEK', 'used_percent': 100 - left, 'duration_minutes': 10080,
                        'resets_at': now + 5 * 86400 + 4 * 3600}]
            if provider == 'claude' and session:
                windows.insert(0, {'label': '5H', 'used_percent': 41, 'duration_minutes': 300, 'resets_at': now + 2 * 3600})
            record = {'source': provider + '_official_cli', 'fetched_at': now, 'stale': False,
                      'ordinary_usage_allowed': True, 'windows': windows}
            rows[provider] = local_row(account, record, now=now)
        store = UsageStore([{'key': k, 'alias': k, 'provider': k} for k in rows], fetch=lambda a: rows[a['key']])
        store.refresh()
        with patch('token_tv.state.time.time', return_value=now):
            return store.snapshot()

    def test_the_arcade_page_draws_the_session_only_under_claudes_bar_and_keeps_each_side_apart(self):
        from token_tv.board_arcade import render_arcade
        with patch('time.time', return_value=1000), patch('token_tv.state.time.time', return_value=1000):
            base = render_arcade(self.arcade_snapshot())
            without = render_arcade(self.arcade_snapshot(session=False))
            claude_other = render_arcade(self.arcade_snapshot(claude_left=60))
            codex_other = render_arcade(self.arcade_snapshot(codex_left=80))
        self.assertEqual(base.size, (320, 240))

        def changed(a, b):
            return [(x, y) for y in range(240) for x in range(320) if a.getpixel((x, y)) != b.getpixel((x, y))]
        meter = changed(base, without)
        self.assertGreater(len(meter), 40)                                   # the two lines of five parts are drawn,
        self.assertTrue(all(204 <= x < 316 and 40 <= y < 58 for x, y in meter), 'the session left its place')
        self.assertTrue(all(x >= 200 for x, _ in changed(base, claude_other)))   # Claude's numbers stay on its side
        self.assertTrue(all(x < 120 for x, _ in changed(base, codex_other)))     # and Codex's on its own

    def test_the_dials_page_keeps_the_session_inside_claudes_dial_and_never_antialiases(self):
        import math
        from token_tv.board_dials import render_dials
        with patch('time.time', return_value=1000), patch('token_tv.state.time.time', return_value=1000):
            base = render_dials(self.arcade_snapshot())
            without = render_dials(self.arcade_snapshot(session=False))
            codex_other = render_dials(self.arcade_snapshot(codex_left=80))
        self.assertEqual(base.size, (320, 240))
        rings = [(x, y) for y in range(240) for x in range(320) if base.getpixel((x, y)) != without.getpixel((x, y))]
        self.assertGreater(len(rings), 100)                                  # the two thin rings are drawn...
        self.assertTrue(all(math.dist(p, (263, 185)) < 34 for p in rings))   # ...inside Claude's dial, in its ring zone
        other = [(x, y) for y in range(240) for x in range(320) if base.getpixel((x, y)) != codex_other.getpixel((x, y))]
        self.assertTrue(all(x < 120 for x, _ in other))                      # Codex's numbers stay in its own dial
        self.assertLess(len(base.getcolors(maxcolors=100000)), 900)          # flat bands, plus scan-line and vignette shades

    def test_the_anim_trailer_round_trips_and_malformed_ones_are_refused(self):
        import struct
        from token_tv import board_anim
        sprite = Image.new('RGBA', (3, 2), (0, 0, 0, 0))
        sprite.putpixel((1, 0), (255, 0, 0, 255))
        sprite.putpixel((2, 1), (255, 0, 255, 255))                       # exactly the key colour: must not vanish
        payload = board_anim.encode(
            [{'x': 10, 'y': 20, 'frames': [sprite, sprite], 'script': [(0, 0, 0), (1, 2, -1)], 'step_ms': 250}],
            [(4, 6, 0x1234, 0xFFFF, 0x0001)],
            {'x0': 0, 'y0': 1, 'x1': 100, 'y1': 50, 'period_ms': 7000, 'head': 0xFFFF, 'tail': 0x8410, 'length': 12, 'speed': 5})
        got = board_anim.decode(payload)
        self.assertEqual(got['stars'], [(4, 6, 0x1234, 0xFFFF, 0x0001)])
        self.assertEqual(got['meteor']['period_ms'], 7000)
        one = got['sprites'][0]
        self.assertEqual((one['w'], one['h'], one['x'], one['y'], one['step_ms']), (3, 2, 10, 20, 250))
        self.assertEqual(one['script'], [(0, 0, 0), (1, 2, -1)])
        self.assertEqual(one['frames'][0][0], board_anim.KEY)              # transparent
        self.assertEqual(one['frames'][0][1], 0xF800)                      # red
        self.assertNotEqual(one['frames'][0][5], board_anim.KEY)           # a real magenta is nudged, never see-through
        image = Image.new('RGB', (320, 240), (3, 8, 18))
        frame = rgb565_frame(image, anim=payload)
        self.assertEqual(frame_size(frame), (320, 240))
        self.assertEqual(frame[:len(rgb565_frame(image))], rgb565_frame(image))   # the pixels are the same
        self.assertIsNone(frame_size(frame[:-1]))                          # truncated
        self.assertIsNone(frame_size(frame + b'x'))                        # trailing junk
        base = 8 + 320 * 240 * 2
        lie = frame[:base + 4] + struct.pack('<I', len(payload) + 5) + frame[base + 8:]
        self.assertIsNone(frame_size(lie))                                 # the length lies
        small = Image.new('RGB', (16, 8), (3, 8, 18))
        self.assertIsNone(frame_size(rgb565_frame(small, anim=payload)))   # only full-screen pages animate
        with self.assertRaises(ValueError):
            board_anim.encode([{'x': 0, 'y': 0, 'frames': [sprite], 'script': [(3, 0, 0)], 'step_ms': 250}])

    def test_versus_goes_out_as_a_clean_background_plus_sprites_that_rebuild_the_static_page(self):
        import struct
        from token_tv import board_anim
        with patch('time.time', return_value=1000), patch('token_tv.state.time.time', return_value=1000):
            snapshot = self.arcade_snapshot()
            static = render_board_pages(snapshot)
            moving = render_board_pages(snapshot, anim=True)
        names = list(PAGE_NAMES)
        arcade = names.index('arcade')
        for number, (a, b) in enumerate(zip(static, moving)):
            if names[number] not in ('arcade', 'dials', 'code-forge', 'surf', 'paradise', 'countdown', 'cockpit'):
                self.assertEqual(a, b, names[number])                      # only pages with resident animation change
        self.assertEqual(frame_size(moving[arcade]), PAGE_SIZE)
        self.assertLessEqual(len(moving[arcade]), MAX_PAGE_BYTES)
        base = 8 + 320 * 240 * 2
        self.assertEqual(moving[arcade][base:base + 4], b'ANIM')
        payload = moving[arcade][base + 8:]
        spec = board_anim.decode(payload)
        self.assertEqual(len(spec['sprites']), 2)                          # composed city/fighter halves
        self.assertEqual(spec['meteor']['period_ms'],14000)
        self.assertGreaterEqual(len(spec['stars']),10)
        # putting the first pose of each sprite back (2x2 per pixel) gives exactly the static page
        words = list(struct.unpack('<76800H', moving[arcade][8:base]))
        for sprite in spec['sprites']:
            for sy in range(sprite['h']):
                for sx in range(sprite['w']):
                    word = sprite['frames'][0][sy * sprite['w'] + sx]
                    if word == board_anim.KEY:
                        continue
                    for dy in (0, 1):
                        for dx in (0, 1):
                            words[(sprite['y'] + sy * 2 + dy) * 320 + sprite['x'] + sx * 2 + dx] = word
        self.assertEqual(struct.pack('<76800H', *words), static[arcade][8:base])

    def test_the_board_is_told_how_many_pages_exist_so_a_deleted_one_is_not_cycled(self):
        board = BoardDisplay(self.serve(), TOKEN)
        FakeBoard.diagnostics = {'active': 8, 'anim': 1, 'waves': 1}
        board.ensure_paired()
        self.assertTrue(board.anim)
        self.assertTrue(board.waves)
        self.assertEqual(board.active, 8)
        board.set_active_pages(7)
        self.assertEqual(FakeBoard.options, ['pages=7'])
        self.assertEqual(board.active, 7)
        board.set_active_pages(7)                                          # nothing to say twice
        self.assertEqual(FakeBoard.options, ['pages=7'])
        with self.assertRaises(ValueError):
            board.configure(pages=9)
        older = BoardDisplay(self.serve(), TOKEN)                          # firmware without the setting
        older.ensure_paired()
        self.assertFalse(older.anim)
        self.assertFalse(older.waves)
        self.assertIsNone(older.active)
        older.set_active_pages(7)
        self.assertEqual(FakeBoard.options, [])                            # it is left alone

    def test_the_arcade_page_never_antialiases(self):
        import inspect
        import re
        from PIL import ImageColor
        from token_tv import board_arcade
        from token_tv.board_arcade import render_arcade
        with patch('time.time', return_value=1000), patch('token_tv.state.time.time', return_value=1000):
            image = render_arcade(self.arcade_snapshot())
        # Every pixel must be an explicitly authored flat colour, not a blended
        # edge. Richer architecture may add colours without adding antialiasing.
        palette={ImageColor.getrgb(c) for c in re.findall(r'#[0-9a-fA-F]{6}',inspect.getsource(board_arcade))}
        palette.update(ImageColor.getrgb(c) for c in (board_arcade.CODEX,board_arcade.CLAUDE))
        self.assertTrue({c for _,c in image.getcolors(maxcolors=100000)} <= palette)

    def test_a_flaring_star_has_its_whole_cross_free_and_crosses_never_touch(self):
        from token_tv import board_art
        from token_tv.board_art import FLARE, free_stars
        bare = board_art._backdrop().resize((board_art.W, board_art.H), Image.Resampling.LANCZOS).convert('RGB')
        stars = free_stars(bare)
        self.assertGreater(len(stars), 80)                               # a lively sky, not a handful
        self.assertLessEqual(len(stars), 128)                            # what the firmware can hold
        pixels = [(x + dx, y + dy) for x, y, _ in stars for dx, dy in FLARE]
        self.assertEqual(len(pixels), len(set(pixels)))                  # no two crosses share a pixel
        for x, y, _ in stars:
            self.assertTrue(2 <= x < board_art.W - 2 and 2 <= y < board_art.H - 2)   # the arms stay on screen
        x, y, _ = stars[0]
        covered = bare.copy()
        covered.putpixel((x + 2, y), (255, 0, 0))                        # something drawn on the tip of one arm
        self.assertNotIn((x, y), [(a, b) for a, b, _ in free_stars(covered)])

    def test_stars_are_only_sent_to_firmware_that_says_it_can_twinkle(self):
        from token_tv.board_pages import render_board_pages
        board = BoardDisplay(self.serve(), TOKEN)
        board.ensure_paired()
        self.assertFalse(board.stars)                                    # firmware 3 reports nothing
        FakeBoard.stars = True
        board.ensure_paired()
        self.assertTrue(board.stars)
        snapshot = {'accounts': {}}
        with patch('time.time', return_value=1000):
            still = render_board_pages(snapshot, stars=False)
            twinkling = render_board_pages(snapshot, stars=True)
        names = list(PAGE_NAMES)
        for number, (a, b) in enumerate(zip(still, twinkling)):
            with self.subTest(page=names[number]):
                if names[number] == 'cockpit':
                    self.assertGreater(len(b), len(a))                   # a trailer with the free stars
                    self.assertEqual(b[:len(a)], a)                      # on top of identical pixels
                    self.assertLessEqual(len(b), MAX_PAGE_BYTES)
                    self.assertIsNotNone(frame_size(b))
                else:
                    self.assertEqual(a, b)                               # faces never carry a trailer
        last = names.index('cockpit')
        board.upload(last, twinkling[last])                              # and the board accepts the long frame
        self.assertEqual(FakeBoard.pages[last], twinkling[last])

    def test_check_reports_uptime_restart_reason_and_touches_of_firmware_6(self):
        from token_tv.cli import main
        board = BoardDisplay(self.serve(), TOKEN)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({
                'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source_home': '/tmp/demo'}],
                'local_only': True, 'board_display': {'url': board.base_url, 'token': TOKEN}}))
            with patch('sys.stdout', new_callable=StringIO) as older:           # firmware 5 says none of it
                self.assertEqual(main(['board', '--config', str(path), '--check']), 0)
            self.assertNotIn('Up ', older.getvalue())
            FakeBoard.diagnostics = {'up': 3725, 'rst': 4, 'taps': 12, 'longs': 1, 'irq': 1, 'rssi': -61,
                                     'silent': 42, 'renews': 2, 'srest': 1, 'page': 3, 'info': 0}
            with patch('sys.stdout', new_callable=StringIO) as out:
                self.assertEqual(main(['board', '--config', str(path), '--check']), 0)
        for text in ('Up 62 min', 'crash', '12 taps', '1 long presses', '-61 dBm', 'last heard 42 s ago', 'renewed 2x', 'showing page 3'):
            self.assertIn(text, out.getvalue())

    def test_a_page_can_be_selected_and_a_bad_number_is_refused(self):
        board = BoardDisplay(self.serve(), TOKEN)
        board.show(0)
        self.assertEqual(FakeBoard.options, ['show=0'])
        with self.assertRaises(ValueError):
            board.show(9)
        self.assertEqual(FakeBoard.options, ['show=0'])

    def test_a_board_that_stored_something_else_is_reported(self):
        board = BoardDisplay(self.serve(), TOKEN)
        FakeBoard.corrupt = True
        with self.assertRaises(ValueError):
            board.upload(0, self.jpeg())

    def test_bad_pages_are_refused_before_anything_is_sent(self):
        board = BoardDisplay(self.serve(), TOKEN)
        for number, image in ((0, b''), (0, b'not a frame'), (0, b'TVF1' + b'x' * MAX_PAGE_BYTES), (9, self.jpeg())):
            with self.subTest(number=number, size=len(image)), self.assertRaises(ValueError):
                board.upload(number, image)
        self.assertEqual(FakeBoard.pages, {})

    def test_only_changed_pages_are_sent_and_a_failure_refreshes_everything(self):
        calls = []
        class Spy:
            fail = False
            def upload(self, number, image):
                if self.fail:
                    raise OSError('down')
                calls.append(('upload', number))
                return {'page': number}
            held = ''
            def ping(self):
                if self.fail:
                    raise OSError('down')
                calls.append(('ping',))
                return self.held
        spy, sent = Spy(), {}
        pages = [b'TVF1a', b'TVF1b', b'TVF1c']
        publish_pages(spy, pages, sent)
        self.assertEqual(calls, [('ping',), ('upload', 0), ('upload', 1), ('upload', 2)])
        calls.clear()
        publish_pages(spy, pages, sent)                                 # nothing changed: heartbeat only
        self.assertEqual(calls, [('ping',)])
        calls.clear()
        publish_pages(spy, [pages[0], b'TVF1B', pages[2]], sent)        # one page changed
        self.assertEqual(calls, [('ping',), ('upload', 1)])
        calls.clear()
        spy.held = '101000'                                             # the board lost page 1 (reflashed, formatted)
        publish_pages(spy, [pages[0], b'TVF1B', pages[2]], sent)
        self.assertEqual(calls, [('ping',), ('upload', 1)])
        calls.clear()
        spy.held = 'OK'                                                 # older firmware: digests alone decide
        publish_pages(spy, [pages[0], b'TVF1B', pages[2]], sent)
        self.assertEqual(calls, [('ping',)])
        spy.held = ''
        spy.fail = True
        with self.assertRaises(OSError):
            publish_pages(spy, [b'TVF1z', pages[1], pages[2]], sent)
        self.assertEqual(sent, {})                                      # forgotten: resend all when it is back
        spy.fail = False
        calls.clear()
        publish_pages(spy, pages, sent)
        self.assertEqual([c for c in calls if c[0] == 'upload'], [('upload', 0), ('upload', 1), ('upload', 2)])

    def test_the_network_guard_allows_the_board_and_nothing_else(self):
        policy = LocalPolicy('http://192.168.0.50', 'http://192.168.0.60')
        self.assertTrue(policy.allowed_host('192.168.0.50', 80))
        self.assertTrue(policy.allowed_host('192.168.0.60', 80))
        self.assertTrue(policy.allowed_host('127.0.0.1', 8787))
        for host, port in (('192.168.0.60', 8080), ('192.168.0.70', 80), ('8.8.8.8', 80), ('example.com', 80)):
            with self.subTest(host=host, port=port):
                self.assertFalse(policy.allowed_host(host, port))
        board_only = LocalPolicy(None, 'http://192.168.0.60:8080')
        self.assertTrue(board_only.allowed_host('192.168.0.60', 8080))
        self.assertFalse(board_only.allowed_host('192.168.0.60', 80))
        with self.assertRaises(ValueError):
            LocalPolicy('http://192.168.0.50', 'http://8.8.8.8')

    def test_config_accepts_a_valid_board_and_rejects_the_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            base = {'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source_home': '/tmp/demo-claude'}], 'local_only': True}
            for board, ok in (({'url': 'http://192.168.0.60', 'token': TOKEN}, True),
                              ({'url': 'http://8.8.8.8', 'token': TOKEN}, False),
                              ({'url': 'http://192.168.0.60', 'token': 'short'}, False),
                              ({'url': 'http://192.168.0.60'}, False), ('http://192.168.0.60', False)):
                with self.subTest(board=board):
                    path.write_text(json.dumps({**base, 'board_display': board}))
                    if ok:
                        self.assertEqual(load_config(path)['board_display']['token'], TOKEN)
                    else:
                        with self.assertRaises(ValueError):
                            load_config(path)

    def test_cli_saves_the_board_privately_and_keeps_everything_else(self):
        from token_tv.cli import main
        url = self.serve()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            original = {'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude',
                                      'source_home': '/tmp/demo-claude'}],
                        'local_only': True, 'display_style': 'orbit', 'device_url': 'http://192.168.0.50'}
            path.write_text(json.dumps(original))
            os.chmod(path, 0o644)
            with patch('sys.stdout', new_callable=StringIO) as out:     # a board already paired with this token
                code = main(['board', '--config', str(path), '--url', url, '--token', TOKEN.upper()])
            self.assertEqual(code, 0)
            self.assertNotIn(TOKEN, out.getvalue())                     # the token is never echoed
            saved = json.loads(path.read_text())
            self.assertEqual(saved['board_display'], {'url': url, 'token': TOKEN})
            self.assertEqual({k: v for k, v in saved.items() if k != 'board_display'}, original)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            before = path.read_text()
            with patch('sys.stderr', new_callable=StringIO):            # bad requests change nothing
                self.assertEqual(main(['board', '--config', str(path), '--url', 'http://8.8.8.8']), 1)
                self.assertEqual(main(['board', '--config', str(path), '--url', url, '--token', 'nope']), 1)
            self.assertEqual(path.read_text(), before)

    def test_pages_are_exact_frames_that_fit_the_board_and_show_unknown_as_dashes(self):
        import struct
        now = 1000

        def snapshot(with_session=True):
            windows = [{'label': 'WEEK', 'used_percent': 46, 'duration_minutes': 10080, 'resets_at': now + 5 * 86400}]
            if with_session:
                windows.insert(0, {'label': '5H', 'used_percent': 18, 'duration_minutes': 300, 'resets_at': now + 4 * 3600})
            rows = {}
            for provider in ('claude', 'codex'):
                account = {'key': provider, 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo'}
                record = {'source': provider + '_official_cli', 'fetched_at': now, 'stale': False,
                          'ordinary_usage_allowed': True, 'windows': windows if provider == 'claude' else windows[-1:]}
                rows[provider] = local_row(account, record, now=now)
            store = UsageStore([{'key': k, 'alias': k, 'provider': k} for k in rows], fetch=lambda a: rows[a['key']])
            store.refresh()
            with patch('token_tv.state.time.time', return_value=now):
                return store.snapshot()
        with patch('time.time', return_value=now):
            with_session = render_board_pages(snapshot(True))
            without = render_board_pages(snapshot(False))
            unknown = render_board_pages({'accounts': {}})
        self.assertEqual(PAGE_NAMES, ('game-boy', 'paradise', 'code-forge', 'surf', 'dials', 'arcade',
                                      'cockpit', 'countdown'))
        self.assertEqual(len(with_session), len(PAGE_NAMES))
        sizes = [frame_size(frame) for frame in with_session + unknown]
        self.assertNotIn(None, sizes)                                   # every frame is well formed
        for frame in with_session + unknown:
            self.assertLessEqual(len(frame), MAX_PAGE_BYTES)
        self.assertEqual(set(sizes), {PAGE_SIZE})                       # every page fills the screen: no black margins
        self.assertEqual(frame_size(b'TVF1' + struct.pack('<HH', 240, 240) + b'x'), None)   # truncated
        self.assertEqual(frame_size(b'JPEG' + b'\0' * 20), None)

        # Exact pixels: decoding a frame gives back the rendered image to the bit (RGB565).
        from token_tv.themes import RENDERERS as THEMES
        source = THEMES['retro'](snapshot(True)).convert('RGB')
        frame = rgb565_frame(source)
        words = struct.unpack(f'<{240 * 240}H', frame[8:])
        expected = [((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3) for r, g, b in source.getdata()]
        self.assertEqual(list(words), expected)

        for number, name in enumerate(PAGE_NAMES):                      # every page draws Claude's session bars...
            with self.subTest(page=name):
                self.assertNotEqual(with_session[number], without[number])   # ...only from a fresh reading
                self.assertNotEqual(with_session[number], unknown[number])


    def test_pixel_retro_fills_the_wide_screen_with_a_session_card_and_game_boy_is_dmg_green(self):
        import struct
        now = 1000

        def pages(with_session):
            windows = [{'label': 'WEEK', 'used_percent': 46, 'duration_minutes': 10080, 'resets_at': now + 5 * 86400}]
            if with_session:
                windows.insert(0, {'label': '5H', 'used_percent': 18, 'duration_minutes': 300, 'resets_at': now + 4 * 3600})
            rows = {}
            for provider in ('claude', 'codex'):
                account = {'key': provider, 'alias': provider.upper(), 'provider': provider, 'source_home': '/demo'}
                record = {'source': provider + '_official_cli', 'fetched_at': now, 'stale': False,
                          'ordinary_usage_allowed': True, 'windows': windows if provider == 'claude' else windows[-1:]}
                rows[provider] = local_row(account, record, now=now)
            store = UsageStore([{'key': k, 'alias': k, 'provider': k} for k in rows], fetch=lambda a: rows[a['key']])
            store.refresh()
            from token_tv.themes import RENDERERS
            from token_tv.personal_faces import RENDERERS as PERSONAL
            from token_tv.board_pages import LCD_GRID
            with patch('token_tv.state.time.time', return_value=now), patch('time.time', return_value=now):
                snapshot = store.snapshot()
                # Pixel Retro left the board's page list on 2026-10-13, but the face is still the clock's
                # Pocket remains available locally after PARADISE takes its board slot.
                pocket = PERSONAL['game-boy-pocket'](snapshot, screen=PAGE_SIZE,
                                                     grid=LCD_GRID['game-boy-pocket'])
                return (render_board_pages(snapshot), rgb565_frame(RENDERERS['retro'](snapshot, screen=PAGE_SIZE)),
                        rgb565_frame(pocket))
        (known, known_retro, known_pocket), (unknown, unknown_retro, _) = pages(True), pages(False)

        def rows_of(frame):
            width, height = struct.unpack('<HH', frame[4:8])
            return [frame[8 + y * width * 2: 8 + (y + 1) * width * 2] for y in range(height)]
        first, second = rows_of(known_retro), rows_of(unknown_retro)
        changed = [y for y in range(240) if first[y] != second[y]]
        self.assertTrue(changed)
        self.assertGreaterEqual(min(changed), 161)       # only the third card carries the session...
        self.assertLess(max(changed), 238)               # ...and it reaches the bottom: no empty band below
        # The three cards use the whole height: the first and last rows of the screen are not background.
        self.assertTrue(any(first[y] != first[0] for y in range(236, 240)) or first[237] != first[0])

        # The LCD remains visibly green; the new physical casing is deliberately grey.
        offset = 8 + (40 * 320 + 26) * 2  # LCD interior; outer pixels now belong to the grey casing
        word = struct.unpack('<H', known[0][offset:offset + 2])[0]
        red, green, blue = ((word >> 11) & 31) * 255 // 31, ((word >> 5) & 63) * 255 // 63, (word & 31) * 255 // 31
        self.assertTrue(green > red + 20 and green > blue + 100, (red, green, blue))   # #afc93f: still clearly green, never grey
        pocket = struct.unpack('<H', known_pocket[8:10])[0]                              # the preserved pocket is green too...
        pr, pg, pb = ((pocket >> 11) & 31) * 255 // 31, ((pocket >> 5) & 63) * 255 // 63, (pocket & 31) * 255 // 31
        self.assertTrue(pg > pr + 20 and pg > pb + 100, (pr, pg, pb))                    # never grey
        self.assertNotEqual(word, pocket)                                                # ...in its own, softer shade


if __name__ == '__main__':
    unittest.main()
