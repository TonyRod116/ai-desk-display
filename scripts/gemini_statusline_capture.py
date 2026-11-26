"""Save native Antigravity (agy) Gemini quota metadata locally. No commands, credentials or network."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from token_tv.gemini_usage import GEMINI_DEFAULT_HOME, capture_gemini
from token_tv.local_usage import LocalPolicy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', default='~/.config/token-tv/offline')
    args = parser.parse_args()
    sys.addaudithook(LocalPolicy().audit)
    try:
        raw = sys.stdin.buffer.read(1000001)
        data = json.loads(raw) if len(raw) <= 1000000 else None
        capture_gemini(
            data,
            Path(args.cache_dir).expanduser() / 'gemini-official.json',
            source_home=os.environ.get('AGY_CONFIG_DIR') or GEMINI_DEFAULT_HOME,
        )
    except (OSError, ValueError, TypeError, KeyError):
        pass


if __name__ == '__main__':
    main()
