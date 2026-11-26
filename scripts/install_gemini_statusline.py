"""Install or update the Antigravity (agy) statusLine hook in ~/.gemini/antigravity-cli/settings.json."""
import argparse
import json
import os
import tempfile
from pathlib import Path


def build_statusline_config(repo_root):
    root = Path(repo_root).resolve()
    python = root / '.venv' / 'bin' / 'python'
    script = root / 'scripts' / 'gemini_statusline_capture.py'
    return {
        'type': 'command',
        'command': f'{python} -B {script}',
        'padding': 0,
        'enabled': True,
        'stack_with_default': True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', default='~/.gemini/antigravity-cli/settings.json')
    args = parser.parse_args()
    settings_path = Path(args.settings).expanduser()
    settings_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {}
    if settings_path.exists():
        loaded = json.loads(settings_path.read_text(encoding='utf-8'))
        if not isinstance(loaded, dict):
            raise SystemExit(f'{settings_path} must contain a JSON object')
        data = loaded
    data['statusLine'] = build_statusline_config(Path(__file__).resolve().parents[1])
    payload = json.dumps(data, indent=2) + '\n'
    fd, tmp_name = tempfile.mkstemp(dir=str(settings_path.parent), prefix='.settings-', suffix='.tmp')
    try:
        os.chmod(tmp_name, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
        os.replace(tmp_name, settings_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    print(f'Updated {settings_path} with Antigravity statusLine Gemini capture.')


if __name__ == '__main__':
    main()
