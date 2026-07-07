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

def _get_email_integration():
    """Return the active email NotificationIntegration, or None."""
    from .models import NotificationIntegration
    return NotificationIntegration.objects.filter(
        integration_type='email', is_active=True
    ).first()


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
    from_addr = config.get('smtp_from', 'ReleaseRocket <noreply@releaserocket.local>')
    use_tls  = bool(config.get('use_tls', True))

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"[ReleaseRocket] {subject}"
    msg['From']    = from_addr
    msg['To']      = ', '.join(recipients)

    # Plain text part
    msg.attach(MIMEText(body, 'plain'))

    # HTML part — simple branded wrapper
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:580px;margin:0 auto;color:#e6edf3;background:#0d1117;border-radius:10px;border:1px solid #30363d;overflow:hidden;">
      <div style="background:#161b22;padding:16px 24px;border-bottom:1px solid #30363d;">
        <span style="font-size:1rem;font-weight:700;color:#2f81f7;">🚀 ReleaseRocket</span>
      </div>
      <div style="padding:24px;">
        <h2 style="margin:0 0 12px;font-size:1.1rem;color:#e6edf3;">{subject}</h2>
        <p style="margin:0;font-size:0.9rem;line-height:1.6;color:#8b949e;white-space:pre-wrap;">{body}</p>
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
        logger.info(f"Email sent: '{subject}' → {recipients}")
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

    integration = _get_email_integration()
    if not integration:
        logger.debug("No active email integration — skipping notification.")
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

    _send_smtp(integration.config, recipients, subject, full_body)


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
