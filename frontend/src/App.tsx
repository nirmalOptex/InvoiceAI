import { useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  BadgeCheck,
  BarChart3,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Clock3,
  CloudUpload,
  Download,
  ExternalLink,
  Eye,
  FileCheck2,
  FileText,
  Filter,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Trash2,
  X,
} from 'lucide-react'
import {
  deleteInvoice,
  getDashboardStats,
  getHealth,
  getInvoice,
  getInvoiceDocumentUrl,
  getInvoiceExportUrl,
  getInvoices,
  updateInvoice,
  uploadInvoice,
  validateInvoice,
  type DashboardStats,
  type FieldEvidence,
  type Invoice,
  type InvoiceCorrection,
  type InvoiceItem,
  type InvoiceListItem,
  type InvoiceListParams,
  type ProcessingStatus,
  type ValidationStatus,
} from './lib/api'
import './App.css'

type Section = 'overview' | 'invoices'
type ScalarField =
  | 'supplier_name'
  | 'supplier_address'
  | 'supplier_tax_id'
  | 'invoice_number'
  | 'invoice_date'
  | 'due_date'
  | 'currency'
  | 'subtotal'
  | 'discount'
  | 'tax_rate'
  | 'tax_amount'
  | 'additional_charges'
  | 'total_amount'

interface InvoiceDraft {
  description: string
  quantity: string
  unit: string
  unit_price: string
  line_total: string
  currency: string
}

const scalarFields: Array<{
  name: ScalarField
  label: string
  type: 'text' | 'date' | 'number'
  wide?: boolean
}> = [
  { name: 'supplier_name', label: 'Supplier', type: 'text' },
  { name: 'invoice_number', label: 'Invoice number', type: 'text' },
  { name: 'supplier_tax_id', label: 'Tax ID', type: 'text' },
  { name: 'currency', label: 'Currency', type: 'text' },
  { name: 'invoice_date', label: 'Invoice date', type: 'date' },
  { name: 'due_date', label: 'Due date', type: 'date' },
  { name: 'subtotal', label: 'Subtotal', type: 'number' },
  { name: 'discount', label: 'Discount', type: 'number' },
  { name: 'tax_rate', label: 'Tax rate (%)', type: 'number' },
  { name: 'tax_amount', label: 'Tax amount', type: 'number' },
  { name: 'additional_charges', label: 'Additional charges', type: 'number' },
  { name: 'total_amount', label: 'Total amount', type: 'number' },
  { name: 'supplier_address', label: 'Supplier address', type: 'text', wide: true },
]

const numericFields = new Set<ScalarField>([
  'subtotal',
  'discount',
  'tax_rate',
  'tax_amount',
  'additional_charges',
  'total_amount',
])

