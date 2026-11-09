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
