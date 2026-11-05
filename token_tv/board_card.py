"""The text of the board's details card (Tony, 2026-11-03: "this card is the one place for exact numbers").

Hold the touch screen for about 0.7 seconds and release: the board shows what the scenes leave out so that they stay clean.
The PC builds ONE short line of ASCII from the snapshot and sends it on the heartbeat it already sends (`/ping?card=...`),
only to a board that advertises the capability. Nothing is stored in the board's flash, nothing extra is requested, and no
account data travels: numbers, and the fixed words of `reader_status`, only.

Version 1, comma separated: `1,xw62,xr259000,xa95,xs2,lw75,lr259000,lh40,lk5400,la120,ls-,leSign-in needed`
`x` is Codex and `l` is Claude, then one letter for the field and its value:
  w  week left, whole percent as every scene rounds it; `<` when positive but under one percent; `-` unknown
  r  seconds to the weekly reset (counted down by the board from the moment it arrives); `-` unknown
  h  Claude's five-hour quota left, as `w`        k  seconds to the five-hour reset
  a  age of the reading in seconds (the board adds the time since arrival); `-` unknown
  s  saved resets, digits, `o` after them when only an old confirmed count is known; `-` unknown
  e  the short reason something is missing (`reader_status.short_reason`), letters, digits, spaces and hyphens
Unknown is `-`, never zero. The firmware parses it strictly and ignores a malformed line whole.
"""
import math
import re

from token_tv import reader_status
from token_tv.display import overview_rows, primary_window
from token_tv.personal_faces import banked_hearts, session_window

VERSION = '1'
MAX_PAYLOAD = 200   # characters; the board refuses anything longer
MAX_WEEK_SECONDS = 9_999_999
MAX_SESSION_SECONDS = 99_999
MAX_AGE_SECONDS = 99_999
SIDES = (('x', 'codex'), ('l', 'claude'))
_REASON_TEXT = re.compile(r'[A-Za-z0-9 -]{1,17}')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _percent(remaining):
    """`-` unknown, `<` positive but under one percent, else the whole percent: the rounding every scene uses."""
    if not _number(remaining):
        return '-'
    remaining = max(0.0, min(100.0, float(remaining)))
    return '<' if 0 < remaining < 1 else str(round(remaining))


def _seconds(value, limit):
    """Whole seconds from now, or `-` when unknown, already passed or beyond what the board accepts."""
    return str(int(value)) if _number(value) and 0 <= value <= limit else '-'


def _reason(row, week_missing):
    """The short words for why something is missing, or '' when nothing is. Tolerates a row without `reader`."""
    reader = row.get('reader')
    failing = isinstance(reader, dict) and reader.get('state') == 'failing'
    if not (week_missing or failing):
        return ''
    reason = reader.get('reason') if isinstance(reader, dict) else None
    text = reader_status.short_reason(reason if isinstance(reason, str) else None)
    return text if _REASON_TEXT.fullmatch(text) else reader_status.short_reason(None)


def _side(prefix, row, now):
    row = dict(row, windows=row.get('windows') or [])
    week = primary_window(row, 'WEEK')
    used = week.get('used_percent') if week else None
    remaining = 100 - max(0, min(100, used)) if _number(used) else None
    reset = week.get('resets_at') if week else None
    tokens = [('w', _percent(remaining)),
              ('r', _seconds(reset - now, MAX_WEEK_SECONDS) if _number(reset) else '-')]
    if prefix == 'l':
        session = session_window(row, now)
        if session:
            tokens += [('h', _percent(100 - max(0, min(100, session['used_percent'])))),
                       ('k', _seconds(session['resets_at'] - now, MAX_SESSION_SECONDS))]
    fetched = row.get('fetched_at')
    age = max(0, now - fetched) if remaining is not None and _number(fetched) and fetched > 0 else None
    tokens.append(('a', _seconds(age, MAX_AGE_SECONDS) if age is not None else '-'))
    count, old = banked_hearts(row)
    tokens.append(('s', f'{min(count, 99)}{"o" if old else ""}' if type(count) is int and count >= 0 else '-'))
    text = _reason(row, remaining is None)
    if text:
        tokens.append(('e', text))
    return [prefix + field + value for field, value in tokens]


def card_payload(snapshot, now):
    """The card's line for the board, or None when there is nothing to say (no Codex or Claude account) or the snapshot
    cannot be read. `now` is the epoch second the snapshot is read at; the board counts from its own arrival."""
    try:
        rows = {row.get('provider'): row for row in overview_rows(snapshot)}
        tokens = []
        for prefix, provider in SIDES:
            row = rows.get(provider)
            if row is not None and row.get('status') is not None:
                tokens += _side(prefix, row, now)
        payload = VERSION + ',' + ','.join(tokens)
        return payload if tokens and len(payload) <= MAX_PAYLOAD else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
