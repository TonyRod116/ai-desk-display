"""Serve the usage page with fictional readings on localhost, for visual checks. Reads no config and no credentials.

    python3 -B scripts/sample_dashboard.py --port 18791 --scenario normal

`GET /__scenario/<name>` on the same port switches the story without a restart (this script only, never the monitor).
The readings follow the shape the monitor sends: official-cache rows, saved-reset hearts, the reader fields and, when
`token_tv.usage_history` exists, a seeded history so the chart and the forecast have something to show.
"""
import argparse
import inspect
import json
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_tv import live, reset_balances  # noqa: E402
from token_tv.display import STYLES  # noqa: E402

H, D = 3600, 86400
SCENARIOS = ('normal', 'reader_failing', 'bank_failing', 'aged', 'unknown', 'thin', 'runs_out', 'lasts', 'gap', 'two_accounts')


def window(label, used, left, now):
    return {'label': label, 'used_percent': used, 'resets_at': now + left, 'duration_minutes': 300 if label == '5H' else 10080}


def row(key, provider, now, windows, age=40, **extra):
    base = {'key': key, 'alias': key.upper().replace('_', ' '), 'provider': provider, 'status': 'ok', 'identity_verified': True,
            'source': 'local', 'quota_origin': provider + '_official_cli', 'windows': windows,
            'fetched_at': now - age, 'last_success_at': now - age}
    if provider == 'codex':
        base['ordinary_usage_allowed'] = True
    base.update(extra)
    return base


def missing(row_, reader=None):
    """What the monitor sends when a reading is unknown: no windows, no fetch time, the reader's reason when it has one."""
    row_.update(status='quota_unavailable', windows=[], fetched_at=0, last_success_at=0, identity_verified=False, error_code='quota_refresh_overdue')
    if reader:
        row_['reader'] = reader
    return row_


def accounts(scenario, now):
    claude = row('claude_a', 'claude', now, [window('WEEK', 62, 3 * D + 4 * H, now), window('5H', 41, 2 * H + 5 * 60, now)],
                 reader={'state': 'ok', 'reason': None, 'since': now - 3 * H, 'retry_at': None})
    codex = row('codex_a', 'codex', now, [window('WEEK', 35, 5 * D + 2 * H, now)], age=25,
                reader={'state': 'ok', 'reason': None, 'since': now - 5 * H, 'retry_at': None})
    result = [claude, codex]
    if scenario == 'runs_out':
        claude['windows'] = [window('WEEK', 71, 3 * D + 4 * H, now), window('5H', 63, 2 * H + 5 * 60, now)]
    elif scenario == 'reader_failing':
        missing(claude, {'state': 'failing', 'reason': 'login_required', 'since': now - 26 * 60, 'retry_at': now + 45})
    elif scenario == 'aged':
        claude.update(reading_aged=True, fetched_at=now - 5 * 60 - 10, last_success_at=now - 5 * 60 - 10,
                      reader={'state': 'failing', 'reason': 'reader_stuck', 'since': now - 5 * 60, 'retry_at': now + 30})
    elif scenario == 'unknown':
        missing(claude)
        claude.pop('reader', None)
        codex.pop('reader', None)
    elif scenario == 'two_accounts':
        second = row('claude_b', 'claude', now, [window('5H', 88, 3 * H + 41 * 60, now), window('WEEK', 30, 5 * D, now)], age=55)
        result.insert(1, second)
    return result


