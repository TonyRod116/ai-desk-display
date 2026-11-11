"""A separate read-only, password-protected tablet companion on a private LAN."""
from __future__ import annotations

import argparse
import collections
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from token_tv import tablet_live
from token_tv.tablet_history import MetricsHistory
from token_tv.tablet_metrics import collect
from token_tv.tablet_settings import Settings
from token_tv.tablet_snapshot import tablet_snapshot

WEB = Path(__file__).with_name('tablet_web')
PRIVATE = Path.home() / '.local/share/ai-desk-display/tablet'
AUTH_FILE = 'tablet-auth.json'
SESSION_SECONDS = 90 * 24 * 3600
RATE_SECONDS = 600
MAX_ATTEMPTS = 5
DATA_LIMIT = 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 48 * 1024 * 1024
REPORTS_FILE = 'tablet-reports.json'
SETTINGS_FILE = 'tablet-settings.json'
REPORT_KEEP = 40
_STATIC = {
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/access.css': ('access.css', 'text/css; charset=utf-8'),
    '/login.js': ('login.js', 'text/javascript; charset=utf-8'),
    '/setup.js': ('setup.js', 'text/javascript; charset=utf-8'),
    '/assets/city.png': ('@city.png', 'image/png'),
    '/assets/paradise.png': ('@paradise.png', 'image/png'),
}
# The page's own scripts and styles (the scene stage and its renderers) are served by name from the package, never from a listing
# of a writable folder. Sign-in and setup keep their own, narrower rules.
_PACKAGE_TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'}
for _file in sorted(WEB.glob('*')):
    if (_file.suffix in _PACKAGE_TYPES and _file.name not in ('login.js', 'setup.js', 'access.css')
            and re.fullmatch(r'[a-z0-9-]{1,40}\.(js|css)', _file.name)):
        _STATIC.setdefault('/' + _file.name, (_file.name, _PACKAGE_TYPES[_file.suffix]))
SCENES = ('city', 'paradise', 'surf', 'token-run', 'city-iso', 'fighting',
          'neon-city', 'neon-district', 'violet-horizon',
          'infinite-express', 'midnight-video-club')
# Internal time-of-day variants are assets, not separate choices or settings.
EXPRESS_VARIANTS = tuple('infinite-express-' + part for part in ('dawn', 'day', 'dusk', 'night'))
HOUSE_VARIANTS = tuple('midnight-video-club-' + part for part in ('dawn', 'day', 'dusk', 'night'))
MOUNTAIN_VARIANTS = tuple('neon-district-' + part for part in ('dawn', 'day', 'dusk', 'night'))
# What a prepared scene may consist of: a picture or a looping VP8 video, and always a small thumbnail.
ASSET_TYPES = {'webp': 'image/webp', 'webm': 'video/webm', 'jpg': 'image/jpeg', 'png': 'image/png', 'json': 'application/json'}
MEDIA_EXTENSIONS = ('webp', 'webm', 'jpg', 'png')             # what a scene's picture or film may be
SCENE_EXTENSIONS = {'scene': MEDIA_EXTENSIONS + ('json',), 'thumb': ('webp',)}      # a game scene also has its atlas data (frames) as scene-<name>.json
for _scene in SCENES + EXPRESS_VARIANTS + HOUSE_VARIANTS + MOUNTAIN_VARIANTS:
    for _kind, _extensions in SCENE_EXTENSIONS.items():
        for _ext in _extensions:
            _file_name = f'{_kind}-{_scene}.{_ext}'
            _STATIC[f'/assets/{_file_name}'] = ('@' + _file_name, ASSET_TYPES[_ext])
PHOTO_COUNT = 40
PHOTOS_MANIFEST = 'photos.json'
APK_NAME = 'ai-desk-tablet.apk'
for _number_ in range(1, PHOTO_COUNT + 1):                  # the photo frame: Tony's own pictures, prepared offline, fixed names only
    _STATIC[f'/assets/photo-{_number_:02d}.jpg'] = (f'@photo-{_number_:02d}.jpg', 'image/jpeg')
_PUBLIC = {'/login', '/login.js', '/access.css'}
MANIFEST = 'scenes.json'
LOOKS = ('crt', 'lcd', 'photo', 'plain', 'game')


_BUILD = {'at': 0.0, 'value': ''}


