"""Numbers-only history of the quota readings, for the dashboard's chart and its forecast (Tony, 2026-11-03).

WEB ONLY. Nothing in the board renderers or `board_pages` imports this module or receives its numbers
(`tests/test_usage_history.py` proves it); the touch board and the clock never show a forecast.

One line per reading that changed: time, provider, window label, used percent, reset time. Never an account name,
an email, a credential or any screen text. The file is private (0600), keeps 30 days, survives a corrupt line and
must never disturb the monitor: `UsageHistory.record` swallows every error.

Honesty rules, in the words of the brief:
- A gap breaks the line. An outage is never flat usage: two points further apart than `GAP` are not joined and are
  never evidence for a pace.
- A reset starts a new window. A forecast uses the CURRENT window only.
- Thin evidence, flat usage or an old reading say nothing (`forecast` returns None). Unknown is never a number.
"""
import json
import math
import os
import re
import threading
import time
from pathlib import Path

RETENTION_SECONDS = 30 * 86400
MIN_INTERVAL = 180        # a changed reading is written at most this often per window
HEARTBEAT = 600           # an unchanged one is written this often: "still the same" can be told from "no reading"
GAP = 1200                # two points further apart than this are not one line, and never one pace
STALE = 900               # a forecast needs a recorded reading at most this old
MAX_READING_AGE = 900     # a reading older than this is not recorded (the monitor calls it stale at the same age)
RESET_TOLERANCE = 120     # reset times that differ by less are the same window
LABELS = {'5H': 5 * 3600, 'WEEK': 7 * 86400}      # window label -> its length in seconds
PACE_SECONDS = {'5H': 3600, 'WEEK': 86400}        # how far back the pace is measured
MIN_COVER = 0.5           # the evidence must span at least this share of that look-back...
MIN_POINTS = 3            # ...and have at least this many readings
MAX_POINTS = 240          # points per window sent to the page
COMPACT_EVERY = 6 * 3600
MAX_READ_BYTES = 16 * 1024 * 1024
PROVIDER = re.compile(r'^[a-z][a-z0-9_-]{0,23}$')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _point(record):
    """(time, used percent, reset time) of one stored line, or None when the line is not a usable reading."""
    if not isinstance(record, dict):
        return None
    t, u, r = record.get('t'), record.get('u'), record.get('r')
    if not (_number(t) and _number(u) and _number(r)) or not 0 <= u <= 100 or t <= 0 or r <= t:
        return None
    return float(t), float(u), float(r)


def _line(provider, label, t, used, resets_at):
    return json.dumps({'t': int(t), 'p': provider, 'w': label, 'u': round(float(used), 2), 'r': int(resets_at)},
                      separators=(',', ':'), sort_keys=True) + '\n'


def readings(snapshot, now):
    """The readings of a monitor snapshot worth keeping: (provider, label, time, used, resets_at).

    Only a provider with exactly one account is recorded (two accounts would be two different lines mixed into one),
    only a row that is `ok` and recent, and only a window with a real percent and a reset time in the future.
    The time is the reading's own (`fetched_at`), never the poll time, so a reader that stopped cannot look alive.
    """
    rows = [row for row in (snapshot.get('accounts') or {}).values() if isinstance(row, dict)]
    by_provider = {}
    for row in rows:
        by_provider.setdefault(row.get('provider'), []).append(row)
    found = []
    for provider, group in by_provider.items():
        if len(group) != 1 or not isinstance(provider, str) or not PROVIDER.match(provider):
            continue
        row = group[0]
        fetched = row.get('fetched_at')
        if row.get('status') != 'ok' or not _number(fetched) or fetched > now + 60 or now - fetched > MAX_READING_AGE:
            continue
        done = set()
        for window in row.get('windows') or []:
            if not isinstance(window, dict):
                continue
            label, used, reset = window.get('label'), window.get('used_percent'), window.get('resets_at')
            if label not in LABELS or label in done or not _number(used) or not 0 <= used <= 100 or not _number(reset) or reset <= max(fetched, now):
                continue
            done.add(label)
            found.append((provider, label, min(float(fetched), float(now)), float(used), float(reset)))
    return found


