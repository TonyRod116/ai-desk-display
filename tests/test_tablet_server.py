import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from token_tv.tablet_server import Auth, Feeds, Handler, TabletServer, clean_report


class FakeFeeds:
    def status(self):
        return {'providers': {'codex': {'weekly': {'remaining': 42}}}, 'metrics': {'disks': []}}


class FeedTests(unittest.TestCase):
    def test_offline_diagnostics_keep_only_bounded_progress_not_readings_or_paths(self):
        result = clean_report({'why':'tick', 'offline_state':'ready', 'offline_ready':True, 'offline_done':79,
                               'offline_count':79, 'offline_bytes':1000, 'offline_total':1000,
                               'providers':{'claude':{'credits':123}}, 'path':'private', 'cookie':'private'})
        self.assertEqual(set(result), {'why','offline_state','offline_ready','offline_done','offline_count','offline_bytes','offline_total'})
        self.assertEqual(clean_report({'why':'tick', 'offline_count':True, 'offline_done':2.5,
                                       'offline_total':2**40, 'offline_state':'unknown-private'}), {'why':'tick'})

    def test_old_or_unavailable_sources_do_not_stay_visible(self):
        feeds = Feeds()
        feeds.quota = {'providers': {'codex': {'weekly': {'remaining': 42}}}}
        feeds.hardware = {'disks': [{'name': 'C:'}]}
        feeds.quota_at = feeds.hardware_at = 0
        status = feeds.status()
        self.assertFalse(status['quota_connected'])
        self.assertEqual(status['providers'], {})
        self.assertIsNone(status['metrics'])


class SetupDiagnosticsTests(unittest.TestCase):
    def test_local_setup_shows_only_sensor_availability(self):
        class LocalFeeds:
            def status(self):
                return {'providers': {'codex': {'secret': 'must-not-leak'}},
                        'metrics': {'cpu_percent': 50, 'cpu_temp_c': 73,
                                    'memory': {'total': 100, 'free': 25},
                                    'disks': [{'name': 'C:'}, {'name': 'D:'}],
                                    'gpus': [{'temp_c': 60}]}}

        with tempfile.TemporaryDirectory() as temp:
            server = TabletServer(('127.0.0.1', 0), Handler, mode='setup', auth=Auth(temp),
                                  feeds=LocalFeeds(), private=temp, lan='127.0.0.1',
                                  lan_port=8667, fingerprint='EXAMPLE')
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                conn.request('GET', '/api/setup')
                response = conn.getresponse()
                raw = response.read()
                result = json.loads(raw)
                self.assertEqual(response.status, 200)
                self.assertEqual(result['hardware'], {'cpu_load': True, 'cpu_temp': True,
                                 'memory': True, 'disks': 2, 'gpu': True})
                self.assertNotIn(b'must-not-leak', raw)
                self.assertNotIn(b'C:', raw)
                conn.close()
            finally:
                server.shutdown()
                server.server_close()


class TabletServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = Auth(self.tmp.name)
        self.assertTrue(self.auth.set_password('fictional-password'))
        self.server = TabletServer(('127.0.0.1', 0), Handler, mode='lan', auth=self.auth,
                                   feeds=FakeFeeds(), private=self.tmp.name, lan='127.0.0.1',
                                   lan_port=8667, fingerprint='EXAMPLE')
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        headers = dict(headers or {})
        if body is not None:
            body = json.dumps(body)
            headers.setdefault('Content-Type', 'application/json')
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        out = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return out

    def login(self):
        origin = 'https://127.0.0.1:' + str(self.port)
        status, headers, _ = self.request('POST', '/api/login',
                                           {'password': 'fictional-password'}, {'Origin': origin})
        self.assertEqual(status, 200)
        self.assertIn('Secure; HttpOnly; SameSite=Strict', headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';', 1)[0]

    def test_offline_inventory_is_authenticated_same_origin_and_never_contains_readings(self):
        self.assertEqual(self.request('GET', '/api/offline')[0], 401)
        headers = {'Cookie': self.login()}
        self.assertEqual(self.request('GET', '/api/offline', headers={**headers, 'Origin':'https://evil.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/api/offline', headers={**headers, 'Sec-Fetch-Site':'cross-site'})[0], 403)
        status, _, raw = self.request('GET', '/api/offline', headers=headers)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertEqual({x['path'] for x in data['files']}, {'/api/scenes', '/api/photos'})
        for private in (b'providers', b'metrics', b'Cookie', b'password'):
            self.assertNotIn(private, raw)

    def test_memory_action_requires_login_origin_and_an_empty_body(self):
        class Memory:
            calls = 0
            def release(self): self.calls += 1; return {'state':'nothing','apps':[],'before':None,'after':None}
        memory=Memory();self.server.memory=memory
        origin={'Origin':'https://127.0.0.1:'+str(self.port)}
        self.assertEqual(self.request('POST','/api/memory/release',{},origin)[0],401)
        cookie=self.login();headers={**origin,'Cookie':cookie}
        self.assertEqual(self.request('POST','/api/memory/release',{'pid':123},headers)[0],400)
        self.assertEqual(self.request('POST','/api/memory/release',{}, {**headers,'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(memory.calls,0)
        status,_,body=self.request('POST','/api/memory/release',{},headers)
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['state'],'nothing');self.assertEqual(memory.calls,1)

    def test_memory_action_reports_busy_and_uncertain_results_without_leaking_errors(self):
        class Memory:
            value = {'state':'cooldown','seconds':120}
            def release(self):
                if self.value == 'raise': raise RuntimeError('PRIVATE ERROR')
                return self.value
        memory=Memory();self.server.memory=memory
        headers={'Cookie':self.login(),'Origin':'https://127.0.0.1:'+str(self.port)}
        self.assertEqual(self.request('POST','/api/memory/release',{},headers)[0],429)
        memory.value={'state':'busy'}
        self.assertEqual(self.request('POST','/api/memory/release',{},headers)[0],409)
        memory.value='raise'
        status,_,body=self.request('POST','/api/memory/release',{},headers)
        self.assertEqual(status,502);self.assertEqual(json.loads(body),{'state':'unknown'});self.assertNotIn(b'PRIVATE',body)

    def test_board_preview_requires_login_and_same_origin(self):
        class Board:
            calls = []
            def preview(self, index):
                self.calls.append(index)
                return b'fictional-png' if index == 3 else None
        board = Board(); self.server.board = board
        self.assertEqual(self.request('GET', '/api/board/preview/3.png')[0], 401)
        self.assertEqual(board.calls, [])
        cookie = self.login()
        headers = {'Cookie': cookie}
        status, response, body = self.request('GET', '/api/board/preview/3.png', headers=headers)
        self.assertEqual((status, response['Content-Type'], body), (200, 'image/png', b'fictional-png'))
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(board.calls, [3])
        self.assertEqual(self.request('GET', '/api/board/preview/8.png', headers=headers)[0], 404)
        self.assertEqual(self.request('GET', '/api/board/preview/3.png', headers={**headers, 'Sec-Fetch-Site':'cross-site'})[0], 403)
        self.assertEqual(self.request('GET', '/api/board/preview/3.png', headers={**headers, 'Origin':'https://attacker.invalid'})[0], 403)
        self.assertEqual(board.calls, [3])

    def test_public_access_never_exposes_data(self):
        status, _, body = self.request('GET', '/api/status')
        self.assertEqual(status, 401)
        self.assertNotIn(b'providers', body)
        status, headers, _ = self.request('GET', '/')
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/login')
        self.assertEqual(self.request('GET', '/assets/city.png')[0], 303)
        self.assertEqual(self.request('GET', '/api/scenes')[0], 401)
        self.assertEqual(self.request('GET', '/assets/scene-neon-city.webp')[0], 303)

    def test_scene_catalog_only_lists_prepared_allowlisted_art(self):
        root = Path(self.tmp.name)
        for name in ('scene-surf.webp', 'thumb-surf.webp', 'scene-secret.webp', 'thumb-secret.webp', 'scene-neon-city.webp'):
            (root / name).write_bytes(b'fictional-image')
        cookie = self.login()
        status, _, body = self.request('GET', '/api/scenes', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'scenes': ['surf'], 'info': {}})
        self.assertEqual(self.request('GET', '/assets/scene-secret.webp', headers={'Cookie': cookie})[0], 404)

    def prepare(self, **files):
        root = Path(self.tmp.name)
        for name, content in files.items():
            (root / name.replace('__', '.').replace('_', '-')).write_bytes(content)   # scene_surf__webm -> scene-surf.webm
        return root

    def manifest(self, scenes):
        (Path(self.tmp.name) / 'scenes.json').write_text(json.dumps({'version': 2, 'scenes': scenes}))

    def scenes(self):
        status, _, body = self.request('GET', '/api/scenes', headers={'Cookie': self.login()})
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_manifest_describes_how_to_show_each_prepared_scene(self):
        self.prepare(scene_paradise__webm=b'v' * 100, thumb_paradise__webp=b't', scene_paradise__jpg=b'j' * 10,
                     scene_surf__webm=b'v' * 100, thumb_surf__webp=b't')
        self.manifest({
            'paradise': {'look': 'photo', 'media': {'kind': 'video', 'file': 'scene-paradise.webm', 'width': 768, 'height': 960,
                                                    'fps': 30, 'loop_seconds': 5.25},
                         'still': 'scene-paradise.jpg', 'focus': [.5, .55], 'rate': .8},
            'surf': {'look': 'crt', 'media': {'kind': 'video', 'file': 'scene-surf.webm', 'width': 640, 'height': 480}}})
        result = self.scenes()
        self.assertEqual(result['scenes'], ['paradise', 'surf'])
        self.assertEqual(result['info']['paradise'], {
            'look': 'photo', 'focus': [.5, .55], 'rate': .8, 'still': '/assets/scene-paradise.jpg',
            'media': {'kind': 'video', 'url': '/assets/scene-paradise.webm', 'width': 768, 'height': 960, 'fps': 30, 'loop_seconds': 5.25}})
        self.assertEqual(result['info']['surf'], {'look': 'crt', 'focus': [.5, .5], 'rate': 1,
                         'media': {'kind': 'video', 'url': '/assets/scene-surf.webm', 'width': 640, 'height': 480}})

    def test_manifest_entries_that_are_wrong_are_dropped_not_trusted(self):
        self.prepare(scene_surf__webm=b'v' * 100, thumb_surf__webp=b't', scene_neon_city__webp=b'i', thumb_neon_city__webp=b't')
        good = {'kind': 'video', 'file': 'scene-surf.webm', 'width': 640, 'height': 480}
        bad = {
            'unknown look': {'look': 'neon', 'media': good},
            'other scene file': {'look': 'crt', 'media': dict(good, file='scene-neon-city.webm')},
            'path': {'look': 'crt', 'media': dict(good, file='../scenes.json')},
            'size': {'look': 'crt', 'media': dict(good, width=10**6)},
            'fps': {'look': 'crt', 'media': dict(good, fps=True)},
            'focus': {'look': 'crt', 'media': good, 'focus': [2, 0]},
            'rate': {'look': 'crt', 'media': good, 'rate': 99},
            'still': {'look': 'crt', 'media': good, 'still': 'scene-surf.mp4'},
            'kind': {'look': 'crt', 'media': dict(good, kind='image')},
            'missing file': {'look': 'crt', 'media': dict(good, file='scene-surf.png')},
        }
        for label, entry in bad.items():
            with self.subTest(label):
                self.manifest({'surf': entry})
                self.assertEqual(self.scenes()['info'], {})
        (Path(self.tmp.name) / 'scenes.json').write_text('{not json')
        self.assertEqual(self.scenes(), {'scenes': ['surf', 'neon-city'], 'info': {}})
        (Path(self.tmp.name) / 'scenes.json').write_text(json.dumps({'version': 1, 'scenes': {'surf': {}}}))
        self.assertEqual(self.scenes()['info'], {})

    def test_express_daypart_variants_are_checked_and_remain_hidden_choices(self):
        self.prepare(scene_infinite_express__webm=b'v', thumb_infinite_express__webp=b't',
                     scene_infinite_express_day__webm=b'd', scene_infinite_express_day__jpg=b'j')
        basic = {'look': 'photo', 'media': {'kind': 'video', 'file': 'scene-infinite-express.webm', 'width': 672, 'height': 900}}
        day = {'look': 'photo', 'media': {'kind': 'video', 'file': 'scene-infinite-express-day.webm', 'width': 672, 'height': 900},
               'still': 'scene-infinite-express-day.jpg'}
        bad = {'look': 'photo', 'media': dict(day['media'], file='../tablet-auth.json')}
        self.manifest({'infinite-express': basic, 'infinite-express-day': day, 'infinite-express-night': bad})
        result = self.scenes()
        self.assertEqual(result['scenes'], ['infinite-express'])
        self.assertEqual(result['info']['infinite-express-day']['media']['url'], '/assets/scene-infinite-express-day.webm')
        self.assertNotIn('infinite-express-night', result['info'])

    def test_house_variants_follow_existing_selections_and_bad_paths_are_rejected(self):
        self.prepare(scene_midnight_video_club__webm=b'v', thumb_midnight_video_club__webp=b't',
                     scene_midnight_video_club_day__webm=b'd', scene_midnight_video_club_day__jpg=b'j',
                     scene_neon_district__webm=b'v', thumb_neon_district__webp=b't',
                     scene_neon_district_night__webm=b'n', scene_neon_district_night__jpg=b'j')
        entries = {}
        for parent, part in (('midnight-video-club', 'day'), ('neon-district', 'night')):
            entries[parent] = {'look': 'photo', 'media': {'kind': 'video', 'file': f'scene-{parent}.webm', 'width': 672, 'height': 1008}}
            name = parent + '-' + part
            entries[name] = {'look': 'photo', 'media': {'kind': 'video', 'file': f'scene-{name}.webm', 'width': 672, 'height': 1008},
                             'still': f'scene-{name}.jpg'}
        entries['neon-district-dawn'] = {'look': 'photo', 'media': {'kind': 'video', 'file': '../tablet-auth.json', 'width': 1, 'height': 1}}
        self.manifest(entries)
        result = self.scenes()
        for parent, part in (('midnight-video-club', 'day'), ('neon-district', 'night')):
            self.assertIn(parent, result['scenes'])
            self.assertNotIn(parent + '-' + part, result['scenes'])
            self.assertIn(parent + '-' + part, result['info'])
        self.assertNotIn('neon-district-dawn', result['info'])

    def test_videos_are_served_in_ranges_with_a_revalidation_tag(self):
        data = bytes(range(256)) * 40
        self.prepare(scene_paradise__webm=data, thumb_paradise__webp=b't')
        cookie = {'Cookie': self.login()}
        status, headers, body = self.request('GET', '/assets/scene-paradise.webm', headers=cookie)
        self.assertEqual((status, body, headers['Content-Type'], headers['Accept-Ranges']), (200, data, 'video/webm', 'bytes'))
        self.assertIn("media-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'], 'private, no-cache')
        status, headers, body = self.request('GET', '/assets/scene-paradise.webm', headers=dict(cookie, Range='bytes=10-19'))
        self.assertEqual((status, body, headers['Content-Range']), (206, data[10:20], f'bytes 10-19/{len(data)}'))
        status, headers, body = self.request('GET', '/assets/scene-paradise.webm', headers=dict(cookie, Range='bytes=-5'))
        self.assertEqual((status, body), (206, data[-5:]))
        status, _, body = self.request('GET', '/assets/scene-paradise.webm', headers=dict(cookie, Range=f'bytes={len(data) - 3}-'))
        self.assertEqual((status, body), (206, data[-3:]))
        for wrong in ('bytes=5000000-', 'bytes=9-3', 'bytes=-', 'items=1-2', 'bytes=1-2,4-5'):
            with self.subTest(wrong):
                self.assertEqual(self.request('GET', '/assets/scene-paradise.webm', headers=dict(cookie, Range=wrong))[0], 416)
        tag = self.request('GET', '/assets/scene-paradise.webm', headers=cookie)[1]['ETag']
        status, _, body = self.request('GET', '/assets/scene-paradise.webm', headers=dict(cookie, **{'If-None-Match': tag}))
        self.assertEqual((status, body), (304, b''))

    def test_scene_files_need_the_session_and_stay_inside_the_fixed_names(self):
        self.prepare(scene_paradise__webm=b'v' * 10, thumb_paradise__webp=b't', scene_extra__webm=b'v')
        self.assertEqual(self.request('GET', '/assets/scene-paradise.webm')[0], 303)
        cookie = {'Cookie': self.login()}
        for path in ('/assets/scene-extra.webm', '/assets/scene-paradise.mp4', '/assets/scene-paradise.webm/../x', '/assets/scenes.json',
                     '/scenes.json', '/tablet-auth.json', '/assets/tablet-auth.json'):
            with self.subTest(path):
                self.assertEqual(self.request('GET', path, headers=cookie)[0], 404)

    def test_the_stage_scripts_are_served_from_the_package_by_name(self):
        from token_tv import tablet_server
        cookie = {'Cookie': self.login()}
        self.assertIn('/app.js', tablet_server._STATIC)
        for name, (file, kind) in list(tablet_server._STATIC.items()):
            if file.startswith('@') or name in ('/setup.js', '/login.js', '/access.css'):
                continue
            with self.subTest(name):
                status, headers, body = self.request('GET', name, headers=cookie)
                self.assertEqual((status, headers['Content-Type']), (200, kind))
                self.assertTrue(body)
        self.assertEqual(self.request('GET', '/setup.js', headers=cookie)[0], 404)

    def test_login_and_exact_read_only_routes(self):
        cookie = self.login()
        status, _, body = self.request('GET', '/api/status', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertIn(b'providers', body)
        self.assertEqual(self.request('GET', '/../tablet_server.py', headers={'Cookie': cookie})[0], 404)
        self.assertEqual(self.request('GET', '/api/setup', headers={'Cookie': cookie})[0], 404)
        self.assertEqual(self.request('POST', '/api/status', {}, {'Cookie': cookie, 'Origin':
                         'https://127.0.0.1:' + str(self.port)})[0], 404)

    def test_rejects_host_and_cross_origin(self):
        self.assertEqual(self.request('GET', '/', headers={'Host': 'attacker.example'})[0], 400)
        self.assertEqual(self.request('POST', '/api/login', {'password': 'fictional-password'},
                                      {'Origin': 'https://attacker.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'password': 'fictional-password'})[0], 403)

    def test_new_password_revokes_persisted_sessions(self):
        cookie = self.login()
        saved = Auth(self.tmp.name)
        self.assertTrue(saved.allowed(cookie))
        self.assertTrue(saved.set_password('different-fictional-password'))
        self.assertFalse(saved.allowed(cookie))
        self.assertEqual(Path(self.tmp.name, 'tablet-auth.json').stat().st_mode & 0o777, 0o600)

    def test_connection_limit_recovers_after_slots_are_released(self):
        for _ in range(8):
            self.assertTrue(self.server._slots.acquire(blocking=False))
        try:
            with self.assertRaises((http.client.RemoteDisconnected, ConnectionResetError)):
                self.request('GET', '/login')
        finally:
            for _ in range(8):
                self.server._slots.release()
        self.assertEqual(self.request('GET', '/login')[0], 200)

    def test_five_failed_passwords_pause_further_attempts(self):
        for _ in range(5):
            self.assertEqual(self.auth.login('fake-client', 'wrong-password')[0], 'invalid')
        self.assertEqual(self.auth.login('fake-client', 'fictional-password')[0], 'limited')

    def report(self, **extra):
        body = {'why': 'load', 'vw': 800, 'vh': 1280, 'dpr': 1.5, 'fit': 1, 'fs': True, 'scene': 'paradise', 'renderer': 'webgl', 'tier': 'high',
                'boxes': {'dock': 574.2, 'slot': 530}, 'notes': ['autoplay blocked: showing the still']}
        body.update(extra)
        return body

    def signed_in(self):
        return {'Cookie': self.login(), 'Origin': 'https://127.0.0.1:' + str(self.port)}

    def test_the_page_reports_what_it_measures_only_with_a_session_and_keeps_only_known_fields(self):
        origin = {'Origin': 'https://127.0.0.1:' + str(self.port)}
        self.assertEqual(self.request('POST', '/api/report', self.report(), origin)[0], 401)
        self.assertFalse(Path(self.tmp.name, 'tablet-reports.json').exists())
        headers = self.signed_in()
        status, _, _ = self.request('POST', '/api/report', self.report(secret='must-not-be-kept', password='x', boxes={'dock': 1, 'evil': 2},
                                                                       gpu='Malié-G615\x00'), headers)
        self.assertEqual(status, 200)
        path = Path(self.tmp.name, 'tablet-reports.json')
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(len(saved), 1)
        entry = saved[0]
        self.assertEqual((entry['why'], entry['scene'], entry['renderer'], entry['tier'], entry['vw'], entry['from']),
                         ('load', 'paradise', 'webgl', 'high', 800, '127.0.0.1'))
        self.assertEqual(entry['boxes'], {'dock': 1.0})
        self.assertEqual(entry['gpu'], 'Mali?-G615?')
        self.assertNotIn('secret', entry)
        self.assertNotIn('password', entry)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_reports_are_limited_checked_and_trimmed(self):
        headers = self.signed_in()
        self.assertEqual(self.request('POST', '/api/report', self.report(), headers)[0], 200)
        self.assertEqual(self.request('POST', '/api/report', self.report(), headers)[0], 400)           # at most one a second
        for bad in ({'why': 'something-else'}, {}, {'vw': 5}):
            self.server.reports.last = 0
            self.assertEqual(self.request('POST', '/api/report', bad, headers)[0], 400, bad)
        self.server.reports.last = 0
        self.assertEqual(self.request('POST', '/api/report', [1, 2], headers)[0], 403)              # not an object: refused like any other body
        self.server.reports.last = 0
        self.assertEqual(self.request('POST', '/api/report', {'why': 'load', 'pad': 'x' * 5000}, headers)[0], 403)   # bigger than 4 KiB
        self.assertEqual(self.request('POST', '/api/report', self.report(), {'Cookie': headers['Cookie'], 'Origin': 'https://attacker.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/report', self.report(), {'Cookie': headers['Cookie']})[0], 403)    # no Origin at all
        from token_tv.tablet_server import REPORT_KEEP, clean_report
        clean = clean_report({'why': 'tick', 'fps': float('nan'), 'vw': -5, 'dpr': 100, 'fit': .8, 'scene': 'not-a-scene', 'tier': 'ultra', 'fs': 'yes', 'rm': False})
        self.assertEqual(clean, {'why': 'tick', 'fit': .8, 'rm': False})
        for _ in range(REPORT_KEEP + 5):
            self.server.reports.last = 0
            self.assertTrue(self.server.reports.add('192.168.1.9', self.report()))
        self.assertEqual(len(json.loads(Path(self.tmp.name, 'tablet-reports.json').read_text(encoding='utf-8'))), REPORT_KEEP)

    def test_the_tablets_own_settings_need_a_session_are_validated_and_persist(self):
        origin = {'Origin': 'https://127.0.0.1:' + str(self.port)}
        self.assertEqual(self.request('GET', '/api/settings')[0], 401)
        self.assertEqual(self.request('POST', '/api/settings', {'scene': 'surf'}, origin)[0], 401)
        headers = self.signed_in()
        status, _, body = self.request('GET', '/api/settings', headers={'Cookie': headers['Cookie']})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['settings']['scene'], 'auto')
        status, _, body = self.request('POST', '/api/settings', {'scene': 'surf', 'night': {'level': 40, 'bad': 1}, 'sound': {'volume': 500}}, headers)
        saved = json.loads(body)['settings']
        self.assertEqual((status, saved['scene'], saved['night']['level'], saved['sound']['volume']), (200, 'surf', 40, 60))
        self.assertEqual(self.request('POST', '/api/settings', {'scene': 'surf'}, {'Cookie': headers['Cookie'], 'Origin': 'https://attacker.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/settings', {'pad': 'x' * 3000}, headers)[0], 403)
        path = Path(self.tmp.name, 'tablet-settings.json')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['scene'], 'surf')

    def test_a_game_scene_is_an_atlas_picture_with_its_frames_and_nothing_else_is_trusted(self):
        from PIL import Image
        directory = Path(self.tmp.name)
        Image.new('RGBA', (64, 64), (1, 2, 3, 255)).save(directory / 'scene-fighting.png')
        Image.new('RGB', (32, 24), (9, 9, 9)).save(directory / 'thumb-fighting.webp')
        (directory / 'scene-fighting.json').write_text('{"frames": {"a": [0, 0, 8, 8]}}', encoding='utf-8')
        entry = {'look': 'game', 'media': {'kind': 'image', 'file': 'scene-fighting.png', 'width': 64, 'height': 64}, 'data': 'scene-fighting.json'}
        (directory / 'scenes.json').write_text(json.dumps({'version': 2, 'scenes': {'fighting': entry}}), encoding='utf-8')
        headers = {'Cookie': self.login()}
        info = json.loads(self.request('GET', '/api/scenes', headers=headers)[2])['info']['fighting']
        self.assertEqual((info['look'], info['data'], info['media']['url']), ('game', '/assets/scene-fighting.json', '/assets/scene-fighting.png'))
        status, answer, body = self.request('GET', '/assets/scene-fighting.json', headers=headers)
        self.assertEqual((status, answer['Content-Type'], json.loads(body)['frames']['a']), (200, 'application/json', [0, 0, 8, 8]))
        for bad in ('scene-other.json', '../scenes.json', 'tablet-auth.json'):
            (directory / 'scenes.json').write_text(json.dumps({'version': 2, 'scenes': {'fighting': {**entry, 'data': bad}}}), encoding='utf-8')
            self.assertNotIn('fighting', json.loads(self.request('GET', '/api/scenes', headers=headers)[2])['info'], bad)
        (directory / 'scenes.json').write_text(json.dumps({'version': 2, 'scenes': {'fighting': entry}}), encoding='utf-8')
        (directory / 'scene-fighting.png').unlink()                      # data alone never makes a scene
        self.assertNotIn('fighting', json.loads(self.request('GET', '/api/scenes', headers=headers)[2])['scenes'])

    def test_the_photo_frame_lists_only_checked_photos_with_fixed_names(self):
        from PIL import Image
        directory = Path(self.tmp.name)
        for name in ('photo-01.jpg', 'photo-02.jpg', 'photo-41.jpg', 'secret.jpg'):
            Image.new('RGB', (32, 24), (90, 120, 160)).save(directory / name)
        manifest = {'version': 1, 'photos': [
            {'file': 'photo-01.jpg', 'width': 1200, 'height': 800, 'focus': [.3, .6]},
            {'file': 'photo-02.jpg', 'width': 1200, 'height': 800, 'focus': [3, 9]},          # focus out of range: centred
            {'file': 'photo-03.jpg', 'width': 1200, 'height': 800},                           # no such file
            {'file': 'photo-41.jpg', 'width': 1200, 'height': 800},                           # beyond the fixed names
            {'file': 'secret.jpg', 'width': 1200, 'height': 800},                             # not a fixed name
            {'file': '../photo-01.jpg', 'width': 1200, 'height': 800},
            {'file': 'photo-01.jpg', 'width': 'wide', 'height': 800}]}
        (directory / 'photos.json').write_text(json.dumps(manifest), encoding='utf-8')
        self.assertEqual(self.request('GET', '/api/photos')[0], 401)
        headers = {'Cookie': self.login()}
        status, _, body = self.request('GET', '/api/photos', headers=headers)
        photos = json.loads(body)['photos']
        self.assertEqual((status, [p['url'] for p in photos]), (200, ['/assets/photo-01.jpg', '/assets/photo-02.jpg']))
        self.assertEqual((photos[0]['focus'], photos[1]['focus']), ([.3, .6], [.5, .5]))
        self.assertEqual(self.request('GET', '/assets/photo-01.jpg', headers=headers)[0], 200)
        self.assertEqual(self.request('GET', '/assets/secret.jpg', headers=headers)[0], 404)
        self.assertEqual(self.request('GET', '/assets/photo-01.jpg')[0], 303)

    def test_the_remote_for_the_small_screen_needs_a_session_and_passes_only_a_command_and_a_value(self):
        class FakeBoard:
            def __init__(self):
                self.sent = []

            def status(self):
                return {'state': 'ok', 'page': 2}

            def command(self, name, value):
                self.sent.append((name, value))
                return {'ok': name == 'page', 'status': {'state': 'ok', 'page': value}, 'error': None if name == 'page' else 'refused'}
        origin = {'Origin': 'https://127.0.0.1:' + str(self.port)}
        self.assertEqual(self.request('GET', '/api/board')[0], 401)
        self.assertEqual(self.request('POST', '/api/board/command', {'command': 'page', 'value': 1}, origin)[0], 401)
        headers = self.signed_in()
        self.assertEqual(json.loads(self.request('GET', '/api/board', headers={'Cookie': headers['Cookie']})[2])['board'], {'state': 'unavailable'})
        self.assertEqual(self.request('POST', '/api/board/command', {'command': 'page', 'value': 1}, headers)[0], 503)       # no remote configured
        self.server.board = board = FakeBoard()
        self.assertEqual(json.loads(self.request('GET', '/api/board', headers={'Cookie': headers['Cookie']})[2])['board']['page'], 2)
        status, _, body = self.request('POST', '/api/board/command', {'command': 'page', 'value': 3}, headers)
        self.assertEqual((status, json.loads(body)['status']['page']), (200, 3))
        self.assertEqual(self.request('POST', '/api/board/command', {'command': 'night', 'value': {}}, headers)[0], 502)    # the module refused it
        for bad in ({'command': 'page'}, {'value': 1}, {'command': 5, 'value': 1}, {'command': 'page', 'value': 1, 'extra': 'x'}):
            self.assertEqual(self.request('POST', '/api/board/command', bad, headers)[0], 400, bad)
        self.assertEqual(self.request('POST', '/api/board/command', {'command': 'page', 'value': 1}, {'Cookie': headers['Cookie'], 'Origin': 'https://attacker.example'})[0], 403)
        self.assertEqual(board.sent, [('page', 3), ('night', {})])                                                         # only what was asked, once

    def test_the_app_is_downloaded_only_with_a_session_and_the_status_says_when_it_exists(self):
        headers = {'Cookie': self.login()}
        self.assertFalse(json.loads(self.request('GET', '/api/status', headers=headers)[2])['app'])
        self.assertEqual(self.request('GET', '/app/ai-desk-tablet.apk', headers=headers)[0], 404)
        folder = Path(self.tmp.name, 'app')
        folder.mkdir()
        (folder / 'ai-desk-tablet.apk').write_bytes(b'PK\x03\x04 not a real app, a test file')
        self.assertTrue(json.loads(self.request('GET', '/api/status', headers=headers)[2])['app'])
        self.assertEqual(self.request('GET', '/app/ai-desk-tablet.apk')[0], 303)
        status, answer, body = self.request('GET', '/app/ai-desk-tablet.apk', headers=headers)
        self.assertEqual((status, answer['Content-Type']), (200, 'application/vnd.android.package-archive'))
        self.assertIn('attachment; filename="ai-desk-tablet.apk"', answer['Content-Disposition'])
        self.assertTrue(body.startswith(b'PK'))
        self.assertEqual(self.request('GET', '/app/other.apk', headers=headers)[0], 404)
        self.assertEqual(self.request('GET', '/app/../tablet-auth.json', headers=headers)[0], 404)

    def test_the_status_carries_a_build_tag_that_changes_with_the_page_files(self):
        from token_tv import tablet_server
        headers = {'Cookie': self.login()}
        first = json.loads(self.request('GET', '/api/status', headers=headers)[2])['build']
        self.assertRegex(first, r'^[0-9a-f]{12}$')
        tablet_server._BUILD['at'] = 0.0
        self.assertEqual(tablet_server.build_id(self.tmp.name), first)     # nothing changed: the same tag
        tablet_server._BUILD.update(at=0.0, value='')
        original = tablet_server._STATIC.copy()
        tablet_server._STATIC['/another.js'] = ('app.js', 'text/javascript')
        try:
            self.assertNotEqual(tablet_server.build_id(self.tmp.name), first)  # a file joined the page
        finally:
            tablet_server._STATIC.clear()
            tablet_server._STATIC.update(original)
            tablet_server._BUILD.update(at=0.0, value='')

    def test_scene_catalog_change_updates_build_even_within_cache_interval(self):
        from token_tv import tablet_server
        first = tablet_server.build_id(self.tmp.name)
        manifest = Path(self.tmp.name, 'scenes.json')
        manifest.write_text('{"scenes":{}}')
        second = tablet_server.build_id(self.tmp.name)
        self.assertNotEqual(first, second)
        manifest.write_text('{"scenes":{"fictional":{}}}')
        self.assertNotEqual(second, tablet_server.build_id(self.tmp.name))

    def test_a_browser_that_rejects_the_certificate_does_not_fill_the_log_with_tracebacks(self):
        import contextlib
        import io
        import ssl
        self.server.refused_at -= 700                                    # the one-line summary is due
        quiet = io.StringIO()
        with contextlib.redirect_stderr(quiet):
            try:
                raise ssl.SSLError('certificate unknown')
            except ssl.SSLError:
                self.server.handle_error(None, ('192.168.1.9', 5))
        self.assertIn('1 connection(s) ended during the secure handshake', quiet.getvalue())
        self.assertNotIn('Traceback', quiet.getvalue())
        loud = io.StringIO()
        with contextlib.redirect_stderr(loud):
            try:
                raise ValueError('a real fault')
            except ValueError:
                self.server.handle_error(None, ('192.168.1.9', 5))
        self.assertIn('Traceback', loud.getvalue())

    def test_keep_alive_reuses_a_connection_and_closes_when_busy_or_malformed(self):
        cookie = self.login()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            conn.request('GET', '/api/status', headers={'Cookie': cookie})
            first = conn.getresponse()
            first.read()
            self.assertEqual(first.status, 200)
            self.assertEqual(first.getheader('Connection'), 'keep-alive')
            sock = conn.sock
            conn.request('GET', '/api/status', headers={'Cookie': cookie})
            second = conn.getresponse()
            second.read()
            self.assertEqual(second.status, 200)
            self.assertIs(conn.sock, sock, 'the second poll reuses the same connection')
            with self.server._active_lock:
                self.server._active += self.server._keep_alive_limit
            try:
                conn.request('GET', '/api/status', headers={'Cookie': cookie})
                busy = conn.getresponse()
                busy.read()
                self.assertEqual(busy.status, 200)
                self.assertEqual(busy.getheader('Connection'), 'close')
            finally:
                with self.server._active_lock:
                    self.server._active -= self.server._keep_alive_limit
        finally:
            conn.close()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            conn.request('POST', '/api/report', body='{"why":"tick"}',
                         headers={'Cookie': cookie, 'Content-Type': 'application/json'})
            bad = conn.getresponse()
            bad.read()
            self.assertEqual(bad.status, 403)
            self.assertEqual(bad.getheader('Connection'), 'close')
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