def build_id(directory=None):
    """Tag page files and the scene catalog so installed scenes trigger a refresh."""
    now = time.monotonic()
    try:
        info = (Path(directory) / MANIFEST).stat() if directory is not None else None
        scene_tag = (str(directory), info.st_ino, info.st_size, info.st_mtime_ns) if info else (str(directory), None)
    except OSError:
        scene_tag = (str(directory), None)
    if now - _BUILD['at'] < 2 and _BUILD['value'] and _BUILD.get('scenes') == scene_tag:
        return _BUILD['value']
    digest = hashlib.sha1()
    digest.update(repr(scene_tag).encode())
    for name, (file, _kind) in sorted(_STATIC.items()):
        if file.startswith('@'):
            continue
        try:
            info = (WEB / file).stat()
            digest.update(f'{name}:{info.st_size}:{info.st_mtime_ns};'.encode())
        except OSError:
            digest.update(f'{name}:missing;'.encode())
    for extra in ('index.html', 'login.html'):
        try:
            info = (WEB / extra).stat()
            digest.update(f'{extra}:{info.st_size}:{info.st_mtime_ns};'.encode())
        except OSError:
            pass
    _BUILD.update(at=now, value=digest.hexdigest()[:12], scenes=scene_tag)
    return _BUILD['value']


def _size_ok(path, limit):
    try:
        return path.is_file() and 0 < path.stat().st_size <= limit
    except OSError:
        return False


def _limit(name):
    return MAX_VIDEO_BYTES if name.endswith('.webm') else MAX_IMAGE_BYTES


def prepared_scenes(directory):
    """Expose only fixed, completely prepared scenes (a thumbnail and a picture or video), not a file listing."""
    directory = Path(directory)
    result = []
    for scene in SCENES:
        if not _size_ok(directory / f'thumb-{scene}.webp', MAX_IMAGE_BYTES):
            continue
        if any(_size_ok(directory / f'scene-{scene}.{ext}', _limit(f'scene-{scene}.{ext}')) for ext in MEDIA_EXTENSIONS):
            result.append(scene)
    return result


def _number(value, low, high):
    return type(value) in (int, float) and low <= value <= high


def _scene_info(scene, entry, directory):
    """One scene's manifest entry, checked field by field; anything unexpected drops the entry (the page then shows the plain picture)."""
    if not isinstance(entry, dict) or entry.get('look') not in LOOKS:
        return None
    media = entry.get('media')
    if not isinstance(media, dict) or media.get('kind') not in ('video', 'image'):
        return None
    ext = {'video': ('webm',), 'image': ('webp', 'jpg', 'png')}[media['kind']]
    match = re.fullmatch(r'scene-' + re.escape(scene) + r'\.([a-z0-9]{3,4})', str(media.get('file')))
    if not match or match.group(1) not in ext or not _size_ok(directory / media['file'], _limit(media['file'])):
        return None
    if not (type(media.get('width')) is int and type(media.get('height')) is int
            and 16 <= media['width'] <= 8192 and 16 <= media['height'] <= 8192):
        return None
    info_media = {'kind': media['kind'], 'url': '/assets/' + media['file'], 'width': media['width'], 'height': media['height']}
    for key, low, high in (('fps', 1, 120), ('loop_seconds', .1, 600)):
        if media.get(key) is not None:
            if not _number(media[key], low, high):
                return None
            info_media[key] = media[key]
    result = {'look': entry['look'], 'media': info_media, 'focus': [.5, .5], 'rate': 1}
    focus = entry.get('focus')
    if focus is not None:
        if not (isinstance(focus, list) and len(focus) == 2 and all(_number(v, 0, 1) for v in focus)):
            return None
        result['focus'] = [float(v) for v in focus]
    if entry.get('rate') is not None:
        if not _number(entry['rate'], .25, 2):
            return None
        result['rate'] = float(entry['rate'])
    still = entry.get('still')
    if still is not None:
        match = re.fullmatch(r'scene-' + re.escape(scene) + r'\.(webp|jpg|png)', str(still))
        if not match or not _size_ok(directory / still, MAX_IMAGE_BYTES):
            return None
        result['still'] = '/assets/' + still
    data = entry.get('data')                           # a game scene's frames (the atlas is its picture): scene-<name>.json, small
    if data is not None:
        if data != f'scene-{scene}.json' or not _size_ok(directory / data, 512 * 1024):
            return None
        result['data'] = '/assets/' + data
    if entry.get('live') is not None:                  # the live effects of a photo scene (water, clouds, lights...), checked by tablet_live
        live = tablet_live.live_info(entry['live'], scene)
        if live:
            result['live'] = live
    return result


