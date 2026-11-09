InvoiceIQ
InvoiceIQ is an invoice extraction and verification web application built for a technical assessment. It combines OCR, optional vision-model extraction, deterministic financial validation, a FastAPI backend, and a React frontend.
Features
- Upload PDF, PNG, JPG, and JPEG invoices (15 MB maximum; up to 50 PDF pages).
- Extract invoice fields using PaddleOCR and local rules, or optional Gemini/Claude vision providers.
- Retain OCR evidence, including page references, bounding boxes, and confidence where available.
- Validate line-item arithmetic, subtotal, tax, grand total, currency, required fields, and date order using Python Decimal.
- Review and edit invoices, revalidate, export JSON, preview documents, and delete records.
- View searchable invoice history and dashboard statistics.
Development status
Phases 1–5 are complete: project foundations, extraction pipeline, financial validation, API, and React review interface. Phase 6 remains: end-to-end testing with representative invoices, integration polish, and deployment-readiness documentation.
Architecture
backend/
  app/
    api/          Invoice and dashboard endpoints
    models/       SQLAlchemy models
    schemas/      Pydantic schemas
    providers/    Local, Gemini, and Claude adapters
    services/     Rendering, OCR, extraction, and validation
    config.py
    database.py
    main.py
  tests/
frontend/         React + TypeScript application
invoice_extractor.py  Standalone OpenAI vision CLI
Requirements
- Python 3.11+ (the current workspace was also tested with Python 3.10.11)
- Node.js 20.19+ and npm
- Internet access for PaddleOCR's first model download
- Optional Gemini or Anthropic API key for vision-based extraction
Setup
Backend (PowerShell, from the project root)
py -3.11 -m venv .venv-invoiceiq
.\.venv-invoiceiq\Scripts\Activate.ps1
python -m pip install -r .\backend\requirements.txt
Copy-Item .\backend\.env.example .\backend\.env
Set-Location .\backend
uvicorn app.main:app --reload
API: http://localhost:8000
Health: http://localhost:8000/api/health
Swagger docs: http://localhost:8000/docs

The default database is SQLite at backend/invoiceiq.db. PaddleOCR downloads its English models on the first OCR run.
Frontend (in a second terminal)
Set-Location .\frontend
npm install
Copy-Item .\.env.example .\.env
npm run dev
Vite normally runs at http://localhost:5173. The default API URL is http://localhost:8000. If you change the frontend origin, update CORS_ORIGINS in backend/.env.
Configuration
Backend settings are read from backend/.env. Common options:
Variable	Purpose	Default
DATABASE_URL	Database connection	sqlite:///./invoiceiq.db
STORAGE_DIR	Uploaded document storage	./storage
AI_PROVIDER	local, gemini, or claude	local
GEMINI_API_KEY	Gemini credential	Unset
ANTHROPIC_API_KEY	Anthropic credential	Unset
MAX_UPLOAD_SIZE_MB	Upload size limit	15
MAX_DOCUMENT_PAGES	PDF page limit	50


Local extraction uses OCR and conservative rules; it does not call an AI API. Ambiguous fields and line items may require manual review. Never commit real API keys or .env files.
API endpoints
Method	Endpoint	Purpose
POST	/api/invoices/upload	Upload and process an invoice
GET	/api/invoices	Search and paginate invoice history
GET	/api/invoices/{id}	Get invoice, OCR evidence, and validation
GET	/api/invoices/{id}/document	Preview original document
PATCH	/api/invoices/{id}	Edit invoice data and revalidate
POST	/api/invoices/{id}/validate	Run financial checks again
GET	/api/invoices/{id}/export	Export invoice JSON
DELETE	/api/invoices/{id}	Delete invoice and document
GET	/api/dashboard/stats	Dashboard statistics
GET	/api/health	Health check


Tests
Run backend tests:
Set-Location .\backend
..\.venv-invoiceiq\Scripts\python.exe -m pytest -c .\pytest.ini .\tests -v
Run standalone CLI tests from the project root:
.\.venv-invoiceiq\Scripts\python.exe -m unittest -v
Build the frontend:
Set-Location .\frontend
npm run build
Tests use generated documents and mocked OCR/HTTP responses; they do not require paid API calls or OCR model downloads.
Deployment notes
Deployment has not yet been performed. The Vite frontend can be built for static hosting (for example, Vercel), and the FastAPI backend can be hosted separately (for example, Render).

For production, configure persistent database and document storage. SQLite and local files need persistent disks; use a managed database and durable object storage for multiple replicas or higher throughput. Authentication is not included in this assessment MVP.
Standalone CLI
The original invoice_extractor.py is a separate image-to-JSON prototype using OpenAI vision:
$env:OPENAI_API_KEY = "your-api-key"
python .\invoice_extractor.py "C:\path\to\invoice.png" --output .\invoice.json
It accepts JPEG, PNG, WEBP, and GIF images up to 20 MB. Only submit invoices you are authorized to share with the provider.