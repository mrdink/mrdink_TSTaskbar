"""Unit tests use only Python's standard library (no GUI required)."""
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tailscale_t_indicator.py'
spec = importlib.util.spec_from_file_location('tailscale_t_indicator', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StatusTests(unittest.TestCase):
    def test_running(self):
        payload = {'BackendState': 'Running', 'Self': {'TailscaleIPs': ['100.90.2.3']}}
        self.assertEqual(module.classify_status(json.dumps(payload)), (True, 'Connected', '100.90.2.3'))

    def test_stopped(self):
        self.assertEqual(module.classify_status('{"BackendState":"Stopped"}'), (False, 'Disconnected', ''))

    def test_needs_login(self):
        self.assertEqual(module.classify_status('{"BackendState":"NeedsLogin"}')[0], False)

    def test_unavailable(self):
        self.assertEqual(module.classify_status('not-json'), (False, 'Status unavailable', ''))

    def test_unrecognized_state(self):
        self.assertEqual(module.classify_status('{"BackendState":"SomeFutureState"}')[0], False)

    def test_toggle_running(self):
        self.assertEqual(module.action_for_status('{"BackendState":"Running"}'), 'down')

    def test_toggle_stopped(self):
        self.assertEqual(module.action_for_status('{"BackendState":"Stopped"}'), 'up')

    def test_toggle_unknown(self):
        for status in ('NeedsLogin', 'Starting', 'NoState', 'SomethingElse'):
            with self.subTest(status=status):
                self.assertIsNone(module.action_for_status(json.dumps({'BackendState': status})))

    def test_toggle_bad_json(self):
        self.assertIsNone(module.action_for_status('broken'))

    def test_not_object(self):
        self.assertEqual(module.classify_status('[]'), (False, 'Status unavailable', ''))

    def test_peer_list_sorted_and_copyable_fields(self):
        payload = {
            'BackendState': 'Running',
            'Self': {'HostName': 'workstation', 'DNSName': 'workstation.example.ts.net.',
                     'TailscaleIPs': ['100.64.0.1', 'fd7a::1']},
            'Peer': {
                'abc': {'HostName': 'z-offline', 'Online': False,
                        'TailscaleIPs': ['100.64.0.3'], 'OS': 'linux'},
                'def': {'DNSName': 'a-online.example.ts.net.', 'Online': True,
                        'TailscaleIPs': ['100.64.0.2', 'fd7a::2'], 'OS': 'windows'}
            }
        }
        local, peers = module.visible_devices(json.dumps(payload))
        self.assertEqual(local['name'], 'workstation')
        self.assertEqual(local['ips'], ['100.64.0.1', 'fd7a::1'])
        self.assertEqual([p['name'] for p in peers], ['a-online', 'z-offline'])
        self.assertEqual(peers[0]['dns'], 'a-online.example.ts.net')
        self.assertIs(peers[0]['online'], True)
        self.assertIs(peers[1]['online'], False)

    def test_peer_list_not_available_when_down(self):
        local, peers = module.visible_devices('{"BackendState":"Stopped","Peer":{"x":{"HostName":"x"}}}')
        self.assertIsNone(local)
        self.assertEqual(peers, [])

    def test_peer_list_missing_or_malformed_fields(self):
        local, peers = module.visible_devices(
            '{"BackendState":"Running","Self":[],"Peer":{"x":{"TailscaleIPs":null,"Online":"yes"}}}'
        )
        self.assertIsNone(local)
        self.assertEqual(peers[0]['ips'], [])
        self.assertIsNone(peers[0]['online'])


if __name__ == '__main__':
    unittest.main()
