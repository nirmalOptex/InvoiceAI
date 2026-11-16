from functools import lru_cache
from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "InvoiceIQ"
    database_url: str = "sqlite:///./invoiceiq.db"
    storage_dir: str = "./storage"
    storage_backend: Literal["local", "supabase"] = "local"
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = Field(default=None, repr=False)
    supabase_storage_bucket: str = "invoice-documents"
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

    @model_validator(mode="after")
    def validate_storage_settings(self) -> "Settings":
        if self.storage_backend == "supabase" and (
            not self.supabase_url
            or not self.supabase_url.strip()
            or not self.supabase_service_role_key
            or not self.supabase_service_role_key.get_secret_value().strip()
            or not self.supabase_storage_bucket.strip()
        ):
            raise ValueError(
                "Supabase storage requires SUPABASE_URL, "
                "SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_STORAGE_BUCKET."
            )
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