def scene_catalog(directory):
    """The names of the prepared scenes and, where the private manifest describes them, how to show each one."""
    directory = Path(directory)
    names = prepared_scenes(directory)
    info = {}
    path = directory / MANIFEST
    try:
        if _size_ok(path, 64 * 1024):
            manifest = json.loads(path.read_text(encoding='utf-8'))
            scenes = manifest.get('scenes') if isinstance(manifest, dict) and manifest.get('version') == 2 else None
            for name in names:
                parsed = _scene_info(name, scenes.get(name), directory) if isinstance(scenes, dict) else None
                if parsed:
                    info[name] = parsed
            # Variants accompany their parent and never become extra choices.
            # Invalid or absent files leave the parent's normal fallback.
            if isinstance(scenes, dict):
                for parent, variants in (('infinite-express', EXPRESS_VARIANTS), ('midnight-video-club', HOUSE_VARIANTS), ('neon-district', MOUNTAIN_VARIANTS)):
                    if parent in names:
                        for name in variants:
                            parsed = _scene_info(name, scenes.get(name), directory)
                            if parsed:
                                info[name] = parsed
    except (OSError, ValueError):
        info = {}
    return {'scenes': names, 'info': info}


def photo_catalog(directory):
    """The prepared photos, checked one by one against their fixed names and sizes; nothing else in the folder is ever listed."""
    directory = Path(directory)
    path = directory / PHOTOS_MANIFEST
    result = []
    try:
        if not _size_ok(path, 64 * 1024):
            return result
        manifest = json.loads(path.read_text(encoding='utf-8'))
        entries = manifest.get('photos') if isinstance(manifest, dict) and manifest.get('version') == 1 else None
        for entry in entries[:PHOTO_COUNT] if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not re.fullmatch(r'photo-(0[1-9]|[1-3]\d|40)\.jpg', str(entry.get('file'))):
                continue
            if not _size_ok(directory / entry['file'], MAX_IMAGE_BYTES):
                continue
            if not (type(entry.get('width')) is int and type(entry.get('height')) is int and 16 <= entry['width'] <= 8192 and 16 <= entry['height'] <= 8192):
                continue
            focus = entry.get('focus')
            if not (isinstance(focus, list) and len(focus) == 2 and all(_number(v, 0, 1) for v in focus)):
                focus = [.5, .5]
            result.append({'url': '/assets/' + entry['file'], 'width': entry['width'], 'height': entry['height'], 'focus': [float(v) for v in focus]})
    except (OSError, ValueError):
        return []
    return result


def apk_ready(directory):
    return _size_ok(Path(directory) / 'app' / APK_NAME, MAX_IMAGE_BYTES)


APK_MAX_BYTES = 2 * 1024 * 1024          # the app refuses anything bigger (Guard.MAX_UPDATE_BYTES); the real file is about 25 KiB
_APK = {'key': None, 'value': False}


def apk_info(directory):
    """What the page may know about the APK on offer: `{'version_code', 'version_name', 'size', 'sha256'}`, or False when there is none.

    The size and the SHA-256 are measured on the file itself (cached while it does not change); the version comes from the build's own
    `ai-desk-tablet.apk.json` and is only believed when it is a small whole number and a `1.<code>` name. A file that is there but has
    no readable version still counts as an APK (`{'size', 'sha256'}`), so the install button keeps working. The page compares the version
    with the installed app's and the app checks the downloaded bytes against this hash before it asks Android to install them."""
    path = Path(directory) / 'app' / APK_NAME
    try:
        stat = path.stat()
    except OSError:
        return False
    if not path.is_file() or not 0 < stat.st_size <= APK_MAX_BYTES:
        return bool(apk_ready(directory))       # too big for the in-app update, but the browser download may still be offered
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if _APK['key'] == key:
        return _APK['value']
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    info = {'size': stat.st_size, 'sha256': digest}
    try:
        meta = json.loads((path.parent / (APK_NAME + '.json')).read_text(encoding='utf-8')[:4096])
        code, name = meta.get('version_code'), meta.get('version_name')
        if type(code) is int and 0 < code < 10 ** 6 and name == f'1.{code}' and meta.get('sha256') == digest:
            info = {'version_code': code, 'version_name': name, **info}
    except (OSError, ValueError, UnicodeError, AttributeError):
        pass
    _APK['key'], _APK['value'] = key, info
    return info


