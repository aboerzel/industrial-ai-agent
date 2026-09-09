"""Application port for authorized document bytes without storage identifiers."""

from dataclasses import dataclass
from typing import Protocol

from industrial_ai_agent.domain.security import SecurityContext


@dataclass(frozen=True, slots=True)
class AuthorizedDocumentContent:
    """Already-authorized document bytes and safe browser presentation metadata."""

    content: bytes
    media_type: str
    filename: str


class AuthorizedDocumentContentReader(Protocol):
    """Re-evaluate current authorization before returning a cataloged document."""

    def get_document(
        self, document_id: str, security_context: SecurityContext
    ) -> AuthorizedDocumentContent | None: ...
