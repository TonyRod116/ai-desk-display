"""The tablet's outside weather: what is accepted from the forecast service, what leaves the computer, when a reading is old, and the route.

No real network is used: the connection class and the fetcher are fakes, and the one test of the real `fetch` runs against a fake connection.
"""
import http.client
import json
import ssl
import tempfile
import threading
import unittest

from token_tv import tablet_weather as tw
from token_tv.tablet_server import Auth, Handler, TabletServer
from token_tv.tablet_settings import Settings, apply, defaults


def body(temp=14.4, code=3, day=1, **extra):
    current = {'time': '2026-11-10T08:30', 'temperature_2m': temp, 'weather_code': code, 'is_day': day}
    current.update(extra)
    return json.dumps({'latitude': 41.4, 'current': current}).encode()


class ParseTests(unittest.TestCase):
    def test_a_good_reading_is_rounded_and_typed(self):
        self.assertEqual(tw.parse(body(14.4, 3, 1)), {'temp': 14, 'code': 3, 'day': True})
        self.assertEqual(tw.parse(body(-3.6, 71, 0)), {'temp': -4, 'code': 71, 'day': False})

    def test_anything_odd_is_refused_whole(self):
        bad = [b'', b'not json', b'[]', b'{}', b'{"current": 5}', json.dumps({'current': {}}).encode(),
               body(temp=None), body(temp='14'), body(temp=True), body(temp=float('nan')), body(temp=999), body(temp=-80),
               body(code=7), body(code='3'), body(code=3.0), body(code=True), body(day=2), body(day=True), body(day=None)]
        for raw in bad:
            with self.subTest(raw=raw[:40]):
                self.assertIsNone(tw.parse(raw))

    def test_every_code_the_service_accepts_is_a_known_wmo_code_and_nothing_else(self):
        self.assertEqual(len(tw.CODES), 28)
        for code in tw.CODES:
            self.assertIsNotNone(tw.parse(body(code=code)))
        for code in (4, 10, 44, 100, -1):
            self.assertIsNone(tw.parse(body(code=code)))


class PlaceTests(unittest.TestCase):
    def test_the_place_leaves_the_computer_rounded_to_a_tenth_of_a_degree(self):
        self.assertEqual(tw.coarse(41.3874, 2.1686), (41.4, 2.2))
        self.assertEqual(tw.coarse(-0.04, -0.04), (0.0, 0.0))                 # never -0.0
        self.assertEqual(str(tw.coarse(-0.04, 0)[0]), '0.0')


class FakeConnection:
    sent = []
    status, payload, error = 200, b'', None

    def __init__(self, host, timeout=None, context=None):
        self.host, self.timeout, self.context = host, timeout, context
        self.closed = False

    def request(self, method, path, headers=None):
        if self.error:
            raise self.error
        FakeConnection.sent.append((self.host, method, path, dict(headers or {}), self.context, self.timeout))

    def getresponse(self):
        outer = self

        class Response:
            status = outer.status

            def read(self, limit=-1):
                return outer.payload if limit < 0 else outer.payload[:limit]
        return Response()

    def close(self):
        self.closed = True


def connection(status=200, payload=b'', error=None):
    return type('Conn', (FakeConnection,), {'status': status, 'payload': payload, 'error': error})


class FetchTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.sent = []

    def test_what_is_sent_is_only_a_coarse_place_the_variables_and_a_generic_client_name(self):
        reading = tw.fetch(41.3874, 2.1686, connect=connection(payload=body(11.6, 2, 1)))
        self.assertEqual(reading, {'temp': 12, 'code': 2, 'day': True})
        (host, method, path, headers, context, timeout), = FakeConnection.sent
        self.assertEqual((host, method, timeout), ('api.open-meteo.com', 'GET', tw.TIMEOUT))
        self.assertIn('latitude=41.4', path)
        self.assertIn('longitude=2.2', path)
        self.assertNotIn('41.38', path)
        self.assertNotIn('2.16', path)
        self.assertIn('current=temperature_2m%2Cweather_code%2Cis_day', path)
        self.assertEqual(set(headers), {'User-Agent', 'Accept'})
        self.assertEqual(headers['User-Agent'], 'ai-desk-display-tablet')
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)             # certificates are checked
        self.assertTrue(context.check_hostname)

    def test_failures_are_unknown_not_errors(self):
        self.assertIsNone(tw.fetch(41.4, 2.2, connect=connection(status=503, payload=body())))
        self.assertIsNone(tw.fetch(41.4, 2.2, connect=connection(status=301, payload=body())))     # a redirect is never followed
        self.assertIsNone(tw.fetch(41.4, 2.2, connect=connection(payload=b'x' * (tw.MAX_BODY + 1))))
        self.assertIsNone(tw.fetch(41.4, 2.2, connect=connection(payload=b'{"current": {}}')))
        for error in (OSError('down'), TimeoutError(), ssl.SSLError('bad certificate'), http.client.HTTPException('x')):
            with self.subTest(error=type(error).__name__):
                self.assertIsNone(tw.fetch(41.4, 2.2, connect=connection(error=error)))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class WeatherTests(unittest.TestCase):
    def make(self, readings, **options):
        self.settings = Settings(None, ())
        self.settings.update({'weather': {'enabled': True}})
        self.clock, self.asked, self.logs = Clock(), [], []
        queue = list(readings)

        def fetch(lat, lon):
            self.asked.append((lat, lon))
            value = queue.pop(0) if queue else None
            if isinstance(value, Exception):
                raise value
            return value
        return tw.Weather(self.settings, fetch, clock=self.clock, log=self.logs.append, **options)

    def test_a_reading_is_shown_with_its_age_and_is_unknown_once_old(self):
        weather = self.make([{'temp': 14, 'code': 3, 'day': True}])
        self.assertIsNone(weather.status())
        self.assertEqual(weather.refresh(), tw.INTERVAL)
        self.clock.now += 100
        self.assertEqual(weather.status(), {'temp': 14, 'code': 3, 'day': True, 'age': 100})
        self.clock.now += tw.FRESH - 100
        self.assertIsNotNone(weather.status())
        self.clock.now += 1
        self.assertIsNone(weather.status())                                   # old is unknown, never the last number

    def test_the_place_asked_is_the_settings_place_rounded(self):
        weather = self.make([{'temp': 1, 'code': 0, 'day': True}])
        self.settings.update({'place': {'lat': 41.3874, 'lon': 2.1686}})
        weather.refresh()
        self.assertEqual(self.asked, [(41.4, 2.2)])

    def test_a_failure_keeps_the_last_fresh_reading_retries_soon_and_logs_once(self):
        weather = self.make([{'temp': 14, 'code': 3, 'day': True}, None, RuntimeError('boom'), {'temp': 15, 'code': 1, 'day': True}])
        weather.refresh()
        self.assertEqual(weather.refresh(), tw.RETRY)
        self.assertEqual(weather.refresh(), tw.RETRY)                          # a fetcher that raises never kills the loop
        self.assertEqual(weather.status()['temp'], 14)
        self.assertEqual(self.logs, ['tablet: weather unavailable (kept as unknown)'])
        self.assertEqual(weather.refresh(), tw.INTERVAL)
        self.assertEqual(self.logs[-1], 'tablet: weather available again')
        self.assertEqual(weather.status()['temp'], 15)

    def test_a_changed_place_is_unknown_until_the_new_place_answers(self):
        weather = self.make([{'temp': 14, 'code': 3, 'day': True}, {'temp': 9, 'code': 61, 'day': True}])
        weather.refresh()
        self.settings.update({'place': {'lat': 40.4, 'lon': -3.7}})
        self.assertIsNone(weather.status())                                   # Barcelona's number is not Madrid's
        weather.refresh()
        self.assertEqual(self.asked[-1], (40.4, -3.7))
        self.assertEqual(weather.status()['temp'], 9)

    def test_switched_off_asks_nothing_and_shows_nothing(self):
        weather = self.make([{'temp': 14, 'code': 3, 'day': True}])
        weather.refresh()
        self.settings.update({'weather': {'enabled': False}})
        self.assertIsNone(weather.status())
        self.assertEqual(weather.refresh(), weather.watch)
        self.assertEqual(len(self.asked), 1)                                  # no request while it is off
        self.settings.update({'weather': {'enabled': True}})
        self.assertIsNone(weather.status())                                   # the reading was dropped, not kept in secret

    def test_the_loop_asks_again_when_the_place_changes_and_does_not_hammer_a_failing_service(self):
        weather = self.make([None] * 5, watch=0.01)
        calls = []
        original = weather.refresh

        def counted():
            calls.append(1)
            return original()
        weather.refresh = counted
        weather.start()
        self.addCleanup(weather.stop.set)
        threading.Event().wait(0.15)
        self.assertEqual(len(calls), 1)                                       # the first attempt failed: the next one waits RETRY, not the watch interval
        self.settings.update({'place': {'lat': 10.0, 'lon': 10.0}})
        threading.Event().wait(0.15)
        self.assertEqual(len(calls), 2)                                       # a new place is asked for at once, once


