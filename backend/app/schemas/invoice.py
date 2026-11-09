from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProcessingStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ValidationStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    NOT_CHECKED = "NOT_CHECKED"


class CheckStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    NOT_CHECKED = "NOT_CHECKED"


class FieldEvidence(BaseModel):
    extracted_value: Any = None
    original_source_text: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    bounding_box: list[float] | None = None
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_provider: str | None = None
    manually_corrected: bool = False


class InvoiceItemInput(BaseModel):
    description: str | None = None
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source_evidence: dict[str, FieldEvidence] = Field(default_factory=dict)
    manually_corrected: bool = False


class InvoiceData(BaseModel):
    supplier_name: str | None = None
    supplier_address: str | None = None
    supplier_tax_id: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    items: list[InvoiceItemInput] = Field(default_factory=list)
    subtotal: Decimal | None = Field(default=None, ge=0)
    discount: Decimal | None = Field(default=None, ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    tax_amount: Decimal | None = Field(default=None, ge=0)
    additional_charges: Decimal | None = Field(default=None, ge=0)
    total_amount: Decimal | None = Field(default=None, ge=0)
    field_evidence: dict[str, FieldEvidence] = Field(default_factory=dict)


class InvoiceCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_name: str | None = None
    supplier_address: str | None = None
    supplier_tax_id: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    items: list[InvoiceItemInput] | None = None
    subtotal: Decimal | None = Field(default=None, ge=0)
    discount: Decimal | None = Field(default=None, ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    tax_amount: Decimal | None = Field(default=None, ge=0)
    additional_charges: Decimal | None = Field(default=None, ge=0)
    total_amount: Decimal | None = Field(default=None, ge=0)


class ValidationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    check_name: str
    expected_value: str | None
    actual_value: str | None
    difference: Decimal | None
    status: CheckStatus
    message: str
    created_at: datetime


class ValidationCheck(BaseModel):
    check_name: str
    expected_value: str | None = None
    actual_value: str | None = None
    difference: Decimal | None = None
    status: CheckStatus
    message: str


class ValidationReport(BaseModel):
    status: ValidationStatus
    checks: list[ValidationCheck]
    passed_checks: int
    failed_checks: int
    warning_checks: int
    not_checked: int


class InvoiceItemRead(InvoiceItemInput):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class InvoiceRead(InvoiceData):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    processing_status: ProcessingStatus
    processing_error: str | None
    validation_status: ValidationStatus
    is_verified: bool
    raw_extraction_json: dict[str, Any] | None
    extraction_metadata: dict[str, Any] | None
    items: list[InvoiceItemRead]
    validation_results: list[ValidationResultRead]
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str
    app: str


class InvoiceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    supplier_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    currency: str | None
    total_amount: Decimal | None
    processing_status: ProcessingStatus
    processing_error: str | None
    validation_status: ValidationStatus
    is_verified: bool
    created_at: datetime


class InvoicePage(BaseModel):
    items: list[InvoiceListItem]
    total: int
    page: int
    page_size: int
    pages: int


class ValidationRunResponse(BaseModel):
    invoice_id: int
    validation: ValidationReport
    updated_at: datetime


class ValidationDistribution(BaseModel):
    passed: int
    failed: int
    warning: int
    not_checked: int


class DashboardRecentInvoice(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_name: str | None
    invoice_number: str | None
    currency: str | None
    total_amount: Decimal | None
    processing_status: ProcessingStatus
    validation_status: ValidationStatus
    is_verified: bool
    created_at: datetime


class DashboardStats(BaseModel):
    total_invoices: int
    successfully_validated: int
    needs_review: int
    failed_processing: int
    total_invoice_value: dict[str, Decimal]
    validation_distribution: ValidationDistribution
    recent_invoices: list[DashboardRecentInvoice]
