"""Independent approval generations, synthetic tickets, and exact retry identity."""

import asyncio
from dataclasses import replace
from hashlib import sha256
from threading import Event
from uuid import UUID, uuid4

import pytest

from industrial_ai_agent.application.action_approval import (
    MaintenanceTicketApprovalClaim,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.action_approval import (
    AgentRunStoreActionApprovalPort,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability

MODEL_ACTION_ID = "reused-model-call"
CONTEXT = SecurityContext(
    "synthetic-c06", ("test",), DataClassification.CONFIDENTIAL, True
)


def _proposal(station="S04", summary="Synthetic first action"):
    return {
        "action": "create_maintenance_ticket",
        "action_id": MODEL_ACTION_ID,
        "arguments": {"station_id": station, "summary": summary},
    }


async def _approve(
    store, run_id, station="S04", summary="Synthetic first action", **kwargs
):
    pending = await store.wait_for_approval(
        run_id, _proposal(station, summary), **kwargs
    )
    assert (
        await store.claim_resume(
            run_id,
            approval_execution_id=UUID(
                (await store.get(run_id)).approval_request["approval_execution_id"]
            ),
            decision="approve",
            approval_clearance=DataClassification.CONFIDENTIAL,
        )
        is not None
    )
    return pending.approval_request["approval_execution_id"]


def test_same_run_reused_model_action_id_does_not_alias_independent_approvals():
    async def verify():
        run_id = uuid4()
        store = InMemoryAgentRunStore()
        await store.create(run_id)
        repository = InMemoryMaintenanceTicketRepository()
        capability = MaintenanceTicketCapability(
            repository, approval_claims=AgentRunStoreActionApprovalPort(lambda _: store)
        )
        results = []
        for station, summary in (
            ("S04", "Synthetic first action"),
            ("S02", "Synthetic second action"),
        ):
            pending = await store.wait_for_approval(run_id, _proposal(station, summary))
            assert (
                await store.claim_resume(
                    run_id,
                    approval_execution_id=UUID(
                        (await store.get(run_id)).approval_request[
                            "approval_execution_id"
                        ]
                    ),
                    decision="approve",
                    approval_clearance=DataClassification.CONFIDENTIAL,
                )
                is not None
            )
            # Retain the original execution path solely for the pre-fix reproduction.
            execution_id = pending.approval_request.get(
                "approval_execution_id", MODEL_ACTION_ID
            )
            results.append(
                await capability.create_maintenance_ticket(
                    execution_id,
                    station,
                    summary,
                    run_id=run_id,
                    security_context=CONTEXT,
                )
            )
        assert results[0].ticket_id != results[1].ticket_id
        assert [result.station_id for result in results] == ["S04", "S02"]
        assert len(repository.tickets) == 2

    asyncio.run(verify())


def _setup():
    store = InMemoryAgentRunStore()
    repository = InMemoryMaintenanceTicketRepository()
    capability = MaintenanceTicketCapability(
        repository, approval_claims=AgentRunStoreActionApprovalPort(lambda _: store)
    )
    return store, repository, capability


async def _execute(
    capability, run_id, execution_id, station="S04", summary="Synthetic first action"
):
    return await capability.create_maintenance_ticket(
        execution_id, station, summary, run_id=run_id, security_context=CONTEXT
    )


@pytest.mark.parametrize(
    "summary", ["Synthetic first action", "Synthetic different proposal"]
)
def test_independent_same_target_approvals_are_not_content_addressed(summary):
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        first = await _approve(store, run_id)
        result_a = await _execute(capability, run_id, first)
        second = await _approve(store, run_id, summary=summary)
        result_b = await _execute(capability, run_id, second, summary=summary)
        assert UUID(first) != UUID(second)
        assert result_a.ticket_id != result_b.ticket_id
        assert len(repository.tickets) == 2

    asyncio.run(verify())


def test_same_generation_retry_returns_same_result_without_new_side_effect():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        result = await _execute(capability, run_id, identity)
        assert await _execute(capability, run_id, identity) == result
        assert len(repository.tickets) == 1
        assert (
            repository.tickets[0].request_id.value
            == sha256(f"{run_id}:{identity}".encode()).hexdigest()
        )
        claim = MaintenanceTicketApprovalClaim(
            run_id, identity, StationId("S04"), "Synthetic first action"
        )
        assert (
            await store.claim_protected_action_approval(claim, security_context=CONTEXT)
            is False
        )
        assert (
            await store.is_consumed_protected_action_approval(
                claim, security_context=CONTEXT
            )
            is True
        )

    asyncio.run(verify())


def test_concurrent_same_generation_creates_one_ticket():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        results = await asyncio.gather(
            *(_execute(capability, run_id, identity) for _ in range(4))
        )
        assert all(result == results[0] for result in results)
        assert len(repository.tickets) == 1

    asyncio.run(verify())


def test_claimed_generation_can_finish_while_a_distinct_generation_executes():
    async def verify():
        store, repository, capability_b = _setup()
        run_id = uuid4()
        await store.create(run_id)
        identity_a = await _approve(store, run_id)
        claimed = asyncio.Event()
        release = asyncio.Event()

        class WaitingClaims(AgentRunStoreActionApprovalPort):
            async def claim_approved_action(self, claim, security_context):
                result = await super().claim_approved_action(claim, security_context)
                if result:
                    claimed.set()
                    await release.wait()
                return result

        capability_a = MaintenanceTicketCapability(
            repository, approval_claims=WaitingClaims(lambda _: store)
        )
        task_a = asyncio.create_task(_execute(capability_a, run_id, identity_a))
        try:
            await asyncio.wait_for(claimed.wait(), timeout=2)
            identity_b = await _approve(store, run_id, "S02", "Synthetic second action")
            result_b = await _execute(
                capability_b, run_id, identity_b, "S02", "Synthetic second action"
            )
        finally:
            release.set()
            result_a = await task_a
        assert identity_a != identity_b
        assert result_a.ticket_id != result_b.ticket_id
        assert (result_a.station_id, result_b.station_id) == ("S04", "S02")
        assert len(repository.tickets) == 2

    asyncio.run(verify())


def test_wrong_generation_cannot_consume_the_current_approval():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        first = await _approve(store, run_id)
        second = await _approve(store, run_id, "S02", "Synthetic second action")
        for identity, station, summary in (
            (second, "S04", "Synthetic first action"),
            (first, "S02", "Synthetic second action"),
            (str(uuid4()), "S02", "Synthetic second action"),
            (MODEL_ACTION_ID, "S02", "Synthetic second action"),
        ):
            with pytest.raises(PermissionError):
                await _execute(capability, run_id, identity, station, summary)
        assert repository.tickets == ()
        assert (await store.get(run_id)).approval_generations[second][
            "consumed"
        ] is False
        assert (
            await _execute(capability, run_id, second, "S02", "Synthetic second action")
        ).station_id == "S02"

    asyncio.run(verify())


def test_previous_generation_with_identical_arguments_cannot_claim_a_new_approval():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        first = await _approve(store, run_id)
        second = await _approve(store, run_id)
        with pytest.raises(PermissionError):
            await _execute(capability, run_id, first)
        assert repository.tickets == ()
        await _execute(capability, run_id, second)
        assert len(repository.tickets) == 1

    asyncio.run(verify())


def test_retry_previous_completed_generation_does_not_consume_a_later_one():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        first = await _approve(store, run_id)
        result = await _execute(capability, run_id, first)
        second = await _approve(store, run_id)
        assert await _execute(capability, run_id, first) == result
        assert (await store.get(run_id)).approval_generations[second][
            "consumed"
        ] is False
        assert len(repository.tickets) == 1

    asyncio.run(verify())


def test_consumed_approval_without_a_committed_ticket_does_not_retry_a_write():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        claim = MaintenanceTicketApprovalClaim(
            run_id, identity, StationId("S04"), "Synthetic first action"
        )
        assert await store.claim_protected_action_approval(
            claim, security_context=CONTEXT
        )
        with pytest.raises(PermissionError):
            await _execute(capability, run_id, identity)
        assert repository.tickets == ()

    asyncio.run(verify())


def test_ambiguous_failure_after_ticket_commit_resolves_to_the_existing_ticket():
    async def verify():
        store = InMemoryAgentRunStore()
        run_id = uuid4()
        await store.create(run_id)

        class AmbiguousRepository(InMemoryMaintenanceTicketRepository):
            creates = 0

            def create_maintenance_ticket(self, *args):
                self.creates += 1
                super().create_maintenance_ticket(*args)
                raise RuntimeError("Synthetic failure after commit")

        repository = AmbiguousRepository()
        capability = MaintenanceTicketCapability(
            repository, approval_claims=AgentRunStoreActionApprovalPort(lambda _: store)
        )
        identity = await _approve(store, run_id)
        with pytest.raises(RuntimeError):
            await _execute(capability, run_id, identity)
        result = await _execute(capability, run_id, identity)
        assert result.ticket_id == repository.tickets[0].ticket_id
        assert len(repository.tickets) == repository.creates == 1

    asyncio.run(verify())


def test_explicit_checkpoint_generation_is_stable_and_cannot_be_rebound():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        identity = uuid4()
        assert await _approve(store, run_id, approval_execution_id=identity) == str(
            identity
        )
        approved = await store.get(run_id)
        repeated = await store.wait_for_approval(
            run_id, _proposal(), approval_execution_id=identity
        )
        assert repeated == approved
        with pytest.raises(PermissionError):
            await store.wait_for_approval(
                run_id, _proposal("S02"), approval_execution_id=identity
            )
        assert (await store.get(run_id)).approval_generations[str(identity)][
            "consumed"
        ] is False
        result = await _execute(capability, run_id, str(identity))
        await store.wait_for_approval(
            run_id, _proposal(), approval_execution_id=identity
        )
        assert await _execute(capability, run_id, str(identity)) == result
        assert len(repository.tickets) == 1

    asyncio.run(verify())


def test_payload_generation_is_ignored_and_caller_payload_mutation_cannot_rebind():
    async def verify():
        store, _, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        untrusted = str(uuid4())
        payload = _proposal()
        payload["approval_execution_id"] = untrusted
        pending = await store.wait_for_approval(run_id, payload)
        identity = pending.approval_request["approval_execution_id"]
        assert UUID(identity) and identity != untrusted
        payload["arguments"]["summary"] = "Unapproved mutation"
        await store.claim_resume(
            run_id,
            approval_execution_id=UUID(
                (await store.get(run_id)).approval_request["approval_execution_id"]
            ),
            decision="approve",
            approval_clearance=DataClassification.CONFIDENTIAL,
        )
        assert (
            await _execute(capability, run_id, identity)
        ).summary == "Synthetic first action"

    asyncio.run(verify())


def test_legacy_approval_without_generation_history_fails_closed():
    async def verify():
        store, repository, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        store._records[run_id] = replace(
            await store.get(run_id), approval_generations={}
        )
        with pytest.raises(PermissionError):
            await _execute(capability, run_id, identity)
        store._records[run_id] = replace(
            await store.get(run_id), status=RunStatus.WAITING_FOR_APPROVAL
        )
        assert (
            await store.claim_resume(
                run_id,
                approval_execution_id=UUID(
                    (await store.get(run_id)).approval_request["approval_execution_id"]
                ),
                decision="approve",
                approval_clearance=DataClassification.CONFIDENTIAL,
            )
            is None
        )
        assert repository.tickets == ()

    asyncio.run(verify())


def test_same_generation_like_value_is_isolated_between_runs():
    async def verify():
        store, repository, capability = _setup()
        identity = uuid4()
        results = []
        for station in ("S04", "S02"):
            run_id = uuid4()
            await store.create(run_id)
            generation = await _approve(
                store, run_id, station, approval_execution_id=identity
            )
            results.append(await _execute(capability, run_id, generation, station))
        assert results[0].ticket_id != results[1].ticket_id
        assert len({ticket.request_id for ticket in repository.tickets}) == 2

    asyncio.run(verify())


def test_consumed_ticket_lookup_keeps_the_event_loop_available():
    async def verify():
        store = InMemoryAgentRunStore()
        started, release, finished = Event(), Event(), Event()

        class ControlledRepository(InMemoryMaintenanceTicketRepository):
            def get_maintenance_ticket_by_request_id(self, identity):
                started.set()
                release.wait(timeout=3)
                finished.set()
                return super().get_maintenance_ticket_by_request_id(identity)

        repository = ControlledRepository()
        capability = MaintenanceTicketCapability(
            repository, approval_claims=AgentRunStoreActionApprovalPort(lambda _: store)
        )
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        first = await _execute(capability, run_id, identity)
        retry = asyncio.create_task(_execute(capability, run_id, identity))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 2), timeout=3)
            assert not finished.is_set()
        finally:
            release.set()
            assert await retry == first

    asyncio.run(verify())


