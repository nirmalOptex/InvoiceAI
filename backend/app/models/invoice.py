from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_invoice_processing_status",
        ),
        CheckConstraint(
            "validation_status IN ('PENDING', 'PASSED', 'FAILED', 'WARNING', 'NOT_CHECKED')",
            name="ck_invoice_validation_status",
        ),
        Index("ix_invoices_invoice_date", "invoice_date"),
        Index("ix_invoices_created_at", "created_at"),
        Index("ix_invoices_validation_status", "validation_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    supplier_address: Mapped[str | None] = mapped_column(Text)
    supplier_tax_id: Mapped[str | None] = mapped_column(String(100))
    invoice_number: Mapped[str | None] = mapped_column(String(100), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    discount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    additional_charges: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    processing_error: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="NOT_CHECKED"
    )
    raw_extraction_json: Mapped[dict | None] = mapped_column(JSON)
    extraction_metadata: Mapped[dict | None] = mapped_column(JSON)
    field_evidence: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    validation_results: Mapped[list["ValidationResult"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (Index("ix_invoice_items_invoice_id", "invoice_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    source_evidence: Mapped[dict | None] = mapped_column(JSON)
    manually_corrected: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class ValidationResult(Base):
    __tablename__ = "validation_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PASSED', 'FAILED', 'WARNING', 'NOT_CHECKED')",
            name="ck_validation_result_status",
        ),
        Index("ix_validation_results_invoice_id", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    check_name: Mapped[str] = mapped_column(String(100), nullable=False)
    expected_value: Mapped[str | None] = mapped_column(String(255))
    actual_value: Mapped[str | None] = mapped_column(String(255))
    difference: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    invoice: Mapped[Invoice] = relationship(back_populates="validation_results")
