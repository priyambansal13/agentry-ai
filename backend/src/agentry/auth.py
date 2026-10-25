"""Request authentication for the API.

The dashboard (Better Auth) issues short-lived JWTs; we verify them against its JWKS. The JWT only proves *who*
the user is. *Which organisation* comes from the X-Org-Id header (the org switcher) and membership is always read
fresh from auth.member, so a removed member or changed role takes effect immediately.
Agentry staff (platform_role = admin) may act in any organisation; their requests are audited as agentry_staff.
"""
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import text

from agentry.config import settings
from agentry.db import system_session
from agentry.permissions import can

_jwks = PyJWKClient(settings.auth_jwks_url, cache_keys=True, lifespan=300)


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    name: str
    platform_role: str

    @property
    def is_staff(self) -> bool:
        return self.platform_role == "admin"


@dataclass(frozen=True)
class OrgContext:
    principal: Principal
    org_id: str
    role: str | None  # None for Agentry staff acting without a membership

    @property
    def actor_type(self) -> str:
        return "agentry_staff" if self.role is None else "user"

    def can(self, resource: str, action: str) -> bool:
        return self.principal.is_staff or can(self.role, resource, action)


def _decode(token: str) -> dict:
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=["EdDSA", "ES256", "RS256"],
            audience=settings.auth_audience, issuer=settings.auth_issuer,
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e


async def current_principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    claims = _decode(authorization.split(" ", 1)[1])
    return Principal(
        user_id=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        platform_role=claims.get("platform_role", "user"),
    )


async def membership_role(user_id: str, org_id: str) -> str | None:
    async with system_session() as conn:
        row = await conn.execute(
            text('select role from auth.member where "userId" = :u and "organizationId" = :o'),
            {"u": user_id, "o": org_id},
        )
        return row.scalar_one_or_none()


async def current_org(
    principal: Annotated[Principal, Depends(current_principal)],
    x_org_id: Annotated[str | None, Header()] = None,
) -> OrgContext:
    if not x_org_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Org-Id header required")
    role = await membership_role(principal.user_id, x_org_id)
    if role is None and not principal.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not a member of this organisation")
    return OrgContext(principal=principal, org_id=x_org_id, role=role)


def require(resource: str, action: str):
    """Dependency: the caller must hold resource:action in the current organisation."""

    async def check(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
        if not ctx.can(resource, action):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission {resource}:{action}")
        return ctx

    return check


async def require_staff(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not principal.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agentry staff only")
    return principal


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
