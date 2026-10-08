import unittest
from collections import Counter
from scripts.update import select_balanced


def candidates(country, count):
    return [{'ip': f'{country}-{i}', 'country': country, 'max_ms': 100+i, 'median_ms': 80+i,
             'node_passed': True, 'success_rate': 1, 'proxy_max_ms': 100+i, 'proxy_median_ms': 80+i}
            for i in range(count)]


class AllocationTests(unittest.TestCase):
    def counts(self, rows):
        return dict(Counter(row['country'] for row in select_balanced(rows)))

    def test_three_per_country(self):
        self.assertEqual(self.counts(candidates('SG', 5)+candidates('JP', 5)+candidates('US', 12)),
                         {'SG': 3, 'JP': 3, 'US': 3})

    def test_missing_asian_slots_go_to_us(self):
        self.assertEqual(self.counts(candidates('SG', 1)+candidates('US', 12)), {'SG': 1, 'US': 8})

    def test_us_only_fallback(self):
        self.assertEqual(self.counts(candidates('US', 12)), {'US': 9})

    def test_insufficient_candidates_are_not_duplicated(self):
        rows = candidates('JP', 2)+candidates('US', 2)
        result = select_balanced(rows+rows+candidates('KR', 5))
        self.assertEqual(len(result), 4)
        self.assertEqual(len({row['ip'] for row in result}), 4)

    def test_quality_order_and_empty_input(self):
        rows = candidates('US', 12)[::-1]
        self.assertEqual([r['ip'] for r in select_balanced(rows)], [f'US-{i}' for i in range(9)])
        self.assertEqual(select_balanced([]), [])

    def test_fast_entrance_without_full_node_pass_is_excluded(self):
        bad = {'ip': 'bad', 'country': 'US', 'max_ms': 1, 'median_ms': 1}
        self.assertEqual(self.counts([bad]+candidates('US', 4)), {'US': 4})


if __name__ == '__main__':
    unittest.main()
