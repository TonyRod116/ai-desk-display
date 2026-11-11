"""The tablet's remote for the small screen (the touch board), through the monitor's control room.

Tony asked for the two displays to stay apart ("different configuration and screens, so there is less mess"): the tablet never reads
or writes the board's settings, files or token and never talks to the board. This module is the ONLY bridge. It asks the monitor's
control room (the same routes its own page, `/board`, uses, on 127.0.0.1) to do four things and nothing else:

    page      0..7                           show a stored page
    rotation  0 | 30 | 60                    change pages by themselves, in minutes (0 = stay on one page)
    speed     75 | 100 | 125                 animation speed in percent: the page on display (firmware 27+), else every page
    night     {enabled, start, end, level}   the board's night schedule, kept and applied by the monitor

Every value is checked here exactly as `board_control.BoardControl.execute` checks it (tests/test_tablet_board.py runs both side by
side), and a refused value never causes a request. The only reachable routes are `GET /board/status` and the four `POST /board/<name>`
paths above, written out below; nothing is built from the caller's text. No token, cookie or Origin header is ever sent, redirects and
proxies are not followed, and at most 64 KiB of an answer is read. What leaves this module is a fixed shape and fixed words: never the
monitor's body, an exception's text, an address or a token.

`BoardRemote.status()` returns these keys, always (unknown is None, never a made-up value):

    state     'ok' | 'offline' | 'not_configured' | 'unavailable'
              ok = the board answers (also while the monitor is sending it a page, if the page is known); offline and
              not_configured are the control room's own words; unavailable = no usable answer from the monitor
    page      0..7 on display, or None (unknown, or the board shows its connection screen)
    controls  True when the board takes rotation and speed (firmware 26+); False otherwise
    rotation  0 | 30 | 60 minutes, or None
    speed     75 | 100 | 125 percent, or None (on per-screen firmware: the page on display)
    night     {'enabled', 'start', 'end', 'level'}, or None (the board cannot dim, or the monitor has no schedule)
    firmware  a short printable string, or None. The control room does not report it today, so this is None for now
    slots     None, or a list of {'index': 0..7, 'name': str | None}: what each stored page shows, as the monitor last CONFIRMED it
              on the board (a page it has not confirmed yet has name None); names are ASCII, at most 32 characters

`BoardRemote.command(name, value)` returns {'ok': bool, 'status': <the same shape> | None, 'error': word | None} with one of these words:

    invalid      refused here, nothing sent (unknown command, or a value the control room would refuse)
    busy         another command is running, or the last one ended less than `min_gap` seconds ago; nothing sent
    rejected     the control room answered 400: it refused the value or the control (for example rotation on old firmware)
    timeout      no complete answer in `timeout` seconds. The monitor may still carry the command out: it waits for a page
                 transfer to end (up to two minutes) before touching the board, so say "no answer yet", not "failed"
    unavailable  anything else: the monitor is not running, answered another error (503 = the board did not confirm), or answered
                 with something that is not the control room's JSON (garbage, too big, a redirect)
"""
import http.client
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request

DEFAULT_BASE = 'http://127.0.0.1:8787'
STATUS_SECONDS = 15          # one real status request at most this often: the board is probed gently, and the monitor polls it too
RESPONSE_LIMIT = 64 * 1024   # bytes of an answer ever read
PAGES = 8
ROTATIONS = (0, 30, 60)
SPEEDS = (75, 100, 125)
NIGHT_LEVELS = (5, 100)      # percent; never zero, a dark board looks dead (board_control.NIGHT_LEVEL_RANGE)

COMMANDS = ('page', 'rotation', 'speed', 'night')
STATES = ('ok', 'offline', 'not_configured', 'unavailable')
ERRORS = ('invalid', 'busy', 'rejected', 'timeout', 'unavailable')

_STATUS_ROUTE = '/board/status'
_ROUTES = {'page': '/board/page', 'rotation': '/board/rotation', 'speed': '/board/speed', 'night': '/board/night'}
_BASE = re.compile(r'http://127\.0\.0\.1:([0-9]{1,5})/?')
_CLOCK = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]')   # ASCII digits only: the control room's \d would also take other scripts'
_NIGHT_KEYS = frozenset(('enabled', 'start', 'end', 'level'))
_MONITOR_STATES = ('connected', 'busy', 'offline', 'not_configured')   # the words of BoardControl._status
_LABEL_DROP = re.compile(r'[^A-Za-z0-9 ._+()/-]')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Failed(Exception):
    """A request that did not end in the control room's JSON. `word` is the only thing that leaves this module."""
    def __init__(self, word):
        super().__init__(word)
        self.word = word


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _timed_out(error):
    return isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError)