def test_direct_mcp_uses_independent_server_generations_with_reused_model_ids():
    from test_protected_mcp_actions import RUN_ID
    from test_protected_mcp_actions import _setup as mcp_setup

    server, store, repository, _, context, _ = mcp_setup()

    async def verify():
        tool = server._tool_manager.get_tool("create_maintenance_ticket").fn
        identities, results = [], []
        for station, summary in (
            ("S04", "Synthetic first action"),
            ("S02", "Synthetic second action"),
        ):
            identity = await _approve(store, RUN_ID, station, summary)
            identities.append(identity)
            arguments = {
                "run_id": str(RUN_ID),
                "request_id": identity,
                "station_id": station,
                "summary": summary,
            }
            results.append(await tool(**arguments, ctx=context))
            assert await tool(**arguments, ctx=context) == results[-1]
            with pytest.raises(PermissionError):
                await tool(**{**arguments, "summary": "Unapproved change"}, ctx=context)
        assert identities[0] != identities[1]
        assert results[0]["ticket_id"] != results[1]["ticket_id"]
        assert results[1]["station_id"] == "S02"
        assert len(repository.tickets) == 2

    asyncio.run(verify())


def test_graph_producer_does_not_reuse_model_identity_or_accept_generation_arguments():
    from langchain_core.messages import AIMessage
    from test_langgraph_mcp_hitl import RecordingMcpToolProvider

    from industrial_ai_agent.agent.agent_run import InvalidToolArgumentsError
    from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
        LangGraphTroubleshootingAgent,
    )

    async def verify():
        provider = RecordingMcpToolProvider()
        async with provider.open_session() as session:
            tools = {tool.name: tool for tool in session.tools}
            policies = {policy.name: policy for policy in session.tool_policies}
            call = {
                "id": MODEL_ACTION_ID,
                "name": "create_maintenance_ticket",
                "args": {"station_id": "S04", "summary": "Synthetic first action"},
            }
            state = {"messages": [AIMessage(content="", tool_calls=[call])]}
            first = LangGraphTroubleshootingAgent._prepare_mcp_action_node(
                tools, policies, state
            )
            second = LangGraphTroubleshootingAgent._prepare_mcp_action_node(
                tools, policies, state
            )
            assert UUID(first["pending_action"]["approval_execution_id"]) != UUID(
                second["pending_action"]["approval_execution_id"]
            )
            assert (
                first["pending_action"]["tool_call_id"]
                == second["pending_action"]["tool_call_id"]
                == MODEL_ACTION_ID
            )
            malicious = {
                **call,
                "args": {**call["args"], "approval_execution_id": str(uuid4())},
            }
            with pytest.raises(InvalidToolArgumentsError):
                LangGraphTroubleshootingAgent._prepare_mcp_action_node(
                    tools,
                    policies,
                    {"messages": [AIMessage(content="", tool_calls=[malicious])]},
                )
            assert provider.calls == []

    asyncio.run(verify())


