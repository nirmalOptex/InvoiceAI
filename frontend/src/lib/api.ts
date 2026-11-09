export type ProcessingStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
export type ValidationStatus =
  | 'PENDING'
  | 'PASSED'
  | 'FAILED'
  | 'WARNING'
  | 'NOT_CHECKED'
export type CheckStatus = 'PASSED' | 'FAILED' | 'WARNING' | 'NOT_CHECKED'
export type Money = number | string | null

export interface InvoiceItem {
  id: number
  description: string | null
  quantity: Money
  unit: string | null
  unit_price: Money
  line_total: Money
  currency: string | null
  manually_corrected: boolean
  source_evidence: Record<string, FieldEvidence>
}

export interface FieldEvidence {
  extracted_value?: unknown
  original_source_text?: string | null
  page_number?: number | null
  bounding_box?: number[] | null
  ocr_confidence?: number | null
  extraction_provider?: string | null
  manually_corrected?: boolean
}

export interface ValidationCheck {
  check_name: string
  expected_value: string | null
  actual_value: string | null
  difference: Money
  status: CheckStatus
  message: string
}

export interface Invoice {
  id: number
  original_filename: string
  supplier_name: string | null
  supplier_address: string | null
  supplier_tax_id: string | null
  invoice_number: string | null
  invoice_date: string | null
  due_date: string | null
  currency: string | null
  items: InvoiceItem[]
  subtotal: Money
  discount: Money
  tax_rate: Money
  tax_amount: Money
  additional_charges: Money
  total_amount: Money
  processing_status: ProcessingStatus
  processing_error: string | null
  validation_status: ValidationStatus
  raw_extraction_json: Record<string, unknown> | null
  extraction_metadata: {
    source_type?: string
    page_count?: number
    provider?: string | null
    warnings?: string[]
    ocr_lines?: Array<{
      text: string
      page_number: number
      bounding_box: number[] | null
      confidence: number | null
    }>
  } | null
  field_evidence: Record<string, FieldEvidence>
  validation_results: ValidationCheck[]
  created_at: string
  updated_at: string
}

export interface InvoiceListItem {
  id: number
  original_filename: string
  supplier_name: string | null
  invoice_number: string | null
  invoice_date: string | null
  currency: string | null
  total_amount: Money
  processing_status: ProcessingStatus
  processing_error: string | null
  validation_status: ValidationStatus
  created_at: string
}

export interface InvoicePage {
  items: InvoiceListItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface DashboardStats {
  total_invoices: number
  successfully_validated: number
  needs_review: number
  failed_processing: number
  total_invoice_value: Record<string, Money>
  validation_distribution: {
    passed: number
    failed: number
    warning: number
    not_checked: number
  }
  recent_invoices: Array<{
    id: number
    supplier_name: string | null
    invoice_number: string | null
    currency: string | null
    total_amount: Money
    processing_status: ProcessingStatus
    validation_status: ValidationStatus
    created_at: string
  }>
}

export interface HealthResponse {
  status: string
  app: string
}

export interface InvoiceListParams {
  q?: string
  validation_status?: ValidationStatus | ''
  processing_status?: ProcessingStatus | ''
  sort_by: 'created_at' | 'invoice_date' | 'supplier_name' | 'invoice_number' | 'total_amount'
  order: 'asc' | 'desc'
  page: number
  page_size: number
}

export interface InvoiceCorrection {
  supplier_name?: string | null
  supplier_address?: string | null
  supplier_tax_id?: string | null
  invoice_number?: string | null
  invoice_date?: string | null
  due_date?: string | null
  currency?: string | null
  subtotal?: number | null
  discount?: number | null
  tax_rate?: number | null
  tax_amount?: number | null
  additional_charges?: number | null
  total_amount?: number | null
  items?: Array<{
    description: string | null
    quantity: number | null
    unit: string | null
    unit_price: number | null
    line_total: number | null
    currency: string | null
  }>
}

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new Error('Cannot reach the InvoiceIQ API. Check that the backend server is running.')
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try {
      const body: unknown = await response.json()
      if (
        typeof body === 'object' &&
        body !== null &&
        'detail' in body &&
        typeof body.detail === 'string'
      ) {
        message = body.detail
      }
    } catch {
      // Keep the HTTP status message when the server does not return JSON.
    }
    throw new Error(message)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function getDashboardStats(): Promise<DashboardStats> {
  return request('/api/dashboard/stats')
}

export function getHealth(): Promise<HealthResponse> {
  return request('/api/health')
}

export function getInvoices(params: InvoiceListParams): Promise<InvoicePage> {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  return request(`/api/invoices?${search.toString()}`)
}

export function getInvoice(id: number): Promise<Invoice> {
  return request(`/api/invoices/${id}`)
}

export function uploadInvoice(file: File): Promise<Invoice> {
  const form = new FormData()
  form.append('file', file)
  return request('/api/invoices/upload', { method: 'POST', body: form })
}

export function uploadInvoices(files: File[]): Promise<Invoice[]> {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  return request('/api/invoices/bulk-upload', { method: 'POST', body: form })
}

export function updateInvoice(id: number, correction: InvoiceCorrection): Promise<Invoice> {
  return request(`/api/invoices/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(correction),
  })
}

export function validateInvoice(id: number): Promise<{ invoice_id: number }> {
  return request(`/api/invoices/${id}/validate`, { method: 'POST' })
}

export function deleteInvoice(id: number): Promise<void> {
  return request(`/api/invoices/${id}`, { method: 'DELETE' })
}

export function getInvoiceDocumentUrl(id: number): string {
  return `${API_BASE_URL}/api/invoices/${id}/document`
}

export function getInvoiceExportUrl(id: number): string {
  return `${API_BASE_URL}/api/invoices/${id}/export`
}
