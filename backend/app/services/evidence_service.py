from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.invoice import FieldEvidence, InvoiceData
from app.services.ocr_service import OCRLine


def _canonical_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _line_matches(value: Any, text: str) -> bool:
    if value is None:
        return False
    expected = _canonical_text(str(value))
    source = _canonical_text(text)
    if expected and expected in source:
        return True

    try:
        expected_amount = Decimal(expected.replace(",", "").replace("%", ""))
    except InvalidOperation:
        return False

    for token in re.findall(r"(?<![\w/])[+-]?\d[\d.,]*%?(?![\w/.,])", source):
        try:
            numeric = token.rstrip("%")
            if re.fullmatch(r"\d{1,3}(?:\.\d{2})*\.\d{3}\.\d{2}", numeric):
                groups = numeric.split(".")
                numeric = "".join(groups[:-1]) + "." + groups[-1]
            elif "," in numeric:
                standard_grouping = re.fullmatch(
                    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", numeric
                )
                nepali_grouping = re.fullmatch(
                    r"\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?", numeric
                )
                if standard_grouping is None and nepali_grouping is None:
                    continue
                numeric = numeric.replace(",", "")
            if Decimal(numeric) == expected_amount:
                return True
        except InvalidOperation:
            continue
    return False


def _evidence(value: Any, lines: list[OCRLine], provider: str) -> FieldEvidence | None:
    matching_lines = [line for line in lines if _line_matches(value, line.text)]
    if len(matching_lines) != 1:
        return None
    line = matching_lines[0]
    return FieldEvidence(
        extracted_value=value,
        original_source_text=line.text,
        page_number=line.page_number,
        bounding_box=line.bounding_box,
        ocr_confidence=line.confidence,
        extraction_provider=provider,
    )


def attach_ocr_evidence(
    invoice: InvoiceData, lines: list[OCRLine], provider: str
) -> InvoiceData:
    """Attach OCR evidence only when extracted values can be found in OCR text."""
    scalar_fields = (
        "supplier_name",
        "supplier_address",
        "supplier_tax_id",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "discount",
        "tax_rate",
        "tax_amount",
        "additional_charges",
        "total_amount",
    )
    for field in scalar_fields:
        value = getattr(invoice, field)
        evidence = _evidence(value, lines, provider)
        if evidence is not None:
            invoice.field_evidence[field] = evidence

    for item in invoice.items:
        for field in ("description", "quantity", "unit", "unit_price", "line_total"):
            evidence = _evidence(getattr(item, field), lines, provider)
            if evidence is not None:
                item.source_evidence[field] = evidence
    return invoice
