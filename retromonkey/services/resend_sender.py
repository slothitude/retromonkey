"""Resend email sender — send from any @retromonkey.com.au address."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "orders@retromonkey.com.au"


def send_email(
    to: str,
    subject: str,
    html: str = "",
    text: str = "",
    from_addr: str | None = None,
    reply_to: str | None = None,
) -> dict:
    """Send an email via the Resend API.

    Parameters
    ----------
    to : str
        Recipient email address.
    subject : str
        Email subject line.
    html : str
        HTML body (takes precedence over text if both provided).
    text : str
        Plain-text body (fallback if no html).
    from_addr : str, optional
        Sender address — any @retromonkey.com.au address.
        Defaults to ``orders@retromonkey.com.au``.
    reply_to : str, optional
        Reply-To header.

    Returns
    -------
    dict
        ``{"id": "resend-message-id"}`` on success.

    Raises
    ------
    RuntimeError
        If ``RESEND_API_KEY`` is not configured.
    httpx.HTTPStatusError
        If the Resend API returns a non-2xx status.
    """
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not configured")

    sender = from_addr or DEFAULT_FROM
    body = html if html else text
    if not body:
        raise ValueError("Must provide html or text body")

    payload = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to

    resp = httpx.post(
        RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info("Resend email sent: id=%s from=%s to=%s", data.get("id"), sender, to)
    return data
