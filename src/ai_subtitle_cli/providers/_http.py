"""Minimal HTTP helpers shared by the transcription providers.

Kept dependency-free (standard library only) so the CLI needs no third-party
packages to make multipart uploads.
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path


def build_multipart_body(
    fields: list[tuple[str, str]],
    file_field: str,
    file_path: Path,
) -> tuple[bytes, str]:
    """Build a ``multipart/form-data`` body and its ``Content-Type`` header.

    ``fields`` are simple text form fields; ``file_field`` is the form field
    name under which ``file_path`` is uploaded.
    """
    boundary = f"ai-subtitle-{os.urandom(12).hex()}"
    chunks: list[bytes] = []

    for name, value in fields:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")

    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))

    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def extract_error_message(body_text: str) -> str:
    """Pull a human-readable message out of a provider error response body."""
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text.strip()
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return body_text.strip()
