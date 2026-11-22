"""Read Codex quota and saved resets; publish sanitized local observations."""
import argparse
import signal
import threading
import time
from pathlib import Path
from urllib.request import Request

from token_tv.alerts import Alerts
from token_tv.codex_resets import CodexResetReader
from token_tv.local_usage import OFFICIAL_MAX_AGE_SECONDS, atomic_json, origin_id, read_record
from token_tv.http import open_direct
from token_tv.reader_status import last_state, publish_status, reason_for
from token_tv.reset_balances import ResetBalances
from token_tv.sources import SourceError, load_config

_PENDING = object()
POLL_SECONDS = 60
RETRY_FIRST_SECONDS = 10
# A single transient RPC/CLI hiccup must not wipe a good reading that is still inside the display's own 480 s limit:
# the monitor ages it at 180 s and expires it honestly at 480 s. Account/login/schema failures still blank at once.
HOLD_SECONDS = OFFICIAL_MAX_AGE_SECONDS - 30
HOLDABLE = {'timeout', 'rpc_error', 'cli_unavailable', 'TimeoutError', 'OSError', 'BrokenPipeError', 'EOFError', 'ConnectionError'}


def held_reading(path, origin, now):
    """The reading already on disk if it belongs to this account, has windows, is fresh and not stale."""
    record = read_record(path)
    if (record and record.get('origin') == origin and record.get('windows') and not record.get('stale')
            and 0 <= now - record.get('fetched_at', 0) <= HOLD_SECONDS):
        return record
    return None


def notify_display():
    try:
        with open_direct(Request('http://127.0.0.1:8787/display/usage-refresh', data=b'{}',
                                 headers={'Content-Type': 'application/json'}), no_proxy=True) as response:
            response.read()
            return response.status == 200
    except (OSError, ValueError):
        return False


def publish_count(balances, count, last_notified, notify=notify_display):
    balances.set_count('codex', count, source='codex_cli')
    if count == last_notified:
        return last_notified
    # A failed notification leaves a pending refresh, even when the next
    # reading recovers the previously displayed balance.
    return count if notify() else _PENDING


def publish_reading(balances, count, quota, path, notify=None):
    atomic_json(path, quota)
    # Quota changes independently of saved hearts. Every observation (including
    # failure/recovery) refreshes the clock, even when the count stays zero.
    return publish_count(balances, count, _PENDING, notify=notify or notify_display)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='~/.config/token-tv/config.json')
    args = parser.parse_args()
    path = Path(args.config).expanduser()
    config = load_config(path)
    if not config.get('automatic_codex_resets'):
        print('Automatic saved-reset queries disabled.', flush=True)
        return
    accounts = [a for a in config['accounts'] if a['provider'] == 'codex']
    if len(accounts) != 1:
        raise SystemExit('Exactly one Codex account is required')
    email = accounts[0].get('email')
    balances = ResetBalances(path.parent / 'reset-balances.json', config['accounts'])
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    reader = None
    offline = path.parent / 'offline'
    cache_path = offline / 'codex-official.json'
    origin = origin_id(accounts[0]['source_home'], email)
    alerts = Alerts(path.parent / 'state' / 'alerts-codex.json', 'codex')
    state, since = last_state(offline, 'codex')   # a quick restart keeps when the current state began
    was_unavailable = False
    retry_wait = RETRY_FIRST_SECONDS
    try:
        while not stopping.is_set():
            code = None
            try:
                if not load_config(path).get('automatic_codex_resets'):
                    break
                if reader is None:
                    reader = CodexResetReader(accounts[0]['source_home'], expected_email=email)
                observation = reader.read_snapshot()
                count = observation['available_resets']
                quota = observation['quota']
                if not any(w.get('label') == 'WEEK' for w in quota.get('windows', [])):
                    code = 'no_weekly_reading'   # the client answered, but with no weekly quota
            except Exception as error:
                # Error text or RPC payloads must not enter the journal; only a fixed code reaches the status file.
                code = error.code if isinstance(error, SourceError) else type(error).__name__
                count = None
                quota = {'fetched_at': 0, 'windows': [], 'origin': origin,
                         'source': 'codex_official_cli', 'stale': True}
                if reader is not None:
                    reader.close()
                    reader = None
            if stopping.is_set():
                break
            now = time.time()
            held = code in HOLDABLE and held_reading(cache_path, origin, now) is not None
            if code in HOLDABLE:
                wait = retry_wait
                retry_wait = min(POLL_SECONDS, retry_wait * 2)
            else:
                wait = POLL_SECONDS
                retry_wait = RETRY_FIRST_SECONDS
            if code is not None:
                print(f'Codex quota/reset reading unavailable ({code}); '
                      + ('keeping the last reading until it is older than the display limit.' if held else 'shown as unknown.')
                      + f' Retry in {wait} seconds.', flush=True)
            elif was_unavailable:
                print('Codex quota/reset reading recovered with a fresh reading.', flush=True)
            was_unavailable = code is not None
            if ('failing' if code else 'ok') != state:
                state, since = 'failing' if code else 'ok', int(now)
            why = reason_for(code) if code else None
            publish_status(offline, 'codex', state, why, since, None, now + wait, now)   # first: publish_reading notifies the monitor
            if not held:
                publish_reading(balances, count, quota, cache_path)
            alerts.observe(code is None, why, now)
            stopping.wait(wait)
    finally:
        if reader is not None:
            reader.close()


if __name__ == '__main__':
    main()
