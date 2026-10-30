from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agentry.api import webhooks
from agentry.api.routes import billing_api, business, cold_email, connections, hq, me, org, public, setup, voice, work
from agentry.api.widget import widget_app
from agentry.automations import load_all
from agentry.config import settings
from agentry.llm.gateway import AllModelsFailed


class AppCORS(CORSMiddleware):
    """CORS for Agentry's own sites only, except the chat widget: /widget is called from every client's website and
    has its own open CORS policy (widget.py), so its requests (including preflights) must pass straight through."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/widget/"):
            return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)


app = FastAPI(title="Agentry API", version="0.1.0")
app.add_middleware(
    AppCORS,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Org-Id"],
)
load_all()
for r in (public.router, me.router, org.router, work.router, setup.router, connections.router, business.router,
          billing_api.router, hq.router, voice.router, webhooks.router, cold_email.router):
    app.include_router(r)


app.mount("/widget", widget_app)


@app.exception_handler(AllModelsFailed)
async def models_unavailable(_request, exc: AllModelsFailed) -> JSONResponse:
    """Every model for a tier failed (quota, outage, bad key): a clear, retryable message instead of a server error.
    The failed calls are in app.llm_calls, so `agentry alerts` tells ops."""
    return JSONResponse(status_code=503, content={"detail": "The AI service is unavailable right now. Please try again in a few minutes."})


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/ready")
async def ready() -> dict:
    """Readiness: the database answers (Kubernetes stops routing traffic here when it doesn't)."""
    from agentry.ops import ready as db_ready
    try:
        await db_ready()
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {type(e).__name__}") from e
    return {"ok": True}
