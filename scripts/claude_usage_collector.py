"""Read Claude's official usage; publish only sanitized, dated local metadata."""
import argparse
import json
import signal
import threading
import time
from pathlib import Path
from urllib.request import Request

from token_tv.claude_usage import ClaudeUsageReader
from token_tv.http import open_direct
from token_tv.local_usage import OFFICIAL_MAX_AGE_SECONDS, atomic_json, origin_id, read_record
from token_tv.sources import SourceError, load_config

# A failed poll must not wipe a good reading that is still inside the display's own freshness limit (180 s): the monitor
# already expires anything older, so holding it for a little less never shows data older than the rule allows. Only these
# reasons hold: a different login, a new client series or model activity must blank at once.
HOLD_SECONDS = OFFICIAL_MAX_AGE_SECONDS - 30
HOLDABLE = {'native_refresh_unconfirmed', 'official_quota_unavailable', 'usage_view_not_confirmed', 'client_not_ready',
            'cli_output_limit', 'auth_unavailable', 'subscription_login_required', 'timeout'}
TRACE_LINES = 200
POLL_SECONDS = 60
RATE_LIMIT_FIRST_WAIT = 300
RATE_LIMIT_MAX_WAIT = 900


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
    was_unavailable = False
    retry_seconds = POLL_SECONDS
    target = path.parent / 'offline' / 'claude-official.json'
    origin = origin_id(root, email)
    while not stopping.is_set():
        if not load_config(path).get('automatic_claude_usage'):
            break
        reason = None
        try:
            record = reader.read(cancel_event=stopping)
            if record.get('stale') or not record.get('windows'):
                reason = 'native_refresh_unconfirmed'
        except Exception as error:
            # Never serialize raw CLI output, exception text or account data.
            # SourceError codes are fixed identifiers; other errors log their class only.
            record = {'fetched_at': 0, 'windows': [], 'origin': origin,
                      'source': 'claude_official_cli', 'stale': True}
            reason = error.code if isinstance(error, SourceError) else type(error).__name__
        if stopping.is_set():
            break
        trace = getattr(reader, 'trace', {}) or {}
        hints = trace.get('hints', []) if isinstance(trace, dict) else []
        if reason == 'official_quota_unavailable' and {'rate limit', 'error'}.issubset(hints):
            retry_seconds = min(RATE_LIMIT_MAX_WAIT, max(RATE_LIMIT_FIRST_WAIT, retry_seconds * 2))
        else:
            retry_seconds = POLL_SECONDS
        held = reason in HOLDABLE and held_reading(target, origin, time.time()) is not None
        if reason:
            print(f'Claude official usage unavailable ({reason}); '
                  + ('keeping the last reading until it is older than the display limit.' if held else 'shown as unknown.')
                  + (f' Retry in {retry_seconds} seconds.' if retry_seconds > POLL_SECONDS else ''), flush=True)
            keep_trace(path.parent / 'state' / 'claude-reader' / 'failures.jsonl', reason, trace, held)
        unavailable = bool(record.get('stale') or not record.get('windows'))
        if was_unavailable and not unavailable:
            print('Claude official usage recovered with a fresh reading.', flush=True)
        was_unavailable = unavailable
        if not held:
            atomic_json(target, record)
            notify_display()
        stopping.wait(retry_seconds)


if __name__ == '__main__':
    main()
