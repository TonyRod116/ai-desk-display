"""Prepare a private, locally paired browser extension (Chrome); disclose no credentials."""
import argparse
import base64
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from token_tv.local_usage import atomic_json, read_record
from token_tv.sources import load_config


CODE = ('manifest.json', 'background.js', 'reader.mjs')


def sync_code(destination):
    """Update the extension's code in an installed copy, touching nothing else (Tony, 2026-11-03: new code must not need a new
    pairing). `pairing.js` is only checked to exist, never read or rewritten, and the bridge file stays as it is, so the secret is
    the same one. Returns the names of the files that changed."""
    destination = Path(destination)
    source = Path(__file__).resolve().parents[1] / 'integrations/claude-bank'
    if destination.resolve() == source.resolve() or not (destination/'pairing.js').is_file():
        raise ValueError('Only a prepared extension folder can be updated; use --config and --pin to prepare a new one')
    changed = []
    for name in CODE:
        wanted = (source/name).read_bytes()
        if (destination/name).is_file() and (destination/name).read_bytes() == wanted:
            continue
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as handle:
            handle.write(wanted)
            temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            temporary.replace(destination/name)
        finally:
            temporary.unlink(missing_ok=True)
        changed.append(name)
    return changed


def prepare(config_path, pin_path, destination):
    config_path, destination = Path(config_path), Path(destination)
    config = load_config(config_path)
    if not config.get('local_only'):
        raise ValueError('This reader is limited to local installations')
    accounts = [a for a in config['accounts'] if a['provider'] == 'claude']
    if len(accounts) != 1 or not accounts[0].get('email'):
        raise ValueError('Pin one authorized Claude account first')
    account_hash = hashlib.sha256(accounts[0]['email'].strip().lower().encode()).hexdigest()
    pin = read_record(pin_path)
    from token_tv.claude_bank import HASH
    import re
    if (not pin or pin.get('account_hash') != account_hash
            or not isinstance(pin.get('organization_id'), str)
            or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', pin['organization_id'], re.I)):
        raise ValueError('Verify the authorized browser account and organization first')
    source = Path(__file__).resolve().parents[1] / 'integrations/claude-bank'
    manifest = json.loads((source/'manifest.json').read_text())
    key_hash = hashlib.sha256(base64.b64decode(manifest['key'])).hexdigest()[:32]
    extension_id = ''.join(chr(ord('a') + int(character, 16)) for character in key_hash)
    bridge_path = config_path.parent/'claude-bank-bridge.json'
    old = read_record(bridge_path) or {}
    organization_hash = hashlib.sha256(pin['organization_id'].encode()).hexdigest()
    import secrets
    same_pairing = (old.get('account_hash') == account_hash
                    and old.get('organization_hash') == organization_hash
                    and old.get('extension_id') == extension_id)
    secret = old.get('secret') if (same_pairing and isinstance(old.get('secret'), str)
                                  and HASH.fullmatch(old['secret'])) else secrets.token_hex(32)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    for name in ('manifest.json', 'background.js', 'reader.mjs'):
        shutil.copyfile(source/name, destination/name)
        os.chmod(destination/name, 0o600)
    pairing = {'accountHash':account_hash, 'organization':pin['organization_id'], 'secret':secret}
    private = destination/'pairing.js'
    with tempfile.NamedTemporaryFile(mode='w', dir=destination, delete=False) as handle:
        handle.write('export const PAIRING = '+json.dumps(pairing,separators=(',', ':'))+';\n')
        temporary = Path(handle.name)
    temporary.replace(private)
    atomic_json(bridge_path, {'secret':secret, 'extension_id':extension_id,
        'account_hash':account_hash, 'organization_hash':organization_hash})
    # Preparing files does not enable provider traffic; installation is separate.
    return extension_id


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--pin')
    parser.add_argument('--destination', required=True)
    parser.add_argument('--sync-code', action='store_true',
                        help='only copy the extension code over an installed copy; no config, pin or pairing is read or changed')
    args = parser.parse_args()
    if args.sync_code:
        if args.config or args.pin:
            parser.error('--sync-code needs only --destination')
        try:
            changed = sync_code(args.destination)
        except (OSError, ValueError) as error:
            raise SystemExit(f'Not updated: {error}')
        print((f'Extension code updated ({", ".join(changed)}).' if changed else 'Extension code was already current.')
              + ' The pairing was not touched. Reload the extension in the browser to run it.')
    else:
        if not (args.config and args.pin):
            parser.error('--config and --pin are required (or --sync-code to update only the code)')
        prepare(args.config, args.pin, args.destination)
        print('Private local reader prepared. Account data and pairing secret remain local.')
