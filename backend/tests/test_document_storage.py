from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.database import normalize_database_url
from app.services import document_storage
from app.services.document_storage import (
    DocumentStorageError,
    StoredDocumentNotFoundError,
    delete_document,
    read_document,
    store_document,
)


def _supabase_settings() -> Settings:
    return Settings(
        storage_backend="supabase",
        supabase_url="https://invoiceiq-test.supabase.co",
        supabase_service_role_key="test-service-role-key",
    )


def test_supabase_storage_document_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"\x89PNG\r\n\x1a\nexample"
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=content)
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.Client
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        document_storage.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    settings = _supabase_settings()
    filename = store_document(content, "invoice.png", settings)
    assert filename.endswith(".png")
    assert read_document(filename, settings) == content
    delete_document(filename, settings)

    assert [request.method for request in requests] == ["POST", "GET", "DELETE"]
    assert all(
        request.headers["authorization"] == "Bearer test-service-role-key"
        and request.headers["apikey"] == "test-service-role-key"
        for request in requests
    )
    assert requests[0].headers["content-type"] == "image/png"
    assert requests[0].content == content
    assert requests[2].url.path.endswith("/storage/v1/object/invoice-documents")
    assert json.loads(requests[2].content) == {"prefixes": [filename]}


def test_supabase_storage_maps_missing_objects_and_rejects_unsafe_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404)
    )
    monkeypatch.setattr(
        document_storage.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    settings = _supabase_settings()

    with pytest.raises(StoredDocumentNotFoundError):
        read_document("missing.png", settings)
    with pytest.raises(DocumentStorageError, match="name is invalid"):
        read_document("../private.png", settings)


def test_supabase_storage_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_SERVICE_ROLE_KEY"):
        Settings(storage_backend="supabase", supabase_url="https://example.supabase.co")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql://user:pass@db.example.test/postgres",
            "postgresql+psycopg://user:pass@db.example.test/postgres",
        ),
        (
            "postgres://user:pass@db.example.test/postgres",
            "postgresql+psycopg://user:pass@db.example.test/postgres",
        ),
        ("sqlite:///./invoiceiq.db", "sqlite:///./invoiceiq.db"),
    ],
)
def test_database_url_supports_supabase_postgres_urls(url: str, expected: str) -> None:
    assert normalize_database_url(url) == expected
