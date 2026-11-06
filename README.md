# InvoiceIQ

InvoiceIQ is being built as an invoice extraction and verification application
for the supplied technical assessment. The Python backend is the source of
truth for extraction data and financial validation; the React application
provides an interface for uploading and reviewing invoices.

## Difference between the two approaches

The original implementation in `invoice_extractor.py` is a small, single-file
command-line tool. It sends an image directly to OpenAI's vision API, receives
JSON, and checks a couple of totals. It is quick to run and easy to understand,
but depends on one provider, has no OCR text or bounding-box evidence, and
doesn't save invoices or provide a review interface.

The InvoiceIQ specification describes a larger, multi-stage application:

1. Validate and preprocess an uploaded image or PDF.
2. Use OCR to collect text, page references, and (where available) bounding
   boxes and OCR confidence.
3. Extract labeled fields from OCR text with local rules, or optionally send
   the document and OCR text to a vision provider (Gemini or Claude).
4. Validate amounts deterministically with `Decimal`, preserve evidence, and
   store invoices for review in a database.
5. Expose that workflow through a FastAPI API and a React web interface.

The direct-vision approach is simpler and has fewer moving parts. The OCR-plus-
vision approach takes more setup and compute, but can provide traceable source
evidence, handle PDFs and multi-page documents, and swap providers behind an
interface. The latter is the target architecture; the existing CLI remains a
separate, runnable first implementation rather than pretending to be that
complete system.

## Development status

Work is incremental, as requested. **Phase 1 is complete**: the backend and
frontend foundations, initial schemas, and database models are in place.
**Phase 2 is complete**: the independent Python pipeline now validates and
renders PNG/JPEG/PDF documents, reads OCR through PaddleOCR, and extracts
structured data through a local rule-based adapter or optional Gemini/Claude
vision adapters. OCR and provider calls are injectable so tests do not require
model downloads or paid API calls.
**Phase 3 is complete**: the extraction pipeline now runs a financial validator
that checks line-item arithmetic, subtotal, document-specified tax rate, grand
total, currency consistency, required fields, and date order using `Decimal`.
**Phase 4 is complete**: FastAPI now exposes upload, invoice history/detail,
manual correction, revalidation, JSON export, original document preview,
deletion, and database-backed dashboard statistics. Uploads are size/type
checked, stored under randomized filenames, and OCR evidence is retained when
vision extraction fails. **Phase 5 is complete**: the React frontend is
connected to those APIs and includes dashboard metrics, searchable and
filterable invoice history, document upload, invoice review with source
evidence and document preview, editable invoice and line-item fields,
revalidation, JSON export, and deletion. The API health indicator reports the
live health endpoint.

Remaining work is Phase 6: end-to-end testing against representative invoices,
integration polish, and final deployment-readiness documentation. The API is
also available through Swagger at `/docs`.

## Architecture

```text
backend/
  app/
    config.py            Environment-based settings
    database.py          SQLAlchemy engine, session, and declarative base
    main.py              FastAPI app, health endpoint, router registration
    api/invoices.py      Upload, history, review, export, and dashboard routes
    providers/           Local rules and optional Gemini/Claude adapters
    services/            PDF/image rendering, OCR, normalization, evidence,
                         extraction pipeline, and Decimal validation
    models/invoice.py    Invoice, line-item, and validation-result tables
    schemas/invoice.py   Pydantic request/response data models
  tests/                 Foundation, extraction, financial, and API tests
frontend/
  src/                   React + TypeScript invoice dashboard and review workflows
  components.json        shadcn/ui configuration
invoice_extractor.py     Existing standalone OpenAI CLI
test_invoice_extractor.py CLI tests (no paid API calls)
```

Invoice and line-item monetary values use SQL `NUMERIC` and Python `Decimal`
types in the new backend foundation. The CLI is an independent initial
prototype and currently uses its own response/validation format.

## Requirements

- Python 3.11 or later is the target for backend development. The existing
  workspace virtual environment is Python 3.10.11; Phase 1 was smoke-tested
  there and Phase 2's dependencies and tests were also validated there.
- Node.js 20.19+ and npm (the current Vite release requires a recent Node).
- For OCR, a supported PaddlePaddle CPU runtime and internet access for
  PaddleOCR's first-use model download. PaddleOCR then runs locally.
- Gemini or Anthropic API credentials are optional and only needed if you
  choose one of those paid/network vision providers. Local rule-based
  extraction does not make an AI API call.

## Setup

### Backend

From the project root in PowerShell:

```powershell
py -3.11 -m venv .venv-invoiceiq
.\.venv-invoiceiq\Scripts\Activate.ps1
python -m pip install -r .\backend\requirements.txt
Copy-Item .\backend\.env.example .\backend\.env
Set-Location .\backend
uvicorn app.main:app --reload
```

The health endpoint is `http://localhost:8000/api/health`; FastAPI's generated
API documentation is at `http://localhost:8000/docs`. The SQLite database
defaults to `backend/invoiceiq.db` and its tables are created when the app
starts. Override `DATABASE_URL` to use another SQLAlchemy database URL.
PaddleOCR downloads its English recognition models on its first OCR run; this
may take a few minutes and requires internet access.

The extraction pipeline can be called from Python with `extract_document(content,
filename, settings=...)` in `app.services.extraction_pipeline`. `content` is
the document's bytes. The function returns normalized invoice data, OCR lines
with page/bounding-box/confidence evidence, financial validation checks,
warnings, and any provider error. By default, `AI_PROVIDER=local` uses PaddleOCR
text and conservative rules for clearly labeled fields such as invoice
number/date, currency, subtotal, tax, and total; it does not call an AI API.
Line items and unlabeled or ambiguous values are intentionally left for manual
review. Set `AI_PROVIDER=gemini` or `AI_PROVIDER=claude` and configure only the
matching API key to use a vision provider instead.

