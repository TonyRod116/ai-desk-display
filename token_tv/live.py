"""Live account dashboard and stock-firmware image publisher."""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from token_tv.board import BoardDisplay, publish_pages
from token_tv.board_pages import render_board_pages
from token_tv.device import ALBUM_FACES, FILES, PhotoDisplay
from token_tv.catalog import payload as theme_payload
from token_tv.display import STYLES, render_page
from token_tv.web_assets import HTML, ASSETS, asset
from token_tv.sources import load_config
from token_tv.state import UsageStore
from token_tv.reset_balances import ResetBalances, attach_balances
from token_tv.claude_bank import ClaudeBankBridge


def clock_enabled(config):
    """True when the service should publish to the Geek TV clock."""
    return bool(config.get('device_url')) and config.get('display_enabled', True)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


class DisplayPreferences:
    def __init__(self, config_path, config):
        self.path = Path(config_path)
        self.config = dict(config)
        self.style = config.get('display_style', 'pixel')
        self.applied_style = None
        self.status = 'queued' if clock_enabled(config) else 'preview_only'
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.quota_changed = False
        self.reset_balances = ResetBalances(self.path.parent / 'reset-balances.json', config.get('accounts', []))
        self.claude_bank = ClaudeBankBridge(self.path.parent / 'claude-bank-bridge.json',
                                          lambda: self.config, self.reset_balances)

    def automatic_reset_providers(self):
        return [provider for provider in ('codex', 'claude')
                if self.config.get('automatic_' + provider + '_resets')]

    def snapshot(self):
        with self.lock:
            return {'style': self.style, 'applied_style': self.applied_style,
                    'status': self.status, 'styles': list(STYLES),
                    'rotation_seconds': self.config.get('display_rotation_seconds', 0),
                    'saved_resets': self.reset_snapshot(),
                    'automatic_reset_providers': self.automatic_reset_providers()}

    def reset_snapshot(self):
        settings = self.claude_bank.settings()
        return self.reset_balances.snapshot(self.automatic_reset_providers(),
                                           settings['organization_hash'] if settings else None)

    def request_quota_refresh(self):
        with self.lock:
            self.quota_changed = True
        self.changed.set()

    def consume_quota_refresh(self):
        with self.lock:
            refresh = self.quota_changed
            self.quota_changed = False
            return refresh

    def set_resets(self, provider, count):
        if provider in self.automatic_reset_providers():
            raise ValueError('This reset balance is read automatically')
        self.reset_balances.set_count(provider, count)
        self.changed.set()

    def set_style(self, style):
        if style not in STYLES:
            raise ValueError('Unknown display style')
        with self.lock:
            updated = dict(load_config(self.path), display_style=style)
            write_json(self.path, updated)
            self.config = updated
            self.style = style
            self.status = 'queued' if clock_enabled(self.config) else 'preview_only'
        self.changed.set()

    def delivered(self, style, success):
        with self.lock:
            if success:
                self.applied_style = style
            self.status = ('queued' if style != self.style else 'ok' if success else 'error')


