"""Read Claude's official usage; publish only sanitized, dated local metadata."""
import argparse
import signal
import threading
from pathlib import Path
from urllib.request import Request

from token_tv.claude_usage import ClaudeUsageReader
from token_tv.http import open_direct
from token_tv.local_usage import atomic_json, origin_id
from token_tv.sources import SourceError, load_config


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
    while not stopping.is_set():
        if not load_config(path).get('automatic_claude_usage'):
            break
        try:
            record = reader.read(cancel_event=stopping)
            if record.get('stale') or not record.get('windows'):
                print('Claude official usage unavailable (native_refresh_unconfirmed); shown as unknown.', flush=True)
        except Exception as error:
            # Never serialize raw CLI output, exception text or account data.
            # SourceError codes are fixed identifiers; other errors log their class only.
            record = {'fetched_at': 0, 'windows': [], 'origin': origin_id(root, email),
                      'source': 'claude_official_cli', 'stale': True}
            reason = error.code if isinstance(error, SourceError) else type(error).__name__
            print(f'Claude official usage unavailable ({reason}); shown as unknown.', flush=True)
        if stopping.is_set():
            break
        unavailable = bool(record.get('stale') or not record.get('windows'))
        if was_unavailable and not unavailable:
            print('Claude official usage recovered with a fresh reading.', flush=True)
        was_unavailable = unavailable
        atomic_json(path.parent / 'offline' / 'claude-official.json', record)
        notify_display()
        stopping.wait(60)


if __name__ == '__main__':
    main()
