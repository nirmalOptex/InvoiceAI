from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app
from app.models import Invoice, InvoiceItem, ValidationResult
from app.schemas.invoice import InvoiceCorrection, InvoiceData


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "InvoiceIQ"}


def test_cors_origins_parse_localhost_and_loopback() -> None:
    settings = Settings(
        cors_origins="http://localhost:5173,http://127.0.0.1:5173"
    )
    assert settings.allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_invoice_schema_keeps_money_as_decimal() -> None:
    invoice = InvoiceData.model_validate(
        {
            "supplier_name": "Rivertech Supplies Ltd.",
            "invoice_number": "RT-2024-1052",
            "invoice_date": "2024-10-14",
            "currency": "NPR",
            "subtotal": "100500.00",
            "tax_rate": "13",
            "tax_amount": "13065.00",
            "total_amount": "113565.00",
        }
    )

    assert invoice.invoice_date == date(2024, 10, 14)
    assert invoice.subtotal == Decimal("100500.00")
    assert invoice.total_amount == Decimal("113565.00")


def test_invoice_correction_rejects_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        InvoiceCorrection.model_validate({"totl_amount": "100.00"})


def test_database_models_register_expected_tables() -> None:
    assert set(Invoice.metadata.tables) == {
        "invoices",
        "invoice_items",
        "validation_results",
    }

    assert InvoiceItem.__tablename__ == "invoice_items"
    assert ValidationResult.__tablename__ == "validation_results"
