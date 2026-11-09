from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import httpx
import pytest
import pymupdf as fitz
from PIL import Image

from app.config import Settings
from app.providers.base import ProviderConfigurationError, ProviderError, VisionPage
from app.providers.claude import ClaudeVisionProvider
from app.providers.factory import create_vision_provider
from app.providers.gemini import GeminiVisionProvider
from app.providers.local import LocalRuleBasedProvider
from app.services.document_processing import (
    DocumentProcessingError,
    process_document,
)
from app.services.evidence_service import attach_ocr_evidence
from app.services.extraction_pipeline import extract_document
from app.services.normalizer import normalize_extraction
from app.services.normalizer import ExtractionNormalizationError
from app.services.ocr_service import (
    OCRLine,
    OCRUnavailableError,
    PaddleOCRService,
    parse_paddle_result,
)

SAMPLE_DATA = {
    "supplier_name": "Rivertech Supplies Ltd.",
    "supplier_address": "45 Industrial Estate Road",
    "supplier_tax_id": None,
    "invoice_number": "RT-2024-1052",
    "invoice_date": "14 October 2024",
    "due_date": "13 November 2024",
    "currency": "npr",
    "items": [
        {
            "description": "HDPE Pipe 110mm (6m length)",
            "quantity": "50",
            "unit": "pcs",
            "unit_price": "1,250.00",
            "line_total": "62,500.00",
        }
    ],
    "subtotal": "100500.00",
    "discount": None,
    "tax_rate": "13%",
    "tax_amount": "13065.00",
    "additional_charges": None,
    "total_amount": "113565.00",
}


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(output, format="PNG")
    return output.getvalue()


def _pdf_bytes(pages: int = 2) -> bytes:
    document = fitz.open()
    for _ in range(pages):
        document.new_page(width=200, height=100)
    content = document.tobytes()
    document.close()
    return content


class StubOCR:
    def __init__(self, lines: list[OCRLine] | None = None) -> None:
        self.lines = lines or []
        self.pages: list[VisionPage] = []

    def extract(self, pages: list[VisionPage]) -> list[OCRLine]:
        self.pages = pages
        return self.lines


class StubProvider:
    name = "mock"

    def __init__(self, data: dict | None = None) -> None:
        self.data = data or SAMPLE_DATA
        self.pages: list[VisionPage] = []
        self.ocr_text = ""

    def extract(self, pages: list[VisionPage], ocr_text: str) -> dict:
        self.pages = pages
        self.ocr_text = ocr_text
        return self.data


def test_process_png_normalizes_to_vision_page_and_safe_filename() -> None:
    document = process_document(_png_bytes(), r"..\invoices\bill.png")

    assert document.filename == "bill.png"
    assert document.source_type == "image/png"
    assert len(document.pages) == 1
    assert document.pages[0].mime_type == "image/jpeg"
    assert Image.open(io.BytesIO(document.pages[0].image_bytes)).size == (20, 10)


@pytest.mark.parametrize(
    ("content", "filename", "message"),
    [
        (b"", "bill.png", "empty"),
        (b"%PDF-not-an-image", "bill.png", "does not match"),
        (b"not an image", "bill.exe", "Supported document formats"),
        (b"\x89PNG\r\n\x1a\nnot a real png", "bill.png", "invalid or unreadable"),
    ],
)
def test_invalid_document_inputs_are_rejected(
    content: bytes, filename: str, message: str
) -> None:
    with pytest.raises(DocumentProcessingError, match=message):
        process_document(content, filename)


def test_process_pdf_renders_all_pages_and_enforces_page_limit() -> None:
    processed = process_document(_pdf_bytes(), "invoice.pdf", max_pages=2)

    assert len(processed.pages) == 2
    assert [page.page_number for page in processed.pages] == [1, 2]
    with pytest.raises(DocumentProcessingError, match="limit is 1"):
        process_document(_pdf_bytes(2), "invoice.pdf", max_pages=1)


def test_document_size_limit_is_enforced() -> None:
    with pytest.raises(DocumentProcessingError, match="size limit"):
        process_document(_png_bytes(), "invoice.png", max_file_bytes=1)


def test_encrypted_pdf_is_rejected() -> None:
    document = fitz.open()
    document.new_page()
    protected = document.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    document.close()

    with pytest.raises(DocumentProcessingError, match="Password-protected"):
        process_document(protected, "locked.pdf")


