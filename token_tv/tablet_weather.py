"""Outside weather for the tablet page: one small reading, fetched by this PC and shown beside the clock.

Optional weather is disabled by default. When enabled, this is what the tablet service asks of the internet:

- WHO: Open-Meteo's public forecast endpoint (`api.open-meteo.com`, no account, no key), over HTTPS with the system's certificates, from this PC, never
  from the tablet. No redirects are followed, a response is read up to 16 KiB and every field is checked before it is kept.
- WHAT LEAVES THE COMPUTER: the place from the tablet's own settings (`place`, Barcelona until changed) ROUNDED TO 0.1 DEGREE (about 11 km),
  the three variables asked for and the ordinary connection data. No name, no account, no quota, no scene, no hostname of this PC. The client name
  is generic.
- HOW OFTEN: every 20 minutes (5 minutes after a failure), and at once when the place or the switch changes. A reading older than 90 minutes is
  unknown, never shown: unknown is never a number.
- WHAT THE PAGE GETS: `{temp, code, day, age}` through `/api/weather`; the page draws an icon and words from the WMO `code`.

The switch `weather.enabled` in the tablet's settings turns the whole thing off (then nothing is requested at all).
"""
from __future__ import annotations

import http.client
import json
import math
import ssl
import sys
import threading
import time
import urllib.parse

HOST = 'api.open-meteo.com'
PATH = '/v1/forecast'
VARIABLES = 'temperature_2m,weather_code,is_day'
CLIENT = 'ai-desk-display-tablet'
MAX_BODY = 16 * 1024
INTERVAL = 20 * 60              # seconds between readings
RETRY = 5 * 60                  # seconds before trying again after a failure
FRESH = 90 * 60                 # a reading older than this is unknown
WATCH = 15                      # seconds between looks at the settings
TIMEOUT = 8
# The WMO weather codes Open-Meteo documents; anything else is refused.
CODES = frozenset((0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def parse(body):
    """The reading in a response body, `{'temp': int, 'code': int, 'day': bool}`, or None when anything is missing or out of range."""
    try:
        data = json.loads(body)
        current = data['current']
        temp, code, day = current['temperature_2m'], current['weather_code'], current['is_day']
    except (ValueError, UnicodeError, KeyError, TypeError):
        return None
    if not _number(temp) or not -60 <= temp <= 60 or type(code) is not int or code not in CODES or type(day) is not int or day not in (0, 1):
        return None
    return {'temp': int(round(temp)), 'code': code, 'day': bool(day)}


def coarse(lat, lon):
    """The place as it leaves the computer: rounded to 0.1 degree."""
    return round(float(lat), 1) + 0.0, round(float(lon), 1) + 0.0


def fetch(lat, lon, timeout=TIMEOUT, connect=http.client.HTTPSConnection):
    """One request to Open-Meteo for the (coarse) place. Returns the checked reading or None; never raises for a network or format problem."""
    lat, lon = coarse(lat, lon)
    query = urllib.parse.urlencode({'latitude': f'{lat:.1f}', 'longitude': f'{lon:.1f}', 'current': VARIABLES, 'timezone': 'auto', 'forecast_days': 1})
    connection = None
    try:
        connection = connect(HOST, timeout=timeout, context=ssl.create_default_context())
        connection.request('GET', f'{PATH}?{query}', headers={'User-Agent': CLIENT, 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            return None
        body = response.read(MAX_BODY + 1)
        return parse(body) if len(body) <= MAX_BODY else None
    except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


class Weather:
    """The latest outside reading for the page. `settings` is the tablet's `Settings`; `fetch` takes (lat, lon) and returns a reading or None."""

    def __init__(self, settings, fetch=fetch, *, interval=INTERVAL, retry=RETRY, fresh=FRESH, watch=WATCH, clock=time.monotonic, log=None):
        self.settings, self.fetch = settings, fetch
        self.interval, self.retry, self.fresh, self.watch, self.clock = interval, retry, fresh, watch, clock
        self.log = log or (lambda text: print(text, file=sys.stderr, flush=True))
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.reading, self.at, self.key = None, 0.0, None      # key = (lat, lon) of the reading, rounded
        self.asked = False                                      # what the last attempt was for (False = nothing yet), so a failure is retried on the slow clock
        self.failing = False

    def _wanted(self):
        """(lat, lon) to ask for, or None when the switch is off."""
        value = self.settings.get()
        if not value.get('weather', {}).get('enabled'):
            return None
        place = value['place']
        return coarse(place['lat'], place['lon'])

    def refresh(self):
        """Look at the settings and ask once if needed. Returns the seconds to wait before the next attempt."""
        wanted = self._wanted()
        self.asked = wanted
        if wanted is None:
            with self.lock:
                self.reading, self.key = None, None
            return self.watch
        try:
            reading = self.fetch(*wanted)
        except Exception:                               # a custom fetcher must never kill the thread
            reading = None
        with self.lock:
            if reading is not None:
                self.reading, self.at, self.key = reading, self.clock(), wanted
        if (reading is None) != self.failing:
            self.failing = reading is None
            self.log('tablet: weather unavailable (kept as unknown)' if self.failing else 'tablet: weather available again')
        return self.interval if reading is not None else self.retry

    def _loop(self):
        due = 0.0
        while not self.stop.is_set():
            wanted = self._wanted()
            if wanted != self.asked or self.clock() >= due:
                due = self.clock() + self.refresh()
            self.stop.wait(self.watch)

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def status(self):
        """`{'temp', 'code', 'day', 'age'}` for a fresh reading of the place now set, else None (the page then shows nothing)."""
        wanted = self._wanted()
        with self.lock:
            if wanted is None or self.reading is None or self.key != wanted:
                return None
            age = self.clock() - self.at
            if age > self.fresh:
                return None
            return {**self.reading, 'age': int(age)}
