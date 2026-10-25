"""Event handlers. Each runs as its own durable DBOS workflow, enqueued once per (event, handler).

Register a handler for an event type with @on("type"). Handlers receive the event dict
{id, org_id, type, payload, occurred_at}.
"""
from collections.abc import Awaitable, Callable

Handler = Callable[[dict], Awaitable[None]]
HANDLERS: dict[str, list[Handler]] = {}


def on(event_type: str):
    def register(fn: Handler) -> Handler:
        HANDLERS.setdefault(event_type, []).append(fn)
        return fn
    return register
