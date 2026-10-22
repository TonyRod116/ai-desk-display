import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from token_tv.claude_bank import ClaudeBankBridge, available_resets
from token_tv.local_usage import atomic_json
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

    def bridge(self, directory):
        account = {'provider': 'claude', 'source_home': '/synthetic/claude', 'email': 'demo@example.invalid'}
        owner = hashlib.sha256(account['email'].encode()).hexdigest()
        settings = {'secret': 'a'*64, 'extension_id': 'b'*32, 'account_hash': owner,
                    'organization_hash': 'c'*64}
        path = Path(directory)/'claude-bank-bridge.json'
        atomic_json(path, settings)
        balances = ResetBalances(Path(directory)/'resets.json', [account])
        return ClaudeBankBridge(path, {'automatic_claude_resets': True, 'local_only': True,
                                     'accounts': [account]}, balances), balances, owner

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
            try:
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
                with self.assertRaises(HTTPError) as caught: urlopen(root+'/health')
                self.assertEqual(caught.exception.code,503)
                with post({'operation':'challenge'}) as response:
                    nonce = json.load(response)['nonce']
                with post(self.observation(nonce,owner)) as response:
                    self.assertEqual(json.load(response)['status'],'ok')
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'],origin)
                self.assertEqual(preferences.snapshot()['automatic_reset_providers'],['claude'])
                self.assertEqual(preferences.reset_snapshot()['claude']['available'],1)
                with self.assertRaises(ValueError): preferences.set_resets('claude',3)
                self.assertEqual(urlopen(root+'/health').status,200)
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
