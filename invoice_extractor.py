"""Extract structured invoice data from an image with the OpenAI vision API."""

from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any


API_URL = "https://api.openai.com/v1/chat/completions"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
AMOUNT_TOLERANCE = Decimal("0.01")


class ExtractionError(Exception):
    """Raised when an image cannot be sent or parsed as an invoice."""


def image_data_url(image_path: Path) -> str:
    """Read an image and encode it as a data URL for the vision API."""
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        raise ExtractionError(f"Cannot read image '{image_path}': {exc}") from exc

    if not image_bytes:
        raise ExtractionError(f"Image '{image_path}' is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ExtractionError("Image exceeds the 20 MB limit.")

    mime_type, _ = mimetypes.guess_type(image_path.name)
    if mime_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise ExtractionError(
            "Unsupported image type. Use a JPEG, PNG, WEBP, or GIF image."
        )

    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded_image}"


def _amount(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ExtractionError(f"'{field_name}' must be a number or null.")
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ExtractionError(f"'{field_name}' must be a finite number.")
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        cleaned = re.sub(r"^(?:NPR|Rs\.?)\s*", "", cleaned, flags=re.IGNORECASE)
        if re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
            return float(cleaned)
    raise ExtractionError(f"'{field_name}' must be a number or null.")


def normalize_invoice_data(data: Any) -> dict[str, Any]:
    """Validate the model response and fill absent fields with null/empty values."""
    if not isinstance(data, dict):
        raise ExtractionError("The AI response must be a JSON object.")

    normalized: dict[str, Any] = {}
    for field in ("invoice_number", "invoice_date", "supplier_name", "currency"):
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            raise ExtractionError(f"'{field}' must be a string or null.")
        normalized[field] = value

    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        raise ExtractionError("'items' must be a JSON array.")

    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise ExtractionError(f"Item {index} must be a JSON object.")
        item: dict[str, Any] = {}
        for field in ("description", "quantity"):
            value = raw_item.get(field)
            if value is not None and not isinstance(value, str):
                raise ExtractionError(f"Item {index} '{field}' must be a string or null.")
            item[field] = value
        item["unit_price"] = _amount(raw_item.get("unit_price"), f"items[{index}].unit_price")
        item["line_total"] = _amount(raw_item.get("line_total"), f"items[{index}].line_total")
        items.append(item)
    normalized["items"] = items

    for field in ("subtotal", "tax_amount", "total_amount"):
        normalized[field] = _amount(data.get(field), field)

    return normalized


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _item_amount(item: dict[str, Any]) -> Decimal | None:
    line_total = item["line_total"]
    if line_total is not None:
        return _decimal(line_total)

    quantity = item["quantity"]
    unit_price = item["unit_price"]
    if quantity is None or unit_price is None:
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\b", quantity)
    if match is None:
        return None
    return Decimal(match.group(1)) * _decimal(unit_price)


def validate_invoice(data: dict[str, Any]) -> dict[str, Any]:
    """Check extracted amounts and report unavailable or inconsistent checks."""
    warnings: list[str] = []
    for field in ("invoice_number", "invoice_date", "supplier_name"):
        if not data[field]:
            warnings.append(f"Could not identify {field.replace('_', ' ')}.")
    if not data["items"]:
        warnings.append("No invoice line items were identified.")
    if data["total_amount"] is None:
        warnings.append("Could not identify the total amount.")

    item_amounts = [_item_amount(item) for item in data["items"]]
    if data["subtotal"] is not None and item_amounts and all(
        amount is not None for amount in item_amounts
    ):
        item_sum = sum((amount for amount in item_amounts if amount is not None), Decimal(0))
        line_items_match_subtotal = (
            abs(item_sum - _decimal(data["subtotal"])) <= AMOUNT_TOLERANCE
        )
        if not line_items_match_subtotal:
            warnings.append(
                "The sum of line items does not match the invoice subtotal."
            )
    else:
        line_items_match_subtotal = None
        if data["subtotal"] is not None:
            warnings.append(
                "Could not verify the subtotal because line-item amounts are incomplete."
            )

    if (
        data["subtotal"] is not None
        and data["tax_amount"] is not None
        and data["total_amount"] is not None
    ):
        expected_total = _decimal(data["subtotal"]) + _decimal(data["tax_amount"])
        subtotal_plus_tax_matches_total = (
            abs(expected_total - _decimal(data["total_amount"])) <= AMOUNT_TOLERANCE
        )
        if not subtotal_plus_tax_matches_total:
            warnings.append("The subtotal plus tax does not match the total amount.")
    else:
        subtotal_plus_tax_matches_total = None

    return {
        "line_items_match_subtotal": line_items_match_subtotal,
        "subtotal_plus_tax_matches_total": subtotal_plus_tax_matches_total,
        "warnings": warnings,
    }


def _prompt() -> str:
    return (
        "Read the invoice in this image and return one JSON object only. Do not "
        "guess: use null for unknown scalar values and an empty array if no items "
        "are visible. Return exactly these top-level fields: invoice_number "
        "(string or null), invoice_date (ISO YYYY-MM-DD string or null), "
        "supplier_name (string or null), currency (string or null), items (array "
        "of objects), subtotal (number or null), tax_amount (number or null), "
        "total_amount (number or null). Each item must have description "
        "(string or null), quantity (string or null, preserving its unit), "
        "unit_price (number or null), and line_total (number or null). Amounts "
        "must be numeric without currency symbols or thousands separators. "
        "Extract the printed line totals when available."
    )


def extract_invoice(image_path: Path, api_key: str, model: str) -> dict[str, Any]:
    data_url = image_data_url(image_path)
    request_body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _prompt()},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ExtractionError(
            f"AI API returned HTTP {exc.code}: {details or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ExtractionError(f"Could not connect to the AI API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ExtractionError("The AI API request timed out.") from exc

    try:
        api_response = json.loads(response_text)
        content = api_response["choices"][0]["message"]["content"]
        invoice_data = json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ExtractionError(
            "The AI API response did not contain valid invoice JSON."
        ) from exc

    return normalize_invoice_data(invoice_data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract invoice details from an image into structured JSON."
    )
    parser.add_argument("image", type=Path, help="Path to a JPEG, PNG, WEBP, or GIF invoice image")
    parser.add_argument(
        "-o", "--output", type=Path, help="Write JSON to this file instead of stdout"
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        help="OpenAI vision model (default: OPENAI_MODEL or gpt-4o-mini)",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            "Error: set the OPENAI_API_KEY environment variable before running.",
            file=sys.stderr,
        )
        return 2

    try:
        invoice = extract_invoice(args.image, api_key, args.model)
    except ExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    result = {"invoice": invoice, "validation": validate_invoice(invoice)}
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        try:
            args.output.write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"Error: cannot write '{args.output}': {exc}", file=sys.stderr)
            return 1
        print(f"Extracted invoice JSON written to {args.output}")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