def test_legacy_checkpoint_cannot_infer_generation_from_a_model_uuid():
    from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
        _require_pending_action,
    )

    with pytest.raises(RuntimeError):
        _require_pending_action(
            {
                "pending_action": {
                    "action": "create_maintenance_ticket",
                    "request_id": str(uuid4()),
                    "tool_call_id": MODEL_ACTION_ID,
                    "station_id": "S04",
                    "summary": "Synthetic first action",
                }
            }
        )


def test_returned_snapshots_cannot_mutate_persisted_approval_authority():
    async def verify():
        store, _, capability = _setup()
        run_id = uuid4()
        await store.create(run_id)
        pending = await store.wait_for_approval(run_id, _proposal())
        identity = pending.approval_request["approval_execution_id"]
        pending.approval_request["arguments"]["summary"] = "Caller mutation"
        pending.approval_generations[identity]["arguments"]["summary"] = (
            "Caller mutation"
        )
        approved = await store.claim_resume(
            run_id,
            approval_execution_id=UUID(
                (await store.get(run_id)).approval_request["approval_execution_id"]
            ),
            decision="approve",
            approval_clearance=DataClassification.CONFIDENTIAL,
        )
        assert approved is not None
        approved.approval_generations[identity]["consumed"] = True
        queried = await store.get(run_id)
        queried.approval_generations[identity]["decision"] = "reject"
        assert (
            await _execute(capability, run_id, identity)
        ).summary == "Synthetic first action"

    asyncio.run(verify())
