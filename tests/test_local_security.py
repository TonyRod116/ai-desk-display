import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from token_tv.live import handler
from token_tv.state import UsageStore


class LocalSecurityTests(unittest.TestCase):
    def serve(self, cls):
        server = ThreadingHTTPServer(('127.0.0.1', 0), cls)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        return f'http://127.0.0.1:{server.server_port}'

    def test_external_host_rejected_even_with_matching_origin(self):
        root = self.serve(handler(UsageStore([])))
        for body in (None, b'{"style":"orbit"}'):
            req = Request(root + ('/snapshot' if body is None else '/display/style'), data=body,
                          headers={'Host': 'attacker.example', 'Origin': 'http://attacker.example',
                                   'Content-Type': 'application/json'})
            with self.assertRaises(HTTPError) as caught:
                urlopen(req)
            self.assertEqual(caught.exception.code, 403)
        self.assertEqual(urlopen(root + '/health').status, 200)

    def test_authenticated_redirect_never_reaches_second_endpoint(self):
        from token_tv.sources import json_get
        received = []
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                received.append(self.path)
                if self.path == '/start':
                    self.send_response(302)
                    self.send_header('Location', '/unexpected-destination')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{}')
        root = self.serve(Redirect)
        with self.assertRaises(HTTPError):
            json_get(root + '/start', {'Authorization': 'Bearer TEST-ONLY-NOT-A-SECRET'})
        self.assertEqual(received, ['/start'])
