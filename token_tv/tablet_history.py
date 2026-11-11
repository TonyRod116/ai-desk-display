"""A short memory of the PC metrics for the tablet's trend lines (numbers only, RAM only).

The tablet service calls MetricsHistory.add() once per collection (every 30 s) and serves payload().
Nothing here touches the disk, an account or a program name; a reading that is missing is a gap
(None), never a zero.

Series (all rounded to one decimal): cpu = CPU load %, gpu = % of the busiest GPU, cpu_temp and
gpu_temp = degrees C (the hottest GPU), memory = % of RAM in use, down and up = bits per second.
"""
from collections import deque
import math
import threading
import time

SERIES = ('cpu', 'gpu', 'cpu_temp', 'gpu_temp', 'memory', 'down', 'up')


def _value(number, maximum=None):
    """A finite, non-negative number rounded to one decimal, else None."""
    if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
        return None
    if maximum is not None and number > maximum:
        return None
    return round(float(number), 1)


def _highest(system, key, maximum):
    """The highest known value of a per-GPU field (the busiest or hottest GPU), else None."""
    gpus = system.get('gpus')
    values = [_value(gpu.get(key), maximum) for gpu in gpus if isinstance(gpu, dict)] \
        if isinstance(gpus, list) else []
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _memory_used(memory):
    if not isinstance(memory, dict):
        return None
    total, free = memory.get('total'), memory.get('free')
    if type(total) not in (int, float) or type(free) not in (int, float) or not total > 0 or free < 0 or free > total:
        return None
    return _value(100.0 * (total - free) / total, 100)


def _point(system):
    """One value per series from a collect() result; anything unreadable is None."""
    if not isinstance(system, dict):
        return (None,) * len(SERIES)
    network = system.get('network') if isinstance(system.get('network'), dict) else {}
    return (_value(system.get('cpu_percent'), 100), _highest(system, 'percent', 100),
            _value(system.get('cpu_temp_c'), 150), _highest(system, 'temp_c', 150),
            _memory_used(system.get('memory')), _value(network.get('down_bps')), _value(network.get('up_bps')))


class MetricsHistory:
    """The last `keep` readings, one per `step` seconds, oldest first, safe to share between threads.

    Missed beats become gaps: when add() is called later than a whole step after the previous call
    (a stalled collector, a PC that slept), the missing steps are recorded as unknown so the time
    axis stays honest. Calls close to one step apart (collection time makes a 30 s loop about 33 s)
    are not gaps.
    """

    def __init__(self, step=30, keep=120, clock=time.monotonic):
        self.step = max(1, int(step))
        self.keep = max(1, int(keep))
        self._clock = clock
        self._lock = threading.Lock()
        self._rows = deque(maxlen=self.keep)
        self._last = None

    def add(self, system):
        """Record one collect() result; None, or a result that cannot be read, records a gap."""
        try:
            row = _point(system)
        except Exception:        # a malformed feed must never break the collector's loop
            row = (None,) * len(SERIES)
        now = self._clock()
        with self._lock:
            if self._last is not None:
                for _ in range(min(self.keep, max(0, int(round((now - self._last) / self.step)) - 1))):
                    self._rows.append((None,) * len(SERIES))
            self._last = now
            self._rows.append(row)

    def payload(self):
        """{'step': seconds, <series>: [oldest ... newest]}; all series have the same length."""
        with self._lock:
            rows = list(self._rows)
        result = {'step': self.step}
        for index, name in enumerate(SERIES):
            result[name] = [row[index] for row in rows]
        return result
