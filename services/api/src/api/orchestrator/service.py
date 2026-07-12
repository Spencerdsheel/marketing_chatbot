"""Orchestrator turn pipeline -- the brain's judgement layer (S10.2).

``answer_turn`` composes the modules S2-S6 already shipped, plus S10.2's own
intent gate + 3-way decision, into one turn: resolve the tenant's LLM config,
resolve the tenant's orchestrator thresholds, get-or-create the conversation,
store the user turn, classify intent, branch on intent (chit-chat -> direct
answer, scheduling_request/off_topic -> escalate, question/other -> grounded
RAG + confidence-band decision), store the assistant turn, and return the
answer + decision + sources. No new RAG/LLM/store *mechanisms* -- this module
only composes their existing public functions, always with the caller's own
VISITOR ``claims``.

No silent fallback (CLAUDE.md §3): a misconfigured tenant fails before any
store write (decision 9); a runtime classify/RAG/LLM failure fails loud AFTER
the user turn is durably stored -- never a fabricated answer, never data
loss. The 3-way decision (``answer``/``clarify``/``escalate``) is a PURE
function of the closed-set intent label + the numeric confidence vs the
tenant's two thresholds -- no fuzzy LLM-decided branch selection. This
SUPERSEDES the S10.1 amendment's standalone ``orchestrator_confidence_floor``
short-circuit and ``_LOW_CONFIDENCE_REPLY`` -- "below floor" is now simply
``confidence < cfg.escalate_threshold`` inside the unified decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError

from api.config import get_api_settings
from api.conversation_store.repository import (
    append_message,
    create_conversation,
    get_message,
    get_working_memory,
)
from api.llm.config_repository import get_llm_config
from api.llm.factory import provider_for
from api.llm.provider import ChatMessage
from api.orchestrator.config_repository import OrchestratorConfig, get_orchestrator_config
from api.orchestrator.guardrails import scan_output
from api.rag.service import HybridMatch, retrieve_hybrid

Decision = Literal["answer", "clarify", "escalate", "blocked"]


@dataclass(frozen=True)
class Source:
    """A cited chunk, surfaced to the caller -- identifiers + score only."""

    doc_id: str
    chunk_id: str
    score: float | None
    matched_by: list[str]


@dataclass(frozen=True)
class TurnResult:
    """The outcome of one turn -- returned by ``answer_turn``.

    ``intent`` and ``guardrail_flag`` are carried for the route's PII-safe log
    line only (closed-set, non-PII labels) -- ``ChatMessageResponse`` does not
    surface them (decision 10/S10.3 decision 6: stored for analytics, not
    part of the public response). ``action`` (S10.3) IS surfaced -- it tells
    the widget whether to render the consent-gated lead form.
    """

    conversation_id: str
    message_id: str
    reply: str
    decision: str
    confidence: float | None
    sources: list[Source]
    intent: str | None = None
    action: str | None = None
    guardrail_flag: str | None = None


# -- Intent taxonomy (decision 1) -- a fixed, code-owned label set. Only the
# numeric thresholds are tenant-tunable; the taxonomy itself is not.
_INTENT_LABELS: list[str] = ["question", "chitchat", "scheduling_request", "off_topic", "other"]

_GROUNDING_SYSTEM_PROMPT = (
    "You are a helpful assistant for this business. Answer the user's "
    "question using ONLY the context provided below. If the context does "
    "not contain the answer, say you don't have that information -- do not "
    "invent facts, prices, or commitments."
)

_NO_CONTEXT_LINE = "(no relevant knowledge was found)"

# Chit-chat branch: a brief, ungrounded reply -- NO RAG context block. The
# model must not answer business-specific questions from this prompt; it
# should redirect the visitor to ask about the business instead.
_CHITCHAT_SYSTEM_PROMPT = (
    "Reply briefly and warmly. Do NOT answer business-specific questions or "
    "invent facts, prices, or commitments; if asked something specific, "
    "invite them to ask about the business."
)

# Fixed clarify template (decision 6) -- deterministic, cheap, no generate
# call; sidesteps the weak-model self-censor gap that motivated the S10.1
# amendment (we do not re-trust the model to gracefully decline).
_CLARIFY_REPLY = (
    "Could you tell me a bit more about what you're looking for? A few "
    "extra details will help me find the right answer."
)

# Fixed escalate template (decision 6) -- consent-forward (S10.3 decision 1):
# asks for consent BEFORE any contact detail is collected. The widget renders
# its already-consent-gated lead form on action="lead_form"; actual capture
# flows through POST /public/leads (S7.1), which enforces CONSENT_REQUIRED.
# S10.4 replaces/augments this with a real scheduling CTA + ensure-lead
# handoff.
_ESCALATE_REPLY = (
    "I'm not able to answer that confidently from what I know here. If "
    "you'd like someone to follow up, share your name and email below and "
    "confirm you're happy for us to contact you -- I'll pass it along."
)

# Fixed guardrail-block safe reply (S10.3 decision 4) -- substituted for a
# generated reply that trips scan_output. Never the flagged text; also
# consent-forward (same downstream UX as a genuine escalate -- offer a human,
# honestly).
_GUARDRAIL_SAFE_REPLY = (
    "Sorry, I can't help with that here. If you'd like, share your name and "
    "email below and confirm you're happy to be contacted, and I'll connect "
    "you with someone who can."
)

# Maps the store's role column ('user'|'bot'|'system') to the LLM provider's
# expected chat role ('user'|'assistant'|'system') -- the store never sends
# role="bot" to a provider (S4.1 decision 5 vs S10.1 decision 4).
_ROLE_MAP: dict[str, str] = {"user": "user", "bot": "assistant", "system": "system"}


def _decide(confidence: float, cfg: OrchestratorConfig) -> Decision:
    """The pure confidence-band function (decision 2) for the grounded path.

    ``confidence >= cfg.answer_threshold`` -> ``answer``;
    ``cfg.escalate_threshold <= confidence < cfg.answer_threshold`` ->
    ``clarify``; ``confidence < cfg.escalate_threshold`` -> ``escalate``.
    When ``cfg.escalate_threshold == cfg.answer_threshold`` the clarify band
    collapses -- only ``answer``/``escalate`` are ever returned.
    """
    if confidence >= cfg.answer_threshold:
        return "answer"
    if confidence >= cfg.escalate_threshold:
        return "clarify"
    return "escalate"


def _build_prompt(wm: dict[str, Any], chunks: list[HybridMatch]) -> list[ChatMessage]:
    """Build ``[system, ...history]`` for the grounded ``generate`` call.

    The system message carries the grounding instruction, a context block
    (one ``[{chunk_id}] {content}`` line per chunk, or the literal
    "no relevant knowledge was found" line when ``chunks`` is empty), and an
    optional "Conversation summary so far" section. The remaining messages
    are ``wm["messages"]`` role-mapped via ``_ROLE_MAP`` -- the last one is
    the current question (already appended to the store), so it is not
    re-appended separately.
    """
    if chunks:
        context_block = "\n".join(f"[{c.chunk_id}] {c.content}" for c in chunks)
    else:
        context_block = _NO_CONTEXT_LINE

    system_parts = [_GROUNDING_SYSTEM_PROMPT, "", "Context:", context_block]
    summary = wm.get("summary")
    if summary:
        system_parts.append("")
        system_parts.append(f"Conversation summary so far: {summary}")

    prompt = [ChatMessage(role="system", content="\n".join(system_parts))]
    for m in wm["messages"]:
        prompt.append(ChatMessage(role=_ROLE_MAP.get(m.role, m.role), content=m.content))
    return prompt


def _build_chitchat_prompt(wm: dict[str, Any]) -> list[ChatMessage]:
    """Build ``[system, ...history]`` for the chit-chat ``generate`` call --
    no RAG context block, a dedicated brief/warm system prompt."""
    prompt = [ChatMessage(role="system", content=_CHITCHAT_SYSTEM_PROMPT)]
    for m in wm["messages"]:
        prompt.append(ChatMessage(role=_ROLE_MAP.get(m.role, m.role), content=m.content))
    return prompt


def _sources_from_chunks(chunks: list[HybridMatch]) -> list[Source]:
    return [
        Source(doc_id=c.doc_id, chunk_id=c.chunk_id, score=c.score, matched_by=c.matched_by)
        for c in chunks
    ]


def _sources_to_payload(sources: list[Source]) -> list[dict[str, Any]]:
    return [
        {
            "doc_id": s.doc_id,
            "chunk_id": s.chunk_id,
            "score": s.score,
            "matched_by": s.matched_by,
        }
        for s in sources
    ]


async def answer_turn(
    db: Database,
    claims: AuthClaims,
    *,
    message: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
) -> TurnResult:
    """Run one visitor turn end-to-end (decision 8, the extended pipeline).

    Every downstream call carries ``claims`` (the caller's own VISITOR
    session) -- cross-tenant/cross-visitor context is impossible.

    Raises
    ------
    ValidationError (``LLM_NOT_CONFIGURED``)
        No LLM config for this tenant -- raised BEFORE any store write.
    ValidationError (``RAG_EMBEDDING_NOT_CONFIGURED``)
        Propagates from ``retrieve_hybrid`` -- AFTER the user turn is stored.
    NotFoundError (``CONVERSATION_NOT_FOUND``)
        A supplied ``conversation_id`` is not visible to this visitor.
    LLMError
        Propagates untouched from ``classify``, ``embed`` (via
        ``retrieve_hybrid``), or ``generate`` -- the user turn is preserved;
        the assistant turn is never written on a failed completion.
    """
    settings = get_api_settings()

    # Step 1: resolve the tenant's LLM config up front -- fail fast BEFORE
    # any store write (deterministic misconfiguration).
    config = await get_llm_config(db, claims)
    if config is None:
        raise ValidationError(
            "LLM is not configured for this tenant.",
            code="LLM_NOT_CONFIGURED",
        )

    # Step 2: resolve the tenant's orchestrator thresholds -- read-only,
    # tenant-scoped, no side effects. Never None (get-or-default).
    cfg = await get_orchestrator_config(db, claims)

    # Step 3: get-or-create the conversation.
    client_supplied_conversation_id = conversation_id is not None
    if conversation_id is None:
        conversation_id = await create_conversation(db, claims)

    # Step 4: turn-idempotency replay check -- only when the CLIENT supplied
    # BOTH message_id and conversation_id (a first-turn retry can't dedup;
    # the client never received the server-generated conversation_id yet).
    # On a hit, classify/retrieve_hybrid/generate are ALL skipped and the
    # stored decision/reply/confidence/sources are returned verbatim.
    assistant_id: str | None = None
    if message_id is not None:
        assistant_id = f"{message_id}-a"
        if client_supplied_conversation_id:
            existing = await get_message(db, claims, conversation_id, assistant_id)
            if existing is not None:
                existing_decision = existing.decision or "answer"
                return TurnResult(
                    conversation_id=conversation_id,
                    message_id=existing.message_id,
                    reply=existing.content,
                    decision=existing_decision,
                    confidence=existing.confidence,
                    sources=[Source(**s) for s in (existing.sources or [])],
                    intent=existing.intent,
                    action="lead_form" if existing_decision in ("escalate", "blocked") else None,
                    guardrail_flag=existing.guardrail_flag,
                )

    # Step 5: store the user turn BEFORE classify/RAG/LLM -- idempotent
    # (ON CONFLICT DO NOTHING); a later 5xx never loses the visitor's message.
    await append_message(
        db, claims, conversation_id, role="user", content=message, message_id=message_id,
    )

    provider = provider_for(config)

    # Step 6: classify intent -- runs AFTER the user turn is durably stored,
    # so a classify failure never loses the visitor's message. On LLMError
    # this propagates untouched -> LLM_ERROR 502 (decision 9, fail-loud,
    # same class of failure as generate).
    intent = await provider.classify(message, _INTENT_LABELS, model=config.model)

    # Step 7: branch on intent -> decision -> reply (decisions 2 + 6).
    guardrail_flag: str | None = None
    action: str | None = None

    if intent == "chitchat":
        wm = await get_working_memory(
            db, claims, conversation_id, keep_recent=settings.orchestrator_history_turns,
        )
        prompt = _build_chitchat_prompt(wm)
        completion = await provider.generate(
            prompt, model=config.model, max_tokens=settings.llm_max_tokens,
        )
        reply = completion.text
        decision: Decision = "answer"
        confidence: float | None = None
        grounded = False
        sources: list[Source] = []
        tokens: int | None = completion.output_tokens

        # S10.3 decision 4: scan the generated reply before it can be stored
        # or returned -- ONLY the two generate branches are scanned.
        guardrail = scan_output(reply)
        if not guardrail.ok:
            reply = _GUARDRAIL_SAFE_REPLY
            decision = "blocked"
            action = "lead_form"
            grounded = False
            sources = []
            guardrail_flag = guardrail.rule
            # confidence/tokens keep their real values (chitchat never runs
            # RAG, so confidence stays None; tokens reflects the real,
            # actually-incurred generation cost).

    elif intent in ("scheduling_request", "off_topic"):
        # No RAG, no generate -- a fixed, honest, trusted-constant reply.
        # Fixed-template branches are never scanned (decision 4).
        reply = _ESCALATE_REPLY
        decision = "escalate"
        confidence = None
        grounded = False
        sources = []
        tokens = None
        action = "lead_form"

    else:  # "question" | "other" -- the grounded path.
        result = await retrieve_hybrid(db, claims, message, k=settings.orchestrator_rag_k)
        confidence = result.confidence
        decision = _decide(confidence, cfg)

        if decision == "answer":
            wm = await get_working_memory(
                db, claims, conversation_id, keep_recent=settings.orchestrator_history_turns,
            )
            prompt = _build_prompt(wm, result.chunks)
            completion = await provider.generate(
                prompt, model=config.model, max_tokens=settings.llm_max_tokens,
            )
            reply = completion.text
            grounded = True
            sources = _sources_from_chunks(result.chunks)
            tokens = completion.output_tokens

            # S10.3 decision 4: scan the generated reply before storing/
            # returning it. On a violation the retrieval confidence stays
            # real (analytics still sees the true confidence that produced
            # the flagged generation) but the reply/decision/action/grounded/
            # sources all degrade to the safe, honest fallback.
            guardrail = scan_output(reply)
            if not guardrail.ok:
                reply = _GUARDRAIL_SAFE_REPLY
                decision = "blocked"
                action = "lead_form"
                grounded = False
                sources = []
                guardrail_flag = guardrail.rule
        elif decision == "clarify":
            # Fixed-template branch -- our own trusted constant, never scanned.
            reply = _CLARIFY_REPLY
            grounded = False
            sources = []
            tokens = None
        else:  # escalate (sub-floor confidence)
            # Fixed-template branch -- our own trusted constant, never scanned.
            reply = _ESCALATE_REPLY
            grounded = False
            sources = []
            tokens = None
            action = "lead_form"

    # Step 8: store the assistant turn + return. Reached only on a real
    # completion for the generate branches; the fixed-template branches
    # always store a real (non-fabricated) reply. The flagged/violating text
    # (if any) was already discarded above -- never stored, never returned.
    stored_message_id = await append_message(
        db,
        claims,
        conversation_id,
        role="bot",
        content=reply,
        intent=intent,
        decision=decision,
        grounded=grounded,
        confidence=confidence,
        tokens=tokens,
        message_id=assistant_id,
        sources=_sources_to_payload(sources),
        guardrail_flag=guardrail_flag,
    )

    return TurnResult(
        conversation_id=conversation_id,
        message_id=stored_message_id,
        reply=reply,
        decision=decision,
        confidence=confidence,
        sources=sources,
        intent=intent,
        action=action,
        guardrail_flag=guardrail_flag,
    )
