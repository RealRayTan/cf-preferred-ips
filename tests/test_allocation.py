import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from scripts.update import select_best, write_list


def candidate(ip, country='US', score=None, latency=100):
    quality = {'state': 'scored' if score is not None else 'unknown', 'quality_score': score}
    return {'ip': ip, 'country': country, 'max_ms': 100, 'node_passed': True,
            'success_rate': 1, 'proxy_max_ms': latency, 'proxy_median_ms': latency, 'quality': quality}


class SelectionTests(unittest.TestCase):
    def test_quality_overrides_latency_and_country(self):
        rows = [candidate('fast', 'US', 10, 1), candidate('quality', 'DE', 90, 500)]
        self.assertEqual([r['ip'] for r in select_best(rows)], ['quality', 'fast'])

    def test_unknown_remains_eligible_after_scored(self):
        rows = [candidate('unknown', latency=1), candidate('scored', score=0, latency=500)]
        self.assertEqual([r['ip'] for r in select_best(rows)], ['scored', 'unknown'])

    def test_api_outage_falls_back_to_real_proxy_performance(self):
        rows = [candidate('slow', latency=500), candidate('fast', latency=100)]
        self.assertEqual([r['ip'] for r in select_best(rows)], ['fast', 'slow'])

    def test_limits_unique_nodes_and_requires_full_pass(self):
        rows = [candidate(str(i), score=100-i) for i in range(12)]
        bad = candidate('bad', score=100)
        bad['node_passed'] = False
        selected = select_best([bad]+rows+rows)
        self.assertEqual([r['ip'] for r in selected], [str(i) for i in range(9)])
        self.assertEqual(select_best([]), [])
        self.assertEqual(len(select_best(rows[:2]*2)), 2)


class SubscriptionTests(unittest.TestCase):
    def test_slot_names_survive_score_and_address_changes(self):
        with TemporaryDirectory() as directory, patch('scripts.update.ROOT', Path(directory)):
            path = Path(directory) / 'ip.txt'
            write_list('ip.txt', [candidate('192.0.2.1', score=90), candidate('192.0.2.2')])
            before = path.read_text().splitlines()
            write_list('ip.txt', [candidate('192.0.2.3'), candidate('192.0.2.4', score=10)])
            after = path.read_text().splitlines()
            self.assertNotEqual(before, after)
            self.assertEqual([line.split('#')[1] for line in before], ['CF-01', 'CF-02'])
            self.assertEqual([line.split('#')[1] for line in after], ['CF-01', 'CF-02'])

    def test_empty_scan_preserves_last_subscription(self):
        with TemporaryDirectory() as directory, patch('scripts.update.ROOT', Path(directory)):
            path = Path(directory) / 'ip.txt'
            write_list('ip.txt', [candidate('192.0.2.1', score=90)])
            before = path.read_text()
            write_list('ip.txt', [])
            self.assertEqual(path.read_text(), before)
