"""Why a quota reading is missing, in fixed words only (Tony, 2026-11-03).

Claude had no data for 7 days 14 h (2026-10-25 to 11-02) and nothing said so or why. Readers publish one of these ids,
never screen text or account data; the panel and the board's detail card show the words. New visible text is English;
the dashboard translates by id (`token_tv/web/i18n.js`).
"""
import math
import time
from pathlib import Path

# id: (short words for the board's card, one plain sentence for the dashboard)
REASONS = {
    'org_blocked': ('Access blocked', 'Claude Code says the organization has disabled subscription access.'),
    'rate_limited': ('Too many requests', 'The service is limiting usage requests; the reader is waiting before it asks again.'),
    'login_required': ('Sign-in needed', 'The login was lost: sign in again in the client (in Claude Code, /login).'),
    'wrong_account': ('Different account', 'The signed-in account is not the one this display expects.'),
    'client_version': ('Client updated', 'A new Claude Code series needs a review before the reader can use it.'),
    'model_activity': ('Reader stopped', 'The reader stopped because the client reported model activity.'),
    'reader_stuck': ('Reader stuck', 'The client opened but did not confirm a new reading.'),
    'unknown': ('No reading', 'The reader has not obtained a reading.'),
}

# The reader's fixed failure codes. Hints are the yes/no screen words of `claude_usage.SCREEN_HINTS`.
_CODES = {
    'subscription_login_required': 'login_required', 'auth_unavailable': 'login_required', 'auth_required': 'login_required',
    'identity_mismatch': 'wrong_account', 'wrong_account': 'wrong_account',
    'unsupported_client_version': 'client_version',
    'unexpected_model_activity': 'model_activity',
    'native_refresh_unconfirmed': 'reader_stuck', 'official_quota_unavailable': 'reader_stuck',
    'usage_view_not_confirmed': 'reader_stuck', 'client_not_ready': 'reader_stuck', 'cli_output_limit': 'reader_stuck',
    'timeout': 'reader_stuck', 'cli_unavailable': 'reader_stuck', 'rpc_error': 'reader_stuck', 'method_unavailable': 'reader_stuck',
}
# Hints are substrings of the lowercased screen. The real block message is "Your organization has disabled Claude
# subscription access for Claude Code" (the old check looked for the wrong word and could never match).
ORG_BLOCK = 'organization has disabled'
RATE_LIMIT = ('rate limit', '429', 'too many requests')


def reason_for(code, hints=()):
    """The id for a reader's failure code and the screen words it saw. A block or a limit explains more than the step that failed."""
    hints = set(hints or ())
    if ORG_BLOCK in hints:
        return 'org_blocked'
    if hints & set(RATE_LIMIT):
        return 'rate_limited'
    return _CODES.get(code, 'unknown')


def short_reason(reason):
    return REASONS.get(reason, REASONS['unknown'])[0]


def long_reason(reason):
    return REASONS.get(reason, REASONS['unknown'])[1]


# What a reader publishes for the monitor next to its readings (offline/<provider>-reader-status.json): ids and epochs only.
STATUS_FILES = {'claude': 'claude-reader-status.json', 'codex': 'codex-reader-status.json'}
STATUS_GRACE_SECONDS = 300  # a reader that missed its own next write by this much has stopped: say nothing rather than guess


def status_record(state, reason=None, since=None, retry_at=None, next_at=None, now=None):
    """The file body. `state` is 'ok' or 'failing'; `reason` one id of REASONS; `since` when this state began; `retry_at` when a
    deliberate backoff ends; `next_at` when the reader will write again."""
    now = int(time.time() if now is None else now)
    if state not in ('ok', 'failing'):
        raise ValueError('state must be ok or failing')
    reason = None if state == 'ok' else (reason if reason in REASONS else 'unknown')
    return {'schema': 1, 'state': state, 'reason': reason, 'since': int(since if since is not None else now),
            'retry_at': None if retry_at is None else int(retry_at), 'updated_at': now,
            'next_at': int(next_at if next_at is not None else now)}


def publish_status(cache_dir, provider, state, reason, since, retry_at, next_at, now):
    """Write the reader's state next to its readings. Never lets a full disk stop the reader."""
    from token_tv.local_usage import atomic_json   # local_usage imports this module
    try:
        atomic_json(Path(cache_dir) / STATUS_FILES[provider], status_record(state, reason, since, retry_at, next_at, now))
    except OSError:
        pass


def last_state(cache_dir, provider):
    """(state, since) a quickly restarted reader resumes, so 'since' survives a restart; (None, 0) when there is nothing recent."""
    from token_tv.local_usage import read_record
    found = reader_state(read_record(Path(cache_dir) / STATUS_FILES[provider]))
    return (found['state'], found['since']) if found else (None, 0)


def _epoch(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def reader_state(data, now=None):
    """`row['reader']` from a status file: {'state', 'reason', 'since', 'retry_at'}, or None when the file is missing, malformed
    or its reader stopped writing (nothing is known then)."""
    if not isinstance(data, dict) or data.get('schema') != 1:
        return None
    now = time.time() if now is None else now
    updated, next_at = data.get('updated_at'), data.get('next_at')
    if not _epoch(updated) or not _epoch(next_at) or data.get('state') not in ('ok', 'failing'):
        return None
    if not updated - 60 <= now <= max(updated, next_at) + STATUS_GRACE_SECONDS:
        return None
    failing = data['state'] == 'failing'
    since, retry_at = data.get('since'), data.get('retry_at')
    reason = data.get('reason') if data.get('reason') in REASONS else 'unknown'
    return {'state': data['state'], 'reason': reason if failing else None,
            'since': int(min(since, updated)) if _epoch(since) else int(updated),
            'retry_at': int(retry_at) if failing and _epoch(retry_at) and now - 60 <= retry_at <= now + 86400 else None}
