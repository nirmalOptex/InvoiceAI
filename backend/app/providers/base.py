from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    """Raised when a configured vision provider cannot extract invoice data."""


class ProviderConfigurationError(ProviderError):
    """Raised when the selected provider is not configured correctly."""


@dataclass(frozen=True)
class VisionPage:
    page_number: int
    mime_type: str
    image_bytes: bytes


class InvoiceVisionProvider(Protocol):
    name: str

    def extract(
        self, pages: list[VisionPage], ocr_text: str
    ) -> dict[str, Any]: ...
