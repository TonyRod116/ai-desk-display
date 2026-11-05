"""The real extension code (node) talking to the real bridge (a throwaway server on its own port): the two sides were written and
tested apart, so this is where a field name, a type or a date format that one writes and the other refuses would show.
Claude is a canned answer; nothing leaves the machine and the live monitor's port is never used."""
import contextlib
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from token_tv.claude_bank import EXTENSION_REASONS
from token_tv.live import DisplayPreferences, handler
from token_tv.local_usage import atomic_json, fetch_local
from token_tv.state import UsageStore

ROOT = Path(__file__).resolve().parents[1]
EMAIL = 'demo@example.invalid'
UUID = '11111111-1111-1111-1111-111111111111'
ACCOUNT = {'key': 'claude', 'alias': 'Claude', 'provider': 'claude', 'source_home': '/synthetic/claude', 'email': EMAIL}
SCRIPT = '''
const cfg = JSON.parse(process.env.ROUNDTRIP);
const {collect} = await import(cfg.reader);
const stamp = {Date: new Date(cfg.now * 1000).toUTCString()};
const json = (data, status = 200) => new Response(JSON.stringify(data), {status, headers: stamp});
let accounts = 0;
const transport = async (url, options) => {
  if (url.startsWith('http://127.0.0.1:8787/')) {
    const answer = await fetch(url.replace(':8787', ':' + cfg.port), {...options, headers: {...options.headers, Origin: cfg.origin}});
    return answer;
  }
  if (cfg.network) throw new TypeError('Failed to fetch');
  const path = new URL(url).pathname;
  if (path === '/api/account') {
    accounts += 1;
    return json(cfg.switch && accounts === 2 ? {...cfg.account, uuid: '22222222-2222-2222-2222-222222222222'} : cfg.account);
  }
  if (path.endsWith('/usage')) return cfg.status ? json({}, cfg.status) : json(cfg.usage);
  throw new Error('unexpected request');
};
let outcome;
try { outcome = await collect(cfg.pairing, transport, cfg.version); } catch (error) { outcome = {error: error.message}; }
console.log(JSON.stringify(outcome));
'''


def iso(seconds, microseconds=False):
    stamp = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
    return stamp.isoformat(timespec='microseconds').replace('+00:00', 'Z') if microseconds else stamp.isoformat()


