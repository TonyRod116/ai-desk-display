"""Read-only, account-pinned ingress for a local Claude browser quota reader."""
import hashlib
import hmac
import math
import re
import secrets
import stat
import threading
import time
from pathlib import Path

from token_tv.local_usage import origin_id, read_record
from token_tv.usage import timestamp

HASH = re.compile(r'[0-9a-f]{64}\Z')
EXTENSION_ID = re.compile(r'[a-p]{32}\Z')


def finite_time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        return None
    return value


def available_resets(status, provider_now):
    """Missing/invalid inventory is unknown. Never count renewals or dollars."""
    if (not isinstance(status, dict) or status.get('eligible') is not True
            or not isinstance(status.get('grants'), list) or len(status['grants']) > 200
            or finite_time(provider_now) is None):
        return None
    count, expiry = 0, None
    for grant in status['grants']:
        if not isinstance(grant, dict):
            return None
        left, total = grant.get('resets_left'), grant.get('resets_total')
        start, end = timestamp(grant.get('starts_at')), timestamp(grant.get('ends_at'))
        if (type(left) is not int or type(total) is not int or not 0 <= left <= total <= 50
                or type(grant.get('paused')) is not bool
                or finite_time(start) is None or finite_time(end) is None or end <= start):
            return None
        if left and not grant['paused'] and start <= provider_now < end:
            count += left
            expiry = end if expiry is None else min(expiry, end)
        if count > 50:
            return None
    return count, expiry


class ClaudeBankBridge:
    """Only the privately paired extension may submit sanitized observations."""
    def __init__(self, path, config, balances):
        self.path, self.config, self.balances = Path(path), config, balances
        self.lock = threading.Lock()
        self.pending = None

    def settings(self):
        config = self.config() if callable(self.config) else self.config
        if not config.get('local_only') or not config.get('automatic_claude_resets'):
            return None
        accounts = [a for a in config.get('accounts', []) if a['provider'] == 'claude']
        if len(accounts) != 1 or not isinstance(accounts[0].get('email'), str):
            return None
        if origin_id(accounts[0].get('source_home') or '~/.claude', accounts[0]['email']) != self.balances.origins.get('claude'):
            return None  # Account changes require a fresh monitor, never relabel an old ledger.
        try:
            mode = self.path.lstat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                return None
        except OSError:
            return None
        data = read_record(self.path)
        if not isinstance(data, dict):
            return None
        if (not isinstance(data.get('secret'), str) or not HASH.fullmatch(data['secret'])
                or not isinstance(data.get('extension_id'), str) or not EXTENSION_ID.fullmatch(data['extension_id'])
                or not isinstance(data.get('organization_hash'), str) or not HASH.fullmatch(data['organization_hash'])):
            return None
        owner = hashlib.sha256(accounts[0]['email'].strip().lower().encode()).hexdigest()
        if data.get('account_hash') != owner:
            return None
        return data

    def origin_allowed(self, origin):
        settings = self.settings()
        return bool(settings and origin == 'chrome-extension://' + settings['extension_id'])

    def authorized(self, origin, authorization):
        settings = self.settings()
        return bool(settings and origin == 'chrome-extension://' + settings['extension_id']
                    and isinstance(authorization, str)
                    and hmac.compare_digest(authorization, 'Bearer ' + settings['secret']))

    def accept(self, data):
        settings = self.settings()
        if settings is None or not isinstance(data, dict):
            raise ValueError('Browser reader unavailable')
        with self.lock:
            now = time.time()
            if data == {'operation': 'challenge'}:
                nonce = secrets.token_hex(32)
                self.pending = (nonce, now, settings['account_hash'], settings['organization_hash'])
                return {'nonce': nonce}
            pending = self.pending
            if (data.get('operation') not in ('observation', 'unavailable') or pending is None
                    or data.get('nonce') != pending[0] or not 0 <= now-pending[1] <= 30
                    or pending[2:] != (settings['account_hash'], settings['organization_hash'])):
                raise ValueError('Reading must answer a fresh single-use challenge')
            self.pending = None
            self.balances.set_count('claude', None, source='claude_web',
                                    organization_hash=settings['organization_hash'])
            if data.get('operation') == 'unavailable':
                return {'status': 'unknown'}
            if (data.get('identity_before') != settings['account_hash']
                    or data.get('identity_after') != settings['account_hash']
                    or data.get('organization_hash') != settings['organization_hash']
                    or not isinstance(data.get('account_before'), str)
                    or not HASH.fullmatch(data['account_before'])
                    or data.get('account_after') != data['account_before']):
                raise ValueError('Reading is not bound to the configured account')
            before, observed, after = (finite_time(data.get(k)) for k in ('provider_before', 'provider_at', 'provider_after'))
            if (None in (before, observed, after) or not before-2 <= observed <= after+2
                    or not 0 <= after-before <= 30):
                raise ValueError('Usage must come from the current provider observation')
            result = available_resets(data.get('inventory'), observed)
            if result is None:
                return {'status': 'unknown'}
            count, expiry = result
            # Provider dates bound the grant, even when the PC's clock is offset.
            valid_until = pending[1]+expiry-observed if expiry is not None else None
            self.balances.set_count('claude', count, source='claude_web',
                                    observed_at=pending[1], valid_until=valid_until,
                                    organization_hash=settings['organization_hash'])
            return {'status': 'ok'}
