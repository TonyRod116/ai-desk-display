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
from urllib.parse import parse_qs, urlparse

from token_tv.device import ALBUM_FACES, PhotoDisplay
from token_tv.live import clock_enabled
from token_tv.sources import load_config

OURS = list(ALBUM_FACES.values()) + ['tokentv.jpg']
THEIRS = ['ezgif-1-795e37b516.jpg', 'spaceman.gif', 'My holiday.jpg']


class FakeClock(BaseHTTPRequestHandler):
    """A Geek TV Ultra: the file list page, delete and the settings endpoint of its web UI."""
    files = []
    settings = []
    deleted = []

    def log_message(self, *args):
        pass

    def reply(self, body, status=200):
        data = body.encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/filelist':
            rows = ''.join(f"<tr><td>{i}</td><td><a href='/image/{n}'>{n}</a></td></tr>" for i, n in enumerate(self.files))
            return self.reply(f"<table id='list'><tbody>{rows}</tbody></table>")
        if url.path == '/delete':
            name = parse_qs(url.query)['file'][0]
            self.deleted.append(name)
            type(self).files = [n for n in self.files if '/image/' + n != name]
            return self.reply('OK')
        if url.path == '/set':
            self.settings.append(url.query)
            return self.reply('OK')
        self.reply('', 404)


class ClockTests(unittest.TestCase):
    def serve(self):
        FakeClock.files, FakeClock.settings, FakeClock.deleted = OURS + THEIRS, [], []
        server = ThreadingHTTPServer(('127.0.0.1', 0), FakeClock)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        return f'http://127.0.0.1:{server.server_port}'

    def config(self, directory, url, **extra):
        path = Path(directory) / 'config.json'
        data = {'accounts': [{'key': 'claude_a', 'alias': 'CLAUDE A', 'provider': 'claude', 'source_home': '/tmp/demo'}],
                'local_only': True, 'device_url': url, **extra}
        path.write_text(json.dumps(data))
        state = Path(directory) / 'state'
        state.mkdir()
        (state / 'display-original.json').write_text(json.dumps({
            'profile': 'ultra', 'theme': 1, 'autoplay': 0, 'image_interval': 5, 'device_url': url,
            'rotation': {'list': '0,0,0,0,0,0,0', 'sw_en': '0', 'sw_i': '30'}}))
        return path

    def test_only_files_tokentv_created_can_be_deleted(self):
        device = PhotoDisplay(self.serve())
        self.assertEqual(sorted(device.listing()), sorted(OURS + THEIRS))
        for name in THEIRS + ['../app.json', '/image/tokentv.jpg', '']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                device.delete_own(name)
        self.assertEqual(FakeClock.deleted, [])                       # nothing of the reference was even requested
        device.delete_own('Orbit.jpg')
        self.assertEqual(FakeClock.deleted, ['/image/Orbit.jpg'])

    def test_the_clock_can_be_switched_off_and_the_service_honours_it(self):
        from token_tv.cli import main
        self.assertTrue(clock_enabled({'device_url': 'http://192.168.0.50'}))
        self.assertFalse(clock_enabled({'device_url': 'http://192.168.0.50', 'display_enabled': False}))
        self.assertFalse(clock_enabled({}))                           # no clock configured
        with tempfile.TemporaryDirectory() as directory:
            path = self.config(directory, self.serve())
            os.chmod(path, 0o644)
            before = json.loads(path.read_text())
            with patch('sys.stdout', new_callable=StringIO):
                self.assertEqual(main(['clock', '--config', str(path), '--off']), 0)
            saved = json.loads(path.read_text())
            self.assertIs(saved['display_enabled'], False)
            self.assertEqual({k: v for k, v in saved.items() if k != 'display_enabled'}, before)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse(clock_enabled(load_config(path)))
            bad = json.loads(path.read_text())
            bad['display_enabled'] = 'no'
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_clean_restores_the_clock_and_removes_only_our_files(self):
        from token_tv.cli import main
        with tempfile.TemporaryDirectory() as directory:
            path = self.config(directory, self.serve(), display_enabled=True)
            with patch('sys.stderr', new_callable=StringIO) as err:   # refused while the service would put them back
                self.assertEqual(main(['clock', '--config', str(path), '--clean']), 1)
            self.assertIn('--off', err.getvalue())
            self.assertEqual(FakeClock.deleted, [])
            main_args = ['clock', '--config', str(path)]
            with patch('sys.stdout', new_callable=StringIO):
                self.assertEqual(main(main_args + ['--off']), 0)
            with patch('sys.stdout', new_callable=StringIO) as out:
                self.assertEqual(main(main_args + ['--clean']), 0)
            self.assertEqual(sorted(FakeClock.deleted), sorted('/image/' + n for n in OURS))
            self.assertEqual(sorted(FakeClock.files), sorted(THEIRS))  # everything of the reference is still there
            self.assertIn('Left untouched: 3', out.getvalue())
            joined = ' '.join(FakeClock.settings)
            self.assertIn('theme=1', joined)                          # its original theme is selected again
            self.assertIn('sw_en=0', joined)                          # and the 30 s rotation is off


if __name__ == '__main__':
    unittest.main()
