"""PC side of the touch ESP32 board: pushes pre-rendered pages, never asks it for data.

Same shape as the clock: the PC renders, the board only shows images. The board
holds the pages and changes between them on touch, so nothing on this computer
listens beyond localhost. Every call carries the board's token, which the board
generated and shows on its own screen.
"""
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
import hashlib
import ipaddress
import json
import os
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse
from urllib.request import Request

from token_tv.http import open_direct

MAX_PAGE_BYTES = 8 + 320 * 240 * 2 + 81920  # pixels plus the firmware 14 animation allowance
PAGES = 8  # what this PC can send; the board says how many it holds (older firmware: 6)
CARD_MAX = 200  # characters of the details card's line; the board refuses anything longer
TOKEN = re.compile(r'[0-9a-f]{16}')


def card_is_valid(card):
    """A details line the board could accept by size and characters (its own parser still checks the grammar)."""
    return isinstance(card, str) and 0 < len(card) <= CARD_MAX and card.isascii() and card.isprintable()


def board_settings(value):
    """(url, token) from the `board_display` config entry, or ValueError."""
    if not isinstance(value, dict) or set(value) != {'url', 'token'}:
        raise ValueError('board_display needs exactly a url and a token')
    url, token = value['url'], value['token']
    if not isinstance(url, str) or not isinstance(token, str):
        raise ValueError('board_display url and token must be text')
    parsed = urlparse(url)
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
    except ValueError:
        raise ValueError('The board address must be a private IP address, e.g. http://192.168.0.60') from None
    if (parsed.scheme != 'http' or parsed.username or parsed.password or parsed.query
            or parsed.path not in ('', '/') or not address.is_private or address.is_unspecified):
        raise ValueError('The board address must be plain http to a private IP address, e.g. http://192.168.0.60')
    if not TOKEN.fullmatch(token):
        raise ValueError('The board token is the 16 characters shown on its screen')
    return url.rstrip('/'), token


