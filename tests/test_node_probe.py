import unittest
from scripts.node_probe import classify_request, make_config, ranking_key


class NodeProbeTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
