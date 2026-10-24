"""PC side of the touch ESP32 board: pushes pre-rendered pages, never asks it for data.

Same shape as the clock: the PC renders, the board only shows images. The board
holds the pages and changes between them on touch, so nothing on this computer
listens beyond localhost. Every call carries the board's token, which the board
generated and shows on its own screen.
"""
from datetime import datetime
import hashlib
import ipaddress
import json
import re
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from urllib.request import Request

from token_tv.http import open_direct

MAX_PAGE_BYTES = 8 + 320 * 240 * 2 + 81920  # pixels plus the firmware 14 animation allowance
PAGES = 8  # what this PC can send; the board says how many it holds (older firmware: 6)
TOKEN = re.compile(r'[0-9a-f]{16}')


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
        self.capacity = 6  # until the board says otherwise: the first firmware had six slots
        self.stars = False  # firmware 4+ can make the stars of a page twinkle (5 flares them as a cross)
        self.anim = False  # firmware 7+ moves sprites over a page (ANIM trailer)
        self.anim_frames = 4  # firmware 14 advertises eight-frame scenery
        self.waves = False  # firmware 8+ moves the whole photographic sea at native resolution
        self.remembers_selection = False
        self.active = None  # how many page slots the board cycles; None on firmware without the setting

    def request(self, path, data=None, headers=None, authorized=True):
        headers = dict(headers or {})
        if authorized:
            headers['X-Token'] = self.token
        # The board keeps animating while transferring a page: a measured
        # upload/readback took 42/24 s. Keep controls short, allow page I/O
        # enough time, and still verify every stored byte in upload().
        timeout = 60 if path.split('?', 1)[0] == '/page' else 20
        with open_direct(Request(self.base_url + path, data=data, headers=headers),
                         timeout=timeout, no_proxy=True) as response:
            return response.status, response.read()

    def info(self):
        _, body = self.request('/info', authorized=False)
        return json.loads(body)

    def ping(self):
        """Heartbeat. Returns which pages the board holds, e.g. '110111' (older firmware answers 'OK')."""
        # Local civil seconds align boundaries with the PC's timezone, including DST.
        now = datetime.now().astimezone()
        civil = int(now.timestamp()) + int(now.utcoffset().total_seconds())
        _, body = self.request(f'/ping?clock={civil}', data=b'')
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
        self.waves = info.get('waves') in (1, True)
        active = info.get('active')
        self.active = active if type(active) is int and 1 <= active <= PAGES else None
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

    def configure(self, rotation=None, invert=None, swap_red_blue=None, swap_bytes=None, pages=None):
        """Panel options kept on the board: 1 or 3 for landscape either way up, inverted colours,
        red and blue swapped, byte order of each pixel swapped, how many page slots are cycled."""
        options = []
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
        status, _ = self.request(f'/page?n={number}', body,
                                 {'Content-Type': 'multipart/form-data; boundary=' + boundary})
        if self.read(number) != image:  # what the board stored must be what was sent
            raise ValueError('Board image verification failed')
        return {'page': number, 'status': status, 'bytes': len(image)}


def publish_pages(board, pages, sent):
    """Heartbeat, then send the pages that changed or that the board lacks. Returns the receipts.

    `sent` maps page number to the digest the board already holds. Any failure
    forgets it, so a board that rebooted or came back is refreshed in full.
    """
    receipts = []
    try:
        held = board.ping()
        known = bool(held) and set(held) <= {'0', '1'}
        capacity = getattr(board, 'capacity', len(pages))
        for number, image in enumerate(pages[:capacity]):  # never more pages than the board has slots
            digest = hashlib.sha256(image).hexdigest()
            lacks = known and number < len(held) and held[number] == '0'
            if sent.get(number) != digest or lacks:  # identical pages are not rewritten to the board's flash
                receipts.append(dict(board.upload(number, image), sha256=digest))
                sent[number] = digest
    except (OSError, ValueError):
        sent.clear()
        raise
    return receipts


def find_boards(hosts, port=80, timeout=0.8):
    """The addresses among `hosts` that answer like a TokenTV board (GET /info, nothing else sent)."""
    def probe(host):
        try:
            with open_direct(Request(f'http://{host}:{port}/info'), timeout=timeout, no_proxy=True) as response:
                data = json.loads(response.read(4000))
            return host if isinstance(data, dict) and data.get('model') == 'tokentv-board' else None
        except (OSError, ValueError):
            return None
    with ThreadPoolExecutor(max_workers=64) as pool:
        return [host for host in pool.map(probe, hosts) if host]


def subnet_hosts(address):
    """Every host of the /24 around a private IPv4 address."""
    return [str(host) for host in ipaddress.ip_network(f'{address}/24', strict=False).hosts()]


def new_token():
    return secrets.token_hex(8)