def current_run(series, reset):
    """The newest unbroken stretch of readings in the window that ends at `reset`, oldest first.

    It stops at an outage (a gap), at another window (a different reset time) and where the count fell.
    """
    run = [series[-1]]
    for point in reversed(series[:-1]):
        if run[0][0] - point[0] > GAP or abs(point[2] - reset) > RESET_TOLERANCE or point[1] > run[0][1]:
            break
        run.insert(0, point)
    return run


def forecast(points, label, now):
    """What the recent pace says about this window, or None when it says nothing.

    `points` are (time, used percent, reset time) of ONE provider and window label, in any order. The pace is the used
    percent gained over the last hour (5-hour window) or day (week), counted only inside the current window and only
    over an unbroken stretch of readings. Needs at least `MIN_POINTS` readings spanning half of that look-back, a
    recent last reading, a window that has not ended, and usage that actually moved: otherwise None.

    Returns {'state': 'runs_out', 'at', 'seconds', ...} when 100% comes before the reset and {'state': 'lasts', ...}
    when it does not. This is arithmetic on the pace so far, not a promise: the page words it "at this pace".
    """
    look_back = PACE_SECONDS.get(label)
    series = sorted(p for p in map(_point_of, points) if p)
    if not look_back or not series:
        return None
    last_t, last_used, reset = series[-1]
    if now - last_t > STALE or last_t > now + 60 or reset <= now or last_used >= 100:
        return None
    base = [p for p in current_run(series, reset) if p[0] >= last_t - look_back]
    span = base[-1][0] - base[0][0]
    rise = base[-1][1] - base[0][1]
    if len(base) < MIN_POINTS or span < look_back * MIN_COVER or rise <= 0:
        return None
    per_second = rise / span
    result = {'pace_per_hour': round(per_second * 3600, 2), 'span': int(span)}
    runs_out_at = last_t + (100 - last_used) / per_second
    if runs_out_at >= reset:
        result.update(state='lasts', at=None, seconds=None, end_used=round(min(100.0, last_used + per_second * (reset - last_t)), 1))
    else:
        result.update(state='runs_out', at=int(runs_out_at), seconds=int(max(0, runs_out_at - now)), end_used=100.0)
    return result


def _point_of(point):
    try:
        t, u, r = point
    except (TypeError, ValueError):
        return None
    return _point({'t': t, 'u': u, 'r': r})


