"""Read Claude's official usage; publish only sanitized, dated local metadata."""
import argparse
import json
import math
import signal
import threading
import time
from pathlib import Path
from urllib.request import Request

from token_tv.alerts import Alerts
from token_tv.claude_usage import RETRY_MAX_AHEAD, ClaudeUsageReader, statusline_record
from token_tv.http import open_direct
from token_tv.local_usage import OFFICIAL_FRESH_SECONDS, OFFICIAL_MAX_AGE_SECONDS, atomic_json, origin_id, read_record
from token_tv.reader_status import RATE_LIMIT, last_state, publish_status, reason_for
from token_tv.sources import SourceError, load_config

# A failed poll must not wipe a good reading that is still inside the display's own limit (480 s since Tony's 2026-11-03 ruling,
# 180 s before): the monitor already expires anything older, so holding it for a little less never shows data older than the rule
# allows. Only these reasons hold: a different login, a new client series or model activity must blank at once.
HOLD_SECONDS = OFFICIAL_MAX_AGE_SECONDS - 30
HOLDABLE = {'native_refresh_unconfirmed', 'official_quota_unavailable', 'usage_view_not_confirmed', 'client_not_ready', 'cli_output_limit',
            'auth_unavailable', 'subscription_login_required', 'timeout'}
TRACE_LINES = 200
# These blank at once and the status line never covers for them: a new client series gets no help until its screen is reviewed.
BLANK_AT_ONCE = {'identity_mismatch', 'unsupported_client_version', 'unexpected_model_activity'}
LOGIN_LOST = {'identity_mismatch', 'subscription_login_required', 'auth_unavailable'}   # the login proof no longer stands
# Tony, 2026-11-03: every poll started a whole Claude Code client (345 MB, peak 630 MB, one /usage line in his history each time).
# Every two minutes is enough: a normal reading is fresh for 180 s, so it never shows the dot (see next_wait for the exceptions).
POLL_SECONDS = 120
RATE_LIMIT_FIRST_WAIT = 300
RATE_LIMIT_MAX_WAIT = 900
IDENTITY_SECONDS = 600   # how long a passed `authenticate()` vouches for the status-line capture
READ_SECONDS = 15        # a normal authenticate + client start + /usage


def held_reading(path, origin, now):
    """The reading already on disk if it is the same account's, fresh and complete: it stays instead of a failure marker."""
    record = read_record(path)
    if (record and record.get('origin') == origin and record.get('windows') and not record.get('stale')
            and 0 <= now - record.get('fetched_at', 0) <= HOLD_SECONDS):
        return record
    return None


def keep_trace(path, reason, trace, held):
    """One line per failed poll, only fixed words, numbers and yes/no flags: why the refresh was not confirmed, found over time."""
    line = json.dumps({'at': int(time.time()), 'reason': reason, 'held': held, **(trace if isinstance(trace, dict) else {})}, sort_keys=True)
    try:
        previous = path.read_text().splitlines()[-(TRACE_LINES - 1):] if path.exists() else []
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text('\n'.join([*previous, line]) + '\n')
        path.chmod(0o600)
    except OSError:
        pass


def notify_display():
    try:
        with open_direct(Request('http://127.0.0.1:8787/display/usage-refresh', data=b'{}',
                                 headers={'Content-Type': 'application/json'}), no_proxy=True) as response:
            response.read()
            return response.status == 200
    except (OSError, ValueError):
        return False


def unavailable(origin):
    return {'fetched_at': 0, 'windows': [], 'origin': origin, 'source': 'claude_official_cli', 'stale': True}


def statusline_reading(reader, capture, root, email, identity):
    """A recent, complete status-line capture of this source home stands in for a `/usage` run: no client is started. The login
    is proved by `authenticate()`, repeated at most every IDENTITY_SECONDS; when that check is missing or fails the reader
    polls normally. The record keeps the capture's real fetch time and its own honest source."""
    record = statusline_record(read_record(capture), root, email, time.time())
    if record is None:
        return None
    if identity['at'] is None or time.monotonic() - identity['at'] >= IDENTITY_SECONDS:
        began = time.monotonic(), time.time()
        try:
            reader.authenticate()
        except Exception:
            identity['at'] = None
            return None
        identity.update(at=began[0], epoch=began[1])
    return {**record, 'identity_verified': email is not None, 'identity_checked_at': int(identity['epoch'])}


def covered_by_backup(offline, origin, now):
    """The browser extension's reading is on the display: the reader is failing, but Tony is not without data, so no alert."""
    record = read_record(offline / 'claude-browser.json')
    return bool(record and record.get('origin') == origin and record.get('windows')
                and 0 <= now - record.get('fetched_at', 0) <= OFFICIAL_MAX_AGE_SECONDS)


