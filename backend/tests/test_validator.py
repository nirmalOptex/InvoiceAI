from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from app.config import Settings
from app.schemas.invoice import CheckStatus, InvoiceData, ValidationStatus
from app.services.validator import validate_invoice

SAMPLE_INVOICE = {
    "supplier_name": "RIVERTECH SUPPLIES LTD.",
    "invoice_number": "RT-2024-1052",
    "invoice_date": date(2024, 10, 14),
    "due_date": date(2024, 11, 13),
    "currency": "NPR",
    "items": [
        {
            "description": "HDPE Pipe 110mm (6m length)",
            "quantity": "50",
            "unit": "pcs",
            "unit_price": "1250.00",
            "line_total": "62500.00",
            "currency": "NPR",
        },
        {
            "description": "HDPE Elbow 90° 110mm",
            "quantity": "20",
            "unit": "pcs",
            "unit_price": "450.00",
            "line_total": "9000.00",
            "currency": "NPR",
        },
        {
            "description": "HDPE Coupling 110mm",
            "quantity": "30",
            "unit": "pcs",
            "unit_price": "300.00",
            "line_total": "9000.00",
            "currency": "NPR",
        },
        {
            "description": "Welding Service",
            "quantity": "10",
            "unit": "hrs",
            "unit_price": "1500.00",
            "line_total": "15000.00",
            "currency": "NPR",
        },
        {
            "description": "Delivery Charge",
            "quantity": "1",
            "unit": "lot",
            "unit_price": "5000.00",
            "line_total": "5000.00",
            "currency": "NPR",
        },
    ],
    "subtotal": "100500.00",
    "discount": "0.00",
    "tax_rate": "13",
    "tax_amount": "13065.00",
    "additional_charges": "0.00",
    "total_amount": "113565.00",
}


def _invoice(overrides: dict | None = None) -> InvoiceData:
    data = deepcopy(SAMPLE_INVOICE)
    if overrides:
        data.update(overrides)
    return InvoiceData.model_validate(data)


def _check(report, name: str):
    return next(check for check in report.checks if check.check_name == name)


def test_sample_invoice_financials_pass_all_checks() -> None:
    invoice = _invoice()

    report = validate_invoice(invoice)

    assert report.status == ValidationStatus.PASSED
    assert report.failed_checks == 0
    assert report.warning_checks == 0
    assert report.not_checked == 0
    assert _check(report, "subtotal_matches_line_items").status == CheckStatus.PASSED
    assert _check(report, "tax_calculation").expected_value == "13,065.00"
    assert _check(report, "grand_total").expected_value == "113,565.00"


def test_assignment_grand_total_difference_is_exactly_2000() -> None:
    invoice = _invoice({"total_amount": "115565.00"})
    original_total = invoice.total_amount

    report = validate_invoice(invoice)
    grand_total = _check(report, "grand_total")

    assert grand_total.status == CheckStatus.FAILED
    assert grand_total.expected_value == "113,565.00"
    assert grand_total.actual_value == "115,565.00"
    assert grand_total.difference == Decimal("2000.00")
    assert report.status == ValidationStatus.FAILED
    assert invoice.total_amount == original_total


def test_line_item_calculation_detects_printed_total_mismatch() -> None:
    data = deepcopy(SAMPLE_INVOICE)
    data["items"][0]["line_total"] = "64500.00"

    report = validate_invoice(InvoiceData.model_validate(data))

    result = _check(report, "line_item_1_calculation")
    assert result.status == CheckStatus.FAILED
    assert result.difference == Decimal("2000.00")
    assert _check(report, "subtotal_matches_line_items").status == CheckStatus.FAILED


def test_subtotal_check_reports_its_difference() -> None:
    report = validate_invoice(_invoice({"subtotal": "102500.00"}))
    subtotal = _check(report, "subtotal_matches_line_items")

    assert subtotal.status == CheckStatus.FAILED
    assert subtotal.expected_value == "100,500.00"
    assert subtotal.actual_value == "102,500.00"
    assert subtotal.difference == Decimal("2000.00")


def test_tax_calculation_uses_extracted_rate_not_a_fixed_vat_rate() -> None:
    invoice = _invoice(
        {
            "subtotal": "1000.00",
            "discount": "0.00",
            "tax_rate": "5",
            "tax_amount": "50.00",
            "additional_charges": "0.00",
            "total_amount": "1050.00",
            "items": [],
        }
    )

    report = validate_invoice(invoice)

    tax = _check(report, "tax_calculation")
    assert tax.status == CheckStatus.PASSED
    assert tax.expected_value == "50.00"


def test_tax_mismatch_is_failed_and_a_missing_rate_is_not_invented() -> None:
    mismatch = validate_invoice(_invoice({"tax_amount": "13000.00"}))
    missing = validate_invoice(_invoice({"tax_rate": None}))

    assert _check(mismatch, "tax_calculation").status == CheckStatus.FAILED
    assert _check(missing, "tax_calculation").status == CheckStatus.NOT_CHECKED
    assert _check(missing, "tax_calculation").expected_value is None


def test_missing_adjustment_data_leaves_grand_total_unchecked() -> None:
    invoice = _invoice({"discount": None})

    report = validate_invoice(invoice)

    assert _check(report, "grand_total").status == CheckStatus.NOT_CHECKED
    assert report.status == ValidationStatus.WARNING


def test_additional_charges_with_unspecified_tax_treatment_skip_tax_check() -> None:
    invoice = _invoice(
        {"additional_charges": "100.00", "total_amount": "113665.00"}
    )

    report = validate_invoice(invoice)

    assert _check(report, "tax_calculation").status == CheckStatus.NOT_CHECKED
    assert "treatment of additional charges" in _check(
        report, "tax_calculation"
    ).message
    assert _check(report, "grand_total").status == CheckStatus.PASSED


def test_currency_conflict_and_due_date_before_invoice_are_failed() -> None:
    data = deepcopy(SAMPLE_INVOICE)
    data["items"][0]["currency"] = "USD"
    data["due_date"] = date(2024, 10, 13)

    report = validate_invoice(InvoiceData.model_validate(data))

    assert _check(report, "currency_consistency").status == CheckStatus.FAILED
    assert _check(report, "date_consistency").status == CheckStatus.FAILED


def test_missing_required_fields_produce_manual_review_warning() -> None:
    invoice = _invoice(
        {
            "supplier_name": None,
            "invoice_number": None,
            "invoice_date": None,
            "currency": None,
            "total_amount": None,
        }
    )

    report = validate_invoice(invoice)

    completeness = _check(report, "required_fields")
    assert completeness.status == CheckStatus.WARNING
    assert "supplier name" in completeness.message
    assert report.status == ValidationStatus.WARNING


@pytest.mark.parametrize("tolerance", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_tolerance_is_rejected(tolerance: Decimal) -> None:
    with pytest.raises(ValueError, match="finite, non-negative"):
        validate_invoice(_invoice(), tolerance=tolerance)


def test_configured_rounding_tolerance_is_applied() -> None:
    invoice = _invoice({"total_amount": "113565.02"})

    report = validate_invoice(
        invoice,
        settings=Settings(financial_rounding_tolerance=Decimal("0.02")),
    )

    assert _check(report, "grand_total").status == CheckStatus.PASSED
