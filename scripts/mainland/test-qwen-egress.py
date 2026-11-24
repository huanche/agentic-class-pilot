import importlib.machinery
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('qwen_egress', str(Path(__file__).with_name('agentic-qwen-egress')))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class EgressTest(unittest.TestCase):
    def network(self, **updates):
        return {'Internal': True, 'Id': 'a' * 64,
                'IPAM': {'Config': [{'Gateway': '172.19.0.1'}]},
                'Options': {}, 'Containers': {}, **updates}

    def test_keeps_tls_encrypted_and_destination_fixed(self):
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps([self.network()])), \
             patch.object(module.subprocess, 'run') as address, patch.object(module.os, 'execv') as execute:
            module.main()
            address.assert_called_once_with(['/usr/sbin/ip', 'address', 'replace',
                '172.19.255.254/32', 'dev', 'br-' + 'a' * 12], check=True)
            execute.assert_called_once_with('/usr/bin/socat', ['socat',
                'TCP4-LISTEN:443,bind=172.19.255.254,reuseaddr,fork,range=172.19.0.0/16',
                'TCP4:dashscope.aliyuncs.com:443'])

    def test_refuses_external_or_changed_networks(self):
        for n in [self.network(Internal=False), self.network(IPAM={'Config': [{'Gateway': '10.0.0.1'}]})]:
            with self.subTest(network=n), patch.object(module.subprocess, 'check_output', return_value=json.dumps([n])), \
                 patch.object(module.subprocess, 'run') as address, patch.object(module.os, 'execv') as execute:
                with self.assertRaises(RuntimeError): module.main()
                address.assert_not_called()
                execute.assert_not_called()

    def test_refuses_an_allocated_host_address(self):
        n = self.network(Containers={'id': {'IPv4Address': '172.19.255.254/16'}})
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps([n])), \
             patch.object(module.subprocess, 'run') as address:
            with self.assertRaisesRegex(RuntimeError, 'allocated'): module.main()
            address.assert_not_called()

    def test_refuses_unexpected_bridge_names(self):
        n = self.network(Options={'com.docker.network.bridge.name': '../../wrong'})
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps([n])), \
             patch.object(module.subprocess, 'run') as address:
            with self.assertRaisesRegex(RuntimeError, 'bridge name'): module.main()
            address.assert_not_called()


if __name__ == '__main__':
    unittest.main()