class BoardDisplay:
    def __init__(self, base_url, token):
        self.base_url, self.token = board_settings({'url': base_url, 'token': token})
        self.lock = threading.RLock()  # one board request at a time, including upload + readback
        self.last_info = None
        self.last_seen = 0.0
        self.capacity = 6  # until the board says otherwise: the first firmware had six slots
        self.stars = False  # firmware 4+ can make the stars of a page twinkle (5 flares them as a cross)
        self.anim = False  # firmware 7+ moves sprites over a page (ANIM trailer)
        self.anim_frames = 4  # firmware 14 advertises eight-frame scenery
        self.extended_anim = False  # only explicit firmware support permits larger city animations
        self.waves = False  # firmware 8+ moves the whole photographic sea at native resolution
        self.scroll = False  # only boards explicitly advertising resident platform scrolling
        self.remembers_selection = False
        self.active = None  # how many page slots the board cycles; None on firmware without the setting
        self.brightness = False  # firmware 42 drives its backlight with PWM and takes `/config?bright=N` (night mode)
        self.card = False  # firmware 42 shows a details card built from text that rides on the heartbeat

    def set_address(self, url):
        """The board moved to another address (its router gave it a new one): follow it. The token stays; what was learned
        about the old connection is forgotten, so nothing claims to be current until the board answers again."""
        new_url, _ = board_settings({'url': url, 'token': self.token})
        with self.lock:
            self.base_url = new_url
            self.last_info = None
            self.last_seen = 0.0

    def request(self, path, data=None, headers=None, authorized=True):
        headers = dict(headers or {})
        if authorized:
            headers['X-Token'] = self.token
        # The board keeps animating while transferring a page: a measured
        # upload/readback took 42/24 s. Keep controls short, allow page I/O
        # enough time, and still verify every stored byte in upload().
        timeout = 60 if path.split('?', 1)[0] == '/page' else 20
        with self.lock:
            with open_direct(Request(self.base_url + path, data=data, headers=headers),
                             timeout=timeout, no_proxy=True) as response:
                return response.status, response.read()

    def info(self):
        with self.lock:
            _, body = self.request('/info', authorized=False)
            info = json.loads(body)
            if not isinstance(info, dict):
                raise ValueError('Invalid board status')
            self.last_info = info
            self.last_seen = time.monotonic()
            return info

    def ping(self, card=None):
        """Heartbeat. Returns which pages the board holds, e.g. '110111' (older firmware answers 'OK').

        `card` is the details card's line (token_tv/board_card.py). It rides on this request, so it costs no extra one;
        it is only ever passed for a board that advertises `card` in /info."""
        # Local civil seconds align boundaries with the PC's timezone, including DST.
        now = datetime.now().astimezone()
        civil = int(now.timestamp()) + int(now.utcoffset().total_seconds())
        query = f'clock={civil}'
        if card is not None:
            if not card_is_valid(card):
                raise ValueError('Invalid details card')
            query += '&card=' + quote(card, safe=',')
        _, body = self.request(f'/ping?{query}', data=b'')
        return body.decode('ascii', 'replace').strip()

    def show(self, number):
        """Select a stored page. A board still on its address screen leaves it."""
        if not 0 <= number < PAGES:
            raise ValueError('Unexpected board page')
        self.request(f'/show?n={int(number)}', data=b'')

    def pair(self, token):
        """Set the board's token. An unpaired board accepts the first caller; a paired one needs the current token."""
        new = board_settings({'url': self.base_url, 'token': token})[1]
        self.request(f'/pair?token={new}', data=b'')
        self.token = new

    def ensure_paired(self):
        """A board without a token (just flashed or formatted) is claimed with this PC's token,
        so nobody has to type anything after reflashing it. Older firmware has no pairing."""
        info = self.info()
        pages = info.get('pages')
        if type(pages) is int and 1 <= pages <= PAGES:
            self.capacity = pages
        self.remembers_selection = info.get('selection_memory') is True
        self.stars = info.get('stars') is True
        self.anim = info.get('anim') in (1, True)
        self.anim_frames = 8 if type(info.get('anim_frames')) is int and info['anim_frames'] == 8 else 4
        self.extended_anim = type(info.get('anim_extended')) is int and info['anim_extended'] == 1
        self.waves = info['waves'] if type(info.get('waves')) is int and info['waves'] in (2, 3, 4) else info.get('waves') in (1, True)
        scroll = info.get('scroll')
        self.scroll = scroll if type(scroll) is int and scroll in (2, 3, 4) else (1 if scroll in (1, True) else False)
        active = info.get('active')
        self.active = active if type(active) is int and 1 <= active <= PAGES else None
        self.brightness = info.get('brightness') in (1, True)
        self.card = info.get('card') in (1, True)
        if info.get('paired') is False:
            self.pair(self.token)

    def select_initial_page(self):
        """Legacy boards need a nudge; newer boards restore their own saved page."""
        if not self.remembers_selection:
            self.show(0)

    def update(self, firmware, wait=60):
        """Install a firmware image over the wifi. The board only accepts it while its address
        screen is showing (a long touch), so changing its code needs someone at the board."""
        if len(firmware) < 100000 or firmware[:1] != b'\xe9':
            raise ValueError('Not an ESP32 application image')
        boundary = 'TokenTV' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="firmware.bin"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n').encode() + firmware + f'\r\n--{boundary}--\r\n'.encode()
        before = self.info().get('fw')
        with open_direct(Request(self.base_url + '/update', body,
                                 {'Content-Type': 'multipart/form-data; boundary=' + boundary, 'X-Token': self.token}),
                         timeout=120, no_proxy=True) as response:
            response.read()
        deadline = time.time() + wait
        while time.time() < deadline:  # the board restarts into the new image
            time.sleep(2)
            try:
                after = self.info().get('fw')
            except (OSError, ValueError):
                continue
            if after:
                return before, after
        raise OSError('The board did not come back after the update')

    def configure(self, rotation=None, invert=None, swap_red_blue=None, swap_bytes=None, pages=None,
                  cycle=None, speed=None, speed_page=None, mode_hold=None, connect_hold=None, bright=None):
        """Panel options kept on the board: 1 or 3 for landscape either way up, inverted colours,
        red and blue swapped, byte order of each pixel swapped, how many page slots are cycled."""
        options = []
        if cycle is not None:
            if type(cycle) is not int or cycle not in (0, 30, 60):
                raise ValueError('Cycle must be fixed, 30 minutes or one hour')
            options.append(f'cycle={cycle}')
        if speed is not None:
            if type(speed) is not int or speed not in (75, 100, 125):
                raise ValueError('Unsupported animation speed')
            options.append(f'speed={speed}')
        if speed_page is not None:
            if speed is None or type(speed_page) is not int or not 0 <= speed_page < PAGES:
                raise ValueError('Invalid screen for animation speed')
            options.append(f'speedpage={speed_page}')
        if mode_hold is not None or connect_hold is not None:
            if (type(mode_hold) is not int or type(connect_hold) is not int
                    or not 1 <= mode_hold <= 4 or not 5 <= connect_hold <= 10):
                raise ValueError('Invalid touch timing')
            options.extend((f'holdmode={mode_hold}', f'holdconnect={connect_hold}'))
        if pages is not None:
            if not 1 <= pages <= PAGES:
                raise ValueError(f'Pages are 1 to {PAGES}')
            options.append(f'pages={pages}')
        if rotation is not None:
            if rotation not in (1, 3):
                raise ValueError('Rotation is 1 or 3')
            options.append(f'rotation={rotation}')
        if invert is not None:
            options.append(f'invert={int(bool(invert))}')
        if swap_red_blue is not None:
            options.append(f'swaprb={int(bool(swap_red_blue))}')
        if swap_bytes is not None:
            options.append(f'swapbytes={int(bool(swap_bytes))}')
        if bright is not None:
            if type(bright) is not int or not 0 <= bright <= 100:
                raise ValueError('Brightness is 0 to 100')
            options.append(f'bright={bright}')
        if not options:
            raise ValueError('Nothing to change')
        self.request('/config?' + '&'.join(options), data=b'')

    def set_active_pages(self, count):
        """Tell the board how many pages exist, so a deleted one is not cycled (firmware 7+; older firmware
        has no such setting and keeps all its slots)."""
        if self.active is not None and self.active != count:
            self.configure(pages=count)
            self.active = count

    def read(self, number):
        return self.request(f'/page?n={int(number)}')[1]

    def upload(self, number, image):
        if not 0 <= number < PAGES:
            raise ValueError('Unexpected board page')
        if not image or len(image) > MAX_PAGE_BYTES or image[:4] != b'TVF1':
            raise ValueError('Unexpected board image')
        boundary = 'TokenTV' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="p{number}.jpg"\r\n'
                f'Content-Type: image/jpeg\r\n\r\n').encode() + image + f'\r\n--{boundary}--\r\n'.encode()
        with self.lock:
            status, _ = self.request(f'/page?n={number}', body,
                                     {'Content-Type': 'multipart/form-data; boundary=' + boundary})
            if self.read(number) != image:  # what the board stored must be what was sent
                raise ValueError('Board image verification failed')
        return {'page': number, 'status': status, 'bytes': len(image)}


