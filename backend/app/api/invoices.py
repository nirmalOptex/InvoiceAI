from __future__ import annotations

import mimetypes
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from time import perf_counter
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.database import SessionLocal, get_db
from app.models import Invoice, InvoiceItem, ValidationResult
from app.schemas.invoice import (
    DashboardStats,
    InvoiceCorrection,
    InvoiceData,
    InvoicePage,
    InvoiceRead,
    ProcessingStatus,
    ValidationCheck,
    ValidationDistribution,
    ValidationRunResponse,
    ValidationStatus,
)
from app.services.document_processing import DocumentProcessingError, safe_filename
from app.services.extraction_pipeline import ExtractionResult, extract_document
from app.services.validator import validate_invoice

router = APIRouter(prefix="/api", tags=["invoices"])
logger = logging.getLogger(__name__)
ALLOWED_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
MAX_BULK_UPLOAD_FILES = 10
_processing_executor = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="invoice-processing"
)
SORT_COLUMNS = {
    "created_at": Invoice.created_at,
    "invoice_date": Invoice.invoice_date,
    "supplier_name": Invoice.supplier_name,
    "invoice_number": Invoice.invoice_number,
    "total_amount": Invoice.total_amount,
}
EDITABLE_SCALAR_FIELDS = (
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


def _invoice_or_404(session: Session, invoice_id: int) -> Invoice:
    invoice = session.scalar(
        select(Invoice)
        .options(
            selectinload(Invoice.items),
            selectinload(Invoice.validation_results),
        )
        .where(Invoice.id == invoice_id)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice


def _read_upload(upload: UploadFile, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(min(64 * 1024, maximum_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File exceeds the {maximum_bytes // (1024 * 1024)} MB upload limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_upload_type(upload: UploadFile, content: bytes | None = None) -> None:
    filename = upload.filename or ""
    suffix = Path(filename.replace("\\", "/").rsplit("/", 1)[-1]).suffix.lower()
    expected_type = ALLOWED_CONTENT_TYPES.get(suffix)
    if expected_type is None:
        raise HTTPException(
            status_code=415,
            detail="Supported document formats are PDF, PNG, JPG, and JPEG.",
        )

    content_type = (upload.content_type or "").lower()
    if content_type and content_type not in {expected_type, "application/octet-stream"}:
        raise HTTPException(
            status_code=415,
            detail="The declared MIME type does not match the filename extension.",
        )

    if content is None:
        return
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=422,
            detail="The file extension does not match a PDF document.",
        )
    if suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(
            status_code=422,
            detail="The file extension does not match a PNG image.",
        )
    if suffix in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        raise HTTPException(
            status_code=422,
            detail="The file extension does not match a JPEG image.",
        )


def _store_document(content: bytes, filename: str, settings: Settings) -> str:
    suffix = Path(filename).suffix.lower()
    stored_filename = f"{uuid.uuid4().hex}{suffix}"
    storage_dir = Path(settings.storage_dir).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    destination = storage_dir / stored_filename
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".upload-", suffix=".tmp", dir=storage_dir, delete=False
        ) as temporary:
            temporary_path = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    except OSError as exc:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise HTTPException(
            status_code=500, detail="Could not store the uploaded invoice."
        ) from exc
    return stored_filename


def _delete_stored_document(stored_filename: str, settings: Settings) -> None:
    storage_dir = Path(settings.storage_dir).resolve()
    path = (storage_dir / stored_filename).resolve()
    if path.parent != storage_dir:
        raise HTTPException(status_code=500, detail="Stored document path is invalid.")
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail="Could not remove the stored invoice document."
        ) from exc


def _record_validation_results(invoice: Invoice, checks: list[ValidationCheck]) -> None:
    invoice.validation_results.clear()
    for check in checks:
        invoice.validation_results.append(
            ValidationResult(
                check_name=check.check_name,
                expected_value=check.expected_value,
                actual_value=check.actual_value,
                difference=check.difference,
                status=check.status.value,
                message=check.message,
            )
        )


def _invoice_data_from_record(invoice: Invoice) -> InvoiceData:
    data = {
        field: getattr(invoice, field) for field in EDITABLE_SCALAR_FIELDS
    }
    data.update(
        {
            "items": [
                {
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "unit_price": item.unit_price,
                    "line_total": item.line_total,
                    "currency": item.currency,
                    "source_evidence": item.source_evidence or {},
                    "manually_corrected": item.manually_corrected,
                }
                for item in invoice.items
            ],
            "field_evidence": invoice.field_evidence or {},
        }
    )
    return InvoiceData.model_validate(data)


def _apply_corrections(invoice: Invoice, correction: InvoiceCorrection) -> None:
    provided = correction.model_fields_set
    field_evidence = dict(invoice.field_evidence or {})
    for field in EDITABLE_SCALAR_FIELDS:
        if field not in provided:
            continue
        old_value = getattr(invoice, field)
        setattr(invoice, field, getattr(correction, field))
        evidence = field_evidence.get(field, {})
        evidence = dict(evidence) if isinstance(evidence, dict) else {}
        evidence.setdefault("extracted_value", old_value.isoformat() if hasattr(old_value, "isoformat") else str(old_value) if old_value is not None else None)
        evidence["manually_corrected"] = True
        field_evidence[field] = evidence
    invoice.field_evidence = field_evidence

    if "items" in provided and correction.items is not None:
        previous_items = list(invoice.items)
        invoice.items.clear()
        for index, corrected_item in enumerate(correction.items):
            item_data = corrected_item.model_dump(
                mode="python", exclude={"source_evidence", "manually_corrected"}
            )
            previous = previous_items[index] if index < len(previous_items) else None
            previous_evidence = dict(previous.source_evidence or {}) if previous else {}
            for evidence in previous_evidence.values():
                if isinstance(evidence, dict):
                    evidence["manually_corrected"] = True
            invoice.items.append(
                InvoiceItem(
                    **item_data,
                    source_evidence=previous_evidence,
                    manually_corrected=True,
                )
            )


def _refresh_validation(invoice: Invoice, session: Session, settings: Settings) -> None:
    data = _invoice_data_from_record(invoice)
    report = validate_invoice(data, settings=settings)
    invoice.validation_status = report.status.value
    _record_validation_results(invoice, report.checks)
    session.flush()


def _apply_extraction_result(invoice: Invoice, result: ExtractionResult) -> None:
    extracted = result.invoice
    if extracted is not None:
        invoice_values = extracted.model_dump(
            mode="python",
            exclude={"items", "field_evidence"},
        )
        for field, value in invoice_values.items():
            setattr(invoice, field, value)

    invoice.processing_status = (
        ProcessingStatus.COMPLETED.value
        if extracted is not None
        else ProcessingStatus.FAILED.value
    )
    invoice.processing_error = result.error
    invoice.validation_status = (
        result.validation.status.value
        if result.validation is not None
        else ValidationStatus.NOT_CHECKED.value
    )
    invoice.raw_extraction_json = result.raw_extraction
    invoice.extraction_metadata = {
        "source_type": result.source_type,
        "page_count": result.page_count,
        "provider": result.provider,
        "warnings": result.warnings,
        "ocr_lines": [
            {
                "text": line.text,
                "page_number": line.page_number,
                "bounding_box": line.bounding_box,
                "confidence": line.confidence,
            }
            for line in result.ocr_lines
        ],
    }
    invoice.field_evidence = (
        {
            name: evidence.model_dump(mode="json")
            for name, evidence in extracted.field_evidence.items()
        }
        if extracted is not None
        else {}
    )
    invoice.items.clear()
    if extracted is not None:
        for item in extracted.items:
            invoice.items.append(
                InvoiceItem(
                    **item.model_dump(
                        mode="python",
                        exclude={"source_evidence", "manually_corrected"},
                    ),
                    source_evidence={
                        name: evidence.model_dump(mode="json")
                        for name, evidence in item.source_evidence.items()
                    },
                    manually_corrected=False,
                )
            )
    invoice.validation_results.clear()
    if result.validation is not None:
        for check in result.validation.checks:
            invoice.validation_results.append(
                ValidationResult(
                    check_name=check.check_name,
                    expected_value=check.expected_value,
                    actual_value=check.actual_value,
                    difference=check.difference,
                    status=check.status.value,
                    message=check.message,
                )
            )


def _set_processing_failure(invoice_id: int, message: str) -> None:
    with SessionLocal() as session:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            return
        invoice.processing_status = ProcessingStatus.FAILED.value
        invoice.processing_error = message
        invoice.validation_status = ValidationStatus.NOT_CHECKED.value
        session.commit()


def _process_uploaded_invoice(
    invoice_id: int, stored_filename: str, settings: Settings
) -> None:
    total_started = perf_counter()
    try:
        with SessionLocal() as session:
            invoice = session.get(Invoice, invoice_id)
            if invoice is None:
                return
            filename = invoice.original_filename

        storage_dir = Path(settings.storage_dir).resolve()
        stored_path = (storage_dir / stored_filename).resolve()
        if stored_path.parent != storage_dir:
            raise OSError("Stored invoice path is invalid.")
        content = stored_path.read_bytes()
        result = extract_document(content, filename, settings=settings)

        with SessionLocal() as session:
            invoice = session.scalar(
                select(Invoice)
                .options(
                    selectinload(Invoice.items),
                    selectinload(Invoice.validation_results),
                )
                .where(Invoice.id == invoice_id)
            )
            if invoice is None:
                return
            _apply_extraction_result(invoice, result)
            session.commit()

        logger.info(
            "Invoice processing timings: %s",
            {
                "invoice_id": invoice_id,
                "file_bytes": len(content),
                "page_count": result.page_count,
                "provider": result.provider,
                "stage_timings_ms": result.stage_timings_ms,
                "background_total_ms": round((perf_counter() - total_started) * 1000, 1),
            },
        )
    except (DocumentProcessingError, ValueError) as exc:
        _set_processing_failure(invoice_id, str(exc))
        logger.warning(
            "Invoice processing failed: %s",
            {"invoice_id": invoice_id, "background_total_ms": round((perf_counter() - total_started) * 1000, 1)},
        )
    except Exception:
        logger.exception("Invoice processing failed unexpectedly (invoice_id=%s)", invoice_id)
        try:
            _set_processing_failure(invoice_id, "Invoice processing failed unexpectedly.")
        except Exception:
            logger.exception("Could not mark invoice processing failure (invoice_id=%s)", invoice_id)


def _queue_invoice_processing(
    invoice_id: int, stored_filename: str, settings: Settings
) -> None:
    try:
        _processing_executor.submit(
            _process_uploaded_invoice, invoice_id, stored_filename, settings
        )
    except RuntimeError:
        _set_processing_failure(invoice_id, "Invoice processing is unavailable.")


@router.post(
    "/invoices/upload",
    response_model=InvoiceRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_invoice(
    file: Annotated[UploadFile, File()],
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db)],
) -> Invoice:
    settings = get_settings()
    content = _read_upload(file, settings.max_upload_size_mb * 1024 * 1024)
    _validate_upload_type(file, content)
    try:
        filename = safe_filename(file.filename or "")
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stored_filename = _store_document(content, filename, settings)
    invoice = Invoice(
        original_filename=filename,
        stored_filename=stored_filename,
        processing_status=ProcessingStatus.PROCESSING.value,
        validation_status=ValidationStatus.PENDING.value,
        extraction_metadata={},
        field_evidence={},
    )
    try:
        session.add(invoice)
        session.commit()
        session.refresh(invoice)
    except Exception:
        session.rollback()
        try:
            _delete_stored_document(stored_filename, settings)
        except HTTPException as cleanup_error:
            raise HTTPException(
                status_code=500,
                detail="Invoice persistence failed and stored-file cleanup also failed.",
            ) from cleanup_error
        raise
    thread = Thread(
        target=_process_uploaded_invoice,
        args=(invoice.id, stored_filename, settings),
        daemon=True,
        name=f"invoice-processing-{invoice.id}",
    )
    thread.start()
    return invoice


@router.post(
    "/invoices/bulk-upload",
    response_model=list[InvoiceRead],
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_invoices(
    files: Annotated[list[UploadFile], File()],
    session: Annotated[Session, Depends(get_db)],
) -> list[Invoice]:
    if not files:
        raise HTTPException(status_code=422, detail="Choose at least one invoice.")
    if len(files) > MAX_BULK_UPLOAD_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload no more than {MAX_BULK_UPLOAD_FILES} invoices at a time.",
        )

    settings = get_settings()
    prepared: list[tuple[str, bytes]] = []
    for upload in files:
        content = _read_upload(upload, settings.max_upload_size_mb * 1024 * 1024)
        _validate_upload_type(upload, content)
        try:
            filename = safe_filename(upload.filename or "")
        except DocumentProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        prepared.append((filename, content))

    stored_files: list[str] = []
    try:
        for filename, content in prepared:
            stored_files.append(_store_document(content, filename, settings))

        invoices = [
            Invoice(
                original_filename=filename,
                stored_filename=stored_filename,
                processing_status=ProcessingStatus.PROCESSING.value,
                validation_status=ValidationStatus.PENDING.value,
                extraction_metadata={},
                field_evidence={},
            )
            for (filename, _), stored_filename in zip(prepared, stored_files)
        ]
        session.add_all(invoices)
        session.commit()
        for invoice in invoices:
            session.refresh(invoice)
    except Exception:
        session.rollback()
        cleanup_errors = []
        for stored_filename in stored_files:
            try:
                _delete_stored_document(stored_filename, settings)
            except HTTPException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        if cleanup_errors:
            raise HTTPException(
                status_code=500,
                detail="Invoice batch persistence failed and stored-file cleanup also failed.",
            ) from cleanup_errors[0]
        raise

    for invoice in invoices:
        _queue_invoice_processing(invoice.id, invoice.stored_filename, settings)
    return invoices


@router.get("/invoices", response_model=InvoicePage)
def list_invoices(
    session: Annotated[Session, Depends(get_db)],
    q: str | None = Query(default=None, max_length=200),
    validation_status: ValidationStatus | None = None,
    processing_status: ProcessingStatus | None = None,
    sort_by: str = Query(default="created_at", pattern="^(created_at|invoice_date|supplier_name|invoice_number|total_amount)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> InvoicePage:
    statement = select(Invoice)
    count_statement = select(func.count()).select_from(Invoice)
    filters = []
    if q:
        search = f"%{q.strip()}%"
        filters.append(
            or_(
                Invoice.invoice_number.ilike(search),
                Invoice.supplier_name.ilike(search),
            )
        )
    if validation_status is not None:
        filters.append(Invoice.validation_status == validation_status.value)
    if processing_status is not None:
        filters.append(Invoice.processing_status == processing_status.value)
    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(*filters)

    total = int(session.scalar(count_statement) or 0)
    sort_column = SORT_COLUMNS[sort_by]
    sort_column = sort_column.asc() if order == "asc" else sort_column.desc()
    records = session.scalars(
        statement.order_by(sort_column, Invoice.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return InvoicePage(
        items=records,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(
    invoice_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> Invoice:
    return _invoice_or_404(session, invoice_id)


@router.get("/invoices/{invoice_id}/document")
def get_invoice_document(
    invoice_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    invoice = _invoice_or_404(session, invoice_id)
    settings = get_settings()
    storage_dir = Path(settings.storage_dir).resolve()
    path = (storage_dir / invoice.stored_filename).resolve()
    if path.parent != storage_dir or not path.is_file():
        raise HTTPException(status_code=404, detail="Invoice document is unavailable.")
    content_type = mimetypes.guess_type(invoice.original_filename)[0]
    if content_type not in {"application/pdf", "image/png", "image/jpeg"}:
        raise HTTPException(status_code=415, detail="Stored document type is unsupported.")
    return FileResponse(
        path,
        media_type=content_type,
        filename=invoice.original_filename,
        content_disposition_type="inline",
    )


@router.patch("/invoices/{invoice_id}", response_model=InvoiceRead)
def update_invoice(
    invoice_id: int,
    correction: InvoiceCorrection,
    session: Annotated[Session, Depends(get_db)],
) -> Invoice:
    invoice = _invoice_or_404(session, invoice_id)
    if not correction.model_fields_set:
        raise HTTPException(status_code=422, detail="Provide at least one correction.")
    if "items" in correction.model_fields_set and correction.items is None:
        raise HTTPException(
            status_code=422,
            detail="Items must be an array; use an empty array to remove all line items.",
        )
    _apply_corrections(invoice, correction)
    if invoice.currency is not None:
        invoice.currency = invoice.currency.upper()
    for item in invoice.items:
        if item.currency is not None:
            item.currency = item.currency.upper()
    _refresh_validation(invoice, session, get_settings())
    session.commit()
    return _invoice_or_404(session, invoice_id)


@router.post(
    "/invoices/{invoice_id}/validate",
    response_model=ValidationRunResponse,
)
def validate_invoice_record(
    invoice_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> ValidationRunResponse:
    invoice = _invoice_or_404(session, invoice_id)
    report = validate_invoice(_invoice_data_from_record(invoice), settings=get_settings())
    invoice.validation_status = report.status.value
    _record_validation_results(invoice, report.checks)
    session.commit()
    session.refresh(invoice)
    return ValidationRunResponse(
        invoice_id=invoice.id,
        validation=report,
        updated_at=invoice.updated_at,
    )


@router.get("/invoices/{invoice_id}/export")
def export_invoice(
    invoice_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    invoice = _invoice_or_404(session, invoice_id)
    response = InvoiceRead.model_validate(invoice)
    content = response.model_dump(mode="json")
    return JSONResponse(
        content=content,
        headers={
            "Content-Disposition": f'attachment; filename="invoice-{invoice.id}.json"'
        },
    )


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    invoice = _invoice_or_404(session, invoice_id)
    stored_filename = invoice.stored_filename
    settings = get_settings()
    storage_dir = Path(settings.storage_dir).resolve()
    source_path = (storage_dir / stored_filename).resolve()
    if source_path.parent != storage_dir:
        raise HTTPException(status_code=500, detail="Stored document path is invalid.")
    staged_path = storage_dir / f".delete-{uuid.uuid4().hex}.tmp"
    try:
        if source_path.exists():
            os.replace(source_path, staged_path)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail="Could not stage the invoice document for deletion."
        ) from exc

    try:
        session.delete(invoice)
        session.commit()
    except Exception:
        session.rollback()
        if staged_path.exists():
            try:
                os.replace(staged_path, source_path)
            except OSError as restore_error:
                raise HTTPException(
                    status_code=500,
                    detail="Invoice deletion failed and its document could not be restored.",
                ) from restore_error
        raise

    try:
        staged_path.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invoice was deleted, but its staged document could not be removed.",
        ) from exc


@router.get("/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(
    session: Annotated[Session, Depends(get_db)],
) -> DashboardStats:
    total = int(session.scalar(select(func.count()).select_from(Invoice)) or 0)
    passed = int(
        session.scalar(
            select(func.count()).select_from(Invoice).where(
                Invoice.validation_status == ValidationStatus.PASSED.value
            )
        )
        or 0
    )
    failed_processing = int(
        session.scalar(
            select(func.count()).select_from(Invoice).where(
                Invoice.processing_status == ProcessingStatus.FAILED.value
            )
        )
        or 0
    )
    needs_review = int(
        session.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(
                or_(
                    Invoice.processing_status == ProcessingStatus.FAILED.value,
                    Invoice.validation_status.in_(
                        [
                            ValidationStatus.FAILED.value,
                            ValidationStatus.WARNING.value,
                            ValidationStatus.NOT_CHECKED.value,
                        ]
                    ),
                )
            )
        )
        or 0
    )
    distribution = {
        status_value.lower(): int(
            session.scalar(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.validation_status == status_value.value)
            )
            or 0
        )
        for status_value in (
            ValidationStatus.PASSED,
            ValidationStatus.FAILED,
            ValidationStatus.WARNING,
            ValidationStatus.NOT_CHECKED,
        )
    }
    values = session.execute(
        select(Invoice.currency, func.sum(Invoice.total_amount))
        .where(
            Invoice.processing_status == ProcessingStatus.COMPLETED.value,
            Invoice.currency.is_not(None),
            Invoice.total_amount.is_not(None),
        )
        .group_by(Invoice.currency)
    ).all()
    recent = session.scalars(
        select(Invoice).order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(5)
    ).all()
    return DashboardStats(
        total_invoices=total,
        successfully_validated=passed,
        needs_review=needs_review,
        failed_processing=failed_processing,
        total_invoice_value={
            cast(str, currency): Decimal(amount)
            for currency, amount in values
        },
        validation_distribution=ValidationDistribution(**distribution),
        recent_invoices=recent,
    )
