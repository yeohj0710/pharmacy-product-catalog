import hashlib
import http.server
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from lib.catalog_review.baseline import canonical_json_sha256, field_schema, validate_baseline


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CANONICAL_FIELDS = (
    "app_capacity",
    "app_category",
    "app_etc",
    "app_id",
    "app_name",
    "app_price",
    "app_updated",
    "capacity",
    "category",
    "displayed_price_krw",
    "document_create_time",
    "document_id",
    "document_update_time",
    "duplicate_group_id",
    "duplicate_group_size",
    "enrichment_status",
    "etc",
    "id",
    "image_checked_at",
    "image_kind",
    "image_rights_status",
    "image_source_url",
    "image_url",
    "match_alternatives",
    "name",
    "normalized_capacity",
    "normalized_name",
    "official_active_ingredients",
    "official_additional_data",
    "official_additives",
    "official_appearance",
    "official_atc_code",
    "official_barcode",
    "official_category",
    "official_checked_at",
    "official_classification_code",
    "official_consumer_guidance",
    "official_content",
    "official_content_status",
    "official_domain",
    "official_dosage",
    "official_dosage_form",
    "official_dur_age",
    "official_dur_contraindications",
    "official_dur_max_dose",
    "official_dur_max_period",
    "official_dur_pregnancy",
    "official_dur_senior",
    "official_dur_split_dosage",
    "official_efficacy",
    "official_english_name",
    "official_identification",
    "official_images",
    "official_ingredients",
    "official_insert_pdf_url",
    "official_insurance",
    "official_insurance_detail",
    "official_insurance_history",
    "official_interactions",
    "official_item_name",
    "official_item_seq",
    "official_kpic_atc",
    "official_manufacturer",
    "official_manufacturer_details",
    "official_match_score",
    "official_match_status",
    "official_medication_guide",
    "official_medication_summary",
    "official_pack_unit",
    "official_patient_guidance",
    "official_permit_date",
    "official_pictograms",
    "official_precautions",
    "official_product_key",
    "official_professional_precautions",
    "official_reimbursement_criteria",
    "official_report_number",
    "official_route",
    "official_same_ingredient_products",
    "official_section_evidence",
    "official_source_type",
    "official_source_url",
    "official_standard_codes",
    "official_storage",
    "official_udi_di",
    "official_upstream_updated_at",
    "official_valid_term",
    "price",
    "price_status",
    "recorded_at",
    "source_order",
    "source_type",
    "specification",
    "updated",
    "verification_status",
)


