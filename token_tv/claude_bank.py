"""Read-only, account-pinned ingress for a local Claude browser quota reader."""
import hashlib
import hmac
import re
import secrets
import stat
import threading
import time
from pathlib import Path

from token_tv.claude_backup import FILE as QUOTA_FILE, quota_record, store as store_quota
from token_tv.local_usage import origin_id, read_record
from token_tv.usage import timestamp

HASH = re.compile(r'[0-9a-f]{64}\Z')
EXTENSION_ID = re.compile(r'[a-p]{32}\Z')
EXTENSION_ORIGIN = re.compile(r'chrome-extension://[a-p]{32}\Z')
VERSION = re.compile(r'\d{1,4}(\.\d{1,4}){1,3}\Z')

# Why the browser reader has no saved-reset reading (Tony, 2026-11-03: in Arc it was silent for 19 days and nothing said why). Fixed
# ids only, never a response body, account data or screen text. The first block is what the extension may send (its REASONS in
# integrations/claude-bank/reader.mjs; a test keeps the two equal, and anything else becomes `unknown`), the second what this
# side concludes alone. The sentences are for the dashboard; the journal gets the ids.
EXTENSION_REASONS = {
    'rate_limited': 'Claude is limiting requests; the extension waits before asking again.',
    'access_denied': 'Claude refused the request: the browser may be signed out or blocked.',
    'provider_unavailable': 'Claude answered with an error.',
    'cached_response': 'The answer looked old or cached, so it was not used.',
    'missing_provider_date': 'The answer carried no usable date, so it was not used.',
    'response_too_large': 'The answer was larger than expected and was ignored.',
    'malformed_response': 'The answer was not the expected data.',
    'network_error': 'The browser could not reach Claude.',
    'timeout': 'Claude took too long to answer.',
    'identity_unavailable': 'The account could not be identified.',
    'wrong_account': 'The browser is signed in to a different account than the paired one.',
    'account_changed': 'The signed-in account changed during the reading.',
    'invalid_pairing': 'The extension holds an invalid pairing.',
    'not_offered': 'Claude no longer offers saved resets in its answer.',
    'not_eligible': 'Claude says this account has no saved resets to offer.',
    'malformed_inventory': 'The list of saved resets had an unexpected shape.',
    'unknown': 'The extension reported a problem it could not name.',
}
LOCAL_REASONS = {
    'no_contact': 'The browser extension has not contacted the display.',
    'pairing_rejected': 'The extension contacted the display and was refused: its pairing is out of date.',
    'not_paired': 'The display has no valid pairing for the extension.',
    'unanswered': 'The extension asked to start a reading but never delivered one.',
    'pairing_mismatch': 'The extension reading does not match the paired account or organization.',
}
REASONS = {**EXTENSION_REASONS, **LOCAL_REASONS}
QUOTA_REASONS = {'quota_missing': 'The answer carried no weekly quota.', 'quota_invalid': 'The quota in the answer was not usable.'}
SILENT_SECONDS = 180      # the extension asks about once a minute
BACKOFF_SILENT_SECONDS = 1200  # ...but waits up to 15 minutes after a rate limit
CHALLENGE_SECONDS = 30


def reason_id(value, allowed):
    return value if isinstance(value, str) and value in allowed else None


def finite_time(value):
    # Range first: it refuses nan and inf, and a whole number too big for a float would make math.isfinite raise.
    if type(value) not in (int, float) or not 0 < value < 1e15:
        return None
    return value


def grant_time(value):
    return None if type(value) in (int, float) and not 0 < value < 1e15 else timestamp(value)


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
        start, end = grant_time(grant.get('starts_at')), grant_time(grant.get('ends_at'))
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


class Rejected(ValueError):
    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


def bind(settings, data):
    """The provider's time for a reading that belongs to the configured account and organization, or Rejected."""
    if (data.get('identity_before') != settings['account_hash']
            or data.get('identity_after') != settings['account_hash']
            or data.get('organization_hash') != settings['organization_hash']
            or not isinstance(data.get('account_before'), str)
            or not HASH.fullmatch(data['account_before'])
            or data.get('account_after') != data['account_before']):
        raise Rejected('Reading is not bound to the configured account', 'pairing_mismatch')
    before, observed, after = (finite_time(data.get(k)) for k in ('provider_before', 'provider_at', 'provider_after'))
    if (None in (before, observed, after) or not before-2 <= observed <= after+2
            or not 0 <= after-before <= 30):
        raise Rejected('Usage must come from the current provider observation', 'cached_response')
    return observed


