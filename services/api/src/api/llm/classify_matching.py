"""Shared label-matching and prompt-building helpers for ``LLMProvider.classify()``.

LLM replies to a classify prompt are usually the exact label, but small
models (and even production models, occasionally) reply with near-misses:
trailing punctuation, a pluralized label, or the label wrapped in a
sentence ("The label is: scheduling_request."). ``match_label`` recognizes
those near-misses WITHOUT weakening the contract -- it only ever returns one
of the caller-supplied ``labels`` (never a hallucinated string), and returns
``None`` when no tier produces a single unambiguous match so the caller can
still fail loud.

``build_classify_instruction`` builds the system instruction sent to the
provider ahead of the text to classify. Weak/small instruct-tuned models
have a strong bias toward being a "helpful conversational assistant" and
will sometimes ignore a mild classify instruction entirely -- replying
conversationally to the text instead of emitting a label (e.g. replying
"hello!" to a chitchat classification instead of the label ``chitchat``).
That failure mode produces a reply that is not a near-miss of any label, so
``match_label`` correctly finds no match and the caller fails loud -- but
the fix belongs upstream, in a prompt forceful enough to keep a weak model
on task. Both provider implementations share this builder so the prompt
stays identical across vendors.
"""
from __future__ import annotations

import re

_TRAILING_CHARS = " \t\r\n.!?"

# Generic, business-content-free few-shot examples used purely to demonstrate
# the required output SHAPE (single bare label, no extra text) to a weak
# model. Deliberately spread across several distinct example labels so the
# examples never bias the model toward one particular label, and use
# domain-agnostic categories unrelated to any real tenant's label set.
_FEWSHOT_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("Is it going to rain today?", "weather"),
    ("Who won the game last night?", "sports"),
    ("How do I bake sourdough bread?", "cooking"),
)


def build_classify_instruction(labels: list[str]) -> str:
    """Build the strict, non-conversational classify system instruction.

    Explicitly frames the model as a classification system (not a chat
    assistant), forbids engaging with the text's content, forbids any
    output beyond the bare label, and includes balanced few-shot examples
    illustrating the expected output shape.
    """
    labels_str = ", ".join(labels)
    examples = "\n".join(f'Input: "{text}"\nLabel: {label}' for text, label in _FEWSHOT_EXAMPLES)
    return (
        "You are a text classification system, not a conversational assistant. "
        "Your ONLY job is to read the text below and output exactly one label. "
        "Do NOT answer, respond to, or engage with the content of the text. "
        "Do NOT have a conversation with the user. Do NOT explain your reasoning. "
        "Output ONLY the single label -- no extra words, no punctuation, no preamble, "
        "no quotation marks.\n\n"
        f"The valid labels are: {labels_str}.\n\n"
        "Example format (using unrelated sample labels, illustrating output shape only):\n"
        f"{examples}\n\n"
        "Now classify the text that follows into exactly one of the valid labels listed "
        "above, following the same output format: reply with only the label, nothing else."
    )


def _exact_match(candidate: str, labels: list[str]) -> str | None:
    for label in labels:
        if candidate.lower() == label.lower():
            return label
    return None


def match_label(reply: str, labels: list[str]) -> str | None:
    """Match ``reply`` to exactly one of ``labels``, or return ``None``.

    Tries, in order, stopping at the first success:
      a. Exact match (case-insensitive).
      b. Exact match after stripping trailing punctuation/whitespace.
      c. Naive depluralization (strip one trailing 's') if it resolves to a
         UNIQUE label.
      d. Whole-word substring match, if exactly one label matches this way.

    Never returns a label that isn't in ``labels``. Never guesses when the
    match would be ambiguous.
    """
    if not labels:
        return None

    exact = _exact_match(reply, labels)
    if exact is not None:
        return exact

    stripped = reply.strip(_TRAILING_CHARS)
    if stripped != reply:
        stripped_match = _exact_match(stripped, labels)
        if stripped_match is not None:
            return stripped_match

    if stripped.endswith("s"):
        depluralized = stripped[:-1]
        candidates = {label for label in labels if depluralized.lower() == label.lower()}
        if len(candidates) == 1:
            return next(iter(candidates))

    substring_matches = {
        label
        for label in labels
        if re.search(rf"\b{re.escape(label)}\b", reply, re.IGNORECASE)
    }
    if len(substring_matches) == 1:
        return next(iter(substring_matches))

    return None
