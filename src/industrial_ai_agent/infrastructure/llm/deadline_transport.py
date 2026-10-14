"""RCA-only total HTTP deadline without an extra event loop or provider thread."""

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from math import isfinite
from time import monotonic

import anyio.from_thread
import httpx

_OPERATION_DEADLINE: ContextVar[float | None] = ContextVar(
    "llm_operation_deadline", default=None
)


@contextmanager
def operation_deadline(timeout_seconds: float | None) -> Iterator[None]:
    """Keep an operation budget out of provider payloads and credential headers."""
    if timeout_seconds is not None and (
        not isfinite(timeout_seconds) or timeout_seconds <= 0
    ):
        raise ValueError("Provider operation timeout must be finite and positive")
    token = _OPERATION_DEADLINE.set(
        monotonic() + timeout_seconds if timeout_seconds is not None else None
    )
    try:
        yield
    finally:
        _OPERATION_DEADLINE.reset(token)


class DeadlineHTTPTransport(httpx.BaseTransport):
    """Bridge the sync SDK to cancellable HTTP on its owning AnyIO event loop.

    Use inside an AnyIO-managed worker only. Each request owns its async transport
    and closes it before the worker returns, including on deadline expiry.
    """

    def __init__(
        self,
        *,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        self._transport_factory = transport_factory or (
            lambda: httpx.AsyncHTTPTransport(trust_env=False)
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        deadline = _OPERATION_DEADLINE.get()
        if deadline is None:
            raise ValueError("RCA transport requires a finite operation timeout")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise httpx.ReadTimeout(
                "RCA provider operation deadline exceeded", request=request
            )
        return anyio.from_thread.run(self._request, request, remaining)

    async def _request(
        self, request: httpx.Request, timeout_seconds: float
    ) -> httpx.Response:
        try:
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport_factory(),
                    timeout=httpx.Timeout(timeout_seconds),
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    response = await client.send(
                        httpx.Request(
                            request.method,
                            request.url,
                            headers=request.headers,
                            content=request.read(),
                            extensions=request.extensions,
                        )
                    )
                    # The async response body is already decoded and fully buffered.
                    # Its headers must describe those bytes at the sync SDK boundary.
                    headers = response.headers.copy()
                    for name in (
                        "content-encoding",
                        "content-length",
                        "transfer-encoding",
                    ):
                        headers.pop(name, None)
                    return httpx.Response(
                        response.status_code,
                        headers=headers,
                        content=response.content,
                        request=request,
                    )
        except TimeoutError as error:
            raise httpx.ReadTimeout(
                "RCA provider operation deadline exceeded", request=request
            ) from error