function displayDate(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00`)
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' }).format(parsed)
}

function displayMoney(value: number | string | null, currency: string | null): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return String(value)
  try {
    return new Intl.NumberFormat('en', {
      style: 'currency',
      currency: currency || 'USD',
      maximumFractionDigits: 2,
    }).format(amount)
  } catch {
    return `${currency ? `${currency} ` : ''}${amount.toLocaleString('en', { maximumFractionDigits: 2 })}`
  }
}

function displayCount(value: number): string {
  return new Intl.NumberFormat('en').format(value)
}

function StatusBadge({ status }: { status: ValidationStatus | ProcessingStatus }) {
  const normalized = status.toLowerCase().replaceAll('_', ' ')
  const label = normalized.replace(/\b\w/g, (letter) => letter.toUpperCase())
  return <span className={`status-badge status-${normalized.replaceAll(' ', '-')}`}>{label}</span>
}

function FieldSource({ evidence }: { evidence?: FieldEvidence }) {
  if (!evidence || (!evidence.original_source_text && evidence.page_number == null)) return null
  return (
    <span className="field-source">
      {evidence.original_source_text ? `Source: “${evidence.original_source_text}”` : 'OCR evidence'}
      {evidence.page_number != null ? ` · page ${evidence.page_number}` : ''}
      {evidence.ocr_confidence != null
        ? ` · ${Math.round(evidence.ocr_confidence * 100)}% confidence`
        : ''}
    </span>
  )
}

function InvoiceTable({
  invoices,
  onOpen,
  compact = false,
}: {
  invoices: Array<InvoiceListItem | DashboardStats['recent_invoices'][number]>
  onOpen: (id: number) => void
  compact?: boolean
}) {
  if (invoices.length === 0) {
    return (
      <div className="empty-state">
        <span className="empty-icon"><FileText size={22} /></span>
        <strong>No invoices yet</strong>
        <span>Upload your first invoice to see it here.</span>
      </div>
    )
  }

  return (
    <div className="table-scroll">
      <table className="invoice-table">
        <thead>
          <tr>
            <th>Supplier / document</th>
            <th>Invoice no.</th>
            {!compact && <th>Invoice date</th>}
            <th>Amount</th>
            <th>Processing</th>
            <th>Validation</th>
            <th aria-label="Open invoice" />
          </tr>
        </thead>
        <tbody>
          {invoices.map((invoice) => (
            <tr key={invoice.id} onClick={() => onOpen(invoice.id)}>
              <td>
                <span className="table-primary">
                  {invoice.supplier_name || ('original_filename' in invoice ? invoice.original_filename : 'Untitled invoice')}
                </span>
                <span className="table-secondary">
                  {'original_filename' in invoice ? invoice.original_filename : invoice.invoice_number || 'Recent invoice'}
                </span>
              </td>
              <td>{invoice.invoice_number || '—'}</td>
              {!compact && <td>{displayDate('invoice_date' in invoice ? invoice.invoice_date : null)}</td>}
              <td className="amount-cell">{displayMoney(invoice.total_amount, invoice.currency)}</td>
              <td><StatusBadge status={invoice.processing_status} /></td>
              <td><StatusBadge status={invoice.validation_status} /></td>
              <td><button className="icon-button row-open" type="button" aria-label="Review invoice" onClick={(event) => { event.stopPropagation(); onOpen(invoice.id) }}><Eye size={16} /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function UploadDialog({
  onClose,
  onUpload,
  isUploading,
  error,
}: {
  onClose: () => void
  onUpload: (file: File) => void
  isUploading: boolean
  error: string | null
}) {
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
  }

  function dropFile(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault()
    setDragging(false)
    setFile(event.dataTransfer.files[0] ?? null)
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (file) onUpload(file)
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !isUploading) onClose() }}>
      <section className="upload-dialog" role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">DOCUMENT INTAKE</span>
            <h2 id="upload-title">Upload an invoice</h2>
            <p>We’ll extract the details and check the totals for you.</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} disabled={isUploading} aria-label="Close upload dialog"><X size={19} /></button>
        </div>
        <form onSubmit={submit}>
          <label
            className={`dropzone ${dragging ? 'dropzone-active' : ''} ${file ? 'dropzone-selected' : ''}`}
            onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={dropFile}
          >
            <input type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onChange={chooseFile} />
            <span className="dropzone-icon"><CloudUpload size={24} /></span>
            {file ? (
              <>
                <strong>{file.name}</strong>
                <span>{(file.size / (1024 * 1024)).toFixed(2)} MB · Ready to process</span>
              </>
            ) : (
              <>
                <strong>Drop your invoice here, or <span className="text-link">browse files</span></strong>
                <span>PDF, PNG or JPG · up to 15 MB</span>
              </>
            )}
          </label>
          {error && <div className="inline-error"><CircleAlert size={16} />{error}</div>}
          <div className="dialog-actions">
            <button className="button button-quiet" type="button" onClick={onClose} disabled={isUploading}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={!file || isUploading}>
              {isUploading ? <><LoaderCircle className="spin" size={16} /> Processing…</> : <><CloudUpload size={16} /> Upload invoice</>}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}

function emptyDraft(): InvoiceDraft {
  return { description: '', quantity: '1', unit: '', unit_price: '', line_total: '', currency: '' }
}

function draftFromItem(item: InvoiceItem): InvoiceDraft {
  return {
    description: item.description ?? '',
    quantity: item.quantity == null ? '' : String(item.quantity),
    unit: item.unit ?? '',
    unit_price: item.unit_price == null ? '' : String(item.unit_price),
    line_total: item.line_total == null ? '' : String(item.line_total),
    currency: item.currency ?? '',
  }
}

function invoiceValues(invoice: Invoice): Record<ScalarField, string> {
  return {
    supplier_name: invoice.supplier_name ?? '',
    supplier_address: invoice.supplier_address ?? '',
    supplier_tax_id: invoice.supplier_tax_id ?? '',
    invoice_number: invoice.invoice_number ?? '',
    invoice_date: invoice.invoice_date ?? '',
    due_date: invoice.due_date ?? '',
    currency: invoice.currency ?? '',
    subtotal: invoice.subtotal == null ? '' : String(invoice.subtotal),
    discount: invoice.discount == null ? '' : String(invoice.discount),
    tax_rate: invoice.tax_rate == null ? '' : String(invoice.tax_rate),
    tax_amount: invoice.tax_amount == null ? '' : String(invoice.tax_amount),
    additional_charges: invoice.additional_charges == null ? '' : String(invoice.additional_charges),
    total_amount: invoice.total_amount == null ? '' : String(invoice.total_amount),
  }
}

function numericValue(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function InvoiceReview({
  invoice,
  onClose,
  onSave,
  onValidate,
  onDelete,
  saving,
  validating,
  deleting,
}: {
  invoice: Invoice
  onClose: () => void
  onSave: (correction: InvoiceCorrection) => void
  onValidate: () => void
  onDelete: () => void
  saving: boolean
  validating: boolean
  deleting: boolean
}) {
  const [values, setValues] = useState(() => invoiceValues(invoice))
  const [dirtyFields, setDirtyFields] = useState<Set<ScalarField>>(() => new Set())
  const [items, setItems] = useState(() => invoice.items.map(draftFromItem))
  const [itemsDirty, setItemsDirty] = useState(false)

  function updateField(name: ScalarField, value: string) {
    setValues((current) => ({ ...current, [name]: value }))
    setDirtyFields((current) => new Set(current).add(name))
  }

  function updateItem(index: number, key: keyof InvoiceDraft, value: string) {
    setItems((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: value } : item))
    setItemsDirty(true)
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const correction: InvoiceCorrection = {}
    for (const name of dirtyFields) {
      const value = values[name]
      if (numericFields.has(name)) Object.assign(correction, { [name]: numericValue(value) })
      else Object.assign(correction, { [name]: value.trim() || null })
    }
    if (itemsDirty) {
      correction.items = items.map((item) => ({
        description: item.description.trim() || null,
        quantity: numericValue(item.quantity),
        unit: item.unit.trim() || null,
        unit_price: numericValue(item.unit_price),
        line_total: numericValue(item.line_total),
        currency: item.currency.trim().toUpperCase() || null,
      }))
    }
    if (Object.keys(correction).length > 0) onSave(correction)
  }

  const previewIsImage = /\.(png|jpe?g)$/i.test(invoice.original_filename)
  const checks = invoice.validation_results ?? []
  const ocrLines = invoice.extraction_metadata?.ocr_lines ?? []

  return (
    <div className="review-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="review-panel" role="dialog" aria-modal="true" aria-labelledby="review-title">
        <header className="review-header">
          <div className="review-header-main">
            <button className="icon-button back-button" type="button" onClick={onClose} aria-label="Close invoice review"><ChevronLeft size={20} /></button>
            <span className="review-file-icon"><FileText size={18} /></span>
            <div className="review-title-wrap">
              <span className="eyebrow">INVOICE REVIEW · #{invoice.id}</span>
              <h2 id="review-title">{invoice.supplier_name || invoice.original_filename}</h2>
              <span className="review-file-name">{invoice.original_filename}</span>
            </div>
          </div>
          <div className="review-header-actions">
            <a className="button button-quiet button-small" href={getInvoiceExportUrl(invoice.id)} download><Download size={15} /> Export JSON</a>
            <button className="icon-button" type="button" onClick={onClose} aria-label="Close"><X size={19} /></button>
          </div>
        </header>

        <div className="review-content">
          <div className="review-main-column">
            {invoice.processing_error && (
              <div className="processing-notice"><ShieldAlert size={18} /><div><strong>Extraction needs attention</strong><span>{invoice.processing_error}</span></div></div>
            )}
            {invoice.extraction_metadata?.warnings?.map((warning) => (
              <div className="processing-notice warning-notice" key={warning}><CircleAlert size={18} /><div><strong>Processing note</strong><span>{warning}</span></div></div>
            ))}

            <section className="review-card">
              <div className="section-title-row">
                <div><h3>Extracted details</h3><p>Review and correct any fields before saving.</p></div>
                <StatusBadge status={invoice.validation_status} />
              </div>
              <form onSubmit={save}>
                <div className="field-grid">
                  {scalarFields.map((field) => (
                    <label className={`form-field ${field.wide ? 'field-wide' : ''}`} key={field.name}>
                      <span>{field.label}</span>
                      <input
                        type={field.type}
                        step={field.type === 'number' ? 'any' : undefined}
                        min={field.type === 'number' ? '0' : undefined}
                        value={values[field.name]}
                        onChange={(event) => updateField(field.name, event.target.value)}
                      />
                      <FieldSource evidence={invoice.field_evidence?.[field.name]} />
                    </label>
                  ))}
                </div>

                <div className="items-editor-heading">
                  <div><h3>Line items</h3><p>Update item details to recalculate validation.</p></div>
                  <button className="button button-quiet button-small" type="button" onClick={() => { setItems((current) => [...current, emptyDraft()]); setItemsDirty(true) }}><Plus size={15} /> Add item</button>
                </div>
                <div className="item-editor-list">
                  {items.length === 0 && <p className="muted-copy">No line items extracted. Add one if needed.</p>}
                  {items.map((item, index) => (
                    <div className="item-editor-row" key={`item-${index}`}>
                      <label className="form-field item-description"><span>Description</span><input value={item.description} onChange={(event) => updateItem(index, 'description', event.target.value)} /></label>
                      <label className="form-field"><span>Qty</span><input type="number" min="0" step="any" value={item.quantity} onChange={(event) => updateItem(index, 'quantity', event.target.value)} /></label>
                      <label className="form-field"><span>Unit</span><input value={item.unit} onChange={(event) => updateItem(index, 'unit', event.target.value)} /></label>
                      <label className="form-field"><span>Unit price</span><input type="number" min="0" step="any" value={item.unit_price} onChange={(event) => updateItem(index, 'unit_price', event.target.value)} /></label>
                      <label className="form-field"><span>Line total</span><input type="number" min="0" step="any" value={item.line_total} onChange={(event) => updateItem(index, 'line_total', event.target.value)} /></label>
                      <label className="form-field"><span>Currency</span><input maxLength={3} value={item.currency} onChange={(event) => updateItem(index, 'currency', event.target.value)} /></label>
                      <button className="icon-button remove-item" type="button" aria-label={`Remove item ${index + 1}`} onClick={() => { setItems((current) => current.filter((_, itemIndex) => itemIndex !== index)); setItemsDirty(true) }}><Trash2 size={15} /></button>
                      {invoice.items[index] && <FieldSource evidence={invoice.items[index].source_evidence?.line_total} />}
                    </div>
                  ))}
                </div>
                <div className="form-actions">
                  <span className="muted-copy">Changes recalculate financial checks.</span>
                  <button className="button button-primary" type="submit" disabled={saving || (dirtyFields.size === 0 && !itemsDirty)}>
                    {saving ? <><LoaderCircle className="spin" size={16} /> Saving…</> : <><Check size={16} /> Save corrections</>}
                  </button>
                </div>
              </form>
            </section>

            <section className="review-card validation-card">
              <div className="section-title-row">
                <div><h3>Validation checks</h3><p>Deterministic checks for invoice amounts and required data.</p></div>
                <button className="button button-quiet button-small" type="button" onClick={onValidate} disabled={validating}>
                  {validating ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
                  Re-run checks
                </button>
              </div>
              {checks.length > 0 ? (
                <div className="check-list">
                  {checks.map((check) => (
                    <div className="check-row" key={`${check.check_name}-${check.message}`}>
                      <span className={`check-mark check-${check.status.toLowerCase()}`}>
                        {check.status === 'PASSED' ? <CircleCheck size={17} /> : check.status === 'FAILED' ? <CircleAlert size={17} /> : <Clock3 size={17} />}
                      </span>
                      <div className="check-copy"><strong>{check.check_name.replaceAll('_', ' ')}</strong><span>{check.message}</span></div>
                      <StatusBadge status={check.status} />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="checks-empty"><Clock3 size={17} /><span>No validation results yet. Run checks to review this invoice.</span></div>
              )}
            </section>

            {ocrLines.length > 0 && (
              <details className="review-card evidence-card">
                <summary><span><Eye size={17} /> OCR source evidence</span><span>{ocrLines.length} text lines</span></summary>
                <div className="ocr-lines">
                  {ocrLines.map((line, index) => (
                    <div className="ocr-line" key={`${line.page_number}-${index}`}>
                      <span>{line.text}</span>
                      <small>Page {line.page_number}{line.confidence != null ? ` · ${Math.round(line.confidence * 100)}%` : ''}</small>
                    </div>
                  ))}
                </div>
              </details>
            )}

            <div className="review-danger-zone">
              <div><strong>Delete this invoice</strong><span>Remove the invoice record and its stored document.</span></div>
              <button className="button button-danger button-small" type="button" onClick={onDelete} disabled={deleting}>
                {deleting ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />} Delete
              </button>
            </div>
          </div>

          <aside className="document-column">
            <div className="document-preview-card">
              <div className="document-preview-heading"><span><Eye size={16} /> Original document</span><a href={getInvoiceDocumentUrl(invoice.id)} target="_blank" rel="noreferrer" aria-label="Open document in a new tab"><ExternalLink size={15} /></a></div>
              <div className="document-preview">
                {previewIsImage ? (
                  <img src={getInvoiceDocumentUrl(invoice.id)} alt={`Preview of ${invoice.original_filename}`} />
                ) : (
                  <iframe src={getInvoiceDocumentUrl(invoice.id)} title={`Preview of ${invoice.original_filename}`} />
                )}
              </div>
              <div className="document-meta">
                <span>{invoice.original_filename}</span>
                <small>{invoice.extraction_metadata?.page_count ?? 1} page{(invoice.extraction_metadata?.page_count ?? 1) === 1 ? '' : 's'} · {invoice.extraction_metadata?.source_type || 'document'}</small>
              </div>
            </div>
          </aside>
        </div>
      </section>
    </div>
  )
}

function MetricCard({
  label,
  value,
  note,
  icon: Icon,
  tone,
}: {
  label: string
  value: string
  note: string
  icon: typeof FileText
  tone: 'blue' | 'green' | 'amber' | 'red'
}) {
  return (
    <article className="metric-card">
      <div className="metric-heading"><span>{label}</span><span className={`metric-icon metric-${tone}`}><Icon size={18} /></span></div>
      <strong className="metric-value">{value}</strong>
      <span className="metric-note">{note}</span>
    </article>
  )
}

function Dashboard({
  stats,
  onViewAll,
  onOpen,
  onUpload,
}: {
  stats: DashboardStats
  onViewAll: () => void
  onOpen: (id: number) => void
  onUpload: () => void
}) {
  const distribution = stats.validation_distribution
  const distributionTotal = Math.max(
    distribution.passed + distribution.failed + distribution.warning + distribution.not_checked,
    1,
  )
  const statusBars = [
    { label: 'Passed', count: distribution.passed, color: 'bar-green' },
    { label: 'Needs review', count: distribution.failed, color: 'bar-red' },
    { label: 'Warnings', count: distribution.warning, color: 'bar-amber' },
    { label: 'Not checked', count: distribution.not_checked, color: 'bar-slate' },
  ]

  return (
    <>
      <div className="page-heading">
        <div><span className="eyebrow">WORKSPACE OVERVIEW</span><h1>Good to see you.</h1><p>Here’s what’s happening with your invoices.</p></div>
        <button className="button button-primary" type="button" onClick={onUpload}><Plus size={17} /> Upload invoice</button>
      </div>
      <div className="metrics-grid">
        <MetricCard label="Total invoices" value={displayCount(stats.total_invoices)} note="Invoices in your workspace" icon={FileText} tone="blue" />
        <MetricCard label="Successfully validated" value={displayCount(stats.successfully_validated)} note={`${stats.total_invoices ? Math.round(stats.successfully_validated / stats.total_invoices * 100) : 0}% of all invoices`} icon={BadgeCheck} tone="green" />
        <MetricCard label="Needs review" value={displayCount(stats.needs_review)} note="Errors or incomplete checks" icon={ShieldAlert} tone="amber" />
        <MetricCard label="Processing issues" value={displayCount(stats.failed_processing)} note="Extraction could not finish" icon={CircleAlert} tone="red" />
      </div>

      <div className="dashboard-grid">
        <section className="surface-card recent-card">
          <div className="card-heading"><div><h2>Recent invoices</h2><p>Your latest processed documents</p></div><button className="text-button" type="button" onClick={onViewAll}>View all <ArrowUpRight size={15} /></button></div>
          <InvoiceTable invoices={stats.recent_invoices} onOpen={onOpen} compact />
        </section>

        <section className="surface-card insights-card">
          <div className="card-heading"><div><h2>Validation overview</h2><p>Invoice checks at a glance</p></div><span className="insights-icon"><BarChart3 size={17} /></span></div>
          <div className="distribution-total"><strong>{displayCount(stats.total_invoices)}</strong><span>total invoices</span></div>
          <div className="distribution-bars">
            {statusBars.map((bar) => (
              <div className="distribution-row" key={bar.label}>
                <div className="distribution-label"><span>{bar.label}</span><strong>{bar.count}</strong></div>
                <div className="distribution-track"><span className={bar.color} style={{ width: `${bar.count / distributionTotal * 100}%` }} /></div>
              </div>
            ))}
          </div>
          <div className="totals-heading"><span>Invoice value by currency</span></div>
          {Object.keys(stats.total_invoice_value).length > 0 ? (
            <div className="currency-totals">{Object.entries(stats.total_invoice_value).map(([currency, value]) => <div key={currency}><span>{currency}</span><strong>{displayMoney(value, currency)}</strong></div>)}</div>
          ) : <p className="muted-copy totals-empty">Totals appear here when invoices have been extracted.</p>}
        </section>
      </div>
    </>
  )
}

function InvoiceHistory({
  data,
  params,
  onParamsChange,
  onOpen,
  onUpload,
  isLoading,
}: {
  data: Awaited<ReturnType<typeof getInvoices>> | undefined
  params: InvoiceListParams
  onParamsChange: (params: InvoiceListParams) => void
  onOpen: (id: number) => void
  onUpload: () => void
  isLoading: boolean
}) {
  return (
    <>
      <div className="page-heading">
        <div><span className="eyebrow">DOCUMENT LIBRARY</span><h1>Invoices</h1><p>Search, review, and manage your invoice documents.</p></div>
        <button className="button button-primary" type="button" onClick={onUpload}><Plus size={17} /> Upload invoice</button>
      </div>
      <section className="surface-card history-card">
        <div className="history-toolbar">
          <label className="search-field"><Search size={17} /><input value={params.q ?? ''} placeholder="Search supplier or invoice number" onChange={(event) => onParamsChange({ ...params, q: event.target.value, page: 1 })} /></label>
          <label className="filter-field"><Filter size={15} /><select value={params.validation_status ?? ''} onChange={(event) => onParamsChange({ ...params, validation_status: event.target.value as ValidationStatus | '', page: 1 })}><option value="">All validation</option><option value="PASSED">Passed</option><option value="FAILED">Failed</option><option value="WARNING">Warning</option><option value="NOT_CHECKED">Not checked</option></select></label>
          <label className="filter-field"><select value={params.processing_status ?? ''} onChange={(event) => onParamsChange({ ...params, processing_status: event.target.value as ProcessingStatus | '', page: 1 })}><option value="">All processing</option><option value="COMPLETED">Completed</option><option value="FAILED">Failed</option><option value="PROCESSING">Processing</option><option value="PENDING">Pending</option></select></label>
          <label className="sort-field"><span>Sort by</span><select value={params.sort_by} onChange={(event) => onParamsChange({ ...params, sort_by: event.target.value as InvoiceListParams['sort_by'], page: 1 })}><option value="created_at">Date added</option><option value="invoice_date">Invoice date</option><option value="supplier_name">Supplier</option><option value="invoice_number">Invoice number</option><option value="total_amount">Amount</option></select></label>
          <button className="icon-button sort-direction" type="button" onClick={() => onParamsChange({ ...params, order: params.order === 'desc' ? 'asc' : 'desc', page: 1 })} aria-label={`Sort ${params.order === 'desc' ? 'ascending' : 'descending'}`}>{params.order === 'desc' ? <ArrowDown size={16} /> : <ArrowUp size={16} />}</button>
        </div>
        {isLoading ? <div className="loading-state"><LoaderCircle className="spin" size={22} /> Loading invoices…</div> : (
          <InvoiceTable invoices={data?.items ?? []} onOpen={onOpen} />
        )}
        {data && (
          <div className="pagination">
            <span>Showing {data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1}–{Math.min(data.page * data.page_size, data.total)} of {displayCount(data.total)} invoices</span>
            <div><button className="icon-button" type="button" aria-label="Previous page" disabled={data.page <= 1} onClick={() => onParamsChange({ ...params, page: params.page - 1 })}><ChevronLeft size={17} /></button><span>Page {data.page} of {Math.max(data.pages, 1)}</span><button className="icon-button" type="button" aria-label="Next page" disabled={data.page >= data.pages} onClick={() => onParamsChange({ ...params, page: params.page + 1 })}><ChevronRight size={17} /></button></div>
          </div>
        )}
      </section>
    </>
  )
}

function App() {
  const queryClient = useQueryClient()
  const [section, setSection] = useState<Section>('overview')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [reviewRevision, setReviewRevision] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)
  const [params, setParams] = useState<InvoiceListParams>({
    sort_by: 'created_at',
    order: 'desc',
    page: 1,
    page_size: 20,
  })

  const dashboardQuery = useQuery({
    queryKey: ['dashboard'],
    queryFn: getDashboardStats,
  })
  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: 1,
    refetchInterval: 30000,
  })
  const invoicesQuery = useQuery({
    queryKey: ['invoices', params],
    queryFn: () => getInvoices(params),
    enabled: section === 'invoices',
    placeholderData: (previous) => previous,
  })
  const selectedQuery = useQuery({
    queryKey: ['invoice', selectedId],
    queryFn: () => getInvoice(selectedId!),
    enabled: selectedId !== null,
  })

  const uploadMutation = useMutation({
    mutationFn: uploadInvoice,
    onSuccess: async (invoice) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
      ])
      queryClient.setQueryData(['invoice', invoice.id], invoice)
      setUploadOpen(false)
      setSection('invoices')
      setSelectedId(invoice.id)
      setNotice(invoice.processing_status === 'FAILED'
        ? 'Invoice saved, but extraction needs attention. Review the document and enter details manually.'
        : 'Invoice uploaded and processed successfully.')
    },
  })
  const saveMutation = useMutation({
    mutationFn: (correction: InvoiceCorrection) => updateInvoice(selectedId!, correction),
    onSuccess: async (invoice) => {
      queryClient.setQueryData(['invoice', invoice.id], invoice)
      setReviewRevision((revision) => revision + 1)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
      ])
      setNotice('Corrections saved and validation updated.')
    },
  })
  const validateMutation = useMutation({
    mutationFn: () => validateInvoice(selectedId!),
    onSuccess: async () => {
      setReviewRevision((revision) => revision + 1)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['invoice', selectedId] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
      ])
      setNotice('Validation checks completed.')
    },
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteInvoice(selectedId!),
    onSuccess: async () => {
      const deletedId = selectedId
      setSelectedId(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
      ])
      if (deletedId !== null) queryClient.removeQueries({ queryKey: ['invoice', deletedId] })
      setNotice('Invoice and stored document deleted.')
    },
  })

  const actionError = saveMutation.error ?? validateMutation.error ?? deleteMutation.error

  function openInvoice(id: number) {
    setSelectedId(id)
    saveMutation.reset()
    validateMutation.reset()
    deleteMutation.reset()
  }

  function closeReview() {
    setSelectedId(null)
    saveMutation.reset()
    validateMutation.reset()
    deleteMutation.reset()
  }

  function changeParams(next: InvoiceListParams) {
    setParams(next)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setSection('overview') }}>
          <span className="brand-mark">IQ</span>
          <span><strong>InvoiceIQ</strong><small>Invoice workspace</small></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          <button className={section === 'overview' ? 'nav-item nav-active' : 'nav-item'} type="button" onClick={() => setSection('overview')}><BarChart3 size={17} /> Overview</button>
          <button className={section === 'invoices' ? 'nav-item nav-active' : 'nav-item'} type="button" onClick={() => setSection('invoices')}><FileCheck2 size={17} /> Invoices<span className="nav-count">{dashboardQuery.data?.total_invoices ?? 0}</span></button>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-promo">
            <span className="promo-icon"><ShieldAlert size={16} /></span>
            <strong>Review with confidence</strong>
            <p>OCR evidence and deterministic checks keep every invoice traceable.</p>
          </div>
          <div className="sidebar-status"><span className={`online-dot ${healthQuery.isSuccess && healthQuery.data.status === 'ok' ? '' : 'offline-dot'}`} />{healthQuery.isLoading ? 'Checking API…' : healthQuery.isSuccess && healthQuery.data.status === 'ok' ? 'API connected' : 'API unavailable'}<button className="health-retry" type="button" onClick={() => void healthQuery.refetch()} aria-label="Check API connection"><RefreshCw size={13} /></button><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer" aria-label="Open API docs"><ArrowUpRight size={14} /></a></div>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><ChevronRight size={14} /><strong>{section === 'overview' ? 'Overview' : 'Invoices'}</strong></div>
          <div className="topbar-actions"><span className="environment-pill"><span /> Local environment</span><button className="button button-primary button-small" type="button" onClick={() => { uploadMutation.reset(); setUploadOpen(true) }}><Plus size={16} /> New invoice</button></div>
        </header>

        <main className="page-content">
          {notice && <div className="notice-banner"><CircleCheck size={17} /><span>{notice}</span><button type="button" className="icon-button" onClick={() => setNotice(null)} aria-label="Dismiss notification"><X size={15} /></button></div>}
          {section === 'overview' ? (
            dashboardQuery.isLoading ? <div className="loading-state page-loading"><LoaderCircle className="spin" size={22} /> Loading your workspace…</div>
              : dashboardQuery.error ? <div className="page-error"><CircleAlert size={20} /><div><strong>Couldn’t load your dashboard</strong><span>{dashboardQuery.error.message}</span><button className="text-button" type="button" onClick={() => void dashboardQuery.refetch()}>Try again <RefreshCw size={14} /></button></div></div>
                : dashboardQuery.data ? <Dashboard stats={dashboardQuery.data} onViewAll={() => setSection('invoices')} onOpen={openInvoice} onUpload={() => { uploadMutation.reset(); setUploadOpen(true) }} /> : null
          ) : (
            <InvoiceHistory data={invoicesQuery.data} params={params} onParamsChange={changeParams} onOpen={openInvoice} onUpload={() => { uploadMutation.reset(); setUploadOpen(true) }} isLoading={invoicesQuery.isLoading} />
          )}
        </main>
        <footer className="app-footer"><span>InvoiceIQ · Invoice processing with evidence</span><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">API documentation <ArrowUpRight size={13} /></a></footer>
      </div>

      {uploadOpen && <UploadDialog onClose={() => { if (!uploadMutation.isPending) setUploadOpen(false) }} onUpload={(file) => uploadMutation.mutate(file)} isUploading={uploadMutation.isPending} error={uploadMutation.error?.message ?? null} />}
      {selectedId !== null && (
        selectedQuery.isLoading ? <div className="review-backdrop"><div className="review-loading"><LoaderCircle className="spin" size={24} /> Loading invoice…</div></div>
          : selectedQuery.error ? <div className="review-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeReview() }}><div className="review-error"><button className="icon-button" type="button" onClick={closeReview} aria-label="Close"><X size={18} /></button><CircleAlert size={22} /><strong>Couldn’t open this invoice</strong><span>{selectedQuery.error.message}</span><button className="button button-quiet" type="button" onClick={() => void selectedQuery.refetch()}>Try again</button></div></div>
            : selectedQuery.data ? (
              <>
                {actionError && <div className="action-error"><CircleAlert size={16} /><span>{actionError.message}</span><button type="button" onClick={() => { saveMutation.reset(); validateMutation.reset(); deleteMutation.reset() }} aria-label="Dismiss error"><X size={15} /></button></div>}
                <InvoiceReview key={`${selectedId}-${reviewRevision}`} invoice={selectedQuery.data} onClose={closeReview} onSave={(correction) => saveMutation.mutate(correction)} onValidate={() => validateMutation.mutate()} onDelete={() => { if (window.confirm('Delete this invoice and its stored document? This cannot be undone.')) deleteMutation.mutate() }} saving={saveMutation.isPending} validating={validateMutation.isPending} deleting={deleteMutation.isPending} />
              </>
            ) : null
      )}
    </div>
  )
}

export default App