def publish_pages(board, pages, sent, on_verified=None, card=None):
    """Heartbeat, then send the pages that changed or that the board lacks. Returns the receipts.

    `card` (the details card's line) rides on the heartbeat; without it the heartbeat is the plain one.

    `sent` maps page number to the digest verified on the board. A heartbeat
    failure forgets everything. Modern boards report missing slots, so a failed
    individual transfer can retain the other verified pages and resume without
    repeatedly starting from page zero. Legacy boards still retry everything.
    """
    receipts = []
    if card is not None and not card_is_valid(card):
        card = None  # a bad details line must never stand in the way of the heartbeat (a failed one re-sends every page)
    try:
        held = board.ping() if card is None else board.ping(card)
    except (OSError, ValueError):
        sent.clear()
        raise
    capacity = getattr(board, 'capacity', len(pages))
    known = (bool(held) and len(held) >= min(capacity, len(pages))
             and set(held) <= {'0', '1'})
    number = None
    try:
        for number, image in enumerate(pages[:capacity]):  # never more pages than the board has slots
            digest = hashlib.sha256(image).hexdigest()
            lacks = known and number < len(held) and held[number] == '0'
            if sent.get(number) != digest or lacks:  # identical pages are not rewritten to the board's flash
                receipts.append(dict(board.upload(number, image), sha256=digest))
                sent[number] = digest
            if on_verified is not None:
                on_verified(number)
    except (OSError, ValueError) as error:
        if known and number is not None:
            sent.pop(number, None)  # an interrupted page is never considered verified
        else:
            sent.clear()
        error.board_page = number
        error.board_receipts = receipts
        raise
    return receipts


RESET_REASONS = {1: 'power on', 3: 'software restart', 4: 'crash', 5: 'watchdog', 6: 'watchdog', 7: 'watchdog',
                 9: 'brown-out (power dip)'}
IMPLAUSIBLE_RSSI = -10  # dBm: a connected board reads about -30 to -90; above this the number is not believable


