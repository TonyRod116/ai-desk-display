"""Trigger the official /usage view; export only its dated native quota cache."""
import fcntl
import json
import math
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time
from datetime import datetime, timedelta
from pathlib import Path

from token_tv.local_usage import clean_windows, origin_id
from token_tv.sources import SourceError, exe, scoped_env, identity_matches
from token_tv.usage import normalize_claude, timestamp

ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*?(?:\x07|\x1b\\)|[78])')
# Patch releases of the reviewed client series show the same safe-mode screen,
# and every other marker in read() must still match. A new series gets no command.
SERIES = (2, 1)
BANNER = re.compile(r'Claude Code v(\d+)\.(\d+)\.\d+(?![\d.])')
# The client reuses its own usage cache when something else (another Claude session) fetched it a moment ago, and then writes
# no newer date. Such a reading is as good as a new one while it is young: after waiting REUSE_AFTER seconds for a fresh fetch to
# land, a native cache no older than REUSE_SECONDS is accepted with its real fetch date (the monitor still expires it at 180 s).
REUSE_AFTER = 10
REUSE_SECONDS = 90
# Words that, if the usage screen shows them, say WHY a refresh was not confirmed. Only whether each one appeared is ever
# kept (a yes/no per word), never the screen text, so a diagnosis can not leak anything about the account.
SCREEN_HINTS = ('rate limit', '429', 'too many requests', 'failed to', 'error', 'unable to', 'try again', 'retrying',
                'not logged in', '/login', 'expired', 'network', 'current session', 'current week',
                'organization has disabled')
# The client's own status line (scripts/claude_statusline_capture.py) carries the same quota numbers, free of any new request or
# client start. A capture this young with both windows live is as good as a `/usage` run; the reader still proves the login
# (`authenticate`) before relying on it. Tony approved this on 2026-11-03.
STATUSLINE_MAX_AGE = 100
STATUSLINE_SOURCE = 'claude_official_statusline'
# `/usage` says "rate limited until <time>" while it is limiting requests. Only that moment, as a number, is ever kept.
RATE_LIMITED_UNTIL = re.compile(r'rate[ -]limited until\s+([^\r\n]{1,48})', re.I)
RETRY_MAX_AHEAD = 6 * 3600
MONTHS = 'jan feb mar apr may jun jul aug sep oct nov dec'.split()


def reader_env(root):
    root = Path(root).expanduser().resolve()
    env = scoped_env('claude', root)
    if root == (Path.home() / '.claude').resolve():
        env.pop('CLAUDE_CONFIG_DIR', None)
        env.pop('CLAUDE_SECURESTORAGE_CONFIG_DIR', None)
    for key in list(env):
        if key.startswith(('ANTHROPIC_', 'CLAUDE_CODE_')) or key in {
            'NODE_OPTIONS', 'NODE_EXTRA_CA_CERTS', 'LD_PRELOAD', 'DYLD_INSERT_LIBRARIES',
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy',
            'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'}:
            env.pop(key, None)
    # The aggregate NONESSENTIAL_TRAFFIC flag also suppresses /usage. Disable
    # the unwanted features individually while retaining the account GET.
    env.update(DISABLE_TELEMETRY='1', DISABLE_ERROR_REPORTING='1', DISABLE_AUTOUPDATER='1',
               TERM='xterm-256color', NO_COLOR='1')
    return env


def native_config_path(root):
    root = Path(root).expanduser().resolve()
    return Path.home() / '.claude.json' if root == (Path.home() / '.claude').resolve() else root / '.claude.json'


def native_record(data, root, since, now=None, expected_email=None):
    """The client's fetch date is authoritative, including on cached failures."""
    now = time.time() if now is None else now
    cache = data.get('cachedUsageUtilization') if isinstance(data, dict) else None
    identity = data.get('oauthAccount') if isinstance(data, dict) else None
    if not isinstance(cache, dict) or not isinstance(identity, dict):
        return None
    if expected_email is not None and (not isinstance(identity.get('emailAddress'), str)
                                     or not identity_matches(expected_email, identity['emailAddress'])):
        return None
    if not isinstance(cache.get('accountUuid'), str) or not cache['accountUuid'] or cache['accountUuid'] != identity.get('accountUuid'):
        return None
    millis = cache.get('fetchedAtMs')
    if type(millis) not in (int, float) or not math.isfinite(millis):
        return None
    fetched = millis / 1000
    if not 0 <= now - fetched <= 3600 or fetched > now + 1:
        return None
    rates = cache.get('utilization')
    if not isinstance(rates, dict):
        return None
    if any(rates.get(key) is not None and not isinstance(rates[key], dict)
           for key in ('five_hour', 'seven_day')):
        return None
    windows = normalize_claude(rates)
    expected = sum(rates.get(key) is not None for key in ('five_hour', 'seven_day'))
    if not windows or len(windows) != expected:
        return None
    # A five-hour window that has just rolled over has no live reset yet: that
    # number is unknown, so drop it. The weekly reading keeps its own reset.
    windows = [w for w in windows if w['label'] == 'WEEK' or (w['resets_at'] or 0) > now]
    if not windows or any(w['resets_at'] is None or w['resets_at'] <= now for w in windows):
        return None
    return {'fetched_at': fetched, 'windows': windows, 'origin': origin_id(root, expected_email),
            'source': 'claude_official_cli', 'stale': fetched < since - 1,
            'identity_verified': expected_email is not None}


