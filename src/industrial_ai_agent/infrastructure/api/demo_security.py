"""Explicit local-only authentication and authorization simulation for the demo UI."""

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.schemas import DemoUserClearance


class DemoSecurityContextResolver:
    """Map a closed UI enum to a server-created SecurityContext.

    This is a demo-only authentication/authorization simulation and must be replaced
    by real identity-based authentication and authorization before production use.
    """

    def resolve(self, clearance: DemoUserClearance) -> SecurityContext:
        if not isinstance(clearance, DemoUserClearance):
            raise TypeError("Unknown demo user clearance")
        mapped_clearance = DataClassification[clearance.name]
        return SecurityContext(
            subject_id=f"demo-user-{clearance.value.lower()}",
            roles=("demo-engineer",),
            clearance=mapped_clearance,
            authenticated=True,
        )
