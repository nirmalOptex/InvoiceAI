from functools import lru_cache
from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "InvoiceIQ"
    database_url: str = "sqlite:///./invoiceiq.db"
    storage_dir: str = "./storage"
    ai_provider: str = "local"
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    anthropic_model: str = "claude-sonnet-4-5"
    provider_timeout_seconds: int = Field(default=90, ge=1, le=600)
    max_upload_size_mb: int = Field(default=15, ge=1)
    max_document_pages: int = Field(default=50, ge=1)
    document_render_dpi: int = Field(default=150, ge=72, le=300)
    financial_rounding_tolerance: Decimal = Field(
        default=Decimal("0.01"), ge=Decimal("0")
    )
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
