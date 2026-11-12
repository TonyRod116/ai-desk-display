"""Read the optional Windows CPU sensor export without elevated privileges.

The separately approved Windows task owns the sensor query. A stale, missing,
partial or invalid export is unknown; it never falls back to a second query.
"""
import json
import math
import os
from pathlib import Path
import stat
import time

DIRECTORY = Path('/mnt/c/ProgramData/AI Desk Display CPU Sensor')
MAX_AGE = 90


def installed():
    try:
        DIRECTORY.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True  # an unreadable installation must not cause a parallel query


def read(now=None):
    now = time.time() if now is None else now
    try:
        if not stat.S_ISDIR(DIRECTORY.lstat().st_mode):
            return None
        fd = os.open(DIRECTORY / 'reading.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 512:
                return None
            raw = stream.read(513)
        if len(raw) > 512:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'version', 'source', 'sampledAt', 'celsius'}:
            return None
        if type(data['version']) is not int or data['version'] != 1 or data['source'] != 'msi-acpi-cpu':
            return None
        stamp, value = data['sampledAt'], data['celsius']
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not -5 <= now - stamp <= MAX_AGE:
            return None
        return value if type(value) is int and 10 <= value <= 110 else None
    except (OSError, ValueError, TypeError):
        return None
