from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.config import Settings, get_settings
from app.schemas.invoice import (
    CheckStatus,
    InvoiceData,
    ValidationCheck,
    ValidationReport,
    ValidationStatus,
)

CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _format(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:,.2f}"


def _check(
    name: str,
    status: CheckStatus,
    message: str,
    *,
    expected: Decimal | date | str | None = None,
    actual: Decimal | date | str | None = None,
    difference: Decimal | None = None,
) -> ValidationCheck:
    return ValidationCheck(
        check_name=name,
        expected_value=(
            _format(expected) if isinstance(expected, Decimal) else str(expected) if expected is not None else None
        ),
        actual_value=(
            _format(actual) if isinstance(actual, Decimal) else str(actual) if actual is not None else None
        ),
        difference=difference,
        status=status,
        message=message,
    )


def _unavailable(name: str, reason: str) -> ValidationCheck:
    return _check(name, CheckStatus.NOT_CHECKED, reason)


def _amount_check(
    name: str,
    expected: Decimal,
    actual: Decimal,
    tolerance: Decimal,
    description: str,
) -> ValidationCheck:
    difference = actual - expected
    passed = abs(difference) <= tolerance
    status = CheckStatus.PASSED if passed else CheckStatus.FAILED
    message = (
        f"{description}: expected {expected:,.2f}, found {actual:,.2f}."
        if not passed
        else f"{description}: matches within {tolerance:,.2f}."
    )
    return _check(
        name,
        status,
        message,
        expected=expected,
        actual=actual,
        difference=difference,
    )


def _line_item_checks(
    invoice: InvoiceData, tolerance: Decimal
) -> tuple[list[ValidationCheck], Decimal | None]:
    checks: list[ValidationCheck] = []
    subtotal_parts: list[Decimal] = []

    for index, item in enumerate(invoice.items, start=1):
        expected = (
            _money(item.quantity * item.unit_price)
            if item.quantity is not None and item.unit_price is not None
            else None
        )
        if expected is not None and item.line_total is not None:
            checks.append(
                _amount_check(
                    f"line_item_{index}_calculation",
                    expected,
                    item.line_total,
                    tolerance,
                    f"Line item {index} quantity × unit price",
                )
            )
        else:
            missing = []
            if item.quantity is None:
                missing.append("quantity")
            if item.unit_price is None:
                missing.append("unit price")
            if item.line_total is None:
                missing.append("printed line total")
            checks.append(
                _unavailable(
                    f"line_item_{index}_calculation",
                    f"Cannot verify line item {index}; missing {', '.join(missing)}.",
                )
            )

        subtotal_amount = item.line_total if item.line_total is not None else expected
        if subtotal_amount is not None:
            subtotal_parts.append(subtotal_amount)
        else:
            subtotal_parts.append(Decimal("NaN"))

    if not invoice.items:
        checks.append(
            _unavailable("line_items", "No line items were identified.")
        )
        return checks, None

    if all(amount.is_finite() for amount in subtotal_parts):
        return checks, sum(subtotal_parts, Decimal(0))
    return checks, None


