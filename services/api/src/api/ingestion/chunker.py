"""Sentence-aware deterministic text chunker.

``chunk_text(text, *, max_chars, overlap)`` splits *text* into a list of strings
where:

- Each chunk is at most *max_chars* characters long (except when a single token
  longer than *max_chars* is encountered — it is hard-split, never dropped).
- The last *overlap* characters of chunk N are prepended to chunk N+1 (trailing
  context window so downstream embedding models see sentence-boundary context).
- Splitting prefers sentence boundaries (``re`` sentence-end detection). When a
  sentence fits entirely in the remaining budget, it is packed into the current
  chunk; when it would overflow, the current chunk is emitted first.
- Empty / whitespace-only input returns ``[]`` (no error, no fabricated content).
- The function is **pure and deterministic**: identical input always yields
  identical output, so re-ingesting the same document is stable.

This module has **no database or I/O side effects**.  It is intentionally
dependency-free (stdlib only) so it can be tested without any infrastructure.
"""
from __future__ import annotations

import re

# Sentence-boundary split pattern.
# We match on ". " / "! " / "? " sequences (punctuation followed by whitespace),
# consuming the whitespace in the split (re.split drops the matched separator).
# Two patterns cover plain endings and quote-terminated endings:
#   r'(?<=[.!?])\s+'          — e.g. "dog. Next"
#   r'(?<=[.!?]["\'])\s+'     — e.g. 'said." Next'
# Python's fixed-width lookbehind disallows alternation with different widths
# inside ONE lookbehind, so we use a compiled alternation at match level instead.
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?]["\'])\s+')


def chunk_text(text: str, *, max_chars: int, overlap: int) -> list[str]:
    """Split *text* into overlapping sentence-aware chunks.

    Parameters
    ----------
    text:
        Input text to chunk.  Empty / whitespace-only → ``[]``.
    max_chars:
        Maximum characters per chunk.  A sentence that is itself longer than
        *max_chars* is hard-split at exactly *max_chars* boundaries.
    overlap:
        Number of trailing characters from the previous chunk prepended to the
        next chunk (trailing context).  ``0`` → no overlap.

    Returns
    -------
    list[str]
        Ordered list of chunk strings.  Content is never dropped.
    """
    if not text or not text.strip():
        return []

    # Split on sentence boundaries; keep the terminating punctuation in the
    # preceding segment by using lookbehind assertions.
    sentences = _split_sentences(text.strip())

    chunks: list[str] = []
    # `current` is the text accumulated into the chunk being built.
    # `budget` is how many chars are still available in `current`.
    current = ""

    def _emit() -> None:
        """Flush `current` as a completed chunk."""
        nonlocal current
        if current.strip():
            chunks.append(current)
        current = ""

    def _start_next(prev_chunk: str) -> None:
        """Start a new accumulator seeded with the overlap tail of *prev_chunk*."""
        nonlocal current
        if overlap > 0 and prev_chunk:
            tail = prev_chunk[-overlap:]
            current = tail
        else:
            current = ""

    for sentence in sentences:
        # A single sentence that already exceeds max_chars must be hard-split
        # into max_chars pieces before we pack them.
        pieces = _hard_split(sentence, max_chars) if len(sentence) > max_chars else [sentence]

        for piece in pieces:
            separator = " " if current else ""
            candidate = current + separator + piece

            if len(candidate) <= max_chars:
                current = candidate
            else:
                # Emit whatever we have so far, then start fresh with overlap.
                prev = current
                _emit()
                _start_next(prev)

                # Now try to fit the piece into the new (overlap-seeded) current.
                separator2 = " " if current else ""
                candidate2 = current + separator2 + piece
                if len(candidate2) <= max_chars:
                    current = candidate2
                else:
                    # Even with just the overlap prefix + piece it's too long.
                    # Hard-split the piece into max_chars windows, carrying the
                    # overlap prefix only for the very first sub-piece.
                    prefix = current
                    sub_pieces = _hard_split(piece, max_chars)
                    for j, sp in enumerate(sub_pieces):
                        if j == 0 and prefix:
                            sep = " " if prefix else ""
                            combined = prefix + sep + sp
                            if len(combined) <= max_chars:
                                current = combined
                            else:
                                # prefix alone too long or combined too long → emit prefix first
                                prev2 = prefix
                                if prev2.strip():
                                    chunks.append(prev2)
                                current = sp
                        else:
                            sep = " " if current else ""
                            cand = current + sep + sp
                            if len(cand) <= max_chars:
                                current = cand
                            else:
                                prev3 = current
                                _emit()
                                _start_next(prev3)
                                sep2 = " " if current else ""
                                current = (current + sep2 + sp).lstrip()

    if current.strip():
        chunks.append(current)

    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split *text* on sentence boundaries, returning non-empty sentence strings."""
    parts = _SENTENCE_END_RE.split(text)
    return [p for p in parts if p.strip()]


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Split *text* into pieces of at most *max_chars* characters.

    Prefers splitting at whitespace boundaries to avoid cutting mid-word when
    possible; falls back to hard character splits for content with no spaces.
    """
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        # Try to find the last space within the budget.
        window = remaining[:max_chars]
        cut = window.rfind(" ")
        if cut > 0:
            pieces.append(remaining[:cut])
            remaining = remaining[cut + 1:]
        else:
            # No space found — hard cut at exactly max_chars.
            pieces.append(remaining[:max_chars])
            remaining = remaining[max_chars:]
    if remaining.strip():
        pieces.append(remaining)
    return pieces
