import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlparse

from token_tv.device import PhotoDisplay


class UltraTests(unittest.TestCase):
    def setUp(self):
        self.state = {'theme': 1, 'autoplay': 1, 'i_i': 5, 'sw_en': '1'}
        self.calls = []
        self.model = 'SmallTV-Ultra'
        self.free = 1000000
        self.images = {}
        self.corrupt_upload = False
        self.display = PhotoDisplay('http://127.0.0.1')
        self.mock = patch.object(self.display, 'request', side_effect=self.request)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def request(self, path, data=None, headers=None):
        self.calls.append((path, data))
        if path == '/theme/list':
            raise HTTPError(path, 404, 'Not found', {}, None)
        if path == '/v.json':
            value = {'m': self.model, 'v': 'Ultra-V9.0.50'}
        elif path == '/app.json':
            value = {'theme': self.state['theme']}
        elif path == '/album.json':
            value = {key: self.state[key] for key in ('autoplay', 'i_i')}
        elif path == '/theme_list.json':
            value = {'sw_en': self.state['sw_en'], 'list': '1,0,0', 'sw_i': '30'}
        elif path == '/space.json':
            value = {'free': self.free}
        elif path.startswith('/set?'):
            values = parse_qs(urlparse(path).query)
            for key in ('theme', 'autoplay', 'i_i'):
                if key in values:
                    self.state[key] = int(values[key][0])
            if 'sw_en' in values:
                self.state['sw_en'] = values['sw_en'][0]
            return 200, b'OK'
        elif path == '/doUpload?dir=/image/':
            name = data.partition(b'filename="')[2].split(b'"', 1)[0].decode()
            image = data.split(b'\r\n\r\n', 1)[1].rsplit(b'\r\n--', 1)[0]
            self.images[name] = b'OLD-IMAGE' if self.corrupt_upload else image
            return 200, b'OK'
        elif path.startswith('/image/'):
            return 200, self.images[unquote(path[7:])]
        else:
            self.fail('Unexpected endpoint: ' + path)
        return 200, json.dumps(value).encode()

    def test_detect_upload_and_restore_preserve_original_settings(self):
        initial = dict(self.state)
        original = self.display.capture()
        self.display.upload('tokentv.jpg', b'JPEG')
        self.display.activate(original)
        self.assertEqual(self.state['theme'], 3)
        self.assertEqual(self.state['autoplay'], 0)
        self.assertEqual(self.state['sw_en'], '0')
        # Restore must work in a fresh process too, before any capture.
        fresh = PhotoDisplay('http://127.0.0.1')
        with patch.object(fresh, 'request', side_effect=self.request):
            fresh.restore(original)
        self.assertEqual(self.state, initial)
        uploads = [body for path, body in self.calls if path.startswith('/doUpload')]
        self.assertEqual(len(uploads), 1)
        self.assertIn(b'filename="tokentv.jpg"', uploads[0])
        self.assertFalse(any('/delete' in path or '/update' in path for path, _ in self.calls))

    def test_unknown_model_is_rejected_without_mutation(self):
        self.model = 'OtherTV'
        with self.assertRaises(ValueError):
            self.display.capture()
        self.assertFalse(any('/set?' in path for path, _ in self.calls))

    def test_active_photo_cannot_be_backed_up_so_refuse_to_replace_it(self):
        self.state['theme'] = 3
        with self.assertRaises(ValueError):
            self.display.capture()

    def test_insufficient_space_does_not_delete_photos_or_upload(self):
        self.display.capture()
        self.free = 100
        with self.assertRaises(ValueError):
            self.display.upload('tokentv.jpg', b'JPEG')
        self.assertFalse(any('/doUpload' in path or '/delete' in path for path, _ in self.calls))

    def test_acknowledged_upload_is_read_back_before_success(self):
        self.display.capture()
        self.display.upload('Game Boy verde.jpg', b'EXACT-JPEG')
        self.assertIn(('/image/Game%20Boy%20verde.jpg', None), self.calls)

    def test_http_200_with_an_old_image_is_not_success(self):
        self.display.capture()
        self.corrupt_upload = True
        with self.assertRaisesRegex(ValueError, 'verification'):
            self.display.upload('tokentv.jpg', b'NEW-JPEG')
        self.assertFalse(any('/delete' in path for path, _ in self.calls))

    def test_named_local_faces_can_be_uploaded_without_selecting_or_deleting(self):
        self.display.capture()
        names = ('Game Boy verde.jpg', 'Game Boy gris.jpg', 'Pixel Retro.jpg',
                 'Terminal Ambar.jpg', 'Orbit.jpg')
        for name in names:
            self.display.upload(name, b'JPEG')
        uploads = [body for path, body in self.calls if path.startswith('/doUpload')]
        self.assertEqual(len(uploads), 5)
        for name, body in zip(names, uploads):
            self.assertIn(('filename="' + name + '"').encode(), body)
        self.assertFalse(any('/set?' in path or '/delete' in path for path, _ in self.calls))
        with self.assertRaises(ValueError):
            self.display.upload('../another.jpg', b'JPEG')

    def test_named_face_activation_preserves_clock_rotation(self):
        original = self.display.capture()
        self.display.activate(original, 'Pixel Retro.jpg', rotation_seconds=30)
        selected = [parse_qs(urlparse(path).query) for path, _ in self.calls
                    if path.startswith('/set?') and 'img=' in path]
        self.assertEqual(selected[-1]['img'], ['/image/Pixel Retro.jpg'])
        self.assertEqual(self.state['sw_en'], '1')

    def test_rotation_uses_only_original_theme_and_quota_and_can_restore(self):
        initial = dict(self.state)
        original = self.display.capture()
        self.display.activate(original, rotation_seconds=30)
        rotations = [parse_qs(urlparse(path).query) for path, _ in self.calls
                     if path.startswith('/set?') and 'theme_list=' in path]
        self.assertEqual(rotations[-1]['theme_list'], ['1,0,1'])
        self.assertEqual(rotations[-1]['sw_en'], ['1'])
        self.assertEqual(rotations[-1]['theme_interval'], ['30'])
        self.assertEqual(self.state['autoplay'], 0)
        self.display.restore(original)
        self.assertEqual(self.state, initial)
        self.assertEqual(original['rotation']['list'], '1,0,0')

    def test_invalid_rotation_does_not_modify_the_clock(self):
        original = self.display.capture()
        for bad in (-1, 1, True, '30', 3601):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.display.activate(original, rotation_seconds=bad)
        self.assertFalse(any('/set?' in path for path, _ in self.calls))
