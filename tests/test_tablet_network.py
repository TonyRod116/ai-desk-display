import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from token_tv import tablet_server


class InterfaceAddressTests(unittest.TestCase):
    def probe(self, addresses):
        info = [{'addr_info': addresses}]
        return SimpleNamespace(stdout=json.dumps(info))

    @patch('token_tv.tablet_server.subprocess.run')
    def test_selects_private_ipv4_for_the_chosen_interface(self, run):
        run.return_value = self.probe([
            {'family': 'inet', 'scope': 'link', 'local': '169.254.1.2'},
            {'family': 'inet', 'scope': 'global', 'local': '192.168.1.42'},
            {'family': 'inet6', 'scope': 'global', 'local': '2001:db8::1'},
        ])
        self.assertEqual(tablet_server.interface_address('eth2'), '192.168.1.42')
        self.assertEqual(run.call_args.args[0], ['ip', '-j', '-4', 'addr', 'show', 'dev', 'eth2'])

    @patch('token_tv.tablet_server.subprocess.run')
    def test_rejects_missing_or_ambiguous_private_addresses(self, run):
        run.return_value = self.probe([{'family': 'inet', 'scope': 'global', 'local': '8.8.8.8'}])
        with self.assertRaises(ValueError):
            tablet_server.interface_address('eth2')
        run.return_value = self.probe([
            {'family': 'inet', 'scope': 'global', 'local': '192.168.1.20'},
            {'family': 'inet', 'scope': 'global', 'local': '192.168.1.21'},
        ])
        with self.assertRaises(ValueError):
            tablet_server.interface_address('eth2')

    @patch('token_tv.tablet_server.subprocess.run')
    def test_rejects_interface_names_that_could_be_options(self, run):
        for name in ('-bad', 'eth2;command', '', 'x' * 16):
            with self.subTest(name=name), self.assertRaises(ValueError):
                tablet_server.interface_address(name)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
