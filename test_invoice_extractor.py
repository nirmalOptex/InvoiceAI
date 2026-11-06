import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from invoice_extractor import (
    ExtractionError,
    extract_invoice,
    image_data_url,
    normalize_invoice_data,
    validate_invoice,
)


class InvoiceExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.invoice = normalize_invoice_data(
            {
                "invoice_number": "RT-2024-1052",
                "invoice_date": "2024-10-14",
                "supplier_name": "Rivertech Supplies Ltd.",
                "currency": "NPR",
                "items": [
                    {
                        "description": "HDPE Pipe 110mm (6m length)",
                        "quantity": "50 pcs",
                        "unit_price": 1250,
                        "line_total": 62500,
                    },
                    {
                        "description": "HDPE Elbow 90° 110mm",
                        "quantity": "20 pcs",
                        "unit_price": 450,
                        "line_total": 9000,
                    },
                    {
                        "description": "HDPE Coupling 110mm",
                        "quantity": "30 pcs",
                        "unit_price": 300,
                        "line_total": 9000,
                    },
                    {
                        "description": "Welding Service",
                        "quantity": "10 hrs",
                        "unit_price": 1500,
                        "line_total": 15000,
                    },
                    {
                        "description": "Delivery Charge",
                        "quantity": "1 lot",
                        "unit_price": 5000,
                        "line_total": 5000,
                    },
                ],
                "subtotal": 100500,
                "tax_amount": 13065,
                "total_amount": 113565,
            }
        )

    def test_sample_invoice_totals_validate(self) -> None:
        result = validate_invoice(self.invoice)

        self.assertTrue(result["line_items_match_subtotal"])
        self.assertTrue(result["subtotal_plus_tax_matches_total"])
        self.assertEqual(result["warnings"], [])

    def test_missing_fields_are_preserved_and_reported(self) -> None:
        invoice = normalize_invoice_data({"items": []})
        result = validate_invoice(invoice)

        self.assertIsNone(invoice["invoice_number"])
        self.assertEqual(invoice["items"], [])
        self.assertIsNone(invoice["total_amount"])
        self.assertGreaterEqual(len(result["warnings"]), 4)

    def test_inconsistent_totals_produce_warnings(self) -> None:
        invoice = dict(self.invoice)
        invoice["total_amount"] = 120000

        result = validate_invoice(invoice)

        self.assertFalse(result["subtotal_plus_tax_matches_total"])
        self.assertIn(
            "The subtotal plus tax does not match the total amount.",
            result["warnings"],
        )

    def test_amount_strings_are_normalized(self) -> None:
        invoice = normalize_invoice_data(
            {"total_amount": "NPR 113,565.00", "items": []}
        )

        self.assertEqual(invoice["total_amount"], 113565.0)

    def test_invalid_amount_is_reported(self) -> None:
        with self.assertRaisesRegex(ExtractionError, "'total_amount'"):
            normalize_invoice_data({"total_amount": "unknown", "items": []})

    def test_image_is_encoded_as_data_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "invoice.png"
            image_path.write_bytes(b"test-image")

            data_url = image_data_url(image_path)

        self.assertTrue(data_url.startswith("data:image/png;base64,"))

    def test_unsupported_image_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "invoice.pdf"
            image_path.write_bytes(b"test-file")

            with self.assertRaisesRegex(ExtractionError, "Unsupported image type"):
                image_data_url(image_path)

    def test_api_response_is_normalized_without_network_access(self) -> None:
        api_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "invoice_number": "RT-2024-1052",
                                "items": [],
                                "total_amount": 113565,
                            }
                        )
                    }
                }
            ]
        }
        response = MagicMock()
        response.read.return_value = json.dumps(api_payload).encode("utf-8")
        response.__enter__.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "invoice.png"
            image_path.write_bytes(b"test-image")
            with patch("invoice_extractor.urllib.request.urlopen", return_value=response):
                invoice = extract_invoice(image_path, "test-key", "test-model")

        self.assertEqual(invoice["invoice_number"], "RT-2024-1052")
        self.assertEqual(invoice["total_amount"], 113565.0)


if __name__ == "__main__":
    unittest.main()
