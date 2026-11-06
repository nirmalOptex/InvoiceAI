from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.invoices import router as invoices_router
from app.config import get_settings
from app.database import create_database_tables
from app.schemas.invoice import HealthResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    create_database_tables()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(invoices_router)


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    return HealthResponse(status="ok", app=settings.app_name)
