"""Capture and normalize local Antigravity (agy) Gemini quota metadata for the tablet.

Only sanitized quota percentages and reset timestamps are stored or returned:
no credentials, emails, prompts, session ids or workspace paths.
"""
import fcntl
import math
import os
import time
from pathlib import Path

from token_tv.local_usage import OFFICIAL_FRESH_SECONDS, atomic_json, clean_windows, origin_id, read_record
from token_tv.usage import timestamp, window

GEMINI_DEFAULT_CACHE = Path('~/.config/token-tv/offline/gemini-official.json')
GEMINI_DEFAULT_HOME = '~/.gemini/antigravity-cli'
GEMINI_SOURCE = 'gemini_agy_statusline'
GEMINI_FRESH_SECONDS = OFFICIAL_FRESH_SECONDS
# Keep the last valid status-line reading (flagged aged after GEMINI_FRESH_SECONDS)
# until its own reset time passes, capped at 7 days so a bogus future timestamp cannot stick.
GEMINI_MAX_HOLD_SECONDS = 7 * 86400
_MAX_RESET_AHEAD_SECONDS = 35 * 86400


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _used_percent(entry):
    remaining_fraction = entry.get('remaining_fraction')
    if _finite(remaining_fraction) and 0 <= remaining_fraction <= 1:
        return round((1.0 - remaining_fraction) * 100.0, 4)
    for key in ('remaining_percent', 'remaining_percentage'):
        value = entry.get(key)
        if _finite(value) and 0 <= value <= 100:
            return round(100.0 - value, 4)
    for key in ('used_percentage', 'used_percent'):
        value = entry.get(key)
        if _finite(value) and 0 <= value <= 100:
            return round(float(value), 4)
    return None


def _resets_at(entry, now):
    for key in ('reset_time', 'resets_at'):
        parsed = timestamp(entry.get(key))
        if parsed is not None:
            return parsed
    seconds = entry.get('reset_in_seconds')
    if _finite(seconds) and 0 < seconds <= _MAX_RESET_AHEAD_SECONDS:
        return int(round(now + seconds))
    return None


def _is_non_gemini_bucket(key):
    return key.startswith('3p') or any(token in key for token in ('claude', 'openai', 'gpt', 'third_party', 'third-party'))


def parse_agy_quota(data, now=None):
    """Extract live normalized WEEK (and optional 5H) Gemini windows from an agy statusLine JSON payload."""
    if not isinstance(data, dict):
        return []
    now = time.time() if now is None else now
    container = data.get('quota') if isinstance(data.get('quota'), dict) else data.get('rate_limits')
    if not isinstance(container, dict):
        return []
    weekly_candidates = []
    session_candidates = []
    for raw_key, entry in container.items():
        if not isinstance(raw_key, str) or not isinstance(entry, dict):
            continue
        key = raw_key.strip().lower()
        if _is_non_gemini_bucket(key):
            continue
        used = _used_percent(entry)
        resets = _resets_at(entry, now)
        if used is None or resets is None or resets <= now:
            continue
        remaining_seconds = resets - now
        if any(token in key for token in ('week', 'seven_day', '7d')):
            priority = 0 if key == 'gemini-weekly' else 1
            weekly_candidates.append((priority, -used, window('WEEK', used, resets, 10080)))
        elif any(token in key for token in ('5h', 'five_hour', '5_hour', 'session')):
            priority = 0 if key == 'gemini-5h' else (1 if 'gemini' in key else 2)
            session_candidates.append((priority, -used, window('5H', used, resets, 300)))
        elif remaining_seconds > 24 * 3600:
            priority = 2 if 'gemini' in key else 3
            weekly_candidates.append((priority, -used, window('WEEK', used, resets, 10080)))
        elif 0 < remaining_seconds <= 6 * 3600:
            priority = 2 if 'gemini' in key else 3
            session_candidates.append((priority, -used, window('5H', used, resets, 300)))
    windows = []
    if weekly_candidates:
        weekly_candidates.sort(key=lambda item: (item[0], item[1]))
        if weekly_candidates[0][2]:
            windows.append(weekly_candidates[0][2])
    if session_candidates:
        session_candidates.sort(key=lambda item: (item[0], item[1]))
        if session_candidates[0][2]:
            windows.append(session_candidates[0][2])
    return windows


def capture_gemini(data, path=GEMINI_DEFAULT_CACHE, now=None, source_home=GEMINI_DEFAULT_HOME):
    """Save sanitized Antigravity Gemini quota fields locally; preserve live windows against stale idle sessions."""
    now = int(time.time() if now is None else now)
    windows = parse_agy_quota(data, now)
    if not windows:
        return False
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    origin = origin_id(source_home)
    fd = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_record(path)
        merged = {item['label']: item for item in windows}
        if isinstance(previous, dict) and previous.get('origin') == origin and previous.get('source') == GEMINI_SOURCE:
            for item in clean_windows(previous.get('windows')):
                label = item.get('label')
                if label in ('WEEK', '5H') and label not in merged and item.get('resets_at') and item['resets_at'] > now:
                    merged[label] = item
        ordered = [merged[label] for label in ('WEEK', '5H') if label in merged]
        saved = {
            'fetched_at': now,
            'windows': ordered,
            'source': GEMINI_SOURCE,
            'origin': origin,
        }
        atomic_json(path, saved)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return True


def read_gemini_record(cache_path=GEMINI_DEFAULT_CACHE, source_home=GEMINI_DEFAULT_HOME):
    """Read the local sanitized Gemini record when its origin matches the configured agy home."""
    record = read_record(Path(cache_path).expanduser())
    if not record or record.get('source') != GEMINI_SOURCE:
        return None
    if source_home is not None and record.get('origin') != origin_id(source_home):
        return None
    return record


def gemini_tablet_provider(record, now=None):
    """Convert a sanitized local Gemini record into the tablet's read-only provider shape.

    Stays fresh for GEMINI_FRESH_SECONDS, then stays visible marked `aged: True` until
    its weekly `resets_at` passes (capped at GEMINI_MAX_HOLD_SECONDS). Once the reset
    passes, returns honest unknown (`weekly: None`) until the next agy capture.
    """
    empty = {'weekly': None, 'session': None, 'aged': False,
             'resets': {'count': None, 'old': False}, 'credits': None}
    if not isinstance(record, dict) or record.get('source') != GEMINI_SOURCE:
        return empty
    now = time.time() if now is None else now
    fetched = timestamp(record.get('fetched_at'))
    if fetched is None:
        return empty
    age = now - fetched
    if age < -60 or age > GEMINI_MAX_HOLD_SECONDS:
        return empty
    windows = clean_windows(record.get('windows'))
    week = [w for w in windows if w['label'] == 'WEEK' and w.get('resets_at') is not None and w['resets_at'] > now]
    if len(week) != 1:
        return empty
    aged = age > GEMINI_FRESH_SECONDS
    result = dict(empty, aged=aged)
    result['weekly'] = {'remaining': round(100 - week[0]['used_percent'], 4), 'resets_at': week[0]['resets_at']}
    session = [w for w in windows if w['label'] == '5H' and w.get('resets_at') is not None and w['resets_at'] > now]
    if len(session) == 1:
        result['session'] = {'remaining': round(100 - session[0]['used_percent'], 4), 'resets_at': session[0]['resets_at']}
    return result
