"""Read Codex quota and saved resets with account GETs; never redeem them."""
import time
from pathlib import Path
from token_tv.sources import RPC, scoped_env, exe, SourceError, identity_matches
from token_tv.local_usage import origin_id
from token_tv.usage import normalize_codex
from token_tv.credits import parse_balance


def available_resets(data):
    summary = data.get('rateLimitResetCredits') if isinstance(data, dict) else None
    count = summary.get('availableCount') if isinstance(summary, dict) else None
    return count if type(count) is int and 0 <= count <= 999 else None


def quota_record(data, root, now=None, expected_email=None):
    now = time.time() if now is None else now
    record = {'fetched_at': now, 'windows': [], 'source': 'codex_official_cli',
              'origin': origin_id(root, expected_email), 'stale': False, 'ordinary_usage_allowed': None}
    if not isinstance(data, dict):
        return record
    if type(data.get('ordinaryUsageAllowed')) is bool:
        record['ordinary_usage_allowed'] = data['ordinaryUsageAllowed']
    buckets = data.get('rateLimitsByLimitId')
    rates = buckets.get('codex') if isinstance(buckets, dict) and 'codex' in buckets else data.get('rateLimits')
    if not isinstance(rates, dict) or rates.get('limitId') not in (None, 'codex'):
        return record
    credits = rates.get('credits')
    if isinstance(credits, dict) and credits.get('unlimited') is False:
        record['credits_balance'] = parse_balance(credits.get('balance'))
    # A present but malformed window must not disappear and make the other
    # window appear to give more usable quota. Null windows are legitimate.
    expected = 0
    for name in ('primary', 'secondary'):
        value = rates.get(name)
        if value is not None:
            if not isinstance(value, dict):
                return record
            expected += 1
    windows = normalize_codex({'rateLimits': rates})
    if len(windows) != expected or any(w['resets_at'] is None or w['resets_at'] <= now for w in windows):
        return record
    record['windows'] = windows
    return record


class CodexResetReader:
    def __init__(self, root, expected_email=None):
        self.root = Path(root).expanduser().resolve()
        self.expected_email = expected_email
        command = [exe('codex'), 'app-server', '-c', 'analytics.enabled=false',
                   '-c', 'chatgpt_base_url="https://chatgpt.com/backend-api/"',
                   '-c', 'respect_system_proxy=false', '-c', 'mcp_servers={}']
        self.rpc = RPC(command, scoped_env('codex', Path(root).expanduser()))
        try:
            self.rpc.call('initialize', {'clientInfo': {'name': 'local_reset_display', 'title': 'Local reset balance',
                                                       'version': '0.1.0'}, 'capabilities': {'experimentalApi': True}})
            self.rpc.process.stdin.write('{"method":"initialized","params":{}}\n')
            self.rpc.process.stdin.flush()
            self.authenticate()
        except Exception:
            self.rpc.close()
            raise

    def read(self):
        # These are account GETs. No threads, model turns, checkout or redemption RPCs.
        self.authenticate()
        data = self.rpc.call('account/rateLimits/read')
        self.authenticate()
        return available_resets(data)

    def authenticate(self):
        account = self.rpc.call('account/read', {'refreshToken': True}).get('account') or {}
        if account.get('type') != 'chatgpt':
            raise SourceError('subscription_login_required')
        if self.expected_email is not None and (not isinstance(account.get('email'), str)
                                               or not identity_matches(self.expected_email, account['email'])):
            raise SourceError('identity_mismatch')

    def read_snapshot(self):
        # Re-check both subscription and identity on every observation.
        self.authenticate()
        data = self.rpc.call('account/rateLimits/read')
        observed_at = time.time()
        # A concurrent login change must not attribute its response to the
        # configured account. The response itself has no account identity.
        self.authenticate()
        quota = quota_record(data, self.root, now=observed_at, expected_email=self.expected_email)
        quota['identity_verified'] = self.expected_email is not None
        return {'quota': quota,
                'available_resets': available_resets(data)}

    def close(self):
        self.rpc.close()
