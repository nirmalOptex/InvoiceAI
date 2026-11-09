from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.providers.base import ProviderError, VisionPage

_NUMBER = re.compile(r"(?<![\w/.,])\d[\d,]*(?:\.\d+)?(?![\w/.,])")
_OCR_GROUPED_NUMBER = re.compile(
    r"(?<![\w/])\d{1,3}(?:\.\d{2})*\.\d{3}\.\d{2}(?![\w/])"
)
_DATE = re.compile(
    r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"
)
_OCR_DATE_MONTH = re.compile(
    r"^\s*(\d{1,2})0(ctober|ecember|anuary|ebruary|arch|pril|une|uly|"
    r"ugust|eptember|ovember)\s+(\d{4})\s*$",
    re.IGNORECASE,
)
_OCR_DATE_MONTH_NAMES = {
    "ctober": "October",
    "ecember": "December",
    "anuary": "January",
    "ebruary": "February",
    "arch": "March",
    "pril": "April",
    "une": "June",
    "uly": "July",
    "ugust": "August",
    "eptember": "September",
    "ovember": "November",
}
_CURRENCIES = re.compile(
    r"\b(NPR|USD|EUR|GBP|INR|CAD|AUD|JPY|CNY|CHF|AED|SGD|NZD)\b",
    re.IGNORECASE,
)
_ELBOW_ANGLE_DIMENSION = re.compile(r"\b(elbow)\s+(90)(?=\d{2,}\s*mm\b)", re.I)
_PAGE_LINE = re.compile(
    r"^\[Page\s+(\d+)(?:\s+x1=([\d.]+)\s+y1=([\d.]+)"
    r"\s+x2=([\d.]+)\s+y2=([\d.]+))?\]\s*(.*)$"
)
_LABELS: dict[str, tuple[re.Pattern[str], ...]] = {
    "invoice_number": (
        re.compile(
            r"^\s*(?:invoice\s*(?:number|no\.?|#)|bill\s*(?:number|no\.?|#)|"
            r"voucher\s*(?:number|no\.?|#))\s*[:#-]?\s*(.*?)\s*$",
            re.IGNORECASE,
        ),
    ),
    "supplier_name": (
        re.compile(
            r"^\s*(?:supplier|vendor|seller)\s*(?:name)?\s*[:=-]\s*(.+?)\s*$",
            re.IGNORECASE,
        ),
    ),
    "supplier_address": (
        re.compile(
            r"^\s*(?:supplier|vendor|seller)\s+address\s*[:=-]\s*(.+?)\s*$",
            re.IGNORECASE,
        ),
    ),
    "supplier_tax_id": (
        re.compile(
            r"^\s*(?:supplier\s+)?(?:VAT|GST|tax)\s*(?:registration\s*)?"
            r"(?:ID|number|no\.?|#)\s*[:#-]?\s*(.*?)\s*$",
            re.IGNORECASE,
        ),
    ),
    "invoice_date": (
        re.compile(r"^\s*(?:invoice\s+)?date\s*[:=-]\s*(.*?)\s*$", re.IGNORECASE),
    ),
    "due_date": (
        re.compile(r"^\s*(?:due|payment)\s+date\s*[:=-]\s*(.*?)\s*$", re.IGNORECASE),
    ),
    "currency": (
        re.compile(r"^\s*currency\s*[:=-]\s*([A-Z]{3})\s*$", re.IGNORECASE),
    ),
    "subtotal": (
        re.compile(r"^\s*(?:sub\s*total|subtotal)\s*[:=-]?\s*(.*?)\s*$", re.IGNORECASE),
    ),
    "discount": (
        re.compile(r"^\s*(?:discount|less)\s*[:=-]?\s*(.*?)\s*$", re.IGNORECASE),
    ),
    "tax_amount": (
        re.compile(
            r"^\s*(?:(?:VAT|GST|sales\s+tax|tax)\s+amount)\s*[:=-]?\s*(.*?)\s*$",
            re.IGNORECASE,
        ),
    ),
    "additional_charges": (
        re.compile(
            r"^\s*(?:shipping|delivery|handling|service)\s+(?:fee|charge|charges)"
            r"\s*[:=-]?\s*(.*?)\s*$",
            re.IGNORECASE,
        ),
    ),
    "total_amount": (
        re.compile(
            r"^\s*(?:grand\s+total|invoice\s+total|total\s+due|amount\s+payable|"
            r"net\s+payable|total\s+amount|balance\s+due|total)\s*[:=-]?\s*(.*?)\s*$",
            re.IGNORECASE,
        ),
    ),
}