def display(scenario, now):
    def bank(count, source, **extra):
        return dict({'available': count, 'confirmed_at': now - 20, 'source': source, 'valid_until': now + 10 * D}, **extra)
    claude = bank(2, 'claude_web', reader={'state': 'ok', 'reason': None, 'last_contact': now - 20, 'last_delivery': now - 20, 'extension_version': '1.2'})
    if scenario == 'bank_failing':
        claude = {'available': None, 'confirmed_at': now - 20 * 60, 'source': 'stale', 'last_known': 2,
                  'reader': {'state': 'failing', 'reason': 'wrong_account', 'last_contact': now - 3 * 60, 'last_delivery': now - 20 * 60, 'extension_version': '1.2'}}
    return {'style': 'pixel', 'applied_style': None, 'status': 'preview_only', 'styles': list(STYLES), 'rotation_seconds': 0,
            'automatic_reset_providers': ['codex', 'claude'],
            'saved_resets': {'claude': claude, 'codex': {'available': 1, 'confirmed_at': now - 25, 'source': 'codex_cli'}}}


class Fixture:
    """The store and the preferences of the page, both answered from the current scenario."""
    def __init__(self, scenario):
        self.scenario = scenario
        self.config = {'local_only': True}

    def snapshot(self):  # as the store's: rows built from the current scenario
        now = time.time()
        rows = {a['key']: a for a in accounts(self.scenario, now)}
        return {'schema': 1, 'updated_at': int(now), 'accounts': rows}

    def reset_snapshot(self):
        return display(self.scenario, time.time())['saved_resets']


class Preferences(Fixture):
    def snapshot(self):
        return display(self.scenario, time.time())


# Fictional pace per scenario: (five-hour window, week), in percent of quota used per hour.
PACE = {'normal': (9.0, 0.35), 'runs_out': (28.0, 0.9), 'lasts': (4.0, 0.3), 'gap': (9.0, 0.35), 'aged': (9.0, 0.35), 'bank_failing': (9.0, 0.35),
        'two_accounts': (9.0, 0.35)}


def seed_history(path, scenario, now):
    """Fictional numbers shaped like the monitor's own file: a bit of every story, relative to now."""
    from token_tv.usage_history import UsageHistory
    path.unlink(missing_ok=True)
    book = UsageHistory(path)
    if scenario not in PACE:  # thin, unknown, reader_failing: the history has nothing to say
        return book
    for who in accounts(scenario, now):
        if who['provider'] not in ('claude', 'codex'):
            continue
        for w in who['windows']:
            week = w['label'] == 'WEEK'
            per_hour = PACE[scenario][1 if week else 0]
            window_start = w['resets_at'] - (7 * D if week else 5 * H)
            last_day = now - 24 * H

            def used_at(t):
                if not week or t >= last_day:  # the last day (or the whole five hours) at the scenario's pace
                    return max(0.0, w['used_percent'] - per_hour * (now - t) / H)
                before = w['used_percent'] - per_hour * 24  # earlier days: a slow climb up to where the last day began
                return max(0.0, before * (t - window_start) / max(1.0, last_day - window_start))

            t = now - 20
            while t >= window_start:
                outage = scenario == 'gap' and week and now - 2 * D < t < now - 20 * H
                if not outage:
                    book.write(who['provider'], w['label'], t, round(used_at(t), 1), w['resets_at'])
                t -= 10 * 60 if week else 3 * 60
    return book


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=18791)
    parser.add_argument('--scenario', choices=SCENARIOS, default='normal')
    args = parser.parse_args()
    if args.port == 8787:
        parser.error('8787 is the live monitor')
    store, prefs = Fixture(args.scenario), Preferences(args.scenario)
    directory = tempfile.TemporaryDirectory()
    history_path = Path(directory.name) / 'usage-history.jsonl'
    options = {}
    if 'history' in inspect.signature(live.handler).parameters:
        class Seeded:
            def payload(self, now=None):
                now = time.time() if now is None else now
                return seed_history(history_path, prefs.scenario, now).payload(now)
        options['history'] = Seeded()
    served = live.handler(store, prefs, None, **options)
    class Handler(served):
        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith('/__scenario/') and path[12:] in SCENARIOS:
                store.scenario = prefs.scenario = path[12:]
                self.reply(200, json.dumps({'scenario': prefs.scenario}).encode())
                return
            super().do_GET()
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Sample dashboard (fictional readings) at http://127.0.0.1:{args.port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