def handler(store, preferences=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def local_request(self):
            # Loopback binding alone does not prevent a hostile page using DNS rebinding.
            try:
                host = urlparse('http://' + self.headers.get('Host', ''))
                valid = (host.hostname in {'localhost', '127.0.0.1', '::1'}
                         and (host.port or 80) == self.server.server_port
                         and not host.username and not host.password)
            except ValueError:
                valid = False
            if not valid:
                self.send_error(403, 'Local access only')
            return valid

        def do_GET(self):
            if not self.local_request():
                return
            url = urlparse(self.path)
            path = url.path
            snapshot = store.snapshot()
            if preferences:
                attach_balances(snapshot, preferences.reset_snapshot())
            display = preferences.snapshot() if preferences else {'style': 'pixel', 'status': 'preview_only', 'styles': list(STYLES)}
            snapshot['display'] = display
            content_type = "application/json; charset=utf-8"
            if path == "/":
                body = HTML.encode()
                content_type = "text/html; charset=utf-8"
            elif path in ASSETS:
                body, content_type = asset(path)
            elif path == "/snapshot":
                body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
            elif path.startswith("/snapshot/") and path[10:] in snapshot["accounts"]:
                body = json.dumps(snapshot["accounts"][path[10:]], ensure_ascii=False, separators=(",", ":")).encode()
            elif path in ("/frame/0.jpg", "/frame/1.jpg"):
                style = parse_qs(url.query).get('style', [display['style']])[0]
                if style not in STYLES:
                    self.send_error(400, 'Unknown display style')
                    return
                body = render_page(snapshot, int(path[7]), style)
                content_type = "image/gif" if body[:4] == b"GIF8" else "image/jpeg"
            elif path == '/themes':
                body = json.dumps(theme_payload()).encode()
            elif path == '/display':
                body = json.dumps(display).encode()
            elif path == "/health":
                expected_display = 'ok' if preferences and clock_enabled(preferences.config) else 'preview_only'
                banks = {provider: 'ok' if display.get('saved_resets', {}).get(provider, {}).get('available') is not None else 'unknown'
                         for provider in display.get('automatic_reset_providers', [])}
                degraded = (any(row['status'] != 'ok' for row in snapshot['accounts'].values())
                            or display['status'] != expected_display or 'unknown' in banks.values())
                body = json.dumps({"status": "degraded" if degraded else "ok",
                                   "updated_at": snapshot["updated_at"],
                                   "providers": {row['provider']: row['status'] for row in snapshot['accounts'].values()},
                                   "display_status": display['status'], "saved_resets": banks}).encode()
                self.reply(503 if degraded else 200, body)
                return
            else:
                self.send_error(404)
                return
            self.reply(200, body, content_type)

        def reply(self, status, body, content_type='application/json; charset=utf-8', bridge_cors=False):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if bridge_cors:
                self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Methods', 'POST')
                self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
                if self.headers.get('Access-Control-Request-Private-Network') == 'true':
                    self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A browser cancelled an obsolete preview request.

        def do_OPTIONS(self):
            if not self.local_request():
                return
            requested = {header.strip().lower() for header in self.headers.get('Access-Control-Request-Headers', '').split(',') if header.strip()}
            if (self.path != '/display/claude-bank' or preferences is None
                    or not preferences.claude_bank.origin_allowed(self.headers.get('Origin'))
                    or self.headers.get('Access-Control-Request-Method') != 'POST'
                    or not requested <= {'authorization', 'content-type'}):
                self.send_error(403, 'Paired local reader only')
                return
            self.reply(204, b'', bridge_cors=True)

        def receive_claude_bank(self):
            if preferences is None or not preferences.claude_bank.authorized(
                    self.headers.get('Origin'), self.headers.get('Authorization')):
                self.send_error(403, 'Paired local reader only')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid request')
                result = preferences.claude_bank.accept(json.loads(self.rfile.read(length)))
            except (ValueError, UnicodeError):
                # A current failed identity/date check also invalidates the old balance.
                preferences.changed.set()
                self.reply(400, b'{"status":"rejected"}', bridge_cors=True)
                return
            except OSError:
                self.reply(500, b'{"status":"unavailable"}', bridge_cors=True)
                return
            if result.get('status'):
                preferences.changed.set()
            self.reply(200, json.dumps(result).encode(), bridge_cors=True)

        def do_POST(self):
            if not self.local_request():
                return
            if self.path == '/display/claude-bank':
                self.receive_claude_bank()
                return
            path = urlparse(self.path).path
            if path not in ('/display/style', '/display/resets', '/display/reset-refresh', '/display/usage-refresh'):
                self.send_error(404)
                return
            if preferences is None:
                self.send_error(409, 'Display settings unavailable')
                return
            origin = self.headers.get('Origin')
            if origin and (urlparse(origin).scheme not in ('http', 'https') or urlparse(origin).netloc != self.headers.get('Host')):
                self.send_error(403, 'Origin mismatch')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid JSON request')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Invalid request')
                if path == '/display/style':
                    if set(data) != {'style'} or data['style'] not in STYLES:
                        raise ValueError('Unknown display style')
                    preferences.set_style(data['style'])
                elif path == '/display/resets':
                    if set(data) != {'provider', 'available'}:
                        raise ValueError('Invalid reset balance')
                    preferences.set_resets(data['provider'], data['available'])
                else:
                    if data:
                        raise ValueError('Invalid refresh notification')
                    if path == '/display/usage-refresh':
                        if not preferences.config.get('local_only'):
                            raise ValueError('Only local-cache refreshes are allowed')
                        preferences.request_quota_refresh()
                    preferences.changed.set()
            except (ValueError, UnicodeError):
                self.send_error(400, 'Choose a supported style or reset balance')
                return
            except OSError:
                self.send_error(500, 'Could not save display choice')
                return
            self.reply(200, json.dumps(preferences.snapshot()).encode())
    return Handler


