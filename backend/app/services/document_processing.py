from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pymupdf as fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from app.providers.base import VisionPage

SUPPORTED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
MAX_IMAGE_PIXELS = 40_000_000
MAX_RENDER_PIXELS = 16_000_000


class DocumentProcessingError(Exception):
    """Raised when a document is invalid, unsupported, or unsafe to render."""


@dataclass(frozen=True)
class ProcessedDocument:
    filename: str
    pages: list[VisionPage]
    source_type: str


def _safe_filename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if not name or name in {".", ".."}:
        raise DocumentProcessingError("The uploaded filename is invalid.")
    return name[:255]


def _process_image(content: bytes, suffix: str) -> VisionPage:
    if not content.startswith(b"\x89PNG\r\n\x1a\n") and suffix == ".png":
        raise DocumentProcessingError("The file extension does not match a PNG image.")
    if not content.startswith(b"\xff\xd8\xff") and suffix in {".jpg", ".jpeg"}:
        raise DocumentProcessingError("The file extension does not match a JPEG image.")

    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.format not in {"PNG", "JPEG"}:
                raise DocumentProcessingError("Only PNG and JPEG images are supported.")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise DocumentProcessingError("The image dimensions exceed the safe limit.")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise DocumentProcessingError("The uploaded image is invalid or unreadable.") from exc

    max_side = int(MAX_RENDER_PIXELS**0.5)
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True)
    return VisionPage(page_number=1, mime_type="image/jpeg", image_bytes=output.getvalue())


def _process_pdf(content: bytes, max_pages: int, render_dpi: int) -> list[VisionPage]:
    if not content.startswith(b"%PDF-"):
        raise DocumentProcessingError("The file extension does not match a PDF document.")

    try:
        document = fitz.open(stream=content, filetype="pdf")
    except (fitz.FileDataError, RuntimeError) as exc:
        raise DocumentProcessingError("The uploaded PDF is invalid or unreadable.") from exc

    with document:
        if document.is_encrypted:
            raise DocumentProcessingError("Password-protected PDF files are not supported.")
        if document.page_count == 0:
            raise DocumentProcessingError("The PDF contains no pages.")
        if document.page_count > max_pages:
            raise DocumentProcessingError(
                f"The PDF has {document.page_count} pages; the limit is {max_pages}."
            )

        pages = []
        base_scale = render_dpi / 72
        for index, page in enumerate(document, start=1):
            scale = base_scale
            estimated_pixels = page.rect.width * scale * page.rect.height * scale
            if estimated_pixels > MAX_RENDER_PIXELS:
                scale *= (MAX_RENDER_PIXELS / estimated_pixels) ** 0.5
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pages.append(
                VisionPage(
                    page_number=index,
                    mime_type="image/png",
                    image_bytes=pixmap.tobytes("png"),
                )
            )
        return pages


def process_document(
    content: bytes,
    filename: str,
    *,
    max_pages: int = 50,
    render_dpi: int = 150,
    max_file_bytes: int = 15 * 1024 * 1024,
) -> ProcessedDocument:
    """Validate and normalize a PNG, JPEG, or PDF into page images."""
    if not content:
        raise DocumentProcessingError("The uploaded document is empty.")
    if max_pages < 1:
        raise ValueError("max_pages must be at least one.")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be at least one.")
    if len(content) > max_file_bytes:
        raise DocumentProcessingError(
            f"The document exceeds the {max_file_bytes} byte size limit."
        )
    if render_dpi < 72 or render_dpi > 300:
        raise ValueError("render_dpi must be between 72 and 300.")

    safe_name = _safe_filename(filename)
    suffix = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if suffix == ".pdf":
        pages = _process_pdf(content, max_pages, render_dpi)
        source_type = "application/pdf"
    elif suffix in SUPPORTED_IMAGE_TYPES:
        pages = [_process_image(content, suffix)]
        source_type = SUPPORTED_IMAGE_TYPES[suffix]
    else:
        raise DocumentProcessingError("Supported document formats are PDF, PNG, JPG, and JPEG.")

    return ProcessedDocument(filename=safe_name, pages=pages, source_type=source_type)
