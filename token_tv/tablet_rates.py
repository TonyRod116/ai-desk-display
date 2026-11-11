"""Quantities that need two readings: the CPU and GPU share of each program, and network speed.

The Windows script reports cumulative counters (CPU time, GPU engine time, bytes). A rate is the
difference between this reading and the previous one divided by the time between them, so the
previous readings are kept here, in memory only. Until a usable previous reading exists (the first
call, a gap longer than MAX_WINDOW, a clock that went backwards) the rates are unknown: None, never
a made-up zero.

Privacy: a program is only ever a name. Process ids are used inside one reading to tell two
programs of the same name apart and are never returned; neither are command lines, paths or users
(the script does not even collect them).
"""
import math
import re
import threading

MIN_WINDOW = 5.0        # seconds; two readings closer than this are too noisy to rank anything
MAX_WINDOW = 180.0      # seconds; an older previous reading no longer describes "now"
NAME_LIMIT = 24
CPU_TOP = 6
MEMORY_TOP = 6
GPU_TOP = 4
MAX_ROWS = 20000
MAX_BPS = 4e11          # 400 Gbit/s: anything above is a broken counter, not traffic
SKEW = 1.05             # readings are taken a fraction of a second apart: 5 % above the possible is noise
_MIB = 1024 * 1024
_TICKS = 1e7            # Windows counts CPU and GPU time in 100 ns units
# Not programs: the idle placeholder, kernel bookkeeping, and the compressed-memory store.
_SKIPPED = frozenset(('idle', 'system idle process', 'system', 'registry', 'memory compression',
                      'memcompression', 'secure system', '_total'))
_GPU_INSTANCE = re.compile(r'pid_(\d{1,10})_luid_(0x[0-9A-Fa-f]{1,8}_0x[0-9A-Fa-f]{1,8})'
                           r'_phys_\d{1,3}_eng_\d{1,4}_engtype_([A-Za-z0-9_ ]{1,32})')


