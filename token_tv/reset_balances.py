"""Locally confirmed saved-reset balances, separate from quota and reset timers."""
import fcntl
import os
import re
import time
from pathlib import Path

from token_tv.local_usage import atomic_json, origin_id, read_record
from token_tv.usage import timestamp

LAST_KNOWN_SECONDS = 72 * 3600  # how long a stale count is still worth showing, marked by the discreet dot
# An automatic count is current for 180 s (Tony's tiers of 2026-11-03). A late observation is accepted up to MAX_AGE_SECONDS, the
# limit a quota reading can still be shown under. token_tv/web/app.js keeps the same numbers.
FRESH_SECONDS = 180
MAX_AGE_SECONDS = 480


class ResetBalances:
    def __init__(self, path, accounts):
        self.path = Path(path)
        self.origins = {}
        for provider in ('claude', 'codex'):
            selected = [a for a in accounts if a['provider'] == provider]
            self.origins[provider] = (origin_id(selected[0].get('source_home') or '~/.'+provider,
                                               selected[0].get('email')) if len(selected) == 1 else None)

    def snapshot(self, automatic_providers=(), claude_organization=None):
        data = read_record(self.path) or {}
        entries = data.get('balances') if isinstance(data.get('balances'), dict) else {}
        result = {}
        for provider, origin in self.origins.items():
            empty = {'available': None, 'confirmed_at': None, 'source': 'unknown'}
            entry = entries.get(provider)
            if not origin or not isinstance(entry, dict) or entry.get('origin') != origin:
                result[provider] = empty
                continue
            count = entry.get('available')
            stamp = timestamp(entry.get('confirmed_at'))
            if type(count) is not int or not 0 <= count <= 999 or not stamp or stamp > time.time()+60:
                result[provider] = empty
                continue
            source = entry.get('source', 'user_confirmed')
            expected = {'codex': 'codex_cli', 'claude': 'claude_web'}[provider]
            if source not in ('user_confirmed', expected):
                result[provider] = empty
                continue
            if provider in automatic_providers and source != {'codex': 'codex_cli', 'claude': 'claude_web'}[provider]:
                result[provider] = {'available': None, 'confirmed_at': None, 'source': 'awaiting_automatic'}
                continue
            until = timestamp(entry.get('valid_until'))
            if source == 'claude_web' and (not claude_organization
                    or entry.get('organization_hash') != claude_organization
                    or count > 0 and until is None
                    or 'valid_until' in entry and until is None):
                result[provider] = empty
                continue
            if source == 'claude_web' and count == 0 and entry.get('not_eligible') is True:
                # Claude said this account has no saved resets (Tony, 2026-11-03). An answer, not a reading that ages:
                # three faint icons and no dot, until a real inventory says otherwise.
                result[provider] = {'available': 0, 'confirmed_at': stamp, 'source': 'claude_not_eligible'}
                continue
            age = time.time() - stamp
            if source in ('codex_cli', 'claude_web') and (age > FRESH_SECONDS or until is not None and until <= time.time()):
                result[provider] = {'available': None, 'confirmed_at': stamp, 'source': 'stale'}
                # Nothing fresh, but the last confirmed count is a far better answer than "unknown" while it can
                # still be true: no counted grant has expired and it is recent. Screens mark it with the dot; every
                # consumer that reads `available` still sees "unknown".
                if age <= LAST_KNOWN_SECONDS and (until is None or until > time.time()):
                    result[provider]['last_known'] = count
                    if until is not None:
                        result[provider]['valid_until'] = until
                continue
            result[provider] = {'available': count, 'confirmed_at': stamp, 'source': source}
            if source == 'claude_web':
                result[provider]['valid_until'] = until
        return result

    def not_eligible(self, provider, organization_hash):
        """Whether the stored answer is Claude's "this account has no saved resets", for this account and organization."""
        data = read_record(self.path) or {}
        entries = data.get('balances') if isinstance(data.get('balances'), dict) else {}
        entry = entries.get(provider)
        return (isinstance(entry, dict) and entry.get('not_eligible') is True and entry.get('origin') == self.origins.get(provider)
                and entry.get('organization_hash') == organization_hash)

    def set_count(self, provider, count, source='user_confirmed', observed_at=None, valid_until=None,
                  organization_hash=None, not_eligible=False):
        if provider not in self.origins or not self.origins[provider]:
            raise ValueError('Choose a configured provider with one account')
        if count is not None and (type(count) is not int or not 0 <= count <= 999):
            raise ValueError('Saved resets must be a whole number from 0 to 999, or unknown')
        if source not in ('user_confirmed', 'codex_cli', 'claude_web') or source in ('codex_cli', 'claude_web') and source != {'codex': 'codex_cli', 'claude': 'claude_web'}[provider]:
            raise ValueError('Unsupported confirmation source')
        # An observation is recorded while it can still be shown (flagged old past FRESH_SECONDS); older is dropped.
        if observed_at is not None and (timestamp(observed_at) is None or not 0 <= time.time()-observed_at <= MAX_AGE_SECONDS):
            raise ValueError('Invalid observation date')
        if valid_until is not None and timestamp(valid_until) is None:
            raise ValueError('Invalid inventory expiry')
        if source == 'claude_web' and (not isinstance(organization_hash, str)
                or not re.fullmatch(r'[0-9a-f]{64}', organization_hash)
                or count is not None and count > 0 and valid_until is None):
            raise ValueError('Browser inventory must be bound to its organization and expiry')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = read_record(self.path) or {}
            balances = data.get('balances') if isinstance(data.get('balances'), dict) else {}
            balances[provider] = {'available': count, 'confirmed_at': (observed_at if observed_at is not None else int(time.time())) if count is not None else None,
                                  'origin': self.origins[provider], 'source': source}
            if source == 'claude_web' and valid_until is not None:
                balances[provider]['valid_until'] = valid_until
            if source == 'claude_web' and not_eligible and count == 0:
                balances[provider]['not_eligible'] = True
            if source == 'claude_web':
                balances[provider]['organization_hash'] = organization_hash
            atomic_json(self.path, {'schema': 1, 'balances': balances})


def attach_balances(snapshot, balances):
    for row in snapshot['accounts'].values():
        # The browser reader's own state (`reader`) belongs to the display's saved_resets, not to a row's balance.
        row['banked_resets'] = {key: value for key, value in balances.get(
            row['provider'], {'available': None, 'confirmed_at': None, 'source': 'unknown'}).items() if key != 'reader'}
    return snapshot
