import unittest

from lib.catalog_text_normalization import (
    normalize_health_text,
    parse_health_rich_text,
)


class CatalogTextNormalizationTests(unittest.TestCase):
    def test_health_separator_order_does_not_leave_literal_br(self):
        source = "첫 문장.brbr<P></P>둘째 문장brbr<P></P><P>셋째 문장</P>"

        self.assertEqual(normalize_health_text(source), "첫 문장.\n\n둘째 문장\n\n셋째 문장")

    def test_legacy_damaged_separator_is_repaired(self):
        source = "첫 문장.br\n\n둘째 문장br\n\n세 번째 문장"

        self.assertEqual(normalize_health_text(source), "첫 문장.\n\n둘째 문장\n\n세 번째 문장")

    def test_numeric_ranges_and_subtraction_formula_are_repaired(self):
        source = "[140 ? 연령 (세)] × 체중 (kg)brbr<P></P>경증 50 ? 79brbr<P></P>중등도 30 ? 49"

        self.assertEqual(
            normalize_health_text(source),
            "[140 - 연령 (세)] × 체중 (kg)\n\n경증 50–79\n\n중등도 30–49",
        )

    def test_unicode_spacing_and_invisible_characters_are_removed(self):
        self.assertEqual(normalize_health_text("복용\u00a0방법\u200b 안내"), "복용 방법 안내")

    def test_table_is_preserved_as_structured_rows(self):
        source = (
            "표를 참조한다.brbr<P></P>"
            "<TABLE><TR><TD>구분</TD><TD>용량</TD></TR>"
            "<TR><TD>경증</TD><TD>10 mg</TD></TR>"
            "<TR><TD>중등도</TD><TD>5 mg</TD></TR></TABLE>"
            "brbr<P></P>연령에 따라 조절한다."
        )

        rich = parse_health_rich_text(source)

        self.assertEqual(
            rich["blocks"],
            [
                {"type": "paragraph", "text": "표를 참조한다."},
                {
                    "type": "table",
                    "headers": ["구분", "용량"],
                    "rows": [["경증", "10 mg"], ["중등도", "5 mg"]],
                },
                {"type": "paragraph", "text": "연령에 따라 조절한다."},
            ],
        )
        self.assertEqual(
            rich["text"],
            "표를 참조한다.\n\n구분 | 용량\n경증 | 10 mg\n중등도 | 5 mg\n\n연령에 따라 조절한다.",
        )

    def test_normalization_is_idempotent(self):
        normalized = normalize_health_text("첫 문장.brbr<P></P>둘째 문장")
        self.assertEqual(normalize_health_text(normalized), normalized)

    def test_rowspan_and_colspan_expand_to_rectangular_rows(self):
        source = (
            "<TABLE>"
            "<TR><TH rowspan='2'>구분</TH><TH colspan='2'>용량</TH></TR>"
            "<TR><TH>아침</TH><TH>저녁</TH></TR>"
            "<TR><TD>경증</TD><TD>5 mg</TD><TD>5 mg</TD></TR>"
            "</TABLE>"
        )

        table = parse_health_rich_text(source)["blocks"][0]

        self.assertEqual(table["headers"], ["구분", "용량", ""])
        self.assertEqual(table["rows"], [["", "아침", "저녁"], ["경증", "5 mg", "5 mg"]])
        self.assertTrue(all(len(row) == 3 for row in [table["headers"], *table["rows"]]))

    def test_nested_table_content_is_preserved_in_parent_cell(self):
        source = "<TABLE><TR><TD>외부<TABLE><TR><TD>내부 1</TD><TD>내부 2</TD></TR></TABLE></TD></TR></TABLE>"

        rich = parse_health_rich_text(source)

        self.assertIn("외부", rich["text"])
        self.assertIn("내부 1 | 내부 2", rich["text"])


if __name__ == "__main__":
    unittest.main()
