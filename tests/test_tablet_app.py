"""The Android shell around the tablet page (`android/`) and the script that builds it (`scripts/build_tablet_app.py`).

Everything here uses fictional addresses and fingerprints, throw-away signing keys in temporary folders and a fake setup endpoint on
this computer's loopback. It never contacts the real tablet service, a device or a provider, and never reads a certificate or key of
the service. The real build needs the Android SDK and a JDK (on this PC the Windows ones, reached through WSL); without them
only the static checks run. What the app does on the tablet (pinning, brightness, full screen, the bridge) is NOT tested here.
"""
import contextlib
import hashlib
import io
import json
import re
import shutil
import stat
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from scripts import build_tablet_app as app

SRC = app.ANDROID / 'src/app/aidesk/tablet'
MAIN = (SRC / 'MainActivity.java').read_text(encoding='utf-8')
BRIDGE = (SRC / 'Bridge.java').read_text(encoding='utf-8')
GUARD = (SRC / 'Guard.java').read_text(encoding='utf-8')
LOADER = (SRC / 'Loader.java').read_text(encoding='utf-8')
MANIFEST = app.ANDROID / 'AndroidManifest.xml'
ANDROID_NS = '{http://schemas.android.com/apk/res/android}'
FICTIONAL_URL = 'https://192.0.2.10:8667'          # TEST-NET-1: never a real address
FICTIONAL_PIN = 'ab' * 32
FICTIONAL_PIN_COLONS = ':'.join(f'{b:02X}' for b in bytes.fromhex(FICTIONAL_PIN))
CONTRACT = [('String', 'version', ''), ('void', 'setBrightness', 'double'), ('void', 'keepAwake', 'boolean'), ('void', 'reload', ''),
            ('void', 'vibrate', 'double'), ('String', 'battery', ''), ('double', 'light', ''), ('String', 'installUpdate', 'String'), ('String', 'fingerprint', ''), ('String', 'offlineStatus', ''), ('String', 'syncOffline', '')]


def tools_or_none():
    try:
        return app.find_toolchain()
    except app.BuildError:
        return None


TOOLS = tools_or_none()


_JAVA_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])+\'', re.S)


def plain_java(source):
    """The Java text without comments and the contents of string and character literals (so braces and quotes can be counted).
    One pass, in text order: a `//` inside a string literal belongs to the string, an apostrophe inside a comment to the comment."""
    def blank(match):
        return {'"': '""', "'": "''"}.get(match.group(0)[0], ' ')
    return _JAVA_TOKEN.sub(blank, source)


def method_body(source, signature):
    """The text between the braces of the method whose declaration contains `signature`."""
    source = plain_java(source)
    start = source.index(signature)
    depth, begin = 0, source.index('{', start)
    for position in range(begin, len(source)):
        if source[position] == '{':
            depth += 1
        elif source[position] == '}':
            depth -= 1
            if depth == 0:
                return source[begin + 1:position]
    raise AssertionError(f'unbalanced braces after {signature}')


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(MANIFEST).getroot()
        self.application = self.root.find('application')

    def test_only_four_permissions_and_no_other_feature_request(self):
        names = sorted(p.get(ANDROID_NS + 'name') for p in self.root.findall('uses-permission'))
        self.assertEqual(names, sorted(app.PERMISSIONS))
        self.assertEqual(self.root.findall('uses-feature'), [])
        self.assertEqual(self.root.findall('queries'), [])

    def test_the_app_is_locked_down(self):
        attrs = self.application.attrib
        self.assertEqual(attrs[ANDROID_NS + 'usesCleartextTraffic'], 'false')
        self.assertEqual(attrs[ANDROID_NS + 'allowBackup'], 'false')
        self.assertEqual(attrs[ANDROID_NS + 'hardwareAccelerated'], 'true')
        self.assertNotIn(ANDROID_NS + 'debuggable', attrs, 'only a --debug build may be debuggable (aapt2 adds it)')
        self.assertNotIn(ANDROID_NS + 'networkSecurityConfig', attrs)
        self.assertNotIn(ANDROID_NS + 'requestLegacyExternalStorage', attrs)

    def test_exactly_one_exported_component_and_it_is_the_launcher(self):
        components = [e for e in self.application if e.tag in ('activity', 'activity-alias', 'service', 'receiver', 'provider')]
        self.assertEqual([c.tag for c in components], ['activity'])
        activity = components[0]
        self.assertEqual(activity.get(ANDROID_NS + 'name'), '.MainActivity')
        self.assertEqual(activity.get(ANDROID_NS + 'exported'), 'true')
        filters = activity.findall('intent-filter')
        self.assertEqual(len(filters), 1)
        self.assertEqual([a.get(ANDROID_NS + 'name') for a in filters[0].findall('action')], ['android.intent.action.MAIN'])
        self.assertEqual([c.get(ANDROID_NS + 'name') for c in filters[0].findall('category')], ['android.intent.category.LAUNCHER'])
        self.assertEqual(len(re.findall(r'android:exported="true"', MANIFEST.read_text(encoding='utf-8'))), 1)

    def test_portrait_both_ways_and_nothing_recreates_the_page(self):
        activity = self.application.find('activity')
        self.assertEqual(activity.get(ANDROID_NS + 'screenOrientation'), 'sensorPortrait')
        changes = set(activity.get(ANDROID_NS + 'configChanges').split('|'))
        # every configuration change the manifest can name, so that nothing (Bold text, a language, a keyboard, a resize) recreates the page
        self.assertEqual(changes, {'mcc', 'mnc', 'locale', 'touchscreen', 'keyboard', 'keyboardHidden', 'navigation', 'orientation', 'screenLayout',
                                   'uiMode', 'screenSize', 'smallestScreenSize', 'density', 'layoutDirection', 'colorMode', 'grammaticalGender',
                                   'fontScale', 'fontWeightAdjustment'})
        self.assertEqual(self.root.get('package'), app.PACKAGE)
        sdk = self.root.find('uses-sdk')
        self.assertEqual((sdk.get(ANDROID_NS + 'minSdkVersion'), sdk.get(ANDROID_NS + 'targetSdkVersion')),
                         (str(app.MIN_SDK), str(app.TARGET_SDK)))

    def test_black_theme_and_a_launcher_icon_that_exists(self):
        res = app.ANDROID / 'res'
        styles = (res / 'values/styles.xml').read_text(encoding='utf-8')
        self.assertIn('@color/black', styles)
        icon = ET.parse(res / 'mipmap-anydpi-v26/ic_launcher.xml').getroot()
        self.assertEqual(icon.tag, 'adaptive-icon')
        for layer in icon:
            target = layer.get(ANDROID_NS + 'drawable')
            kind, name = target.lstrip('@').split('/')
            self.assertTrue((res / kind / f'{name}.xml').is_file() or kind == 'color', target)

    def test_strings_exist_in_english_and_spanish_with_the_same_names(self):
        res = app.ANDROID / 'res'
        english = {s.get('name'): s.text for s in ET.parse(res / 'values/strings.xml').getroot()}
        spanish = {s.get('name'): s.text for s in ET.parse(res / 'values-es/strings.xml').getroot()}
        self.assertEqual(sorted(english), sorted(spanish))
        self.assertEqual((english['app_name'], spanish['app_name']), ('AI Desk', 'AI Desk'))
        self.assertEqual(english['status_waiting'], 'Waiting for the PC...')
        self.assertEqual(spanish['status_waiting'], 'Esperando al PC...')
        for name in ('status_connecting', 'status_waiting_hint', 'status_certificate', 'status_certificate_hint'):
            self.assertTrue(english[name] and spanish[name] and english[name] != spanish[name], name)


