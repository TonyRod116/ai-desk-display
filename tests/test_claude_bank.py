import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from token_tv.claude_bank import EXTENSION_REASONS, LOCAL_REASONS, QUOTA_REASONS, REASONS, ClaudeBankBridge, available_resets
from token_tv.claude_usage import native_record
from token_tv.local_usage import atomic_json, origin_id
from token_tv.reset_balances import ResetBalances


class ClaudeBankTests(unittest.TestCase):
    def grant(self, count=1, **changes):
        return dict(dict(resets_total=max(2, count), resets_left=count, starts_at=1000,
                         ends_at=2000, paused=False), **changes)

    def test_counts_resets_not_grants_or_current_redemption_permission(self):
        one, two = self.grant(2), self.grant(1)
        one['usable_now'] = False
        self.assertEqual(available_resets({'eligible': True, 'grants': [one, two]}, 1500), (3, 2000))
        self.assertEqual(available_resets({'eligible': True, 'grants': []}, 1500), (0, None))
        self.assertEqual(available_resets({'eligible': True, 'grants': [self.grant(0)]}, 1500), (0, None))

    def test_paused_future_expired_and_exhausted_are_not_saved_resets(self):
        grants = [self.grant(), self.grant(0), self.grant()]
        grants[0]['paused'] = True
        grants[2]['ends_at'] = 1500
        future = self.grant(); future['starts_at'] = 1501
        grants.append(future)
        self.assertEqual(available_resets({'eligible': True, 'grants': grants}, 1500), (0, None))

    def test_missing_ineligible_or_malformed_inventory_is_unknown(self):
        for status in (None, {}, {'eligible': False, 'grants': []}, {'eligible': True},
                       {'eligible': True, 'grants': [None]}):
            self.assertIsNone(available_resets(status, 1500))
        for key, value in [('resets_left', True), ('resets_left', -1), ('resets_left', '1'),
                           ('resets_total', 0), ('starts_at', None), ('ends_at', float('inf')),
                           ('ends_at', 500), ('paused', 0)]:
            grant = self.grant(); grant[key] = value
            with self.subTest(key=key, value=value):
                self.assertIsNone(available_resets({'eligible': True, 'grants': [grant]}, 1500))
        self.assertIsNone(available_resets({'eligible': True, 'grants': [self.grant(51)]}, 1500))

    def bridge(self, directory, log=None):
        account = {'provider': 'claude', 'source_home': '/synthetic/claude', 'email': 'demo@example.invalid'}
        owner = hashlib.sha256(account['email'].encode()).hexdigest()
        settings = {'secret': 'a'*64, 'extension_id': 'b'*32, 'account_hash': owner,
                    'organization_hash': 'c'*64}
        path = Path(directory)/'claude-bank-bridge.json'
        atomic_json(path, settings)
        balances = ResetBalances(Path(directory)/'resets.json', [account])
        return ClaudeBankBridge(path, {'automatic_claude_resets': True, 'local_only': True,
                                     'accounts': [account]}, balances, log=log), balances, owner

    def observation(self, nonce, owner, **changes):
        result = {'operation': 'observation', 'nonce': nonce,
                  'identity_before': owner, 'identity_after': owner,
                  'account_before': 'd'*64, 'account_after': 'd'*64,
                  'organization_hash': 'c'*64,
                  'provider_before': 1500, 'provider_at': 1501, 'provider_after': 1502,
                  'inventory': {'eligible': True, 'grants': [self.grant()]}}
        result.update(changes)
        return result

    def test_only_pinned_extension_secret_and_account_can_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            self.assertTrue(bridge.authorized('chrome-extension://'+'b'*32, 'Bearer '+'a'*64))
            for origin, auth in [('https://attacker.invalid','Bearer '+'a'*64),
                                 ('chrome-extension://'+'b'*32,'Bearer wrong'),
                                 (None, 'Bearer '+'a'*64)]:
                self.assertFalse(bridge.authorized(origin, auth))
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                challenge = bridge.accept({'operation': 'challenge'})
                with self.assertRaises(ValueError):
                    bridge.accept(self.observation(challenge['nonce'], owner, identity_after='e'*64))
            self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])

    def test_request_challenge_is_single_use_and_provider_clock_controls_grant_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                challenge = bridge.accept({'operation': 'challenge'})
                body = self.observation(challenge['nonce'], owner)
                bridge.accept(body)
                with self.assertRaises(ValueError): bridge.accept(body)
            with patch('token_tv.reset_balances.time.time', return_value=10001):
                result = balances.snapshot(['claude'], 'c'*64)['claude']
                self.assertEqual(result['available'], 1)
                self.assertEqual(result['source'], 'claude_web')
                self.assertEqual(result['confirmed_at'], 10000)
                self.assertEqual(result['valid_until'], 10000+499)
            with patch('token_tv.reset_balances.time.time', return_value=10181):
                self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])

    def test_old_challenge_cached_bank_and_changed_organization_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            for changes in [{'provider_at': 1400}, {'organization_hash': 'e'*64},
                            {'account_after': 'e'*64}]:
                with patch('token_tv.claude_bank.time.time', return_value=10000):
                    nonce = bridge.accept({'operation':'challenge'})['nonce']
                    with self.assertRaises(ValueError): bridge.accept(self.observation(nonce, owner, **changes))
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                nonce = bridge.accept({'operation':'challenge'})['nonce']
            with patch('token_tv.claude_bank.time.time', return_value=10031):
                with self.assertRaises(ValueError): bridge.accept(self.observation(nonce, owner))

    def test_not_eligible_is_an_answer_with_no_dot_that_survives_failures_and_a_closed_browser(self):
        # Tony, 2026-11-03: "no tengo resets, quitame el puntito de todas partes".
        from token_tv.personal_faces import banked_hearts
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            def answer(now, **changes):
                with patch('token_tv.claude_bank.time.time', return_value=now):
                    nonce = bridge.accept({'operation': 'challenge'})['nonce']
                    body = self.observation(nonce, owner, operation='unavailable', reason='not_eligible', **changes)
                    body.pop('inventory')
                    return bridge.accept(body)
            def seen(now):
                with patch('token_tv.reset_balances.time.time', return_value=now):
                    return balances.snapshot(['claude'], 'c'*64)['claude']
            self.assertEqual(answer(10000)['status'], 'ok')
            zero = seen(10001)
            self.assertEqual((zero['available'], zero['source']), (0, 'claude_not_eligible'))
            self.assertEqual(banked_hearts({'banked_resets': zero}), (0, False))             # three faint icons, no dot
            self.assertEqual(seen(10000 + 30 * 86400)['available'], 0)                       # a month with the browser closed
            with patch('token_tv.claude_bank.time.time', return_value=10100):
                self.assertEqual((bridge.reader_status(True, 10100)['state'], bridge.reader_status(True, 10100)['reason']), ('ok', 'not_eligible'))
                nonce = bridge.accept({'operation': 'challenge'})['nonce']
                bridge.accept({'operation': 'unavailable', 'nonce': nonce, 'reason': 'network_error'})   # signed out, offline...
            self.assertEqual(seen(10101)['source'], 'claude_not_eligible')
            with patch('token_tv.claude_bank.time.time', return_value=10200), patch('token_tv.reset_balances.time.time', return_value=10200):
                nonce = bridge.accept({'operation': 'challenge'})['nonce']
                bridge.accept(self.observation(nonce, owner))                                # Claude grants resets: they show
                self.assertEqual((seen(10200)['available'], seen(10200)['source']), (1, 'claude_web'))
                nonce = bridge.accept({'operation': 'challenge'})['nonce']
                bridge.accept({'operation': 'unavailable', 'nonce': nonce, 'reason': 'network_error'})   # and the normal rules are back
                self.assertIsNone(seen(10200)['available'])

    def test_a_not_eligible_answer_for_another_account_stores_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                nonce = bridge.accept({'operation': 'challenge'})['nonce']
                body = self.observation(nonce, owner, operation='unavailable', reason='not_eligible', identity_after='e'*64)
                self.assertEqual(bridge.accept(body)['status'], 'unknown')
            self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])

    def test_failed_read_removes_an_existing_automatic_balance(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                nonce = bridge.accept({'operation':'challenge'})['nonce']
                bridge.accept(self.observation(nonce, owner))
                nonce = bridge.accept({'operation':'challenge'})['nonce']
                bridge.accept({'operation':'unavailable', 'nonce':nonce})
            self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])

    def test_delayed_failure_cannot_erase_a_new_observation_or_challenge(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                old = bridge.accept({'operation':'challenge'})['nonce']
                current = bridge.accept({'operation':'challenge'})['nonce']
                with self.assertRaises(ValueError):
                    bridge.accept({'operation':'unavailable', 'nonce':old})
                bridge.accept(self.observation(current, owner))
                with self.assertRaises(ValueError):
                    bridge.accept({'operation':'unavailable', 'nonce':old})
                self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)

    def test_expiry_account_and_organization_change_invalidate_existing_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                nonce = bridge.accept({'operation':'challenge'})['nonce']
                bridge.accept(self.observation(nonce, owner, inventory={
                    'eligible':True, 'grants':[self.grant(1, ends_at=1510)]}))
                self.assertIsNone(balances.snapshot(['claude'], 'e'*64)['claude']['available'])
                self.assertIsNone(balances.snapshot(['claude'])['claude']['available'])
            with patch('token_tv.reset_balances.time.time', return_value=10009):
                self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])

    def test_failed_current_identity_check_clears_previous_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                nonce = bridge.accept({'operation':'challenge'})['nonce']
                bridge.accept(self.observation(nonce, owner))
                nonce = bridge.accept({'operation':'challenge'})['nonce']
                with self.assertRaises(ValueError):
                    bridge.accept(self.observation(nonce, owner, identity_after='e'*64))
                self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])

    def test_automatic_source_cannot_be_used_for_another_provider_or_new_account(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, _ = self.bridge(directory)
            bridge.config['accounts'][0]['email'] = 'other@example.invalid'
            self.assertFalse(bridge.authorized('chrome-extension://'+'b'*32, 'Bearer '+'a'*64))
            store = ResetBalances(Path(directory)/'other.json', [{'provider':'codex','source_home':'/demo'}])
            with self.assertRaises(ValueError): store.set_count('codex', 1, source='claude_web')

    def test_repairing_another_account_cannot_relabel_the_running_monitor_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, _ = self.bridge(directory)
            old_origin = balances.origins['claude']
            bridge.config['accounts'][0]['email'] = 'other@example.invalid'
            settings = json.loads(bridge.path.read_text())
            settings['account_hash'] = hashlib.sha256(b'other@example.invalid').hexdigest()
            atomic_json(bridge.path, settings)
            self.assertIsNone(bridge.settings())
            with self.assertRaises(ValueError): bridge.accept({'operation':'challenge'})
            self.assertEqual(balances.origins['claude'],old_origin)

    def test_preparer_rotates_pairing_secret_on_account_or_organization_change(self):
        from scripts.prepare_claude_bank import prepare
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, pin_path = root/'config.json', root/'pin.json'
            config = {'local_only':True, 'automatic_claude_resets':True, 'accounts':[
                {'key':'claude','alias':'Claude','provider':'claude','source_home':'/synthetic/claude',
                 'email':'demo@example.invalid'}]}
            owner = hashlib.sha256(b'demo@example.invalid').hexdigest()
            atomic_json(config_path,config)
            atomic_json(pin_path,{'account_hash':owner,'organization_id':'11111111-1111-1111-1111-111111111111'})
            extension_id = prepare(config_path,pin_path,root/'extension')
            bridge_path = root/'claude-bank-bridge.json'
            original = json.loads(bridge_path.read_text())
            prepare(config_path,pin_path,root/'extension')
            self.assertEqual(json.loads(bridge_path.read_text())['secret'],original['secret'])
            atomic_json(pin_path,{'account_hash':owner,'organization_id':'22222222-2222-2222-2222-222222222222'})
            prepare(config_path,pin_path,root/'extension')
            changed = json.loads(bridge_path.read_text())
            self.assertNotEqual(changed['secret'],original['secret'])
            bank = ResetBalances(root/'resets.json',config['accounts'])
            bridge = ClaudeBankBridge(bridge_path,config,bank)
            self.assertFalse(bridge.authorized('chrome-extension://'+extension_id,'Bearer '+original['secret']))
            self.assertTrue(bridge.authorized('chrome-extension://'+extension_id,'Bearer '+changed['secret']))
            config['accounts'][0]['email'] = 'other@example.invalid'
            atomic_json(config_path,config)
            atomic_json(pin_path,{'account_hash':hashlib.sha256(b'other@example.invalid').hexdigest(),
                                 'organization_id':'22222222-2222-2222-2222-222222222222'})
            prepare(config_path,pin_path,root/'extension')
            self.assertNotEqual(json.loads(bridge_path.read_text())['secret'],changed['secret'])
            self.assertEqual((root/'extension/pairing.js').stat().st_mode & 0o777,0o600)

    # --- why the browser reader has (or has not) delivered (Tony, 2026-11-03) ---
    def quota(self, **changes):
        """What the extension sends: provider times in observation() are 1500-1502, so these resets are in the future."""
        return dict({'five_hour': {'utilization': 12.5, 'resets_at': 1800},
                     'seven_day': {'utilization': 40, 'resets_at': 2000}}, **changes)

    def evidence(self, owner):
        """The identity and date fields an answer carries, whatever it reports."""
        return {k: v for k, v in self.observation('x', owner).items()
                if k.startswith(('identity', 'account', 'organization', 'provider'))}

    def cycle(self, bridge, owner, now, operation='observation', **changes):
        with patch('token_tv.claude_bank.time.time', return_value=now):
            nonce = bridge.accept({'operation': 'challenge'})['nonce']
            if operation == 'observation':
                return bridge.accept(self.observation(nonce, owner, **changes))
            return bridge.accept(dict({'operation': operation, 'nonce': nonce}, **changes))

    def quota_path(self, directory):
        return Path(directory)/'offline'/'claude-browser.json'

    def test_the_extensions_reason_ids_are_the_same_list_in_javascript_and_python(self):
        source = (Path(__file__).resolve().parents[1]/'integrations/claude-bank/reader.mjs').read_text()
        listed = re.findall(r"'([a-z_]+)'", re.search(r'export const REASONS = \[(.*?)\];', source, re.S).group(1))
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(listed), set(EXTENSION_REASONS))
        self.assertFalse(set(EXTENSION_REASONS) & set(LOCAL_REASONS))
        self.assertEqual(set(REASONS), set(EXTENSION_REASONS) | set(LOCAL_REASONS))
        self.assertNotIn('inventory_unavailable', REASONS)
        for ids in (REASONS, QUOTA_REASONS):
            for reason, words in ids.items():
                self.assertRegex(reason, r'^[a-z_]+$')
                self.assertTrue(isinstance(words, str) and words.endswith('.'), reason)

    def test_reader_state_follows_each_answer_and_the_journal_notes_each_change(self):
        with tempfile.TemporaryDirectory() as directory:
            lines = []
            bridge, _, owner = self.bridge(directory, log=lines.append)
            silent = bridge.reader_status(now=10000)
            self.assertEqual((silent['state'], silent['reason'], silent['last_contact'], silent['last_delivery'],
                              silent['extension_version'], silent['rejected']), ('failing', 'no_contact', None, None, None, 0))
            self.cycle(bridge, owner, 10000, version='1.1.0')
            ok = bridge.reader_status(now=10001)
            self.assertEqual((ok['state'], ok['reason'], ok['last_contact'], ok['last_delivery'], ok['extension_version']),
                             ('ok', None, 10000, 10000, '1.1.0'))
            self.cycle(bridge, owner, 10060, 'unavailable', reason='not_offered', version='1.1.0')
            offered = bridge.reader_status(now=10061)
            self.assertEqual((offered['state'], offered['reason'], offered['last_contact'], offered['last_delivery']),
                             ('failing', 'not_offered', 10060, 10000))
            self.assertEqual(offered['since'], 10060)
            self.cycle(bridge, owner, 10120)
            self.assertEqual(bridge.reader_status(now=10121)['reason'], None)
            self.assertEqual(lines, ['Claude saved-reset reader: start -> no_contact.',
                                     'Claude saved-reset reader: no_contact -> ok.',
                                     'Claude saved-reset reader: ok -> not_offered.',
                                     'Claude saved-reset reader: not_offered -> ok.'])
            before = len(lines)
            for now in range(10122, 10130):
                bridge.reader_status(now=now)
            self.assertEqual(len(lines), before, 'only a change is written')

    def test_every_answer_the_extension_can_give_is_recorded_and_anything_else_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            for reason in EXTENSION_REASONS:
                self.cycle(bridge, owner, 10000, 'unavailable', reason=reason)
                self.assertEqual(bridge.reader_status(now=10001)['reason'], reason)
            for bad in ('inventory_unavailable', 'no_contact', 'drop table', '', 'x'*10000, ['not_offered'], {'a': 1}, 7, None, True):
                with self.subTest(reason=bad):
                    self.cycle(bridge, owner, 10000, 'unavailable', reason=bad)
                    status = bridge.reader_status(now=10001)
                    self.assertEqual(status['reason'], 'unknown')
                    self.assertNotIn('x'*100, json.dumps(status))
            self.cycle(bridge, owner, 10000, 'unavailable')   # an extension from before the reasons existed
            status = bridge.reader_status(now=10001)
            self.assertEqual((status['reason'], status['extension_version']), ('unknown', None))

    def test_only_a_plain_version_number_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000, version='1.1.0')
            for bad in ('v1', '1', 'PRIVATE', '1.1.0-beta', '1.'*20, 7, ['1.1.0'], '1.1.0\n'):
                with self.subTest(version=bad):
                    self.cycle(bridge, owner, 10000, version=bad)
                    self.assertEqual(bridge.reader_status(now=10001)['extension_version'], '1.1.0')
            self.cycle(bridge, owner, 10000, version='2.0.3')
            self.assertEqual(bridge.reader_status(now=10001)['extension_version'], '2.0.3')

    def test_silence_is_told_from_a_rate_limit_back_off(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000)
            self.assertEqual(bridge.reader_status(now=10180)['state'], 'ok')
            quiet = bridge.reader_status(now=10181)
            self.assertEqual((quiet['state'], quiet['reason'], quiet['since'], quiet['last_contact']),
                             ('failing', 'no_contact', 10181, 10000))
            self.cycle(bridge, owner, 20000, 'unavailable', reason='rate_limited')
            self.assertEqual(bridge.reader_status(now=20900)['reason'], 'rate_limited')   # it asks again after up to 15 minutes
            self.assertEqual(bridge.reader_status(now=21201)['reason'], 'no_contact')

    def test_a_challenge_that_is_never_answered_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000)
            with patch('token_tv.claude_bank.time.time', return_value=10060):
                bridge.accept({'operation': 'challenge'})
            self.assertIsNone(bridge.reader_status(now=10070)['reason'])            # still within its 30 seconds
            self.assertEqual(bridge.reader_status(now=10091)['reason'], 'unanswered')
            self.cycle(bridge, owner, 10120)
            self.assertEqual(bridge.reader_status(now=10121)['state'], 'ok')

    def test_a_late_answer_to_an_old_challenge_changes_nothing_but_the_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                old = bridge.accept({'operation': 'challenge'})['nonce']
            self.cycle(bridge, owner, 10010)
            with patch('token_tv.claude_bank.time.time', return_value=10020):
                with self.assertRaises(ValueError):
                    bridge.accept({'operation': 'unavailable', 'nonce': old, 'reason': 'timeout'})
            status = bridge.reader_status(now=10021)
            self.assertEqual((status['state'], status['last_contact'], status['last_delivery'], status['rejected']),
                             ('ok', 10020, 10010, 0))
            with patch('token_tv.reset_balances.time.time', return_value=10021):
                self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)

    def test_a_rejected_reading_is_recorded_with_the_reason_it_was_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            for changes, reason in (({'identity_after': 'e'*64}, 'pairing_mismatch'), ({'organization_hash': 'e'*64}, 'pairing_mismatch'),
                                    ({'account_after': 'e'*64}, 'pairing_mismatch'), ({'provider_at': 1400}, 'cached_response'),
                                    ({'provider_after': 1600}, 'cached_response')):
                with self.subTest(changes=changes):
                    with self.assertRaises(ValueError):
                        self.cycle(bridge, owner, 10000, **changes)
                    status = bridge.reader_status(now=10001)
                    self.assertEqual((status['state'], status['reason'], status['last_delivery']), ('failing', reason, None))
            self.cycle(bridge, owner, 10000, inventory={'eligible': True, 'grants': [{'resets_left': 'many'}]})
            self.assertEqual(bridge.reader_status(now=10001)['reason'], 'malformed_inventory')

    def test_a_stale_pairing_is_counted_and_is_not_mistaken_for_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            lines = []
            bridge, _, owner = self.bridge(directory, log=lines.append)
            now = 10000
            with patch('token_tv.claude_bank.time.time', return_value=now):
                self.assertFalse(bridge.authorized('chrome-extension://'+'b'*32, 'Bearer '+'0'*64))     # the secret was rotated
                self.assertFalse(bridge.authorized('chrome-extension://'+'c'*32, 'Bearer '+'a'*64))     # another extension
                self.assertFalse(bridge.origin_allowed('chrome-extension://'+'c'*32))                   # its preflight
                self.assertFalse(bridge.authorized('https://attacker.invalid', 'Bearer '+'a'*64))       # a web page is no extension
                self.assertFalse(bridge.authorized(None, None))
                self.assertFalse(bridge.authorized('chrome-extension://'+'b'*31, 'Bearer '+'a'*64))     # not an extension origin
            status = bridge.reader_status(now=now+1)
            self.assertEqual((status['state'], status['reason'], status['rejected'], status['last_contact']),
                             ('failing', 'pairing_rejected', 3, None))
            self.assertEqual(bridge.reader_status(now=now+181)['reason'], 'no_contact')                 # it stopped knocking
            self.assertEqual(lines, ['Claude saved-reset reader: start -> pairing_rejected.',
                                     'Claude saved-reset reader: pairing_rejected -> no_contact.'])
            with patch('token_tv.claude_bank.time.time', return_value=now+200):
                self.assertFalse(bridge.authorized('chrome-extension://'+'b'*32, 'Bearer '+'0'*64))
            self.assertEqual(bridge.reader_status(now=now+201)['reason'], 'pairing_rejected')
            self.cycle(bridge, owner, now+260)                                                          # paired again
            repaired = bridge.reader_status(now=now+261)
            self.assertEqual((repaired['state'], repaired['rejected']), ('ok', 4))

    def test_a_missing_or_unsafe_pairing_file_is_reported_and_a_disabled_reader_says_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            lines = []
            bridge, _, _ = self.bridge(directory, log=lines.append)
            now = 10000
            os.chmod(bridge.path, 0o644)
            self.assertFalse(bridge.authorized('chrome-extension://'+'b'*32, 'Bearer '+'a'*64))
            self.assertEqual(bridge.reader_status(now=now)['reason'], 'not_paired')
            bridge.path.unlink()
            self.assertEqual(bridge.reader_status(now=now)['reason'], 'not_paired')
            bridge.config['automatic_claude_resets'] = False
            lines.clear()
            self.assertFalse(bridge.authorized('chrome-extension://'+'b'*32, 'Bearer '+'a'*64))
            self.assertIsNone(bridge.reader_status())
            self.assertEqual(lines, [])

    def test_journal_lines_hold_fixed_ids_only(self):
        with tempfile.TemporaryDirectory() as directory:
            lines = []
            bridge, _, owner = self.bridge(directory, log=lines.append)
            with patch('token_tv.claude_bank.time.time', return_value=9990):
                bridge.authorized('chrome-extension://'+'b'*32, 'Bearer '+'0'*64)
            self.cycle(bridge, owner, 10000, 'unavailable', reason='drop table PRIVATE', version='1.1.0')
            self.cycle(bridge, owner, 10060, version='1.1.0')
            self.cycle(bridge, owner, 10120, 'unavailable', reason='timeout')
            bridge.reader_status(now=20000)
            self.assertGreaterEqual(len(lines), 4)
            for line in lines:
                self.assertRegex(line, r'^Claude saved-reset reader: [a-z_]+ -> [a-z_]+\.$')
                for private in ('a'*64, 'b'*32, 'c'*64, 'PRIVATE', 'chrome-extension', 'demo@example', owner):
                    self.assertNotIn(private, line)

    # --- the quota backup travels with the bank, and apart from it ---
    def test_a_good_quota_is_kept_as_a_native_shaped_record_dated_by_the_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000, quota=self.quota(), version='1.1.0')
            path = self.quota_path(directory)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            record = json.loads(path.read_text())
            self.assertEqual(record['source'], 'claude_browser')
            self.assertEqual(record['fetched_at'], 1501, 'the provider date, never the arrival time (10000)')
            self.assertEqual(record['origin'], origin_id('/synthetic/claude', 'demo@example.invalid'))
            self.assertEqual((record['stale'], record['identity_verified']), (False, True))
            self.assertEqual(record['windows'], [
                {'label': '5H', 'used_percent': 12.5, 'resets_at': 1800, 'duration_minutes': 300},
                {'label': 'WEEK', 'used_percent': 40.0, 'resets_at': 2000, 'duration_minutes': 10080}])
            native = native_record({'oauthAccount': {'emailAddress': 'demo@example.invalid', 'accountUuid': 'u'},
                                    'cachedUsageUtilization': {'accountUuid': 'u', 'fetchedAtMs': 1501000, 'utilization': {
                                        'five_hour': {'utilization': 12.5, 'resets_at': '1970-01-01T00:30:00+00:00'},
                                        'seven_day': {'utilization': 40, 'resets_at': '1970-01-01T00:33:20+00:00'}}}},
                                   '/synthetic/claude', 0, now=1501, expected_email='demo@example.invalid')
            self.assertEqual(set(native), set(record), 'the same record shape as the official reader writes')
            self.assertEqual(native['windows'], record['windows'])
            status = bridge.reader_status(now=10001)
            self.assertEqual((status['last_quota'], status['quota_reason']), (10000, None))

    def test_a_bank_failure_does_not_lose_the_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000)                                  # a bank is on the books
            with patch('token_tv.reset_balances.time.time', return_value=10001):
                self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)
            self.cycle(bridge, owner, 10060, 'unavailable', reason='not_offered', quota=self.quota(), **self.evidence(owner))
            with patch('token_tv.reset_balances.time.time', return_value=10061):
                self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])   # the failure still clears the bank
            self.assertEqual(json.loads(self.quota_path(directory).read_text())['windows'][1]['used_percent'], 40.0)
            status = bridge.reader_status(now=10061)
            self.assertEqual((status['reason'], status['last_quota'], status['last_delivery']), ('not_offered', 10060, 10000))

    def test_a_missing_or_bad_quota_does_not_lose_the_bank(self):
        for changes, reason in (({}, None), ({'quota_reason': 'quota_missing'}, 'quota_missing'), ({'quota_reason': 'sudo'}, 'quota_invalid'),
                                ({'quota': self.quota(seven_day={'utilization': 140, 'resets_at': 2000})}, 'quota_invalid'),
                                ({'quota': None}, 'quota_invalid'), ({'quota': 'all of it'}, 'quota_invalid'),
                                ({'quota': {}}, 'quota_invalid')):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                bridge, balances, owner = self.bridge(directory)
                self.cycle(bridge, owner, 10000, **changes)
                with patch('token_tv.reset_balances.time.time', return_value=10001):
                    self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)
                self.assertFalse(self.quota_path(directory).exists())
                status = bridge.reader_status(now=10001)
                self.assertEqual((status['state'], status['quota_reason'], status['last_quota']), ('ok', reason, None))

    def test_an_older_extension_that_sends_no_quota_still_works(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000)
            status = bridge.reader_status(now=10001)
            self.assertEqual((status['state'], status['extension_version'], status['quota_reason'], status['last_quota']),
                             ('ok', None, None, None))
            with patch('token_tv.reset_balances.time.time', return_value=10001):
                self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)

    def test_a_quota_is_strict_and_anything_doubtful_is_no_reading(self):
        nan, inf = float('nan'), float('inf')
        week = {'utilization': 40, 'resets_at': 2000}
        cases = {
            'no week': {'five_hour': week}, 'week not a dict': {'seven_day': 40}, 'extra top key': self.quota(extra_usage=week),
            'extra window key': self.quota(seven_day=dict(week, label='x')), 'missing window key': self.quota(seven_day={'utilization': 40}),
            'percent over': self.quota(seven_day=dict(week, utilization=100.01)), 'percent under': self.quota(seven_day=dict(week, utilization=-0.01)),
            'percent bool': self.quota(seven_day=dict(week, utilization=True)), 'percent string': self.quota(seven_day=dict(week, utilization='40')),
            'percent nan': self.quota(seven_day=dict(week, utilization=nan)), 'percent inf': self.quota(seven_day=dict(week, utilization=inf)),
            'reset passed': self.quota(seven_day=dict(week, resets_at=1501)), 'reset before': self.quota(seven_day=dict(week, resets_at=100)),
            'reset text': self.quota(seven_day=dict(week, resets_at='2026-11-03T00:00:00Z')), 'reset nan': self.quota(seven_day=dict(week, resets_at=nan)),
            'reset none': self.quota(seven_day=dict(week, resets_at=None)),
            'five-hour lapsed': self.quota(five_hour={'utilization': 5, 'resets_at': 1500}),
            'five-hour not a dict': self.quota(five_hour=[1, 2]),
        }
        for name, quota in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                bridge, balances, owner = self.bridge(directory)
                self.cycle(bridge, owner, 10000, quota=quota)
                self.assertFalse(self.quota_path(directory).exists())
                self.assertEqual(bridge.reader_status(now=10001)['quota_reason'], 'quota_invalid')
                with patch('token_tv.reset_balances.time.time', return_value=10001):
                    self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)
        with tempfile.TemporaryDirectory() as directory:   # the limits themselves are fine, and no live five-hour window is not zero
            bridge, _, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000, quota={'five_hour': None, 'seven_day': {'utilization': 100, 'resets_at': 1502}})
            record = json.loads(self.quota_path(directory).read_text())
            self.assertEqual([(w['label'], w['used_percent']) for w in record['windows']], [('WEEK', 100.0)])
            self.cycle(bridge, owner, 10060, quota={'five_hour': {'utilization': 0, 'resets_at': 1800},
                                                    'seven_day': {'utilization': 0, 'resets_at': 2000}})
            record = json.loads(self.quota_path(directory).read_text())
            self.assertEqual([(w['label'], w['used_percent']) for w in record['windows']], [('5H', 0.0), ('WEEK', 0.0)])

    def test_numbers_too_big_for_a_float_are_refused_not_a_crash(self):
        huge = 10**400
        week = {'utilization': 40, 'resets_at': 2000}
        for name, quota in {'percent': self.quota(seven_day=dict(week, utilization=huge)), 'reset': self.quota(seven_day=dict(week, resets_at=huge)),
                            'negative': self.quota(seven_day=dict(week, utilization=-huge)),
                            'a reset years away': self.quota(seven_day=dict(week, resets_at=1501 + 367*86400))}.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                bridge, balances, owner = self.bridge(directory)
                self.cycle(bridge, owner, 10000, quota=quota)
                self.assertFalse(self.quota_path(directory).exists())
                with patch('token_tv.reset_balances.time.time', return_value=10001):
                    self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)
        self.assertIsNone(available_resets({'eligible': True, 'grants': [self.grant(1, ends_at=huge)]}, 1500))
        self.assertIsNone(available_resets({'eligible': True, 'grants': [self.grant(1, starts_at=-huge)]}, 1500))
        self.assertIsNone(available_resets({'eligible': True, 'grants': [self.grant(1)]}, huge))
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            with self.assertRaises(ValueError):
                self.cycle(bridge, owner, 10000, provider_at=huge)
            self.assertEqual(bridge.reader_status(now=10001)['reason'], 'cached_response')

    def test_a_different_identity_organization_or_provider_date_never_produces_a_reading(self):
        for changes in ({'identity_before': 'e'*64}, {'identity_after': 'e'*64}, {'organization_hash': 'e'*64},
                        {'account_after': 'e'*64}, {'account_before': 'nothex'}, {'provider_at': 1400}, {'provider_at': 1600},
                        {'provider_before': 1400, 'provider_at': 1401, 'provider_after': 1450}, {'provider_after': 1499}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                bridge, balances, owner = self.bridge(directory)
                with self.assertRaises(ValueError):
                    self.cycle(bridge, owner, 10000, quota=self.quota(), **changes)
                self.assertFalse(self.quota_path(directory).exists())
                with patch('token_tv.reset_balances.time.time', return_value=10001):
                    self.assertIsNone(balances.snapshot(['claude'], 'c'*64)['claude']['available'])
        for changes in ({'identity_after': 'e'*64}, {'organization_hash': 'e'*64}, {'provider_at': 1400}):   # a failure report is no way in either
            with self.subTest(failure=changes), tempfile.TemporaryDirectory() as directory:
                bridge, _, owner = self.bridge(directory)
                self.cycle(bridge, owner, 10000, 'unavailable', reason='not_offered', quota=self.quota(),
                           **dict(self.evidence(owner), **changes))
                self.assertFalse(self.quota_path(directory).exists())
                self.assertEqual(bridge.reader_status(now=10001)['quota_reason'], 'quota_invalid')

    def test_a_failure_report_carries_a_quota_only_with_its_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            self.cycle(bridge, owner, 10000, 'unavailable', reason='not_offered', quota=self.quota())   # no dates, no identity
            self.assertFalse(self.quota_path(directory).exists())
            self.assertEqual(bridge.reader_status(now=10001)['quota_reason'], 'quota_invalid')

    def test_a_late_failure_cannot_touch_a_newer_quota_and_a_quota_never_goes_back_in_time(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            with patch('token_tv.claude_bank.time.time', return_value=10000):
                old = bridge.accept({'operation': 'challenge'})['nonce']
            self.cycle(bridge, owner, 10010, quota=self.quota())
            kept = self.quota_path(directory).read_bytes()
            with patch('token_tv.claude_bank.time.time', return_value=10020):
                with self.assertRaises(ValueError):
                    bridge.accept(dict(self.evidence(owner), operation='unavailable', nonce=old, reason='timeout',
                                       quota=self.quota(seven_day={'utilization': 1, 'resets_at': 2000})))
            self.assertEqual(self.quota_path(directory).read_bytes(), kept)
            older = dict(provider_before=1400, provider_at=1401, provider_after=1402)    # a reading the provider dated earlier
            self.cycle(bridge, owner, 10030, quota=self.quota(seven_day={'utilization': 1, 'resets_at': 2000}), **older)
            self.assertEqual(self.quota_path(directory).read_bytes(), kept)
            newer = dict(provider_before=1600, provider_at=1601, provider_after=1602)
            self.cycle(bridge, owner, 10040, quota=self.quota(seven_day={'utilization': 2, 'resets_at': 2000}), **newer)
            record = json.loads(self.quota_path(directory).read_text())
            self.assertEqual((record['fetched_at'], record['windows'][1]['used_percent']), (1601, 2.0))

    def test_an_unwritable_quota_never_costs_the_bank(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, balances, owner = self.bridge(directory)
            (Path(directory)/'offline').write_text('a file where the folder should be')
            self.cycle(bridge, owner, 10000, quota=self.quota())
            with patch('token_tv.reset_balances.time.time', return_value=10001):
                self.assertEqual(balances.snapshot(['claude'], 'c'*64)['claude']['available'], 1)
            self.assertEqual(bridge.reader_status(now=10001)['quota_reason'], 'quota_invalid')

    def test_only_paired_ingress_has_cors_and_bank_is_in_health_and_preferences(self):
        from token_tv.live import DisplayPreferences, handler
        from token_tv.state import UsageStore
        with tempfile.TemporaryDirectory() as directory:
            bridge, _, owner = self.bridge(directory)
            preferences = DisplayPreferences(Path(directory)/'config.json', bridge.config)
            server = ThreadingHTTPServer(('127.0.0.1',0), handler(UsageStore([]), preferences))
            thread = threading.Thread(target=server.serve_forever); thread.start()
            root = f'http://127.0.0.1:{server.server_port}'
            origin = 'chrome-extension://'+'b'*32
            headers = {'Origin':origin, 'Authorization':'Bearer '+'a'*64, 'Content-Type':'application/json'}
            def post(body, extra=None):
                return urlopen(Request(root+'/display/claude-bank',data=json.dumps(body).encode(),headers=dict(headers,**(extra or {}))))
            journal = io.StringIO()   # the monitor's lines for the service log, written by the server's own thread
            try:
              with contextlib.redirect_stdout(journal):
                for extra in [{'Origin':'https://attacker.invalid'},{'Authorization':'wrong'},{'Host':'attacker.invalid'}, {'Origin':''}]:
                    with self.assertRaises(HTTPError) as caught: post({'operation':'challenge'},extra)
                    self.assertEqual(caught.exception.code,403)
                preflight = {'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'Authorization, Content-Type'}
                with urlopen(Request(root+'/display/claude-bank',method='OPTIONS',headers=preflight)) as response:
                    self.assertEqual(response.status,204)
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'],origin)
                for path in ['/snapshot','/display/style']:
                    with self.assertRaises(HTTPError): urlopen(Request(root+path,method='OPTIONS',headers=preflight))
                with urlopen(root+'/snapshot') as response:
                    self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
                # Tony, 2026-11-03: an unknown bank is a warning on /health, no longer a 503 (the quota is what makes it degraded).
                with urlopen(root+'/health') as response:
                    self.assertEqual(response.status,200)
                    self.assertEqual(json.load(response)['warnings'],['claude_saved_resets_unknown'])
                with post({'operation':'challenge'}) as response:
                    nonce = json.load(response)['nonce']
                with post(self.observation(nonce,owner,version='1.1.0',quota=self.quota())) as response:
                    self.assertEqual(json.load(response)['status'],'ok')
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'],origin)
                self.assertEqual(preferences.snapshot()['automatic_reset_providers'],['claude'])
                self.assertEqual(preferences.reset_snapshot()['claude']['available'],1)
                with self.assertRaises(ValueError): preferences.set_resets('claude',3)
                with urlopen(root+'/health') as response:
                    self.assertEqual((response.status,json.load(response)['warnings']),(200,[]))
                with urlopen(root+'/display') as response:   # the dashboard's own view of the browser reader
                    saved = json.load(response)['saved_resets']
                reader = saved['claude']['reader']
                self.assertEqual((reader['state'], reader['reason'], reader['extension_version'], reader['rejected']), ('ok', None, '1.1.0', 1))
                for key in ('last_contact', 'last_delivery', 'last_quota', 'since'): self.assertIsInstance(reader[key], int, key)
                self.assertNotIn('reader', saved['codex'])
                self.assertTrue(self.quota_path(directory).is_file())
            finally:
                server.shutdown(); server.server_close(); thread.join()
            self.assertEqual(journal.getvalue().splitlines(), ['Claude saved-reset reader: start -> pairing_rejected.',
                                                              'Claude saved-reset reader: pairing_rejected -> ok.'])


if __name__ == '__main__':
    unittest.main()