The HTTP upload route invokes this pipeline and saves the original document
plus extraction, OCR, and validation metadata to SQLite. Local extraction
requires readable OCR text; if OCR is unavailable or no fields can be matched,
the request still saves the document and available OCR output for manual review.

### Frontend

In another PowerShell terminal, from the project root:

```powershell
Set-Location .\frontend
npm install
Copy-Item .\.env.example .\.env
npm run dev
```

Vite prints the local URL (normally `http://localhost:5173`). The default
`VITE_API_URL` in `.env.example` points to `http://localhost:8000`; keep the
browser frontend origin as `http://localhost:5173` or
`http://127.0.0.1:5173` to match the backend's default CORS allowlist. If you
change either host or port, update `CORS_ORIGINS` in `backend/.env` to include
the exact frontend origin.

## Environment configuration

Backend settings are read from `backend/.env` or process environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `APP_NAME` | FastAPI application title | `InvoiceIQ` |
| `DATABASE_URL` | SQLAlchemy database connection | `sqlite:///./invoiceiq.db` |
| `STORAGE_DIR` | Original uploaded document directory | `./storage` |
| `AI_PROVIDER` | Extraction mode (`local`, `gemini`, or `claude`) | `local` |
| `GEMINI_API_KEY` | Gemini API credential | unset |
| `ANTHROPIC_API_KEY` | Anthropic API credential | unset |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` |
| `ANTHROPIC_MODEL` | Anthropic model name | `claude-sonnet-4-5` |
| `PROVIDER_TIMEOUT_SECONDS` | Vision request timeout | `90` |
| `MAX_UPLOAD_SIZE_MB` | Maximum document size accepted by the pipeline | `15` |
| `MAX_DOCUMENT_PAGES` | Maximum rendered PDF pages | `50` |
| `DOCUMENT_RENDER_DPI` | PDF page rendering resolution | `150` |
| `FINANCIAL_ROUNDING_TOLERANCE` | Accepted difference for monetary checks | `0.01` |
| `CORS_ORIGINS` | Comma-separated frontend origins | localhost and 127.0.0.1 on port 5173 |

The extraction service reads the selected provider, optional credentials/model,
render DPI, and page limit. The standalone CLI instead reads `OPENAI_API_KEY`
and optionally `OPENAI_MODEL`. Never put a real key in an example file or
commit a `.env` file.

## Tests

Run backend, extraction, validation, and API tests from the project root:

```powershell
Set-Location .\backend
..\.venv-invoiceiq\Scripts\python.exe -m pytest -c .\pytest.ini .\tests -v
```

Run standalone CLI tests:

```powershell
.\.venv-invoiceiq\Scripts\python.exe -m unittest -v
```

Build the frontend:

```powershell
Set-Location .\frontend
npm run build
```

The tests use generated local documents and mocked OCR/HTTP responses; they do
not download PaddleOCR models or call a paid AI API.

The sample invoice validation uses the expected NPR 100,500.00 subtotal,
13% VAT (NPR 13,065.00), and NPR 113,565.00 total. A separate test changes the
grand total to NPR 115,565.00 and verifies the validator reports a difference
of exactly NPR 2,000.00.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/invoices/upload` | Validate, process, and save an invoice file |
| `GET` | `/api/invoices` | Search, filter, sort, and paginate invoice history |
| `GET` | `/api/invoices/{id}` | Retrieve invoice data, OCR evidence, and validation checks |
| `GET` | `/api/invoices/{id}/document` | Preview the stored original PDF or image |
| `PATCH` | `/api/invoices/{id}` | Save corrected invoice fields or line items and revalidate |
| `POST` | `/api/invoices/{id}/validate` | Re-run deterministic financial checks |
| `GET` | `/api/invoices/{id}/export` | Download the structured invoice JSON |
| `DELETE` | `/api/invoices/{id}` | Delete an invoice and its stored document |
| `GET` | `/api/dashboard/stats` | Read counts, validation distribution, totals by currency, recent activity |
| `GET` | `/api/health` | Basic app health and name |

Interactive request/response documentation is at `http://localhost:8000/docs`.
Uploads currently accept PDF, PNG, JPG, and JPEG; the default limit is 15 MB
and 50 pages per PDF. Use an `image/*` or `application/pdf` content type (or
`application/octet-stream`); the backend also checks the extension and actual
file signature before processing.

## Deployment notes and limitations

No deployment has been performed. The frontend is a Vite application that can
be built for static hosting such as Vercel. The FastAPI backend can be hosted
on Render with an environment-configured production CORS allowlist.

SQLite and local document storage require persistent disks in production.
For multiple replicas or higher throughput, use a managed database and
durable object storage. Do not rely on an ephemeral deployment filesystem for
invoice files.

Authentication is intentionally not included in this assessment MVP. The API
uses local SQLite and file storage by default; configure persistent volumes or
managed storage before deploying invoice documents. The frontend is connected
to the API, but the complete end-to-end and deployment-readiness phase remains.
The standalone CLI remains separate: it supports image input and OpenAI
vision, not PDF/OCR/provider-selectable extraction.

## Standalone CLI quick start

The initial assessment CLI can already extract an image to JSON using an
OpenAI vision model. From the project root:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
python .\invoice_extractor.py "C:\path\to\invoice.png" --output .\invoice.json
```

It accepts JPEG, PNG, WEBP, and GIF images up to 20 MB. The invoice image is
sent to OpenAI for processing; only use it with invoices you are permitted to
share with that provider.