def signal_text(rssi):
    """What `--check` says about the wifi signal. 2026-11-03: a check printed "-2 dBm". The firmware prints the driver's
    signed byte unchanged (nothing is lost in formatting), so the number comes from the driver itself and cannot be
    judged without the board: anything above -10 dBm is reported as doubtful and never as a fact. 0 is "no reading"."""
    if type(rssi) is not int or rssi == 0:
        return None
    if rssi > IMPLAUSIBLE_RSSI:
        return f'wifi signal reading looks implausible ({rssi} dBm), so it is not used'
    return f'wifi signal {rssi} dBm'


def health_text(info):
    """The sentence `token-tv board --check` prints from a board's /info. Older firmware says less, never something false."""
    if not isinstance(info.get('up'), int):  # firmware 6 and later report these
        return ''
    parts = [f'Up {info["up"] // 60} min', f'last start: {RESET_REASONS.get(info.get("rst"), info.get("rst"))}',
             f'since then {info.get("taps")} taps and {info.get("longs")} long presses']
    parts.append(signal_text(info.get('rssi')))
    if info.get('silent') == -1:
        parts.append('no heartbeat from the PC yet')
    elif isinstance(info.get('silent'), int):
        parts.append(f'PC last heard {info["silent"]} s ago')
    if info.get('renews') or info.get('srest'):
        parts.append(f'link renewed {info["renews"]}x, restarted {info.get("srest")}x for silence')
    if isinstance(info.get('active'), int):
        parts.append(f'cycling {info["active"]} of {info.get("pages")} page slots')
    if isinstance(info.get('page'), int):
        parts.append('showing the address screen' if info.get('info') else f'showing page {info["page"]}')
    # Firmware 42: the build trial, its fallback and the watchdog.
    if info.get('trial') in (0, 1):
        strikes = info.get('strikes') if isinstance(info.get('strikes'), int) else 0
        build = f' {info["build"]}' if isinstance(info.get('build'), str) and info['build'] else ''
        parts.append(f'build{build} is on trial ({strikes} of 3 crashes counted)' if info['trial'] == 1
                     else f'build{build} confirmed')
        if info.get('rolled') == 1:
            parts.append('running because the newer build failed three times')
        if info.get('fallback') in (0, 1):
            parts.append('a previous image is ready to go back to' if info['fallback'] == 1
                         else 'no previous image to go back to')
    if isinstance(info.get('wdt'), int) and info['wdt'] > 0:
        parts.append(f'watchdog {info["wdt"]} s')
    if type(info.get('free_heap')) is int and info['free_heap'] > 0:
        parts.append(f'{info["free_heap"] // 1024} kB of memory free')
    # Night mode and the details card (firmware 42).
    if info.get('brightness') == 1 and type(info.get('bright_now')) is int and type(info.get('bright')) is int:
        parts.append(f'backlight {info["bright_now"]}%' + ('' if info['bright_now'] == info['bright']
                                                           else f' (scheduled {info["bright"]}%)'))
    if info.get('card') == 1 and type(info.get('card_age')) is int:
        parts.append('no details card received yet' if info['card_age'] < 0
                     else f'details card received {info["card_age"]} s ago')
        if type(info.get('card_bad')) is int and info['card_bad'] > 0:
            parts.append(f'{info["card_bad"]} details lines refused')
    return '; '.join(part for part in parts if part) + '.'


def find_boards(hosts, port=80, timeout=0.8, workers=64):
    """The addresses among `hosts` that answer like a TokenTV board (GET /info, nothing else sent)."""
    def probe(host):
        try:
            with open_direct(Request(f'http://{host}:{port}/info'), timeout=timeout, no_proxy=True) as response:
                data = json.loads(response.read(4000))
            return host if isinstance(data, dict) and data.get('model') == 'tokentv-board' else None
        except (OSError, ValueError):
            return None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [host for host in pool.map(probe, hosts) if host]


def subnet_hosts(address):
    """Every host of the /24 around a private IPv4 address."""
    return [str(host) for host in ipaddress.ip_network(f'{address}/24', strict=False).hosts()]


def new_token():
    return secrets.token_hex(8)