@unittest.skipUnless(shutil.which('node'), 'needs node')
class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.now = int(__import__('time').time())
        self.secret, self.extension = 'a' * 64, 'b' * 32
        owner = hashlib.sha256(EMAIL.encode()).hexdigest()
        self.organization = hashlib.sha256(UUID.encode()).hexdigest()
        atomic_json(self.root/'claude-bank-bridge.json', {'secret': self.secret, 'extension_id': self.extension,
                                                          'account_hash': owner, 'organization_hash': self.organization})
        self.config = {'automatic_claude_resets': True, 'local_only': True, 'accounts': [ACCOUNT]}
        self.preferences = DisplayPreferences(self.root/'config.json', self.config)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(UsageStore([]), self.preferences))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop)
        self.journal = io.StringIO()
        redirect = contextlib.redirect_stdout(self.journal)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.pairing = {'accountHash': owner, 'organization': UUID, 'secret': self.secret}

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def usage(self, bank=True, quota=True, **changes):
        grants = [{'id': 'PRIVATE', 'resets_total': 2, 'resets_left': 1, 'starts_at': self.now - 1000, 'ends_at': self.now + 86400, 'paused': False}]
        data = {'cedar_ember': {'eligible': True, 'grants': grants}} if bank else {'cedar_ember': None}
        if quota:
            data.update(five_hour={'utilization': 12.5, 'resets_at': iso(self.now + 3600, True)},
                        seven_day={'utilization': 40, 'resets_at': iso(self.now + 3 * 86400)})
        return dict(data, **changes)

    def run_extension(self, version='1.1.0', **changes):
        config = dict(reader=(ROOT/'integrations/claude-bank/reader.mjs').as_uri(), port=self.server.server_port,
                      origin='chrome-extension://' + self.extension, now=self.now, pairing=self.pairing, version=version,
                      account={'email_address': EMAIL.title(), 'uuid': UUID}, usage=self.usage())
        config.update(changes)
        done = subprocess.run(['node', '--input-type=module', '-e', SCRIPT], capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, ROUNDTRIP=json.dumps(config)))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def bank(self):
        return self.preferences.snapshot()['saved_resets']['claude']

    def quota_row(self):
        return fetch_local(ACCOUNT, self.root/'offline', official_claude=True)

    def test_a_good_answer_reaches_the_bank_the_reader_state_and_the_quota_backup(self):
        self.assertEqual(self.run_extension(), {'status': 'ok'})
        bank = self.bank()
        self.assertEqual((bank['available'], bank['source']), (1, 'claude_web'))
        reader = bank['reader']
        self.assertEqual((reader['state'], reader['reason'], reader['extension_version'], reader['quota_reason'], reader['rejected']),
                         ('ok', None, '1.1.0', None, 0))
        self.assertIsInstance(reader['last_delivery'], int); self.assertIsInstance(reader['last_quota'], int)
        row = self.quota_row()
        self.assertEqual((row['quota_origin'], row['status'], row['identity_verified'], row['fetched_at']), ('claude_browser', 'ok', True, self.now))
        self.assertEqual([(w['label'], w['used_percent'], w['resets_at']) for w in row['windows']],
                         [('5H', 12.5, self.now + 3600), ('WEEK', 40.0, self.now + 3 * 86400)])
        self.assertEqual(self.journal.getvalue().splitlines(), ['Claude saved-reset reader: start -> ok.'])

    def test_a_bank_the_provider_no_longer_offers_still_delivers_the_quota_and_says_why(self):
        usage = {key: value for key, value in self.usage().items() if key != 'cedar_ember'}
        # Not eligible comes last: it is Claude's answer that the account has no saved resets, so it stays (Tony, 2026-11-03).
        for bank, reason, available, state in (({'cedar_ember': None}, 'not_offered', None, 'failing'), ({}, 'not_offered', None, 'failing'),
                                               ({'cedar_ember': {'eligible': True, 'grants': 'many'}}, 'malformed_inventory', None, 'failing'),
                                               ({'cedar_ember': {'eligible': False, 'grants': []}}, 'not_eligible', 0, 'ok')):
            with self.subTest(bank=bank):
                self.assertEqual(self.run_extension(usage=dict(usage, **bank)), {'error': reason})
                shown = self.bank()
                self.assertEqual((shown['available'], shown['reader']['state'], shown['reader']['reason']), (available, state, reason))
                self.assertIsInstance(shown['reader']['last_quota'], int)
                self.assertEqual((self.quota_row()['quota_origin'], self.quota_row()['windows'][-1]['used_percent']), ('claude_browser', 40.0))
                (self.root/'offline'/'claude-browser.json').unlink()

    def test_a_quota_the_provider_does_not_send_never_costs_the_bank(self):
        self.assertEqual(self.run_extension(usage=self.usage(quota=False)), {'status': 'ok'})
        reader = self.bank()['reader']
        self.assertEqual((self.bank()['available'], reader['state'], reader['quota_reason'], reader['last_quota']), (1, 'ok', 'quota_missing', None))
        self.assertEqual(self.quota_row()['windows'], [])
        self.assertEqual(self.run_extension(usage=self.usage(seven_day={'utilization': 140, 'resets_at': iso(self.now + 3600)})), {'status': 'ok'})
        self.assertEqual((self.bank()['available'], self.bank()['reader']['quota_reason']), (1, 'quota_invalid'))
        self.assertFalse((self.root/'offline'/'claude-browser.json').exists())

    def test_every_failure_the_extension_names_arrives_as_that_reason(self):
        cases = [({'status': 429}, 'rate_limited'), ({'status': 403}, 'access_denied'), ({'status': 401}, 'access_denied'),
                 ({'status': 500}, 'provider_unavailable'), ({'network': True}, 'network_error'),
                 ({'account': {'email_address': 'other@example.invalid', 'uuid': UUID}}, 'wrong_account'),
                 ({'account': {'uuid': UUID}}, 'identity_unavailable'), ({'switch': True}, 'account_changed'),
                 ({'pairing': dict(self.pairing, organization='../attacker')}, 'invalid_pairing')]
        self.assertTrue({reason for _, reason in cases} <= set(EXTENSION_REASONS))
        for changes, reason in cases:
            with self.subTest(reason=reason, changes=sorted(changes)):
                self.assertEqual(self.run_extension(**changes), {'error': reason})
                shown = self.bank()
                self.assertEqual((shown['available'], shown['reader']['state'], shown['reader']['reason']), (None, 'failing', reason))
                self.assertEqual(shown['reader']['extension_version'], '1.1.0')
                self.assertFalse((self.root/'offline'/'claude-browser.json').exists())

    def test_the_wrong_secret_is_counted_as_a_refused_contact_and_no_answer_comes(self):
        outcome = self.run_extension(pairing=dict(self.pairing, secret='0' * 64))
        self.assertEqual(outcome, {'error': 'local_reader_unavailable'})
        reader = self.bank()['reader']
        self.assertEqual((reader['state'], reader['reason'], reader['rejected'], reader['last_contact']), ('failing', 'pairing_rejected', 1, None))
        self.assertEqual(self.run_extension(), {'status': 'ok'})
        self.assertEqual(self.bank()['reader']['state'], 'ok')

    def test_what_goes_over_the_wire_holds_no_account_data(self):
        seen = []
        real = self.preferences.claude_bank.accept
        def spy(data):
            seen.append(json.dumps(data))
            return real(data)
        self.preferences.claude_bank.accept = spy
        self.run_extension()
        self.assertEqual(len(seen), 2)
        for private in (EMAIL, EMAIL.title(), UUID, 'PRIVATE', self.secret):
            self.assertNotIn(private, ''.join(seen))


if __name__ == '__main__':
    unittest.main()
