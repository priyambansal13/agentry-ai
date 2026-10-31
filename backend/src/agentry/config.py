"""Settings, read from environment variables (and ../.env in development)."""
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # repo root
BACKEND = ROOT / "backend"

# Provider keys (OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, ...) are read by LiteLLM from the process
# environment, so load the repo .env into it. Real environment variables win over the file.
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="AGENTRY_", extra="ignore")

    env: str = "dev"
    db_host: str = "localhost"
    db_port: int = 55432
    db_name: str = "agentry"
    db_owner_password: str = "postgres"
    db_app_password: str = "agentry_app"
    db_system_password: str = "agentry_system"

    # Better Auth runs inside the dashboard app; the API verifies its JWTs with this JWKS endpoint.
    auth_jwks_url: str = "http://localhost:3201/api/auth/jwks"
    auth_issuer: str = "http://localhost:3201"
    auth_audience: str = "http://localhost:3201"

    cors_origins: list[str] = ["http://localhost:3200", "http://localhost:3201"]

    # Voice (Phase 4): LiveKit carries the audio; speech via OpenAI by default (any provider later, see PHASE-4-VOICE.md).
    # Dev defaults match `livekit-server --dev`; production must set real keys. AGENTRY_LIVEKIT_* wins, else LiveKit's
    # own LIVEKIT_* names (what LiveKit Cloud's dashboard tells you to copy).
    livekit_url: str = Field("ws://localhost:7880", validation_alias=AliasChoices("AGENTRY_LIVEKIT_URL", "LIVEKIT_URL"))
    # what browsers connect to, if different from the worker's address
    livekit_public_url: str | None = Field(None, validation_alias=AliasChoices("AGENTRY_LIVEKIT_PUBLIC_URL", "LIVEKIT_PUBLIC_URL"))
    livekit_api_key: str = Field("devkey", validation_alias=AliasChoices("AGENTRY_LIVEKIT_API_KEY", "LIVEKIT_API_KEY"))
    livekit_api_secret: str = Field("secret", validation_alias=AliasChoices("AGENTRY_LIVEKIT_API_SECRET", "LIVEKIT_API_SECRET"))
    voice_stt_model: str = "gpt-4o-mini-transcribe"
    voice_tts_model: str = "gpt-4o-mini-tts"
    voice_tts_voice: str = "ash"
    voice_language: str = "en"
    voice_record: bool = True  # record calls (the greeting always says "this call may be recorded")
    recordings_dir: str = str(ROOT / "var" / "recordings")  # production: a mounted volume (object storage later)
    voice_idle_processes: int = 2  # warm processes ready for the next call (LiveKit's default is one per CPU core)
    voice_load_threshold: float | None = None  # stop taking new calls above this CPU load (0-1); default: 0.85 in production, never in dev

    # Platform email. One SMTP setup serves the API and the dashboard: AGENTRY_SMTP_* wins, else the dashboard's SMTP_*.
    # Empty user = no login (Mailpit in development); port 587 upgrades to TLS (STARTTLS) automatically.
    smtp_host: str = Field("localhost", validation_alias=AliasChoices("AGENTRY_SMTP_HOST", "SMTP_HOST"))
    smtp_port: int = Field(51025, validation_alias=AliasChoices("AGENTRY_SMTP_PORT", "SMTP_PORT"))
    smtp_user: str | None = Field(None, validation_alias=AliasChoices("AGENTRY_SMTP_USER", "SMTP_USER"))
    smtp_password: str | None = Field(None, validation_alias=AliasChoices("AGENTRY_SMTP_PASSWORD", "SMTP_PASSWORD"))
    smtp_starttls: bool | None = Field(None, validation_alias=AliasChoices("AGENTRY_SMTP_STARTTLS"))
    mail_from: str = Field("Agentry <hello@agentry.dev>", validation_alias=AliasChoices("AGENTRY_MAIL_FROM", "MAIL_FROM"))
    ops_email: str = "ops@agentry.dev"  # where new demo requests are announced
    ops_telegram_chat_id: str | None = None  # Agentry's own ops alerts (agentry alerts)
    telegram_bot_token: str | None = None  # AGENTRY_TELEGRAM_BOT_TOKEN: Agentry's team bot (alerts, cards, Tools menu)
    telegram_webhook_secret: str = "dev-only-telegram-secret"  # checked on every webhook call (X-Telegram-Bot-Api-Secret-Token)
    # "polling": the worker asks Telegram for updates every few seconds (local development: no public address);
    # "webhook": Telegram calls {api_public_url}/webhooks/telegram/... (production). Default: webhook when the API is public.
    telegram_mode: str | None = None
    widget_secret: str = "dev-only-widget-secret-change-me"  # signs website-chat conversation tokens

    # Connections (Phase 1b)
    encryption_key: str | None = None  # Fernet key for stored OAuth/API tokens
    api_public_url: str = "http://localhost:8801"  # OAuth redirect + webhook base
    dashboard_url: str = "http://localhost:3201"
    web_url: str = "http://localhost:3200"  # the public website: demo pages (/demo/<slug>) linked from sales emails
    sales_signature: str = "The Agentry team"  # how Agentry's own sales emails are signed, e.g. "Priyam, Agentry"
    imap_host: str | None = None  # where replies to sales emails are read (default: imap.gmail.com when sending through Gmail)
    sales_inbox_minutes: int = 2  # how often the sales inbox is checked for replies (0 = never)
    # Cold email (Phase 5): "mock" runs prospecting on mock-data/cold-email/ (no keys, no cost). Real providers: 5.6.
    cold_email_providers: str = "mock"
    # Content repurposing (Phase 6): uploads, transcripts and images; transcription with the OpenAI key ("mock" = the
    # sample podcast, used by tests); publishing is "mock" (recorded at the slot time) until social accounts are connected
    content_dir: str = str(ROOT / "var" / "content")
    documents_dir: str = str(ROOT / "var" / "documents")  # receipts and bills (Document AI); production: a mounted volume
    content_transcriber: str = "openai"
    content_transcribe_model: str = "whisper-1"  # gives timestamped segments
    content_publisher: str = "mock"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    gmail_poll_seconds: int = 60
    # Outlook / Microsoft 365 (#6): an app registration in Microsoft Entra (docs/setup/outlook.md)
    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None
    microsoft_tenant: str = "common"  # "common" = any work, school or personal Microsoft account
    # Gmail push (#5): Google Cloud Pub/Sub topic Gmail publishes to, and the secret in the push endpoint URL
    gmail_pubsub_topic: str | None = None  # projects/<project>/topics/<topic>
    gmail_push_token: str | None = None
    whatsapp_app_secret: str | None = None  # verifies X-Hub-Signature-256 on webhooks
    whatsapp_verify_token: str | None = None  # Meta's webhook subscription handshake
    whatsapp_graph_version: str = "v23.0"
    # Instagram publishing (6.5): the Meta app (same app as WhatsApp) + its Facebook Login for Business configuration
    meta_app_id: str | None = None
    meta_app_secret: str | None = None  # defaults to whatsapp_app_secret (one Meta app)
    instagram_config_id: str | None = None

    # Agentry's own billing (charging clients). Each optional: without keys, statements are issued without a pay link.
    company_name: str = "Agentry"
    company_gstin: str | None = None
    billing_razorpay_key_id: str | None = None
    billing_razorpay_key_secret: str | None = None
    billing_razorpay_webhook_secret: str | None = None
    billing_stripe_secret_key: str | None = None
    billing_stripe_webhook_secret: str | None = None
    usd_to_inr: float = 85.0  # for margin views (LLM costs are in USD)
    # rough conversion for margin reports only (never for billing amounts)
    fx_to_inr: dict[str, float] = {"INR": 1, "USD": 85, "EUR": 92, "GBP": 108, "AED": 23}
    whatsapp_template_cost_inr: float = 0.9  # rough per-template cost for margin views; check Meta's current rates
    voice_cost_inr_per_minute: float = 2.0  # rough speech + telephony cost per call minute, margin views only; check current rates

    # Model tiers: comma-separated LiteLLM model strings, tried in order (primary first, then fallbacks), e.g.
    # AGENTRY_MODEL_FAST="gemini/<model>,openai/<model>". Unset tiers run in mock mode (no network, no cost).
    # A client can override any tier in app.org_settings.llm_models.
    model_fast: str | None = None
    model_writer: str | None = None
    model_conversation: str | None = None
    model_voice: str | None = None  # phone calls: a fast, non-reasoning model keeps replies under ~2 s (unset = conversation)
    model_vision: str | None = None
    model_embed: str | None = None
    embed_dimensions: int = 768  # must match app.kb_chunks.embedding

    def _url(self, user: str, password: str, driver: str = "psycopg") -> str:
        return f"postgresql+{driver}://{user}:{quote(password, safe='')}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def migrate_database_url(self) -> str:
        return self._url("postgres", self.db_owner_password)

    @property
    def app_database_url(self) -> str:
        return self._url("agentry_app", self.db_app_password)

    @property
    def system_database_url(self) -> str:
        return self._url("agentry_system", self.db_system_password)

    @property
    def dbos_database_url(self) -> str:
        return f"postgresql://agentry_system:{quote(self.db_system_password, safe='')}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()