def save_board_config(path, url, token):
    """Write `board_display` into the private config: validated first, atomic, mode 0600. The one place that does it:
    `token-tv board` (including `--find`) and the monitor, when it finds a board that moved, both come here."""
    from token_tv.sources import load_config
    path = Path(path)
    data = json.loads(path.read_text())
    data['board_display'] = {'url': url, 'token': token}
    temporary = path.with_name(path.name + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(json.dumps(data, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    try:
        load_config(temporary)  # never replace a working config with one that does not validate
    except (ValueError, KeyError, TypeError):
        temporary.unlink()
        raise
    temporary.replace(path)


# A board whose address changed (its router handed out another one) used to stop publishing silently until someone ran
# `token-tv board --find`. The monitor now does that itself, carefully: the board serves one client at a time and a
# network scan is not a thing to repeat (Tony, 2026-11-03).
FIND_AFTER_SECONDS = 600     # the board must have been unreachable this long
FIND_EVERY_SECONDS = 3600    # and a search runs at most this often
FIND_WORKERS = 6             # low concurrency: a quiet look at one /24, not a flood
FIND_CANDIDATES = 4          # more boards than this answering to the model name is not a house, it is a puzzle
# Fixed words only: the log never says an address or a token.
FIND_LOG = {'search': 'TokenTV board address search started.',
            'found': 'TokenTV board address found and saved.',
            'unsaved': 'TokenTV board address found but could not be saved; run: token-tv board --find',
            'none': 'TokenTV board address not found.',
            'several': 'TokenTV board address search found several boards; nothing was changed.',
            'error': 'TokenTV board address search failed.'}


class BoardLocator:
    """Finds the board again for the monitor if its address moved.

    It only looks when the board has been unreachable for ten minutes, at most once an hour, on the saved address's own
    /24, with six workers. It accepts a device only if it reports the board model AND takes the saved token on the
    heartbeat (the same harmless authenticated call `--find` makes), and only when exactly one does. The saved address
    answering as a board means it has not moved and nothing is searched. A found address is saved through
    `save_board_config`, the code `--find` uses, and the network guard is told about it."""

    def __init__(self, board, save, policy=None, log=None, clock=time.monotonic, find=None, make=None,
                 after=FIND_AFTER_SECONDS, every=FIND_EVERY_SECONDS, workers=FIND_WORKERS):
        self.board, self.save, self.policy = board, save, policy
        self.log = log or (lambda text: print(text, flush=True))
        self.clock, self.after, self.every, self.workers = clock, after, every, workers
        self.find = find or find_boards
        self.make = make or BoardDisplay
        self.unreachable_since = None
        self.last_search = None

    def reached(self):
        self.unreachable_since = None

    def failed(self):
        if self.unreachable_since is None:
            self.unreachable_since = self.clock()

    def due(self):
        now = self.clock()
        return (self.unreachable_since is not None and now - self.unreachable_since >= self.after
                and (self.last_search is None or now - self.last_search >= self.every))

    def search(self):
        """Look once if it is time. Returns the new address when found and saved, else None. Never raises."""
        if not self.due():
            return None
        self.last_search = self.clock()
        try:
            return self._search()
        except (OSError, ValueError, KeyError, TypeError):
            self.log(FIND_LOG['error'])
            return None

    def _is_board(self, url):
        try:
            info = self.make(url, self.board.token).info()
        except (OSError, ValueError):
            return False
        return isinstance(info, dict) and info.get('model') == 'tokentv-board'

    def _search(self):
        parsed = urlparse(self.board.base_url)
        host, port = parsed.hostname, parsed.port or 80
        if ipaddress.ip_address(host).version != 4:
            return None
        scope = self.policy.scanning(host, port) if self.policy is not None else nullcontext()
        with scope:
            if self._is_board(self.board.base_url):  # still there: the address did not change, so there is nothing to find
                self.unreachable_since = None
                return None
            self.log(FIND_LOG['search'])
            network = ipaddress.ip_network(f'{host}/24', strict=False)
            found = [h for h in self.find(subnet_hosts(host), port=port, timeout=0.8, workers=self.workers)
                     if ipaddress.ip_address(h) in network]
            accepted = []
            for candidate in found[:FIND_CANDIDATES]:
                url = f'http://{candidate}' + (f':{port}' if port != 80 else '')
                try:
                    self.make(url, self.board.token).ping()  # accepts the saved token, or it is not our board
                except (OSError, ValueError):
                    continue
                accepted.append(url)
        if len(accepted) != 1:
            self.log(FIND_LOG['several'] if accepted else FIND_LOG['none'])
            return None
        url = accepted[0]
        if self.policy is not None:
            self.policy.set_board_url(url)  # before the first request to it: the guard would refuse the new address
        try:
            self.save(url, self.board.token)
            self.log(FIND_LOG['found'])
        except (OSError, ValueError, KeyError, TypeError):
            self.log(FIND_LOG['unsaved'])  # it works from now on in memory; a restart would look again
        self.board.set_address(url)
        self.unreachable_since = None
        return url
