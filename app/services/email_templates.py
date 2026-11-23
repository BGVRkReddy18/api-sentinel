"""HTML + plain-text alert emails (inline styles: email clients ignore <style> blocks)."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.notifier import AlertEvent

_STYLE = {
    "down": ("#e5484d", "🔴", "DOWN"),
    "recovered": ("#30a46c", "🟢", "RECOVERED"),
    "latency_anomaly": ("#f5a524", "🟠", "LATENCY ANOMALY"),
    "ssl_expiring": ("#f5a524", "🔒", "TLS CERTIFICATE"),
}


def render_alert_email(event: AlertEvent, base_url: str | None) -> tuple[str, str, str]:
    """Return (subject, html, text) for an alert."""
    color, icon, label = _STYLE.get(event.kind.value, ("#6e56cf", "🔔", event.kind.value.upper()))
    prefix = "[TEST] " if event.is_test else ""
    subject = f"{prefix}{icon} {label}: {event.endpoint_name}"
    when = event.created_at.strftime("%d %b %Y, %H:%M:%S UTC")
    link = f"{base_url.rstrip('/')}/endpoints/{event.endpoint_id}" if base_url else None
    status_link = f"{base_url.rstrip('/')}/status" if base_url else None

    text_lines = [
        f"{prefix}{label}: {event.endpoint_name}",
        "",
        event.message,
        "",
        f"URL:  {event.endpoint_url}",
        f"Time: {when}",
    ]
    if link:
        text_lines += ["", f"Dashboard: {link}"]
    text_lines += ["", "You receive this because you are an alert contact for this endpoint in API Sentinel."]
    text = "\n".join(text_lines)

    button = (
        f'<a href="{escape(link)}" style="display:inline-block;background:#111113;color:#ffffff;'
        f'text-decoration:none;padding:10px 18px;border-radius:8px;font-weight:600;font-size:14px">'
        f"Open in dashboard &rarr;</a>"
        if link
        else ""
    )
    status = (
        f' &nbsp;<a href="{escape(status_link)}" style="color:#6e6e76;font-size:13px">Status page</a>'
        if status_link
        else ""
    )
    test_banner = (
        '<div style="background:#f4f0ff;color:#5b3fd6;padding:8px 24px;font-size:13px">'
        "This is a test alert - your email alerts are working.</div>"
        if event.is_test
        else ""
    )
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#18181b">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">
<table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e4e4e7">
<tr><td style="height:4px;background:{color}"></td></tr>
{f"<tr><td>{test_banner}</td></tr>" if test_banner else ""}
<tr><td style="padding:24px 24px 8px">
  <div style="font-size:12px;letter-spacing:.06em;font-weight:700;color:{color}">{icon} {escape(label)}</div>
  <div style="font-size:20px;font-weight:700;margin-top:6px">{escape(event.endpoint_name)}</div>
  <div style="font-size:13px;color:#6e6e76;margin-top:2px;word-break:break-all">{escape(event.endpoint_url)}</div>
</td></tr>
<tr><td style="padding:12px 24px">
  <div style="background:#fafafa;border:1px solid #f0f0f2;border-radius:8px;padding:14px 16px;font-size:14px;line-height:1.5">
    {escape(event.message)}
  </div>
  <div style="font-size:13px;color:#6e6e76;margin-top:10px">{escape(when)}</div>
</td></tr>
<tr><td style="padding:12px 24px 24px">{button}{status}</td></tr>
<tr><td style="padding:14px 24px;background:#fafafa;border-top:1px solid #f0f0f2;font-size:12px;color:#8b8b93">
  You receive this because you are an alert contact for <b>{escape(event.endpoint_name)}</b> in API Sentinel.
</td></tr>
</table></td></tr></table>
</body></html>"""
    return subject, html, text
