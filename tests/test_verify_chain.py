import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

from scripts.verify_chain import (
    parse_trace,
    verify_general_egress,
    verify_gemini_egress,
    verify_node_chain,
)


class VerifyChainTests(unittest.TestCase):
    def test_parse_trace_success(self):
        text = "fl=123f1\nh=speed.cloudflare.com\nip=104.28.167.95\nts=1697280000\ncolo=DFW\nloc=US\n"
        data = parse_trace(text)
        self.assertEqual(data.get('ip'), '104.28.167.95')
        self.assertEqual(data.get('colo'), 'DFW')
        self.assertEqual(data.get('loc'), 'US')

    def test_parse_trace_empty_and_malformed(self):
        self.assertEqual(parse_trace(''), {})
        self.assertEqual(parse_trace('invalid_lines_without_equals'), {})

    def test_verify_general_egress_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'response.bin').write_text('{"ip": "1.2.3.4"}')
            with patch('scripts.verify_chain.proxy_request', return_value={'http_status': 200, 'duration_ms': 50.0, 'failure': None}):
                res = verify_general_egress(1080, directory)
                self.assertEqual(res['status'], 'passed')
                self.assertEqual(res['egress_ip'], '1.2.3.4')

    def test_verify_general_egress_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch('scripts.verify_chain.proxy_request', return_value={'http_status': 500, 'duration_ms': 0, 'failure': 'timeout'}):
                res = verify_general_egress(1080, directory)
                self.assertEqual(res['status'], 'failed')
                self.assertEqual(res['failure'], 'timeout')

    def test_verify_gemini_egress_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'response.bin').write_bytes(b'<!DOCTYPE html><html><body>Gemini Welcome</body></html>')
            with patch('scripts.verify_chain.proxy_request', return_value={'http_status': 200, 'duration_ms': 80.0, 'failure': None}):
                res = verify_gemini_egress(1080, directory)
                self.assertEqual(res['status'], 'passed')
                self.assertEqual(res['reason'], 'accessible')

    def test_verify_gemini_egress_region_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'response.bin').write_bytes(b"Gemini isn't currently supported in your country")
            with patch('scripts.verify_chain.proxy_request', return_value={'http_status': 200, 'duration_ms': 80.0, 'failure': None}):
                res = verify_gemini_egress(1080, directory)
                self.assertEqual(res['status'], 'region_rejected')
                self.assertEqual(res['reason'], 'explicit_region_notice')

    def test_verify_gemini_egress_challenge_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'response.bin').write_bytes(b'<title>Sorry... Google</title><form action="recaptcha">')
            with patch('scripts.verify_chain.proxy_request', return_value={'http_status': 200, 'duration_ms': 80.0, 'failure': None}):
                res = verify_gemini_egress(1080, directory)
                self.assertEqual(res['status'], 'blocked')
                self.assertEqual(res['reason'], 'bot_or_captcha_challenge')

    def test_verify_gemini_egress_transport_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch('scripts.verify_chain.proxy_request', return_value={'http_status': 0, 'duration_ms': 0, 'failure': 'timeout'}):
                res = verify_gemini_egress(1080, directory)
                self.assertEqual(res['status'], 'failed')
                self.assertEqual(res['reason'], 'timeout')


if __name__ == '__main__':
    unittest.main()
