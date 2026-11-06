from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from app.schemas.invoice import InvoiceData

AMOUNT_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
QUANTITY_PATTERN = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*(.*?)\s*$")


class ExtractionNormalizationError(Exception):
    """Raised when a provider response cannot be normalized into invoice data."""


def _normalize_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ExtractionNormalizationError(f"AI returned an invalid {field_name}.")
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        cleaned = re.sub(r"^(?:NPR|USD|EUR|GBP|Rs\.?)\s*", "", cleaned, flags=re.I)
        cleaned = cleaned.rstrip("%").strip()
        if not AMOUNT_PATTERN.fullmatch(cleaned):
            raise ExtractionNormalizationError(f"AI returned an invalid {field_name}.")
        value = cleaned
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ExtractionNormalizationError(
            f"AI returned an invalid {field_name}."
        ) from None
    if not amount.is_finite():
        raise ExtractionNormalizationError(f"AI returned an invalid {field_name}.")
    return amount


def _normalize_date(value: Any) -> tuple[date | None, str | None]:
    if value is None or value == "":
        return None, None
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if not isinstance(value, str):
        return None, "A date was returned in an unsupported format."

    text = " ".join(value.strip().split())
    try:
        return date.fromisoformat(text), None
    except ValueError:
        pass

    for date_format in ("%d %B %Y", "%d %b %Y", "%Y/%m/%d", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(text, date_format).date(), None
        except ValueError:
            continue

    numeric = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
    if numeric:
        first, second, year = (int(part) for part in numeric.groups())
        if first <= 12 and second <= 12 and first != second:
            return None, f"Date '{text}' is ambiguous; confirm it during review."
        if first > 12:
            day, month = first, second
        else:
            month, day = first, second
        try:
            return date(year, month, day), None
        except ValueError:
            return None, f"Date '{text}' is invalid."

    return None, f"Date '{text}' could not be normalized."


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExtractionNormalizationError("AI returned an invalid text field.")
    cleaned = " ".join(value.split())
    return cleaned or None


def _normalize_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ExtractionNormalizationError(f"AI returned invalid line item {index}.")

    raw_quantity = item.get("quantity")
    unit = _clean_text(item.get("unit"))
    if isinstance(raw_quantity, str):
        match = QUANTITY_PATTERN.fullmatch(raw_quantity)
        if match:
            quantity = _normalize_decimal(match.group(1), f"item {index} quantity")
            unit = unit or _clean_text(match.group(2))
        else:
            quantity = None
    else:
        quantity = _normalize_decimal(raw_quantity, f"item {index} quantity")

    return {
        "description": _clean_text(item.get("description")),
        "quantity": quantity,
        "unit": unit,
        "unit_price": _normalize_decimal(item.get("unit_price"), f"item {index} unit price"),
        "line_total": _normalize_decimal(item.get("line_total"), f"item {index} line total"),
        "currency": (_clean_text(item.get("currency")) or "").upper() or None,
        "source_evidence": {},
        "manually_corrected": False,
    }


def normalize_extraction(data: Any) -> tuple[InvoiceData, list[str]]:
    """Normalize provider JSON and report dates that need a human decision."""
    if not isinstance(data, dict):
        raise ExtractionNormalizationError("AI response must be a JSON object.")

    warnings: list[str] = []
    normalized: dict[str, Any] = {}
    for field in ("invoice_date", "due_date"):
        parsed_date, warning = _normalize_date(data.get(field))
        normalized[field] = parsed_date
        if warning:
            warnings.append(warning)

    items = data.get("items", [])
    if not isinstance(items, list):
        raise ExtractionNormalizationError("AI returned invalid line items.")

    normalized.update(
        {
            "supplier_name": _clean_text(data.get("supplier_name")),
            "supplier_address": _clean_text(data.get("supplier_address")),
            "supplier_tax_id": _clean_text(data.get("supplier_tax_id")),
            "invoice_number": _clean_text(data.get("invoice_number")),
            "currency": (_clean_text(data.get("currency")) or "").upper() or None,
            "items": [_normalize_item(item, index) for index, item in enumerate(items, 1)],
            "subtotal": _normalize_decimal(data.get("subtotal"), "subtotal"),
            "discount": _normalize_decimal(data.get("discount"), "discount"),
            "tax_rate": _normalize_decimal(data.get("tax_rate"), "tax rate"),
            "tax_amount": _normalize_decimal(data.get("tax_amount"), "tax amount"),
            "additional_charges": _normalize_decimal(
                data.get("additional_charges"), "additional charges"
            ),
            "total_amount": _normalize_decimal(data.get("total_amount"), "total amount"),
            "field_evidence": {},
        }
    )
    try:
        return InvoiceData.model_validate(normalized), warnings
    except ValidationError as exc:
        raise ExtractionNormalizationError(
            "AI response did not match the invoice data schema."
        ) from exc
