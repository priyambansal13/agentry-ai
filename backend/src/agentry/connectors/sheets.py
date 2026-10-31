"""Google Sheets for bookkeeping (9.5): one spreadsheet per business that Agentry creates and keeps appending to.

Connect uses the same Google OAuth client and redirect as Gmail (state "p": "sheets"), with only the `drive.file`
scope: Agentry can open the files it created, nothing else in the person's Drive. The Google Sheets API must be
enabled in the Google Cloud project.
"""
import time
from urllib.parse import urlencode

from agentry.config import settings
from agentry.connectors import gmail
from agentry.connectors.http import client
from agentry.connectors.store import update_state

SCOPES = ["openid", "email", "https://www.googleapis.com/auth/drive.file"]
API = "https://sheets.googleapis.com/v4/spreadsheets"
COLUMNS = ["Date", "Vendor", "Vendor GSTIN", "Bill number", "Category", "Description", "Subtotal", "CGST", "SGST", "IGST", "Total",
           "Currency", "Paid by", "Agentry id"]
FIELDS = ["date", "vendor", "vendor_gstin", "bill_number", "category", "description", "subtotal", "cgst", "sgst", "igst", "total",
          "currency", "payment_method"]


class SheetsError(Exception):
    def __init__(self, message: str, auth: bool = False):
        super().__init__(message)
        self.auth = auth


def auth_url(state: str, login_hint: str | None = None) -> str:
    params = {"client_id": settings.google_client_id, "redirect_uri": gmail.redirect_uri(), "response_type": "code", "scope": " ".join(SCOPES),
              "access_type": "offline", "prompt": "consent", "state": state, **({"login_hint": login_hint} if login_hint else {})}
    return f"{gmail.AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with client() as c:
        r = await c.post(gmail.TOKEN_URL, data={"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                                                "redirect_uri": gmail.redirect_uri(), "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise SheetsError(f"Google rejected the sign-in: {r.text[:200]}")
    tok = r.json()
    if "refresh_token" not in tok:
        raise SheetsError("Google did not return offline access; remove Agentry from your Google account and connect again")
    if "https://www.googleapis.com/auth/drive.file" not in set(tok.get("scope", "").split()):
        raise SheetsError("Google Sheets access was not granted (tick the box for files Agentry creates)")
    return {"refresh_token": tok["refresh_token"], "access_token": tok["access_token"], "expires_at": time.time() + tok.get("expires_in", 3600) - 60}


class Sheets:
    def __init__(self, org_id: str, connection: dict):
        self.org_id, self.conn = org_id, connection
        self.secret = dict(connection["secret"])

    async def _token(self) -> str:
        if self.secret.get("access_token") and self.secret.get("expires_at", 0) > time.time():
            return self.secret["access_token"]
        async with client() as c:
            r = await c.post(gmail.TOKEN_URL, data={"client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                                                    "refresh_token": self.secret["refresh_token"], "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise SheetsError("Google Sheets access was revoked or expired; reconnect it", auth=True)
        tok = r.json()
        self.secret.update(access_token=tok["access_token"], expires_at=time.time() + tok.get("expires_in", 3600) - 60)
        await update_state(self.org_id, self.conn["id"], secret=self.secret)
        return self.secret["access_token"]

    async def call(self, method: str, url: str, **kw) -> dict:
        async with client() as c:
            r = await c.request(method, url, headers={"Authorization": f"Bearer {await self._token()}"}, **kw)
        if r.status_code >= 400:
            raise SheetsError(f"Google Sheets {r.status_code}: {r.text[:300]}", auth=r.status_code in (401, 403))
        return r.json() if r.content else {}


async def create(token_secret: dict, org_id: str, title: str) -> dict:
    """A new spreadsheet with the header row: {"id", "url"}."""
    s = Sheets(org_id, {"id": None, "secret": token_secret})
    s._token = _static(token_secret["access_token"])  # fresh from the sign-in: no refresh, no stored connection yet
    body = {"properties": {"title": title}, "sheets": [{"properties": {"title": "Expenses", "gridProperties": {"frozenRowCount": 1}},
            "data": [{"startRow": 0, "startColumn": 0, "rowData": [{"values": [{"userEnteredValue": {"stringValue": c}} for c in COLUMNS]}]}]}]}
    out = await s.call("POST", API, json=body)
    return {"id": out["spreadsheetId"], "url": out.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{out['spreadsheetId']}"}


def _static(token: str):
    async def t() -> str:
        return token
    return t


def row(doc: dict) -> list:
    f = doc["fields"]
    return [("" if (f.get(k) or {}).get("value") is None else f[k]["value"]) for k in FIELDS] + [doc["id"]]


async def append(org_id: str, connection: dict, rows: list[list]) -> None:
    s = Sheets(org_id, connection)
    sid = connection["account_ref"]
    await s.call("POST", f"{API}/{sid}/values/Expenses!A1:append", params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                 json={"values": rows})