def validate_invoice(
    invoice: InvoiceData,
    *,
    tolerance: Decimal | None = None,
    settings: Settings | None = None,
) -> ValidationReport:
    """Validate extracted invoice data without modifying or filling its values."""
    if tolerance is None:
        tolerance = (settings or get_settings()).financial_rounding_tolerance
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError("tolerance must be a finite, non-negative Decimal.")

    checks: list[ValidationCheck] = []

    required_fields = {
        "supplier_name": invoice.supplier_name,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "currency": invoice.currency,
        "total_amount": invoice.total_amount,
    }
    missing = [field.replace("_", " ") for field, value in required_fields.items() if not value]
    if missing:
        checks.append(
            _check(
                "required_fields",
                CheckStatus.WARNING,
                f"Manual review required; missing {', '.join(missing)}.",
            )
        )
    else:
        checks.append(
            _check(
                "required_fields",
                CheckStatus.PASSED,
                "Supplier, invoice number, invoice date, currency, and total are present.",
            )
        )

    line_checks, line_sum = _line_item_checks(invoice, tolerance)
    checks.extend(line_checks)
    if invoice.subtotal is None:
        checks.append(
            _unavailable("subtotal_matches_line_items", "Subtotal was not identified.")
        )
    elif line_sum is None:
        checks.append(
            _unavailable(
                "subtotal_matches_line_items",
                "Cannot verify subtotal because one or more line-item amounts are missing.",
            )
        )
    else:
        checks.append(
            _amount_check(
                "subtotal_matches_line_items",
                line_sum,
                invoice.subtotal,
                tolerance,
                "Sum of line items against subtotal",
            )
        )

    if invoice.tax_rate is None or invoice.tax_amount is None or invoice.subtotal is None:
        checks.append(
            _unavailable(
                "tax_calculation",
                "Cannot verify tax without the extracted tax rate, tax amount, and subtotal.",
            )
        )
    elif invoice.discount is None:
        checks.append(
            _unavailable(
                "tax_calculation",
                "Cannot verify the taxable base because discount information was not identified.",
            )
        )
    elif invoice.additional_charges not in (Decimal(0),):
        checks.append(
            _unavailable(
                "tax_calculation",
                "Tax treatment of additional charges is not specified; the taxable base is ambiguous.",
            )
        )
    else:
        discount = invoice.discount
        taxable_base = invoice.subtotal - discount
        if taxable_base < 0:
            checks.append(
                _check(
                    "tax_calculation",
                    CheckStatus.FAILED,
                    "Discount exceeds the subtotal, so the taxable base is negative.",
                    expected=Decimal(0),
                    actual=taxable_base,
                    difference=taxable_base,
                )
            )
        else:
            expected_tax = _money(taxable_base * invoice.tax_rate / Decimal(100))
            checks.append(
                _amount_check(
                    "tax_calculation",
                    expected_tax,
                    invoice.tax_amount,
                    tolerance,
                    f"Tax at the document's {invoice.tax_rate}% rate",
                )
            )

    total_components = (
        invoice.subtotal,
        invoice.tax_amount,
        invoice.discount,
        invoice.additional_charges,
    )
    if invoice.total_amount is None or any(value is None for value in total_components):
        checks.append(
            _unavailable(
                "grand_total",
                "Cannot verify grand total; subtotal, discount, tax, charges, and total must be identified.",
            )
        )
    else:
        subtotal, tax, discount, charges = total_components
        expected_total = _money(subtotal - discount + tax + charges)
        checks.append(
            _amount_check(
                "grand_total",
                expected_total,
                invoice.total_amount,
                tolerance,
                "Subtotal − discount + tax + additional charges",
            )
        )

    if invoice.due_date is None or invoice.invoice_date is None:
        checks.append(
            _unavailable(
                "date_consistency",
                "Cannot compare invoice and due dates because one or both dates are missing.",
            )
        )
    elif invoice.due_date < invoice.invoice_date:
        checks.append(
            _check(
                "date_consistency",
                CheckStatus.FAILED,
                "Due date is earlier than the invoice date.",
                expected=f"on or after {invoice.invoice_date.isoformat()}",
                actual=invoice.due_date,
            )
        )
    else:
        checks.append(
            _check(
                "date_consistency",
                CheckStatus.PASSED,
                "Due date is on or after the invoice date.",
                expected=f"on or after {invoice.invoice_date.isoformat()}",
                actual=invoice.due_date,
            )
        )

    item_currencies = {
        item.currency.upper()
        for item in invoice.items
        if item.currency is not None
    }
    if invoice.currency is None:
        checks.append(
            _unavailable(
                "currency_consistency",
                "Cannot verify currency consistency because invoice currency is missing.",
            )
        )
    elif item_currencies and item_currencies != {invoice.currency.upper()}:
        checks.append(
            _check(
                "currency_consistency",
                CheckStatus.FAILED,
                "One or more line-item currencies conflict with the invoice currency.",
                expected=invoice.currency.upper(),
                actual=", ".join(sorted(item_currencies)),
            )
        )
    else:
        checks.append(
            _check(
                "currency_consistency",
                CheckStatus.PASSED,
                "No conflicting line-item currency declarations were found.",
                expected=invoice.currency.upper(),
                actual=", ".join(sorted(item_currencies)) if item_currencies else invoice.currency.upper(),
            )
        )

    statuses = {check.status for check in checks}
    if CheckStatus.FAILED in statuses:
        overall_status = ValidationStatus.FAILED
    elif CheckStatus.WARNING in statuses or CheckStatus.NOT_CHECKED in statuses:
        overall_status = ValidationStatus.WARNING
    else:
        overall_status = ValidationStatus.PASSED

    return ValidationReport(
        status=overall_status,
        checks=checks,
        passed_checks=sum(check.status == CheckStatus.PASSED for check in checks),
        failed_checks=sum(check.status == CheckStatus.FAILED for check in checks),
        warning_checks=sum(check.status == CheckStatus.WARNING for check in checks),
        not_checked=sum(check.status == CheckStatus.NOT_CHECKED for check in checks),
    )
