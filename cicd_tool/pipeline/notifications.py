"""
pipeline/notifications.py  —  Email notification delivery for ReleaseRocket.

Usage:
    from pipeline.notifications import send_notification

    send_notification(
        event_type = 'pipeline_failure',
        subject    = 'Build failed: my-pipeline',
        body       = 'Pipeline my-pipeline run #abc failed at step "Test".',
        users      = [user_obj],          # list of User instances
        link       = 'http://host/ci/pipeline/run/abc/',
    )

Events matched against UserNotificationPreference fields:
    pipeline_success, pipeline_failure,
    pr_assigned, pr_merged,
    issue_assigned, issue_commented
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

import os
from django.conf import settings

def _get_email_integration_config():
    """Return SMTP config dictionary from active DB model or settings/environment fallbacks."""
    from .models import NotificationIntegration
    integration = NotificationIntegration.objects.filter(
        integration_type='email', is_active=True
    ).first()

    if integration and integration.config:
        return integration.config

    # Dynamic fallback to Django settings or OS Environment
    host = getattr(settings, 'EMAIL_HOST', os.environ.get('EMAIL_HOST', ''))
    if host:
        return {
            'smtp_host': host,
            'smtp_port': int(getattr(settings, 'EMAIL_PORT', os.environ.get('EMAIL_PORT', 587))),
            'smtp_user': getattr(settings, 'EMAIL_HOST_USER', os.environ.get('EMAIL_HOST_USER', '')),
            'smtp_password': getattr(settings, 'EMAIL_HOST_PASSWORD', os.environ.get('EMAIL_HOST_PASSWORD', '')),
            'smtp_from': getattr(settings, 'DEFAULT_FROM_EMAIL', os.environ.get('DEFAULT_FROM_EMAIL', 'CogFocus One <noreply@cogfocus.local>')),
            'use_tls': bool(getattr(settings, 'EMAIL_USE_TLS', os.environ.get('EMAIL_USE_TLS', True))),
        }
    return None


def _user_wants(user, event_type: str) -> bool:
    """
    Check whether `user` has opted in to `event_type`.
    Returns True if no preference record exists (opt-in by default for important events).
    """
    from .models import UserNotificationPreference
    prefs = UserNotificationPreference.for_user(user)
    return bool(getattr(prefs, event_type, True))


def _send_smtp(config: dict, recipients: list[str], subject: str, body: str):
    """
    Send one email via the SMTP settings stored in `config`.

    config keys: smtp_host, smtp_port, smtp_user, smtp_password, smtp_from, use_tls
    """
    host     = config.get('smtp_host', 'localhost')
    port     = int(config.get('smtp_port', 587))
    user     = config.get('smtp_user', '')
    password = config.get('smtp_password', '')
    from_addr = config.get('smtp_from', 'CogFocus One <noreply@cogfocus.local>')
    use_tls  = bool(config.get('use_tls', True))

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"[CogFocus One] {subject}"
    msg['From']    = from_addr
    msg['To']      = ', '.join(recipients)

    # Plain text part
    msg.attach(MIMEText(body, 'plain'))

    # HTML part — CogFocus One white theme branded wrapper
    html = f"""
    <div style="font-family:'Plus Jakarta Sans','Inter',sans-serif;max-width:580px;margin:0 auto;color:#0f172a;background:#ffffff;border-radius:10px;border:1px solid #e2e8f0;box-shadow:0 4px 12px rgba(0,0,0,0.05);overflow:hidden;">
      <div style="background:#0f172a;padding:16px 24px;border-bottom:3px solid #059669;">
        <span style="font-size:1.1rem;font-weight:800;color:#ffffff;letter-spacing:-0.02em;">CogFocus One™</span>
        <span style="font-size:0.75rem;font-weight:700;color:#34d399;text-transform:uppercase;letter-spacing:0.05em;margin-left:0.5rem;">CI/CD &amp; DevOps</span>
      </div>
      <div style="padding:24px;background:#ffffff;">
        <h2 style="margin:0 0 12px;font-size:1.1rem;font-weight:700;color:#0f172a;">{subject}</h2>
        <p style="margin:0;font-size:0.88rem;line-height:1.6;color:#475569;white-space:pre-wrap;">{body}</p>
      </div>
      <div style="background:#f8fafc;padding:12px 24px;border-top:1px solid #e2e8f0;font-size:0.75rem;color:#94a3b8;text-align:center;">
        Sent by CogFocus One™ Executive Suite &bull; Automated System Notification
      </div>
    </div>
    """
    msg.attach(MIMEText(html, 'html'))

    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, recipients, msg.as_string())
        server.quit()
        logger.info(f"Email sent: '{subject}' -> {recipients}")
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def send_notification(event_type: str, subject: str, body: str,
                      users=None, link: str = ''):
    """
    Send an email notification to `users` who have opted in for `event_type`.

    `users` — a User instance, a list of User instances, or None (no email sent).
    `link`  — optional URL appended to the email body.
    """
    if not users:
        return

    config = _get_email_integration_config()
    if not config:
        logger.debug("No active email integration or environment settings — skipping notification.")
        return

    if not isinstance(users, (list, tuple)):
        users = [users]

    # Filter to users who want this event AND have an email address
    recipients = []
    for u in users:
        if u and u.email and _user_wants(u, event_type):
            recipients.append(u.email)

    if not recipients:
        return

    full_body = body
    if link:
        full_body += f"\n\nView: {link}"

    _send_smtp(config, recipients, subject, full_body)


def test_smtp_connection(config: dict) -> tuple[bool, str]:
    """
    Try to connect and authenticate with the given SMTP config.
    Returns (success: bool, message: str).
    """
    host     = config.get('smtp_host', '')
    port     = int(config.get('smtp_port', 587))
    user     = config.get('smtp_user', '')
    password = config.get('smtp_password', '')
    use_tls  = bool(config.get('use_tls', True))

    if not host:
        return False, "SMTP host is required."
    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=8)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=8)
        if user and password:
            server.login(user, password)
        server.quit()
        return True, f"Connected to {host}:{port} successfully."
    except Exception as exc:
        return False, str(exc)
