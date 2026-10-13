"""Destination constraints for the existing local-only embedding deployment."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from industrial_ai_agent.agent.model_egress import (
    ExecutionZone,
    ModelEgressDeniedError,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.domain.security import DataClassification


class EmbeddingExecutionAuthorizer:
    """Approve a bounded destination, then apply the authoritative model policy."""

    def __init__(self) -> None:
        self._models = ModelExecutionAuthorizer()

    def require_allowed(self, classification: object, endpoint: object) -> str:
        destination = _approved_local_destination(endpoint)
        if destination is None:
            raise ModelEgressDeniedError("Model egress denied by policy")
        self._models.require_allowed(
            classification, ExecutionZone.LOCAL, DataClassification.RESTRICTED
        )
        return destination


def _approved_local_destination(endpoint: object) -> str | None:
    if not isinstance(endpoint, str) or any(
        ord(character) <= 32 or character in "\\%?#" for character in endpoint
    ):
        return None
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.port != 11434
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
        ):
            return None
        host = parsed.hostname
        if host == "localhost":
            return "http://127.0.0.1:11434"
        # This exact alias is pinned by Compose's deployment-owned host-gateway entry.
        if host == "host.docker.internal":
            return "http://host.docker.internal:11434"
        address = ip_address(host or "")
        if address == ip_address("127.0.0.1"):
            return "http://127.0.0.1:11434"
        if address == ip_address("::1"):
            return "http://[::1]:11434"
    except ValueError:
        return None
    return None
