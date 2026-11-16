# InvoiceIQ

## Requirements

- Python 3.10
- Node.js and npm

## Windows

Run these backend commands from the project folder:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
if (!(Test-Path .\backend\.env)) { Copy-Item .\backend\.env.example .\backend\.env }
Set-Location .\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In a second terminal, from the project folder, start the frontend:

```powershell
Set-Location .\frontend
npm install
if (!(Test-Path .\.env)) { Copy-Item .\.env.example .\.env }
npm run dev
```

## macOS and Linux

Run these backend commands from the project folder:

```bash
python3.10 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
test -f backend/.env || cp backend/.env.example backend/.env
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload
```

In a second terminal, from the project folder, start the frontend:

```bash
cd frontend
npm install
test -f .env || cp .env.example .env
npm run dev
```

Open the frontend at `http://localhost:5173`. The backend API is at `http://localhost:8000`; its interactive docs are at `http://localhost:8000/docs`. PaddleOCR downloads its models on first use.

## Deploying a public demo

The app can be deployed with Vercel (frontend), Render (FastAPI API), and Supabase (Postgres and invoice files). The Render Blueprint is in `render.yaml`.

1. In Supabase, create a project and a **private** Storage bucket named `invoice-documents`. Copy the project URL, service-role key, and Postgres connection string. Use the Session pooler connection string if the direct database connection is unavailable from Render.
2. Deploy the repository's `render.yaml` as a Blueprint on Render; it pins the API to Render's Free compute plan. Set the prompted `DATABASE_URL` to the Supabase Postgres connection string, `SUPABASE_URL` to the project URL, and `SUPABASE_SERVICE_ROLE_KEY` to the service-role key. Set `CORS_ORIGINS` temporarily to `http://localhost:5173`; you will replace it with the Vercel URL in step 4. Keep the service-role key only in Render's environment settings; never put it in the frontend or commit it. The API uses the private bucket for uploaded documents.
3. In Vercel, import the repository, set the Root Directory to `frontend`, and set `VITE_API_URL` to the Render API URL. Use `npm run build` and `dist` if Vercel does not detect the Vite defaults.
4. After Vercel provides the frontend URL, set Render's `CORS_ORIGINS` to that exact origin (for example, `https://your-project.vercel.app`) and redeploy the API.
5. Verify the API at `https://your-render-service.onrender.com/api/health`, then test an upload, document preview, and delete using a dummy invoice.

Render builds the OCR dependencies and downloads PaddleOCR models on first use, so the first deployment or invoice may take longer. The app does not currently have user authentication: anyone with the public URL can view, upload, edit, or delete demo invoices. Use synthetic data only; do not upload real or confidential invoices.
