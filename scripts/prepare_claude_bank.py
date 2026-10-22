"""Prepare a private, locally paired Arc extension; disclose no credentials."""
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
    parser.add_argument('--config', required=True)
    parser.add_argument('--pin', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    prepare(args.config, args.pin, args.destination)
    print('Private local reader prepared. Account data and pairing secret remain local.')