def _safe_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temp = tempfile.mkstemp(prefix='.tablet-', dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _derive(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1, dklen=32).hex()


class Auth:
    def __init__(self, directory=PRIVATE):
        self.path = Path(directory) / AUTH_FILE
        self.lock = threading.RLock()
        self.attempts = collections.defaultdict(collections.deque)
        self.state = {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and isinstance(data.get('sessions'), dict):
                self.state = data
        except (OSError, ValueError):
            pass

    def configured(self):
        return isinstance(self.state.get('hash'), str) and isinstance(self.state.get('salt'), str)

    def set_password(self, password):
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            return False
        salt = secrets.token_bytes(16)
        with self.lock:
            state = {'salt': salt.hex(), 'hash': _derive(password, salt), 'sessions': {}}
            _safe_write(self.path, json.dumps(state))
            self.state = state
            self.attempts.clear()
        return True

    def login(self, address, password):
        now = time.time()
        with self.lock:
            attempts = self.attempts[address]
            while attempts and now - attempts[0] > RATE_SECONDS:
                attempts.popleft()
            if len(attempts) >= MAX_ATTEMPTS:
                return 'limited', None
            attempts.append(now)
            try:
                valid = (self.configured() and isinstance(password, str) and len(password) <= 128
                         and hmac.compare_digest(_derive(password, bytes.fromhex(self.state['salt'])), self.state['hash']))
            except (ValueError, TypeError):
                valid = False
            if not valid:
                return 'invalid', None
            attempts.clear()
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode('ascii')).hexdigest()
            sessions = {k: v for k, v in self.state['sessions'].items()
                        if isinstance(v, (int, float)) and v > now}
            sessions[digest] = now + SESSION_SECONDS
            self.state['sessions'] = sessions
            _safe_write(self.path, json.dumps(self.state))
            return 'ok', token

    def allowed(self, header):
        try:
            cookie = http.cookies.SimpleCookie()
            cookie.load(header or '')
            token = cookie['desk_session'].value
            if not 20 <= len(token) <= 128 or not token.isascii():
                return False
            digest = hashlib.sha256(token.encode('ascii')).hexdigest()
            with self.lock:
                expiration = self.state.get('sessions', {}).get(digest)
            return isinstance(expiration, (int, float)) and expiration > time.time()
        except (KeyError, http.cookies.CookieError):
            return False

# What the tablet's own page may tell this server about itself: sizes, flags and fixed words, never free text from the page's data.
_REPORT_WORDS = {'why': ('load', 'fullscreen', 'scene', 'resize', 'tick'), 'renderer': ('webgl', 'css', 'plain'),
                 'tier': ('high', 'medium', 'light', 'low', 'css', 'plain'), 'look': ('crt', 'lcd', 'photo', 'plain'),
                 'wake': ('on', 'blocked', 'unsupported', 'off', 'none')}
_REPORT_NUMBERS = {'vw': (0, 20000), 'vh': (0, 20000), 'sw': (0, 20000), 'sh': (0, 20000), 'dpr': (.25, 8), 'fit': (.05, 2), 'u': (0, 20),
                   'ovh': (-20000, 20000), 'ovw': (-20000, 20000), 'ovh0': (-20000, 20000), 'fps': (0, 1000), 'dropped': (0, 10 ** 7),
                   'level': (0, 20), 'scale': (0, 8), 'vvs': (0, 20), 'mem': (0, 1024), 'cores': (0, 1024), 'age': (0, 10 ** 7), 'lux': (-1, 200000)}
_REPORT_FLAGS = ('fs', 'rm', 'motion', 'paused', 'video', 'ready', 'blocked', 'secure', 'hidden', 'glass')
_REPORT_TEXT = {'gpu': 90, 'ua': 140, 'error': 120, 'plat': 60, 'app': 20, 'bat': 40}
_REPORT_BOXES = ('topbar', 'slot', 'intro', 'dock', 'quota', 'band', 'machine', 'disks')


def _printable(value, limit):
    return re.sub(r'[^\x20-\x7e]', '?', value)[:limit]


def clean_report(data):
    """Keep only the known fields of a page report, each checked; anything else is dropped. None when it is not a report."""
    if not isinstance(data, dict) or data.get('why') not in _REPORT_WORDS['why']:
        return None
    out = {'why': data['why']}
    for key, words in _REPORT_WORDS.items():
        if key != 'why' and data.get(key) in words:
            out[key] = data[key]
    for key, (low, high) in _REPORT_NUMBERS.items():
        if _number(data.get(key), low, high):
            out[key] = round(float(data[key]), 3)
    for key in _REPORT_FLAGS:
        if type(data.get(key)) is bool:
            out[key] = data[key]
    for key, limit in _REPORT_TEXT.items():
        if isinstance(data.get(key), str):
            out[key] = _printable(data[key], limit)
    if data.get('scene') in SCENES:
        out['scene'] = data['scene']
    for key in ('media', 'canvas', 'clip'):
        pair = data.get(key)
        if isinstance(pair, list) and 2 <= len(pair) <= 4 and all(_number(v, -1, 20000) for v in pair):
            out[key] = [round(float(v), 2) for v in pair]
    boxes = data.get('boxes')
    if isinstance(boxes, dict):
        out['boxes'] = {k: round(float(v), 1) for k, v in boxes.items() if k in _REPORT_BOXES and _number(v, 0, 20000)}
    notes = data.get('notes')
    if isinstance(notes, list):
        out['notes'] = [_printable(n, 90) for n in notes[:8] if isinstance(n, str)]
    return out


class Reports:
    """The last things the tablet's page measured about itself (screen size, whether anything overflowed, the state of the animation),
    so the layout and the motion can be judged from the real device. A private file; no quota, account or reading is ever in it."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.last = 0.0
        self.entries = []

    def add(self, address, data):
        clean = clean_report(data)
        if clean is None:
            return False
        now = time.time()
        with self.lock:
            if now - self.last < 1:                      # a page that talks too much is ignored, not queued
                return False
            self.last = now
            entries = (self.entries + [{'at': int(now), 'from': _printable(str(address), 45), **clean}])[-REPORT_KEEP:]
            if self.path:
                try:
                    _safe_write(self.path, json.dumps(entries, separators=(',', ':')))
                except OSError:
                    return False
            self.entries = entries
        return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_snapshot():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request('http://127.0.0.1:8787/snapshot', headers={'Host': '127.0.0.1:8787'})
    try:
        with opener.open(request, timeout=4) as response:
            body = response.read(DATA_LIMIT + 1)
        if len(body) > DATA_LIMIT:
            return None
        return tablet_snapshot(json.loads(body))
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return None


class Feeds:
    def __init__(self, snapshot=local_snapshot, metrics=collect):
        self.snapshot = snapshot
        self.metrics = metrics
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.quota = None
        self.hardware = None
        self.quota_at = 0
        self.hardware_at = 0
        self.history = MetricsHistory(step=30, keep=120)         # the last hour of the PC's load, temperatures, memory and network (RAM only)

    def _loop(self, method, interval, name, stamp):
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                value = method()
            except Exception:
                value = None
            if name == 'hardware':
                self.history.add(value)                          # None is recorded as a gap; add() never raises
            with self.lock:
                setattr(self, name, value)
                setattr(self, stamp, time.monotonic())
            self.stop.wait(max(1.0, interval - (time.monotonic() - started)))      # keeps the points about 30 s apart

    def start(self):
        for args in ((self.snapshot, 5, 'quota', 'quota_at'), (self.metrics, 30, 'hardware', 'hardware_at')):
            threading.Thread(target=self._loop, args=args, daemon=True).start()

    def status(self):
        now = time.monotonic()
        with self.lock:
            quota = self.quota if now - self.quota_at < 10 else None
            hardware = self.hardware if now - self.hardware_at < 95 else None
        metrics = None if hardware is None else {**hardware, 'history': self.history.payload()}
        return {'providers': (quota or {}).get('providers', {}),
                'quota_connected': quota is not None, 'metrics': metrics}


def ensure_certificate(directory, address):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    cert, key, recorded = directory / 'tablet-cert.pem', directory / 'tablet-key.pem', directory / 'tablet-cert-address'
    try:
        same = recorded.read_text(encoding='ascii') == address
    except OSError:
        same = False
    if not same or not cert.is_file() or not key.is_file():
        with tempfile.TemporaryDirectory(dir=str(directory)) as tmp:
            newcert, newkey = Path(tmp) / 'cert', Path(tmp) / 'key'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', str(newkey), '-out', str(newcert), '-days', '3650',
                            '-subj', '/CN=AI Desk Display', '-addext', 'subjectAltName=IP:' + address],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=30)
            os.chmod(newkey, 0o600)
            os.chmod(newcert, 0o600)
            os.replace(newkey, key)
            os.replace(newcert, cert)
        _safe_write(recorded, address)
    der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding='ascii'))
    fingerprint = ':'.join(a + b for a, b in zip(hashlib.sha256(der).hexdigest()[::2], hashlib.sha256(der).hexdigest()[1::2])).upper()
    return cert, key, fingerprint


class TabletServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, mode, auth, feeds, private, lan, lan_port, fingerprint, reports=None, settings=None, board=None, weather=None):
        super().__init__(address, handler)
        self.mode, self.auth, self.feeds, self.private = mode, auth, feeds, Path(private)
        self.reports = reports if reports is not None else Reports(self.private / REPORTS_FILE)
        self.settings = settings if settings is not None else Settings(self.private / SETTINGS_FILE, SCENES)
        self.board = board                      # a BoardRemote (the small screen's remote) or None
        self.weather = weather                  # a tablet_weather.Weather (the outside reading) or None: then /api/weather says unknown
        self.refused, self.refused_at = 0, time.monotonic()
        self.lan, self.lan_port, self.fingerprint = lan, lan_port, fingerprint
        self.tls_context = None
        self._slots = threading.BoundedSemaphore(8)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        """A browser that does not trust the self-signed certificate yet, or hangs up mid-way, is not a fault: one summary line, no traceback."""
        error = sys.exc_info()[1]
        if not isinstance(error, (ssl.SSLError, ConnectionError, TimeoutError)):
            return super().handle_error(request, client_address)
        self.refused += 1
        if time.monotonic() - self.refused_at >= 600:
            print(f'tablet: {self.refused} connection(s) ended during the secure handshake or by the client in the last 10 minutes '
                  f'(latest from {client_address[0]}: a browser that does not trust the certificate yet?)', file=sys.stderr, flush=True)
            self.refused, self.refused_at = 0, time.monotonic()

    def get_request(self):
        conn, address = super().get_request()
        if self.tls_context is not None:
            try:
                conn = self.tls_context.wrap_socket(conn, server_side=True, do_handshake_on_connect=False)
            except Exception:
                conn.close()
                raise
        return conn, address


class Handler(BaseHTTPRequestHandler):
    server_version = 'AI Desk Display'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(5)
        if isinstance(self.connection, ssl.SSLSocket):
            self.connection.do_handshake()

    def log_message(self, format, *args):
        pass

    def _host_ok(self):
        port = self.server.server_port
        allowed = {self.server.lan + ':' + str(port)} if self.server.mode == 'lan' else {
            '127.0.0.1:' + str(port), 'localhost:' + str(port)}
        return self.headers.get('Host', '').lower() in allowed

    def _origin_ok(self):
        scheme = 'https' if self.server.mode == 'lan' else 'http'
        return self.headers.get('Origin', '') == scheme + '://' + self.headers.get('Host', '')

    def _security_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; media-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")

    def _respond(self, status, body=b'', content='text/plain; charset=utf-8', extra=()):
        self.send_response(status)
        self.send_header('Content-Type', content)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self._security_headers()
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, path, content, extra=()):
        """A private scene file, read in pieces. Videos need byte ranges; the tag lets an unchanged file answer 304."""
        try:
            info = path.stat()
            size = info.st_size
            if not path.is_file() or not 0 < size <= (MAX_VIDEO_BYTES if content == 'video/webm' else MAX_IMAGE_BYTES):
                raise OSError
        except OSError:
            return self._respond(404)
        tag = '"' + format(info.st_mtime_ns, 'x') + '-' + format(size, 'x') + '"'
        if self.headers.get('If-None-Match') == tag:
            self.send_response(304)
            self.send_header('ETag', tag)
            self.send_header('Cache-Control', 'private, no-cache')
            self._security_headers()
            self.end_headers()
            return
        start, end, status = 0, size - 1, 200
        wanted = self.headers.get('Range')
        if wanted:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', wanted.strip())
            if not match or not (match.group(1) or match.group(2)):
                return self._respond(416, extra=(('Content-Range', f'bytes */{size}'),))
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            else:
                start, end = max(0, size - int(match.group(2))), size - 1
            if start > end or start >= size:
                return self._respond(416, extra=(('Content-Range', f'bytes */{size}'),))
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', content)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('ETag', tag)
        self.send_header('Cache-Control', 'private, no-cache')
        for name, value in extra:
            self.send_header(name, value)
        self._security_headers()
        self.end_headers()
        remaining = end - start + 1
        try:
            with path.open('rb') as handle:
                handle.seek(start)
                while remaining > 0:
                    chunk = handle.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (OSError, ConnectionError):
            self.close_connection = True

    def _json(self, status, data, extra=()):
        self._respond(status, json.dumps(data, separators=(',', ':'), allow_nan=False).encode(), 'application/json; charset=utf-8', extra)

    def _read(self, limit=2048):
        if not self._origin_ok() or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return None
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= limit:
                return None
            data = json.loads(self.rfile.read(length))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _file(self, path, kind):
        try:
            if path.startswith('@'):
                return self._stream(self.server.private / path[1:], kind)
            content = (WEB / path).read_bytes()
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError()
            self._respond(200, content, kind)
        except (OSError, ValueError):
            self._respond(404)

    def do_GET(self):
        if not self._host_ok():
            return self._respond(400)
        path = self.path.split('?', 1)[0]
        if self.server.mode == 'setup':
            if path == '/':
                return self._file('setup.html', 'text/html; charset=utf-8')
            if path == '/api/setup':
                metrics = self.server.feeds.status().get('metrics') or {}
                hardware = {'cpu_load': metrics.get('cpu_percent') is not None,
                            'cpu_temp': metrics.get('cpu_temp_c') is not None,
                            'memory': metrics.get('memory') is not None,
                            'disks': len(metrics.get('disks') or []),
                            'gpu': bool(metrics.get('gpus'))}
                return self._json(200, {'url': 'https://' + self.server.lan + ':' + str(self.server.lan_port),
                                        'fingerprint': self.server.fingerprint,
                                        'configured': self.server.auth.configured(), 'hardware': hardware})
            if path in ('/setup.js', '/access.css'):
                return self._file(*_STATIC[path])
            return self._respond(404)
        if path == '/login':
            return self._file('login.html', 'text/html; charset=utf-8')
        if path in _PUBLIC and path in _STATIC:
            return self._file(*_STATIC[path])
        if not self.server.auth.allowed(self.headers.get('Cookie')):
            if path in ('/api/status', '/api/scenes', '/api/settings', '/api/photos', '/api/board', '/api/weather'):
                return self._json(401, {'error': 'sign_in'})
            return self._respond(303, extra=(('Location', '/login'),))
        if path == '/':
            return self._file('index.html', 'text/html; charset=utf-8')
        if path == '/api/status':
            return self._json(200, {**self.server.feeds.status(), 'build': build_id(self.server.private), 'app': apk_info(self.server.private)})
        if path == '/api/settings':
            return self._json(200, {'settings': self.server.settings.get()})
        if path == '/api/photos':
            return self._json(200, {'photos': photo_catalog(self.server.private)})
        if path == '/api/weather':
            weather = self.server.weather
            return self._json(200, {'weather': weather.status() if weather else None})
        if path == '/api/board':
            board = self.server.board
            return self._json(200, {'board': board.status() if board else {'state': 'unavailable'}})
        if path == '/app/' + APK_NAME:
            return self._stream(self.server.private / 'app' / APK_NAME, 'application/vnd.android.package-archive',
                                (('Content-Disposition', f'attachment; filename="{APK_NAME}"'),))
        if path == '/api/scenes':
            return self._json(200, scene_catalog(self.server.private))
        if path in _STATIC and path not in ('/setup.js',):
            return self._file(*_STATIC[path])
        return self._respond(404)

    def do_POST(self):
        if not self._host_ok():
            return self._respond(400)
        data = self._read(4096 if self.path == '/api/report' else 2048)
        if data is None:
            return self._respond(403)
        if self.server.mode == 'lan' and self.path == '/api/board/command':
            if not self.server.auth.allowed(self.headers.get('Cookie')):
                return self._json(401, {'ok': False})
            board = self.server.board
            if board is None or set(data) != {'command', 'value'} or not isinstance(data['command'], str):
                return self._json(503 if board is None else 400, {'ok': False, 'error': 'unavailable' if board is None else 'invalid'})
            result = board.command(data['command'], data['value'])
            return self._json(200 if isinstance(result, dict) and result.get('ok') else 502, result if isinstance(result, dict) else {'ok': False})
        if self.server.mode == 'lan' and self.path == '/api/settings':
            if not self.server.auth.allowed(self.headers.get('Cookie')):
                return self._json(401, {'ok': False})
            try:
                return self._json(200, {'settings': self.server.settings.update(data)})
            except OSError:
                return self._json(503, {'ok': False})
        if self.server.mode == 'lan' and self.path == '/api/report':
            if not self.server.auth.allowed(self.headers.get('Cookie')):
                return self._json(401, {'ok': False})
            ok = self.server.reports.add(self.client_address[0], data)
            return self._json(200 if ok else 400, {'ok': ok})
        if self.server.mode == 'setup' and self.path == '/api/setup':
            try:
                ok = self.server.auth.set_password(data.get('password'))
            except OSError:
                ok = False
            return self._json(200 if ok else 400, {'ok': ok})
        if self.server.mode == 'lan' and self.path == '/api/login':
            try:
                status, token = self.server.auth.login(self.client_address[0], data.get('password'))
            except OSError:
                return self._json(503, {'ok': False})
            if status == 'limited':
                return self._json(429, {'ok': False})
            if status == 'ok':
                cookie = 'desk_session=' + token + '; Path=/; Max-Age=' + str(SESSION_SECONDS) + '; Secure; HttpOnly; SameSite=Strict'
                return self._json(200, {'ok': True}, (('Set-Cookie', cookie),))
            return self._json(401, {'ok': False})
        return self._respond(404)


def lan_address(router='192.168.1.1'):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((router, 9))
        address = sock.getsockname()[0]
    if not ipaddress.ip_address(address).is_private:
        raise ValueError('Private LAN address required')
    return address


def interface_address(interface):
    """Select one private IPv4 from the explicitly chosen Linux interface."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', interface) or interface.startswith('-'):
        raise ValueError('Invalid network interface name')
    result = subprocess.run(['ip', '-j', '-4', 'addr', 'show', 'dev', interface],
                            capture_output=True, text=True, check=True, timeout=3)
    private_networks = tuple(ipaddress.IPv4Network(net) for net in
                             ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    candidates = []
    for entry in json.loads(result.stdout):
        for info in entry.get('addr_info', []):
            if info.get('family') != 'inet' or info.get('scope') != 'global':
                continue
            address = ipaddress.IPv4Address(info['local'])
            if any(address in network for network in private_networks):
                candidates.append(str(address))
    if len(candidates) != 1:
        raise ValueError('The selected interface must have exactly one private IPv4 address')
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    network = parser.add_mutually_exclusive_group()
    network.add_argument('--bind', default=None)
    network.add_argument('--interface', default=None, help='Linux LAN interface to select at startup')
    parser.add_argument('--port', type=int, default=8667)
    parser.add_argument('--setup-port', type=int, default=8666)
    args = parser.parse_args()
    try:
        address = args.bind or (interface_address(args.interface) if args.interface else lan_address())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    if not ipaddress.ip_address(address).is_private or address.startswith('127.'):
        raise SystemExit('A specific private LAN address is required')
    cert, key, fingerprint = ensure_certificate(PRIVATE, address)
    auth, feeds = Auth(PRIVATE), Feeds()
    settings = Settings(PRIVATE / SETTINGS_FILE, SCENES)
    from token_tv.tablet_weather import Weather
    weather = Weather(settings)
    try:
        from token_tv.tablet_board import BoardRemote
        board = BoardRemote()
    except ImportError:
        board = None
    kwargs = dict(auth=auth, feeds=feeds, private=PRIVATE, lan=address, lan_port=args.port, fingerprint=fingerprint,
                  reports=Reports(PRIVATE / REPORTS_FILE), settings=settings, board=board, weather=weather)
    local = TabletServer(('127.0.0.1', args.setup_port), Handler, mode='setup', **kwargs)
    public = TabletServer((address, args.port), Handler, mode='lan', **kwargs)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    public.tls_context = context
    feeds.start()
    weather.start()
    threading.Thread(target=local.serve_forever, daemon=True).start()
    try:
        public.serve_forever()
    finally:
        feeds.stop.set()
        weather.stop.set()
        local.shutdown()
        public.server_close()
        local.server_close()


if __name__ == '__main__':
    main()