def _night(value):
    """A fresh, validated night schedule (exactly four keys, as `board_control.night_settings`), or ValueError."""
    if not isinstance(value, dict) or set(value) != _NIGHT_KEYS:
        raise ValueError('Invalid night mode')
    enabled, start, end, level = (value[key] for key in ('enabled', 'start', 'end', 'level'))
    if type(enabled) is not bool or type(level) is not int or not NIGHT_LEVELS[0] <= level <= NIGHT_LEVELS[1]:
        raise ValueError('Invalid night mode')
    for text in (start, end):
        if type(text) is not str or not _CLOCK.fullmatch(text):
            raise ValueError('Invalid night mode')
    return {'enabled': enabled, 'start': start, 'end': end, 'level': level}


def clean_value(name, value):
    """The value of one allowed command as the control room's `execute` accepts it, rebuilt fresh; ValueError for anything else.

    Whole numbers only (a bool or a float is refused), and a speed is a plain percent: the control room also takes a per-page
    {percent, page} form, which this remote never sends."""
    if type(name) is not str or name not in COMMANDS:
        raise ValueError('Unknown control')
    if name == 'night':
        return _night(value)
    allowed = {'page': range(PAGES), 'rotation': ROTATIONS, 'speed': SPEEDS}[name]
    if type(value) is not int or value not in allowed:
        raise ValueError('Unsupported ' + name)
    return value


def _member(value, allowed):
    return value if type(value) is int and value in allowed else None


def _label(value, limit):
    """A short ASCII label from a monitor-supplied string, or None. A middle dot (as in the name of 'Night Train') becomes a hyphen."""
    if type(value) is not str:
        return None
    text = _LABEL_DROP.sub('', value.replace('\N{MIDDLE DOT}', '-'))
    return ' '.join(text.split())[:limit].strip() or None


def _slots(raw):
    """What each stored page shows, from the scenes the monitor has CONFIRMED on the board (`scene_delivered_ids`): a slot
    it has not confirmed is unknown, not guessed from the wanted scene. None when no slot has a name."""
    delivered, catalog = raw.get('scene_delivered_ids'), raw.get('scene_catalog')
    if not isinstance(delivered, list) or not isinstance(catalog, list) or not delivered:
        return None
    names = {entry['id']: entry['name'] for entry in catalog[:64]
             if isinstance(entry, dict) and type(entry.get('id')) is str and type(entry.get('name')) is str}
    slots = [{'index': index, 'name': _label(names.get(scene), 32) if type(scene) is str else None}
             for index, scene in enumerate(delivered[:PAGES])]
    return slots if any(slot['name'] for slot in slots) else None


def _schedule(raw):
    """The night schedule, shown only where the control room shows it: the board can dim (`night_supported`)."""
    if raw.get('night_supported') is not True:
        return None
    try:
        return _night(raw.get('night'))
    except ValueError:
        return None


def clean_status(raw):
    """The fixed, checked shape of the control room's status (see the module docstring), or None when `raw` is not one."""
    if not isinstance(raw, dict) or raw.get('state') not in _MONITOR_STATES:
        return None
    word, page = raw['state'], raw.get('page')
    page_known = type(page) is int and 0 <= page < PAGES
    # The control room's own page counts a busy monitor (it is sending a page) as usable once the page is known.
    usable = word == 'connected' or (word == 'busy' and page_known)
    on = usable and page_known and raw.get('showing_connection') is not True
    return {'state': 'ok' if usable else word if word in ('offline', 'not_configured') else 'unavailable',
            'page': page if on else None,
            'controls': usable and raw.get('controls') is True,
            'rotation': _member(raw.get('rotation_minutes'), ROTATIONS) if usable else None,
            'speed': _member(raw.get('speed_percent'), SPEEDS) if usable else None,
            'night': _schedule(raw),
            'firmware': _label(raw.get('firmware'), 16) if usable else None,
            'slots': _slots(raw)}


def _unknown():
    return {'state': 'unavailable', 'page': None, 'controls': False, 'rotation': None, 'speed': None,
            'night': None, 'firmware': None, 'slots': None}


def _copy(status):
    """A caller may change what it gets; the cache must not follow."""
    result = dict(status)
    if result['night'] is not None:
        result['night'] = dict(result['night'])
    if result['slots'] is not None:
        result['slots'] = [dict(slot) for slot in result['slots']]
    return result


def _outcome(status=None, error=None):
    return {'ok': error is None, 'status': status, 'error': error}