def test_paddle_ocr_parser_normalizes_legacy_and_v3_shapes() -> None:
    legacy = [
        [
            [[0, 0], [20, 0], [20, 10], [0, 10]],
            ("Invoice RT-2024-1052", 0.97),
        ]
    ]
    modern = {
        "rec_texts": ["Total 113,565.00"],
        "rec_scores": [0.91],
        "rec_polys": [[[1, 2], [3, 2], [3, 4], [1, 4]]],
    }

    parsed_legacy = parse_paddle_result([legacy], 1)
    parsed_modern = parse_paddle_result(modern, 2)

    assert parsed_legacy[0].text == "Invoice RT-2024-1052"
    assert parsed_legacy[0].confidence == 0.97
    assert parsed_legacy[0].page_number == 1
    assert parsed_modern[0].bounding_box == [1, 2, 3, 2, 3, 4, 1, 4]
    assert parsed_modern[0].page_number == 2


def test_paddle_ocr_service_uses_injected_engine_without_model_download() -> None:
    engine = Mock()
    box = [[0, 0], [4, 0], [4, 2], [0, 2]]
    engine.ocr.return_value = [[[box, ("Subtotal", 0.9)]]]
    service = PaddleOCRService(engine=engine)
    page = process_document(_png_bytes(), "invoice.png").pages[0]

    lines = service.extract([page])

    assert lines[0].text == "Subtotal"
    engine.ocr.assert_called_once()


def test_normalization_uses_decimal_and_keeps_ambiguous_dates_unset() -> None:
    payload = dict(SAMPLE_DATA)
    payload["invoice_date"] = "04/05/2024"
    invoice, warnings = normalize_extraction(payload)

    assert invoice.invoice_date is None
    assert invoice.due_date == date(2024, 11, 13)
    assert invoice.items[0].quantity == Decimal("50")
    assert invoice.items[0].unit_price == Decimal("1250.00")
    assert invoice.currency == "NPR"
    assert warnings == ["Date '04/05/2024' is ambiguous; confirm it during review."]


def test_normalization_reports_invalid_numeric_fields_without_guessing() -> None:
    payload = dict(SAMPLE_DATA)
    payload["total_amount"] = "unknown"

    with pytest.raises(ExtractionNormalizationError, match="invalid total amount"):
        normalize_extraction(payload)


def test_evidence_attaches_only_when_text_matches_value() -> None:
    invoice, _ = normalize_extraction(SAMPLE_DATA)
    ocr_lines = [
        OCRLine(
            text="Invoice RT-2024-1052",
            page_number=1,
            bounding_box=[0, 0, 20, 0, 20, 5, 0, 5],
            confidence=0.98,
        ),
        OCRLine(
            text="Unit price NPR 1,250.00",
            page_number=1,
            bounding_box=[0, 10, 20, 10, 20, 15, 0, 15],
            confidence=0.88,
        ),
    ]

    attach_ocr_evidence(invoice, ocr_lines, "gemini")

    assert invoice.field_evidence["invoice_number"].original_source_text == (
        "Invoice RT-2024-1052"
    )
    assert invoice.field_evidence["invoice_number"].ocr_confidence == 0.98
    assert invoice.items[0].source_evidence["unit_price"].page_number == 1
    assert "supplier_name" not in invoice.field_evidence


def test_evidence_matches_amount_with_ocr_separator_repair() -> None:
    invoice, _ = normalize_extraction(
        {**SAMPLE_DATA, "subtotal": "100500.00", "total_amount": "113565.00"}
    )
    line = OCRLine("Subtotal: NPR 100.500.00", 1, [0, 0, 10, 0], 0.9)

    attach_ocr_evidence(invoice, [line], "local")

    assert invoice.field_evidence["subtotal"].original_source_text == line.text
    assert invoice.field_evidence["subtotal"].extraction_provider == "local"


