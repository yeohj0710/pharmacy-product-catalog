import unittest

from scripts.audit_portable_catalog import (
    audit_images,
    audit_official,
    audit_text,
    build_gap_queue,
    normalize_identity_name,
    run_audit,
)


def make_product(
    product_id,
    name,
    *,
    specification="30정",
    category="비타민",
    match_status="not_applicable",
    image_url=None,
    medicine=None,
    source_order=1,
):
    return {
        "schema_version": "1.0",
        "product_id": product_id,
        "display": {
            "name": name,
            "specification": specification,
            "category": category,
            "price_krw": 1000,
            "notes": None,
            "source_order": source_order,
        },
        "media": {
            "primary_image": {"url": image_url, "rights_status": "verified"}
            if image_url
            else None
        },
        "medicine": medicine,
        "quality": {
            "verification_status": "test",
            "official_match_status": match_status,
            "official_content_status": None,
            "image_rights_status": "verified" if image_url else None,
        },
        "provenance": {},
        "ai_context": "",
    }


def make_medicine(item_code, item_name, manufacturer="제조사"):
    return {
        "identity": {
            "item_name": item_name,
            "item_code": item_code,
            "manufacturer": manufacturer,
        },
        "content": {
            "efficacy": {"text": "효능"},
            "dosage": {"text": "용법"},
            "precautions": {"text": "주의"},
        },
        "source": {"url": "https://example.org/item"},
    }


class NormalizeIdentityNameTests(unittest.TestCase):
    def test_ignores_spacing_and_pack_sizes(self):
        self.assertEqual(
            normalize_identity_name("유한 비타민C정 1000mg"),
            normalize_identity_name("유한비타민C정"),
        )

    def test_distinguishes_variant_suffix(self):
        self.assertNotEqual(
            normalize_identity_name("벤포벨"), normalize_identity_name("벤포벨B")
        )


class AuditTextTests(unittest.TestCase):
    def test_flags_residual_html_and_replacement_character(self):
        product = make_product("p1", "상품")
        product["ai_context"] = "본문 <br> 깨짐 �"
        findings = audit_text([product])
        codes = {finding["code"] for finding in findings}
        self.assertIn("residual_html", codes)
        self.assertIn("replacement_character", codes)

    def test_clean_product_has_no_findings(self):
        product = make_product("p1", "상품")
        product["ai_context"] = "정상 본문 1~2정"
        self.assertEqual(audit_text([product]), [])


class AuditImagesTests(unittest.TestCase):
    def test_reports_missing_and_cross_identity_shared_url(self):
        shared = "https://example.org/a.jpg"
        products = [
            make_product("p1", "벤포벨", image_url=shared),
            make_product("p2", "벤포벨B", image_url=shared),
            make_product("p3", "이미지없음"),
        ]
        result = audit_images(products)
        self.assertEqual(len(result["missing"]), 1)
        self.assertEqual(result["missing"][0]["product_id"], "p3")
        self.assertEqual(len(result["shared_url_groups"]), 1)
        self.assertTrue(result["shared_url_groups"][0]["cross_identity"])

    def test_same_identity_shared_url_not_cross_identity(self):
        shared = "https://example.org/a.jpg"
        products = [
            make_product("p1", "안정액 50ml", image_url=shared),
            make_product("p2", "안정액", image_url=shared),
        ]
        result = audit_images(products)
        self.assertFalse(result["shared_url_groups"][0]["cross_identity"])

    def test_flags_search_proxy_hosts(self):
        products = [
            make_product(
                "p1",
                "상품",
                image_url="https://thumbnail.coupangcdn.com/thumbnails/remote/492x492ex/image/a.jpg",
            )
        ]
        result = audit_images(products)
        self.assertEqual(len(result["search_proxy_findings"]), 1)


class AuditOfficialTests(unittest.TestCase):
    def test_confirmed_row_missing_sections_is_reported(self):
        medicine = make_medicine("CODE1", "상품정")
        medicine["content"]["dosage"]["text"] = ""
        products = [
            make_product("p1", "상품", match_status="confirmed", medicine=medicine)
        ]
        result = audit_official(products)
        self.assertEqual(len(result["confirmed_missing_fields"]), 1)
        self.assertIn(
            "content.dosage", result["confirmed_missing_fields"][0]["missing"]
        )

    def test_shared_item_code_across_identities_is_reported(self):
        products = [
            make_product(
                "p1",
                "벤포벨",
                match_status="confirmed",
                medicine=make_medicine("CODE1", "벤포벨정"),
            ),
            make_product(
                "p2",
                "벤포벨B",
                match_status="confirmed",
                medicine=make_medicine("CODE1", "벤포벨정"),
            ),
        ]
        result = audit_official(products)
        self.assertEqual(len(result["shared_item_codes_cross_identity"]), 1)


class GapQueueTests(unittest.TestCase):
    def test_queue_covers_unresolved_missing_image_and_conflicts(self):
        shared = "https://example.org/a.jpg"
        products = [
            make_product(
                "p1", "미해결", match_status="review_required", source_order=1
            ),
            make_product("p2", "이미지없음", match_status="not_applicable", source_order=2),
            make_product(
                "p3",
                "벤포벨",
                match_status="confirmed",
                medicine=make_medicine("CODE1", "벤포벨정"),
                image_url=shared,
                source_order=3,
            ),
            make_product(
                "p4",
                "벤포벨B",
                match_status="confirmed",
                medicine=make_medicine("CODE1", "벤포벨정"),
                image_url=shared,
                source_order=4,
            ),
        ]
        image_audit = audit_images(products)
        official_audit = audit_official(products)
        queue = build_gap_queue(products, image_audit, official_audit)
        rows = {row["product_id"]: row for row in queue}
        self.assertIn("official_match_unresolved", rows["p1"]["queue_reasons"])
        self.assertIn("image_missing", rows["p1"]["queue_reasons"])
        self.assertIn("image_missing", rows["p2"]["queue_reasons"])
        self.assertIn(
            "shared_item_code_identity_conflict", rows["p3"]["queue_reasons"]
        )
        self.assertIn("shared_image_cross_identity", rows["p4"]["queue_reasons"])
        self.assertEqual(queue[0]["product_id"], "p1")

    def test_run_audit_summary_counts(self):
        products = [
            make_product("p1", "미해결", match_status="not_found"),
            make_product(
                "p2",
                "정상",
                match_status="confirmed",
                medicine=make_medicine("CODE9", "정상정"),
                image_url="https://example.org/ok.jpg",
            ),
        ]
        report, queue = run_audit(products, generated_at="2026-07-18T00:00:00+09:00")
        self.assertEqual(report["product_count"], 2)
        self.assertEqual(report["summary"]["image_missing_count"], 1)
        self.assertEqual(report["summary"]["gap_queue_row_count"], 1)
        self.assertEqual(queue[0]["product_id"], "p1")


if __name__ == "__main__":
    unittest.main()