class BoardRemote:
    """Thread-safe: the tablet server calls it from one thread per request."""

    def __init__(self, base=DEFAULT_BASE, timeout=8, min_gap=1.0, opener=None, clock=time.monotonic):
        match = _BASE.fullmatch(base) if type(base) is str else None
        if not match or not 1 <= int(match.group(1)) <= 65535:
            raise ValueError('The control room is plain http on 127.0.0.1 with a port, e.g. ' + DEFAULT_BASE)
        if not _number(timeout) or not 0 < timeout <= 60 or not _number(min_gap) or not 0 <= min_gap <= 3600:
            raise ValueError('Unreasonable timeout or gap')
        self._base = 'http://127.0.0.1:' + str(int(match.group(1)))
        self._host = self._base[len('http://'):]
        self._timeout = timeout
        self._min_gap = min_gap
        self._opener = opener if opener is not None else urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._clock = clock
        self._fetch = threading.Lock()      # one real status request at a time; the others then find it cached
        self._command = threading.Lock()    # one command at a time; held for the whole request
        self._state = threading.Lock()      # guards the cache and its epoch only; never held while waiting for the monitor
        self._cache = None                  # (when, status)
        self._epoch = 0                     # +1 whenever a command has been tried: a status fetched across it is not kept
        self._last_command = None           # when the last command ended

    def status(self):
        """The control room's status in the fixed shape. Cached for STATUS_SECONDS, failures too; never raises."""
        with self._fetch:
            with self._state:
                cached, epoch = self._cache, self._epoch
            if cached is not None and 0 <= self._clock() - cached[0] < STATUS_SECONDS:
                return _copy(cached[1])
            try:
                result = clean_status(self._exchange(_STATUS_ROUTE)) or _unknown()
            except _Failed:
                result = _unknown()
            with self._state:
                if epoch == self._epoch:    # a command ended while this was in flight: it may predate the change
                    self._cache = (self._clock(), result)
            return _copy(result)

    def command(self, name, value):
        """Ask the control room for one allowed change. One at a time, `min_gap` apart; never raises, never queues."""
        try:
            value = clean_value(name, value)
        except ValueError:
            return _outcome(error='invalid')
        if not self._command.acquire(blocking=False):
            return _outcome(error='busy')
        try:
            if self._last_command is not None and not self._clock() - self._last_command >= self._min_gap:
                return _outcome(error='busy')
            try:
                status = clean_status(self._exchange(_ROUTES[name], {'value': value}))
                outcome = _outcome(status=status) if status is not None else _outcome(error='unavailable')
            except _Failed as failed:
                outcome = _outcome(error=failed.word)
            self._last_command = self._clock()
            with self._state:
                self._epoch += 1
                self._cache = None          # the board changed (or may have): the next status asks again
            return outcome
        finally:
            self._command.release()

    def _exchange(self, route, body=None):
        """One request to the control room; its answer as a dict, or _Failed with a fixed word. `body` makes it a POST."""
        data = None if body is None else json.dumps(body, separators=(',', ':')).encode('ascii')
        headers = {'Host': self._host}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self._base + route, data=data, headers=headers, method='GET' if data is None else 'POST')
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = self._read(response)
        except urllib.error.HTTPError as error:
            error.close()                   # its body is never read
            raise _Failed('rejected' if data is not None and error.code == 400 else 'unavailable') from None
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise _Failed('timeout' if _timed_out(error) else 'unavailable') from None
        try:
            parsed = json.loads(raw.decode('utf-8'))
        except (ValueError, RecursionError):
            raise _Failed('unavailable') from None
        if not isinstance(parsed, dict):
            raise _Failed('unavailable')
        return parsed

    def _read(self, response):
        """The whole answer, at most RESPONSE_LIMIT bytes and `timeout` seconds in total (a slow trickle does not hold the lock)."""
        if getattr(response, 'status', None) != 200:
            raise _Failed('unavailable')
        try:
            declared = int((getattr(response, 'headers', None) or {}).get('Content-Length', ''))
        except (TypeError, ValueError):
            declared = 0
        if declared > RESPONSE_LIMIT:
            raise _Failed('unavailable')
        read = getattr(response, 'read1', response.read)
        deadline = time.monotonic() + self._timeout
        chunks, size = [], 0
        while True:
            chunk = read(min(8192, RESPONSE_LIMIT + 1 - size))
            if not chunk:
                return b''.join(chunks)
            chunks.append(chunk)
            size += len(chunk)
            if size > RESPONSE_LIMIT:
                raise _Failed('unavailable')
            if time.monotonic() > deadline:
                raise _Failed('timeout')
