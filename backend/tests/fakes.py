"""In-memory fake Google (OAuth + Gmail API), Microsoft (OAuth + Graph mail API) and Meta (WhatsApp Cloud API) for
connector tests."""
import base64
import json
import re
from email import message_from_bytes

import httpx


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class FakeProviders:
    def __init__(self, mailbox: str = "owner@sharmadigital.example"):
        self.mailbox = mailbox
        self.history_id = 1000
        self.messages: dict[str, dict] = {}
        self.history: list[dict] = []
        self.labels: dict[str, str] = {"INBOX": "INBOX"}
        self.modified: list[tuple[str, dict]] = []
        self.drafts: dict[str, dict] = {}
        self.sent_drafts: list[str] = []
        self.revoked: list[str] = []
        self.wa_sent: list[dict] = []
        self.refreshes = 0
        self.watches: list[dict] = []
        # Microsoft Graph
        self.ms_mailbox = "owner@contoso.example"
        self.ms_inbox: list[dict] = []
        self.ms_sentitems: list[dict] = []
        self.ms_seen: dict[str, int] = {"inbox": 0, "sentitems": 0}
        self.ms_categories: dict[str, list[str]] = {}
        self.ms_drafts: dict[str, dict] = {}
        self.ms_sent_drafts: list[str] = []
        self.ms_moved: list[tuple[str, str]] = []
        self.ms_attachments: dict[str, list[dict]] = {}

    def add_outlook(self, mid: str, conversation: str, sender: str, subject: str, body: str, *, folder: str = "inbox",
                    at: str = "2026-10-25T10:00:00Z", attachments: list[dict] | None = None) -> None:
        msg = {"id": mid, "conversationId": conversation, "subject": subject, "body": {"contentType": "text", "content": body},
               "from": {"emailAddress": {"address": sender, "name": sender.split("@")[0].title()}},
               "receivedDateTime": at, "sentDateTime": at, "internetMessageId": f"<{mid}@outlook.example>",
               "hasAttachments": bool(attachments), "categories": []}
        (self.ms_inbox if folder == "inbox" else self.ms_sentitems).append(msg)
        if attachments:
            self.ms_attachments[mid] = attachments

    def add_email(self, mid: str, thread: str, sender: str, subject: str, body: str, labels=("INBOX",)) -> None:
        self.history_id += 1
        self.messages[mid] = {"id": mid, "threadId": thread, "labelIds": list(labels), "internalDate": "1761300000000",
                              "snippet": body[:50], "payload": {"mimeType": "multipart/alternative", "headers": [
                                  {"name": "From", "value": f"Customer <{sender}>"}, {"name": "Subject", "value": subject},
                                  {"name": "Message-ID", "value": f"<{mid}@mail.example>"}],
                                  "parts": [{"mimeType": "text/plain", "body": {"data": b64(body)}},
                                            {"mimeType": "text/html", "body": {"data": b64(f"<p>{body}</p>")}}]}}
        self.history.append({"id": str(self.history_id), "messagesAdded": [{"message": {"id": mid}}]})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        url, m = str(req.url), req.method
        if url.startswith("https://oauth2.googleapis.com/token"):
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            if form["grant_type"] == "authorization_code":
                if form["code"] != "good-code":
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-secret-123", "expires_in": 3600,
                                                 "scope": "openid email https://www.googleapis.com/auth/gmail.modify"})
            self.refreshes += 1
            return httpx.Response(200, json={"access_token": f"at-{self.refreshes + 1}", "expires_in": 3600})
        if url.startswith("https://oauth2.googleapis.com/revoke"):
            self.revoked.append(req.content.decode())
            return httpx.Response(200)
        if url.startswith("https://login.microsoftonline.com/"):
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            if form["grant_type"] == "authorization_code":
                if form["code"] != "good-code":
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "ms-at-1", "refresh_token": "ms-rt-1", "expires_in": 3600,
                                                 "scope": "https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/Mail.Send "
                                                          "https://graph.microsoft.com/User.Read offline_access openid email"})
            self.refreshes += 1
            return httpx.Response(200, json={"access_token": f"ms-at-{self.refreshes + 1}", "refresh_token": f"ms-rt-{self.refreshes + 1}", "expires_in": 3600})
        if url.startswith("https://graph.microsoft.com/v1.0"):
            return self.graph(req, url.split("/v1.0", 1)[1], m)
        if "gmail.googleapis.com" in url:
            return self.gmail(req, url.split("/users/me", 1)[1], m)
        if "graph.facebook.com" in url:
            return self.meta(req, url, m)
        return httpx.Response(404)

    def gmail(self, req: httpx.Request, path: str, m: str) -> httpx.Response:
        p = path.split("?")[0]
        if p == "/profile":
            return httpx.Response(200, json={"emailAddress": self.mailbox, "historyId": str(self.history_id)})
        if p == "/watch" and m == "POST":
            self.watches.append(json.loads(req.content))
            return httpx.Response(200, json={"historyId": str(self.history_id), "expiration": "1762000000000"})
        if p == "/threads":
            return httpx.Response(200, json={"threads": []})
        if p == "/history":
            start = int(req.url.params["startHistoryId"])
            recs = [h for h in self.history if int(h["id"]) > start]
            return httpx.Response(200, json={"history": recs, "historyId": str(self.history_id)})
        if mm := re.fullmatch(r"/messages/([^/]+)", p):
            if mm.group(1) not in self.messages:
                return httpx.Response(404, json={"error": {"code": 404, "message": "Requested entity was not found.", "status": "NOT_FOUND"}})
            return httpx.Response(200, json=self.messages[mm.group(1)])
        if mm := re.fullmatch(r"/messages/([^/]+)/modify", p):
            self.modified.append((mm.group(1), json.loads(req.content)))
            return httpx.Response(200, json={})
        if p == "/labels" and m == "GET":
            return httpx.Response(200, json={"labels": [{"id": v, "name": k} for k, v in self.labels.items()]})
        if p == "/labels" and m == "POST":
            name = json.loads(req.content)["name"]
            self.labels[name] = f"Label_{len(self.labels)}"
            return httpx.Response(200, json={"id": self.labels[name], "name": name})
        if p == "/drafts" and m == "POST":
            did = f"r-{len(self.drafts) + 1}"
            self.drafts[did] = json.loads(req.content)["message"]
            return httpx.Response(200, json={"id": did})
        if p == "/drafts/send":
            did = json.loads(req.content)["id"]
            self.sent_drafts.append(did)
            return httpx.Response(200, json={"id": f"sent-{did}", "threadId": self.drafts[did]["threadId"]})
        if (mm := re.fullmatch(r"/drafts/([^/]+)", p)) and m == "PUT":
            self.drafts[mm.group(1)] = json.loads(req.content)["message"]
            return httpx.Response(200, json={"id": mm.group(1)})
        return httpx.Response(404, json={"error": p})

    def graph(self, req: httpx.Request, path: str, m: str) -> httpx.Response:
        p = path.split("?")[0]
        if p == "/me":
            return httpx.Response(200, json={"mail": self.ms_mailbox, "userPrincipalName": self.ms_mailbox})
        if mm := re.fullmatch(r"/me/mailFolders/(inbox|sentitems)/messages/delta", p):
            folder = mm.group(1)
            items = self.ms_inbox if folder == "inbox" else self.ms_sentitems
            new = items[self.ms_seen[folder]:]
            self.ms_seen[folder] = len(items)
            return httpx.Response(200, json={"value": new, "@odata.deltaLink": f"https://graph.microsoft.com/v1.0{p}?$deltatoken={len(items)}"})
        if p == "/me/mailFolders/sentitems/messages":
            conv = re.search(r"conversationId eq '([^']+)'", req.url.params.get("$filter", ""))
            hits = [x for x in self.ms_sentitems if conv and x["conversationId"] == conv.group(1)]
            return httpx.Response(200, json={"value": [{"id": x["id"]} for x in hits[:1]]})
        if mm := re.fullmatch(r"/me/messages/([^/]+)/attachments", p):
            return httpx.Response(200, json={"value": self.ms_attachments.get(mm.group(1), [])})
        if mm := re.fullmatch(r"/me/messages/([^/]+)/createReply", p):
            did = f"ms-draft-{len(self.ms_drafts) + 1}"
            self.ms_drafts[did] = {"reply_to": mm.group(1), "body": ""}
            return httpx.Response(201, json={"id": did})
        if mm := re.fullmatch(r"/me/messages/([^/]+)/send", p):
            self.ms_sent_drafts.append(mm.group(1))
            return httpx.Response(202)
        if mm := re.fullmatch(r"/me/messages/([^/]+)/move", p):
            self.ms_moved.append((mm.group(1), json.loads(req.content)["destinationId"]))
            return httpx.Response(201, json={"id": mm.group(1)})
        if mm := re.fullmatch(r"/me/messages/([^/]+)", p):
            mid = mm.group(1)
            if m == "PATCH":
                body = json.loads(req.content)
                if "categories" in body:
                    self.ms_categories[mid] = body["categories"]
                if "body" in body and mid in self.ms_drafts:
                    self.ms_drafts[mid]["body"] = body["body"]["content"]
                return httpx.Response(200, json={"id": mid})
            return httpx.Response(200, json={"id": mid, "categories": self.ms_categories.get(mid, [])})
        return httpx.Response(404, json={"error": p})

    def draft_mime(self, did: str):
        raw = self.drafts[did]["raw"]
        return message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))

    def meta(self, req: httpx.Request, url: str, m: str) -> httpx.Response:
        if req.headers.get("authorization") != "Bearer EAAG-test-token-1234567890":
            return httpx.Response(401, json={"error": {"message": "Invalid OAuth access token"}})
        if m == "GET":
            return httpx.Response(200, json={"display_phone_number": "+1 555 010 0100", "verified_name": "SmileCraft Test",
                                             "id": url.split("/")[-1].split("?")[0]})
        body = json.loads(req.content)
        self.wa_sent.append(body)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.out{len(self.wa_sent)}"}]})
