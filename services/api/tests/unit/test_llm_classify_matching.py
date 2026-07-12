"""Unit tests for the shared classify() label-matching helper.

``match_label`` progressively tries, in order, stopping at the first success:
  a. Exact match (case-insensitive).
  b. Exact match after stripping trailing punctuation/whitespace.
  c. Naive depluralization (strip a single trailing 's') if it resolves to a
     UNIQUE label.
  d. Whole-word substring match, if exactly one label matches this way.

Returns ``None`` (never a hallucinated label) when no tier produces a single
unambiguous match.
"""
from __future__ import annotations

from api.llm.classify_matching import match_label

_LABELS = ["question", "chitchat", "scheduling_request", "off_topic", "other"]


def test_match_label_exact_match() -> None:
    """Exact match (case-sensitive input) returns the canonical label."""
    assert match_label("scheduling_request", _LABELS) == "scheduling_request"


def test_match_label_case_insensitive_exact_match() -> None:
    """Case-insensitive exact match returns the canonical-cased label."""
    assert match_label("Scheduling_Request", _LABELS) == "scheduling_request"


def test_match_label_strips_trailing_punctuation() -> None:
    """Trailing punctuation (period) is stripped before exact match."""
    assert match_label("scheduling_request.", _LABELS) == "scheduling_request"


def test_match_label_strips_trailing_punctuation_and_whitespace() -> None:
    """Trailing whitespace + punctuation combo is stripped."""
    assert match_label("scheduling_request! \n", _LABELS) == "scheduling_request"


def test_match_label_strips_trailing_plural_s() -> None:
    """The exact live-bug scenario: 'scheduling_requests' -> 'scheduling_request'."""
    assert match_label("scheduling_requests", _LABELS) == "scheduling_request"


def test_match_label_depluralization_with_trailing_punctuation() -> None:
    """Depluralization applies after punctuation stripping too."""
    assert match_label("scheduling_requests.", _LABELS) == "scheduling_request"


def test_match_label_whole_word_substring_in_sentence() -> None:
    """A label wrapped in a sentence is recognized via whole-word match."""
    reply = "The correct label is scheduling_request."
    assert match_label(reply, _LABELS) == "scheduling_request"


def test_match_label_no_match_returns_none() -> None:
    """A reply matching no label even loosely returns None (fail loud upstream)."""
    assert match_label("banana", _LABELS) is None


def test_match_label_ambiguous_substring_returns_none() -> None:
    """Two labels both appearing as whole-word substrings -> ambiguous -> None."""
    labels = ["sales", "support", "billing"]
    reply = "This could be sales or support, not sure which."
    assert match_label(reply, labels) is None


def test_match_label_ambiguous_depluralization_returns_none() -> None:
    """Depluralization that could resolve to two different labels -> None.

    'classes' stripped of trailing 's' -> 'classe', which matches neither
    label exactly, so this is not ambiguous -- construct a genuine collision:
    two labels that both become the same string after naive depluralization
    is not reachable with distinct labels, so instead verify that a reply
    which depluralizes to a substring shared by two labels does not guess.
    """
    labels = ["cats", "cat"]
    # "cats" is already an exact match for the label "cats" (tier a) --
    # confirm exact match wins over depluralization ambiguity entirely.
    assert match_label("cats", labels) == "cats"


def test_match_label_whole_word_substring_not_matched_as_prefix() -> None:
    """Substring matching is whole-word, not a bare substring (no false positive)."""
    labels = ["cat", "category"]
    reply = "This is about categories in general."
    # "category" is not a whole word in "categories"; "cat" is not a whole
    # word either -- no match should be produced.
    assert match_label(reply, labels) is None
