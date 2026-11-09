import { useEffect, useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react'
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
  reprocessInvoice,
  updateInvoice,
  uploadInvoices,
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
  const tone = normalized === 'passed' || normalized === 'completed'
    ? "[border-color:#c6ead8] [background:#eefaf4] [color:#147d52] [border-color:#d1dfc7] [background:#edf4e8] [color:#4b713a]"
    : normalized === 'failed'
      ? "[border-color:#f1cdcd] [background:#fff2f1] [color:#c33c3c] [border-color:#ebd0c8] [background:#fbefeb] [color:#a84c3c]"
      : normalized === 'warning' || normalized === 'processing'
        ? "[border-color:#f3dfb8] [background:#fff8e9] [color:#a76b14] [border-color:#e8dfb9] [background:#f8f4df] [color:#83671f]"
        : "[border-color:#e3e7ed] [background:#f5f6f8] [color:#727d8f] [border-color:#dfe4dc] [background:#f0f2ed] [color:#6f7b71]"
  return <span className={"[display:inline-flex] [min-height:20px] [align-items:center] [border:1px_solid_transparent] [border-radius:99px] [padding:0_7px] [font-size:9px] [font-weight:630] [line-height:1] [white-space:nowrap]" + ' ' + tone}>{label}</span>
}

function FieldSource({ evidence }: { evidence?: FieldEvidence }) {
  if (!evidence || (!evidence.original_source_text && evidence.page_number == null)) return null
  return (
    <span className={"[color:#98a1af] [font-size:8px] [font-weight:420] [line-height:1.4]"}>
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
      <div className={"[display:flex] [min-height:195px] [flex-direction:column] [align-items:center] [justify-content:center] [gap:7px] [color:#8a94a4] [font-size:11px] [&_strong]:[margin-top:5px] [&_strong]:[color:#475368] [&_strong]:[font-size:12px] [&_strong]:[font-weight:620]"}>
        <span className={"[display:grid] [width:40px] [height:40px] [place-items:center] [border-radius:11px] [background:#f3f6fa] [color:#76849a] [border-radius:8px] [background:#e9eee5] [color:#647a58]"}><FileText size={22} /></span>
        <strong>No invoices yet</strong>
        <span>Upload your first invoice to see it here.</span>
      </div>
    )
  }

  return (
    <div className={"max-[680px]:[overflow-x:auto]"}>
      <table className={"[width:100%] [border-collapse:collapse] [text-align:left] [&_th]:[height:35px] [&_th]:[border-top:1px_solid_#eff1f4] [&_th]:[border-bottom:1px_solid_#eff1f4] [&_th]:[background:#fafbfc] [&_th]:[padding:0_12px] [&_th]:[color:#8993a3] [&_th]:[font-size:9px] [&_th]:[font-weight:620] [&_th]:[white-space:nowrap] [&_th:first-child]:[padding-left:19px] [&_td:first-child]:[padding-left:19px] [&_td]:[height:56px] [&_td]:[border-bottom:1px_solid_#f0f2f5] [&_td]:[padding:7px_12px] [&_td]:[color:#5e697c] [&_td]:[font-size:10px] [&_td]:[white-space:nowrap] [&_tbody_tr]:[cursor:pointer] [&_tbody_tr]:[transition:background_110ms_ease] [&_tbody_tr:hover]:[background:#fafcff] [&_tbody_tr:last-child_td]:[border-bottom:0] max-[680px]:[min-width:670px] [&_th]:[border-color:#e0e6dd] [&_th]:[background:#eef2e9] [&_th]:[color:#778379] [&_td]:[border-color:#e7ebe4] [&_td]:[color:#647168] [&_tbody_tr:hover]:[background:#f0f4e9]"}>
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
                <span className={"[display:block] [max-width:205px] [overflow:hidden] [text-overflow:ellipsis] [color:#344054] [font-size:11px] [font-weight:620] [color:var(--forest)]"}>
                  {invoice.supplier_name || ('original_filename' in invoice ? invoice.original_filename : 'Untitled invoice')}
                </span>
                <span className={"[display:block] [max-width:205px] [overflow:hidden] [text-overflow:ellipsis] [margin-top:4px] [color:#98a1af] [font-size:9px] [color:#89948b]"}>
                  {'original_filename' in invoice ? invoice.original_filename : invoice.invoice_number || 'Recent invoice'}
                </span>
              </td>
              <td>{invoice.invoice_number || '—'}</td>
              {!compact && <td>{displayDate('invoice_date' in invoice ? invoice.invoice_date : null)}</td>}
              <td className={"[color:#354156_!important] [font-weight:630] [color:var(--forest)_!important]"}>{displayMoney(invoice.total_amount, invoice.currency)}</td>
              <td><StatusBadge status={invoice.processing_status} /></td>
              <td><StatusBadge status={invoice.validation_status} /></td>
              <td><button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)] [width:27px] [height:27px] [color:#8893a3]"} type="button" aria-label="Review invoice" onClick={(event) => { event.stopPropagation(); onOpen(invoice.id) }}><Eye size={16} /></button></td>
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
  onUpload: (files: File[]) => void
  isUploading: boolean
  error: string | null
}) {
  const [files, setFiles] = useState<File[]>([])
  const [dragging, setDragging] = useState(false)
  const [selectionError, setSelectionError] = useState<string | null>(null)

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(event.target.files ?? []))
    event.currentTarget.value = ''
  }

  function addFiles(incoming: File[]) {
    setSelectionError(null)
    const combined = [...files, ...incoming]
    if (combined.length > 10) setSelectionError('Choose no more than 10 invoices at a time.')
    setFiles(combined.slice(0, 10))
  }

  function dropFile(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault()
    setDragging(false)
    addFiles(Array.from(event.dataTransfer.files))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (files.length > 0) onUpload(files)
  }

  return (
    <div className={"[position:fixed] [inset:0] [z-index:20] [display:flex] [align-items:center] [justify-content:center] [background:rgb(24_33_49_/_42%)] [padding:22px] [backdrop-filter:blur(2px)] [animation:upload-backdrop-in_220ms_ease-out_both] motion-reduce:[animation-duration:1ms] motion-reduce:[animation-delay:0ms] motion-reduce:[transition-duration:1ms] max-[680px]:[align-items:flex-end] max-[680px]:[padding:0]"} onMouseDown={(event) => { if (event.target === event.currentTarget && !isUploading) onClose() }}>
      <section className={"[width:min(100%,_510px)] [max-height:calc(100dvh_-_32px)] [overflow-y:auto] [border:1px_solid_#e8ebf0] [border-radius:14px] [background:#fff] [padding:27px] [box-shadow:0_18px_55px_rgb(16_24_40_/_20%)] [animation:upload-dialog-in_420ms_cubic-bezier(0.2,_0.75,_0.25,_1)_both] motion-reduce:[animation-duration:1ms] motion-reduce:[animation-delay:0ms] motion-reduce:[transition-duration:1ms] max-[680px]:[width:100%] max-[680px]:[border-radius:13px_13px_0_0] max-[680px]:[padding:20px_17px_max(18px,_env(safe-area-inset-bottom))]"} role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <div className={"[display:flex] [align-items:flex-start] [justify-content:space-between] [gap:12px] [margin-bottom:22px] [&_h2]:[margin:6px_0_4px] [&_h2]:[color:#202b3e] [&_h2]:[font-size:19px] [&_h2]:[font-weight:650] [&_h2]:[letter-spacing:-0.035em] [&_p]:[margin:0] [&_p]:[color:#8490a1] [&_p]:[font-size:11px]"}>
          <div>
            <span className={"[display:block] [color:#7e899a] [font-size:9px] [font-weight:720] [letter-spacing:0.13em] [color:var(--leaf)] [letter-spacing:0.1em]"}>BATCH DOCUMENT INTAKE</span>
            <h2 id="upload-title">Upload invoices</h2>
            <p>Each document is processed independently in the background.</p>
          </div>
          <button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)]"} type="button" onClick={onClose} disabled={isUploading} aria-label="Close upload dialog"><X size={19} /></button>
        </div>
        <form onSubmit={submit}>
          <label
            className={`[position:relative] [display:flex] [min-height:208px] [flex-direction:column] [align-items:center] [justify-content:center] [gap:13px] [border:1px_dashed_#cbd4e1] [border-radius:10px] [background:radial-gradient(circle_at_50%_32%,_rgb(91_125_62_/_8%),_transparent_48%),_#fbfcf8] [padding:24px] [text-align:center] [cursor:pointer] [transition:border-color_180ms_ease,_background_180ms_ease,_box-shadow_180ms_ease,_transform_180ms_ease] [animation:upload-dropzone-in_460ms_70ms_both] [&:hover]:[border-color:#819a68] [&:hover]:[background:radial-gradient(circle_at_50%_32%,_rgb(91_125_62_/_12%),_transparent_48%),_#f4f7ef] [&:hover]:[box-shadow:inset_0_0_0_1px_rgb(91_125_62_/_7%)] [&:hover]:[transform:translateY(-2px)] [&:focus-within]:[outline:3px_solid_rgb(91_125_62_/_18%)] [&:focus-within]:[outline-offset:3px] [&_input]:[position:absolute] [&_input]:[width:1px] [&_input]:[height:1px] [&_input]:[overflow:hidden] [&_input]:[clip:rect(0,_0,_0,_0)] [&_input]:[white-space:nowrap] [&_input]:[clip-path:inset(50%)] [&:hover_.dropzone-browse]:[border-color:#bfd0b4] [&:hover_.dropzone-browse]:[background:#f8faf5] motion-reduce:[animation-duration:1ms] motion-reduce:[animation-delay:0ms] motion-reduce:[transition-duration:1ms] [border-color:#c9d4c5] ${dragging ? '[border-color:#819a68] [background:radial-gradient(circle_at_50%_32%,_rgb(91_125_62_/_12%),_transparent_48%),_#f4f7ef] [box-shadow:inset_0_0_0_1px_rgb(91_125_62_/_7%)] [&_.dropzone-browse]:[border-color:#bfd0b4] [&_.dropzone-browse]:[background:#f8faf5]' : ''} ${files.length > 0 ? '[border-color:#819a68] [background:radial-gradient(circle_at_50%_32%,_rgb(91_125_62_/_12%),_transparent_48%),_#f4f7ef] [box-shadow:inset_0_0_0_1px_rgb(91_125_62_/_7%)]' : ''}`}
            onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={dropFile}
          >
            <input type="file" multiple disabled={isUploading} accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onChange={chooseFile} />
            <span className={`[display:grid] [width:48px] [height:48px] [place-items:center] [border:1px_solid_#e3e9de] [border-radius:13px] [background:#fff] [color:#55743e] [box-shadow:0_2px_5px_rgb(16_24_40_/_5%)] [animation:upload-icon-in_520ms_100ms_cubic-bezier(0.2,_0.75,_0.25,_1)_both] motion-reduce:[animation-duration:1ms] motion-reduce:[animation-delay:0ms] motion-reduce:[transition-duration:1ms] [border-color:#dce5d5] ${files.length > 0 ? '[border-color:#d7e5cd] [background:#edf4e8] [color:#4d7339]' : ''}`}>
              {files.length > 0 ? <FileCheck2 size={23} /> : <CloudUpload size={24} />}
            </span>
            <span className={"[display:grid] [max-width:100%] [gap:5px] [&_strong]:[overflow:hidden] [&_strong]:[color:#435068] [&_strong]:[font-size:12px] [&_strong]:[font-weight:620] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_>_span]:[color:#9aa3b0] [&_>_span]:[font-size:10px]"}>
              <strong>{files.length > 0 ? `${files.length} ${files.length === 1 ? 'invoice' : 'invoices'} selected` : 'Drop invoices here'}</strong>
              <span>PDF, PNG or JPG · up to 10 files · 15 MB each</span>
            </span>
            <span className={"[display:inline-flex] [min-height:29px] [align-items:center] [border:1px_solid_#dce5d5] [border-radius:6px] [background:#fff] [padding:0_11px] [color:#55743e] [font-size:10px] [font-weight:620] [transition:border-color_160ms_ease,_background_160ms_ease]"}>Browse files</span>
          </label>
          {files.length > 0 && (
            <div className={"[display:grid] [max-height:220px] [gap:5px] [overflow-y:auto] [margin-top:12px] [border:1px_solid_#e8ede3] [border-radius:8px] [background:#fcfdfa] [padding:9px]"} aria-live="polite">
              <div className={"[display:flex] [align-items:center] [justify-content:space-between] [gap:8px] [padding:1px_3px_5px] [&_strong]:[color:#647064] [&_strong]:[font-size:9px] [&_strong]:[font-weight:650]"}>
                <strong>Selected files</strong>
                <button type="button" className={"[display:inline-flex] [align-items:center] [gap:5px] [border:0] [background:transparent] [padding:4px_0] [color:#175cd3] [font-size:11px] [font-weight:620] [&:hover]:[color:#004eeb] [color:#48683c] [&:hover]:[color:#274c31]"} onClick={() => setFiles([])} disabled={isUploading}>Clear all</button>
              </div>
              {files.map((file, index) => (
                <div className={"[display:grid] [min-width:0] [grid-template-columns:16px_minmax(0,_1fr)_auto_28px] [align-items:center] [gap:8px] [border-top:1px_solid_#edf1e9] [padding:6px_2px_1px] [color:#718071] [&_>_span]:[overflow:hidden] [&_>_span]:[color:#45554a] [&_>_span]:[font-size:10px] [&_>_span]:[text-overflow:ellipsis] [&_>_span]:[white-space:nowrap] [&_small]:[color:#929e90] [&_small]:[font-size:9px] [&_.icon-button]:[width:26px] [&_.icon-button]:[height:26px]"} key={`${file.name}-${file.size}-${file.lastModified}-${index}`}>
                  <FileText size={15} />
                  <span>{file.name}</span>
                  <small>{(file.size / (1024 * 1024)).toFixed(2)} MB</small>
                  <button type="button" className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)]"} onClick={() => setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index))} disabled={isUploading} aria-label={`Remove ${file.name}`}><X size={14} /></button>
                </div>
              ))}
            </div>
          )}
          {(selectionError || error) && <div className={"[display:flex] [align-items:flex-start] [gap:7px] [margin-top:12px] [color:#bd3b3b] [font-size:11px] [line-height:1.5]"} role="alert"><CircleAlert size={16} />{selectionError || error}</div>}
          <div className={"[display:flex] [justify-content:flex-end] [gap:8px] [margin-top:18px]"}>
            <button className={"[display:inline-flex] [min-height:37px] [align-items:center] [justify-content:center] [gap:8px] [border:1px_solid_transparent] [border-radius:7px] [padding:0_13px] [font-size:12px] [font-weight:620] [transition:background_130ms_ease,_border-color_130ms_ease,_box-shadow_130ms_ease] [border-color:#e2e6ec] [background:#fff] [color:#465166] [&:hover:not(:disabled)]:[border-color:#cdd3dc] [&:hover:not(:disabled)]:[background:#f9fafb] [border-color:#d8dfd5] [background:var(--panel)] [color:#46564b] [&:hover:not(:disabled)]:[border-color:#bac8b8] [&:hover:not(:disabled)]:[background:#f2f5ee]"} type="button" onClick={onClose} disabled={isUploading}>Cancel</button>
            <button className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-[#d9ef55] bg-[#d9ef55] px-3 text-xs font-semibold text-[#18342d] shadow-sm transition-colors hover:border-[#c5dd42] hover:bg-[#c5dd42] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#9ab62f] disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={files.length === 0 || isUploading}>
              {isUploading ? <><LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={16} /> Queuing…</> : <><CloudUpload size={16} /> Upload {files.length > 0 ? `${files.length} ${files.length === 1 ? 'invoice' : 'invoices'}` : 'invoices'}</>}
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
  onReprocess,
  onDelete,
  saving,
  validating,
  reprocessing,
  deleting,
}: {
  invoice: Invoice
  onClose: () => void
  onSave: (correction: InvoiceCorrection) => void
  onValidate: () => void
  onReprocess: () => void
  onDelete: () => void
  saving: boolean
  validating: boolean
  reprocessing: boolean
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
  const hiddenWarningPatterns = [
    /Local rule-based extraction is conservative/i,
    /OCR punctuation in the date .* was corrected/i,
    /Supplier name was inferred from the document header/i,
    /Supplier address was inferred from the document header/i,
    /No separate discount or additional-charge summary was identified/i,
  ]
  const warnings = Array.from(
    new Map(
      (invoice.extraction_metadata?.warnings ?? [])
        .filter((warning) => !hiddenWarningPatterns.some((pattern) => pattern.test(warning)))
        .map((warning) => [warning, warning]),
    ).values(),
  )
  const rawJson = invoice.raw_extraction_json

  return (
    <div className={"[position:fixed] [inset:0] [z-index:20] [display:flex] [align-items:center] [justify-content:center] [background:rgb(24_33_49_/_42%)] [padding:2px] [backdrop-filter:blur(2px)] [z-index:18] [justify-content:flex-end] [padding:0] [animation:review-backdrop-enter_280ms_ease-out_both] motion-reduce:[animation-duration:1ms]"} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className={"[display:flex] [min-width:0] [width:min(100%,_1120px)] [height:100%] [flex-direction:column] [overflow:hidden] [background:#f7f8fa] [box-shadow:-15px_0_45px_rgb(16_24_40_/_14%)] [animation:review-panel-enter_380ms_cubic-bezier(0.2,_0.75,_0.25,_1)_both] motion-reduce:[animation-duration:1ms] max-[850px]:[width:100%] [background:var(--paper)]"} role="dialog" aria-modal="true" aria-labelledby="review-title">
        <header className={"[position:relative] [z-index:2] [display:flex] [min-height:73px] [align-items:center] [justify-content:space-between] [gap:15px] [border-bottom:1px_solid_#e7eaf0] [background:#fff] [padding:10px_24px] max-[680px]:[min-height:64px] max-[680px]:[padding:8px_12px]"}>
          <div className={"[display:flex] [min-width:0] [align-items:center] [gap:12px] max-[680px]:[gap:7px]"}>
            <button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)] [display:none] max-[680px]:[display:inline-grid]"} type="button" onClick={onClose} aria-label="Close invoice review"><ChevronLeft size={20} /></button>
            <span className={"[display:grid] [width:35px] [height:35px] [flex:0_0_auto] [place-items:center] [border-radius:9px] [background:#edf4ff] [color:#2764c6] max-[680px]:[display:none] [border-radius:7px] [background:#e8eee1] [color:#55743e]"}><FileText size={18} /></span>
            <div className={"[min-width:0] [&_.eyebrow]:[font-size:8px] [&_h2]:[overflow:hidden] [&_h2]:[margin:4px_0_2px] [&_h2]:[color:#273248] [&_h2]:[font-size:14px] [&_h2]:[font-weight:650] [&_h2]:[letter-spacing:-0.015em] [&_h2]:[text-overflow:ellipsis] [&_h2]:[white-space:nowrap]"}>
              <span className={"[display:block] [color:#7e899a] [font-size:9px] [font-weight:720] [letter-spacing:0.13em] [color:var(--leaf)] [letter-spacing:0.1em]"}>INVOICE REVIEW · #{invoice.id}</span>
              <h2 id="review-title">{invoice.supplier_name || invoice.original_filename}</h2>
              <span className={"[display:block] [overflow:hidden] [color:#929aaa] [font-size:9px] [text-overflow:ellipsis] [white-space:nowrap]"}>{invoice.original_filename}</span>
            </div>
          </div>
          <div className={"[display:flex] [min-width:0] [align-items:center] [gap:12px] max-[680px]:[gap:7px] max-[680px]:[&_.button]:[width:32px] max-[680px]:[&_.button]:[min-height:32px] max-[680px]:[&_.button]:[overflow:hidden] max-[680px]:[&_.button]:[gap:16px] max-[680px]:[&_.button]:[padding:0_8px] max-[680px]:[&_.button]:[font-size:0]"}>
            <button className="button inline-flex min-h-8 items-center justify-center gap-2 rounded-md border border-[#d9ef55] bg-[#d9ef55] px-2.5 text-[11px] font-semibold text-[#18342d] transition-colors hover:border-[#c5dd42] hover:bg-[#c5dd42] disabled:cursor-not-allowed disabled:opacity-60" type="button" onClick={onReprocess} disabled={reprocessing} title="Re-extract the full document and replace current extracted values">
              {reprocessing ? <LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={14} /> : <RefreshCw size={14} />}
              {reprocessing ? 'Re-reading…' : 'Re-extract'}
            </button>
            <a className={"[display:inline-flex] [min-height:37px] [align-items:center] [justify-content:center] [gap:8px] [border:1px_solid_transparent] [border-radius:7px] [padding:0_13px] [font-size:12px] [font-weight:620] [transition:background_130ms_ease,_border-color_130ms_ease,_box-shadow_130ms_ease] [border-color:#e2e6ec] [background:#fff] [color:#465166] [&:hover:not(:disabled)]:[border-color:#cdd3dc] [&:hover:not(:disabled)]:[background:#f9fafb] [border-color:#d8dfd5] [background:var(--panel)] [color:#46564b] [&:hover:not(:disabled)]:[border-color:#bac8b8] [&:hover:not(:disabled)]:[background:#f2f5ee] [min-height:32px] [padding:0_10px] [font-size:11px]"} href={getInvoiceExportUrl(invoice.id)} download><Download size={15} /> Export JSON</a>
            <button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)]"} type="button" onClick={onClose} aria-label="Close"><X size={19} /></button>
          </div>
        </header>

        <div className={"[display:grid] [min-width:0] [min-height:0] [flex:1] [grid-template-columns:minmax(0,_1fr)_minmax(270px,_37%)] [gap:17px] [overflow:auto] [padding:20px_22px_26px] max-[1150px]:[grid-template-columns:minmax(0,_1fr)_minmax(230px,_34%)] max-[1150px]:[padding-right:16px] max-[1150px]:[padding-left:16px] max-[850px]:[grid-template-columns:minmax(0,_1fr)] min-[851px]:max-[1000px]:[grid-template-columns:minmax(0,_1fr)] max-[680px]:[display:flex] max-[680px]:[flex-direction:column] max-[680px]:[gap:12px] max-[680px]:[overflow-y:auto] max-[680px]:[padding:12px]"}>
          <div className={"[display:grid] [min-width:0] [align-content:start] [gap:13px] max-[680px]:[display:contents]"}>
            {invoice.processing_error && (
              <div className={"[display:flex] [align-items:flex-start] [gap:10px] [border:1px_solid_#efcdcc] [border-radius:8px] [background:#fff5f4] [padding:11px_13px] [color:#c14444] [&_>_div]:[display:grid] [&_>_div]:[gap:4px] [&_strong]:[color:#873d3e] [&_strong]:[font-size:10px] [&_strong]:[font-weight:640] [&_span]:[color:#9e5e5e] [&_span]:[font-size:9px] [&_span]:[line-height:1.5] max-[680px]:[order:-1]"}><ShieldAlert size={18} /><div><strong>Extraction needs attention</strong><span>{invoice.processing_error}</span></div></div>
            )}
            {warnings.map((warning) => (
              <div className={"[display:flex] [align-items:flex-start] [gap:10px] [border:1px_solid_#efcdcc] [border-radius:8px] [background:#fff5f4] [padding:11px_13px] [color:#c14444] [&_>_div]:[display:grid] [&_>_div]:[gap:4px] [&_strong]:[color:#873d3e] [&_strong]:[font-size:10px] [&_strong]:[font-weight:640] [&_span]:[color:#9e5e5e] [&_span]:[font-size:9px] [&_span]:[line-height:1.5] max-[680px]:[order:-1] [border-color:#f1e0bb] [background:#fffaf0] [color:#ad741c] [&_strong]:[color:#805c20] [&_span]:[color:#8d7449]"} key={warning}><CircleAlert size={18} /><div><strong>Processing note</strong><span>{warning}</span></div></div>
            ))}

            <section className={"[min-width:0] [border:1px_solid_#e8ebf0] [border-radius:9px] [background:#fff] [padding:17px] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] max-[680px]:[order:1] max-[680px]:[padding:13px]"}>
              <div className={"[display:flex] [align-items:flex-start] [justify-content:space-between] [gap:12px] [margin-bottom:16px] [&_h3]:[margin:0] [&_h3]:[color:#2a354a] [&_h3]:[font-size:12px] [&_h3]:[font-weight:660] [&_p]:[margin:4px_0_0] [&_p]:[color:#939cac] [&_p]:[font-size:9px] [&_p]:[line-height:1.5]"}>
                <div><h3>Extracted details</h3><p>Review and correct any fields before saving.</p></div>
                <StatusBadge status={invoice.validation_status} />
              </div>
              <form onSubmit={save}>
                <div className={"[display:grid] [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:11px_12px] max-[680px]:[gap:9px] max-[390px]:[grid-template-columns:1fr]"}>
                  {scalarFields.map((field) => (
                    <label className={`[display:grid] [min-width:0] [gap:5px] [color:#667286] [font-size:9px] [font-weight:580] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[height:33px] [&_input]:[border:1px_solid_#e1e6ed] [&_input]:[border-radius:6px] [&_input]:[outline:none] [&_input]:[background:#fff] [&_input]:[padding:0_9px] [&_input]:[color:#354156] [&_input]:[font-size:10px] [&_input]:[font-weight:450] [&_input]:[transition:border-color_120ms_ease,_box-shadow_120ms_ease] [&_input:focus]:[border-color:#73a0ec] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(46_112_218_/_10%)] [&_input:focus]:[border-color:#819a68] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(91_125_62_/_10%)] ${field.wide ? '[grid-column:1_/_-1] max-[390px]:[grid-column:auto]' : ''}`} key={field.name}>
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

                <div className={"[&_h3]:[margin:0] [&_h3]:[color:#2a354a] [&_h3]:[font-size:12px] [&_h3]:[font-weight:660] [&_p]:[margin:4px_0_0] [&_p]:[color:#939cac] [&_p]:[font-size:9px] [&_p]:[line-height:1.5] [display:flex] [align-items:center] [justify-content:space-between] [gap:10px] [margin:21px_0_10px]"}>
                  <div><h3>Line items</h3><p>Update item details to recalculate validation.</p></div>
                  <button className={"[display:inline-flex] [min-height:37px] [align-items:center] [justify-content:center] [gap:8px] [border:1px_solid_transparent] [border-radius:7px] [padding:0_13px] [font-size:12px] [font-weight:620] [transition:background_130ms_ease,_border-color_130ms_ease,_box-shadow_130ms_ease] [border-color:#e2e6ec] [background:#fff] [color:#465166] [&:hover:not(:disabled)]:[border-color:#cdd3dc] [&:hover:not(:disabled)]:[background:#f9fafb] [border-color:#d8dfd5] [background:var(--panel)] [color:#46564b] [&:hover:not(:disabled)]:[border-color:#bac8b8] [&:hover:not(:disabled)]:[background:#f2f5ee] [min-height:32px] [padding:0_10px] [font-size:11px]"} type="button" onClick={() => { setItems((current) => [...current, emptyDraft()]); setItemsDirty(true) }}><Plus size={15} /> Add item</button>
                </div>
                <div className={"[display:grid] [gap:9px] [overflow-x:auto]"}>
                  {items.length === 0 && <p className={"[color:#939cac] [font-size:9px] [line-height:1.5]"}>No line items extracted. Add one if needed.</p>}
                  {items.map((item, index) => (
                    <div className={"[display:grid] [min-width:650px] [grid-template-columns:minmax(100px,_1.8fr)_minmax(50px,_0.6fr)_minmax(60px,_0.7fr)_minmax(75px,_0.9fr)_minmax(75px,_0.9fr)_minmax(55px,_0.6fr)_27px] [align-items:end] [gap:7px] [border:1px_solid_#edf0f3] [border-radius:7px] [background:#fcfcfd] [padding:9px] [&_.field-source]:[grid-column:1_/_-1]"} key={`item-${index}`}>
                      <label className={"[display:grid] [min-width:0] [gap:5px] [color:#667286] [font-size:9px] [font-weight:580] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[height:33px] [&_input]:[border:1px_solid_#e1e6ed] [&_input]:[border-radius:6px] [&_input]:[outline:none] [&_input]:[background:#fff] [&_input]:[padding:0_9px] [&_input]:[color:#354156] [&_input]:[font-size:10px] [&_input]:[font-weight:450] [&_input]:[transition:border-color_120ms_ease,_box-shadow_120ms_ease] [&_input:focus]:[border-color:#73a0ec] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(46_112_218_/_10%)] [&_input:focus]:[border-color:#819a68] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(91_125_62_/_10%)] item-description"}><span>Description</span><input value={item.description} onChange={(event) => updateItem(index, 'description', event.target.value)} /></label>
                      <label className={"[display:grid] [min-width:0] [gap:5px] [color:#667286] [font-size:9px] [font-weight:580] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[height:33px] [&_input]:[border:1px_solid_#e1e6ed] [&_input]:[border-radius:6px] [&_input]:[outline:none] [&_input]:[background:#fff] [&_input]:[padding:0_9px] [&_input]:[color:#354156] [&_input]:[font-size:10px] [&_input]:[font-weight:450] [&_input]:[transition:border-color_120ms_ease,_box-shadow_120ms_ease] [&_input:focus]:[border-color:#73a0ec] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(46_112_218_/_10%)] [&_input:focus]:[border-color:#819a68] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(91_125_62_/_10%)]"}><span>Qty</span><input type="number" min="0" step="any" value={item.quantity} onChange={(event) => updateItem(index, 'quantity', event.target.value)} /></label>
                      <label className={"[display:grid] [min-width:0] [gap:5px] [color:#667286] [font-size:9px] [font-weight:580] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[height:33px] [&_input]:[border:1px_solid_#e1e6ed] [&_input]:[border-radius:6px] [&_input]:[outline:none] [&_input]:[background:#fff] [&_input]:[padding:0_9px] [&_input]:[color:#354156] [&_input]:[font-size:10px] [&_input]:[font-weight:450] [&_input]:[transition:border-color_120ms_ease,_box-shadow_120ms_ease] [&_input:focus]:[border-color:#73a0ec] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(46_112_218_/_10%)] [&_input:focus]:[border-color:#819a68] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(91_125_62_/_10%)]"}><span>Unit</span><input value={item.unit} onChange={(event) => updateItem(index, 'unit', event.target.value)} /></label>
                      <label className={"[display:grid] [min-width:0] [gap:5px] [color:#667286] [font-size:9px] [font-weight:580] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[height:33px] [&_input]:[border:1px_solid_#e1e6ed] [&_input]:[border-radius:6px] [&_input]:[outline:none] [&_input]:[background:#fff] [&_input]:[padding:0_9px] [&_input]:[color:#354156] [&_input]:[font-size:10px] [&_input]:[font-weight:450] [&_input]:[transition:border-color_120ms_ease,_box-shadow_120ms_ease] [&_input:focus]:[border-color:#73a0ec] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(46_112_218_/_10%)] [&_input:focus]:[border-color:#819a68] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(91_125_62_/_10%)]"}><span>Unit price</span><input type="number" min="0" step="any" value={item.unit_price} onChange={(event) => updateItem(index, 'unit_price', event.target.value)} /></label>
                      <label className={"[display:grid] [min-width:0] [gap:5px] [color:#667286] [font-size:9px] [font-weight:580] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[height:33px] [&_input]:[border:1px_solid_#e1e6ed] [&_input]:[border-radius:6px] [&_input]:[outline:none] [&_input]:[background:#fff] [&_input]:[padding:0_9px] [&_input]:[color:#354156] [&_input]:[font-size:10px] [&_input]:[font-weight:450] [&_input]:[transition:border-color_120ms_ease,_box-shadow_120ms_ease] [&_input:focus]:[border-color:#73a0ec] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(46_112_218_/_10%)] [&_input:focus]:[border-color:#819a68] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(91_125_62_/_10%)]"}><span>Line total</span><input type="number" min="0" step="any" value={item.line_total} onChange={(event) => updateItem(index, 'line_total', event.target.value)} /></label>
                      <label className={"[display:grid] [min-width:0] [gap:5px] [color:#667286] [font-size:9px] [font-weight:580] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[height:33px] [&_input]:[border:1px_solid_#e1e6ed] [&_input]:[border-radius:6px] [&_input]:[outline:none] [&_input]:[background:#fff] [&_input]:[padding:0_9px] [&_input]:[color:#354156] [&_input]:[font-size:10px] [&_input]:[font-weight:450] [&_input]:[transition:border-color_120ms_ease,_box-shadow_120ms_ease] [&_input:focus]:[border-color:#73a0ec] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(46_112_218_/_10%)] [&_input:focus]:[border-color:#819a68] [&_input:focus]:[box-shadow:0_0_0_3px_rgb(91_125_62_/_10%)]"}><span>Currency</span><input maxLength={3} value={item.currency} onChange={(event) => updateItem(index, 'currency', event.target.value)} /></label>
                      <button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)] [width:27px] [height:31px] [color:#a2aab6] [&:hover:not(:disabled)]:[border-color:#f1cdcd] [&:hover:not(:disabled)]:[background:#fff4f4] [&:hover:not(:disabled)]:[color:#bd3b3b]"} type="button" aria-label={`Remove item ${index + 1}`} onClick={() => { setItems((current) => current.filter((_, itemIndex) => itemIndex !== index)); setItemsDirty(true) }}><Trash2 size={15} /></button>
                      {invoice.items[index] && <FieldSource evidence={invoice.items[index].source_evidence?.line_total} />}
                    </div>
                  ))}
                </div>
                <div className={"[display:flex] [align-items:center] [justify-content:space-between] [gap:10px] [margin-top:15px] [border-top:1px_solid_#eff1f4] [padding-top:13px] max-[680px]:[align-items:flex-end] max-[680px]:[&_.muted-copy]:[max-width:130px]"}>
                  <span className={"[color:#939cac] [font-size:9px] [line-height:1.5]"}>Changes recalculate financial checks.</span>
                  <button className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-[#d9ef55] bg-[#d9ef55] px-3 text-xs font-semibold text-[#18342d] shadow-sm transition-colors hover:border-[#c5dd42] hover:bg-[#c5dd42] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#9ab62f] disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={saving || (dirtyFields.size === 0 && !itemsDirty)}>
                    {saving ? <><LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={16} /> Saving…</> : <><Check size={16} /> Save corrections</>}
                  </button>
                </div>
              </form>
            </section>

            <section className={"[min-width:0] [border:1px_solid_#e8ebf0] [border-radius:9px] [background:#fff] [padding:17px] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] max-[680px]:[order:1] max-[680px]:[padding:13px] validation-card"}>
              <div className={"[display:flex] [align-items:flex-start] [justify-content:space-between] [gap:12px] [margin-bottom:16px] [&_h3]:[margin:0] [&_h3]:[color:#2a354a] [&_h3]:[font-size:12px] [&_h3]:[font-weight:660] [&_p]:[margin:4px_0_0] [&_p]:[color:#939cac] [&_p]:[font-size:9px] [&_p]:[line-height:1.5]"}>
                <div><h3>Validation checks</h3><p>Deterministic checks for invoice amounts and required data.</p></div>
                <button className={"[display:inline-flex] [min-height:37px] [align-items:center] [justify-content:center] [gap:8px] [border:1px_solid_transparent] [border-radius:7px] [padding:0_13px] [font-size:12px] [font-weight:620] [transition:background_130ms_ease,_border-color_130ms_ease,_box-shadow_130ms_ease] [border-color:#e2e6ec] [background:#fff] [color:#465166] [&:hover:not(:disabled)]:[border-color:#cdd3dc] [&:hover:not(:disabled)]:[background:#f9fafb] [border-color:#d8dfd5] [background:var(--panel)] [color:#46564b] [&:hover:not(:disabled)]:[border-color:#bac8b8] [&:hover:not(:disabled)]:[background:#f2f5ee] [min-height:32px] [padding:0_10px] [font-size:11px]"} type="button" onClick={onValidate} disabled={validating}>
                  {validating ? <LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={15} /> : <RefreshCw size={15} />}
                  Re-run checks
                </button>
              </div>
              {checks.length > 0 ? (
                <div className={"[display:grid] [gap:0]"}>
                  {checks.map((check) => (
                    <div className={"[display:flex] [min-height:52px] [align-items:center] [gap:10px] [border-top:1px_solid_#f0f2f5] [padding:7px_0] [&:first-child]:[border-top:0]"} key={`${check.check_name}-${check.message}`}>
                      <span className={"[display:grid] [width:26px] [height:26px] [flex:0_0_auto] [place-items:center] [border-radius:50%]" + ' ' + (check.status === 'PASSED' ? "[background:#ebf8f1] [color:#168657]" : check.status === 'FAILED' ? "[background:#fff0ef] [color:#d04444]" : check.status === 'WARNING' ? "[background:#fff6e5] [color:#b7791f]" : "[background:#f1f3f6] [color:#7c8798]")}>
                        {check.status === 'PASSED' ? <CircleCheck size={17} /> : check.status === 'FAILED' ? <CircleAlert size={17} /> : <Clock3 size={17} />}
                      </span>
                      <div className={"[display:grid] [flex:1] [gap:3px] [&_strong]:[color:#455166] [&_strong]:[font-size:10px] [&_strong]:[font-weight:620] [&_strong]:[text-transform:capitalize] [&_span]:[color:#929aaa] [&_span]:[font-size:9px] [&_span]:[line-height:1.45]"}><strong>{check.check_name.replaceAll('_', ' ')}</strong><span>{check.message}</span></div>
                      <StatusBadge status={check.status} />
                    </div>
                  ))}
                </div>
              ) : (
                <div className={"[display:flex] [align-items:center] [gap:8px] [border-top:1px_solid_#f0f2f5] [padding-top:14px] [color:#8490a1] [font-size:10px]"}><Clock3 size={17} /><span>No validation results yet. Run checks to review this invoice.</span></div>
              )}
            </section>

            {ocrLines.length > 0 && (
              <details className={"[min-width:0] [border:1px_solid_#e8ebf0] [border-radius:9px] [background:#fff] [padding:17px] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] max-[680px]:[order:1] max-[680px]:[padding:13px] [padding:0] [&_summary]:[display:flex] [&_summary]:[min-height:48px] [&_summary]:[align-items:center] [&_summary]:[justify-content:space-between] [&_summary]:[gap:10px] [&_summary]:[cursor:pointer] [&_summary]:[list-style:none] [&_summary]:[padding:0_16px] [&_summary]:[color:#667286] [&_summary]:[font-size:10px] [&_summary::-webkit-details-marker]:[display:none] [&_summary_>_span:first-child]:[display:flex] [&_summary_>_span:first-child]:[align-items:center] [&_summary_>_span:first-child]:[gap:8px] [&_summary_>_span:first-child]:[color:#3b4960] [&_summary_>_span:first-child]:[font-weight:620] [&_summary_>_span:last-child]:[color:#98a1af] [&_summary_>_span:last-child]:[font-size:9px]"}>
                <summary><span><Eye size={17} /> OCR source evidence</span><span>{ocrLines.length} text lines</span></summary>
                <div className={"[display:grid] [max-height:260px] [overflow-y:auto] [border-top:1px_solid_#eff1f4] [padding:4px_16px]"}>
                  {ocrLines.map((line, index) => (
                    <div className={"[display:flex] [align-items:baseline] [justify-content:space-between] [gap:12px] [border-bottom:1px_solid_#f2f3f5] [padding:7px_0] [color:#596579] [font-size:9px] [&:last-child]:[border-bottom:0] [&_small]:[flex:0_0_auto] [&_small]:[color:#a0a8b5] [&_small]:[font-size:8px]"} key={`${line.page_number}-${index}`}>
                      <span>{line.text}</span>
                      <small>Page {line.page_number}{line.confidence != null ? ` · ${Math.round(line.confidence * 100)}%` : ''}</small>
                    </div>
                  ))}
                </div>
              </details>
            )}

            {rawJson && (
              <details className={"[min-width:0] [border:1px_solid_#e8ebf0] [border-radius:9px] [background:#fff] [padding:17px] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] max-[680px]:[order:1] max-[680px]:[padding:13px] [padding:0] [&_summary]:[display:flex] [&_summary]:[min-height:48px] [&_summary]:[align-items:center] [&_summary]:[justify-content:space-between] [&_summary]:[gap:10px] [&_summary]:[cursor:pointer] [&_summary]:[list-style:none] [&_summary]:[padding:0_16px] [&_summary]:[color:#667286] [&_summary]:[font-size:10px] [&_summary::-webkit-details-marker]:[display:none] [&_summary_>_span:first-child]:[display:flex] [&_summary_>_span:first-child]:[align-items:center] [&_summary_>_span:first-child]:[gap:8px] [&_summary_>_span:first-child]:[color:#3b4960] [&_summary_>_span:first-child]:[font-weight:620] [&_summary_>_span:last-child]:[color:#98a1af] [&_summary_>_span:last-child]:[font-size:9px] [&_pre]:[margin:0] [&_pre]:[max-height:260px] [&_pre]:[overflow:auto] [&_pre]:[border-top:1px_solid_#eff1f4] [&_pre]:[background:#f8fafc] [&_pre]:[padding:12px_16px] [&_pre]:[color:#32435d] [&_pre]:[font-family:\"SFMono-Regular\",_Consolas,_\"Liberation_Mono\",_Menlo,_monospace] [&_pre]:[font-size:8px] [&_pre]:[line-height:1.6] [&_pre]:[white-space:pre-wrap] [&_pre]:[word-break:break-word]"}>
                <summary><span><FileText size={17} /> Raw JSON</span><span>Extraction payload</span></summary>
                <pre>{JSON.stringify(rawJson, null, 2)}</pre>
              </details>
            )}

            <div className={"[display:flex] [align-items:center] [justify-content:space-between] [gap:12px] [border:1px_solid_#f0dddd] [border-radius:8px] [background:#fffafa] [padding:12px] [&_div]:[display:grid] [&_div]:[gap:4px] [&_strong]:[color:#804347] [&_strong]:[font-size:10px] [&_strong]:[font-weight:620] [&_span]:[color:#a2787a] [&_span]:[font-size:9px] max-[680px]:[order:4]"}>
              <div><strong>Delete this invoice</strong><span>Remove the invoice record and its stored document.</span></div>
              <button className={"[display:inline-flex] [min-height:37px] [align-items:center] [justify-content:center] [gap:8px] [border:1px_solid_transparent] [border-radius:7px] [padding:0_13px] [font-size:12px] [font-weight:620] [transition:background_130ms_ease,_border-color_130ms_ease,_box-shadow_130ms_ease] [border-color:#f3c6c7] [background:#fff] [color:#c43236] [&:hover:not(:disabled)]:[background:#fff4f4] [min-height:32px] [padding:0_10px] [font-size:11px]"} type="button" onClick={onDelete} disabled={deleting}>
                {deleting ? <LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={15} /> : <Trash2 size={15} />} Delete
              </button>
            </div>
          </div>

          <aside className={"[min-width:0] max-[680px]:[order:0]"}>
            <div className={"[position:sticky] [top:0] [overflow:hidden] [border:1px_solid_#e5e9ef] [border-radius:9px] [background:#fff] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] max-[850px]:[position:static] min-[851px]:max-[1000px]:[position:static] max-[680px]:[position:static]"}>
              <div className={"[display:flex] [height:43px] [align-items:center] [justify-content:space-between] [border-bottom:1px_solid_#edf0f3] [padding:0_13px] [color:#576378] [font-size:10px] [font-weight:620] [&_span]:[display:flex] [&_span]:[align-items:center] [&_span]:[gap:7px] [&_a]:[display:grid] [&_a]:[width:27px] [&_a]:[height:27px] [&_a]:[place-items:center] [&_a]:[border-radius:6px] [&_a]:[color:#778397] [&_a:hover]:[background:#f4f6f8]"}><span><Eye size={16} /> Original document</span><a href={getInvoiceDocumentUrl(invoice.id)} target="_blank" rel="noreferrer" aria-label="Open document in a new tab"><ExternalLink size={15} /></a></div>
              <div className={"[display:grid] [min-height:370px] [max-height:min(70vh,_760px)] [place-items:center] [overflow:auto] [background:linear-gradient(45deg,_#f3f5f8_25%,_transparent_25%),_linear-gradient(-45deg,_#f3f5f8_25%,_transparent_25%),_linear-gradient(45deg,_transparent_75%,_#f3f5f8_75%),_linear-gradient(-45deg,_transparent_75%,_#f3f5f8_75%)] [background-color:#f9fafb] [background-position:0_0,_0_6px,_6px_-6px,_-6px_0] [background-size:12px_12px] [&_iframe]:[width:100%] [&_iframe]:[height:min(70vh,_760px)] [&_iframe]:[min-height:470px] [&_iframe]:[border:0] [&_iframe]:[background:#fff] [&_img]:[display:block] [&_img]:[width:100%] [&_img]:[height:auto] [&_img]:[object-fit:contain] max-[850px]:[min-height:240px] max-[850px]:[max-height:360px] max-[850px]:[&_iframe]:[height:360px] max-[850px]:[&_iframe]:[min-height:360px] max-[850px]:[&_img]:[max-height:360px] min-[851px]:max-[1000px]:[min-height:240px] min-[851px]:max-[1000px]:[max-height:360px] min-[851px]:max-[1000px]:[&_iframe]:[height:360px] min-[851px]:max-[1000px]:[&_iframe]:[min-height:360px] min-[851px]:max-[1000px]:[&_img]:[max-height:360px] max-[680px]:[min-height:180px] max-[680px]:[max-height:250px] max-[680px]:[&_iframe]:[height:230px] max-[680px]:[&_iframe]:[min-height:230px] max-[680px]:[&_img]:[max-height:250px]"}>
                {previewIsImage ? (
                  <img src={getInvoiceDocumentUrl(invoice.id)} alt={`Preview of ${invoice.original_filename}`} />
                ) : (
                  <iframe src={getInvoiceDocumentUrl(invoice.id)} title={`Preview of ${invoice.original_filename}`} />
                )}
              </div>
              <div className={"[display:grid] [gap:4px] [border-top:1px_solid_#edf0f3] [padding:10px_13px] [&_span]:[overflow:hidden] [&_span]:[color:#596579] [&_span]:[font-size:9px] [&_span]:[font-weight:560] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:[color:#9ba4b1] [&_small]:[font-size:8px] [&_small]:[text-transform:capitalize]"}>
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
    <article className={"[border:1px_solid_#e8ebf0] [border-radius:10px] [background:#fff] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] [min-height:126px] [padding:16px_17px_14px] max-[680px]:[min-height:111px] max-[680px]:[padding:12px] [border:0] [border-radius:0] [background:transparent] [box-shadow:none] [min-height:132px] [padding:18px_17px_16px] [&_+_.metric-card]:[border-left:1px_solid_#d5ddd2] max-[1150px]:[padding-right:14px] max-[1150px]:[padding-left:14px] max-[680px]:[min-height:112px] max-[680px]:[padding:13px_10px] max-[680px]:[&_+_.metric-card]:[border-left:0] max-[680px]:[&:nth-child(even)]:[border-left:1px_solid_#d5ddd2] max-[680px]:[&:nth-child(n_+_3)]:[border-top:1px_solid_#d5ddd2]"}>
      <div className={"[display:flex] [align-items:center] [justify-content:space-between] [color:#687386] [font-size:11px] [font-weight:540] max-[680px]:[font-size:9px] [color:#66736a] [font-size:10px] [font-weight:600]"}><span>{label}</span><span className={"[display:grid] [width:29px] [height:29px] [place-items:center] [border-radius:8px] max-[680px]:[width:25px] max-[680px]:[height:25px] [width:28px] [height:28px] [border-radius:6px]" + ' ' + (tone === 'blue' ? "[background:#edf4ff] [color:#2264d1] [background:#e6eee0] [color:#45683b]" : tone === 'green' ? "[background:#eaf8f1] [color:#138557] [background:#e6eee0] [color:#45683b]" : tone === 'amber' ? "[background:#fff6e5] [color:#b7791f] [background:#f4edcf] [color:#8b6a23]" : "[background:#fff0ef] [color:#d04444] [background:#f6e5de] [color:#a34a37]")}><Icon size={18} /></span></div>
      <strong className={"[display:block] [margin-top:12px] [color:#1b2638] [font-size:25px] [font-weight:640] [letter-spacing:-0.045em] [line-height:1.1] max-[680px]:[margin-top:10px] max-[680px]:[font-size:22px] [margin-top:13px] [color:var(--forest)] [font-family:Georgia,_\"Times_New_Roman\",_serif] [font-size:31px] [font-weight:500] [letter-spacing:0] max-[680px]:[font-size:28px]"}>{value}</strong>
      <span className={"[display:block] [margin-top:6px] [color:#929aaa] [font-size:10px] max-[680px]:[font-size:9px] [color:#89938b] [font-size:9px]"}>{note}</span>
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
    { label: 'Passed', count: distribution.passed, color: "[background:#19a974] [background:#638843]" },
    { label: 'Needs review', count: distribution.failed, color: "[background:#e05b5b] [background:#c86650]" },
    { label: 'Warnings', count: distribution.warning, color: "[background:#e6a23c] [background:#c5a13c]" },
    { label: 'Not checked', count: distribution.not_checked, color: "[background:#98a2b3] [background:#a2aaa0]" },
  ]

  return (
    <>
      <div className={"[display:flex] [align-items:flex-end] [justify-content:space-between] [gap:20px] [margin-bottom:26px] [&_h1]:[margin:7px_0_4px] [&_h1]:[color:#192437] [&_h1]:[font-size:clamp(24px,_2.2vw,_29px)] [&_h1]:[font-weight:650] [&_h1]:[letter-spacing:-0.045em] [&_h1]:[line-height:1.2] [&_p]:[margin:0] [&_p]:[color:#7c8798] [&_p]:[font-size:13px] max-[680px]:[align-items:flex-start] max-[680px]:[&_.button]:[min-height:34px] max-[680px]:[&_.button]:[flex:0_0_auto] max-[680px]:[&_.button]:[padding:0_9px] max-[680px]:[&_.button]:[font-size:10px] max-[680px]:[&_h1]:[font-size:24px] max-[680px]:[&_p]:[max-width:240px] max-[680px]:[&_p]:[font-size:11px] max-[680px]:[&_p]:[line-height:1.5] [margin-bottom:28px] [border-bottom:1px_solid_#ccd5c9] [padding-bottom:23px] [&_h1]:[margin-top:9px] [&_h1]:[color:var(--forest)] [&_h1]:[font-family:Georgia,_\"Times_New_Roman\",_serif] [&_h1]:[font-size:38px] [&_h1]:[font-weight:500] [&_h1]:[letter-spacing:0] [&_h1]:[line-height:1.08] [&_p]:[color:#6f7a72] [animation:rise-in_420ms_ease-out_both] max-[680px]:[padding-bottom:18px] max-[680px]:[&_h1]:[font-size:31px]"}>
        <div><span className={"[display:block] [color:#7e899a] [font-size:9px] [font-weight:720] [letter-spacing:0.13em] [color:var(--leaf)] [letter-spacing:0.1em]"}>WORKSPACE OVERVIEW</span><h1>Your invoice desk.</h1><p>Every document, extraction, and check in one place.</p></div>
        <button className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border  bg-[#D8EF54] px-3 text-xs font-semibold text-BLACK shadow-sm transition-colors hover:border-[#254a35] hover:bg-[#254a35] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#315b43] disabled:cursor-not-allowed disabled:opacity-60" type="button" onClick={onUpload}><Plus size={17} /> Upload invoice</button>
      </div>
      <div className={"[display:grid] [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:14px] [margin-bottom:19px] max-[1150px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] max-[680px]:[gap:9px] [gap:0] [margin-bottom:28px] [border-top:1px_solid_#cbd5ca] [border-bottom:1px_solid_#cbd5ca] [animation:rise-in_420ms_ease-out_both] [animation-delay:50ms] max-[680px]:[border-bottom:0]"}>
        <MetricCard label="Total invoices" value={displayCount(stats.total_invoices)} note="Invoices in your workspace" icon={FileText} tone="blue" />
        <MetricCard label="Successfully validated" value={displayCount(stats.successfully_validated)} note={`${stats.total_invoices ? Math.round(stats.successfully_validated / stats.total_invoices * 100) : 0}% of all invoices`} icon={BadgeCheck} tone="green" />
        <MetricCard label="Needs review" value={displayCount(stats.needs_review)} note="Errors or incomplete checks" icon={ShieldAlert} tone="amber" />
        <MetricCard label="Processing issues" value={displayCount(stats.failed_processing)} note="Extraction could not finish" icon={CircleAlert} tone="red" />
      </div>

      <div className={"[display:grid] [grid-template-columns:minmax(0,_1.8fr)_minmax(260px,_1fr)] [align-items:start] [gap:17px] max-[1150px]:[grid-template-columns:minmax(0,_1.5fr)_minmax(230px,_1fr)] max-[680px]:[grid-template-columns:1fr] [grid-template-columns:minmax(0,_1.75fr)_minmax(260px,_0.9fr)] [gap:30px] [animation:rise-in_420ms_ease-out_both] [animation-delay:100ms] max-[680px]:[gap:22px]"}>
        <section className={"[border:1px_solid_#e8ebf0] [border-radius:10px] [background:#fff] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] [overflow:hidden] [border:0] [border-radius:0] [background:transparent] [box-shadow:none] [border-top:2px_solid_var(--forest)] max-[680px]:[order:0] max-[680px]:[&_.invoice-table]:[min-width:610px] max-[680px]:[border-top-width:2px]"}>
          <div className={"[display:flex] [min-height:74px] [align-items:center] [justify-content:space-between] [gap:12px] [padding:15px_19px_13px] [&_h2]:[margin:0] [&_h2]:[color:#263247] [&_h2]:[font-size:13px] [&_h2]:[font-weight:650] [&_h2]:[letter-spacing:-0.01em] [&_p]:[margin:5px_0_0] [&_p]:[color:#929aaa] [&_p]:[font-size:10px] [min-height:75px] [padding-right:15px] [padding-left:15px] [&_h2]:[color:var(--forest)] [&_h2]:[font-size:14px] [&_p]:[color:#818c83]"}><div><h2>Recent invoices</h2><p>Your latest processed documents</p></div><button className={"[display:inline-flex] [align-items:center] [gap:5px] [border:0] [background:transparent] [padding:4px_0] [color:#175cd3] [font-size:11px] [font-weight:620] [&:hover]:[color:#004eeb] [color:#48683c] [&:hover]:[color:#274c31]"} type="button" onClick={onViewAll}>View all <ArrowUpRight size={15} /></button></div>
          <InvoiceTable invoices={stats.recent_invoices} onOpen={onOpen} compact />
        </section>

        <section className={"[border:1px_solid_#e8ebf0] [border-radius:10px] [background:#fff] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] [overflow:hidden] [border:0] [border-radius:0] [background:transparent] [box-shadow:none] [border-top:2px_solid_var(--forest)] max-[680px]:[order:1] max-[680px]:[border-top-width:2px]"}>
          <div className={"[display:flex] [min-height:74px] [align-items:center] [justify-content:space-between] [gap:12px] [padding:15px_19px_13px] [&_h2]:[margin:0] [&_h2]:[color:#263247] [&_h2]:[font-size:13px] [&_h2]:[font-weight:650] [&_h2]:[letter-spacing:-0.01em] [&_p]:[margin:5px_0_0] [&_p]:[color:#929aaa] [&_p]:[font-size:10px] [min-height:75px] [padding-right:15px] [padding-left:15px] [&_h2]:[color:var(--forest)] [&_h2]:[font-size:14px] [&_p]:[color:#818c83]"}><div><h2>Validation overview</h2><p>Invoice checks at a glance</p></div><span className={"[display:grid] [width:29px] [height:29px] [place-items:center] [border-radius:8px] [background:#f1f5fb] [color:#617493] [border-radius:6px] [background:#e8eee1] [color:#4b6a3d]"}><BarChart3 size={17} /></span></div>
          <div className={"[display:flex] [align-items:baseline] [gap:7px] [padding:0_19px_12px] [&_strong]:[color:#263247] [&_strong]:[font-size:22px] [&_strong]:[font-weight:650] [&_strong]:[letter-spacing:-0.04em] [&_span]:[color:#919aaa] [&_span]:[font-size:10px] [&_strong]:[color:var(--forest)] [&_span]:[color:var(--forest)] [&_strong]:[font-family:Georgia,_\"Times_New_Roman\",_serif] [&_strong]:[font-weight:500]"}><strong>{displayCount(stats.total_invoices)}</strong><span>total invoices</span></div>
          <div className={"[display:grid] [gap:10px] [padding:0_19px_15px] [gap:12px]"}>
            {statusBars.map((bar) => (
              <div key={bar.label}>
                <div className={"[display:flex] [justify-content:space-between] [margin-bottom:5px] [color:#748093] [font-size:10px] [&_strong]:[color:#475368] [&_strong]:[font-size:10px] [&_strong]:[font-weight:620] [color:#66736a]"}><span>{bar.label}</span><strong>{bar.count}</strong></div>
                <div className={"[height:5px] [overflow:hidden] [border-radius:99px] [background:#f0f2f5] [&_span]:[display:block] [&_span]:[height:100%] [&_span]:[min-width:0] [&_span]:[border-radius:inherit] [background:#e8ece4]"}><span className={bar.color} style={{ width: `${bar.count / distributionTotal * 100}%` }} /></div>
              </div>
            ))}
          </div>
          <div className={"[border-top:1px_solid_#edf0f3] [padding:13px_19px_0] [color:#596579] [font-size:10px] [font-weight:620] [border-color:#dfe5dc] [color:#56665a]"}><span>Invoice value by currency</span></div>
          {Object.keys(stats.total_invoice_value).length > 0 ? (
            <div className={"[display:grid] [gap:8px] [padding:9px_19px_15px] [&_div]:[display:flex] [&_div]:[justify-content:space-between] [&_div]:[gap:10px] [&_div]:[color:#788295] [&_div]:[font-size:10px] [&_strong]:[color:#344054] [&_strong]:[font-size:11px] [&_strong]:[font-weight:630] [&_strong]:[color:var(--forest)]"}>{Object.entries(stats.total_invoice_value).map(([currency, value]) => <div key={currency}><span>{currency}</span><strong>{displayMoney(value, currency)}</strong></div>)}</div>
          ) : <p className={"[color:#939cac] [font-size:9px] [line-height:1.5] [padding:0_19px_17px]"}>Totals appear here when invoices have been extracted.</p>}
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
      <div className={"[display:flex] [align-items:flex-end] [justify-content:space-between] [gap:20px] [margin-bottom:26px] [&_h1]:[margin:7px_0_4px] [&_h1]:[color:#192437] [&_h1]:[font-size:clamp(24px,_2.2vw,_29px)] [&_h1]:[font-weight:650] [&_h1]:[letter-spacing:-0.045em] [&_h1]:[line-height:1.2] [&_p]:[margin:0] [&_p]:[color:#7c8798] [&_p]:[font-size:13px] max-[680px]:[align-items:flex-start] max-[680px]:[&_.button]:[min-height:34px] max-[680px]:[&_.button]:[flex:0_0_auto] max-[680px]:[&_.button]:[padding:0_9px] max-[680px]:[&_.button]:[font-size:10px] max-[680px]:[&_h1]:[font-size:24px] max-[680px]:[&_p]:[max-width:240px] max-[680px]:[&_p]:[font-size:11px] max-[680px]:[&_p]:[line-height:1.5] [margin-bottom:28px] [border-bottom:1px_solid_#ccd5c9] [padding-bottom:23px] [&_h1]:[margin-top:9px] [&_h1]:[color:var(--forest)] [&_h1]:[font-family:Georgia,_\"Times_New_Roman\",_serif] [&_h1]:[font-size:38px] [&_h1]:[font-weight:500] [&_h1]:[letter-spacing:0] [&_h1]:[line-height:1.08] [&_p]:[color:#6f7a72] [animation:rise-in_420ms_ease-out_both] max-[680px]:[padding-bottom:18px] max-[680px]:[&_h1]:[font-size:31px]"}>
        <div><span className={"[display:block] [color:#7e899a] [font-size:9px] [font-weight:720] [letter-spacing:0.13em] [color:var(--leaf)] [letter-spacing:0.1em]"}>DOCUMENT LIBRARY</span><h1>Invoices</h1><p>Search, review, and manage your invoice documents.</p></div>
        <button className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-[#315b43] bg-[#315b43] px-3 text-xs font-semibold text-white shadow-sm transition-colors hover:border-[#254a35] hover:bg-[#254a35] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#315b43] disabled:cursor-not-allowed disabled:opacity-60" type="button" onClick={onUpload}><Plus size={17} /> Upload invoice</button>
      </div>
      <section className={"[border:1px_solid_#e8ebf0] [border-radius:10px] [background:#fff] [box-shadow:0_1px_2px_rgb(16_24_40_/_3%)] [overflow:hidden] [border:0] [border-radius:0] [background:transparent] [box-shadow:none] [border-top:2px_solid_var(--forest)] [min-height:370px] [border-top-width:2px] [animation:rise-in_420ms_ease-out_both] [animation-delay:100ms]"}>
        <div className="grid grid-cols-[minmax(0,1fr)_repeat(2,minmax(125px,160px))_minmax(140px,160px)_31px] items-center gap-2 border-b border-[#e0e6dd] px-4 py-3 max-[1000px]:grid-cols-4 max-[680px]:grid-cols-2 max-[480px]:grid-cols-1 max-[680px]:px-3 max-[680px]:py-3">
          <label className="col-span-1 flex min-w-0 items-center gap-2 rounded-md border border-[#dce3d9] bg-[#fbfcf8] px-3 text-[#7b897f] transition focus-within:border-[#80966b] focus-within:ring-2 focus-within:ring-[#5b7d3e]/10 max-[1000px]:col-span-4 max-[680px]:col-span-2 max-[480px]:col-span-1 [&_input]:min-w-0 [&_input]:w-full [&_input]:border-0 [&_input]:bg-transparent [&_input]:text-sm [&_input]:text-[#33443a] [&_input]:outline-none [&_input::placeholder]:text-[#919c92]"><Search size={17} /><input value={params.q ?? ''} placeholder="Search supplier or invoice number" onChange={(event) => onParamsChange({ ...params, q: event.target.value, page: 1 })} /></label>
          <label className="col-span-1 flex min-w-0 items-center gap-2 rounded-md border border-[#dce3d9] bg-[#fbfcf8] px-3 text-[#7b897f] [&_select]:min-w-0 [&_select]:flex-1 [&_select]:cursor-pointer [&_select]:truncate [&_select]:border-0 [&_select]:bg-transparent [&_select]:text-xs [&_select]:text-[#33443a] [&_select]:outline-none max-[1000px]:col-span-2 max-[680px]:col-span-1"><Filter size={15} /><select value={params.validation_status ?? ''} onChange={(event) => onParamsChange({ ...params, validation_status: event.target.value as ValidationStatus | '', page: 1 })}><option value="">All validation</option><option value="PASSED">Passed</option><option value="FAILED">Failed</option><option value="WARNING">Warning</option><option value="NOT_CHECKED">Not checked</option></select></label>
          <label className="col-span-1 flex min-w-0 items-center gap-2 rounded-md border border-[#dce3d9] bg-[#fbfcf8] px-3 [&_select]:min-w-0 [&_select]:flex-1 [&_select]:cursor-pointer [&_select]:truncate [&_select]:border-0 [&_select]:bg-transparent [&_select]:text-xs [&_select]:text-[#33443a] [&_select]:outline-none max-[1000px]:col-span-2 max-[680px]:col-span-1"><select value={params.processing_status ?? ''} onChange={(event) => onParamsChange({ ...params, processing_status: event.target.value as ProcessingStatus | '', page: 1 })}><option value="">All processing</option><option value="COMPLETED">Completed</option><option value="FAILED">Failed</option><option value="PROCESSING">Processing</option><option value="PENDING">Pending</option></select></label>
          <label className="col-span-1 flex min-w-0 items-center gap-2 rounded-md border border-[#dce3d9] bg-[#fbfcf8] px-3 text-xs text-[#7b897f] max-[1000px]:col-span-3 max-[680px]:col-span-1"><span className="whitespace-nowrap">Sort by</span><select className="min-w-0 flex-1 cursor-pointer truncate border-0 bg-transparent text-xs text-[#33443a] outline-none" value={params.sort_by} onChange={(event) => onParamsChange({ ...params, sort_by: event.target.value as InvoiceListParams['sort_by'], page: 1 })}><option value="created_at">Date added</option><option value="invoice_date">Invoice date</option><option value="supplier_name">Supplier</option><option value="invoice_number">Invoice number</option><option value="total_amount">Amount</option></select></label>
          <button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)] [border-color:#e4e8ee]"} type="button" onClick={() => onParamsChange({ ...params, order: params.order === 'desc' ? 'asc' : 'desc', page: 1 })} aria-label={`Sort ${params.order === 'desc' ? 'ascending' : 'descending'}`}>{params.order === 'desc' ? <ArrowDown size={16} /> : <ArrowUp size={16} />}</button>
        </div>
        {isLoading ? <div className={"[display:flex] [min-height:150px] [align-items:center] [justify-content:center] [gap:10px] [color:#7d8899] [font-size:12px]"}><LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={22} /> Loading invoices…</div> : (
          <InvoiceTable invoices={data?.items ?? []} onOpen={onOpen} />
        )}
        {data && (
          <div className={"[display:flex] [min-height:51px] [align-items:center] [justify-content:space-between] [border-top:1px_solid_#eff1f4] [padding:0_16px] [color:#8a94a4] [font-size:10px] [&_>_div]:[display:flex] [&_>_div]:[align-items:center] [&_>_div]:[gap:9px] [&_.icon-button]:[width:27px] [&_.icon-button]:[height:27px] [&_.icon-button]:[border-color:#e8ebef] max-[680px]:[gap:7px] max-[680px]:[padding:0_10px] max-[680px]:[font-size:9px] max-[680px]:[&_>_div]:[gap:4px] [border-color:#e0e6dd]"}>
            <span>Showing {data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1}–{Math.min(data.page * data.page_size, data.total)} of {displayCount(data.total)} invoices</span>
            <div><button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)]"} type="button" aria-label="Previous page" disabled={data.page <= 1} onClick={() => onParamsChange({ ...params, page: params.page - 1 })}><ChevronLeft size={17} /></button><span>Page {data.page} of {Math.max(data.pages, 1)}</span><button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)]"} type="button" aria-label="Next page" disabled={data.page >= data.pages} onClick={() => onParamsChange({ ...params, page: params.page + 1 })}><ChevronRight size={17} /></button></div>
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

  useEffect(() => {
    if (selectedId === null) return

    const rootOverflow = document.documentElement.style.overflow
    const bodyOverflow = document.body.style.overflow
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'

    return () => {
      document.documentElement.style.overflow = rootOverflow
      document.body.style.overflow = bodyOverflow
    }
  }, [selectedId])

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
    refetchInterval: (query) => query.state.data?.items.some(
      (invoice) => invoice.processing_status === 'PENDING' || invoice.processing_status === 'PROCESSING',
    ) ? 1500 : false,
  })
  const selectedQuery = useQuery({
    queryKey: ['invoice', selectedId],
    queryFn: () => getInvoice(selectedId!),
    enabled: selectedId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.processing_status
      return status === 'PROCESSING' ? 2000 : false
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => uploadInvoices(files),
    onSuccess: async (invoices) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
      ])
      for (const invoice of invoices) {
        queryClient.setQueryData(['invoice', invoice.id], invoice)
      }
      setUploadOpen(false)
      setSection('invoices')
      if (invoices.length === 1) {
        setSelectedId(invoices[0].id)
        setNotice('Invoice uploaded and queued for processing. We’ll refresh it as extraction finishes.')
      } else {
        setSelectedId(null)
        setNotice(`${invoices.length} invoices uploaded. Processing continues in the background; statuses refresh automatically.`)
      }
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
  const reprocessMutation = useMutation({
    mutationFn: () => reprocessInvoice(selectedId!),
    onSuccess: async (invoice) => {
      queryClient.setQueryData(['invoice', invoice.id], invoice)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
      ])
      setNotice('Full-page re-extraction started. Extracted values will be replaced when it finishes.')
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

  const actionError = saveMutation.error ?? validateMutation.error ?? reprocessMutation.error ?? deleteMutation.error

  function openInvoice(id: number) {
    setSelectedId(id)
    saveMutation.reset()
    validateMutation.reset()
    reprocessMutation.reset()
    deleteMutation.reset()
  }

  function closeReview() {
    setSelectedId(null)
    saveMutation.reset()
    validateMutation.reset()
    reprocessMutation.reset()
    deleteMutation.reset()
  }

  function changeParams(next: InvoiceListParams) {
    setParams(next)
  }

  return (
    <div className={"[min-height:100vh] [background:#f7f8fa] [background:var(--paper)] [color:var(--ink)]"}>
      <aside className={"[position:fixed] [inset:0_auto_0_0] [z-index:5] [display:flex] [width:252px] [flex-direction:column] [border-right:1px_solid_#e8ebef] [background:#fff] [padding:25px_17px_17px] max-[1150px]:[width:215px] max-[850px]:[position:static] max-[850px]:[width:auto] max-[850px]:[height:auto] max-[850px]:[flex-direction:row] max-[850px]:[align-items:center] max-[850px]:[justify-content:space-between] max-[850px]:[border-right:0] max-[850px]:[border-bottom:1px_solid_#e8ebef] max-[850px]:[padding:11px_18px] [border-color:#29473d] [background:var(--forest)] [padding-top:27px] max-[850px]:[border-bottom-color:#29473d]"}>
        <a className={"[display:flex] [align-items:center] [gap:11px] [padding:0_9px] [&_strong]:[display:block] [&_small]:[display:block] [&_strong]:[color:#172033] [&_strong]:[font-size:15px] [&_strong]:[font-weight:680] [&_strong]:[letter-spacing:-0.02em] [&_small]:[margin-top:2px] [&_small]:[color:#8a93a3] [&_small]:[font-size:11px] max-[850px]:[padding:0] max-[390px]:[&_small]:[display:none] [&_strong]:[color:#f5f7ef] [&_small]:[color:#a7b9ae]"} href="#" onClick={(event) => { event.preventDefault(); setSection('overview') }}>
          <span className={"[display:grid] [width:37px] [height:37px] [place-items:center] [border-radius:11px] [background:#155eef] [color:#fff] [font-size:13px] [font-weight:750] [letter-spacing:-0.04em] max-[850px]:[width:33px] max-[850px]:[height:33px] [border-radius:9px] [background:var(--citrus)] [color:var(--forest)]"} aria-hidden="true"><FileCheck2 size={21} strokeWidth={2.2} /></span>
          <span><strong>InvoiceIQ</strong><small>Invoice workspace</small></span>
        </a>
        <div className={"[margin:42px_10px_11px] [color:#929aaa] [font-size:10px] [font-weight:720] [letter-spacing:0.12em] max-[850px]:[display:none] [color:#96aa9e] [letter-spacing:0.08em]"}>WORKSPACE</div>
        <nav className={"[display:grid] [gap:5px] max-[850px]:[display:flex] max-[850px]:[gap:4px]"} aria-label="Main navigation">
          <button className={section === 'overview' ? '[display:flex] [height:41px] [align-items:center] [gap:11px] [border:0] [border-radius:8px] [background:transparent] [padding:0_11px] [color:#566174] [font-size:13px] [font-weight:540] [text-align:left] [transition:background_130ms_ease,_color_130ms_ease] [&:hover]:[background:#f6f7f9] [&:hover]:[color:#263248] [&.nav-active]:[background:#edf4ff] [&.nav-active]:[color:#175cd3] [&.nav-active]:[font-weight:650] max-[850px]:[height:35px] max-[850px]:[padding:0_10px] max-[850px]:[font-size:11px] max-[390px]:[gap:6px] max-[390px]:[padding:0_7px] max-[390px]:[font-size:10px] [border-radius:6px] [color:#c1cdc5] [&:hover]:[background:rgb(255_255_255_/_8%)] [&:hover]:[color:#fff] [&.nav-active]:[background:rgb(217_239_85_/_13%)] [&.nav-active]:[color:var(--citrus)] [&_.nav-count]:[background:#dceaff] [&_.nav-count]:[color:#175cd3] [&_.nav-count]:[background:rgb(255_255_255_/_10%)] [&_.nav-count]:[color:#e7efdf]' : '[display:flex] [height:41px] [align-items:center] [gap:11px] [border:0] [border-radius:8px] [background:transparent] [padding:0_11px] [color:#566174] [font-size:13px] [font-weight:540] [text-align:left] [transition:background_130ms_ease,_color_130ms_ease] [&:hover]:[background:#f6f7f9] [&:hover]:[color:#263248] [&.nav-active]:[background:#edf4ff] [&.nav-active]:[color:#175cd3] [&.nav-active]:[font-weight:650] max-[850px]:[height:35px] max-[850px]:[padding:0_10px] max-[850px]:[font-size:11px] max-[390px]:[gap:6px] max-[390px]:[padding:0_7px] max-[390px]:[font-size:10px] [border-radius:6px] [color:#c1cdc5] [&:hover]:[background:rgb(255_255_255_/_8%)] [&:hover]:[color:#fff] [&.nav-active]:[background:rgb(217_239_85_/_13%)] [&.nav-active]:[color:var(--citrus)]'} type="button" onClick={() => setSection('overview')}><BarChart3 size={17} /> Overview</button>
          <button className={section === 'invoices' ? '[display:flex] [height:41px] [align-items:center] [gap:11px] [border:0] [border-radius:8px] [background:transparent] [padding:0_11px] [color:#566174] [font-size:13px] [font-weight:540] [text-align:left] [transition:background_130ms_ease,_color_130ms_ease] [&:hover]:[background:#f6f7f9] [&:hover]:[color:#263248] [&.nav-active]:[background:#edf4ff] [&.nav-active]:[color:#175cd3] [&.nav-active]:[font-weight:650] max-[850px]:[height:35px] max-[850px]:[padding:0_10px] max-[850px]:[font-size:11px] max-[390px]:[gap:6px] max-[390px]:[padding:0_7px] max-[390px]:[font-size:10px] [border-radius:6px] [color:#c1cdc5] [&:hover]:[background:rgb(255_255_255_/_8%)] [&:hover]:[color:#fff] [&.nav-active]:[background:rgb(217_239_85_/_13%)] [&.nav-active]:[color:var(--citrus)] [&_.nav-count]:[background:#dceaff] [&_.nav-count]:[color:#175cd3] [&_.nav-count]:[background:rgb(255_255_255_/_10%)] [&_.nav-count]:[color:#e7efdf]' : '[display:flex] [height:41px] [align-items:center] [gap:11px] [border:0] [border-radius:8px] [background:transparent] [padding:0_11px] [color:#566174] [font-size:13px] [font-weight:540] [text-align:left] [transition:background_130ms_ease,_color_130ms_ease] [&:hover]:[background:#f6f7f9] [&:hover]:[color:#263248] [&.nav-active]:[background:#edf4ff] [&.nav-active]:[color:#175cd3] [&.nav-active]:[font-weight:650] max-[850px]:[height:35px] max-[850px]:[padding:0_10px] max-[850px]:[font-size:11px] max-[390px]:[gap:6px] max-[390px]:[padding:0_7px] max-[390px]:[font-size:10px] [border-radius:6px] [color:#c1cdc5] [&:hover]:[background:rgb(255_255_255_/_8%)] [&:hover]:[color:#fff] [&.nav-active]:[background:rgb(217_239_85_/_13%)] [&.nav-active]:[color:var(--citrus)]'} type="button" onClick={() => setSection('invoices')}><FileCheck2 size={17} /> Invoices<span className={"[margin-left:auto] [border-radius:99px] [background:#f0f2f5] [padding:2px_7px] [color:#677286] [font-size:10px] [font-weight:650] max-[850px]:[display:none] [background:rgb(255_255_255_/_10%)] [color:#e7efdf]"}>{dashboardQuery.data?.total_invoices ?? 0}</span></button>
        </nav>
        <div className={"[margin-top:auto] max-[850px]:[display:none]"}>
          <div className="mb-4 rounded-lg border border-[#365447] bg-[#203d34] p-4 shadow-sm">
            <span className="grid size-8 place-items-center rounded-lg bg-white/10 text-[#d9ef55]"><ShieldAlert size={16} /></span>
            <strong className="mt-3 block text-sm font-semibold text-[#f3f5ef]">Review with confidence</strong>
            <p className="mt-1 text-xs leading-relaxed text-[#d1dbd2]">OCR evidence and deterministic checks keep every invoice traceable.</p>
          </div>
          <div className={"[display:flex] [height:35px] [align-items:center] [gap:8px] [border-top:1px_solid_#edf0f3] [padding:12px_5px_0] [color:#788295] [font-size:11px] [&_a]:[display:grid] [&_a]:[color:#8590a0] [border-color:#365447] [color:#b2c1b6] [&_a]:[color:#b2c1b6]"}><span className={`[width:7px] [height:7px] [border-radius:50%] [background:#17b26a] ${healthQuery.isSuccess && healthQuery.data.status === 'ok' ? '' : '[background:#e05252]'}`} />{healthQuery.isLoading ? 'Checking API…' : healthQuery.isSuccess && healthQuery.data.status === 'ok' ? 'API connected' : 'API unavailable'}<button className={"[display:grid] [width:21px] [height:21px] [place-items:center] [margin-left:auto] [border:0] [border-radius:5px] [background:transparent] [color:#929aaa] [&:hover]:[background:#f3f5f7] [&:hover]:[color:#475368] [color:#b2c1b6] [&:hover]:[background:rgb(255_255_255_/_9%)] [&:hover]:[color:#fff]"} type="button" onClick={() => void healthQuery.refetch()} aria-label="Check API connection"><RefreshCw size={13} /></button><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer" aria-label="Open API docs"><ArrowUpRight size={14} /></a></div>
        </div>
      </aside>

      <div className={"[display:flex] [min-height:100vh] [flex-direction:column] [margin-left:252px] max-[1150px]:[margin-left:215px] max-[850px]:[min-height:calc(100vh_-_56px)] max-[850px]:[margin-left:0] [background:var(--paper)]"}>
        <header className={"[position:sticky] [top:0] [z-index:4] [display:flex] [height:63px] [flex:0_0_63px] [align-items:center] [justify-content:space-between] [border-bottom:1px_solid_#e9ecf0] [background:rgb(255_255_255_/_94%)] [padding:0_38px] [backdrop-filter:blur(12px)] max-[1150px]:[padding-right:25px] max-[1150px]:[padding-left:25px] max-[850px]:[position:static] max-[850px]:[height:53px] max-[850px]:[flex-basis:53px] max-[850px]:[padding:0_20px] max-[680px]:[padding:0_14px] [border-color:var(--line)] [background:rgb(251_252_248_/_94%)]"}>
          <div className={"[display:flex] [align-items:center] [gap:9px] [color:#929aaa] [font-size:12px] [&_strong]:[color:#354156] [&_strong]:[font-weight:620] [color:#8a948c] [&_strong]:[color:var(--ink)]"}><span>Workspace</span><ChevronRight size={14} /><strong>{section === 'overview' ? 'Overview' : 'Invoices'}</strong></div>
          <div className={"[display:flex] [align-items:center] [gap:15px] max-[390px]:[&_.button]:[padding:0_8px]"}><span className={"[&_>_span]:[width:7px] [&_>_span]:[height:7px] [&_>_span]:[border-radius:50%] [&_>_span]:[background:#17b26a] [display:flex] [align-items:center] [gap:7px] [color:#778194] [font-size:11px] [&_>_span]:[width:6px] [&_>_span]:[height:6px] max-[680px]:[display:none]"}><span /> Local environment</span><button className="inline-flex min-h-8 items-center justify-center gap-2 rounded-md border  bg-[#D8EF54] px-2.5 text-[11px] font-semibold text-black shadow-sm transition-colors hover:border-[#254a35] hover:bg-[#254a35] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#315b43] disabled:cursor-not-allowed disabled:opacity-60" 
          type="button" onClick={() => { uploadMutation.reset(); setUploadOpen(true) }}><Plus size={16} /> New invoice</button></div>
        </header>

        <main className={"[width:min(100%,_1450px)] [flex:1] [margin:0_auto] [padding:38px_40px_30px] max-[1150px]:[padding-right:25px] max-[1150px]:[padding-left:25px] max-[850px]:[padding:27px_20px_24px] max-[680px]:[padding:23px_14px_20px] [padding-top:43px] max-[850px]:[padding-top:32px]"}>
          {notice && <div className={"[display:flex] [align-items:center] [gap:9px] [margin-bottom:18px] [border:1px_solid_#ccebd9] [border-radius:8px] [background:#f0fbf5] [padding:9px_11px] [color:#17784e] [font-size:11px] [&_span]:[flex:1] [&_.icon-button]:[width:25px] [&_.icon-button]:[height:25px] [&_.icon-button]:[color:#57816b] [border-color:#d1dfc7] [border-radius:6px] [background:#edf4e8] [color:#4b713a]"}><CircleCheck size={17} /><span>{notice}</span><button type="button" className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)]"} onClick={() => setNotice(null)} aria-label="Dismiss notification"><X size={15} /></button></div>}
          {section === 'overview' ? (
            dashboardQuery.isLoading ? <div className={"[display:flex] [min-height:150px] [align-items:center] [justify-content:center] [gap:10px] [color:#7d8899] [font-size:12px] [min-height:50vh]"}><LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={22} /> Loading your workspace…</div>
              : dashboardQuery.error ? <div className={"[display:flex] [align-items:flex-start] [gap:12px] [border:1px_solid_#f1cdcd] [border-radius:10px] [background:#fff7f6] [padding:18px] [color:#bd3b3b] [&_>_div]:[display:grid] [&_>_div]:[gap:7px] [&_strong]:[color:#732f31] [&_strong]:[font-size:13px] [&_span]:[color:#9c5556] [&_span]:[font-size:11px] [&_.text-button]:[justify-self:start]"}><CircleAlert size={20} /><div><strong>Couldn’t load your dashboard</strong><span>{dashboardQuery.error.message}</span><button className={"[display:inline-flex] [align-items:center] [gap:5px] [border:0] [background:transparent] [padding:4px_0] [color:#175cd3] [font-size:11px] [font-weight:620] [&:hover]:[color:#004eeb] [color:#48683c] [&:hover]:[color:#274c31]"} type="button" onClick={() => void dashboardQuery.refetch()}>Try again <RefreshCw size={14} /></button></div></div>
                : dashboardQuery.data ? <Dashboard stats={dashboardQuery.data} onViewAll={() => setSection('invoices')} onOpen={openInvoice} onUpload={() => { uploadMutation.reset(); setUploadOpen(true) }} /> : null
          ) : (
            <InvoiceHistory data={invoicesQuery.data} params={params} onParamsChange={changeParams} onOpen={openInvoice} onUpload={() => { uploadMutation.reset(); setUploadOpen(true) }} isLoading={invoicesQuery.isLoading} />
          )}
        </main>
        <footer className={"[display:flex] [min-height:47px] [align-items:center] [justify-content:space-between] [gap:14px] [border-top:1px_solid_#eaedf1] [padding:0_40px] [color:#98a1af] [font-size:10px] [&_a]:[display:inline-flex] [&_a]:[align-items:center] [&_a]:[gap:4px] [&_a]:[color:#728096] max-[1150px]:[padding-right:25px] max-[1150px]:[padding-left:25px] max-[850px]:[padding:0_20px] max-[680px]:[padding:0_14px] max-[680px]:[font-size:9px] [border-color:var(--line)] [color:#8a948c] [&_a]:[color:#5e725f] max-[680px]:[background:var(--paper)]"}><span>InvoiceIQ · Invoice processing with evidence</span><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">API documentation <ArrowUpRight size={13} /></a></footer>
      </div>

      {uploadOpen && <UploadDialog onClose={() => { if (!uploadMutation.isPending) setUploadOpen(false) }} onUpload={(files) => uploadMutation.mutate(files)} isUploading={uploadMutation.isPending} error={uploadMutation.error?.message ?? null} />}
      {selectedId !== null && (
        selectedQuery.isLoading ? <div className={"[position:fixed] [inset:0] [z-index:20] [display:flex] [align-items:center] [justify-content:center] [background:rgb(24_33_49_/_42%)] [padding:22px] [backdrop-filter:blur(2px)] [z-index:18] [justify-content:flex-end] [padding:0] [animation:review-backdrop-enter_280ms_ease-out_both] motion-reduce:[animation-duration:1ms]"}><div className={"[margin:auto] [background:#fff] [box-shadow:0_12px_40px_rgb(16_24_40_/_14%)] [display:flex] [align-items:center] [gap:10px] [border-radius:10px] [padding:20px_24px] [color:#657185] [font-size:12px]"}><LoaderCircle className={"[animation:spin_900ms_linear_infinite]"} size={24} /> Loading invoice…</div></div>
          : selectedQuery.error ? <div className={"[position:fixed] [inset:0] [z-index:20] [display:flex] [align-items:center] [justify-content:center] [background:rgb(24_33_49_/_42%)] [padding:22px] [backdrop-filter:blur(2px)] [z-index:18] [justify-content:flex-end] [padding:0] [animation:review-backdrop-enter_280ms_ease-out_both] motion-reduce:[animation-duration:1ms]"} onMouseDown={(event) => { if (event.target === event.currentTarget) closeReview() }}><div className={"[display:flex] [align-items:flex-start] [gap:12px] [border:1px_solid_#f1cdcd] [border-radius:10px] [background:#fff7f6] [padding:18px] [color:#bd3b3b] [margin:auto] [background:#fff] [box-shadow:0_12px_40px_rgb(16_24_40_/_14%)] [position:relative] [display:grid] [width:min(100%,_360px)] [justify-items:start] [gap:10px] [border-color:#e8ebf0] [color:#c14444] [&_.icon-button]:[position:absolute] [&_.icon-button]:[top:8px] [&_.icon-button]:[right:8px] [&_strong]:[color:#344054] [&_strong]:[font-size:13px] [&_span]:[color:#788295] [&_span]:[font-size:11px]"}><button className={"[display:inline-grid] [width:31px] [height:31px] [flex:0_0_auto] [place-items:center] [border:1px_solid_transparent] [border-radius:7px] [background:transparent] [color:#687386] [transition:background_120ms_ease,_border-color_120ms_ease,_color_120ms_ease] [&:hover:not(:disabled)]:[border-color:#e7eaf0] [&:hover:not(:disabled)]:[background:#f7f8fa] [&:hover:not(:disabled)]:[color:#344054] [color:#66746a] [&:hover:not(:disabled)]:[border-color:#dce3d9] [&:hover:not(:disabled)]:[background:#eff3eb] [&:hover:not(:disabled)]:[color:var(--forest)]"} type="button" onClick={closeReview} aria-label="Close"><X size={18} /></button><CircleAlert size={22} /><strong>Couldn’t open this invoice</strong><span>{selectedQuery.error.message}</span><button className={"[display:inline-flex] [min-height:37px] [align-items:center] [justify-content:center] [gap:8px] [border:1px_solid_transparent] [border-radius:7px] [padding:0_13px] [font-size:12px] [font-weight:620] [transition:background_130ms_ease,_border-color_130ms_ease,_box-shadow_130ms_ease] [border-color:#e2e6ec] [background:#fff] [color:#465166] [&:hover:not(:disabled)]:[border-color:#cdd3dc] [&:hover:not(:disabled)]:[background:#f9fafb] [border-color:#d8dfd5] [background:var(--panel)] [color:#46564b] [&:hover:not(:disabled)]:[border-color:#bac8b8] [&:hover:not(:disabled)]:[background:#f2f5ee]"} type="button" onClick={() => void selectedQuery.refetch()}>Try again</button></div></div>
            : selectedQuery.data ? (
              <>
                {actionError && <div className={"[position:fixed] [z-index:25] [top:78px] [right:24px] [display:flex] [max-width:min(480px,_calc(100vw_-_32px))] [align-items:flex-start] [gap:9px] [border:1px_solid_#efcdcc] [border-radius:8px] [background:#fff7f6] [padding:10px_12px] [color:#b63d3d] [box-shadow:0_5px_18px_rgb(16_24_40_/_10%)] [font-size:10px] [line-height:1.5] [&_span]:[flex:1] [&_button]:[display:grid] [&_button]:[place-items:center] [&_button]:[border:0] [&_button]:[background:transparent] [&_button]:[color:#a66565]"}><CircleAlert size={16} /><span>{actionError.message}</span><button type="button" onClick={() => { saveMutation.reset(); validateMutation.reset(); deleteMutation.reset() }} aria-label="Dismiss error"><X size={15} /></button></div>}
                <InvoiceReview
                  key={`${selectedId}-${reviewRevision}-${selectedQuery.data.processing_status}`}
                  invoice={selectedQuery.data}
                  onClose={closeReview}
                  onSave={(correction) => saveMutation.mutate(correction)}
                  onValidate={() => validateMutation.mutate()}
                  onReprocess={() => {
                    if (window.confirm('Re-extract the full document? This replaces all current extracted values, including unsaved edits.')) {
                      reprocessMutation.mutate()
                    }
                  }}
                  onDelete={() => { if (window.confirm('Delete this invoice and its stored document? This cannot be undone.')) deleteMutation.mutate() }}
                  saving={saveMutation.isPending}
                  validating={validateMutation.isPending}
                  reprocessing={reprocessMutation.isPending || selectedQuery.data.processing_status === 'PROCESSING' || selectedQuery.data.processing_status === 'PENDING'}
                  deleting={deleteMutation.isPending}
                />
              </>
            ) : null
      )}
    </div>
  )
}

export default App