class SourceTests(unittest.TestCase):
    def test_the_bridge_is_exactly_the_contract(self):
        source = plain_java(BRIDGE)
        found = re.findall(r'@JavascriptInterface\s+public\s+(\w+)\s+(\w+)\(([^)]*)\)', source)
        listed = [(kind, name, ', '.join(parameter.split()[0] for parameter in params.split(',') if parameter.strip()))
                  for kind, name, params in found]
        self.assertEqual(listed, CONTRACT)
        self.assertEqual(sorted(name for _, name, _ in CONTRACT), sorted(app.BRIDGE_METHODS), 'the build script checks the same list')
        self.assertEqual(source.count('@JavascriptInterface'), len(CONTRACT))
        self.assertEqual(len(re.findall(r'\bpublic\b', source)), len(CONTRACT), 'every public member of the bridge is a contract method')
        self.assertNotIn('@JavascriptInterface', plain_java(MAIN))
        self.assertEqual(len(re.findall(r'addJavascriptInterface\(', MAIN)), 1)
        self.assertIn('addJavascriptInterface(new Bridge(this), "AiDeskApp")', MAIN)

    def test_the_pin_decides_every_ssl_error(self):
        body = method_body(MAIN, 'public void onReceivedSslError(')
        self.assertEqual(body.count('.proceed()'), 1)
        self.assertEqual(len(re.findall(r'\.proceed\(\)', plain_java(MAIN))), 1, 'no other place may accept a certificate')
        condition = re.search(r'if \((.*?)\) \{\s*handler\.proceed\(\)', body, flags=re.S)
        self.assertTrue(condition, 'proceed() must sit directly under a condition')
        self.assertIn('ours', condition.group(1))
        self.assertIn('Guard.matchesPin(derOf(error.getCertificate()), Config.FINGERPRINT)', condition.group(1))
        self.assertIn('Guard.sameOrigin(Config.ORIGIN, error.getUrl())', body)
        self.assertIn('handler.cancel()', body)
        self.assertIn('request.cancel()', method_body(MAIN, 'public void onReceivedClientCertRequest('))
        self.assertNotIn('.ignore()', plain_java(MAIN))

    def test_navigation_outside_the_server_is_blocked(self):
        override = method_body(MAIN, 'public boolean shouldOverrideUrlLoading(')
        self.assertRegex(override, r'return\s*!\s*Guard\.sameOrigin\(Config\.ORIGIN,')
        intercept = method_body(MAIN, 'public WebResourceResponse shouldInterceptRequest(')
        self.assertIn('Guard.sameOrigin(Config.ORIGIN', intercept)
        self.assertIn('403', intercept)
        for url in re.findall(r'loadUrl\(([^)]*)\)', plain_java(MAIN)):
            self.assertEqual(url.strip(), 'Config.START_URL')
        self.assertNotIn('http://', MAIN + BRIDGE + GUARD + LOADER)
        self.assertNotIn('file://', MAIN + BRIDGE + GUARD + LOADER)

    def test_webview_settings_follow_the_brief(self):
        text = plain_java(MAIN)
        for line in ('setJavaScriptEnabled(true)', 'setDomStorageEnabled(true)', 'setMediaPlaybackRequiresUserGesture(false)',
                     'setAllowFileAccess(false)', 'setAllowContentAccess(false)', 'setSupportZoom(false)', 'setBuiltInZoomControls(false)',
                     'setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW)', 'setAcceptCookie(true)', 'setWebContentsDebuggingEnabled(Config.DEBUG)',
                     'FLAG_KEEP_SCREEN_ON', 'BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE', 'SYSTEM_UI_FLAG_IMMERSIVE_STICKY'):
            self.assertIn(line, text)
        self.assertNotIn('setWebContentsDebuggingEnabled(true)', text)
        self.assertNotIn('setJavaScriptEnabled(false)', text)
        focus = method_body(MAIN, 'public void onWindowFocusChanged(')
        self.assertIn('hideSystemUi()', focus, 'immersive mode is re-applied whenever the window regains focus')

    def test_back_never_leaves_and_retries_are_ten_seconds(self):
        back = method_body(MAIN, 'public void onBackPressed(')
        self.assertNotIn('super.onBackPressed', back)
        self.assertNotIn('finish()', plain_java(MAIN))
        self.assertIn('RETRY_MS = 10_000L', LOADER)
        self.assertIn('schedule(retryTask, RETRY_MS)', plain_java(LOADER))
        self.assertIn('R.string.status_waiting', MAIN)
        self.assertIn('Loader.Screen.CONNECTING', MAIN)
        # every page callback goes through the loader, and a lifecycle pause stops its timers
        for callback, call in (('public void onReceivedError(', 'loader.fail(error.getErrorCode() == ERROR_FAILED_SSL_HANDSHAKE)'),
                               ('public void onReceivedHttpError(', 'loader.fail(false)'),
                               ('public void onPageStarted(', 'loader.pageStarted()'),
                               ('public void onPageCommitVisible(', 'loader.loaded()'), ('public void onPageFinished(', 'loader.loaded()'),
                               ('protected void onStop(', 'loader.pause()'), ('protected void onStart(', 'loader.resume()')):
            self.assertIn(call, method_body(MAIN, callback), callback)

    def test_a_renderer_that_keeps_dying_cannot_make_the_app_spin(self):
        body = method_body(MAIN, 'private boolean rebuildWebView(')
        self.assertIn('RENDERER_RETRY_GAP_MS', body)
        self.assertIn('loader.fail(false)', body, 'a repeated loss goes through the ten-second wait')
        self.assertIn('loader.start()', body, 'the first loss is answered at once')
        self.assertIn('view == web', plain_java(MAIN), 'callbacks of a replaced WebView are ignored')

    def test_the_bridge_checks_what_it_is_given(self):
        """Every input rule lives in Guard (and is run on a JVM below); the activity only applies the result."""
        self.assertIn('Guard.brightness(level)', method_body(MAIN, 'void setBrightness('))
        self.assertIn('Float.isNaN', method_body(MAIN, 'void setBrightness('))
        self.assertIn('Guard.vibrationMillis(milliseconds)', method_body(MAIN, 'void vibrate('))
        self.assertIn('Guard.batteryJson(', method_body(MAIN, 'String batteryJson('))
        self.assertIn('Guard.lux(', method_body(MAIN, 'double lightLux('))
        self.assertIn('RELOAD_GAP_MS', plain_java(MAIN))
        self.assertIn('MIN_BRIGHTNESS = 0.02', GUARD)
        self.assertIn('MAX_VIBRATION_MS = 500.0', GUARD)

    def test_no_address_or_certificate_is_written_into_the_sources(self):
        """The server's address and fingerprint exist only in the generated Config of one build, never in Git."""
        for path in sorted(app.ANDROID.rglob('*')):
            if not path.is_file():
                continue
            text = path.read_text(encoding='utf-8')
            self.assertFalse(re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', text), f'{path} holds an IP address')
            self.assertFalse(re.search(r'\b[0-9a-fA-F]{64}\b', text), f'{path} holds a 64-digit hex string')
            self.assertFalse(re.search(r'\b(?:[0-9A-F]{2}:){15}[0-9A-F]{2}\b', text), f'{path} holds a colon fingerprint')
        self.assertFalse((SRC / 'Config.java').exists(), 'Config.java is generated at build time')

    def test_the_build_script_never_opens_the_services_secrets(self):
        script = (app.ROOT / 'scripts/build_tablet_app.py').read_text(encoding='utf-8')
        for secret in ('tablet-key', 'tablet-cert', 'tablet-auth', '.pem', '.config/token-tv', '8787'):
            self.assertNotIn(secret, script)
        self.assertEqual(app.SETUP_URL, 'http://127.0.0.1:8666/api/setup')

    def test_the_updater_talks_to_the_pc_alone_with_the_pinned_certificate_and_checks_the_bytes(self):
        raw = (SRC / 'Updater.java').read_text(encoding='utf-8')
        updater = plain_java(raw)            # strings and comments blanked: for what the CODE may call
        self.assertEqual(re.findall(r'new URL\(([^)]*)\)', raw), ['Config.ORIGIN + PATH'])
        self.assertNotIn('http://', raw)
        self.assertEqual(raw.count('https://'), 0, 'no address is written into the updater')
        self.assertIn('static final String PATH = "/app/ai-desk-tablet.apk"', raw)
        for needle in ('setInstanceFollowRedirects(false)', 'Guard.matchesPin(chain[0].getEncoded(), Config.FINGERPRINT)',
                       'expectedHost.equals(name)', 'Guard.MAX_UPDATE_BYTES', 'Guard.updateMatches(apk, expected)',
                       'MODE_FULL_INSTALL', 'RECEIVER_NOT_EXPORTED', 'setAppPackageName(context.getPackageName())'):
            self.assertIn(needle, raw, needle)
        self.assertIn('throw new CertificateException("no client certificates")', raw)
        for forbidden in ('FileOutputStream', 'getExternal', 'DownloadManager', 'Runtime.getRuntime', 'ProcessBuilder', 'exec(', 'setDefaultSSLSocketFactory',
                          'setDefaultHostnameVerifier', 'ALLOW_ALL'):
            self.assertNotIn(forbidden, updater, forbidden)
        # the cookie is read from the PC's origin only and sent only on that one request
        self.assertIn('CookieManager.getInstance().getCookie(Config.ORIGIN)', MAIN)
        self.assertEqual(raw.count('setRequestProperty("Cookie"'), 1)
        # the bridge method only hands over to the activity, which hands over to the updater; the page gets fixed words back
        self.assertIn('return app.installUpdate(sha256);', plain_java(BRIDGE))
        self.assertIn('return updater.start(sha256);', method_body(MAIN, 'String installUpdate('))
        for state in ('"downloading"', '"confirm"', '"done"', '"failed"'):
            self.assertIn(state, raw)
        self.assertIn('window.aiDeskAppUpdate&&window.aiDeskAppUpdate(\'" + state + "\')', MAIN)
        self.assertIn('updater.release();', method_body(MAIN, 'protected void onDestroy('))

    def test_the_docs_name_every_bridge_method_and_both_install_routes(self):
        text = (app.ROOT / 'docs/tablet-app.md').read_text(encoding='utf-8')
        for _, name, _ in CONTRACT:
            self.assertIn(name + '(', text)
        for needle in ('AiDeskApp', '/app/ai-desk-tablet.apk', 'adb pair', 'adb connect', 'adb install -r', 'build_tablet_app.py',
                       'app-signing', 'not verified', 'REQUEST_INSTALL_PACKAGES', 'APP UPDATE'):
            self.assertIn(needle, text)


class ArgumentTests(unittest.TestCase):
    def test_origin_is_normalised_and_anything_else_is_refused(self):
        self.assertEqual(app.parse_origin('https://192.168.1.21:8667'), ('https://192.168.1.21:8667', '192.168.1.21', 8667))
        self.assertEqual(app.parse_origin(' https://192.168.1.21:8667/ ')[0], 'https://192.168.1.21:8667')
        self.assertEqual(app.parse_origin('https://PC.Local:8667')[0], 'https://pc.local:8667')
        self.assertEqual(app.parse_origin('https://10.0.0.5')[0], 'https://10.0.0.5')
        self.assertEqual(app.parse_origin('https://[fd00::5]:8667')[0], 'https://[fd00::5]:8667')
        self.assertEqual(app.parse_origin('https://[FD00:0:0:0:0:0:0:5]:8667')[0], 'https://[fd00::5]:8667', 'the form WebView reports')
        for bad in ('http://192.168.1.21:8667', '192.168.1.21:8667', 'https://192.168.1.21:8667/app', 'https://192.168.1.21:8667/?x=1',
                    'https://user@192.168.1.21:8667', 'https://127.0.0.1:8667', 'https://8.8.8.8:8667', 'https://0.0.0.0:8667',
                    'https://192.168.1.21:0', 'https://192.168.1.21:99999', 'https://', '', None, 'https://bad_host:8667',
                    'https://192.168.1.21:8667#x', 'https://a b:8667'):
            with self.assertRaises(app.BuildError, msg=repr(bad)):
                app.parse_origin(bad)

    def test_fingerprint_accepts_the_setup_page_format(self):
        self.assertEqual(app.parse_fingerprint(FICTIONAL_PIN_COLONS), FICTIONAL_PIN)
        self.assertEqual(app.parse_fingerprint(FICTIONAL_PIN.upper()), FICTIONAL_PIN)
        self.assertEqual(app.parse_fingerprint(' ' + FICTIONAL_PIN + '\n'), FICTIONAL_PIN)
        for bad in ('', None, 'ab' * 31, 'ab' * 33, 'zz' * 32, 'ab:cd', 'ab' * 31 + 'a'):
            with self.assertRaises(app.BuildError, msg=repr(bad)):
                app.parse_fingerprint(bad)

    def test_the_version_counter_only_moves_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.assertEqual(app.next_version_code(folder), 1)
            (folder / app.COUNTER_NAME).write_text('7\n')
            self.assertEqual(app.next_version_code(folder), 8)
            (folder / app.COUNTER_NAME).unlink()
            (folder / (app.APK_NAME + '.json')).write_text(json.dumps({'version_code': 9}))
            self.assertEqual(app.next_version_code(folder), 10, 'the last JSON is the fallback when the counter is lost')
            (folder / app.COUNTER_NAME).write_text('not a number')
            self.assertEqual(app.next_version_code(folder), 10)

    def test_a_missing_sdk_or_jdk_is_named_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(app.BuildError, r'No Android SDK .*--sdk'):
                app.find_toolchain(sdk=directory)
            (Path(directory) / 'build-tools').mkdir()
            (Path(directory) / 'platforms').mkdir()
            with self.assertRaisesRegex(app.BuildError, 'build-tools'):
                app.find_toolchain(sdk=directory)

    def test_main_explains_itself(self):
        with contextlib.redirect_stderr(io.StringIO()) as captured, self.assertRaises(SystemExit) as stop:
            app.main(['--url', FICTIONAL_URL])
        self.assertEqual(stop.exception.code, 2)
        self.assertIn('--url and --fingerprint', captured.getvalue())
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()) as captured:
            code = app.main(['--url', FICTIONAL_URL, '--fingerprint', FICTIONAL_PIN, '--sdk', directory, '--out', directory])
        self.assertEqual(code, 1)
        self.assertIn('error: No Android SDK', captured.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            code = app.main(['--url', 'http://192.0.2.10:8667', '--fingerprint', FICTIONAL_PIN])
        self.assertEqual(code, 1)
        self.assertIn('https://', captured.getvalue())


class MainOutputTests(unittest.TestCase):
    INFO = {'file': 'ai-desk-tablet.apk', 'size': 25000, 'version_name': '1.1', 'version_code': 1, 'debug': False, 'sha256': 'ab' * 32,
            'origin': FICTIONAL_URL, 'pin_sha256': FICTIONAL_PIN, 'signer_sha256': 'cd' * 32}

    def run_main(self, keys):
        def fake_build(*args, **kwargs):
            keys.mkdir(exist_ok=True)
            (keys / 'release.p12').write_bytes(b'not a real key')
            return self.INFO
        with mock.patch.object(app, 'find_toolchain', return_value=None), mock.patch.object(app, 'build', fake_build), \
                contextlib.redirect_stdout(io.StringIO()) as shown:
            code = app.main(['--url', FICTIONAL_URL, '--fingerprint', FICTIONAL_PIN, '--out', str(keys.parent), '--keystore-dir', str(keys)])
        self.assertEqual(code, 0)
        return shown.getvalue()

    def test_main_says_once_when_it_created_the_signing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            keys = Path(directory) / 'keys'
            first = self.run_main(keys)
            self.assertIn('created the private signing key', first)
            self.assertIn('built ', first)
            self.assertNotIn('created the private signing key', self.run_main(keys))


class FakeSetup(BaseHTTPRequestHandler):
    """Stands in for the tablet service's loopback setup endpoint (its shape: url, fingerprint with colons, configured, hardware)."""
    body = b''
    status = 200

    def do_GET(self):
        if self.status == 302:
            self.send_response(302)
            self.send_header('Location', 'http://192.0.2.99/')
            self.end_headers()
            return
        self.send_response(self.status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


class SetupServer:
    """Mixin: serve() starts a fake setup endpoint on a free port of this computer's loopback and returns its URL."""

    def serve(self, body=b'', status=200):
        handler = type('Handler', (FakeSetup,), {'body': body, 'status': status})
        server = HTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_address[1]}/api/setup'


class SetupEndpointTests(SetupServer, unittest.TestCase):
    def test_it_reads_the_address_and_the_fingerprint_and_nothing_else(self):
        reply = json.dumps({'url': FICTIONAL_URL, 'fingerprint': FICTIONAL_PIN_COLONS, 'configured': True,
                            'hardware': {'cpu_load': True, 'disks': 3}}).encode()
        url, fingerprint = app.fetch_setup(self.serve(reply))
        self.assertEqual((app.parse_origin(url)[0], app.parse_fingerprint(fingerprint)), (FICTIONAL_URL, FICTIONAL_PIN))

    def test_bad_answers_are_refused_with_a_reason(self):
        for body, status in ((b'not json', 200), (b'{}', 200), (b'[]', 200), (b'x' * (app.SETUP_LIMIT + 10), 200), (b'{}', 302)):
            with self.assertRaises(app.BuildError, msg=(body[:20], status)):
                app.fetch_setup(self.serve(body, status))

    def test_it_only_ever_talks_to_this_computer(self):
        for address in ('http://192.168.1.21:8666/api/setup', 'https://127.0.0.1:8666/api/setup', 'http://example.com/api/setup'):
            with self.assertRaisesRegex(app.BuildError, 'on this computer'):
                app.fetch_setup(address)
        free = HTTPServer(('127.0.0.1', 0), FakeSetup)
        port = free.server_address[1]
        free.server_close()
        with self.assertRaisesRegex(app.BuildError, 'does not answer'):
            app.fetch_setup(f'http://127.0.0.1:{port}/api/setup', timeout=1)


GUARD_CHECK = r'''
package app.aidesk.tablet;

public final class GuardCheck {
    static int failures = 0;

    static void expect(boolean wanted, boolean actual, String what) {
        if (wanted != actual) {
            failures++;
            System.out.println("WRONG: " + what);
        }
    }

    static void expect(boolean ok, String what) {
        expect(true, ok, what);
    }

    public static void main(String[] args) throws Exception {
        String origin = "https://192.168.1.21:8667";
        String[] inside = {"https://192.168.1.21:8667", "https://192.168.1.21:8667/", "https://192.168.1.21:8667/app.js",
                "https://192.168.1.21:8667/?x=1#y", "https://192.168.1.21:8667?x=1", "HTTPS://192.168.1.21:8667/Login"};
        for (String url : inside) expect(true, Guard.sameOrigin(origin, url), "inside " + url);
        String[] outside = {"http://192.168.1.21:8667/", "https://192.168.1.21:8668/", "https://192.168.1.21:86670/",
                "https://192.168.1.21:8667@evil.example/", "https://192.168.1.21:8667.evil.example/", "https://192.168.1.21:8667\\@evil.example/",
                "https://192.168.1.21:8667:80/", "https://evil.example/", "https://192.168.1.22:8667/", "https://192.168.1.21/", "",
                "javascript:alert(1)", "about:blank", "data:text/html,x", "file:///etc/passwd", "intent://x#Intent;end", " https://192.168.1.21:8667/",
                "https://192.168.1.21:8667 /", "https:///192.168.1.21:8667/", "https://192.168.1.2:8667/", "https://192.168.1.21:866", "https://192.168.1.21"};
        for (String url : outside) expect(false, Guard.sameOrigin(origin, url), "outside " + url);
        expect(false, Guard.sameOrigin(origin, null), "null url");
        expect(false, Guard.sameOrigin(null, origin), "null origin");
        expect(false, Guard.sameOrigin("", origin), "empty origin");
        expect(true, Guard.sameOrigin("https://kiosk.example", "https://KIOSK.example/x"), "ascii case");
        expect(false, Guard.sameOrigin("https://kiosk.example", "https://Kiosk.example/"), "kelvin sign is not k");
        expect(false, Guard.sameOrigin("https://kiosk.example", "https://kİosk.example/"), "dotted capital i is not i");
        expect(false, Guard.sameOrigin("https://kiosk.example", "https://kiosk.example.evil/"), "suffix host");
        expect(true, Guard.sameOrigin("https://10.0.0.5", "https://10.0.0.5/x"), "default port");
        expect(false, Guard.sameOrigin("https://10.0.0.5", "https://10.0.0.5:8443/x"), "other port than default");

        byte[] der = "abc".getBytes("UTF-8");
        String pin = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        expect(true, Guard.matchesPin(der, pin), "right pin");
        expect(true, Guard.matchesPin(der, pin.toUpperCase()), "upper-case pin");
        expect(false, Guard.matchesPin(der, pin.substring(0, 63) + "e"), "last digit changed");
        expect(false, Guard.matchesPin("abd".getBytes("UTF-8"), pin), "other certificate");
        expect(false, Guard.matchesPin(null, pin), "no certificate");
        expect(false, Guard.matchesPin(new byte[0], pin), "empty certificate");
        expect(false, Guard.matchesPin(der, null), "no pin");
        expect(false, Guard.matchesPin(der, ""), "empty pin");
        expect(false, Guard.matchesPin(der, pin.substring(2)), "short pin");
        expect(false, Guard.matchesPin(der, pin + "00"), "long pin");
        expect(false, Guard.matchesPin(der, "g" + pin.substring(1)), "not hex");
        expect(false, Guard.matchesPin(der, "１" + pin.substring(1)), "fullwidth digit is not hex");
        expect(true, Guard.parseHex("00ff") != null && Guard.parseHex("00ff").length == 2, "parseHex");
        expect(false, Guard.parseHex("0") != null, "odd hex");

        // setBrightness: -1 hands control back, 0.02 to 1.0 passes as it is, anything else is ignored (NaN): nothing is cut into range,
        // because WebView turns a value of the wrong type (undefined, a string, null) into 0 and that must never become "the dimmest backlight".
        expect(Guard.brightness(-1.0) == -1f, "-1 follows the system");
        expect(Guard.brightness(0.5) == 0.5f, "0.5 as it is");
        expect(Guard.brightness(1.0) == 1f, "1.0 as it is");
        expect(Guard.brightness(0.02) == 0.02f, "0.02 as it is");
        expect(Guard.brightness(2.0 / 100.0) == 0.02f, "2 percent computed as 2/100 is exactly 0.02");
        expect(Guard.brightness(25.0 / 100.0) == 0.25f, "25 percent computed as 25/100");
        expect(Guard.brightness(100.0 / 100.0) == 1f, "100 percent computed as 100/100");
        expect(Float.isNaN(Guard.brightness(0.0)), "0 (what a wrong type arrives as) is ignored, never 'the dimmest'");
        expect(Float.isNaN(Guard.brightness(0.0199)), "just below the lowest level is ignored");
        expect(Float.isNaN(Guard.brightness(0.001)), "tiny is ignored");
        expect(Float.isNaN(Guard.brightness(1.0001)), "just above 1 is ignored");
        expect(Float.isNaN(Guard.brightness(7.0)), "above 1 is ignored");
        expect(Float.isNaN(Guard.brightness(Double.MAX_VALUE)), "huge is ignored");
        expect(Float.isNaN(Guard.brightness(Double.NaN)), "NaN is ignored");
        expect(Float.isNaN(Guard.brightness(-0.5)), "a negative level is ignored");
        expect(Float.isNaN(Guard.brightness(-2.0)), "another negative level is ignored");
        expect(Float.isNaN(Guard.brightness(-1.0000001)), "almost -1 is not -1");
        expect(Float.isNaN(Guard.brightness(Double.POSITIVE_INFINITY)), "+infinity is ignored");
        expect(Float.isNaN(Guard.brightness(Double.NEGATIVE_INFINITY)), "-infinity is ignored");

        // vibrate: 1 to 500 ms, a longer ask is cut, anything unusable is 0 (ignored).
        expect(Guard.vibrationMillis(1.0) == 1L, "1 ms");
        expect(Guard.vibrationMillis(120.9) == 120L, "fraction truncated");
        expect(Guard.vibrationMillis(500.0) == 500L, "500 ms");
        expect(Guard.vibrationMillis(501.0) == 500L, "501 is cut");
        expect(Guard.vibrationMillis(1.0e9) == 500L, "huge is cut");
        expect(Guard.vibrationMillis(0.99) == 0L, "below 1 is ignored");
        expect(Guard.vibrationMillis(0.0) == 0L, "0 is ignored");
        expect(Guard.vibrationMillis(-5.0) == 0L, "negative is ignored");
        expect(Guard.vibrationMillis(Double.NaN) == 0L, "NaN is ignored");
        expect(Guard.vibrationMillis(Double.POSITIVE_INFINITY) == 0L, "infinity is ignored");
        expect(Guard.vibrationMillis(Double.NEGATIVE_INFINITY) == 0L, "-infinity is ignored");

        // battery: JSON text, or "" when there is no usable level.
        expect("{\"percent\":87,\"charging\":true}".equals(Guard.batteryJson(87, 100, true)), "87 charging");
        expect("{\"percent\":0,\"charging\":false}".equals(Guard.batteryJson(0, 100, false)), "empty is 0, not unknown");
        expect("{\"percent\":100,\"charging\":true}".equals(Guard.batteryJson(100, 100, true)), "full");
        expect("{\"percent\":33,\"charging\":false}".equals(Guard.batteryJson(1, 3, false)), "a third rounds down");
        expect("{\"percent\":67,\"charging\":false}".equals(Guard.batteryJson(2, 3, false)), "two thirds rounds up");
        expect("{\"percent\":25,\"charging\":false}".equals(Guard.batteryJson(50, 200, false)), "another scale");
        expect("{\"percent\":100,\"charging\":false}".equals(Guard.batteryJson(120, 100, false)), "never above 100");
        expect("".equals(Guard.batteryJson(-1, 100, true)), "no level is unknown");
        expect("".equals(Guard.batteryJson(50, 0, true)), "no scale is unknown");
        expect("".equals(Guard.batteryJson(50, -1, true)), "a negative scale is unknown");

        // light: one decimal; -1 for no usable reading; 0 lux is a real reading.
        expect(Guard.lux(12.34f) == 12.3, "one decimal");
        expect(Guard.lux(0f) == 0.0, "0 lux is a reading");
        expect(Guard.lux(-1f) == -1.0, "the 'no reading yet' value");
        expect(Guard.lux(Float.NaN) == -1.0, "NaN is no reading");
        expect(Guard.lux(Float.POSITIVE_INFINITY) == -1.0, "infinity is no reading");
        expect(Guard.lux(-3f) == -1.0, "negative is no reading");
        expect(Guard.lux(40000f) == 40000.0, "daylight");
        String digest = "315b9c6aa37d9d08175173ee8f8d0ec2edd0a45d1d9ed0f057c1dc1e4832fae6";
        expect(digest.equals(Guard.sha256Hex(digest)), "a lower-case SHA-256 is kept");
        expect(digest.equals(Guard.sha256Hex(digest.toUpperCase())), "an upper-case SHA-256 is lower-cased");
        for (String bad : new String[] {null, "", "abc", digest.substring(1), digest + "0", "zz" + digest.substring(2), digest.replace('3', ' ')}) {
            expect(Guard.sha256Hex(bad) == null, "not a SHA-256: " + bad);
        }
        byte[] sample = "an apk".getBytes();
        String sampleHash = "ac9a9bc5ba51b0e0a45dfc2e3cb7a2de1e4cd3a0d0c4d1a4b0cd2b9e5f3a8a11";
        try {
            byte[] real = java.security.MessageDigest.getInstance("SHA-256").digest(sample);
            StringBuilder hex = new StringBuilder();
            for (byte b : real) { hex.append(String.format("%02x", b)); }
            sampleHash = hex.toString();
        } catch (java.security.GeneralSecurityException e) {
            expect(false, "SHA-256 exists");
        }
        expect(Guard.updateMatches(sample, sampleHash), "the right bytes match their hash");
        expect(Guard.updateMatches(sample, sampleHash.toUpperCase()), "the hash may be upper case");
        expect(!Guard.updateMatches("another".getBytes(), sampleHash), "other bytes do not match");
        expect(!Guard.updateMatches(sample, digest), "a different hash does not match");
        expect(!Guard.updateMatches(null, sampleHash), "no bytes never match");
        expect(!Guard.updateMatches(new byte[0], sampleHash), "empty never matches");
        expect(!Guard.updateMatches(sample, "not a hash"), "a bad hash never matches");
        expect(!Guard.updateMatches(new byte[Guard.MAX_UPDATE_BYTES + 1], sampleHash), "an oversized update is refused before it is hashed");
        System.out.println(failures == 0 ? "GUARD OK" : "GUARD FAILED " + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
'''

LOADER_CHECK = r'''
package app.aidesk.tablet;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

public final class LoaderCheck {
    static int failures = 0;

    static void expect(boolean ok, String what) {
        if (!ok) {
            failures++;
            System.out.println("WRONG: " + what);
        }
    }

    /** A host with a virtual clock: tasks run when advance() reaches their time. */
    static final class FakeHost implements Loader.Host {
        long now = 0;
        final List<Object[]> tasks = new ArrayList<>();   // {due time, Runnable}
        Loader.Screen screen = null;
        boolean covered = true;
        int loads = 0;
        int stops = 0;

        public void load() { loads++; }
        public void stopLoading() { stops++; }
        public void showScreen(Loader.Screen s) { screen = s; covered = true; }
        public void hideScreen() { covered = false; }
        public void schedule(Runnable task, long delayMs) { tasks.add(new Object[] {now + delayMs, task}); }
        public void unschedule(Runnable task) {
            for (int i = tasks.size() - 1; i >= 0; i--) {
                if (tasks.get(i)[1] == task) tasks.remove(i);
            }
        }

        void advance(long ms) {
            long end = now + ms;
            while (true) {
                Object[] next = null;
                for (Object[] t : tasks) {
                    if ((Long) t[0] <= end && (next == null || (Long) t[0] < (Long) next[0])) next = t;
                }
                if (next == null) break;
                tasks.remove(next);
                now = (Long) next[0];
                ((Runnable) next[1]).run();
            }
            now = end;
        }
    }

    static Loader.State s(Loader l) { return l.state(); }

    public static void main(String[] args) {
        // 1. A first start covers the page and tries once.
        FakeHost h = new FakeHost();
        Loader l = new Loader(h);
        l.start();
        expect(h.loads == 1 && s(l) == Loader.State.LOADING && h.covered && h.screen == Loader.Screen.CONNECTING, "first start");
        expect(h.tasks.size() == 1, "only the load limit is pending");
        l.pageStarted();
        l.loaded();
        expect(s(l) == Loader.State.LIVE && !h.covered && h.tasks.isEmpty(), "loaded uncovers and cancels timers");
        l.loaded();
        expect(s(l) == Loader.State.LIVE && h.loads == 1, "a second 'loaded' changes nothing");

        // 2. A failure waits ten seconds, then tries again; success uncovers.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.fail(false);
        expect(s(l) == Loader.State.WAITING && h.covered && h.screen == Loader.Screen.WAITING && h.tasks.size() == 1, "failed attempt waits");
        h.advance(Loader.RETRY_MS - 1);
        expect(h.loads == 1, "no retry before ten seconds");
        h.advance(1);
        expect(h.loads == 2 && s(l) == Loader.State.LOADING && h.screen == Loader.Screen.WAITING, "retry at ten seconds keeps saying waiting");
        l.pageStarted();
        l.loaded();
        expect(s(l) == Loader.State.LIVE && !h.covered, "retry succeeds");

        // 3. More errors of the same outage do not push the retry away.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.fail(false);
        h.advance(5000);
        l.fail(false);
        l.fail(false);
        expect(h.tasks.size() == 1, "still one retry pending");
        h.advance(5000);
        expect(h.loads == 2, "the retry came at ten seconds after the first failure");

        // 4. Chromium's 'finished' for its own error page must not uncover the failure.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.fail(false);
        l.loaded();
        expect(s(l) == Loader.State.WAITING && h.covered, "finished after a failure is ignored");

        // 5. A certificate failure says so, keeps saying it across the retry, and clears when the next attempt fails otherwise.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.fail(true);
        l.fail(false);
        expect(h.screen == Loader.Screen.CERTIFICATE, "certificate screen, even when a plain error follows");
        h.advance(Loader.RETRY_MS);
        expect(h.loads == 2 && h.screen == Loader.Screen.CERTIFICATE, "no flicker while the next attempt runs");
        l.pageStarted();
        l.fail(false);
        expect(h.screen == Loader.Screen.WAITING, "a plain failure of the next attempt replaces the certificate message");
        h.advance(Loader.RETRY_MS);
        l.pageStarted();
        l.loaded();
        expect(s(l) == Loader.State.LIVE && !h.covered, "recovers");
        l.fail(true);
        expect(h.covered && h.screen == Loader.Screen.CERTIFICATE && s(l) == Loader.State.WAITING, "a page that shows covers itself when the pin fails");
        h.advance(Loader.RETRY_MS);
        expect(h.loads == 4, "and tries again");

        // 6. An attempt that shows nothing is stopped at the limit and retried.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        h.advance(Loader.LOAD_LIMIT_MS - 1);
        expect(h.stops == 0 && s(l) == Loader.State.LOADING, "not before the limit");
        h.advance(1);
        expect(h.stops == 1 && s(l) == Loader.State.WAITING && h.screen == Loader.Screen.WAITING, "stopped at the limit");
        h.advance(Loader.RETRY_MS);
        expect(h.loads == 2, "retried ten seconds later");

        // 7. Wi-Fi back: at once when waiting, never otherwise.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.networkAvailable();
        expect(h.loads == 1, "ignored while an attempt runs");
        l.fail(false);
        l.networkAvailable();
        expect(h.loads == 2 && s(l) == Loader.State.LOADING && h.tasks.size() == 1, "immediate retry replaces the timer");
        l.pageStarted();
        l.loaded();
        l.networkAvailable();
        expect(h.loads == 2 && s(l) == Loader.State.LIVE, "ignored while the page shows");

        // 8. Away from the screen: no timers; back: a page that is not showing starts again, one that shows is left alone.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.pause();
        h.advance(120_000);
        expect(h.loads == 1 && h.stops == 0 && h.tasks.isEmpty(), "nothing runs while paused");
        l.resume();
        expect(h.loads == 2 && s(l) == Loader.State.LOADING, "resume restarts a page that was not showing");
        l.loaded();
        l.pause();
        l.resume();
        expect(h.loads == 2 && s(l) == Loader.State.LIVE && !h.covered, "resume leaves a showing page alone");

        // 9. A page that was showing and then fails is covered and retried.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.loaded();
        l.fail(false);
        expect(h.covered && s(l) == Loader.State.WAITING, "covered when a live page fails");
        h.advance(Loader.RETRY_MS);
        l.pageStarted();
        l.loaded();
        expect(!h.covered && s(l) == Loader.State.LIVE, "uncovered again");

        // 11. WebView does not say which attempt an event belongs to. The error page of attempt 1 can report 'finished' after attempt 2 was
        // started: that must not uncover the screen. Only a navigation that has really begun (pageStarted) can be shown.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.pageStarted();
        l.fail(false);
        h.advance(Loader.RETRY_MS);
        expect(h.loads == 2 && s(l) == Loader.State.LOADING, "attempt 2 started");
        l.loaded();
        expect(s(l) == Loader.State.LOADING && h.covered && h.tasks.size() == 1, "a late 'finished' of attempt 1 does not uncover, the limit still runs");
        l.pageStarted();
        l.loaded();
        expect(s(l) == Loader.State.LIVE && !h.covered && h.tasks.isEmpty(), "attempt 2 shows once it really began");

        // 12. A late failure of attempt 1 does not poison attempt 2.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.pageStarted();
        l.fail(false);
        h.advance(Loader.RETRY_MS);
        l.fail(false);
        expect(s(l) == Loader.State.WAITING && h.covered && h.tasks.size() == 1, "the late failure covers and keeps one retry pending");
        l.pageStarted();
        l.loaded();
        expect(s(l) == Loader.State.LIVE && !h.covered && h.tasks.isEmpty(), "attempt 2 still shows, and the retry is cancelled");

        // 13. While the app is away nothing is armed, even when an attempt that was in flight fails afterwards; back on screen it tries once.
        h = new FakeHost();
        l = new Loader(h);
        l.start();
        l.pageStarted();
        l.pause();
        l.fail(false);
        expect(s(l) == Loader.State.WAITING && h.covered && h.tasks.isEmpty(), "a failure while away arms no retry");
        h.advance(120_000);
        l.networkAvailable();
        expect(h.loads == 1, "nothing loads while away, not even when Wi-Fi comes back");
        l.start();
        expect(h.loads == 1 && h.covered && h.tasks.isEmpty() && s(l) == Loader.State.LOADING, "a start while away only covers the page");
        l.resume();
        expect(h.loads == 2 && h.tasks.size() == 1 && s(l) == Loader.State.LOADING, "back on screen: one attempt");

        // 10. Fuzz, with every event in any order: the page is covered exactly when it is not LIVE, there is never more than one timer, no timer
        // while it shows or while the app is away, and once the app is on screen again the page either shows or a timer guarantees another attempt.
        for (int seed = 0; seed < 300; seed++) {
            Random random = new Random(seed);
            h = new FakeHost();
            l = new Loader(h);
            boolean away = false;
            l.start();
            for (int step = 0; step < 400; step++) {
                switch (random.nextInt(10)) {
                    case 0: l.start(); break;
                    case 1: l.loaded(); break;
                    case 2: l.fail(random.nextBoolean()); break;
                    case 3: l.networkAvailable(); break;
                    case 4: l.pause(); away = true; break;
                    case 5: l.resume(); away = false; break;
                    case 6: l.pageStarted(); break;
                    default: h.advance(random.nextInt(14_000)); break;
                }
                boolean live = s(l) == Loader.State.LIVE;
                expect(h.covered == !live, "seed " + seed + " step " + step + ": covered exactly when not live");
                expect(h.tasks.size() <= 1, "seed " + seed + " step " + step + ": at most one timer");
                if (live) {
                    expect(h.tasks.isEmpty(), "seed " + seed + " step " + step + ": no timer while the page shows");
                }
                if (away) {
                    expect(h.tasks.isEmpty(), "seed " + seed + " step " + step + ": no timer while the app is away");
                }
            }
            l.resume();
            expect(s(l) == Loader.State.LIVE || h.tasks.size() == 1, "seed " + seed + ": an attempt or a timer always exists once on screen");
        }
        System.out.println(failures == 0 ? "LOADER OK" : "LOADER FAILED " + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
'''


@unittest.skipUnless(TOOLS, 'no Android SDK / JDK on this computer')
class ToolchainTests(SetupServer, unittest.TestCase):
    def run_on_a_jvm(self, name, check_source, *sources):
        """Compile some of the shell's plain-Java classes with a check program and run it on the desktop JVM; returns its output."""
        with app.workspace(TOOLS) as work:
            folder = work / 'app/aidesk/tablet'
            folder.mkdir(parents=True)
            files = []
            for file_name, text in (*sources, (name + '.java', check_source)):
                (folder / file_name).write_text(text, encoding='utf-8')
                files.append(folder / file_name)
            classes = work / 'classes'
            classes.mkdir()
            app.call(TOOLS.javac, '--release', '11', '-encoding', 'UTF-8', '-d', classes, *files, label='javac', cwd=work)
            return app.call(TOOLS.java, '-cp', classes, 'app.aidesk.tablet.' + name, label=name, cwd=work)

    def test_the_trust_checks_and_the_bridge_rules_run_on_a_desktop_jvm(self):
        output = self.run_on_a_jvm('GuardCheck', GUARD_CHECK, ('Guard.java', GUARD))
        self.assertEqual(output.splitlines()[-1], 'GUARD OK', output)

    def test_the_loading_and_retry_logic_runs_on_a_desktop_jvm(self):
        """Never a blank screen: covered unless showing, one timer, a retry every ten seconds, fuzzed with 300 random event orders."""
        output = self.run_on_a_jvm('LoaderCheck', LOADER_CHECK, ('Loader.java', LOADER))
        self.assertEqual(output.splitlines()[-1], 'LOADER OK', output)

    def test_relative_folders_are_made_absolute_for_tools_that_run_elsewhere(self):
        """The Windows tools run in another folder: a relative --sdk or --keystore-dir would silently point nowhere."""
        import os
        previous = os.getcwd()
        try:
            os.chdir(TOOLS.sdk.parent)
            relative = app.find_toolchain(sdk=TOOLS.sdk.name)
            self.assertEqual(relative.sdk, TOOLS.sdk)
            self.assertTrue(relative.aapt2.path.is_absolute() and relative.java.path.is_absolute())
            with tempfile.TemporaryDirectory() as directory:
                os.chdir(directory)
                store, password = app.ensure_signing_key(TOOLS, Path('relative-keys'), 'release')
                self.assertTrue(store.is_absolute() and password.is_absolute())
                self.assertEqual(store.parent, Path(directory).resolve() / 'relative-keys')
                self.assertTrue(store.is_file() and password.is_file())
                os.chdir(previous)
        finally:
            os.chdir(previous)

    def test_a_real_release_build_and_a_debug_build(self):
        build_folders = []   # every scratch folder this test's builds create, to prove they are removed

        @contextlib.contextmanager
        def recording_workspace(tools):
            with real_workspace(tools) as work:
                build_folders.append(work)
                yield work

        real_workspace = app.workspace
        with mock.patch.object(app, 'workspace', recording_workspace), \
                tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as keys:
            out, keys = Path(out), Path(keys) / 'signing'
            release = app.build(FICTIONAL_URL, FICTIONAL_PIN_COLONS, out_dir=out, keystore_dir=keys, tools=TOOLS)
            apk = out / 'ai-desk-tablet.apk'
            self.assertEqual(release['version_code'], 1)
            self.assertEqual(release['version_name'], f'{app.BRIDGE_CONTRACT}.1')
            self.assertEqual(release['file'], 'ai-desk-tablet.apk')
            self.assertEqual(release['host'], '192.0.2.10')
            self.assertEqual(release['sha256'], hashlib.sha256(apk.read_bytes()).hexdigest())
            self.assertEqual(json.loads((out / 'ai-desk-tablet.apk.json').read_text()), release)
            self.assertEqual((out / app.COUNTER_NAME).read_text().strip(), '1')
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['ai-desk-tablet.apk', 'ai-desk-tablet.apk.json', app.COUNTER_NAME])
            self.assertEqual(stat.S_IMODE(apk.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(keys.stat().st_mode), 0o700)
            self.assertEqual(sorted(p.name for p in keys.iterdir()), ['release.p12', 'release.pass'])
            self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in keys.iterdir()))

            # An independent look at the finished file, not the build's own report.
            report = app.java_jar(TOOLS, TOOLS.apksigner_jar, 'verify', '--verbose', '--print-certs', apk, label='apksigner verify')
            self.assertTrue(report.startswith('Verifies'), report)
            self.assertIn('Verified using v2 scheme (APK Signature Scheme v2): true', report)
            self.assertIn('Number of signers: 1', report)
            self.assertIn(release['signer_sha256'], report)
            badging = app.call(TOOLS.aapt2, 'dump', 'badging', apk, label='aapt2 dump badging')
            self.assertIn("package: name='app.aidesk.tablet' versionCode='1' versionName='1.1'", badging)
            self.assertIn("minSdkVersion:'26'", badging)
            self.assertIn("targetSdkVersion:'35'", badging)
            self.assertIn("application-label:'AI Desk'", badging)
            self.assertIn("launchable-activity: name='app.aidesk.tablet.MainActivity'", badging)
            self.assertEqual(sorted(re.findall(r"uses-permission: name='([^']+)'", badging)), sorted(app.PERMISSIONS))
            manifest = app.call(TOOLS.aapt2, 'dump', 'xmltree', '--file', 'AndroidManifest.xml', apk, label='aapt2 dump xmltree')
            self.assertEqual(len(re.findall(r'exported\(0x[0-9a-f]+\)=true', manifest)), 1)
            self.assertEqual(re.findall(r'E: (activity|service|receiver|provider)\b', manifest), ['activity'])
            self.assertIn('usesCleartextTraffic(0x010104ec)=false', manifest)
            self.assertIn('allowBackup(0x01010280)=false', manifest)
            self.assertNotRegex(manifest, r'debuggable\(0x[0-9a-f]+\)=true')
            with zipfile.ZipFile(apk) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())
                dex = archive.read('classes.dex')
                arsc = archive.read('resources.arsc')
                self.assertEqual(archive.getinfo('resources.arsc').compress_type, zipfile.ZIP_STORED, 'Android 11+ needs resources.arsc stored')
            self.assertTrue({'AndroidManifest.xml', 'resources.arsc', 'classes.dex'} <= names)
            self.assertTrue(any(n.startswith('res/mipmap-anydpi-v26/') for n in names))
            app.call(TOOLS.zipalign, '-c', '-p', '4', apk, label='zipalign -c')   # still aligned after signing (resources.arsc on 4 bytes)
            if TOOLS.dexdump is not None:   # what Android's WebView will hand to the page: exactly the contract, at runtime visibility
                self.assertEqual(app.bridge_methods_in_dex(TOOLS, apk), sorted(name for _, name, _ in CONTRACT))
            # The one build's address and fingerprint are inside the code, and the strings of both languages inside the resources.
            self.assertIn(FICTIONAL_PIN.encode(), dex)
            self.assertIn(FICTIONAL_URL.encode(), dex)
            self.assertIn(b'AiDeskApp', dex)
            text = arsc.replace(b'\x00', b'')   # the string pool is UTF-8 or UTF-16: dropping the NULs reads both
            self.assertIn(b'Waiting for the PC...', text)
            self.assertIn(b'Esperando al PC...', text)

            # A debug build: its own key, its own file name, debuggable, and the release file is untouched.
            before = apk.read_bytes()
            debug = app.build(FICTIONAL_URL, FICTIONAL_PIN, out_dir=out, keystore_dir=keys, debug=True, tools=TOOLS)
            self.assertEqual(debug['file'], 'ai-desk-tablet-debug.apk')
            self.assertEqual(debug['version_code'], 2, 'the counter is shared, so a newer build never has a lower code')
            self.assertTrue(debug['debug'])
            self.assertNotEqual(debug['signer_sha256'], release['signer_sha256'], 'a debuggable app never uses the release key')
            self.assertEqual(apk.read_bytes(), before)
            self.assertEqual(json.loads((out / 'ai-desk-tablet.apk.json').read_text()), release)
            manifest = app.call(TOOLS.aapt2, 'dump', 'xmltree', '--file', 'AndroidManifest.xml', out / 'ai-desk-tablet-debug.apk',
                                label='aapt2 dump xmltree')
            self.assertRegex(manifest, r'debuggable\(0x[0-9a-f]+\)=true')
            self.assertEqual(sorted(p.name for p in keys.iterdir()), ['debug.p12', 'debug.pass', 'release.p12', 'release.pass'])

            # The way the orchestrator runs it: no address given, so the setup endpoint (here a fake one on this computer's loopback)
            # supplies it. A second release build reuses the key (an update installs over the first) and moves the version on.
            reply = json.dumps({'url': FICTIONAL_URL, 'fingerprint': FICTIONAL_PIN_COLONS, 'configured': True, 'hardware': {}}).encode()
            with contextlib.redirect_stdout(io.StringIO()) as shown:
                code = app.main(['--setup-url', self.serve(reply), '--out', str(out), '--keystore-dir', str(keys)])
            self.assertEqual(code, 0, shown.getvalue())
            again = json.loads((out / 'ai-desk-tablet.apk.json').read_text())
            self.assertEqual(again['version_code'], 3)
            self.assertEqual(again['signer_sha256'], release['signer_sha256'])
            self.assertNotEqual(again['sha256'], release['sha256'])
            self.assertIn(again['sha256'], shown.getvalue())
            self.assertNotIn((keys / 'release.pass').read_text().strip(), shown.getvalue(), 'the signing password is never printed')
        self.assertGreaterEqual(len(build_folders), 3, 'at least one folder for each of the three builds')
        self.assertFalse([p for p in build_folders if p.exists()], 'the temporary build folders are removed')

    def test_a_build_that_fails_its_checks_writes_nothing(self):
        """One bridge method that loses its @JavascriptInterface would simply be invisible to the page: the build must refuse it,
        publish nothing and leave the version counter alone."""
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as keys, tempfile.TemporaryDirectory() as broken:
            source = Path(broken) / 'android'
            shutil.copytree(app.ANDROID, source)
            bridge = source / 'src/app/aidesk/tablet/Bridge.java'
            text = bridge.read_text(encoding='utf-8')
            damaged = text.replace('@JavascriptInterface\n    public double light()', 'public double light()')
            self.assertNotEqual(damaged, text)
            bridge.write_text(damaged, encoding='utf-8')
            if TOOLS.dexdump is None:
                self.skipTest('this SDK has no dexdump')
            with self.assertRaises(app.BuildError) as raised:
                app.build(FICTIONAL_URL, FICTIONAL_PIN, out_dir=Path(out), keystore_dir=Path(keys) / 'signing', tools=TOOLS, source=source)
            self.assertIn('does not match what was asked for', str(raised.exception))
            self.assertIn('the bridge exposes', str(raised.exception))
            self.assertEqual(list(Path(out).iterdir()), [], 'nothing is published and the version counter did not move')


if __name__ == '__main__':
    unittest.main()
