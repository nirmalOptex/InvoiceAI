from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable

from app.config import Settings, get_settings
from app.providers.base import InvoiceVisionProvider, ProviderError
from app.providers.factory import create_vision_provider
from app.providers.local import LocalRuleBasedProvider
from app.schemas.invoice import InvoiceData
from app.services.document_processing import (
    ProcessedDocument,
    process_document,
)
from app.services.evidence_service import attach_ocr_evidence
from app.services.normalizer import (
    ExtractionNormalizationError,
    normalize_extraction,
)
from app.services.ocr_service import (
    OCRLine,
    OCRService,
    OCRUnavailableError,
    PaddleOCRService,
)
from app.services.validator import validate_invoice
from app.schemas.invoice import ValidationReport

MAX_OCR_CONTEXT_CHARS = 40_000


@dataclass
class ExtractionResult:
    filename: str
    source_type: str
    page_count: int
    ocr_lines: list[OCRLine] = field(default_factory=list)
    invoice: InvoiceData | None = None
    raw_extraction: dict | None = None
    provider: str | None = None
    validation: ValidationReport | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    stage_timings_ms: dict[str, float] = field(default_factory=dict)


def _ocr_context(
    lines: list[OCRLine], *, include_geometry: bool = False
) -> tuple[str, bool]:
    context_lines = []
    for line in lines:
        if not line.text:
            continue
        prefix = f"[Page {line.page_number}"
        if include_geometry and line.bounding_box and len(line.bounding_box) >= 8:
            xs = line.bounding_box[0::2]
            ys = line.bounding_box[1::2]
            prefix += (
                f" x1={min(xs):.1f} y1={min(ys):.1f}"
                f" x2={max(xs):.1f} y2={max(ys):.1f}"
            )
        context_lines.append(f"{prefix}] {line.text}")
    context = "\n".join(context_lines)
    return context[:MAX_OCR_CONTEXT_CHARS], len(context) > MAX_OCR_CONTEXT_CHARS


def extract_document(
    content: bytes,
    filename: str,
    *,
    settings: Settings | None = None,
    ocr_service: OCRService | None = None,
    provider_factory: Callable[[], InvoiceVisionProvider] | None = None,
) -> ExtractionResult:
    """Run document rendering, OCR, and vision extraction without storing files."""
    config = settings or get_settings()
    total_started = perf_counter()
    stage_started = perf_counter()
    document: ProcessedDocument = process_document(
        content,
        filename,
        max_pages=config.max_document_pages,
        render_dpi=config.document_render_dpi,
        max_file_bytes=config.max_upload_size_mb * 1024 * 1024,
    )
    stage_timings_ms = {
        "document_render_ms": round((perf_counter() - stage_started) * 1000, 1)
    }
    result = ExtractionResult(
        filename=document.filename,
        source_type=document.source_type,
        page_count=len(document.pages),
    )
    ocr = ocr_service or PaddleOCRService()
    stage_started = perf_counter()
    try:
        result.ocr_lines = ocr.extract(document.pages)
    except OCRUnavailableError as exc:
        result.warnings.append(str(exc))
    finally:
        stage_timings_ms["ocr_ms"] = round((perf_counter() - stage_started) * 1000, 1)

    provider_builder = provider_factory or (lambda: create_vision_provider(config))
    try:
        stage_started = perf_counter()
        provider = provider_builder()
        stage_timings_ms["provider_setup_ms"] = round(
            (perf_counter() - stage_started) * 1000, 1
        )
        result.provider = provider.name
        ocr_text, was_truncated = _ocr_context(
            result.ocr_lines,
            include_geometry=provider.name == "local",
        )
        if was_truncated:
            result.warnings.append(
                "OCR text exceeded the vision prompt limit; full OCR remains available for review."
            )
        stage_started = perf_counter()
        try:
            raw_data = provider.extract(document.pages, ocr_text)
        finally:
            stage_timings_ms["provider_extract_ms"] = round(
                (perf_counter() - stage_started) * 1000, 1
            )
        result.raw_extraction = raw_data
        if isinstance(provider, LocalRuleBasedProvider):
            result.warnings.extend(provider.warnings)
        result.warnings = list(dict.fromkeys(result.warnings))
        stage_started = perf_counter()
        try:
            invoice, normalization_warnings = normalize_extraction(raw_data)
            result.invoice = attach_ocr_evidence(invoice, result.ocr_lines, provider.name)
            result.validation = validate_invoice(result.invoice, settings=config)
            result.warnings.extend(normalization_warnings)
        finally:
            stage_timings_ms["normalize_validate_ms"] = round(
                (perf_counter() - stage_started) * 1000, 1
            )
    except (ProviderError, ExtractionNormalizationError) as exc:
        result.error = str(exc)
        result.warnings.append(
            "Invoice extraction did not complete; available OCR text is preserved for review."
        )
    result.stage_timings_ms = stage_timings_ms
    result.stage_timings_ms["pipeline_total_ms"] = round(
        (perf_counter() - total_started) * 1000, 1
    )
    return result