def statusline_record(capture, root, expected_email=None, now=None):
    """The status-line capture as an official reading, or None unless it is recent, complete (both windows, resets still ahead)
    and written for this source home. It keeps the capture's REAL fetch time, never the time it was read. The caller proves the
    login (`ClaudeUsageReader.authenticate`) before it publishes this: a capture alone cannot name its account."""
    now = time.time() if now is None else now
    if not isinstance(capture, dict) or capture.get('origin') != origin_id(root):
        return None
    if capture.get('source') not in ('claude_statusline', 'local_cache'):
        return None
    fetched = timestamp(capture.get('fetched_at'))
    if fetched is None or not 0 <= now - fetched <= STATUSLINE_MAX_AGE:
        return None
    windows = clean_windows(capture.get('windows'))
    if sorted(w['label'] for w in windows) != ['5H', 'WEEK'] or any(w['resets_at'] is None or w['resets_at'] <= now for w in windows):
        return None
    return {'fetched_at': fetched, 'windows': windows, 'origin': origin_id(root, expected_email), 'source': STATUSLINE_SOURCE,
            'stale': False, 'identity_verified': False}


def rate_limited_until(text, now=None):
    """The moment (epoch seconds, an int) a screen says it is rate limited until, else None. The format is not documented, so
    12 h ("3:45 PM", "3pm") and 24 h ("15:45") clocks are read as local time, with an optional "tomorrow" or "Nov 3". Anything
    unparsable, already past or more than six hours ahead is ignored: the caller then falls back to its own backoff."""
    now = time.time() if now is None else now
    found = RATE_LIMITED_UNTIL.search(text)
    if not found:
        return None
    tail = found[1].lower()
    clock = (re.search(r'\b(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap])\.?m\b', tail)
             or re.search(r'\b(\d{1,2})()()\s*([ap])\.?m\b', tail)
             or re.search(r'\b(\d{1,2}):(\d{2})(?::(\d{2}))?()', tail))
    if not clock:
        return None
    hour, minute, second, meridian = int(clock[1]), int(clock[2] or 0), int(clock[3] or 0), clock[4]
    if meridian:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridian == 'p' else 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    months = '|'.join(MONTHS)
    by_name = re.search(rf'\b({months})[a-z]*\.?\s+(\d{{1,2}})(?![\d:])', tail)   # "nov 3" (not "nov 00:10")
    by_day = re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({months})', tail)      # "3 nov"
    date = ((MONTHS.index(by_name[1]) + 1, int(by_name[2])) if by_name else
            (MONTHS.index(by_day[2]) + 1, int(by_day[1])) if by_day else None)
    try:
        when = datetime.fromtimestamp(now).replace(hour=hour, minute=minute, second=second, microsecond=0)
        if date:
            when = when.replace(month=date[0], day=date[1])
            if when.timestamp() < now - 180 * 86400:
                when = when.replace(year=when.year + 1)
        elif 'tomorrow' in tail or when.timestamp() < now - 60:
            when += timedelta(days=1)   # a clock time already gone is the next one, e.g. 12:10 AM at 11:50 PM
        ahead = when.timestamp() - now
    except (ValueError, OverflowError, OSError):
        return None
    return int(when.timestamp()) if 0 < ahead <= RETRY_MAX_AHEAD else None