def next_wait(record, now):
    """POLL_SECONDS, shortened when the reading just published is already old (a client cache another process fetched, a
    status-line capture): the next one must land before this one passes the fresh tier, so a normal reading never shows the dot."""
    age = max(0, now - record.get('fetched_at', now))
    return max(30, min(POLL_SECONDS, int(OFFICIAL_FRESH_SECONDS - READ_SECONDS - age)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='~/.config/token-tv/config.json')
    args = parser.parse_args()
    path = Path(args.config).expanduser()
    config = load_config(path)
    if not config.get('automatic_claude_usage'):
        return
    accounts = [a for a in config['accounts'] if a['provider'] == 'claude']
    if len(accounts) != 1:
        raise SystemExit('Exactly one Claude source is required')
    root = accounts[0]['source_home']
    email = accounts[0].get('email')
    reader = ClaudeUsageReader(root, path.parent / 'state' / 'claude-reader', expected_email=email)
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    offline = path.parent / 'offline'
    target, capture = offline / 'claude-official.json', offline / 'claude.json'
    origin = origin_id(root, email)
    alerts = Alerts(path.parent / 'state' / 'alerts-claude.json', 'claude')
    identity = {'at': None, 'epoch': None}   # when `authenticate()` last passed: monotonic and wall clock
    was_unavailable = False
    backoff = POLL_SECONDS    # grows while the service limits requests
    quiet_until = 0.0         # monotonic: no client is started before this, but the status line keeps being read
    last = {'reason': None, 'hints': []}   # the last attempt's, which a skipped poll repeats
    state, since = last_state(offline, 'claude')   # a quick restart keeps when the current state began
    while not stopping.is_set():
        if not load_config(path).get('automatic_claude_usage'):
            break
        reason, hints, trace, attempted, waited = None, [], {}, False, 0
        record = None if last['reason'] in BLANK_AT_ONCE else statusline_reading(reader, capture, root, email, identity)
        if stopping.is_set():
            break
        if record is None and time.monotonic() < quiet_until:
            # Rate limited: the client stays closed until the service allows requests again; only the status line can help.
            record, reason, hints = unavailable(origin), last['reason'], last['hints']
        elif record is None:
            attempted = True
            began = time.monotonic(), time.time()
            try:
                record = reader.read(cancel_event=stopping)
                if record.get('stale') or not record.get('windows'):
                    reason = 'native_refresh_unconfirmed'
                else:
                    identity.update(at=began[0], epoch=began[1])   # read() proved the login before it opened the client
            except Exception as error:
                # Never serialize raw CLI output, exception text or account data.
                # SourceError codes are fixed identifiers; other errors log their class only.
                record = unavailable(origin)
                reason = error.code if isinstance(error, SourceError) else type(error).__name__
                if reason in LOGIN_LOST:
                    identity['at'] = None   # the status line is trusted again only after a new proof of the login
            trace = getattr(reader, 'trace', {}) or {}
            hints = trace.get('hints', []) if isinstance(trace, dict) else []
        if stopping.is_set():
            break
        now = time.time()
        if attempted:
            # Tony, 2026-11-03: any rate-limit word backs off, whatever the failure code (the recent failures were not the
            # official_quota_unavailable the old rule waited for), and a moment the service names is honoured. A good client
            # reading returns to the normal cadence; a status-line reading says nothing about the service, so it does not.
            given = trace.get('retry_at') if isinstance(trace, dict) else None
            given = given if type(given) in (int, float) and now < given <= now + RETRY_MAX_AHEAD else None
            if reason is not None and (set(hints) & set(RATE_LIMIT) or given is not None):
                backoff = min(RATE_LIMIT_MAX_WAIT, max(RATE_LIMIT_FIRST_WAIT, backoff * 2))
                waited = max(POLL_SECONDS, int(given - now) + 5) if given is not None else backoff
                quiet_until = time.monotonic() + waited
            else:
                backoff, quiet_until = POLL_SECONDS, 0.0
            last = {'reason': reason, 'hints': hints}
        held = reason in HOLDABLE and held_reading(target, origin, time.time()) is not None
        if attempted and reason:
            print(f'Claude official usage unavailable ({reason}); '
                  + ('keeping the last reading until it is older than the display limit.' if held else 'shown as unknown.')
                  + (f' Retry in {waited} seconds.' if waited else ''), flush=True)
            keep_trace(path.parent / 'state' / 'claude-reader' / 'failures.jsonl', reason, trace, held)
        unavailable_now = bool(record.get('stale') or not record.get('windows'))
        if was_unavailable and not unavailable_now:
            print('Claude official usage recovered with a fresh reading.', flush=True)
        was_unavailable = unavailable_now
        wait = next_wait(record, now) if reason is None else POLL_SECONDS
        if ('failing' if reason else 'ok') != state:
            state, since = 'failing' if reason else 'ok', int(now)
        why = reason_for(reason, hints) if reason else None
        pause = quiet_until - time.monotonic()
        if 0 < pause < wait:
            wait = math.ceil(pause)   # wake exactly when the client may be started again
        # The status first: the monitor refreshes the moment it is notified and should find the reason with the reading.
        publish_status(offline, 'claude', state, why, since, int(now + pause) if reason and pause > 0 else None, now + wait, now)
        if not held:
            atomic_json(target, record)
            notify_display()
        alerts.observe(reason is None or covered_by_backup(offline, origin, now), why, now)
        stopping.wait(wait)


if __name__ == '__main__':
    main()