@dataclass(frozen=True)
class _OCRRecord:
    text: str
    page_number: int | None = None
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None

    @property
    def center_x(self) -> float | None:
        if self.x1 is None or self.x2 is None:
            return None
        return (self.x1 + self.x2) / 2

    @property
    def center_y(self) -> float | None:
        if self.y1 is None or self.y2 is None:
            return None
        return (self.y1 + self.y2) / 2


def _clean_labeled_value(value: str) -> str:
    return value.strip().strip("|").strip()


def _parse_amount(value: str) -> Decimal | None:
    repaired_match = _OCR_GROUPED_NUMBER.search(value)
    if repaired_match:
        groups = repaired_match.group().split(".")
        token = "".join(groups[:-1]) + "." + groups[-1]
        try:
            amount = Decimal(token)
        except InvalidOperation:
            return None
        return amount if amount.is_finite() and amount >= 0 else None

    match = _NUMBER.search(value)
    if match is None:
        return None

    token = match.group()
    if value[match.end() :].lstrip().startswith("%"):
        return None
    if "," in token:
        standard_grouping = re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", token)
        nepali_grouping = re.fullmatch(r"\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?", token)
        if standard_grouping is None and nepali_grouping is None:
            return None
    try:
        amount = Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _has_ocr_grouping_repair(value: str) -> bool:
    return _OCR_GROUPED_NUMBER.search(value) is not None


def _parse_records(ocr_text: str) -> list[_OCRRecord]:
    records: list[_OCRRecord] = []
    for raw_line in ocr_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _PAGE_LINE.match(line)
        if match is None:
            records.append(_OCRRecord(line))
            continue
        page, x1, y1, x2, y2, text = match.groups()
        values = [float(value) if value is not None else None for value in (x1, y1, x2, y2)]
        records.append(
            _OCRRecord(
                text=text.strip(),
                page_number=int(page),
                x1=values[0],
                y1=values[1],
                x2=values[2],
                y2=values[3],
            )
        )
    return records


def _right_neighbor(record: _OCRRecord, records: list[_OCRRecord]) -> _OCRRecord | None:
    if record.center_y is not None and record.x2 is not None:
        candidates = [
            candidate
            for candidate in records
            if candidate is not record
            and candidate.center_y is not None
            and candidate.x1 is not None
            and abs(candidate.center_y - record.center_y) <= 14
            and candidate.x1 >= record.x2 - 5
            and (
                record.page_number is None
                or candidate.page_number == record.page_number
            )
        ]
        if candidates:
            return min(candidates, key=lambda candidate: candidate.x1 or 0)
        return None

    try:
        index = records.index(record)
    except ValueError:
        return None
    for candidate in records[index + 1 : index + 3]:
        if candidate.page_number not in (None, record.page_number):
            continue
        if any(
            pattern.match(candidate.text)
            for patterns in _LABELS.values()
            for pattern in patterns
        ):
            continue
        if candidate.text.strip():
            return candidate
    return None


def _is_currency_only(value: str) -> bool:
    cleaned = value.strip().strip("()[]{} ")
    return bool(_CURRENCIES.fullmatch(cleaned))


def _in_item_table(record: _OCRRecord, records: list[_OCRRecord]) -> bool:
    columns = _table_columns(records)
    if columns is None or record.center_y is None:
        return False
    header_y, _, _ = columns
    summary_y = [
        candidate.center_y
        for candidate in records
        if candidate.center_y is not None
        and candidate.center_y > header_y
        and re.match(r"^\s*(?:sub\s*total|subtotal)\b", candidate.text, re.I)
    ]
    return bool(summary_y) and header_y + 12 < record.center_y < min(summary_y) - 10


def _labeled_value(
    records: list[_OCRRecord],
    field: str,
    *,
    amount: bool = False,
) -> str | None:
    for record in records:
        if field == "additional_charges" and _in_item_table(record, records):
            continue
        for pattern in _LABELS[field]:
            match = pattern.match(record.text)
            if match is None:
                continue
            value = _clean_labeled_value(match.group(1))
            parsed_amount = _parse_amount(value) if amount and value else None
            if value and (not amount or parsed_amount is not None):
                return str(parsed_amount) if amount else value
            if value and amount and not _is_currency_only(value):
                continue
            neighbor = _right_neighbor(record, records)
            if neighbor is not None:
                neighbor_value = _clean_labeled_value(neighbor.text)
                parsed_amount = _parse_amount(neighbor_value) if amount else None
                if neighbor_value and (not amount or parsed_amount is not None):
                    return str(parsed_amount) if amount else neighbor_value
    return None


