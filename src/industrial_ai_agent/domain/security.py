"""Provider-independent security vocabulary for classified industrial data."""

from dataclasses import dataclass
from enum import IntEnum


class DataClassification(IntEnum):
    """Ordered technical sensitivity labels for project data."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


def effective_data_classification(
    *classifications: DataClassification,
) -> DataClassification:
    """Return the monotonic maximum sensitivity of a data context."""
    if not classifications:
        raise ValueError("At least one data classification is required")
    if any(
        not isinstance(classification, DataClassification)
        for classification in classifications
    ):
        raise ValueError("Unknown data classification")
    return max(classifications)


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """Authorization context supplied by an outer composition boundary."""

    subject_id: str
    roles: tuple[str, ...]
    clearance: DataClassification
    authenticated: bool

    def __post_init__(self) -> None:
        normalized_subject_id = self.subject_id.strip()
        if not normalized_subject_id:
            raise ValueError("subject_id must not be empty")
        normalized_roles = tuple(role.strip() for role in self.roles if role.strip())
        if not normalized_roles:
            raise ValueError("Security context requires at least one role")
        if not isinstance(self.clearance, DataClassification):
            raise TypeError("Unknown security clearance")
        if not isinstance(self.authenticated, bool):
            raise TypeError("authenticated must be a bool")
        object.__setattr__(self, "subject_id", normalized_subject_id)
        object.__setattr__(self, "roles", normalized_roles)


DEMO_ENGINEER_SECURITY_CONTEXT = SecurityContext(
    subject_id="demo-engineer",
    roles=("engineer",),
    clearance=DataClassification.CONFIDENTIAL,
    authenticated=False,
)