class ClaudeUsageReader:
    def __init__(self, root, workspace, expected_email=None):
        self.root = Path(root).expanduser().resolve()
        self.expected_email = expected_email
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.env = reader_env(self.root)
        self.env['PWD'] = str(self.workspace)
        self.cli = exe('claude')
        self.trace = {}

    def authenticate(self):
        command = [self.cli, '--safe-mode', '--restricted', '--setting-sources', '',
                   'auth', 'status', '--json']
        try:
            result = subprocess.run(command, cwd=self.workspace, env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, timeout=20)
            data = json.loads(result.stdout) if result.returncode == 0 else {}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise SourceError('auth_unavailable') from None
        if not (data.get('loggedIn') is True and data.get('authMethod') == 'claude.ai'
                and data.get('apiProvider') == 'firstParty'
                and data.get('subscriptionType') in ('max', 'pro', 'team', 'enterprise')):
            raise SourceError('subscription_login_required')
        if self.expected_email is not None and (not isinstance(data.get('email'), str)
                                               or not identity_matches(self.expected_email, data['email'])):
            raise SourceError('identity_mismatch')

    def cached(self, since):
        path = native_config_path(self.root)
        try:
            if path.stat().st_size > 16000000:
                return None
            return native_record(json.loads(path.read_text()), self.root, since,
                                 expected_email=self.expected_email)
        except (OSError, ValueError, TypeError):
            return None

    def take(self, started, free_at):
        """The native cache if this run may use it: written after we started, or young enough once the wait is over."""
        record = self.cached(started)
        if not record or not record['stale']:
            return record
        if (free_at is not None and time.monotonic() - free_at >= REUSE_AFTER
                and 0 <= time.time() - record['fetched_at'] <= REUSE_SECONDS):
            return {**record, 'stale': False}
        return record

    def read(self, cancel_event=None):
        cancelled = lambda: cancel_event is not None and cancel_event.is_set()
        self.trace = {}   # a failure before the client opens (login, identity) must not inherit the last run's screen words
        if cancelled():
            raise SourceError('cancelled')
        self.authenticate()
        if cancelled():
            raise SourceError('cancelled')
        started = time.time()
        began = time.monotonic()
        free_at = None
        text = ''
        command = [self.cli, '--safe-mode', '--restricted', '--tools', '',
                   '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                   '--setting-sources', '', '--no-chrome', '--ax-screen-reader',
                   '--prompt-suggestions', 'false', '--permission-mode', 'manual']
        master = slave = None
        process = None
        sent = False
        model_free = False
        buffer = b''
        try:
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 50, 160, 0, 0))
            process = subprocess.Popen(command, cwd=self.workspace, env=self.env,
                                       stdin=slave, stdout=slave, stderr=slave,
                                       start_new_session=True)
            os.close(slave)
            slave = None
            deadline = time.monotonic() + 30
            while not cancelled() and time.monotonic() < deadline and process.poll() is None:
                if not select.select([master], [], [], .25)[0]:
                    # The client can persist the GET result after its last PTY
                    # output. Silence must not hide a newly dated quota cache.
                    if sent and model_free:
                        record = self.take(started, free_at)
                        if record and not record['stale'] and not cancelled():
                            return record
                    continue
                try:
                    buffer += os.read(master, 65536)
                except OSError:
                    break
                if len(buffer) > 1000000:
                    raise SourceError('cli_output_limit')
                text = ANSI.sub('', buffer.decode('utf-8', 'replace'))
                if not sent:
                    banners = list(BANNER.finditer(text))
                    if any((int(b[1]), int(b[2])) != SERIES for b in banners):
                        raise SourceError('unsupported_client_version')
                    # Markers must belong to the latest header, never to an earlier screen.
                    screen = text[banners[-1].start():] if banners else ''
                    lower = screen.lower()
                    location = (str(self.workspace) in screen or
                                self.workspace.is_relative_to(Path.home()) and str(self.workspace.relative_to(Path.home())) in screen)
                    ready = (banners and 'manual mode on' in lower
                             and 'all customizations are disabled' in lower
                             and location
                             and re.search(r'[$]{1,3}\s*$', screen))
                    if ready and not cancelled():
                        os.write(master, b'/usage\r')
                        sent = True
                        buffer = b''
                    continue
                costs = re.findall(r'(?:Total cost|Cost):?\s*\$([\d.]+)', text, re.I)
                if costs:
                    if any(float(value) != 0 for value in costs):
                        raise SourceError('unexpected_model_activity')
                    model_free = True
                    free_at = free_at if free_at is not None else time.monotonic()
                if model_free:
                    record = self.take(started, free_at)
                    if record and not record['stale'] and not cancelled():
                        return record
            if cancelled():
                raise SourceError('cancelled')
            # One final check catches persistence immediately before client exit.
            # native_record preserves the fetch date and marks old data stale;
            # never downgrade a fresh validated result just because PTY ended.
            record = self.take(started, free_at) if sent and model_free else None
            if record:
                return record
            # Fixed identifiers only: they say which step failed and reach the log.
            if not sent:
                raise SourceError('client_not_ready')
            raise SourceError('official_quota_unavailable' if model_free else 'usage_view_not_confirmed')
        finally:
            # How old the client's own usage cache was when this run ended (None if unreadable): a cache fetched shortly before
            # `started` means the client reused it instead of asking again.
            kept = self.cached(0)
            flat = ' '.join(text.lower().split())   # a message wrapped over two lines still counts
            self.trace = {'seconds': round(time.monotonic() - began, 1), 'sent': sent, 'model_free': model_free,
                          'cache_age_at_end': round(time.time() - kept['fetched_at'], 1) if kept else None,
                          'cache_age_at_start': round(started - kept['fetched_at'], 1) if kept else None,
                          'client_exited': process is not None and process.poll() is not None,
                          'screen_bytes': len(buffer), 'hints': [w for w in SCREEN_HINTS if w in flat]}
            retry_at = rate_limited_until(text)
            if retry_at is not None:
                self.trace['retry_at'] = retry_at   # a number: when the service says requests are allowed again
            try:
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=3)
            finally:
                for descriptor in (master, slave):
                    if descriptor is not None:
                        os.close(descriptor)
