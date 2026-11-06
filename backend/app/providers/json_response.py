import json
import re
from typing import Any

from app.providers.base import ProviderError


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.I | re.S)
    if fenced:
        cleaned = fenced.group(1)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError("The vision provider returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise ProviderError("The vision provider response must be a JSON object.")
    return result
