import unittest
from unittest.mock import patch
from scripts.node_probe import classify_request, extract_transfer_source, make_config, ranking_key, parse_quality, query_quality, classify_gemini, query_gemini
import tempfile
from pathlib import Path


class NodeProbeTests(unittest.TestCase):
    def test_gemini_200_and_unrecognized_markup_do_not_prove_access(self):
        result = {'http_status': 200, 'failure': None}
        for body in (b'Gemini login', b'Gemini 45631641,null,false', b'45631641,null,true'):
            self.assertEqual(classify_gemini(result, body)['state'], 'unknown')
        passed = classify_gemini(result, b'Gemini 45631641,null,true ,2,1,200,"USA"')
        self.assertEqual(passed['state'], 'passed')
        self.assertEqual(passed['observed_region'], 'USA')

    def test_gemini_region_notice_overrides_positive_marker(self):
        result = classify_gemini({'http_status': 200, 'failure': None},
                                b"Gemini isn't currently supported in your country 45631641,null,true")
        self.assertEqual(result['state'], 'region_rejected')
        self.assertNotIn('observed_region', result)

    def test_gemini_transport_failure_and_challenge_are_distinct(self):
        for failure, state in [('timeout', 'network_failed'), ('challenge_page', 'unknown'),
                               ('unexpected_http_status', 'unknown')]:
            self.assertEqual(classify_gemini({'failure': failure}, b'')['state'], state)

    def test_gemini_probe_uses_the_authenticated_node_proxy(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'response.bin').write_bytes(b'Gemini 45631641,null,true')
            with patch('scripts.node_probe.proxy_request', return_value={'http_status': 200, 'failure': None}) as request:
                self.assertEqual(query_gemini(12345, directory)['state'], 'passed')
            self.assertEqual(request.call_args.args, (12345, 'https://gemini.google.com/', directory))

    def test_gemini_pass_precedes_quality_and_unknowns_remain_ranked(self):
        base = {'max_ms': 10, 'success_rate': 1}
        rows = [{**base, 'gemini': {'state': state},
                 'quality': {'state': 'scored', 'quality_score': score}}
                for state, score in [('region_rejected', 100), ('unknown', 99), ('passed', 1)] ]
        self.assertEqual([r['gemini']['state'] for r in sorted(rows, key=ranking_key)],
                         ['passed', 'unknown', 'region_rejected'])

    def test_quality_score_and_exit_are_validated(self):
        result = parse_quality({'ip': '8.8.8.8', 'fraudScore': 12, 'countryCode': 'US', 'asn': 15169})
        self.assertEqual(result['quality_score'], 88)
        self.assertEqual(result['exit_ip'], '8.8.8.8')
        for bad in (None, True, -1, 101, '12'):
            with self.assertRaises(ValueError):
                parse_quality({'ip': '8.8.8.8', 'fraudScore': bad})
        with self.assertRaises(ValueError):
            parse_quality({'ip': '127.0.0.1', 'fraudScore': 0})

    def test_quality_transport_failure_is_unknown_not_low_risk(self):
        with patch('scripts.node_probe.proxy_request', return_value={'failure': 'timeout'}) as request:
            result = query_quality(12345, None)
        self.assertEqual(result['state'], 'unknown')
        self.assertIsNone(result['quality_score'])
        self.assertEqual(request.call_args.args[:2], (12345, 'https://my.ippure.com/v1/info'))

    def test_no_direct_fallback_and_candidate_replaces_only_server(self):
        profile = {'type': 'vless', 'uuid': 'private-test-id', 'tls': {'enabled': True, 'server_name': 'example.com'},
                   'transport': {'type': 'ws', 'path': '/private-test-path', 'headers': {'Host': 'example.com'}}}
        config = make_config(profile, '1.2.3.4', 12345)
        self.assertEqual(len(config['outbounds']), 1)
        outbound = config['outbounds'][0]
        self.assertEqual(outbound['server'], '1.2.3.4')
        self.assertEqual(outbound['tls'], profile['tls'])
        self.assertEqual(outbound['transport'], profile['transport'])
        self.assertEqual(config['route']['final'], outbound['tag'])
        self.assertNotIn('server', profile)

    def test_http_errors_and_challenges_are_not_successes(self):
        self.assertEqual(classify_request(0, 403, 500, 200, None, b'forbidden'), 'unexpected_http_status')
        self.assertEqual(classify_request(0, 200, 500, 200, None, b'<title>Just a moment...</title>'), 'challenge_page')
        self.assertEqual(classify_request(0, 200, 500, 200, b'youtube', b'unrelated page'), 'unexpected_page')
        self.assertEqual(classify_request(28, 200, 500, 200, None, b''), 'timeout')
        self.assertIsNone(classify_request(0, 204, 0, 204, None, b''))

    def test_actual_proxy_timing_overrides_entrance_timing(self):
        fast_entrance = {'max_ms': 1, 'success_rate': 1, 'proxy_max_ms': 2000, 'proxy_median_ms': 1500}
        fast_node = {'max_ms': 200, 'success_rate': 1, 'proxy_max_ms': 500, 'proxy_median_ms': 300}
        self.assertLess(ranking_key(fast_node), ranking_key(fast_entrance))

    def test_transfer_resource_uses_only_fixed_youtube_origin(self):
        self.assertEqual(extract_transfer_source(b'<script src="/s/player/abcd/player_ias.vflset/en_US/base.js">'),
                         'https://www.youtube.com/s/player/abcd/player_ias.vflset/en_US/base.js')
        self.assertIsNone(extract_transfer_source(b'<script src="https://untrusted.example/file.js">'))

    def test_partial_content_is_valid_transfer_status(self):
        self.assertIsNone(classify_request(0, 206, 1048576, (200, 206), None, b'javascript'))


if __name__ == '__main__':
    unittest.main()