class SettingsTests(unittest.TestCase):
    def test_the_switch_defaults_off_and_only_accepts_a_boolean(self):
        self.assertEqual(defaults()['weather'], {'enabled': False})
        off = apply(defaults(), {'weather': {'enabled': False}}, ())
        self.assertFalse(off['weather']['enabled'])
        for bad in ('no', 0, None, [True]):
            self.assertFalse(apply(defaults(), {'weather': {'enabled': bad}}, ())['weather']['enabled'])
        self.assertEqual(set(apply(defaults(), {'weather': {'enabled': True, 'url': 'https://example.com'}}, ())['weather']), {'enabled'})


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = Auth(self.tmp.name)
        self.assertTrue(self.auth.set_password('fictional-password'))

        class Feeds:
            def status(self):
                return {'providers': {}, 'metrics': None}

        class Fixed:
            def status(self):
                return {'temp': 7, 'code': 61, 'day': False, 'age': 12}
        self.Fixed = Fixed
        self.Feeds = Feeds

    def serve(self, weather):
        server = TabletServer(('127.0.0.1', 0), Handler, mode='lan', auth=self.auth, feeds=self.Feeds(), private=self.tmp.name,
                              lan='127.0.0.1', lan_port=8667, fingerprint='EXAMPLE', weather=weather)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def get(self, server, path, cookie=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        conn.request('GET', path, headers={'Cookie': cookie} if cookie else {})
        response = conn.getresponse()
        out = (response.status, response.read())
        conn.close()
        return out

    def cookie(self, server):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        conn.request('POST', '/api/login', body=json.dumps({'password': 'fictional-password'}),
                     headers={'Content-Type': 'application/json', 'Origin': 'https://127.0.0.1:' + str(server.server_port)})
        response = conn.getresponse()
        response.read()
        conn.close()
        return response.getheader('Set-Cookie').split(';', 1)[0]

    def test_the_route_needs_a_session(self):
        server = self.serve(self.Fixed())
        status, raw = self.get(server, '/api/weather')
        self.assertEqual(status, 401)
        self.assertNotIn(b'temp', raw)

    def test_the_route_gives_the_reading_or_unknown(self):
        server = self.serve(self.Fixed())
        status, raw = self.get(server, '/api/weather', self.cookie(server))
        self.assertEqual((status, json.loads(raw)), (200, {'weather': {'temp': 7, 'code': 61, 'day': False, 'age': 12}}))
        bare = self.serve(None)
        status, raw = self.get(bare, '/api/weather', self.cookie(bare))
        self.assertEqual((status, json.loads(raw)), (200, {'weather': None}))


if __name__ == '__main__':
    unittest.main()
