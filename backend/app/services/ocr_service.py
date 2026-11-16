from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from app.providers.base import VisionPage


class OCRUnavailableError(Exception):
    """Raised when RapidOCR or its runtime dependencies are unavailable."""


@dataclass(frozen=True)
class OCRLine:
    text: str
    page_number: int
    bounding_box: list[float] | None
    confidence: float | None


class OCRService(Protocol):
    def extract(self, pages: list[VisionPage]) -> list[OCRLine]: ...


def _decode_page(page: VisionPage) -> Any:
    try:
        import numpy as np

        with Image.open(io.BytesIO(page.image_bytes)) as image:
            return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    except (ImportError, UnidentifiedImageError, OSError) as exc:
        raise OCRUnavailableError(
            "OCR requires a readable page image and the NumPy package."
        ) from exc


def _normalize_box(box: Any) -> list[float] | None:
    try:
        points = [[float(point[0]), float(point[1])] for point in box]
    except (TypeError, ValueError, IndexError):
        return None
    if not points or any(
        not all(value >= 0 and value < float("inf") for value in point)
        for point in points
    ):
        return None
    return [coordinate for point in points for coordinate in point]


def _make_line(text: Any, confidence: Any, box: Any, page_number: int) -> OCRLine:
    try:
        score = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        score = None
    if score is not None and not 0 <= score <= 1:
        score = None
    return OCRLine(
        text=str(text).strip() if text is not None else "",
        page_number=page_number,
        bounding_box=_normalize_box(box) if box is not None else None,
        confidence=score,
    )


@lru_cache(maxsize=1)
def _create_rapid_engine() -> Any:
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR(
            intra_op_num_threads=1,
            inter_op_num_threads=1,
            max_side_len=1600,
            use_cls=False,
        )
    except (
        ImportError,
        RuntimeError,
        TypeError,
        ValueError,
        OSError,
        AttributeError,
    ) as exc:
        raise OCRUnavailableError(
            "RapidOCR is unavailable. Install backend requirements and ensure its "
            "ONNX Runtime is supported on this machine."
        ) from exc


def parse_rapid_result(result: Any, page_number: int) -> list[OCRLine]:
    """Convert RapidOCR's detected text boxes into normalized OCR lines."""
    if isinstance(result, tuple) and len(result) == 2:
        result = result[0]
    if not isinstance(result, list):
        return []

    lines = []
    for entry in result:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        line = _make_line(entry[1], entry[2], entry[0], page_number)
        if line.text:
            lines.append(line)
    return lines


class RapidOCRService:
    def __init__(self, engine: Any | None = None) -> None:
        self._engine = engine

    @property
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = _create_rapid_engine()
        return self._engine

    def extract(self, pages: list[VisionPage]) -> list[OCRLine]:
        lines: list[OCRLine] = []
        for page in pages:
            image = _decode_page(page)
            try:
                raw_result = self.engine(image)
            except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as exc:
                raise OCRUnavailableError(
                    f"RapidOCR failed while reading document page {page.page_number}."
                ) from exc
            lines.extend(parse_rapid_result(raw_result, page.page_number))
        return lines
