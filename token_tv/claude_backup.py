"""Claude's quota from the paired browser extension: a backup for the official reader (Tony, 2026-10-25 yes; plan 2026-11-03).

The extension's usage GET (the one it already makes for the saved resets, no new query) carries `five_hour` and `seven_day`
beside the bank. The bridge keeps what passes `quota_record` in the record shape of `claude_usage.native_record`, dated by the
provider and never by the arrival; `fetch_local` lets it stand in only when the official reading is missing, stale or older.
"""
from pathlib import Path

from token_tv.local_usage import atomic_json, local_row, origin_id, read_record
from token_tv.usage import normalize_claude, timestamp

SOURCE = 'claude_browser'
FILE = 'claude-browser.json'


def quota_record(quota, provider_at, origin):
    """The extension's quota as a `native_record`-shaped record, or None. Strict: any doubt means no reading, never a guess."""
    if (not isinstance(quota, dict) or set(quota) - {'five_hour', 'seven_day'}
            or not isinstance(quota.get('seven_day'), dict) or type(provider_at) not in (int, float) or not 0 < provider_at < 1e15):
        return None
    rates = {}
    for key in ('five_hour', 'seven_day'):
        value = quota.get(key)
        if value is None and key == 'five_hour':
            continue  # no session window is live: unknown, never zero
        if not isinstance(value, dict) or set(value) != {'utilization', 'resets_at'}:
            return None
        used, reset = value['utilization'], value['resets_at']
        # Comparisons only (they refuse nan and inf, and never raise for a huge whole number); a reset a year out is junk.
        if (type(used) not in (int, float) or not 0 <= used <= 100
                or type(reset) not in (int, float) or not provider_at < reset <= provider_at + 366 * 86400):
            return None
        rates[key] = value
    windows = normalize_claude(rates)
    if len(windows) != len(rates):
        return None
    return {'fetched_at': provider_at, 'windows': windows, 'origin': origin, 'source': SOURCE, 'stale': False,
            'identity_verified': True}


def store(path, record):
    """Atomic, newest wins: a reading dated before the one on disk (same account) never replaces it."""
    previous = read_record(path)
    if (previous and previous.get('source') == SOURCE and previous.get('origin') == record['origin']
            and (timestamp(previous.get('fetched_at')) or 0) > record['fetched_at']):
        return False
    atomic_json(path, record)
    return True


def with_backup(row, account, cache_dir, now=None):
    """`row` is the official reading. The browser's takes its place only when that is missing, stale or older, never while it
    is current; the age tiers are `local_row`'s own, so the browser's reading is shown, aged or dropped by the same rule."""
    record = read_record(Path(cache_dir) / FILE)
    if (not record or record.get('source') != SOURCE
            or record.get('origin') != origin_id(account['source_home'], account.get('email'))):
        return row
    backup = local_row(account, record, now)
    if not backup['windows']:
        return row
    if row['windows'] and (not row.get('reading_aged') or row['fetched_at'] >= backup['fetched_at']):
        return row
    backup['quota_origin'] = SOURCE
    backup['identity_verified'] = bool(account.get('email') and record.get('identity_verified') is True
                                       and backup['status'] == 'ok')
    if 'reader' in row:
        backup['reader'] = row['reader']  # why the official reader is failing stays known
    return backup