def test_gemini_provider_sends_images_and_ocr_and_parses_json() -> None:
    response = httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(SAMPLE_DATA)}]}}
            ]
        },
        request=httpx.Request("POST", "https://example.test"),
    )
    page = VisionPage(1, "image/png", b"sample")
    with patch("app.providers.gemini.httpx.post", return_value=response) as post:
        data = GeminiVisionProvider("secret").extract([page], "invoice OCR")

    request = post.call_args.kwargs
    assert data["invoice_number"] == "RT-2024-1052"
    assert request["headers"]["x-goog-api-key"] == "secret"
    assert request["json"]["contents"][0]["parts"][0]["text"].find("invoice OCR") > 0
    assert request["json"]["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "image/png"


def test_claude_provider_sends_images_and_parses_json() -> None:
    response = httpx.Response(
        200,
        json={"content": [{"type": "text", "text": json.dumps(SAMPLE_DATA)}]},
        request=httpx.Request("POST", "https://example.test"),
    )
    with patch("app.providers.claude.httpx.post", return_value=response) as post:
        data = ClaudeVisionProvider("secret").extract(
            [VisionPage(1, "image/jpeg", b"sample")], "OCR contents"
        )

    assert data["currency"] == "npr"
    request = post.call_args.kwargs
    assert request["headers"]["x-api-key"] == "secret"
    assert request["json"]["messages"][0]["content"][1]["source"]["media_type"] == (
        "image/jpeg"
    )


@pytest.mark.parametrize(
    ("provider", "patch_path", "status"),
    [
        ("gemini", "app.providers.gemini.httpx.post", 401),
        ("claude", "app.providers.claude.httpx.post", 503),
    ],
)
def test_provider_http_errors_do_not_expose_response_body(
    provider: str, patch_path: str, status: int
) -> None:
    response = httpx.Response(
        status,
        text="sensitive provider response",
        request=httpx.Request("POST", "https://example.test"),
    )
    with patch(patch_path, return_value=response):
        adapter = (
            GeminiVisionProvider("secret")
            if provider == "gemini"
            else ClaudeVisionProvider("secret")
        )
        with pytest.raises(ProviderError, match=f"HTTP {status}") as error:
            adapter.extract([VisionPage(1, "image/png", b"image")], "")

    assert "sensitive provider response" not in str(error.value)
    assert "secret" not in str(error.value)


def test_provider_factory_requires_selected_provider_credentials() -> None:
    with pytest.raises(ProviderConfigurationError, match="GEMINI_API_KEY"):
        create_vision_provider(Settings(ai_provider="gemini", gemini_api_key=None))

    assert create_vision_provider(Settings(ai_provider="local")).name == "local"
    assert create_vision_provider(
        Settings(ai_provider="claude", anthropic_api_key="test-key")
    ).name == "claude"


def test_local_provider_extracts_labeled_invoice_fields_without_api() -> None:
    provider = LocalRuleBasedProvider()
    data = provider.extract(
        [],
        "\n".join(
            [
                "[Page 1] Supplier: Rivertech Supplies Ltd.",
                "[Page 1] Invoice No: RT-2024-1052",
                "[Page 1] Invoice Date: 14 October 2024",
                "[Page 1] Currency: NPR",
                "[Page 1] Subtotal: NPR 1,00,500.00",
                "[Page 1] VAT 13%: NPR 13,065.00",
                "[Page 1] Grand Total: NPR 1,13,565.00",
                "[Page 1] VAT Registration ID: 123456789",
            ]
        ),
    )

    assert data["supplier_name"] == "Rivertech Supplies Ltd."
    assert data["invoice_number"] == "RT-2024-1052"
    assert data["invoice_date"] == "14 October 2024"
    assert data["currency"] == "NPR"
    assert data["subtotal"] == "100500.00"
    assert data["tax_rate"] == "13"
    assert data["tax_amount"] == "13065.00"
    assert data["total_amount"] == "113565.00"
    assert data["supplier_tax_id"] == "123456789"
    assert data["items"] == []
    assert any(
        "No line items could be reliably matched" in warning
        for warning in provider.warnings
    )


def test_local_provider_uses_invoice_geometry_in_mixed_content_image() -> None:
    records = [
        (20, 11, 76, 39, "Hello,"),
        (875, 99, 1205, 122, "RIVERTECH SUPPLIES LTD"),
        (872, 152, 1037, 173, "45Industrial Estate Road"),
        (872, 173, 1035, 189, "Kathmandu 44600,Nepa"),
        (870, 270, 926, 293, "Bill To:"),
        (1221, 315, 1296, 333, "Invoice No:"),
        (1344, 314, 1435, 331, "RT-2024-1052"),
        (1221, 342, 1309, 360, "Invoice Date:"),
        (1342, 342, 1451, 360, "14 October 2024"),
        (1221, 371, 1286, 389, "Due Date:"),
        (1342, 370, 1469, 390, "13 November 2024"),
        (915, 459, 1002, 475, "Description"),
        (1145, 451, 1213, 481, "Quantity"),
        (1254, 443, 1328, 469, "Unit Price"),
        (1374, 448, 1470, 466, "Total Amount"),
        (98, 475, 707, 499, "Read the attached invoice image"),
        (912, 499, 1117, 520, "HDPE Pipe 110mm (6m length)"),
        (1155, 499, 1206, 522, "50 pcs"),
        (1280, 501, 1338, 518, "1,250.00"),
        (1406, 501, 1474, 518, "62,500.00"),
        (98, 506, 717, 530, "Use an AI tool of your choice"),
        (914, 533, 1075, 554, "HDPE Elbow 90110mm"),
        (1155, 529, 1209, 557, "20 pcs"),
        (1290, 531, 1341, 554, "450.00"),
        (1414, 534, 1475, 552, "9,000.00"),
        (99, 558, 350, 579, "Extract the following information"),
        (914, 565, 1070, 586, "HDPE Coupling 110mm"),
        (1155, 565, 1206, 587, "30 pcs"),
        (1286, 565, 1341, 588, "300.00"),
        (1413, 565, 1477, 587, "9,000.00"),
        (136, 581, 264, 602, "Invoice date"),
        (912, 595, 1023, 621, "Welding Service"),
        (1155, 597, 1205, 619, "10 hrs"),
        (1277, 597, 1341, 619, "1,500.00"),
        (1406, 600, 1474, 618, "15,000.00"),
        (128, 624, 256, 645, "Supplier name"),
        (911, 629, 1023, 655, "Delivery Charge"),
        (1163, 632, 1198, 651, "1 lot"),
        (1277, 630, 1341, 653, "5,000.00"),
        (1413, 630, 1475, 653, "5,000.00"),
        (1152, 667, 1256, 690, "Subtotal (NPR)"),
        (1398, 669, 1474, 686, "100,500.00"),
        (1154, 702, 1226, 720, "VAT13%"),
        (1405, 702, 1474, 720, "13,065.00"),
        (1154, 736, 1298, 757, "Total Amount (NPR)"),
        (1389, 738, 1472, 755, "113,565.00"),
    ]
    ocr_text = "\n".join(
        f"[Page 1 x1={x1} y1={y1} x2={x2} y2={y2}] {text}"
        for x1, y1, x2, y2, text in records
    )

    provider = LocalRuleBasedProvider()
    data = provider.extract([], ocr_text)

    assert data["supplier_name"] == "Rivertech Supplies Ltd"
    assert data["supplier_address"] == "45 Industrial Estate Road, Kathmandu 44600, Nepal"
    assert data["invoice_number"] == "RT-2024-1052"
    assert data["invoice_date"] == "14 October 2024"
    assert data["due_date"] == "13 November 2024"
    assert data["subtotal"] == "100500.00"
    assert data["tax_rate"] == "13"
    assert data["tax_amount"] == "13065.00"
    assert data["total_amount"] == "113565.00"
    assert [item["description"] for item in data["items"]] == [
        "HDPE Pipe 110mm (6m length)",
        "HDPE Elbow 90° 110mm",
        "HDPE Coupling 110mm",
        "Welding Service",
        "Delivery Charge",
    ]
    assert any("90-degree elbow marker" in warning for warning in provider.warnings)
    assert [item["line_total"] for item in data["items"]] == [
        "62500.00",
        "9000.00",
        "9000.00",
        "15000.00",
        "5000.00",
    ]


def test_local_provider_rejects_empty_ocr_text() -> None:
    with pytest.raises(ProviderError, match="no readable OCR text"):
        LocalRuleBasedProvider().extract([], "")


def test_local_provider_repairs_ocr_group_separators_with_a_warning() -> None:
    provider = LocalRuleBasedProvider()
    data = provider.extract(
        [],
        "[Page 1] Invoice No: RT-2024-1052\n"
        "[Page 1] Subtotal: NPR 100.500.00\n"
        "[Page 1] VAT 13%: NPR 13.065.00\n"
        "[Page 1] Total: NPR 113.565.00",
    )

    assert data["subtotal"] == "100500.00"
    assert data["tax_amount"] == "13065.00"
    assert data["total_amount"] == "113565.00"
    assert any(
        "subtotal" in warning and "punctuation" in warning
        for warning in provider.warnings
    )
    assert any(
        "tax amount" in warning and "punctuation" in warning
        for warning in provider.warnings
    )


def test_local_provider_does_not_treat_percentage_discount_as_money() -> None:
    provider = LocalRuleBasedProvider()
    data = provider.extract(
        [],
        "[Page 1] Invoice No: RT-2024-1052\n"
        "[Page 1] Discount: 10%\n"
        "[Page 1] Subtotal: NPR 100.00\n"
        "[Page 1] Total: USD 90.00",
    )

    assert data["discount"] is None
    assert data["currency"] is None
    assert any("discount" in warning for warning in provider.warnings)
    assert any("Conflicting currency codes" in warning for warning in provider.warnings)


def test_pipeline_uses_local_rules_without_provider_credentials() -> None:
    ocr = StubOCR(
        [
            OCRLine("Supplier: Rivertech Supplies Ltd.", 1, [0, 0, 20, 0], 0.96),
            OCRLine("Invoice No: RT-2024-1052", 1, [0, 2, 20, 2], 0.98),
            OCRLine("Invoice Date: 14 October 2024", 1, [0, 4, 20, 4], 0.94),
            OCRLine("Currency: NPR", 1, [0, 6, 20, 6], 0.99),
            OCRLine("Subtotal: NPR 100,500.00", 1, [0, 8, 20, 8], 0.91),
            OCRLine("VAT 13%: NPR 13,065.00", 1, [0, 10, 20, 10], 0.9),
            OCRLine("Grand Total: NPR 113,565.00", 1, [0, 12, 20, 12], 0.97),
        ]
    )
    result = extract_document(
        _png_bytes(),
        "invoice.png",
        settings=Settings(ai_provider="local"),
        ocr_service=ocr,
    )

    assert result.error is None
    assert result.provider == "local"
    assert result.invoice is not None
    assert result.invoice.supplier_name == "Rivertech Supplies Ltd."
    assert result.invoice.invoice_number == "RT-2024-1052"
    assert result.invoice.total_amount == Decimal("113565.00")
    assert result.invoice.items == []
    assert result.validation is not None
    assert any("line items" in warning for warning in result.warnings)
    assert result.invoice.field_evidence["invoice_number"].extraction_provider == "local"


def test_pipeline_preserves_ocr_when_vision_provider_is_unavailable() -> None:
    ocr = StubOCR([OCRLine("Invoice RT-2024-1052", 1, [0, 0, 10, 0], 0.95)])

    def unavailable_provider() -> StubProvider:
        raise ProviderError("Gemini returned HTTP 503.")

    result = extract_document(
        _png_bytes(),
        "invoice.png",
        settings=Settings(),
        ocr_service=ocr,
        provider_factory=unavailable_provider,
    )

    assert result.invoice is None
    assert result.error == "Gemini returned HTTP 503."
    assert result.ocr_lines[0].text == "Invoice RT-2024-1052"
    assert "preserved for review" in result.warnings[-1]


def test_pipeline_passes_ocr_to_provider_and_attaches_evidence() -> None:
    ocr_line = OCRLine("Invoice RT-2024-1052", 1, [0, 0, 20, 0], 0.97)
    ocr = StubOCR([ocr_line])
    provider = StubProvider()

    result = extract_document(
        _png_bytes(),
        "invoice.png",
        settings=Settings(),
        ocr_service=ocr,
        provider_factory=lambda: provider,
    )

    assert result.error is None
    assert result.invoice is not None
    assert result.validation is not None
    assert provider.ocr_text == "[Page 1] Invoice RT-2024-1052"
    assert result.invoice.field_evidence["invoice_number"].page_number == 1


def test_pipeline_can_continue_with_vision_when_ocr_is_unavailable() -> None:
    class BrokenOCR:
        def __init__(self) -> None:
            self.page_count = 0

        def extract(self, pages: list[VisionPage]) -> list[OCRLine]:
            self.page_count = len(pages)
            raise OCRUnavailableError("OCR models are unavailable.")

    broken_ocr = BrokenOCR()
    result = extract_document(
        _png_bytes(),
        "invoice.png",
        settings=Settings(),
        ocr_service=broken_ocr,
        provider_factory=lambda: StubProvider(),
    )

    assert result.invoice is not None
    assert broken_ocr.page_count == 1
    assert result.warnings[0] == "OCR models are unavailable."
    assert result.ocr_lines == []


def test_model_response_must_be_json_object() -> None:
    response = httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": "[]"}]}}]},
        request=httpx.Request("POST", "https://example.test"),
    )
    with patch("app.providers.gemini.httpx.post", return_value=response):
        with pytest.raises(ProviderError, match="JSON object"):
            GeminiVisionProvider("secret").extract(
                [VisionPage(1, "image/png", b"sample")], ""
            )
