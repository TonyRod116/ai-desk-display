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
from pathlib import Path

from token_tv.local_usage import origin_id
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
                'not logged in', '/login', 'expired', 'network', 'current session', 'current week')


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
            self.trace = {'seconds': round(time.monotonic() - began, 1), 'sent': sent, 'model_free': model_free,
                          'cache_age_at_end': round(time.time() - kept['fetched_at'], 1) if kept else None,
                          'cache_age_at_start': round(started - kept['fetched_at'], 1) if kept else None,
                          'client_exited': process is not None and process.poll() is not None,
                          'screen_bytes': len(buffer), 'hints': [w for w in SCREEN_HINTS if w in text.lower()]}
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