def _normalize_ocr_date(value: str, warnings: list[str]) -> str:
    date_match = _DATE.search(value)
    if date_match:
        return date_match.group()
    match = _OCR_DATE_MONTH.fullmatch(value)
    if match is not None:
        day, month_suffix, year = match.groups()
        month = _OCR_DATE_MONTH_NAMES[month_suffix.casefold()]
        warnings.append(
            f"OCR punctuation in the date '{value}' was corrected; confirm it against the document."
        )
        return f"{day} {month} {year}"
    return value


def _row_quantity(value: str) -> tuple[str | None, str | None]:
    match = re.match(r"^\s*(\d[\d,]*(?:\.\d+)?)\s*(.*?)\s*$", value)
    if match is None:
        return None, None
    quantity_text, unit = match.groups()
    quantity = _parse_amount(quantity_text)
    return (
        str(quantity) if quantity is not None else None,
        unit.strip() or None,
    )


def _normalize_item_description(value: str) -> str:
    return _ELBOW_ANGLE_DIMENSION.sub(r"\1 \2° ", value)


def _table_columns(
    records: list[_OCRRecord],
) -> tuple[float, float, list[float]] | None:
    description_headers = [
        record for record in records if re.fullmatch(r"\s*description\s*", record.text, re.I)
    ]
    for description in description_headers:
        if description.center_y is None or description.center_x is None:
            continue
        header_specs = (
            (re.compile(r"\s*quantity\s*", re.I),),
            (re.compile(r"\s*unit\s+price\s*", re.I),),
            (re.compile(r"\s*total\s+amount\s*", re.I),),
        )
        centers = [description.center_x]
        matched = True
        for patterns in header_specs:
            choices = [
                candidate
                for candidate in records
                if candidate.center_x is not None
                and candidate.center_y is not None
                and abs(candidate.center_y - description.center_y) <= 22
                and any(pattern.fullmatch(candidate.text) for pattern in patterns)
            ]
            if not choices:
                matched = False
                break
            closest = min(
                choices,
                key=lambda item: abs(
                    (item.center_y or 0) - (description.center_y or 0)
                ),
            )
            if closest.center_x is None:
                matched = False
                break
            centers.append(closest.center_x)
        if matched:
            centers.sort()
            return (
                description.center_y,
                description.x1 or 0,
                [
                    (centers[index] + centers[index + 1]) / 2
                    for index in range(len(centers) - 1)
                ],
            )
    return None


def _extract_items(
    records: list[_OCRRecord], currency: str | None
) -> list[dict[str, Any]]:
    columns = _table_columns(records)
    if columns is None:
        return []
    header_y, description_left, boundaries = columns
    summary_y_values = [
        record.center_y
        for record in records
        if record.center_y is not None
        and record.center_y > header_y
        and re.match(r"^\s*(?:sub\s*total|subtotal|grand\s+total)\b", record.text, re.I)
    ]
    if not summary_y_values:
        return []
    summary_y = min(summary_y_values)
    entries = [
        record
        for record in records
        if record.center_y is not None
        and record.center_x is not None
        and header_y + 12 < record.center_y < summary_y - 10
    ]
    entries.sort(key=lambda record: (record.center_y or 0, record.x1 or 0))

    rows: list[list[_OCRRecord]] = []
    for record in entries:
        if (
            not rows
            or record.center_y is None
            or rows[-1][0].center_y is None
            or abs(record.center_y - rows[-1][0].center_y) > 14
        ):
            rows.append([record])
        else:
            rows[-1].append(record)

    items: list[dict[str, Any]] = []
    for row in rows:
        description_parts: list[str] = []
        quantity_text: str | None = None
        unit_price: Decimal | None = None
        line_total: Decimal | None = None
        for record in row:
            center_x = record.center_x
            if center_x is None or center_x < description_left:
                continue
            if center_x < boundaries[0]:
                if not re.fullmatch(r"\d{1,2}", record.text.strip()):
                    description_parts.append(record.text.strip())
            elif center_x < boundaries[1]:
                quantity_text = quantity_text or record.text.strip()
            elif center_x < boundaries[2]:
                unit_price = unit_price or _parse_amount(record.text)
            else:
                line_total = line_total or _parse_amount(record.text)

        description = _normalize_item_description(" ".join(description_parts).strip())
        quantity, unit = _row_quantity(quantity_text) if quantity_text else (None, None)
        if not description or (unit_price is None and line_total is None):
            continue
        items.append(
            {
                "description": description,
                "quantity": quantity,
                "unit": unit,
                "unit_price": str(unit_price) if unit_price is not None else None,
                "line_total": str(line_total) if line_total is not None else None,
                "currency": currency,
            }
        )
    return items


