from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterator
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import invoices as invoice_api
from app.config import Settings
from app.database import Base, get_db
from app.main import app
from app.models import Invoice, InvoiceItem
from app.providers.base import VisionPage
from app.schemas.invoice import InvoiceData
from app.services.extraction_pipeline import ExtractionResult, extract_document as run_extraction
from app.services.ocr_service import OCRLine
from app.services.validator import validate_invoice


def _sample_invoice() -> InvoiceData:
    return InvoiceData.model_validate(
        {
            "supplier_name": "Rivertech Supplies Ltd.",
            "supplier_address": "45 Industrial Estate Road",
            "invoice_number": "RT-2024-1052",
            "invoice_date": "2024-10-14",
            "due_date": "2024-11-13",
            "currency": "NPR",
            "items": [
                {
                    "description": "HDPE pipe",
                    "quantity": "1",
                    "unit": "pcs",
                    "unit_price": "100.00",
                    "line_total": "100.00",
                    "currency": "NPR",
                }
            ],
            "subtotal": "100.00",
            "discount": "0.00",
            "tax_rate": "0",
            "tax_amount": "0.00",
            "additional_charges": "0.00",
            "total_amount": "100.00",
            "field_evidence": {
                "invoice_number": {
                    "extracted_value": "RT-2024-1052",
                    "original_source_text": "Invoice RT-2024-1052",
                    "page_number": 1,
                    "bounding_box": [1, 2, 3, 4],
                    "ocr_confidence": 0.97,
                    "extraction_provider": "mock",
                }
            },
        }
    )


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(output, format="PNG")
    return output.getvalue()


def _extraction_result(invoice: InvoiceData | None = None) -> ExtractionResult:
    extracted = invoice or _sample_invoice()
    return ExtractionResult(
        filename="invoice.png",
        source_type="image/png",
        page_count=1,
        ocr_lines=[OCRLine("Invoice RT-2024-1052", 1, [1, 2, 3, 4], 0.97)],
        invoice=extracted,
        raw_extraction={"invoice_number": extracted.invoice_number},
        provider="mock",
        validation=validate_invoice(extracted),
        warnings=[],
    )


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        with test_sessions() as session:
            yield session

    settings = Settings(
        database_url="sqlite://",
        storage_dir=str(tmp_path / "documents"),
        max_upload_size_mb=1,
    )
    monkeypatch.setattr(invoice_api, "get_settings", lambda: settings)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _upload_mock(monkeypatch: pytest.MonkeyPatch, result: ExtractionResult) -> None:
    monkeypatch.setattr(invoice_api, "extract_document", lambda *args, **kwargs: result)


def test_upload_runs_local_extraction_without_external_provider(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ocr_lines = [
        OCRLine("Supplier: Rivertech Supplies Ltd.", 1, [0, 0, 10, 0], 0.96),
        OCRLine("Invoice No: RT-2024-1052", 1, [0, 2, 10, 2], 0.98),
        OCRLine("Invoice Date: 14 October 2024", 1, [0, 4, 10, 4], 0.94),
        OCRLine("Currency: NPR", 1, [0, 6, 10, 6], 0.99),
        OCRLine("Subtotal: NPR 100,500.00", 1, [0, 8, 10, 8], 0.91),
        OCRLine("VAT 13%: NPR 13,065.00", 1, [0, 10, 10, 10], 0.9),
        OCRLine("Grand Total: NPR 113,565.00", 1, [0, 12, 10, 12], 0.97),
    ]

    class StaticOCR:
        def extract(self, pages: list[VisionPage]) -> list[OCRLine]:
            del pages
            return ocr_lines

    monkeypatch.setattr(
        invoice_api,
        "extract_document",
        lambda content, filename, **kwargs: run_extraction(
            content,
            filename,
            settings=invoice_api.get_settings(),
            ocr_service=StaticOCR(),
        ),
    )
    response = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "COMPLETED"
    assert body["invoice_number"] == "RT-2024-1052"
    assert body["total_amount"] == "113565.00"
    assert body["extraction_metadata"]["provider"] == "local"
    assert any(
        "No line items could be reliably matched" in warning
        for warning in body["extraction_metadata"]["warnings"]
    )


def test_upload_persists_invoice_evidence_and_original_document(
    api_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upload_mock(monkeypatch, _extraction_result())

    response = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["invoice_number"] == "RT-2024-1052"
    assert data["processing_status"] == "COMPLETED"
    assert data["validation_status"] == "PASSED"
    assert data["items"][0]["currency"] == "NPR"
    assert data["field_evidence"]["invoice_number"]["ocr_confidence"] == 0.97
    assert data["extraction_metadata"]["ocr_lines"][0]["page_number"] == 1
    stored_path = next((tmp_path / "documents").iterdir())
    assert stored_path.read_bytes() == _png_bytes()
    assert stored_path.name != "invoice.png"


def test_upload_retains_ocr_if_provider_returns_failure(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = ExtractionResult(
        filename="invoice.png",
        source_type="image/png",
        page_count=1,
        ocr_lines=[OCRLine("Invoice RT-2024-1052", 1, [1, 2, 3, 4], 0.97)],
        error="GEMINI_API_KEY is not configured.",
        warnings=["OCR preserved"],
    )
    _upload_mock(monkeypatch, result)

    response = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "FAILED"
    assert body["processing_error"] == "GEMINI_API_KEY is not configured."
    assert body["invoice_number"] is None
    assert body["extraction_metadata"]["ocr_lines"][0]["text"] == (
        "Invoice RT-2024-1052"
    )


def test_upload_rejects_mime_extension_and_signature_mismatches(
    api_client: TestClient,
) -> None:
    wrong_mime = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "application/pdf")},
    )
    wrong_signature = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", b"%PDF-not-a-png", "image/png")},
    )
    unsupported = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.exe", b"nope", "application/octet-stream")},
    )

    assert wrong_mime.status_code == 415
    assert wrong_signature.status_code == 422
    assert unsupported.status_code == 415


