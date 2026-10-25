"""Platform email (development: Mailpit). Client-facing email goes through the client's own mailbox, not this."""
import logging
import smtplib
from email.message import EmailMessage

from agentry.config import settings

log = logging.getLogger("agentry.email")
# RFC 2606/6761 names that can never receive mail: demo clients and test data use them
RESERVED = (".example", ".test", ".invalid", ".localhost", "@example.com", "@example.org", "@example.net")


def undeliverable(to: str) -> bool:
    """A demo/test address while a real mail server is configured: sending would only bounce back to Agentry's inbox.
    The local Mailpit (development and tests) still receives everything."""
    real = settings.smtp_host not in ("localhost", "127.0.0.1", "mailpit")
    return real and to.strip().lower().endswith(RESERVED)


def send_email(to: str, subject: str, body: str) -> None:
    if undeliverable(to):
        log.info("not emailing %s (reserved demo/test domain): %s", to, subject)
        return
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls or (settings.smtp_starttls is None and settings.smtp_port == 587):
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)
