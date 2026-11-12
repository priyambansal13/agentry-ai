"""Agentry HQ → Due dates (automations/ca/due_dates.py): official changes to statutory due dates found by the daily check
of official sources, approved, rejected or entered by Agentry staff, and applied to every CA firm."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agentry.auth import Principal, require_staff
from agentry.automations.ca import core, due_dates

router = APIRouter(prefix="/hq/due-dates", tags=["agentry-hq"])
Staff = Annotated[Principal, Depends(require_staff)]


def _who(p: Principal) -> str:
    return p.email or p.user_id or "staff"


@router.get("")
async def overview(p: Staff) -> dict:
    return {**await due_dates.listing(), "kinds": core.KINDS, "sources": [{"name": n, "url": u} for n, u in due_dates.LIVE_SOURCES],
            "searched": due_dates.SEARCHED}


@router.post("/check")
async def check(p: Staff) -> dict:
    return await due_dates.request_sync("staff")


@router.get("/rules")
async def rules(p: Staff) -> dict:
    """Every official figure the agents use, with its source, and the changes found or entered."""
    return await due_dates.rules_listing()


class RuleIn(BaseModel):
    key: Annotated[str, Field(min_length=3, max_length=80)]
    new_value: str | float | list
    applies_from: Annotated[str | None, Field(max_length=60)] = None
    source: Annotated[str, Field(min_length=4, max_length=300)]
    source_url: Annotated[str | None, Field(max_length=500)] = None


@router.post("/rules")
async def add_rule(body: RuleIn, p: Staff) -> dict:
    try:
        return await due_dates.add_rule(body.key, body.new_value, body.applies_from, body.source, body.source_url, _who(p))
    except core.CaError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/rules/{uid}/{action}")
async def decide_rule(uid: str, action: str, p: Staff) -> dict:
    if action not in ("approve", "reject", "withdraw"):
        raise HTTPException(404, "unknown action")
    try:
        return await due_dates.decide_rule(uid, action, _who(p))
    except core.CaError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/{uid}/{action}")
async def decide(uid: str, action: str, p: Staff) -> dict:
    fn = {"approve": due_dates.approve, "reject": due_dates.reject, "withdraw": due_dates.withdraw}.get(action)
    if not fn:
        raise HTTPException(404, "unknown action")
    try:
        return await fn(uid, _who(p))
    except core.CaError as e:
        raise HTTPException(404, str(e)) from e


class AddIn(BaseModel):
    kind: str
    period: Annotated[str, Field(min_length=4, max_length=40)]
    original_on: date
    due_on: date
    source: Annotated[str, Field(min_length=4, max_length=300)]
    source_url: Annotated[str | None, Field(max_length=500)] = None
    quote: Annotated[str | None, Field(max_length=400)] = None


@router.post("")
async def add(body: AddIn, p: Staff) -> dict:
    try:
        return await due_dates.add(body.kind, body.period, body.original_on, body.due_on, body.source, body.source_url, body.quote, _who(p))
    except core.CaError as e:
        raise HTTPException(422, str(e)) from e