def _number(value, minimum=0, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        return None
    return value if maximum is None or value <= maximum else None


def _seconds(ticks, frequency):
    ticks, frequency = _number(ticks), _number(frequency, 1)
    return None if ticks is None or frequency is None else ticks / frequency


def clean_name(value):
    """A program's display name: no '.exe', printable characters only, at most NAME_LIMIT long."""
    if not isinstance(value, str):
        return None
    name = ''.join(c for c in value if c.isprintable()).strip()
    if name[-4:].lower() == '.exe':
        name = name[:-4].rstrip()
    return name[:NAME_LIMIT].rstrip() or None


def parse_processes(raw):
    """Validate the script's process block into one reading, or None if it is not usable.

    Raw rows are [name, pid, cpu 100 ns ticks or null, working set bytes or null].
    """
    if not isinstance(raw, dict) or not isinstance(raw.get('p'), list) or len(raw['p']) > MAX_ROWS:
        return None
    moment, cpus = _seconds(raw.get('t'), raw.get('f')), _number(raw.get('n'), 1, 1024)
    if moment is None or cpus is None:
        return None
    rows = {}
    for row in raw['p']:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            continue
        name, pid = clean_name(row[0]), _number(row[1])
        if name is None or pid is None or name.casefold() in _SKIPPED:
            continue
        cpu, working_set = _number(row[2]), _number(row[3])
        rows[(int(pid), name.casefold())] = (name, None if cpu is None else cpu / _TICKS, working_set)
    return {'t': moment, 'cpus': int(cpus), 'rows': rows} if rows else None


def parse_gpu(raw):
    """Validate the script's GPU engine block, or None. Raw rows are [instance name, running ticks]."""
    if not isinstance(raw, dict) or not isinstance(raw.get('p'), list) or len(raw['p']) > MAX_ROWS:
        return None
    moment = _number(raw.get('t'), 1)
    if moment is None:
        return None
    instances = {}
    for row in raw['p']:
        if not isinstance(row, (list, tuple)) or len(row) != 2 or not isinstance(row[0], str):
            continue
        match, ticks = _GPU_INSTANCE.fullmatch(row[0]), _number(row[1])
        if match and ticks is not None:
            instances[row[0]] = (int(match[1]), match[2].lower(), match[3].lower(), ticks)
    return {'t': moment / _TICKS, 'instances': instances} if instances else None


def parse_network(raw):
    """Validate the script's adapter block, or None. Raw rows are [adapter id, bytes in, bytes out]."""
    if not isinstance(raw, dict) or not isinstance(raw.get('a'), list) or len(raw['a']) > 256:
        return None
    moment = _seconds(raw.get('t'), raw.get('f'))
    if moment is None:
        return None
    adapters = {}
    for row in raw['a']:
        if not isinstance(row, (list, tuple)) or len(row) != 3 or not isinstance(row[0], str):
            continue
        received, sent = _number(row[1]), _number(row[2])
        if received is not None and sent is not None:
            adapters[row[0][:80]] = (received, sent)
    return {'t': moment, 'adapters': adapters}


def advance(previous, sample):
    """Pick the baseline to measure against and the reading to remember: (baseline, new previous)."""
    if previous is None:
        return None, sample
    window = sample['t'] - previous['t']
    if window <= 0 or window > MAX_WINDOW:
        return None, sample          # a reboot, a clock change or a long gap: start again
    if window < MIN_WINDOW:
        return None, previous        # too close: keep the older baseline for the next reading
    return previous, sample


def _grow(table, key, amount):
    table[key] = table.get(key, 0) + amount


def _used(before, now):
    """Counter growth between two readings of the same counter; a smaller value means it restarted."""
    if before is None or now < before:
        return now                   # new counter, or the same id reused by a new program
    return now - before


def _processes_by_name(sample):
    names = {}
    for (pid, key), (name, _cpu, _working_set) in sample['rows'].items():
        names[pid] = (key, name)
    return names


def _top_memory(sample):
    totals, shown = {}, {}
    for (_pid, key), (name, _cpu, working_set) in sample['rows'].items():
        if working_set is not None:
            _grow(totals, key, working_set)
            shown.setdefault(key, name)
    ranked = sorted(totals, key=lambda key: (-totals[key], shown[key].casefold()))[:MEMORY_TOP]
    return [{'name': shown[key], 'mem_mb': int(round(totals[key] / _MIB))} for key in ranked]


def _top_cpu(baseline, sample):
    window = sample['t'] - baseline['t']
    capacity = window * sample['cpus']
    seconds, shown, memory = {}, {}, {}
    for (pid, key), (name, cpu, working_set) in sample['rows'].items():
        shown.setdefault(key, name)
        if working_set is not None:
            _grow(memory, key, working_set)
        if cpu is None:
            continue
        old = baseline['rows'].get((pid, key))
        if old is not None and old[1] is None:
            continue                 # its CPU time was unreadable before: no difference to take
        used = _used(None if old is None else old[1], cpu)
        if used > capacity * SKEW:
            continue                 # more than the whole machine could give in this window: not new after all
        _grow(seconds, key, used)
    percents = {key: min(100.0, 100.0 * used / capacity) for key, used in seconds.items()}
    ranked = [key for key in sorted(percents, key=lambda key: (-percents[key], shown[key].casefold()))
              if round(percents[key], 1) > 0][:CPU_TOP]
    return [{'name': shown[key], 'percent': round(percents[key], 1),
             'mem_mb': int(round(memory[key] / _MIB)) if key in memory else None} for key in ranked]


def _top_gpu(baseline, sample, names):
    window = sample['t'] - baseline['t']
    engine = {}
    for instance, (pid, luid, kind, ticks) in sample['instances'].items():
        old = baseline['instances'].get(instance)
        used = _used(None if old is None else old[3], ticks)
        if used <= window * _TICKS * SKEW:       # an engine cannot be busy longer than the window
            _grow(engine, (pid, luid, kind), used)
    # A program uses a GPU as much as its busiest engine (3D, compute...), as Task Manager counts it.
    busiest = {}
    for (pid, luid, _kind), used in engine.items():
        busiest[(pid, luid)] = max(busiest.get((pid, luid), 0), used)
    per_adapter, shown = {}, {}
    for (pid, luid), used in busiest.items():
        if pid in names:
            key, name = names[pid]
            _grow(per_adapter, (key, luid), used)
            shown.setdefault(key, name)
    percents = {}
    for (key, _luid), used in per_adapter.items():
        percents[key] = max(percents.get(key, 0.0), min(100.0, 100.0 * used / (window * _TICKS)))
    ranked = [key for key in sorted(percents, key=lambda key: (-percents[key], shown[key].casefold()))
              if round(percents[key], 1) > 0][:GPU_TOP]
    return [{'name': shown[key], 'percent': round(percents[key], 1)} for key in ranked]


def _top_network(baseline, sample):
    window = sample['t'] - baseline['t']
    received = sent = 0
    seen = False
    for adapter, (now_in, now_out) in sample['adapters'].items():
        old = baseline['adapters'].get(adapter)
        if old is None or now_in < old[0] or now_out < old[1]:
            continue                 # new, restarted or wrapped adapter: its difference is unknown
        received, sent, seen = received + now_in - old[0], sent + now_out - old[1], True
    if not seen:
        return {'down_bps': None, 'up_bps': None}
    down, up = received * 8 / window, sent * 8 / window
    if down > MAX_BPS or up > MAX_BPS:
        return {'down_bps': None, 'up_bps': None}
    return {'down_bps': int(round(down)), 'up_bps': int(round(up))}


class RateTracker:
    """Keeps the previous readings and turns each new one into the shares and speeds."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._processes = self._gpu = self._network = None

    def update(self, data):
        """Return (processes, network) for the decoded script output; None where nothing was read.

        processes: {'cpu': [...] or None, 'memory': [...], 'gpu': [...] or None}.
        network: {'down_bps', 'up_bps'}, both None while no speed can be told.
        """
        data = data if isinstance(data, dict) else {}
        with self._lock:
            return self._update_processes(data), self._update_network(data)

    def _update_processes(self, data):
        sample = parse_processes(data.get('pr'))
        if sample is None:
            return None
        baseline, self._processes = advance(self._processes, sample)
        return {'cpu': None if baseline is None else _top_cpu(baseline, sample),
                'memory': _top_memory(sample),
                'gpu': self._update_gpu(parse_gpu(data.get('gp')), sample)}

    def _update_gpu(self, sample, processes):
        if sample is None:
            return None
        baseline, self._gpu = advance(self._gpu, sample)
        if baseline is None:
            return None
        return _top_gpu(baseline, sample, _processes_by_name(processes))

    def _update_network(self, data):
        sample = parse_network(data.get('net'))
        if sample is None:
            return None
        baseline, self._network = advance(self._network, sample)
        if baseline is None:
            return {'down_bps': None, 'up_bps': None}
        return _top_network(baseline, sample)
