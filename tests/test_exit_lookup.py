import copy
import unittest
from unittest.mock import patch
from scripts.exit_lookup import cross_check_exits, parse_location, lookup_exit
from scripts.update import select_best


class ExitLookupTests(unittest.TestCase):
    def test_validated_response_and_public_proxy_scope(self):
        result = parse_location({'ip': '8.8.8.8', 'country_code': 'US', 'asn': '15169', 'is_proxy': False}, '8.8.8.8')
        self.assertEqual(result['asn'], 15169)
        self.assertFalse(result['is_public_proxy'])
        for change in ({'ip': '1.1.1.1'}, {'country_code': '-'}, {'asn': True}, {'error': {'code': 403}}):
            with self.assertRaises(ValueError):
                parse_location({'ip': '8.8.8.8', 'country_code': 'US', 'asn': '15169', **change}, '8.8.8.8')

    def test_duplicate_exits_share_request_and_flag_differences(self):
        rows = [{'quality': {'exit_ip': '8.8.8.8', 'exit_country': country, 'asn': 15169}} for country in ('US', 'SG')]
        response = {'state': 'checked', 'provider': 'IP2Location.io', 'exit_ip': '8.8.8.8', 'exit_country': 'US', 'asn': 15169}
        with patch('scripts.exit_lookup.lookup_exit', return_value=response) as lookup:
            summary = cross_check_exits(rows)
        lookup.assert_called_once_with('8.8.8.8')
        self.assertEqual(summary['request_count'], 1)
        self.assertEqual(rows[1]['exit_check']['mismatched_fields'], ['exit_country'])
        self.assertTrue(rows[0]['exit_check']['consistent'])
        self.assertEqual(summary['mismatched_node_count'], 1)

    def test_outage_does_not_change_scores_or_selection_and_is_cached(self):
        rows = [{'ip': str(i), 'max_ms': 100, 'node_passed': True, 'success_rate': 1,
                 'quality': {'state': 'scored', 'quality_score': 80-i, 'exit_ip': '8.8.8.8'}} for i in range(2)]
        before = copy.deepcopy(rows)
        with patch('scripts.exit_lookup.lookup_exit', return_value={'state': 'unknown', 'provider': 'IP2Location.io', 'failure': 'rate_limited'}) as lookup:
            summary = cross_check_exits(rows)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(summary['unknown_exit_count'], 1)
        self.assertEqual([r['ip'] for r in select_best(rows)], [r['ip'] for r in select_best(before)])
        self.assertEqual([r['quality'] for r in rows], [r['quality'] for r in before])

    def test_missing_exit_skips_lookup_and_private_ip_is_rejected(self):
        rows = [{'quality': {'state': 'unknown'}}]
        with patch('scripts.exit_lookup.lookup_exit') as lookup:
            summary = cross_check_exits(rows)
        lookup.assert_not_called()
        self.assertEqual(summary['request_count'], 0)
        self.assertEqual(rows[0]['exit_check']['state'], 'skipped')
        self.assertEqual(lookup_exit('127.0.0.1')['failure'], 'invalid_exit_ip')
