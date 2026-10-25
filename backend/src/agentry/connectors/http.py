"""Shared HTTP client for provider APIs. Tests swap TRANSPORT for an httpx.MockTransport (fake Google / Meta)."""
import httpx

TRANSPORT: httpx.AsyncBaseTransport | None = None


def client(timeout: float = 20) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=TRANSPORT)
