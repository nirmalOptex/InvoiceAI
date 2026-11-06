from __future__ import annotations

import base64
from typing import Any

import httpx

from app.providers.base import ProviderError, VisionPage
from app.providers.gemini import extraction_prompt
from app.providers.json_response import parse_json_response

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeVisionProvider:
    name = "claude"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        timeout_seconds: int = 90,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def extract(
        self, pages: list[VisionPage], ocr_text: str
    ) -> dict[str, Any]:
        if not pages:
            raise ProviderError("At least one rendered document page is required.")
        content: list[dict[str, Any]] = [
            {"type": "text", "text": extraction_prompt(ocr_text)}
        ]
        for page in pages:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": page.mime_type,
                        "data": base64.b64encode(page.image_bytes).decode("ascii"),
                    },
                }
            )
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": content}],
        }

        try:
            response = httpx.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("Claude request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"Claude returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError("Could not connect to Claude.") from exc

        try:
            body = response.json()
            blocks = body["content"]
            text = "\n".join(
                block["text"]
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("Claude returned an incomplete extraction response.") from exc
        if not text.strip():
            raise ProviderError("Claude returned an empty extraction response.")
        return parse_json_response(text)
