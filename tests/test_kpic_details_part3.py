import unittest

from scripts.collect_kpic_details_part3 import can_reuse_record


class KpicDetailsPart3Tests(unittest.TestCase):
    def test_collected_cache_is_not_reused_after_upstream_match_becomes_unsafe(self):
        source = {
            "catalog_name": "훼로모아",
            "catalog_capacity": "120C",
            "kpic_name": "훼로모아시럽",
            "kpic_code": "CODE1",
            "status": "review_required",
        }
        previous = {"kpic_code": "CODE1", "status": "collected"}
        self.assertFalse(can_reuse_record(source, previous))

    def test_same_safe_confirmed_match_can_reuse_collected_cache(self):
        source = {
            "catalog_name": "훼로모아",
            "catalog_capacity": "120C",
            "kpic_name": "훼로모아캡슐",
            "kpic_code": "CODE1",
            "status": "confirmed",
        }
        previous = {"kpic_code": "CODE1", "status": "collected"}
        self.assertTrue(can_reuse_record(source, previous))


if __name__ == "__main__":
    unittest.main()
