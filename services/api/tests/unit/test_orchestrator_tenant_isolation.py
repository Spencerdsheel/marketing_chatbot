"""MANDATORY multi-tenant isolation test for the orchestrator turn pipeline (S10.2).

Asserts every downstream call in ``answer_turn`` receives ``claims`` scoped to
the visitor's own tenant (including the new ``get_orchestrator_config`` and
``provider.classify``), and that a ``conversation_id`` belonging to another
tenant/visitor is invisible -> 404 CONVERSATION_NOT_FOUND, with classify,
retrieve_hybrid, and generate never reached.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from common.auth import AuthClaims, Role
from common.errors import NotFoundError

from api.llm.config_repository import LLMConfig
from api.llm.provider import Completion
from api.orchestrator.config_repository import OrchestratorConfig
from api.orchestrator.service import answer_turn
from api.rag.service import HybridMatch, HybridResult

_TENANT_A = "tenant-a"


def _claims_a(subject: str = "visitor-a") -> AuthClaims:
    return AuthClaims(subject=subject, role=Role.VISITOR, tenant_id=_TENANT_A)


def _config() -> LLMConfig:
    return LLMConfig(
        provider="anthropic", model="claude-opus-4-8", api_key="sk-test",
        embedding_model="nomic-embed-text",
    )


async def test_every_downstream_call_carries_tenant_a_claims() -> None:
    """A visitor of tenant A drives a turn -- every downstream call receives
    claims with tenant_id == tenant A, including get_orchestrator_config and
    provider.classify (called with tenant A's own model)."""
    get_llm_config = AsyncMock(return_value=_config())
    get_orchestrator_config = AsyncMock(
        return_value=OrchestratorConfig(answer_threshold=0.5, escalate_threshold=0.35)
    )
    create_conversation = AsyncMock(return_value="conv-a")
    get_message = AsyncMock(return_value=None)
    append_message = AsyncMock(return_value="msg-1")
    get_working_memory = AsyncMock(return_value={"summary": None, "summary_message_count": 0, "messages": []})
    retrieve_hybrid = AsyncMock(
        return_value=HybridResult(
            chunks=[
                HybridMatch(
                    doc_id="d1", chunk_id="c1", content="text", score=0.9,
                    rrf_score=0.5, matched_by=["vector"],
                )
            ],
            confidence=0.9,
        )
    )
    provider = AsyncMock()
    provider.classify = AsyncMock(return_value="question")
    provider.generate = AsyncMock(
        return_value=Completion(text="answer", model="claude-opus-4-8", input_tokens=1, output_tokens=1)
    )
    provider_for = lambda cfg: provider  # noqa: E731

    with (
        patch("api.orchestrator.service.get_llm_config", get_llm_config),
        patch("api.orchestrator.service.get_orchestrator_config", get_orchestrator_config),
        patch("api.orchestrator.service.create_conversation", create_conversation),
        patch("api.orchestrator.service.get_message", get_message),
        patch("api.orchestrator.service.append_message", append_message),
        patch("api.orchestrator.service.get_working_memory", get_working_memory),
        patch("api.orchestrator.service.retrieve_hybrid", retrieve_hybrid),
        patch("api.orchestrator.service.provider_for", provider_for),
    ):
        await answer_turn(db=object(), claims=_claims_a(), message="hello", message_id="turn-1")

    for mock in (
        get_llm_config,
        get_orchestrator_config,
        create_conversation,
        append_message,
        get_working_memory,
        retrieve_hybrid,
    ):
        for call in mock.await_args_list:
            claims_arg = call.args[1] if len(call.args) > 1 else call.kwargs.get("claims")
            assert claims_arg is not None
            assert claims_arg.tenant_id == _TENANT_A
            assert claims_arg.role == Role.VISITOR

    provider.classify.assert_awaited_once()
    assert provider.classify.await_args.kwargs["model"] == "claude-opus-4-8"


async def test_guardrail_block_still_carries_tenant_a_claims_scan_output_tenant_agnostic() -> None:
    """A guardrail block still carries tenant-A claims into append_message
    (the stored blocked turn is tenant-scoped), and scan_output receives
    ONLY the reply text -- never claims/tenant data (MANDATORY assertion)."""
    get_llm_config = AsyncMock(return_value=_config())
    get_orchestrator_config = AsyncMock(
        return_value=OrchestratorConfig(answer_threshold=0.5, escalate_threshold=0.35)
    )
    create_conversation = AsyncMock(return_value="conv-a")
    get_message = AsyncMock(return_value=None)
    append_message = AsyncMock(return_value="msg-1")
    get_working_memory = AsyncMock(return_value={"summary": None, "summary_message_count": 0, "messages": []})
    retrieve_hybrid = AsyncMock(
        return_value=HybridResult(
            chunks=[
                HybridMatch(
                    doc_id="d1", chunk_id="c1", content="text", score=0.9,
                    rrf_score=0.5, matched_by=["vector"],
                )
            ],
            confidence=0.9,
        )
    )
    provider = AsyncMock()
    provider.classify = AsyncMock(return_value="question")
    provider.generate = AsyncMock(
        return_value=Completion(
            text="i am a human", model="claude-opus-4-8", input_tokens=1, output_tokens=1,
        )
    )
    provider_for = lambda cfg: provider  # noqa: E731

    from api.orchestrator.guardrails import scan_output as real_scan_output

    with (
        patch("api.orchestrator.service.get_llm_config", get_llm_config),
        patch("api.orchestrator.service.get_orchestrator_config", get_orchestrator_config),
        patch("api.orchestrator.service.create_conversation", create_conversation),
        patch("api.orchestrator.service.get_message", get_message),
        patch("api.orchestrator.service.append_message", append_message),
        patch("api.orchestrator.service.get_working_memory", get_working_memory),
        patch("api.orchestrator.service.retrieve_hybrid", retrieve_hybrid),
        patch("api.orchestrator.service.provider_for", provider_for),
        patch("api.orchestrator.service.scan_output", wraps=real_scan_output) as spy_scan,
    ):
        await answer_turn(db=object(), claims=_claims_a(), message="hello", message_id="turn-1")

    # append_message (the guardrail_flag write) is tenant/visitor-scoped --
    # the assistant append call is the 2nd call.
    assistant_call = append_message.await_args_list[1]
    claims_arg = assistant_call.args[1] if len(assistant_call.args) > 1 else assistant_call.kwargs.get("claims")
    assert claims_arg is not None
    assert claims_arg.tenant_id == _TENANT_A
    assert assistant_call.kwargs["guardrail_flag"] == "human_impersonation"

    # scan_output is tenant-agnostic: called with ONLY the reply text -- no
    # claims/tenant_id/visitor_id ever passed to it.
    spy_scan.assert_called_once()
    call = spy_scan.call_args
    assert call.args == ("i am a human",)
    assert call.kwargs == {}
    for arg in call.args:
        assert not isinstance(arg, AuthClaims)


async def test_cross_tenant_conversation_id_invisible_404_no_classify_rag_or_generate() -> None:
    """A conversation_id belonging to another tenant/visitor is invisible ->
    the store raises NotFoundError -> 404 CONVERSATION_NOT_FOUND; classify,
    retrieve_hybrid, and generate are never reached."""
    get_llm_config = AsyncMock(return_value=_config())
    get_orchestrator_config = AsyncMock(
        return_value=OrchestratorConfig(answer_threshold=0.5, escalate_threshold=0.35)
    )
    create_conversation = AsyncMock(return_value="conv-a")
    get_message = AsyncMock(return_value=None)
    append_message = AsyncMock(
        side_effect=NotFoundError("Conversation not found.", code="CONVERSATION_NOT_FOUND"),
    )
    get_working_memory = AsyncMock()
    retrieve_hybrid = AsyncMock()
    provider = AsyncMock()
    provider.classify = AsyncMock()
    provider.generate = AsyncMock()
    provider_for = lambda cfg: provider  # noqa: E731

    with (
        patch("api.orchestrator.service.get_llm_config", get_llm_config),
        patch("api.orchestrator.service.get_orchestrator_config", get_orchestrator_config),
        patch("api.orchestrator.service.create_conversation", create_conversation),
        patch("api.orchestrator.service.get_message", get_message),
        patch("api.orchestrator.service.append_message", append_message),
        patch("api.orchestrator.service.get_working_memory", get_working_memory),
        patch("api.orchestrator.service.retrieve_hybrid", retrieve_hybrid),
        patch("api.orchestrator.service.provider_for", provider_for),
    ):
        with pytest.raises(NotFoundError) as exc_info:
            await answer_turn(
                db=object(), claims=_claims_a(), message="hello",
                conversation_id="conv-belongs-to-tenant-b",
            )

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"
    provider.classify.assert_not_awaited()
    retrieve_hybrid.assert_not_awaited()
    provider.generate.assert_not_awaited()
    get_working_memory.assert_not_awaited()