def test_upload_enforces_configured_size_limit(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", b"x" * (1024 * 1024 + 1), "image/png")},
    )

    assert response.status_code == 413


def test_invoice_history_search_filter_sort_and_pagination(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index, name in enumerate(("Rivertech", "Northwind", "Rivertech"), start=1):
        invoice = _sample_invoice()
        invoice.supplier_name = name
        invoice.invoice_number = f"INV-{index}"
        invoice.total_amount = Decimal(100 * index)
        _upload_mock(monkeypatch, _extraction_result(invoice))
        response = api_client.post(
            "/api/invoices/upload",
            files={"file": (f"{index}.png", _png_bytes(), "image/png")},
        )
        assert response.status_code == 201

    response = api_client.get(
        "/api/invoices",
        params={"q": "rivertech", "sort_by": "total_amount", "order": "desc", "page": 1, "page_size": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["pages"] == 2
    assert body["items"][0]["supplier_name"] == "Rivertech"
    assert body["items"][0]["total_amount"] == "300.00"


def test_patch_marks_corrections_and_revalidates(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upload_mock(monkeypatch, _extraction_result())
    uploaded = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    ).json()

    response = api_client.patch(
        f"/api/invoices/{uploaded['id']}",
        json={"total_amount": "115.00", "supplier_name": "Rivertech Supplies Ltd."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_amount"] == "115.00"
    assert body["field_evidence"]["total_amount"]["extracted_value"] == "100.00"
    assert body["field_evidence"]["total_amount"]["manually_corrected"] is True
    assert body["validation_status"] == "FAILED"
    assert any(item["check_name"] == "grand_total" for item in body["validation_results"])


def test_validate_endpoint_replaces_saved_check_results(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upload_mock(monkeypatch, _extraction_result())
    uploaded = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    ).json()

    response = api_client.post(f"/api/invoices/{uploaded['id']}/validate")

    assert response.status_code == 200
    assert response.json()["validation"]["status"] == "PASSED"
    assert response.json()["validation"]["failed_checks"] == 0


def test_invoice_export_and_document_preview(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _upload_mock(monkeypatch, _extraction_result())
    uploaded = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    ).json()

    exported = api_client.get(f"/api/invoices/{uploaded['id']}/export")
    preview = api_client.get(f"/api/invoices/{uploaded['id']}/document")

    assert exported.status_code == 200
    assert exported.headers["content-disposition"].endswith(
        f'invoice-{uploaded["id"]}.json"'
    )
    assert exported.json()["invoice_number"] == "RT-2024-1052"
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content == _png_bytes()


def test_dashboard_uses_records_and_groups_values_by_currency(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice = _sample_invoice()
    _upload_mock(monkeypatch, _extraction_result(invoice))
    uploaded = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    )
    assert uploaded.status_code == 201

    failed_result = ExtractionResult(
        filename="failed.png",
        source_type="image/png",
        page_count=1,
        error="Vision provider unavailable.",
    )
    _upload_mock(monkeypatch, failed_result)
    failed = api_client.post(
        "/api/invoices/upload",
        files={"file": ("failed.png", _png_bytes(), "image/png")},
    )
    assert failed.status_code == 201

    response = api_client.get("/api/dashboard/stats")

    assert response.status_code == 200
    stats = response.json()
    assert stats["total_invoices"] == 2
    assert stats["successfully_validated"] == 1
    assert stats["failed_processing"] == 1
    assert stats["needs_review"] == 1
    assert stats["total_invoice_value"] == {"NPR": "100.00"}


def test_delete_removes_invoice_and_stored_document(
    api_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upload_mock(monkeypatch, _extraction_result())
    uploaded = api_client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", _png_bytes(), "image/png")},
    ).json()
    stored_files = list((tmp_path / "documents").iterdir())
    assert len(stored_files) == 1

    response = api_client.delete(f"/api/invoices/{uploaded['id']}")

    assert response.status_code == 204
    assert list((tmp_path / "documents").iterdir()) == []
    assert api_client.get(f"/api/invoices/{uploaded['id']}").status_code == 404


def test_unknown_invoice_and_empty_patch_return_clear_errors(api_client: TestClient) -> None:
    missing = api_client.get("/api/invoices/999")
    empty_patch = api_client.patch("/api/invoices/999", json={})

    assert missing.status_code == 404
    assert missing.json()["detail"] == "Invoice not found."
    assert empty_patch.status_code == 404
