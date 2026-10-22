"""Save native quota metadata locally. No commands, credentials or provider requests."""
import argparse
import json
import os
import sys
from pathlib import Path

from token_tv.local_usage import LocalPolicy, capture_claude


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', default='~/.config/token-tv/offline')
    args = parser.parse_args()
    sys.addaudithook(LocalPolicy().audit)
    try:
        raw = sys.stdin.buffer.read(1000001)
        data = json.loads(raw) if len(raw) <= 1000000 else None
        capture_claude(data, Path(args.cache_dir).expanduser() / 'claude.json',
                       source_home=os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude')
    except (OSError, ValueError, TypeError, KeyError):
        pass


if __name__ == '__main__':
    main()