class ReaderLog:
    """What the browser reader has done since the monitor started, in memory (Tony, 2026-11-03). One fixed id for the situation,
    written to the journal whenever it changes; no secret, origin, account or response text is ever kept."""
    def __init__(self, now, log=None):
        self.lock = threading.Lock()
        self.log = log
        self.shown, self.since = 'start', int(now)
        self.contact = self.challenged_at = self.answered_at = self.delivery = None   # epoch seconds
        self.rejected, self.rejected_at = 0, None
        self.outcome = self.version = None
        self.last_quota = self.quota_reason = None

    def challenged(self, now):
        with self.lock:
            self.contact = self.challenged_at = now

    def contacted(self, now):
        with self.lock:
            self.contact = now

    def rejected_contact(self, now):
        with self.lock:
            self.rejected += 1
            self.rejected_at = now

    def answered(self, now, outcome, version=None, delivered=False, quota=None):
        """`outcome` is 'ok' or a reason id; `quota` is (stored, reason) when the answer carried quota information."""
        with self.lock:
            self.contact = self.answered_at = now
            self.outcome = outcome
            self.version = version or self.version
            if delivered:
                self.delivery = now
            if quota and quota[0]:
                self.last_quota, self.quota_reason = now, None
            elif quota:
                self.quota_reason = quota[1]

    def _key(self, now, paired):
        if not paired:
            return 'not_paired'
        if self.rejected_at is not None and now - self.rejected_at <= SILENT_SECONDS and (
                self.contact is None or self.rejected_at > self.contact):
            return 'pairing_rejected'  # knocking with a stale pairing looks exactly like silence otherwise
        limit = BACKOFF_SILENT_SECONDS if self.outcome == 'rate_limited' else SILENT_SECONDS
        if self.contact is None or now - self.contact > limit:
            return 'no_contact'
        if (self.challenged_at is not None and self.challenged_at > (self.answered_at or 0)
                and now - self.challenged_at > CHALLENGE_SECONDS):
            return 'unanswered'
        return self.outcome or 'no_contact'

    def status(self, now, paired):
        with self.lock:
            key = self._key(now, paired)
            if key != self.shown:
                if self.log:
                    self.log(f'Claude saved-reset reader: {self.shown} -> {key}.')
                self.shown, self.since = key, int(now)
            seconds = lambda value: int(value) if value else None
            # Tony, 2026-11-03: "not eligible" is an answer, not a failure: the account has no saved resets.
            settled = key in ('ok', 'not_eligible')
            return {'state': 'ok' if settled else 'failing', 'reason': None if key == 'ok' else key, 'since': self.since,
                    'last_contact': seconds(self.contact), 'last_delivery': seconds(self.delivery),
                    'extension_version': self.version, 'rejected': self.rejected,
                    'last_quota': seconds(self.last_quota), 'quota_reason': self.quota_reason}