def main():
    parser = argparse.ArgumentParser(description="TokenTV live account display")
    parser.add_argument("--config", required=True, help="Credential-free account metadata")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--output", help="Write a normalized snapshot rather than stdout")
    parser.add_argument("--state-dir", default=".runtime")
    parser.add_argument("--restore-display", action="store_true")
    args = parser.parse_args()
    if args.host not in ('127.0.0.1', 'localhost'):
        parser.error('This installation only serves the dashboard on localhost')
    config = load_config(args.config)
    if config.get('local_only'):
        from token_tv.local_usage import LocalPolicy, fetch_local
        sys.addaudithook(LocalPolicy(config.get('device_url'), (config.get('board_display') or {}).get('url')).audit)
    if config.get("font"):
        os.environ["TOKEN_TV_FONT"] = config["font"]
    state_dir = Path(args.state_dir)
    clock = PhotoDisplay(config["device_url"]) if config.get("device_url") else None
    device = clock if clock_enabled(config) else None   # `token-tv clock --off`: the clock is left alone
    board = (BoardDisplay(config["board_display"]["url"], config["board_display"]["token"])
             if config.get("board_display") else None)
    board_sent = {}
    board_selected = {'done': False}
    backup_path = state_dir / "display-original.json"
    if args.restore_display:
        if not clock or not backup_path.is_file():
            parser.error("A display and its original state backup are required")
        clock.restore(json.loads(backup_path.read_text()))
        print("Original display selection restored.")
        return
    if config.get('local_only'):
        cache_dir = Path(args.config).expanduser().parent / 'offline'
        store = UsageStore(config['accounts'], fetch=lambda account: fetch_local(
            account, cache_dir, official_claude=config.get('automatic_claude_usage', False),
            official_codex=config.get('automatic_codex_resets', False)))
    else:
        store = UsageStore(config["accounts"])
    preferences = DisplayPreferences(args.config, config)
    interval = max(60, int(config.get("poll_seconds", 300)))
    if config.get('local_only') and (config.get('automatic_codex_resets') or config.get('automatic_claude_usage')):
        interval = 60  # Recover missed notifications and expire stopped readers without session activity.
    stopping = threading.Event()
    original = None
    active_file = None
    last_upload = None
    album_uploads = {}

    def cycle(refresh=True):
        nonlocal original, active_file, last_upload
        if refresh:
            store.refresh()
        snapshot = store.snapshot()
        attach_balances(snapshot, preferences.reset_snapshot())
        style = preferences.snapshot()['style']
        if not args.once and device:
            receipts = []
            phase = "backup"
            try:
                if original is None:
                    candidate = json.loads(backup_path.read_text()) if backup_path.is_file() else device.capture()
                    device.resume(candidate)
                    if not backup_path.is_file():
                        write_json(backup_path, candidate)
                    original = candidate
                phase = "upload"
                image = render_page(snapshot, 0, style)
                album_mode = bool(config.get('display_album_faces') and device.profile == 'ultra')
                name = ALBUM_FACES.get(style) if album_mode else None
                name = name or (FILES[1] if image[:4] == b"GIF8" else FILES[0])
                digest = hashlib.sha256(image).hexdigest()
                uploaded = (name, digest) != last_upload
                if uploaded:  # identical frames are not rewritten to flash
                    (state_dir / name).write_bytes(image)
                    receipts.append(dict(device.upload(name, image), sha256=digest))
                    last_upload = (name, digest)
                    if name in ALBUM_FACES.values():
                        album_uploads[name] = digest
                    if device.profile == 'ultra' and not album_mode:
                        active_file = None  # an uploaded replacement still needs a successful selection
                if album_mode:
                    for other_style, other_name in ALBUM_FACES.items():
                        if other_name == name:
                            continue
                        other_image = render_page(snapshot, 0, other_style)
                        other_digest = hashlib.sha256(other_image).hexdigest()
                        if album_uploads.get(other_name) != other_digest:
                            (state_dir / other_name).write_bytes(other_image)
                            receipts.append(dict(device.upload(other_name, other_image), sha256=other_digest))
                            album_uploads[other_name] = other_digest
                if active_file != name or preferences.snapshot()['status'] == 'queued' or (uploaded and device.profile == 'ultra' and not album_mode):
                    phase = "activate"
                    device.activate(original, name, rotation_seconds=config.get('display_rotation_seconds', 0))
                    active_file = name
                write_json(state_dir / "display-receipt.json", {"at": int(time.time()), "style": style, "uploads": receipts})
                preferences.delivered(style, True)
            except (OSError, ValueError, KeyError) as error:
                write_json(state_dir / "display-receipt.json", {"at": int(time.time()), "style": style, "status": "error", "phase": phase,
                           "uploads": receipts, "http_status": getattr(error, "code", None)})
                preferences.delivered(style, False)
        if not args.once and board:
            # Independent of the clock: a missing board never delays or fails the clock's cycle.
            try:
                board.ensure_paired()  # a reflashed board is claimed again without anyone typing
                pages = render_board_pages(snapshot, stars=board.stars, anim=board.anim,
                                           waves=getattr(board, 'waves', False))
                receipts = publish_pages(board, pages, board_sent)
                board.set_active_pages(len(pages))  # a page that was deleted is no longer cycled
                if not board_selected['done']:  # firmware that stays on its address screen until touched
                    board.select_initial_page()
                    board_selected['done'] = True
                write_json(state_dir / "board-receipt.json", {"at": int(time.time()), "uploads": receipts})
            except (OSError, ValueError) as error:
                write_json(state_dir / "board-receipt.json", {"at": int(time.time()), "status": "error",
                           "http_status": getattr(error, "code", None)})
        snapshot['display'] = preferences.snapshot()
        write_json(state_dir / "snapshot.json", snapshot)
        if args.output:
            write_json(args.output, snapshot)

    if args.once:
        cycle()
        if not args.output:
            print(json.dumps(store.snapshot(), ensure_ascii=False, separators=(",", ":")))
        return

    def poll():
        next_refresh = 0
        while not stopping.is_set():
            preferences.changed.clear()
            quota_refresh = preferences.consume_quota_refresh()
            refresh = time.monotonic() >= next_refresh or quota_refresh
            try:
                cycle(refresh)
            except Exception:
                # Never serialize exception text, which may include auth material.
                print("TokenTV poll failed; retained previous snapshot.", flush=True)
            if refresh:
                next_refresh = time.monotonic() + interval
            preferences.changed.wait(max(0, next_refresh - time.monotonic()))

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    try:
        with ThreadingHTTPServer((args.host, args.port), handler(store, preferences)) as server:
            print(f"TokenTV live listening at http://{args.host}:{args.port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        preferences.changed.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
