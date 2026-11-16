from __future__ import annotations

import mimetypes
import os
import tempfile
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from app.config import Settings


class DocumentStorageError(RuntimeError):
    pass


class StoredDocumentNotFoundError(DocumentStorageError):
    pass


def _validate_stored_filename(filename: str) -> None:
    if (
        not filename
        or filename in {".", ".."}
        or PurePosixPath(filename).name != filename
        or PureWindowsPath(filename).name != filename
    ):
        raise DocumentStorageError("Stored document name is invalid.")


def _local_document_path(filename: str, settings: Settings) -> Path:
    _validate_stored_filename(filename)
    storage_dir = Path(settings.storage_dir).resolve()
    path = (storage_dir / filename).resolve()
    if path.parent != storage_dir:
        raise DocumentStorageError("Stored document path is invalid.")
    return path


def _supabase_credentials(settings: Settings) -> tuple[str, str, str]:
    url = settings.supabase_url
    key: SecretStr | None = settings.supabase_service_role_key
    bucket = settings.supabase_storage_bucket
    if not url or not key or not key.get_secret_value().strip() or not bucket:
        raise DocumentStorageError(
            "Supabase Storage is selected but its URL, service role key, or bucket is missing."
        )
    return url.strip().rstrip("/"), key.get_secret_value().strip(), bucket.strip()


def _supabase_object_url(settings: Settings, filename: str) -> tuple[str, dict[str, str]]:
    _validate_stored_filename(filename)
    url, key, bucket = _supabase_credentials(settings)
    object_url = (
        f"{url}/storage/v1/object/{quote(bucket, safe='')}/{quote(filename, safe='')}"
    )
    return object_url, {"apikey": key, "Authorization": f"Bearer {key}"}


def _supabase_request(
    settings: Settings,
    method: str,
    filename: str,
    *,
    content: bytes | None = None,
) -> httpx.Response:
    url, headers = _supabase_object_url(settings, filename)
    if method == "POST":
        headers["Content-Type"] = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        headers["x-upsert"] = "true"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(method, url, headers=headers, content=content)
    except httpx.HTTPError as exc:
        raise DocumentStorageError("Could not reach Supabase Storage.") from exc

    if method == "GET" and response.status_code == 404:
        raise StoredDocumentNotFoundError("Stored invoice document was not found.")
    if not 200 <= response.status_code < 300:
        raise DocumentStorageError(
            f"Supabase Storage request failed (HTTP {response.status_code})."
        )
    return response


def store_document(content: bytes, filename: str, settings: Settings) -> str:
    suffix = Path(filename).suffix.lower()
    stored_filename = f"{uuid.uuid4().hex}{suffix}"
    if settings.storage_backend == "supabase":
        _supabase_request(settings, "POST", stored_filename, content=content)
        return stored_filename

    destination = _local_document_path(stored_filename, settings)
    temporary_path: str | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".upload-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    except OSError as exc:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise DocumentStorageError("Could not store the uploaded invoice.") from exc
    return stored_filename


def read_document(filename: str, settings: Settings) -> bytes:
    if settings.storage_backend == "supabase":
        return _supabase_request(settings, "GET", filename).content

    path = _local_document_path(filename, settings)
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise StoredDocumentNotFoundError("Stored invoice document was not found.") from exc
    except OSError as exc:
        raise DocumentStorageError("Could not read the stored invoice document.") from exc


def delete_document(filename: str, settings: Settings) -> None:
    if settings.storage_backend == "supabase":
        url, headers = _supabase_object_url(settings, filename)
        bucket_url = url.rsplit("/", 1)[0]
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    "DELETE",
                    bucket_url,
                    headers={**headers, "Content-Type": "application/json"},
                    json={"prefixes": [filename]},
                )
        except httpx.HTTPError as exc:
            raise DocumentStorageError("Could not reach Supabase Storage.") from exc
        if not 200 <= response.status_code < 300:
            raise DocumentStorageError(
                f"Supabase Storage request failed (HTTP {response.status_code})."
            )
        return

    path = _local_document_path(filename, settings)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise DocumentStorageError("Could not remove the stored invoice document.") from exc
