"""Read Codex quota and saved resets; publish sanitized local observations."""
import argparse
import signal
import threading
from pathlib import Path
from urllib.request import Request

from token_tv.codex_resets import CodexResetReader
from token_tv.local_usage import atomic_json, origin_id
from token_tv.http import open_direct
from token_tv.reset_balances import ResetBalances
from token_tv.sources import load_config

_PENDING = object()


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
    cache_path = path.parent / 'offline' / 'codex-official.json'
    try:
        while not stopping.is_set():
            try:
                if not load_config(path).get('automatic_codex_resets'):
                    break
                if reader is None:
                    reader = CodexResetReader(accounts[0]['source_home'], expected_email=email)
                observation = reader.read_snapshot()
                count = observation['available_resets']
                quota = observation['quota']
            except Exception:
                # Error text or RPC payloads must not enter the journal.
                count = None
                quota = {'fetched_at': 0, 'windows': [], 'origin': origin_id(accounts[0]['source_home'], email),
                         'source': 'codex_official_cli', 'stale': True}
                if reader is not None:
                    reader.close()
                    reader = None
                print('Codex quota/reset reading unavailable; retrying automatically.', flush=True)
            if stopping.is_set():
                break
            publish_reading(balances, count, quota, cache_path)
            stopping.wait(60)
    finally:
        if reader is not None:
            reader.close()


if __name__ == '__main__':
    main()
