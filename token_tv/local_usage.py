"""Read reported local quotas without running a CLI or opening credential files."""
import fcntl
import hashlib
import heapq
import ipaddress
import json
import math
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from token_tv.usage import timestamp, window

OFFICIAL_MAX_AGE_SECONDS = 180


def live_claude_windows(windows, now):
    """A rolled-over five-hour window is unknown; the weekly window has its own reset."""
    return [w for w in windows if w.get('label') == 'WEEK'
            or (w.get('resets_at') is not None and w['resets_at'] > now)]


def reset_lapsed(windows, now, claude=False):
    """A passed reset. For Claude, a weekly window without any reset is unconfirmed too."""
    return any(w.get('resets_at') is not None and w['resets_at'] <= now
               or claude and w.get('label') == 'WEEK' and w.get('resets_at') is None
               for w in windows)


def expire_official_quota(row, now=None):
    """Old official quota is unknown, even when the poller stops progressing."""
    source = row.get('quota_origin')
    if source not in ('codex_official_cli', 'claude_official_cli'):
        return
    now = time.time() if now is None else now
    age = now - row.get('fetched_at', 0)
    if source == 'claude_official_cli':
        row['windows'] = live_claude_windows(row['windows'], now)
    expired = reset_lapsed(row['windows'], now, source == 'claude_official_cli')
    if age > OFFICIAL_MAX_AGE_SECONDS or age < -60 or expired:
        row['windows'] = []
        row['status'] = 'quota_unavailable'
        row.setdefault('error_code', 'reset_not_confirmed_locally' if expired else 'quota_refresh_overdue')
    elif source == 'codex_official_cli' and row.get('ordinary_usage_allowed') is not True:
        blocked = row.get('ordinary_usage_allowed') is False
        # A fresh explicit zero is a valid reading, even though work is blocked.
        # Never infer exhaustion from the permission flag or retain usable quota.
        exhausted = [w for w in row['windows'] if w.get('label') == 'WEEK'
                     and w.get('used_percent') == 100
                     and w.get('resets_at') is not None and w['resets_at'] > now]
        if blocked and row['status'] == 'ok' and exhausted:
            row['windows'] = exhausted
        else:
            row['windows'] = []
            row['status'] = 'usage_blocked' if blocked else 'quota_unavailable'
            row['error_code'] = 'usage_blocked' if blocked else 'usage_permission_unavailable'
    elif not any(w.get('label') == 'WEEK' for w in row['windows']):
        row['windows'] = []
        row['status'] = 'quota_unavailable'
        row['error_code'] = 'weekly_quota_unavailable'
    elif row['status'] != 'ok':
        row['windows'] = []
        row['status'] = 'quota_unavailable'


class LocalPolicy:
    """Fail closed on external sockets, child processes and credential-file reads."""
    def __init__(self, device_url=None, board_url=None):
        self.clock = None
        self.port = 80
        self.endpoints = []  # (private address, port) of the clock and, optionally, the touch board
        for text in (device_url, board_url):
            if not text:
                continue
            url = urlparse(text)
            address = ipaddress.ip_address(url.hostname)
            port = url.port or 80
            if url.scheme != 'http' or not address.is_private or address.is_unspecified:
                raise ValueError('Local mode requires a private clock IP address')
            self.endpoints.append((address, port))
            if self.clock is None:
                self.clock, self.port = address, port

    def allowed_host(self, host, port=None):
        if host == 'localhost':
            return True
        try:
            address = ipaddress.ip_address(host)
        except (ValueError, TypeError):
            return False
        return address.is_loopback or any(
            address == known and (port is None or port == known_port) for known, known_port in self.endpoints)

    def audit(self, event, args):
        if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec'):
            raise PermissionError('Local quota mode does not run child processes')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            if Path(os.fsdecode(args[0])).name in {'auth.json', '.credentials.json'}:
                raise PermissionError('Local quota mode does not read credentials')
        if event == 'socket.getaddrinfo' and not self.allowed_host(args[0]):
            raise PermissionError('External name lookup blocked in local quota mode')
        if event in ('socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr') and not self.allowed_host(args[0]):
            raise PermissionError('External name lookup blocked in local quota mode')
        if event == 'socket.getnameinfo' and not self.allowed_host(args[0][0]):
            raise PermissionError('External name lookup blocked in local quota mode')
        if event in ('socket.connect', 'socket.sendto', 'socket.sendmsg') and isinstance(args[1], tuple):
            if not self.allowed_host(args[1][0], args[1][1]):
                raise PermissionError('External connection blocked in local quota mode')


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, separators=(',', ':'))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_record(path):
    try:
        path = Path(path)
        if path.stat().st_size > 256000:
            return None
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clean_windows(values):
    result = []
    if not isinstance(values, list):
        return result
    for value in values:
        if not isinstance(value, dict) or value.get('label') not in {'5H', 'WEEK', 'WINDOW'}:
            continue
        item = window(value['label'], value.get('used_percent'), value.get('resets_at'), value.get('duration_minutes'))
        if item:
            result.append(item)
    return result