class CatalogBaselineTests(unittest.TestCase):
    def test_accepts_776_rows_with_conditional_official_content(self):
        rows = [
            {
                "id": f"p-{index}",
                "source_order": index + 1,
                "name": "상품",
                "official_match_status": "confirmed",
                "official_content": {},
            }
            if index < 458
            else {
                "id": f"p-{index}",
                "source_order": index + 1,
                "name": "상품",
                "official_match_status": "not_applicable",
            }
            for index in range(776)
        ]
        expected_fields = {"id", "name", "official_content", "official_match_status", "source_order"}

        result = validate_baseline(rows, expected_count=776, expected_field_union=expected_fields)

        self.assertEqual(result["count"], 776)
        self.assertEqual(set(result["field_union"]), expected_fields)
        self.assertEqual(result["row_field_count_distribution"], {4: 318, 5: 458})

    def test_rejects_wrong_row_count(self):
        with self.assertRaisesRegex(ValueError, "row count"):
            validate_baseline([{"id": "only"}], expected_count=2)

    def test_rejects_empty_or_unstable_ids(self):
        for invalid_id in ("", "   ", None, 1):
            with self.subTest(invalid_id=invalid_id), self.assertRaisesRegex(ValueError, "non-empty string IDs"):
                validate_baseline([{"id": invalid_id}], expected_count=1)

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "duplicate product IDs"):
            validate_baseline([{"id": "same"}, {"id": "same"}], expected_count=2)

    def test_rejects_source_order_that_does_not_match_file_order(self):
        invalid_rows = (
            [{"id": "a", "source_order": 0}],
            [{"id": "a", "source_order": "1"}],
            [{"id": "a", "source_order": 1}, {"id": "b"}],
        )
        for rows in invalid_rows:
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "source_order"):
                validate_baseline(rows, expected_count=len(rows))

    def test_rejects_unexpected_field_union(self):
        with self.assertRaisesRegex(ValueError, "field union"):
            validate_baseline(
                [{"id": "a", "unexpected": True}],
                expected_count=1,
                expected_field_union={"id"},
            )

    def test_rejects_confirmed_row_missing_core_field_supplied_by_another_row(self):
        rows = [
            {
                "id": "a",
                "source_order": 1,
                "official_match_status": "confirmed",
                "official_content": {},
            },
            {
                "id": "b",
                "source_order": 2,
                "name": "상품",
                "official_match_status": "not_applicable",
            },
        ]
        expected_fields = {"id", "source_order", "name", "official_match_status", "official_content"}

        with self.assertRaisesRegex(ValueError, "row fields"):
            validate_baseline(rows, expected_count=2, expected_field_union=expected_fields)

    def test_rejects_both_invalid_conditional_official_content_patterns(self):
        invalid_rows = (
            {"id": "a", "official_match_status": "not_applicable", "official_content": {}},
            {"id": "a", "official_match_status": "confirmed"},
        )
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "official_content"):
                validate_baseline([row], expected_count=1)

    def test_canonical_hash_preserves_utf8_and_key_order(self):
        rows = [{"z": "약", "a": 1}]
        expected = hashlib.sha256('[{"z":"약","a":1}]'.encode("utf-8")).hexdigest()

        self.assertEqual(canonical_json_sha256(rows), expected)
        self.assertNotEqual(canonical_json_sha256(rows), canonical_json_sha256([{"a": 1, "z": "약"}]))

    def test_field_schema_reports_sorted_union_and_distribution(self):
        self.assertEqual(
            field_schema([{"id": "a", "extra": 1}, {"id": "b"}]),
            {
                "field_union": ["extra", "id"],
                "row_field_count_distribution": {1: 1, 2: 1},
            },
        )

    def test_checked_in_schema_matches_exact_production_contract(self):
        schema = json.loads(
            (ROOT / "schemas/catalog-canonical-fields.json").read_text(encoding="utf-8")
        )

        self.assertEqual(schema["schema_version"], "1.0")
        self.assertEqual(schema["field_union"], list(EXPECTED_CANONICAL_FIELDS))
        self.assertEqual(len(schema["field_union"]), 95)
        self.assertEqual(len(set(schema["field_union"])), 95)
        self.assertEqual(schema["accepted_row_field_counts"], [94, 95])
        self.assertEqual(
            schema["conditional_fields"],
            [
                {
                    "field": "official_content",
                    "required_when": {"official_match_status": "confirmed"},
                    "forbidden_otherwise": True,
                }
            ],
        )

    def test_restore_downloads_validates_and_atomically_replaces_existing_targets(self):
        from scripts.restore_production_catalog import _new_sibling_temp, restore_catalog

        payload = json.dumps(
            [{"id": "p-1", "source_order": 1, "official_match_status": "not_applicable"}],
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("ETag", '"test-etag"')
                self.send_header("Last-Modified", "Sat, 18 Jul 2026 00:00:00 GMT")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            output.write_bytes(b"previous catalog")
            manifest_path.write_bytes(b"previous manifest")
            schema_path.write_text(
                json.dumps(
                    {
                        "field_union": ["id", "official_match_status", "source_order"],
                        "accepted_row_field_counts": [3],
                    }
                ),
                encoding="utf-8",
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/catalog.json"
            created_paths = []

            def record_sibling_temp(target, role):
                path = _new_sibling_temp(target, role)
                created_paths.append(path)
                return path

            try:
                with mock.patch(
                    "scripts.restore_production_catalog._new_sibling_temp",
                    side_effect=record_sibling_temp,
                ):
                    manifest = restore_catalog(
                        url=url,
                        output=output,
                        manifest_path=manifest_path,
                        schema_path=schema_path,
                        expected_count=1,
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            self.assertEqual(output.read_bytes(), payload)
            self.assertFalse(output.with_name(output.name + ".download").exists())
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), manifest)
            self.assertEqual(manifest["url"], url)
            self.assertEqual(manifest["http_status"], 200)
            self.assertEqual(manifest["etag"], '"test-etag"')
            self.assertEqual(manifest["last_modified"], "Sat, 18 Jul 2026 00:00:00 GMT")
            self.assertEqual(manifest["byte_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(manifest["count"], 1)
            self.assertEqual(manifest["row_field_count_distribution"], {"3": 1})
            self.assertRegex(manifest["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T")
            self.assertTrue(created_paths[0].name.endswith(".download"), created_paths[0])
            self.assertTrue(
                created_paths[1].name.endswith(".manifest.download"),
                created_paths[1],
            )

    def test_manifest_replace_failure_restores_existing_catalog_and_manifest(self):
        from scripts.restore_production_catalog import restore_catalog

        payload = json.dumps(
            [{"id": "p-1", "source_order": 1, "official_match_status": "not_applicable"}],
            separators=(",", ":"),
        ).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            original_catalog = b"original catalog"
            original_manifest = b'{"version":"original"}\n'
            output.write_bytes(original_catalog)
            manifest_path.write_bytes(original_manifest)
            schema_path.write_text(
                json.dumps(
                    {
                        "field_union": ["id", "official_match_status", "source_order"],
                        "accepted_row_field_counts": [3],
                    }
                ),
                encoding="utf-8",
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original_replace = Path.replace
            manifest_failure_injected = False

            def replace_with_manifest_failure(source, target):
                nonlocal manifest_failure_injected
                if Path(target).resolve() == manifest_path.resolve() and not manifest_failure_injected:
                    manifest_failure_injected = True
                    manifest_path.write_bytes(b"partially replaced manifest")
                    raise OSError("injected manifest replacement failure")
                return original_replace(source, target)

            try:
                with mock.patch.object(Path, "replace", new=replace_with_manifest_failure):
                    with self.assertRaisesRegex(OSError, "injected manifest replacement failure"):
                        restore_catalog(
                            url=f"http://127.0.0.1:{server.server_port}/catalog.json",
                            output=output,
                            manifest_path=manifest_path,
                            schema_path=schema_path,
                            expected_count=1,
                        )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            self.assertTrue(manifest_failure_injected)
            self.assertEqual(output.read_bytes(), original_catalog)
            self.assertEqual(manifest_path.read_bytes(), original_manifest)
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {"catalog.json", "manifest.json", "schema.json"},
            )

    def test_manifest_replace_failure_removes_catalog_created_by_failed_transaction(self):
        from scripts.restore_production_catalog import restore_catalog

        payload = json.dumps(
            [{"id": "p-1", "source_order": 1, "official_match_status": "not_applicable"}],
            separators=(",", ":"),
        ).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            original_manifest = b'{"version":"original"}\n'
            manifest_path.write_bytes(original_manifest)
            schema_path.write_text(
                json.dumps(
                    {
                        "field_union": ["id", "official_match_status", "source_order"],
                        "accepted_row_field_counts": [3],
                    }
                ),
                encoding="utf-8",
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original_replace = Path.replace
            manifest_failure_injected = False

            def replace_with_manifest_failure(source, target):
                nonlocal manifest_failure_injected
                if Path(target).resolve() == manifest_path.resolve() and not manifest_failure_injected:
                    manifest_failure_injected = True
                    raise OSError("injected manifest replacement failure")
                return original_replace(source, target)

            try:
                with mock.patch.object(Path, "replace", new=replace_with_manifest_failure):
                    with self.assertRaisesRegex(OSError, "injected manifest replacement failure"):
                        restore_catalog(
                            url=f"http://127.0.0.1:{server.server_port}/catalog.json",
                            output=output,
                            manifest_path=manifest_path,
                            schema_path=schema_path,
                            expected_count=1,
                        )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            self.assertTrue(manifest_failure_injected)
            self.assertFalse(output.exists())
            self.assertEqual(manifest_path.read_bytes(), original_manifest)

    def test_unique_sibling_staging_paths_do_not_collide(self):
        from scripts.restore_production_catalog import _new_sibling_temp

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "catalog.json"
            first = _new_sibling_temp(target, "download")
            second = _new_sibling_temp(target, "download")
            try:
                self.assertNotEqual(first, second)
                self.assertEqual(first.parent, target.parent)
                self.assertEqual(second.parent, target.parent)
                self.assertTrue(first.exists())
                self.assertTrue(second.exists())
            finally:
                first.unlink(missing_ok=True)
                second.unlink(missing_ok=True)

    def test_restore_rejects_output_manifest_collision(self):
        from scripts.restore_production_catalog import restore_catalog

        payload = json.dumps(
            [{"id": "p-1", "source_order": 1, "official_match_status": "not_applicable"}],
            separators=(",", ":"),
        ).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            colliding_target = root / "catalog-and-manifest.json"
            schema_path = root / "schema.json"
            schema_payload = json.dumps(
                {
                    "field_union": ["id", "official_match_status", "source_order"],
                    "accepted_row_field_counts": [3],
                }
            )
            schema_path.write_text(schema_payload, encoding="utf-8")
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaisesRegex(ValueError, "path collision"):
                    restore_catalog(
                        url=f"http://127.0.0.1:{server.server_port}/catalog.json",
                        output=colliding_target,
                        manifest_path=colliding_target,
                        schema_path=schema_path,
                        expected_count=1,
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            self.assertFalse(colliding_target.exists())
            self.assertEqual(schema_path.read_text(encoding="utf-8"), schema_payload)

    def test_restore_rejects_normalized_output_schema_alias(self):
        from scripts.restore_production_catalog import restore_catalog

        payload = json.dumps(
            [{"id": "p-1", "source_order": 1, "official_match_status": "not_applicable"}],
            separators=(",", ":"),
        ).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema_path = root / "schema.json"
            aliased_output = root / "nested" / ".." / "schema.json"
            manifest_path = root / "manifest.json"
            schema_payload = json.dumps(
                {
                    "field_union": ["id", "official_match_status", "source_order"],
                    "accepted_row_field_counts": [3],
                }
            )
            schema_path.write_text(schema_payload, encoding="utf-8")
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaisesRegex(ValueError, "path collision"):
                    restore_catalog(
                        url=f"http://127.0.0.1:{server.server_port}/catalog.json",
                        output=aliased_output,
                        manifest_path=manifest_path,
                        schema_path=schema_path,
                        expected_count=1,
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            self.assertEqual(schema_path.read_text(encoding="utf-8"), schema_payload)
            self.assertFalse(manifest_path.exists())

    def test_restore_rejects_staging_path_collision_without_deleting_schema(self):
        from scripts.restore_production_catalog import restore_catalog

        payload = json.dumps(
            [{"id": "p-1", "source_order": 1, "official_match_status": "not_applicable"}],
            separators=(",", ":"),
        ).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            schema_payload = json.dumps(
                {
                    "field_union": ["id", "official_match_status", "source_order"],
                    "accepted_row_field_counts": [3],
                }
            )
            schema_path.write_text(schema_payload, encoding="utf-8")
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with mock.patch(
                    "scripts.restore_production_catalog._new_sibling_temp",
                    return_value=schema_path,
                ):
                    with self.assertRaisesRegex(ValueError, "path collision"):
                        restore_catalog(
                            url=f"http://127.0.0.1:{server.server_port}/catalog.json",
                            output=output,
                            manifest_path=manifest_path,
                            schema_path=schema_path,
                            expected_count=1,
                        )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            self.assertEqual(schema_path.read_text(encoding="utf-8"), schema_payload)
            self.assertFalse(output.exists())
            self.assertFalse(manifest_path.exists())

    def test_restore_passes_timeout_and_reads_response_in_bounded_chunks(self):
        from scripts.restore_production_catalog import restore_catalog

        payload = json.dumps(
            [{"id": "p-1", "source_order": 1, "official_match_status": "not_applicable"}],
            separators=(",", ":"),
        ).encode("utf-8")

        class FakeResponse:
            def __init__(self):
                self.headers = {"Content-Length": str(len(payload))}
                self.stream = io.BytesIO(payload)
                self.read_sizes = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def getcode(self):
                return 200

            def read(self, size=-1):
                self.read_sizes.append(size)
                return self.stream.read(size)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            schema_path.write_text(
                json.dumps(
                    {
                        "field_union": ["id", "official_match_status", "source_order"],
                        "accepted_row_field_counts": [3],
                    }
                ),
                encoding="utf-8",
            )
            response = FakeResponse()
            with mock.patch(
                "scripts.restore_production_catalog.urlopen",
                return_value=response,
            ) as opener:
                restore_catalog(
                    url="https://example.test/catalog.json",
                    output=output,
                    manifest_path=manifest_path,
                    schema_path=schema_path,
                    expected_count=1,
                )

            self.assertEqual(opener.call_args.kwargs.get("timeout"), 30)
            self.assertTrue(response.read_sizes)
            self.assertEqual(set(response.read_sizes), {1024 * 1024})

    def test_restore_rejects_declared_content_length_above_maximum(self):
        from scripts.restore_production_catalog import restore_catalog

        class FakeResponse:
            def __init__(self):
                self.headers = {"Content-Length": str(64 * 1024 * 1024 + 1)}
                self.read_sizes = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def getcode(self):
                return 200

            def read(self, size=-1):
                self.read_sizes.append(size)
                return b""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            schema_path.write_text("{}", encoding="utf-8")
            response = FakeResponse()

            with mock.patch(
                "scripts.restore_production_catalog.urlopen",
                return_value=response,
            ):
                with self.assertRaisesRegex(ValueError, "maximum download size"):
                    restore_catalog(
                        url="https://example.test/catalog.json",
                        output=output,
                        manifest_path=manifest_path,
                        schema_path=schema_path,
                        expected_count=1,
                    )

            self.assertEqual(response.read_sizes, [])
            self.assertEqual({path.name for path in root.iterdir()}, {"schema.json"})

    def test_restore_rejects_accumulated_body_above_maximum(self):
        from scripts.restore_production_catalog import restore_catalog

        class FakeResponse:
            def __init__(self):
                self.headers = {}
                self.stream = io.BytesIO(b"123456789")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def getcode(self):
                return 200

            def read(self, size=-1):
                return self.stream.read(size)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            schema_path.write_text("{}", encoding="utf-8")

            with mock.patch(
                "scripts.restore_production_catalog.urlopen",
                return_value=FakeResponse(),
            ), mock.patch(
                "scripts.restore_production_catalog.MAX_DOWNLOAD_BYTES",
                8,
                create=True,
            ):
                with self.assertRaisesRegex(ValueError, "maximum download size"):
                    restore_catalog(
                        url="https://example.test/catalog.json",
                        output=output,
                        manifest_path=manifest_path,
                        schema_path=schema_path,
                        expected_count=1,
                    )

            self.assertEqual({path.name for path in root.iterdir()}, {"schema.json"})

    def test_restore_does_not_replace_baseline_when_validation_fails(self):
        from scripts.restore_production_catalog import restore_catalog

        invalid_payload = json.dumps(
            [{"id": "p-1", "official_match_status": "confirmed"}],
            separators=(",", ":"),
        ).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(invalid_payload)))
                self.end_headers()
                self.wfile.write(invalid_payload)

            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "catalog.json"
            output.write_bytes(b"original baseline")
            manifest_path = root / "manifest.json"
            schema_path = root / "schema.json"
            schema_path.write_text(
                json.dumps({"field_union": ["id", "official_match_status"]}),
                encoding="utf-8",
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaisesRegex(ValueError, "official_content"):
                    restore_catalog(
                        url=f"http://127.0.0.1:{server.server_port}/catalog.json",
                        output=output,
                        manifest_path=manifest_path,
                        schema_path=schema_path,
                        expected_count=1,
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

            self.assertEqual(output.read_bytes(), b"original baseline")
            self.assertFalse(output.with_name(output.name + ".download").exists())
            self.assertFalse(manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
