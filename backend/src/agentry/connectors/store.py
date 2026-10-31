"""Reading and writing connections. Credentials are decrypted only inside the backend, never returned by the API."""
import json

from sqlalchemy import text

from agentry.db import system_session, tenant_session
from agentry.secrets import decrypt_json, encrypt_json


async def save_connection(org_id: str, *, provider: str, account_ref: str, secret: dict, display_name: str | None = None,
                          scopes: list[str] | None = None, state: dict | None = None, connected_by: str | None = None) -> str:
    async with tenant_session(org_id) as conn:
        return str((await conn.execute(text("""
            insert into app.connections (org_id, provider, account_ref, display_name, secret_enc, scopes, state, connected_by)
            values (:o, :p, :a, :d, :s, :sc, cast(:st as jsonb), :by)
            on conflict (org_id, provider, account_ref) do update set secret_enc = excluded.secret_enc,
              display_name = excluded.display_name, scopes = excluded.scopes, state = app.connections.state || excluded.state,
              status = 'connected', last_error = null, connected_by = excluded.connected_by
            returning id"""), {"o": org_id, "p": provider, "a": account_ref, "d": display_name, "s": encrypt_json(secret),
                               "sc": scopes or [], "st": json.dumps(state or {}), "by": connected_by})).scalar_one())


async def get_connection(org_id: str, provider: str) -> dict | None:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select * from app.connections where provider = :p and status = 'connected'
            order by created_at desc limit 1"""), {"p": provider})).mappings().first()
    return _with_secret(row)


async def get_connections(org_id: str, provider: str) -> list[dict]:
    """Every connected account of this kind (a client can connect several Gmail inboxes)."""
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(text("""select * from app.connections where provider = :p and status <> 'revoked'
            order by created_at"""), {"p": provider})).mappings().all()
    return [_with_secret(r) for r in rows]


async def get_connection_for(org_id: str, provider: str, account_ref: str | None) -> dict | None:
    """The connection for one account, else the most recent one (conversations from before several inboxes)."""
    if account_ref:
        async with tenant_session(org_id) as conn:
            row = (await conn.execute(text("""select * from app.connections where provider = :p and account_ref = :a
                and status <> 'revoked'"""), {"p": provider, "a": account_ref})).mappings().first()
        if row:
            return _with_secret(row)
    return await get_connection(org_id, provider)


async def find_by_account(provider: str, account_ref: str) -> dict | None:
    """Webhooks: map a provider account id to its organisation (system role, crosses tenants)."""
    async with system_session() as conn:
        row = (await conn.execute(text("""select * from app.connections where provider = :p and account_ref = :a
            and status <> 'revoked'"""), {"p": provider, "a": account_ref})).mappings().first()
    return _with_secret(row)


async def all_connected(provider: str) -> list[dict]:
    async with system_session() as conn:
        rows = (await conn.execute(text("select id, org_id from app.connections where provider = :p and status = 'connected'"),
                                   {"p": provider})).mappings().all()
    return [dict(r) for r in rows]


async def update_state(org_id: str, connection_id: str, *, state: dict | None = None, secret: dict | None = None,
                       error: str | None = None, synced: bool = False) -> None:
    async with tenant_session(org_id) as conn:
        before = (await conn.execute(text("select provider, account_ref, status from app.connections where id = :id"), {"id": connection_id})).first()
        await conn.execute(text("""update app.connections set
              state = state || cast(:st as jsonb),
              secret_enc = coalesce(:sec, secret_enc),
              last_error = :err,
              status = case when cast(:err as text) is null then 'connected' else 'error' end,
              last_sync_at = case when :synced then now() else last_sync_at end
            where id = :id"""), {"st": json.dumps(state or {}), "sec": encrypt_json(secret) if secret else None,
                                  "err": error, "synced": synced, "id": connection_id})
        if error and before and before.status != "error":  # it just broke (not every failed retry)
            from agentry.events import emit
            await emit(conn, org_id, "connection.broken", {"provider": before.provider, "account": before.account_ref, "error": error[:300]})


def _with_secret(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    d["secret"] = decrypt_json(d.pop("secret_enc"))
    d["id"] = str(d["id"])
    return d


def public_view(row: dict) -> dict:
    """What the portal may see: never tokens."""
    return {k: row.get(k) for k in ("id", "provider", "account_ref", "display_name", "status", "scopes", "last_sync_at",
                                     "last_error", "created_at")}