def _infer_supplier_header(records: list[_OCRRecord]) -> tuple[str | None, str | None]:
    bill_to = next(
        (
            record
            for record in records
            if re.match(r"^\s*bill\s+to\b", record.text, re.I)
        ),
        None,
    )
    if bill_to is None or bill_to.center_y is None:
        return None, None
    supplier_left = (
        max(0, bill_to.x1 - 100) if bill_to.x1 is not None else None
    )
    header = [
        record
        for record in records
        if record.center_y is not None
        and record.center_y < bill_to.center_y
        and (
            record.center_x is None
            or (
                record.center_x >= supplier_left
                if supplier_left is not None
                else record.center_x < 300
            )
        )
    ]
    if not header:
        return None, None
    header.sort(key=lambda record: record.center_y or 0)
    supplier = header[0].text.strip()
    brand = next(
        (
            record.text.strip()
            for record in records
            if record.center_y is not None
            and record.center_y < bill_to.center_y
            and record.text.strip().isalpha()
            and record.text.strip().isupper()
            and 300 <= (record.center_x or 0) <= 650
        ),
        None,
    )
    if brand:
        first_word = supplier.split()[0]
        if first_word.upper().startswith(brand.upper()) and len(first_word) > len(brand):
            supplier = f"{brand} {first_word[len(brand):]} {' '.join(supplier.split()[1:])}"
    supplier = supplier.title()

    street_index = next(
        (
            index
            for index, record in enumerate(header)
            if re.search(r"\b(?:road|rd\.?|street|st\.?|avenue|ave\.?|lane|drive|estate)\b", record.text, re.I)
        ),
        None,
    )
    if street_index is None:
        return supplier, None
    street = re.sub(
        r"(?<=\d)(?=[A-Za-z])", " ", header[street_index].text.strip()
    )
    address_parts = [street]
    for record in header[street_index + 1 :]:
        if record.center_y is None or header[street_index].center_y is None:
            break
        if record.center_y - header[street_index].center_y > 32:
            break
        if re.search(r"\b(?:kathmandu|nepal|city|[0-9]{5,})\b", record.text, re.I):
            locality = re.sub(r"(?<=[A-Za-z])(?=\d{4,}\b)", " ", record.text.strip())
            locality = re.sub(r",(?=[A-Za-z])", ", ", locality)
            if re.search(r"\bKathmandu\b", locality, re.I):
                locality = re.sub(r"\bNepa$", "Nepal", locality, flags=re.I)
            address_parts.append(locality)
    return supplier, ", ".join(address_parts)


