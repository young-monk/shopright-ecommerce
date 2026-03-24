"""Gmail SMTP email tool — reads credentials from Secret Manager at runtime."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_smtp_user: str | None = None
_smtp_pass: str | None = None


def _get_creds() -> tuple[str, str]:
    global _smtp_user, _smtp_pass
    if _smtp_user and _smtp_pass:
        return _smtp_user, _smtp_pass

    project = os.getenv("GCP_PROJECT_ID", "")

    # Allow local override via env vars (useful for testing)
    env_user = os.getenv("GMAIL_SENDER")
    env_pass = os.getenv("GMAIL_APP_PASSWORD")
    if env_user and env_pass:
        _smtp_user, _smtp_pass = env_user, env_pass
        return _smtp_user, _smtp_pass

    from google.cloud import secretmanager  # lazy import — not installed locally
    client = secretmanager.SecretManagerServiceClient()
    _smtp_user = client.access_secret_version(
        name=f"projects/{project}/secrets/gmail-sender/versions/latest"
    ).payload.data.decode("utf-8").strip()
    _smtp_pass = client.access_secret_version(
        name=f"projects/{project}/secrets/gmail-app-password/versions/latest"
    ).payload.data.decode("utf-8").strip()
    return _smtp_user, _smtp_pass


def send_email(to: str, subject: str, html_body: str) -> dict:
    """
    Send an HTML email via Gmail SMTP using the configured app password.

    Args:
        to: Recipient email address (comma-separated for multiple).
        subject: Email subject line.
        html_body: Full HTML content for the email body.

    Returns:
        dict with 'success' bool and optional 'error' message.
    """
    try:
        smtp_user, smtp_pass = _get_creds()
        recipients = [r.strip() for r in to.split(",")]

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"ShopRight Analytics <{smtp_user}>"
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())

        logger.info("Email sent to %s: %s", to, subject)
        return {"success": True}
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return {"success": False, "error": str(exc)}
