"""Transactional email: one generic HTTP provider, with a console fallback.

Deviation from the original design: Pave is not tied to Resend. It POSTs a
JSON message to whatever endpoint EMAIL_API_URL names, authorised with
EMAIL_API_KEY. When either is unset (the default for a fresh clone and for
tests) nothing is sent: the full message is logged as JSON so verification
and reset links are still reachable in development.

Templates are hand-written: a bulletproof table-based `.html` part and a
matching `.txt` part per message. No MJML, no Node build step.
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.settings import settings
from app.templating import templates

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str


def build_payload(msg: EmailMessage) -> dict[str, str]:
    """The JSON body sent to the provider. Generic on purpose: `from`, `to`,
    `subject`, `html`, `text` is the intersection every provider accepts."""
    return {
        "from": settings.email_from,
        "to": msg.to,
        "subject": msg.subject,
        "html": msg.html,
        "text": msg.text,
    }


def render_email(
    template: str, *, subject: str, to: str, **context: Any
) -> EmailMessage:
    """Render the `.html` and `.txt` parts of `templates/email/{template}`."""
    html = templates.get_template(f"email/{template}.html").render(**context)
    text = templates.get_template(f"email/{template}.txt").render(**context)
    return EmailMessage(to=to, subject=subject, html=html, text=text)


async def send_email(msg: EmailMessage) -> None:
    payload = build_payload(msg)

    if not (settings.email_api_url and settings.email_api_key):
        if settings.debug:
            # Dev convenience: print the whole message so verification/reset
            # links are reachable without a provider.
            log.info(
                "email.console",
                to=msg.to,
                subject=msg.subject,
                message=json.dumps(payload),
            )
        else:
            # Never log the body in production: it carries live tokens. Surface
            # the misconfiguration instead of silently leaking links to logs.
            log.warning("email.unconfigured", to=msg.to, subject=msg.subject)
        return

    if not settings.debug and not settings.email_api_url.startswith("https://"):
        # The API key rides in an Authorization header; http would leak it.
        raise RuntimeError("EMAIL_API_URL must use https in production")

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            settings.email_api_url,
            headers={"Authorization": f"Bearer {settings.email_api_key}"},
            json=payload,
        )
        response.raise_for_status()
