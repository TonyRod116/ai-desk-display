"""The app's update, seen from the PC: what the server says about the APK on offer (version, size, SHA-256 measured on the file itself).

Fictional files in temporary folders only; the real APK and its folder are never touched.
"""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from token_tv import tablet_server as server
from token_tv.tablet_server import Auth, Handler, TabletServer

APK = b'PK\x03\x04 a fictional package'


def lay_out(directory, apk=APK, meta=None, raw_meta=None):
    folder = Path(directory) / 'app'
    folder.mkdir(parents=True, exist_ok=True)
    if apk is not None:
        (folder / server.APK_NAME).write_bytes(apk)
    if raw_meta is not None:
        (folder / (server.APK_NAME + '.json')).write_bytes(raw_meta)
    elif meta is not None:
        (folder / (server.APK_NAME + '.json')).write_text(json.dumps(meta), encoding='utf-8')
    return folder


def good_meta(code=7, apk=APK):
    return {'version_name': f'1.{code}', 'version_code': code, 'size': len(apk), 'sha256': hashlib.sha256(apk).hexdigest()}


class ApkInfoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        server._APK['key'] = None

    def test_no_file_means_no_app(self):
        self.assertIs(server.apk_info(self.tmp.name), False)
        lay_out(self.tmp.name, apk=None, meta=good_meta())
        self.assertIs(server.apk_info(self.tmp.name), False)

    def test_the_version_comes_from_the_build_and_the_hash_from_the_file(self):
        lay_out(self.tmp.name, meta=good_meta(7))
        self.assertEqual(server.apk_info(self.tmp.name), {'version_code': 7, 'version_name': '1.7', 'size': len(APK), 'sha256': hashlib.sha256(APK).hexdigest()})

    def test_a_version_that_does_not_belong_to_this_file_is_not_believed(self):
        wrong_hash = {**good_meta(7), 'sha256': 'f' * 64}
        for meta in (wrong_hash, {**good_meta(7), 'version_name': '9.9'}, {**good_meta(7), 'version_code': True},
                     {**good_meta(7), 'version_code': -3, 'version_name': '1.-3'}, {**good_meta(7), 'version_code': 10 ** 7, 'version_name': '1.10000000'}):
            with self.subTest(meta=meta):
                server._APK['key'] = None
                lay_out(self.tmp.name, meta=meta)
                self.assertEqual(set(server.apk_info(self.tmp.name)), {'size', 'sha256'})     # still an APK to download, but no version to compare

    def test_a_broken_or_missing_sidecar_still_offers_the_download(self):
        for raw in (None, b'not json', b'[1]', b'\xff\xfe'):
            with self.subTest(raw=raw):
                server._APK['key'] = None
                lay_out(self.tmp.name, raw_meta=raw) if raw is not None else lay_out(self.tmp.name)
                self.assertEqual(set(server.apk_info(self.tmp.name)), {'size', 'sha256'})

    def test_a_changed_file_is_measured_again(self):
        lay_out(self.tmp.name, meta=good_meta(7))
        first = server.apk_info(self.tmp.name)
        new = APK + b' newer'
        lay_out(self.tmp.name, apk=new, meta=good_meta(8, new))
        second = server.apk_info(self.tmp.name)
        self.assertEqual((first['version_code'], second['version_code']), (7, 8))
        self.assertEqual(second['sha256'], hashlib.sha256(new).hexdigest())

    def test_a_file_too_big_for_the_in_app_update_has_no_hash_for_it(self):
        lay_out(self.tmp.name, apk=b'x' * (server.APK_MAX_BYTES + 1))
        self.assertIs(server.apk_info(self.tmp.name), True)        # the browser download may still be offered, the app update may not


class StatusTests(unittest.TestCase):
    def test_the_status_carries_the_app_info_for_a_signed_in_page_only(self):
        with tempfile.TemporaryDirectory() as temp:
            server._APK['key'] = None
            lay_out(temp, meta=good_meta(5))
            auth = Auth(temp)
            self.assertTrue(auth.set_password('fictional-password'))

            class Feeds:
                def status(self):
                    return {'providers': {}, 'metrics': None, 'quota_connected': False}
            tablet = TabletServer(('127.0.0.1', 0), Handler, mode='lan', auth=auth, feeds=Feeds(), private=temp, lan='127.0.0.1', lan_port=8667, fingerprint='EXAMPLE')
            threading.Thread(target=tablet.serve_forever, daemon=True).start()
            self.addCleanup(tablet.server_close)
            self.addCleanup(tablet.shutdown)

            def call(method, path, headers=None, body=None):
                conn = http.client.HTTPConnection('127.0.0.1', tablet.server_port, timeout=3)
                conn.request(method, path, body=body, headers=headers or {})
                response = conn.getresponse()
                out = (response.status, dict(response.getheaders()), response.read())
                conn.close()
                return out
            self.assertEqual(call('GET', '/api/status')[0], 401)
            status, headers, _ = call('POST', '/api/login', {'Content-Type': 'application/json', 'Origin': 'https://127.0.0.1:' + str(tablet.server_port)},
                                      json.dumps({'password': 'fictional-password'}))
            self.assertEqual(status, 200)
            cookie = headers['Set-Cookie'].split(';', 1)[0]
            status, _, raw = call('GET', '/api/status', {'Cookie': cookie})
            app = json.loads(raw)['app']
            self.assertEqual((status, app['version_code'], app['version_name'], app['sha256']), (200, 5, '1.5', hashlib.sha256(APK).hexdigest()))
            status, _, apk = call('GET', '/app/ai-desk-tablet.apk', {'Cookie': cookie})
            self.assertEqual((status, hashlib.sha256(apk).hexdigest()), (200, app['sha256']))     # what the app downloads is what the status promised
            self.assertEqual(call('GET', '/app/ai-desk-tablet.apk')[0], 303)                       # and only a signed-in page may fetch it


if __name__ == '__main__':
    unittest.main()
