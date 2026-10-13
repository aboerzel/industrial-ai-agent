"""Consume persisted HITL claims using the executing MCP principal's RLS context."""

from collections.abc import Callable

from industrial_ai_agent.application.action_approval import (
    ProtectedActionApprovalClaim,
    TrustedActionApprovalClaimPort,
)
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.api.run_store import AgentRunStore


class AgentRunStoreActionApprovalPort(TrustedActionApprovalClaimPort):
    def __init__(
        self, store_for_context: Callable[[SecurityContext], AgentRunStore]
    ) -> None:
        self._store_for_context = store_for_context

    async def claim_approved_action(
        self, claim: ProtectedActionApprovalClaim, security_context: SecurityContext
    ) -> bool:
        return await self._store_for_context(
            security_context
        ).claim_protected_action_approval(claim, security_context=security_context)
