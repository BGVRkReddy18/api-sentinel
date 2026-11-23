"""Alert delivery channels: log, Slack/Discord webhook, and email (Brevo HTTPS API or SMTP)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import TYPE_CHECKING, Protocol

import httpx

from app.core.logging import log_extra
from app.domain import AlertKind, AlertSeverity
from app.services.email_templates import render_alert_email

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AlertEvent:
    alert_id: int
    kind: AlertKind
    severity: AlertSeverity
    endpoint_id: int
    endpoint_name: str
    endpoint_url: str
    message: str
    created_at: datetime
    recipients: tuple[str, ...] = ()  # the endpoint's alert contacts
    is_test: bool = False


class Notifier(Protocol):
    async def notify(self, event: AlertEvent) -> bool: ...


class LogNotifier:
    async def notify(self, event: AlertEvent) -> bool:
        logger.warning(
            "ALERT %s",
            event.message,
            extra=log_extra(alert_kind=event.kind.value, endpoint_id=event.endpoint_id),
        )
        return True


class WebhookNotifier:
    """Posts a JSON payload compatible with Slack ("text") and Discord ("content") webhooks."""

    def __init__(self, client: httpx.AsyncClient, url: str, timeout_seconds: float = 5.0) -> None:
        self._client = client
        self._url = url
        self._timeout = timeout_seconds

    @staticmethod
    def build_payload(event: AlertEvent) -> dict:
        icon = {"critical": "🔴", "warning": "🟠", "info": "🟢"}[event.severity.value]
        text = f"{icon} [{event.severity.value.upper()}] {event.message}"
        return {
            "text": text,
            "content": text,
            "alert": {
                "id": event.alert_id,
                "kind": event.kind.value,
                "severity": event.severity.value,
                "endpoint_id": event.endpoint_id,
                "endpoint_name": event.endpoint_name,
                "endpoint_url": event.endpoint_url,
                "created_at": event.created_at.isoformat(),
            },
        }

    async def notify(self, event: AlertEvent) -> bool:
        try:
            response = await self._client.post(
                self._url, json=self.build_payload(event), timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            logger.error("webhook delivery failed", extra=log_extra(error=str(exc)))
            return False
        if response.is_error:
            logger.error("webhook rejected alert", extra=log_extra(status=response.status_code))
            return False
        return True


# ------------------------------------------------------------------ email


class EmailDeliveryError(RuntimeError):
    pass


class EmailSender(Protocol):
    async def send(self, to: list[str], subject: str, html: str, text: str) -> None: ...


class BrevoSender:
    """Brevo transactional email over HTTPS - works where SMTP ports are blocked (Render free tier)."""

    URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, client: httpx.AsyncClient, api_key: str, from_email: str, from_name: str) -> None:
        self._client = client
        self._api_key = api_key
        self._sender = {"email": from_email, "name": from_name}

    async def send(self, to: list[str], subject: str, html: str, text: str) -> None:
        payload = {
            "sender": self._sender,
            "to": [{"email": address} for address in to],
            "subject": subject,
            "htmlContent": html,
            "textContent": text,
        }
        try:
            response = await self._client.post(
                self.URL,
                json=payload,
                headers={"api-key": self._api_key, "accept": "application/json"},
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(f"Brevo unreachable: {exc}") from exc
        if response.is_error:
            raise EmailDeliveryError(
                f"Brevo rejected the email (HTTP {response.status_code}): {response.text[:200]}"
            )


class SmtpSender:
    """Plain SMTP (Gmail app password, Mailtrap, your own server). Blocked on many free PaaS tiers."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        from_email: str,
        from_name: str,
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._use_tls = use_tls
        self._from = formataddr((from_name, from_email))

    async def send(self, to: list[str], subject: str, html: str, text: str) -> None:
        try:
            await asyncio.to_thread(self._send_sync, to, subject, html, text)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(f"SMTP delivery failed: {exc}") from exc

    def _send_sync(self, to: list[str], subject: str, html: str, text: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._from
        message["To"] = ", ".join(to)
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        context = ssl.create_default_context()
        if self._port == 465:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=15, context=context) as smtp:
                self._login_and_send(smtp, message)
        else:
            with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
                if self._use_tls:
                    smtp.starttls(context=context)
                self._login_and_send(smtp, message)

    def _login_and_send(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self._username and self._password:
            smtp.login(self._username, self._password)
        smtp.send_message(message)


class EmailNotifier:
    """Emails each alert to the endpoint's own contacts (plus an optional global address)."""

    def __init__(
        self, sender: EmailSender, *, always_to: list[str] | None = None, base_url: str | None = None
    ) -> None:
        self._sender = sender
        self._always_to = always_to or []
        self._base_url = base_url

    def recipients_for(self, event: AlertEvent) -> list[str]:
        seen: list[str] = []
        for address in (*event.recipients, *self._always_to):
            if address and address not in seen:
                seen.append(address)
        return seen

    async def notify(self, event: AlertEvent) -> bool:
        to = self.recipients_for(event)
        if not to:
            return True  # nobody subscribed - nothing to deliver
        subject, html, text = render_alert_email(event, self._base_url)
        try:
            await self._sender.send(to, subject, html, text)
        except EmailDeliveryError as exc:
            logger.error("alert email failed", extra=log_extra(error=str(exc), recipients=len(to)))
            return False
        logger.info("alert email sent", extra=log_extra(kind=event.kind.value, recipients=len(to)))
        return True


class CompositeNotifier:
    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    async def notify(self, event: AlertEvent) -> bool:
        delivered = True
        for notifier in self._notifiers:
            delivered = await notifier.notify(event) and delivered
        return delivered


def build_email_notifier(settings: Settings, client: httpx.AsyncClient) -> EmailNotifier | None:
    if settings.email_provider == "none" or not settings.email_from:
        return None
    sender: EmailSender
    if settings.email_provider == "brevo":
        if settings.brevo_api_key is None:
            logger.warning("email_provider=brevo but SENTINEL_BREVO_API_KEY is not set; email disabled")
            return None
        sender = BrevoSender(
            client, settings.brevo_api_key.get_secret_value(), settings.email_from, settings.email_from_name
        )
    else:
        if not settings.smtp_host:
            logger.warning("email_provider=smtp but SENTINEL_SMTP_HOST is not set; email disabled")
            return None
        sender = SmtpSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_username,
            settings.smtp_password.get_secret_value() if settings.smtp_password else None,
            settings.smtp_use_tls,
            settings.email_from,
            settings.email_from_name,
        )
    always = [settings.alert_email_to] if settings.alert_email_to else []
    return EmailNotifier(sender, always_to=always, base_url=settings.public_base_url)


def build_notifier(
    settings: Settings, client: httpx.AsyncClient, email: EmailNotifier | None = None
) -> Notifier:
    notifiers: list[Notifier] = [LogNotifier()]
    if settings.alert_webhook_url:
        notifiers.append(WebhookNotifier(client, settings.alert_webhook_url))
    if email is not None:
        notifiers.append(email)
    return CompositeNotifier(*notifiers)
