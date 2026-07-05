"""Document parsers for the ingestion pipeline.

``parse(content_type, data)`` is the single entry point. It dispatches to a
per-format handler based on the MIME content type and returns the normalized
plain text. Unsupported types raise ``ValidationError`` (code
``UNSUPPORTED_CONTENT_TYPE``) — never silently return empty/fake text.

Supported content types (S5.2 scope):
- ``text/plain``      → UTF-8 decode (errors="replace") + whitespace normalization.
- docx MIME          → python-docx paragraph extraction, joined with newlines.

PDF + OCR are deferred to S5.2b.
"""
from __future__ import annotations

import re

from common.errors import ValidationError

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _parse_text_plain(data: bytes) -> str:
    """Decode bytes as UTF-8 (replacing undecodable sequences) and normalize whitespace.

    Normalization:
    - Collapse runs of horizontal whitespace (spaces/tabs) on each line.
    - Strip leading/trailing whitespace per line.
    - Collapse runs of blank lines to a single blank line.
    - Strip overall leading/trailing whitespace.
    """
    text = data.decode("utf-8", errors="replace")
    # Normalize line-internal whitespace.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Collapse consecutive blank lines.
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return normalized.strip()


def _parse_docx(data: bytes) -> str:
    """Extract paragraph text from a .docx file using python-docx.

    Joins non-empty paragraphs with newlines. An empty or invalid file
    raises ``ValidationError`` (``PARSE_ERROR``) rather than crashing silently.
    """
    import io  # noqa: PLC0415 — deferred to avoid import cost when not used

    try:
        from docx import Document  # noqa: PLC0415
    except ImportError as exc:
        raise ValidationError(
            "python-docx is required to parse .docx files but is not installed.",
            code="PARSE_ERROR",
        ) from exc

    try:
        doc = Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    except Exception as exc:
        raise ValidationError(
            f"Failed to parse docx document: {exc}",
            code="PARSE_ERROR",
        ) from exc

    return "\n".join(paragraphs)


def parse(content_type: str, data: bytes) -> str:
    """Dispatch to the correct parser for ``content_type`` and return normalized text.

    Parameters
    ----------
    content_type:
        The MIME type of the uploaded file (validated by the route before calling
        this function, but we re-check here to be safe).
    data:
        The raw file bytes.

    Returns
    -------
    str
        Normalized plain text. Never empty on a valid non-empty file (but an
        empty file may return an empty string — callers should record that).

    Raises
    ------
    ValidationError(code="UNSUPPORTED_CONTENT_TYPE")
        When ``content_type`` is not recognised by any parser.
    ValidationError(code="PARSE_ERROR")
        When the file bytes cannot be parsed by the declared type's handler.
    """
    # Strip parameters (e.g. "text/plain; charset=utf-8" → "text/plain").
    mime = content_type.split(";")[0].strip().lower()

    if mime == "text/plain":
        return _parse_text_plain(data)
    if mime == _DOCX_MIME:
        return _parse_docx(data)

    _supported = (
        "text/plain, "
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    raise ValidationError(
        f"Unsupported content type: {content_type!r}. Supported: {_supported}.",
        code="UNSUPPORTED_CONTENT_TYPE",
    )
