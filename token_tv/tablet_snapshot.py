"""Narrow the existing local quota snapshot to the tablet's read-only fields."""
import math
import time

from token_tv.credits import exhausted_credits, format_balance
from token_tv.gemini_usage import gemini_tablet_provider
from token_tv.local_usage import CLAUDE_OFFICIAL, expire_official_quota


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _resets(info, provider, now, quota_aged):
    empty = {'count': None, 'old': False}
    if not isinstance(info, dict):
        return empty
    source = info.get('source')
    allowed = {'user_confirmed', 'stale', 'codex_cli' if provider == 'codex' else 'claude_web'}
    if provider == 'claude':
        allowed.add('claude_not_eligible')
    if source not in allowed:
        return empty
    kept = info.get('available') is None and type(info.get('last_known')) is int
    count = info.get('last_known') if kept else info.get('available')
    if type(count) is not int or count < 0 or count > 999:
        return empty
    timed = kept or source in ('codex_cli', 'claude_web', 'stale')
    stamp, until = info.get('confirmed_at'), info.get('valid_until')
    if timed:
        if not _number(stamp) or not -60 <= now - stamp <= 72 * 3600:
            return empty
        if until is not None and (not _number(until) or until <= now):
            return empty
        if source == 'claude_web' and count > 0 and not _number(until):
            return empty
    if source == 'claude_not_eligible' and count != 0:
        return empty
    return {'count': count, 'old': bool(quota_aged or (timed and now - stamp > 180))}


def _window(window):
    if (not isinstance(window, dict) or window.get('label') not in ('WEEK', '5H')
            or not _number(window.get('used_percent')) or not 0 <= window['used_percent'] <= 100
            or not _number(window.get('resets_at'))):
        return None
    return {'label': window['label'], 'used_percent': window['used_percent'], 'resets_at': window['resets_at']}


def _provider(source, provider, now):
    empty = {'weekly': None, 'session': None, 'aged': False,
             'resets': {'count': None, 'old': False}, 'credits': None}
    if not isinstance(source, dict) or source.get('identity_verified') is not True:
        return empty
    origins = CLAUDE_OFFICIAL if provider == 'claude' else ('codex_official_cli',)
    if source.get('quota_origin') not in origins or not _number(source.get('fetched_at')):
        return empty
    windows = source.get('windows') if isinstance(source.get('windows'), list) else []
    normalized = [_window(window) for window in windows]
    windows = [window for window in normalized if window is not None]
    row = dict(source, windows=windows)
    expire_official_quota(row, now)
    aged = row.get('reading_aged') is True
    result = dict(empty, aged=aged, resets=_resets(source.get('banked_resets'), provider, now, aged))
    if row.get('status') != 'ok':
        return result
    week = [window for window in row['windows'] if window['label'] == 'WEEK' and window['resets_at'] > now]
    if len(week) != 1:
        return result
    result['weekly'] = {'remaining': 100 - week[0]['used_percent'], 'resets_at': week[0]['resets_at']}
    if provider == 'claude':
        session = [window for window in row['windows'] if window['label'] == '5H' and window['resets_at'] > now]
        if len(session) == 1:
            result['session'] = {'remaining': 100 - session[0]['used_percent'], 'resets_at': session[0]['resets_at']}
    else:
        credit = exhausted_credits(row)
        result['credits'] = format_balance(credit) if credit is not None else None
    return result


def tablet_snapshot(snapshot, now=None, gemini_record=None):
    now = time.time() if now is None else now
    accounts = snapshot.get('accounts', {}) if isinstance(snapshot, dict) else {}
    accounts = accounts if isinstance(accounts, dict) else {}
    result = {}
    for provider in ('codex', 'claude'):
        rows = [row for row in accounts.values() if isinstance(row, dict) and row.get('provider') == provider]
        result[provider] = _provider(rows[0] if len(rows) == 1 else None, provider, now)
    result['gemini'] = gemini_tablet_provider(gemini_record, now)
    return {'providers': result}
