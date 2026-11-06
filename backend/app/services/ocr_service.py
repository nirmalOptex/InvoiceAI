from __future__ import annotations

import io
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from app.providers.base import VisionPage


class OCRUnavailableError(Exception):
    """Raised when PaddleOCR or its runtime dependencies are unavailable."""


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


def parse_paddle_result(result: Any, page_number: int) -> list[OCRLine]:
    """Normalize legacy PaddleOCR tuples and PaddleOCR 3.x result dictionaries."""
    if result is None:
        return []
    if (
        isinstance(result, list)
        and len(result) == 1
        and isinstance(result[0], list)
        and result[0]
        and isinstance(result[0][0], (list, tuple))
        and len(result[0][0]) >= 2
        and isinstance(result[0][0][1], (list, tuple))
    ):
        result = result[0]

    if isinstance(result, dict):
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        boxes = result.get("rec_polys", result.get("dt_polys", []))
        lines = []
        for index, text in enumerate(texts):
            score = scores[index] if index < len(scores) else None
            box = boxes[index] if index < len(boxes) else None
            lines.append(_make_line(text, score, box, page_number))
        return [line for line in lines if line.text]

    if hasattr(result, "json"):
        serialized = result.json
        if callable(serialized):
            serialized = serialized()
        if isinstance(serialized, str):
            try:
                serialized = json.loads(serialized)
            except json.JSONDecodeError:
                return []
        if isinstance(serialized, dict):
            return parse_paddle_result(serialized.get("res", serialized), page_number)

    lines = []
    if not isinstance(result, list):
        return lines
    for entry in result:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        recognized = entry[1]
        if not isinstance(recognized, (list, tuple)) or not recognized:
            continue
        text = recognized[0]
        confidence = recognized[1] if len(recognized) > 1 else None
        line = _make_line(text, confidence, entry[0], page_number)
        if line.text:
            lines.append(line)
    return lines


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
def _create_paddle_engine() -> Any:
    try:
        from paddleocr import PaddleOCR

        return PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    except (
        ImportError,
        RuntimeError,
        TypeError,
        ValueError,
        OSError,
        AttributeError,
    ) as exc:
        raise OCRUnavailableError(
            "PaddleOCR is unavailable. Install backend requirements and ensure its "
            "PaddlePaddle runtime is supported on this machine."
        ) from exc


class PaddleOCRService:
    def __init__(self, engine: Any | None = None) -> None:
        self._engine = engine

    @property
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = _create_paddle_engine()
        return self._engine

    def extract(self, pages: list[VisionPage]) -> list[OCRLine]:
        lines: list[OCRLine] = []
        for page in pages:
            image = _decode_page(page)
            try:
                if hasattr(self.engine, "ocr"):
                    raw_result = self.engine.ocr(image, cls=True)
                else:
                    raw_result = self.engine.predict(image)
            except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as exc:
                raise OCRUnavailableError(
                    f"OCR failed while reading document page {page.page_number}."
                ) from exc
            lines.extend(parse_paddle_result(raw_result, page.page_number))
        return lines