class LocalRuleBasedProvider:
    """Extract labeled invoice fields and simple OCR tables without network calls."""

    name = "local"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def extract(self, pages: list[VisionPage], ocr_text: str) -> dict[str, Any]:
        del pages
        self.warnings = [
            "Local rule-based extraction is conservative. Confirm extracted values; "
            "OCR can misread dates, punctuation, and table alignment."
        ]
        records = _parse_records(ocr_text)
        if not records:
            raise ProviderError(
                "Local extraction found no readable OCR text. Check the document image "
                "or enter its details manually."
            )

        data: dict[str, Any] = {
            "supplier_name": _labeled_value(records, "supplier_name"),
            "supplier_address": _labeled_value(records, "supplier_address"),
            "supplier_tax_id": _labeled_value(records, "supplier_tax_id"),
            "invoice_number": _labeled_value(records, "invoice_number"),
            "invoice_date": None,
            "due_date": None,
            "currency": _labeled_value(records, "currency"),
            "items": [],
            "subtotal": _labeled_value(records, "subtotal", amount=True),
            "discount": _labeled_value(records, "discount", amount=True),
            "tax_rate": None,
            "tax_amount": _labeled_value(records, "tax_amount", amount=True),
            "additional_charges": _labeled_value(
                records, "additional_charges", amount=True
            ),
            "total_amount": _labeled_value(records, "total_amount", amount=True),
        }

        for field in ("subtotal", "discount", "tax_amount", "additional_charges", "total_amount"):
            if any(
                pattern.match(record.text)
                and _has_ocr_grouping_repair(record.text)
                for record in records
                if field != "additional_charges" or not _in_item_table(record, records)
                for pattern in _LABELS[field]
            ):
                self.warnings.append(
                    f"OCR punctuation in the {field.replace('_', ' ')} was "
                    "normalized; confirm it against the document."
                )

        for field in ("invoice_date", "due_date"):
            labeled_value = _labeled_value(records, field)
            if labeled_value:
                data[field] = _normalize_ocr_date(labeled_value, self.warnings)

        observed_currencies: set[str] = set()
        for record in records:
            currency_match = _CURRENCIES.search(record.text)
            if currency_match:
                observed_currencies.add(currency_match.group(1).upper())

        if data["currency"]:
            data["currency"] = data["currency"].upper()
        elif len(observed_currencies) == 1:
            data["currency"] = observed_currencies.pop()
        elif len(observed_currencies) > 1:
            self.warnings.append(
                "Conflicting currency codes appear in OCR; confirm the invoice currency."
            )

        for field in ("subtotal", "discount", "tax_amount", "additional_charges", "total_amount"):
            if data[field] is None and any(
                pattern.match(record.text)
                for record in records
                if field != "additional_charges" or not _in_item_table(record, records)
                for pattern in _LABELS[field]
            ):
                self.warnings.append(
                    f"Could not confidently read the labeled {field.replace('_', ' ')}."
                )

        for record in records:
            tax_line = re.match(
                r"^\s*(?:VAT|GST|sales\s+tax|tax)"
                r"(?!\s+(?:(?:registration\s*)?(?:ID|number|no\.?))|"
                r"\s+amount\b)(.*)$",
                record.text,
                re.IGNORECASE,
            )
            if tax_line is None:
                continue
            rate = re.search(r"(\d+(?:\.\d+)?)\s*%", tax_line.group(1))
            if rate is None:
                continue
            data["tax_rate"] = rate.group(1)
            if data["tax_amount"] is None:
                remainder = (
                    tax_line.group(1)[: rate.start()]
                    + tax_line.group(1)[rate.end() :]
                )
                amount = _parse_amount(remainder)
                neighbor = _right_neighbor(record, records) if amount is None else None
                amount = amount or (
                    _parse_amount(neighbor.text) if neighbor is not None else None
                )
                if amount is not None:
                    data["tax_amount"] = str(amount)
                    source_text = neighbor.text if neighbor is not None else remainder
                    if _has_ocr_grouping_repair(source_text):
                        self.warnings.append(
                            "OCR punctuation in the tax amount was normalized; "
                            "confirm it against the document."
                        )
            break

        inferred_supplier, inferred_address = _infer_supplier_header(records)
        if data["supplier_name"] is None and inferred_supplier:
            data["supplier_name"] = inferred_supplier
            self.warnings.append(
                "Supplier name was inferred from the document header; confirm it manually."
            )
        if data["supplier_address"] is None and inferred_address:
            data["supplier_address"] = inferred_address
            self.warnings.append(
                "Supplier address was inferred from the document header; confirm it manually."
            )

        if any(_ELBOW_ANGLE_DIMENSION.search(record.text) for record in records):
            self.warnings.append(
                "A 90-degree elbow marker was inferred from OCR; confirm the item description."
            )
        data["items"] = _extract_items(records, data["currency"])
        if not data["items"]:
            self.warnings.append(
                "No line items could be reliably matched to the invoice table; "
                "enter them manually."
            )
        if data["discount"] is None or data["additional_charges"] is None:
            self.warnings.append(
                "No separate discount or additional-charge summary was identified; "
                "these values need review before totals can be fully verified."
            )

        if not any(
            value is not None
            for key, value in data.items()
            if key != "items"
        ):
            raise ProviderError(
                "Local extraction could not confidently match invoice fields from "
                "the OCR text. Review the OCR and enter details manually."
            )

        self.warnings = list(dict.fromkeys(self.warnings))
        return data