def segments(series, length):
    """The solid parts of the line: a new part starts after a gap or where the count fell. At most MAX_POINTS in all."""
    parts = []
    for point in series:
        if parts and point[0] - parts[-1][-1][0] <= GAP and point[1] >= parts[-1][-1][1]:
            parts[-1].append(point)
        else:
            parts.append([point])
    bucket = max(1.0, length / MAX_POINTS)
    thinned = []
    for part in parts:
        last_in_slice = {}
        for point in part:
            last_in_slice[int(point[0] // bucket)] = point
        thinned.append(sorted({*last_in_slice.values(), part[0], part[-1]}))
    return [[[int(t), round(u, 1)] for t, u, _ in part] for part in thinned]


class UsageHistory:
    def __init__(self, path, clock=time.time, retention=RETENTION_SECONDS):
        self.path = Path(path)
        self.clock = clock
        self.retention = retention
        self.lock = threading.Lock()
        self.last = {}
        self.loaded = False
        self.compacted = 0.0

    # ── writing ──────────────────────────────────────────────────────────
    def record(self, snapshot, now=None):
        """Keep what changed in this snapshot. Returns how many lines were written; never raises."""
        try:
            now = self.clock() if now is None else now
            with self.lock:
                if not self.loaded:
                    self._remember(now)
                    self._compact(now)
                elif now - self.compacted >= COMPACT_EVERY:
                    self._compact(now)
                written = 0
                for provider, label, t, used, reset in readings(snapshot, now):
                    if self._due(self.last.get((provider, label)), t, used, reset):
                        written += self._append(provider, label, t, used, reset)
                return written
        except Exception:  # noqa: BLE001 - the history must never disturb the monitor
            return 0

    def write(self, provider, label, t, used, resets_at):
        """Append one reading as it is (no rules). For tools and tests; the monitor calls `record`."""
        with self.lock:
            return self._append(provider, label, t, used, resets_at)

    @staticmethod
    def _due(last, t, used, reset):
        if last is None:
            return True
        last_t, last_used, last_reset = last
        if t <= last_t:
            return False
        if abs(reset - last_reset) > RESET_TOLERANCE:
            return True                       # a new window starts at once
        return t - last_t >= (MIN_INTERVAL if used != last_used else HEARTBEAT)

    def _append(self, provider, label, t, used, resets_at):
        if label not in LABELS or not PROVIDER.match(str(provider)):
            return 0
        line = _line(provider, label, t, used, resets_at).encode()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            if os.fstat(fd).st_size and not self._ends_with_newline():
                line = b'\n' + line           # a crash left half a line: end it, so only that line is lost
            os.write(fd, line)
        finally:
            os.close(fd)
        self.last[(provider, label)] = (float(t), float(used), float(resets_at))
        return 1

    def _ends_with_newline(self):
        with open(self.path, 'rb') as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) == b'\n'

    def _remember(self, now):
        """What was written last for each window, from the end of the file, so a restart does not repeat a line."""
        self.loaded = True
        for (provider, label), series in self._read(now, tail=262144).items():
            self.last[(provider, label)] = series[-1]

    def _compact(self, now):
        """Drop old and corrupt lines. Rewrites the file only when there is something to drop."""
        self.compacted = now
        try:
            if self.path.stat().st_size > MAX_READ_BYTES:
                return                         # far more than 30 days can hold: leave it alone rather than guess
            raw = self.path.read_bytes()
        except OSError:
            return
        keep, lines = [], raw.splitlines()
        for text in lines:
            parsed = self._parse(text)
            if parsed and parsed[3] >= now - self.retention:
                keep.append(text)
        if len(keep) == len(lines) and (raw.endswith(b'\n') or not raw):
            return
        temporary = self.path.with_name(self.path.name + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, b''.join(text + b'\n' for text in keep))
        finally:
            os.close(fd)
        os.replace(temporary, self.path)

    # ── reading ──────────────────────────────────────────────────────────
    @staticmethod
    def _parse(text):
        """(provider, label, point, time) of one line, or None for anything that is not a good line."""
        try:
            record = json.loads(text)
            point = _point(record)
            provider, label = record.get('p'), record.get('w')
        except (ValueError, UnicodeError, AttributeError):
            return None
        if not point or label not in LABELS or not isinstance(provider, str) or not PROVIDER.match(provider):
            return None
        return provider, label, point, point[0]

    def _read(self, now, tail=MAX_READ_BYTES):
        found = {}
        try:
            size = self.path.stat().st_size
            with open(self.path, 'rb') as handle:
                if size > tail:
                    handle.seek(size - tail)
                    handle.readline()          # the first line of a tail may be cut
                raw = handle.read(tail)
        except OSError:
            return found
        for text in raw.splitlines():
            parsed = self._parse(text)
            if parsed and now - self.retention <= parsed[3] <= now + 60:
                found.setdefault((parsed[0], parsed[1]), []).append(parsed[2])
        return {key: sorted(series) for key, series in found.items()}

    def payload(self, now=None):
        """What `GET /history` sends: for each provider and window, the current window's line and its forecast."""
        now = self.clock() if now is None else now
        windows = {}
        for (provider, label), series in self._read(now).items():
            reset = series[-1][2]
            if reset <= now:
                continue                       # that window has ended; nothing to say until a new reading arrives
            length = LABELS[label]
            inside = [p for p in series if abs(p[2] - reset) <= RESET_TOLERANCE and p[0] >= reset - length - RESET_TOLERANCE]
            windows.setdefault(provider, {})[label] = {
                'resets_at': int(reset), 'length': length, 'segments': segments(inside, length),
                'forecast': forecast(series, label, now)}
        return {'schema': 1, 'now': int(now), 'windows': windows}