def origin_id(root, expected_email=None):
    value = str(Path(root).expanduser().resolve())
    if expected_email is not None:
        value += '\0' + expected_email.strip().casefold()
    return hashlib.sha256(value.encode()).hexdigest()


def codex_record(root):
    def modified(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0
    recent = heapq.nlargest(8, (Path(root) / 'sessions').glob('**/*.jsonl'), key=modified)
    records = []
    for path in recent:
        try:
            with path.open('rb') as handle:
                offset = max(0, path.stat().st_size - 2000000)
                handle.seek(offset)
                if offset:
                    handle.readline()  # discard a partial JSON record
                lines = handle.read(2000000).splitlines()
            for line in reversed(lines):
                if b'"rate_limits"' not in line or len(line) > 500000:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get('type') != 'event_msg':
                    continue
                payload = event.get('payload')
                if not isinstance(payload, dict) or payload.get('type') != 'token_count':
                    continue
                rates = payload.get('rate_limits')
                fetched = timestamp(event.get('timestamp'))
                if (not isinstance(rates, dict) or rates.get('limit_id') not in (None, 'codex')
                        or fetched is None or fetched > time.time() + 60):
                    continue
                values = []
                for key in ('primary', 'secondary'):
                    value = rates.get(key)
                    if not isinstance(value, dict):
                        continue
                    duration = value.get('window_minutes')
                    label = {300: '5H', 10080: 'WEEK'}.get(duration, 'WINDOW') if isinstance(duration, int) else 'WINDOW'
                    item = window(label, value.get('used_percent'), value.get('resets_at'), duration)
                    if item:
                        values.append(item)
                if values:
                    records.append({'fetched_at': fetched, 'windows': values, 'source': 'codex_session',
                                    'origin': origin_id(root)})
                    break
        except OSError:
            continue
    return max(records, key=lambda row: row['fetched_at']) if records else None


def capture_claude(data, path, now=None, source_home='~/.claude'):
    """Accept only native status-line quota fields; unchanged callbacks stay old."""
    if not isinstance(data, dict) or not isinstance(data.get('rate_limits'), dict):
        return False
    now = int(time.time() if now is None else now)
    values = []
    for key, label, duration in (('five_hour', '5H', 300), ('seven_day', 'WEEK', 10080)):
        rate = data['rate_limits'].get(key)
        if isinstance(rate, dict):
            item = window(label, rate.get('used_percentage'), rate.get('resets_at'), duration)
            if item:
                values.append(item)
    if not values:
        return False
    cost = data.get('cost') if isinstance(data.get('cost'), dict) else {}
    context = data.get('context_window') if isinstance(data.get('context_window'), dict) else {}
    api_ms = cost.get('total_api_duration_ms')
    output_tokens = context.get('total_output_tokens')
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for value in (api_ms, output_tokens)):
        return False
    session = data.get('session_id') if isinstance(data.get('session_id'), str) else 'unknown'
    session = hashlib.sha256(session.encode()).hexdigest()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_record(path) or {}
        origin = origin_id(source_home)
        if previous.get('origin') != origin:
            previous = {}
        markers = previous.get('markers') if isinstance(previous.get('markers'), dict) else {}
        markers = {key: value for key, value in markers.items() if isinstance(value, dict)
                   and timestamp(value.get('observed_at')) and timestamp(value['observed_at']) <= now + 60}
        prior = markers.get(session, {})
        previous_api = prior.get('api_ms')
        previous_output = prior.get('output_tokens')
        changed = (type(previous_api) in (int, float) and api_ms > previous_api
                   and type(previous_output) in (int, float) and output_tokens > previous_output)
        observed = now if changed or not prior else prior['observed_at']
        markers[session] = {'observed_at': observed, 'api_ms': api_ms, 'output_tokens': output_tokens}
        markers = dict(sorted(markers.items(), key=lambda p: p[1]['observed_at'], reverse=True)[:64])
        if changed and observed >= (timestamp(previous.get('fetched_at')) or 0):
            saved = {'fetched_at': observed, 'windows': values, 'source': 'claude_statusline'}
        else:
            saved = {'fetched_at': previous.get('fetched_at'), 'windows': clean_windows(previous.get('windows')),
                     'source': 'local_cache'}
        saved['markers'] = markers
        saved['origin'] = origin
        atomic_json(path, saved)
    return True


