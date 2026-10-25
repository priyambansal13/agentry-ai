"""Knowledge base: what an organisation's agents know (services, prices, policies, FAQs, website pages).

Documents are split into overlapping chunks, embedded through the LLM gateway (embed tier, or hashed vectors in
mock mode) and searched by cosine similarity with pgvector. All reads and writes run under row-level security.
"""
import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from pgvector.sqlalchemy import Vector  # noqa: F401 - registers the type with SQLAlchemy
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from sqlalchemy import text

from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, embed

CHUNK_CHARS, OVERLAP = 900, 150


log = logging.getLogger(__name__)


@dataclass
class Hit:
    content: str
    title: str | None
    source_ref: str | None
    score: float


MAX_CHUNKS = 400  # about 350k characters per document
EMBED_BATCH = 50
MAX_FILE_BYTES = 10 * 1024 * 1024
FILE_TYPES = {".pdf": "PDF", ".docx": "Word", ".txt": "text", ".md": "Markdown", ".csv": "CSV"}


class KnowledgeTooLarge(ValueError):
    pass


class UnreadableFile(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    """Plain text from an uploaded file, for the knowledge base."""
    import io
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in FILE_TYPES:
        raise UnreadableFile(f"Upload a {', '.join(FILE_TYPES.values())} file")
    if len(data) > MAX_FILE_BYTES:
        raise UnreadableFile("Files can be up to 10 MB")
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text_ = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        elif ext == ".docx":
            from docx import Document
            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:  # price lists and schedules often live in tables
                parts += [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
            text_ = "\n\n".join(p for p in parts if p.strip())
        else:
            text_ = data.decode("utf-8-sig", errors="replace")
    except Exception as e:
        raise UnreadableFile(f"Couldn't read this {FILE_TYPES[ext]} file ({type(e).__name__}). Is it password-protected?") from e
    text_ = re.sub(r"[ \t]+", " ", text_).strip()
    if len(text_) < 20:
        raise UnreadableFile("No readable text found. Scanned PDFs (images of pages) can't be read yet: paste the text instead")
    return text_


def chunk(content: str) -> list[str]:
    """Split on paragraphs, packing them into ~900-char chunks with a little overlap for context."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        while len(p) > CHUNK_CHARS:  # a single huge paragraph: hard split
            head, p = p[:CHUNK_CHARS], p[CHUNK_CHARS - OVERLAP:]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if len(cur) + len(p) + 2 > CHUNK_CHARS and cur:
            chunks.append(cur)
            cur = cur[-OVERLAP:] + "\n\n" + p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


async def add_document(org_id: str, *, source_type: str, content: str, title: str | None = None,
                       source_ref: str | None = None) -> str:
    """Add (or replace, by source_ref) a document and its embedded chunks."""
    pieces = chunk(content) or [content]
    if len(pieces) > MAX_CHUNKS:
        raise KnowledgeTooLarge(f"This is too long ({len(pieces)} sections, max {MAX_CHUNKS}): split it into smaller documents")
    vectors: list[list[float]] = []
    for i in range(0, len(pieces), EMBED_BATCH):  # providers cap inputs per request
        batch, _ = await embed([f"{title or ''}\n{p}" for p in pieces[i:i + EMBED_BATCH]], org_id=org_id)
        vectors += batch
    async with tenant_session(org_id) as conn:
        if source_ref:
            await conn.execute(text("delete from app.kb_documents where source_ref = :r"), {"r": source_ref})
        doc_id = (await conn.execute(
            text("""insert into app.kb_documents (org_id, source_type, source_ref, title, content)
                    values (:o, :t, :r, :title, :c) returning id"""),
            {"o": org_id, "t": source_type, "r": source_ref, "title": title, "c": content},
        )).scalar_one()
        for i, (piece, vec) in enumerate(zip(pieces, vectors, strict=True)):
            await conn.execute(
                text("""insert into app.kb_chunks (org_id, document_id, ord, content, embedding)
                        values (:o, :d, :i, :c, cast(:e as vector))"""),
                {"o": org_id, "d": doc_id, "i": i, "c": piece, "e": _vec(vec)},
            )
    return str(doc_id)


async def add_faqs(org_id: str, faqs: list[dict]) -> int:
    for f in faqs:
        await add_document(org_id, source_type="faq", title=f["q"], content=f"Q: {f['q']}\nA: {f['a']}",
                           source_ref=f"faq:{f['q'][:120]}")
    return len(faqs)


async def search(org_id: str, query: str, k: int = 5, min_score: float = 0.05) -> list[Hit]:
    """Knowledge for a question. If the embedding model is unavailable (quota, outage), agents carry on without
    knowledge rather than fail: the drafted reply leaves [gaps] for a person to fill, and ops are alerted."""
    try:
        (qv,), _ = await embed([query], org_id=org_id)
    except AllModelsFailed as e:
        log.warning("knowledge search skipped for %s: %s", org_id, str(e)[:200])
        return []
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(
            text("""select c.content, d.title, d.source_ref, 1 - (c.embedding <=> cast(:q as vector)) as score
                    from app.kb_chunks c join app.kb_documents d on d.id = c.document_id
                    order by c.embedding <=> cast(:q as vector) limit :k"""),
            {"q": _vec(qv), "k": k},
        )).all()
    return [Hit(r.content, r.title, r.source_ref, float(r.score)) for r in rows if r.score >= min_score]


def format_hits(hits: list[Hit]) -> str:
    return "\n\n---\n\n".join(f"[{h.title or h.source_ref or 'note'}]\n{h.content}" for h in hits) or "(nothing relevant found)"


# ---------- website crawl (Demo Studio, onboarding) ----------

class UnsafeUrl(ValueError):
    pass


def _check_public(url: str) -> None:
    """Refuse non-http(s) URLs and hosts resolving to private, loopback or link-local addresses (SSRF guard)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UnsafeUrl(f"not a public web address: {url}")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror as e:
        raise UnsafeUrl(f"cannot resolve {p.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeUrl(f"{p.hostname} resolves to a non-public address")


@dataclass
class Page:
    url: str
    title: str
    text: str
    meta: dict


def extract(html: str, url: str) -> Page:
    tree = HTMLParser(html)
    meta = {}
    for m in tree.css("meta"):
        name = (m.attributes.get("property") or m.attributes.get("name") or "").lower()
        if name in ("og:site_name", "og:title", "description", "og:description", "og:image", "theme-color"):
            meta[name] = m.attributes.get("content")
    icon = tree.css_first("link[rel~=icon]")
    if icon and icon.attributes.get("href"):
        meta["icon"] = urljoin(url, icon.attributes["href"])
    if meta.get("og:image"):
        meta["og:image"] = urljoin(url, meta["og:image"])
    title = (tree.css_first("title").text(strip=True) if tree.css_first("title") else "") or meta.get("og:title", "")
    for sel in ("script", "style", "noscript", "svg", "nav", "footer", "form", "iframe"):
        for n in tree.css(sel):
            n.decompose()
    body = tree.body
    blocks = []
    if body:
        for n in body.css("h1,h2,h3,h4,p,li,td,dt,dd,address,blockquote"):
            t = re.sub(r"\s+", " ", n.text(separator=" ", strip=True))
            if len(t) > 2 and (not blocks or blocks[-1] != t):
                blocks.append(t)
    return Page(url=url, title=title, text="\n\n".join(blocks), meta=meta)


async def crawl(start_url: str, max_pages: int = 8, timeout: float = 10.0) -> list[Page]:
    """Fetch the start page and up to max_pages same-site links (about, services, pricing, FAQ, contact first)."""
    if not re.match(r"^https?://", start_url, re.IGNORECASE):
        start_url = "https://" + start_url
    _check_public(start_url)
    host = urlparse(start_url).hostname
    pages: list[Page] = []
    seen: set[str] = set()
    queue = [start_url]
    priority = re.compile(r"about|service|treatment|pricing|price|faq|contact|team|offer", re.IGNORECASE)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                 headers={"User-Agent": "AgentryBot/0.1 (+demo builder)"}) as client:
        while queue and len(pages) < max_pages:
            url = queue.pop(0).split("#")[0]
            if url in seen:
                continue
            seen.add(url)
            try:
                r = await _get_checked(client, url)
            except (httpx.HTTPError, UnsafeUrl):
                continue
            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                continue
            page = extract(r.text[:2_000_000], str(r.url))
            pages.append(page)
            links = []
            for a in HTMLParser(r.text).css("a[href]"):
                href = urljoin(str(r.url), a.attributes.get("href") or "")
                if urlparse(href).hostname == host and href not in seen:
                    links.append(href)
            links.sort(key=lambda h: 0 if priority.search(h) else 1)
            queue.extend(links[:30])
            await asyncio.sleep(0.2)  # be polite
    return pages


async def _get_checked(client: httpx.AsyncClient, url: str, max_redirects: int = 3) -> httpx.Response:
    """GET that re-checks every redirect hop, so a public URL cannot bounce the crawler to an internal one."""
    for _ in range(max_redirects + 1):
        _check_public(url)
        r = await client.get(url)
        if r.is_redirect and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        return r
    raise UnsafeUrl("too many redirects")