class ClaudeBankBridge:
    """Only the privately paired extension may submit sanitized observations."""
    def __init__(self, path, config, balances, log=None):
        self.path, self.config, self.balances = Path(path), config, balances
        self.lock = threading.Lock()
        self.pending = None
        self.reader = ReaderLog(time.time(), log)

    def settings(self):
        config = self.config() if callable(self.config) else self.config
        if not config.get('local_only') or not config.get('automatic_claude_resets'):
            return None
        accounts = [a for a in config.get('accounts', []) if a['provider'] == 'claude']
        if len(accounts) != 1 or not isinstance(accounts[0].get('email'), str):
            return None
        origin = origin_id(accounts[0].get('source_home') or '~/.claude', accounts[0]['email'])
        if origin != self.balances.origins.get('claude'):
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
        return dict(data, origin=origin)

    def reader_status(self, paired=None, now=None):
        """The browser reader's situation for the dashboard, or None while saved resets are not read automatically."""
        config = self.config() if callable(self.config) else self.config
        if not config.get('automatic_claude_resets'):
            return None
        return self.reader.status(time.time() if now is None else now,
                                  self.settings() is not None if paired is None else paired)

    def refused(self, origin, settings):
        # An extension-shaped origin that was turned away is a stale pairing, not silence. Web pages are not counted.
        if isinstance(origin, str) and EXTENSION_ORIGIN.fullmatch(origin):
            now = time.time()
            self.reader.rejected_contact(now)
            self.reader_status(paired=settings is not None, now=now)

    def origin_allowed(self, origin):
        settings = self.settings()
        allowed = bool(settings and origin == 'chrome-extension://' + settings['extension_id'])
        if not allowed:
            self.refused(origin, settings)
        return allowed

    def authorized(self, origin, authorization):
        settings = self.settings()
        allowed = bool(settings and origin == 'chrome-extension://' + settings['extension_id']
                       and isinstance(authorization, str)
                       and hmac.compare_digest(authorization, 'Bearer ' + settings['secret']))
        if not allowed:
            self.refused(origin, settings)
        return allowed

    def quota(self, settings, data, observed=None):
        """(stored, reason) for the quota that came with an answer, judged apart from the bank: it never raises for a bad
        quota and never costs the bank. None when an older extension sent none."""
        if 'quota' not in data and 'quota_reason' not in data:
            return None
        quota = data.get('quota')
        if quota is None:
            return False, reason_id(data.get('quota_reason'), QUOTA_REASONS) or 'quota_invalid'
        try:
            record = quota_record(quota, bind(settings, data) if observed is None else observed, settings['origin'])
            if record is None:
                return False, 'quota_invalid'
            store_quota(self.path.parent/'offline'/QUOTA_FILE, record)
            return True, None
        except Rejected:
            return False, 'quota_invalid'
        except OSError:
            return False, 'quota_invalid'

    def not_eligible(self, settings, data, observed_at):
        """Claude's own answer, bound to this account like any reading: remembered as no saved resets (Tony, 2026-11-03: "no tengo
        resets, quitame el puntito"). It does not expire: three faint icons and no dot, also while the browser is closed."""
        try:
            bind(settings, data)
        except Rejected:
            return False
        self.balances.set_count('claude', 0, source='claude_web', observed_at=observed_at, not_eligible=True,
                                organization_hash=settings['organization_hash'])
        return True

    def note(self, now, *args, **kwargs):
        self.reader.answered(now, *args, **kwargs)
        self.reader_status(paired=True, now=now)

    def accept(self, data):
        settings = self.settings()
        if settings is None or not isinstance(data, dict):
            raise ValueError('Browser reader unavailable')
        with self.lock:
            now = time.time()
            if data == {'operation': 'challenge'}:
                nonce = secrets.token_hex(32)
                self.pending = (nonce, now, settings['account_hash'], settings['organization_hash'])
                self.reader.challenged(now)
                return {'nonce': nonce}
            self.reader.contacted(now)
            pending = self.pending
            if (data.get('operation') not in ('observation', 'unavailable') or pending is None
                    or data.get('nonce') != pending[0] or not 0 <= now-pending[1] <= CHALLENGE_SECONDS
                    or pending[2:] != (settings['account_hash'], settings['organization_hash'])):
                raise ValueError('Reading must answer a fresh single-use challenge')
            self.pending = None
            version = data.get('version') if isinstance(data.get('version'), str) and VERSION.fullmatch(data['version']) else None
            reason = reason_id(data.get('reason'), EXTENSION_REASONS) or 'unknown' if data.get('operation') == 'unavailable' else None
            if reason == 'not_eligible' and self.not_eligible(settings, data, pending[1]):
                self.note(now, reason, version, delivered=True, quota=self.quota(settings, data))
                return {'status': 'ok'}
            # A current failure clears a count, but says nothing against an account Claude has said has no saved resets
            # (Chrome signed out, a network error): only a real inventory or another not-eligible answer changes that.
            if not self.balances.not_eligible('claude', settings['organization_hash']):
                self.balances.set_count('claude', None, source='claude_web',
                                        organization_hash=settings['organization_hash'])
            if reason:
                self.note(now, reason, version, quota=self.quota(settings, data))
                return {'status': 'unknown'}
            try:
                observed = bind(settings, data)
            except Rejected as error:
                self.note(now, error.reason, version)
                raise
            quota = self.quota(settings, data, observed)
            result = available_resets(data.get('inventory'), observed)
            if result is None:
                self.note(now, 'malformed_inventory', version, quota=quota)
                return {'status': 'unknown'}
            count, expiry = result
            # Provider dates bound the grant, even when the PC's clock is offset.
            valid_until = pending[1]+expiry-observed if expiry is not None else None
            self.balances.set_count('claude', count, source='claude_web',
                                    observed_at=pending[1], valid_until=valid_until,
                                    organization_hash=settings['organization_hash'])
            self.note(now, 'ok', version, delivered=True, quota=quota)
            return {'status': 'ok'}