def local_row(account, record, now=None):
    now = time.time() if now is None else now
    row = {'key': account['key'], 'alias': account['alias'], 'provider': account['provider'],
           'status': 'quota_unavailable', 'windows': [], 'fetched_at': 0,
           'identity_verified': False, 'source': 'local'}
    if not isinstance(record, dict):
        return row
    if record.get('source') in ('claude_official_cli', 'codex_official_cli'):
        row['quota_origin'] = record['source']
    if row.get('quota_origin') == 'codex_official_cli':
        allowed = record.get('ordinary_usage_allowed')
        row['ordinary_usage_allowed'] = allowed if type(allowed) is bool else None
    fetched = timestamp(record.get('fetched_at'))
    if fetched is None or fetched > now + 60:
        return row
    values = clean_windows(record.get('windows'))
    if record.get('source') == 'claude_official_cli':
        values = live_claude_windows(values, now)
    expired = reset_lapsed(values, now, record.get('source') == 'claude_official_cli')
    row['windows'] = [] if expired else values
    row['fetched_at'] = row['last_success_at'] = fetched
    if row['windows']:
        row['status'] = 'stale' if record.get('stale') is True or now - fetched > 900 else 'ok'
        if row['provider'] in ('claude', 'codex') and not any(w['label'] == 'WEEK' for w in row['windows']):
            row['windows'] = []
            row['status'] = 'quota_unavailable'
            row['error_code'] = 'weekly_quota_unavailable'
    if expired:
        row['error_code'] = 'reset_not_confirmed_locally'
    expire_official_quota(row, now)
    return row


def fetch_local(account, cache_dir, official_claude=False, official_codex=False):
    provider = account['provider']
    if (provider == 'codex' and official_codex) or (provider == 'claude' and official_claude):
        source = provider + '_official_cli'
        record = read_record(Path(cache_dir) / (provider + '-official.json'))
        if (not record or record.get('origin') != origin_id(account['source_home'], account.get('email'))
                or record.get('source') != source):
            record = None
        row = local_row(account, record)
        row['quota_origin'] = source
        row['identity_verified'] = bool(record and account.get('email')
                                        and record.get('identity_verified') is True and row['status'] == 'ok')
        return row
    if account.get('email'):
        # Session/status-line files do not prove which login produced them.
        # An identity-pinned account must wait for its authenticated reader.
        return local_row(account, None)
    records = []
    cached = read_record(Path(cache_dir) / (account['provider'] + '.json'))
    if cached and cached.get('origin') == origin_id(account['source_home']):
        records.append(cached)
    if account['provider'] == 'codex':
        native = codex_record(Path(account['source_home']).expanduser())
        if native:
            records.append(native)
    valid = [r for r in records if timestamp(r.get('fetched_at')) and timestamp(r['fetched_at']) <= time.time() + 60]
    latest = max(valid, key=lambda r: timestamp(r['fetched_at'])) if valid else None
    return local_row(account, latest)
