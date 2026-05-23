"""Gmail client — OAuth 2.0, read, send, label management."""

import base64
import json
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from retromonkey.app import db

logger = logging.getLogger(__name__)

# Token storage path
TOKEN_PATH = os.path.join(Path(__file__).resolve().parent.parent.parent, "instance", "gmail_tokens.json")


class GmailClient:
    """Gmail API client with OAuth 2.0 support."""

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.labels",
        "https://www.googleapis.com/auth/gmail.modify",
    ]

    def __init__(self, db_instance, config=None):
        self.db = db_instance or db
        self._config = config
        self._credentials = None
        self._service = None

    # ------------------------------------------------------------------
    # OAuth 2.0
    # ------------------------------------------------------------------

    def get_auth_url(self, redirect_uri: str | None = None) -> str:
        """Generate the Google OAuth 2.0 authorization URL.

        Returns
        -------
        str
            URL the user must visit to grant Gmail permissions.
        """
        from flask import current_app

        config = self._config or current_app.config
        client_id = config.get("GOOGLE_CLIENT_ID", "")
        redirect = redirect_uri or config.get(
            "GMAIL_REDIRECT_URI",
            "http://localhost:5000/api/intelligence/gmail/callback",
        )

        scope_str = " ".join(self.SCOPES)
        return (
            f"https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect}"
            f"&response_type=code"
            f"&scope={scope_str}"
            f"&access_type=offline"
            f"&prompt=consent"
        )

    def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Exchange an authorization code for access/refresh tokens.

        Stores tokens to ``TOKEN_PATH`` for reuse.
        """
        import requests as http_requests
        from flask import current_app

        config = self._config or current_app.config
        redirect = redirect_uri or config.get(
            "GMAIL_REDIRECT_URI",
            "http://localhost:5000/api/intelligence/gmail/callback",
        )

        resp = http_requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": config.get("GOOGLE_CLIENT_ID", ""),
                "client_secret": config.get("GOOGLE_CLIENT_SECRET", ""),
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        tokens = resp.json()

        self._save_tokens(tokens)
        self._credentials = tokens
        return tokens

    def _get_service(self):
        """Get or build an authenticated Gmail service object."""
        if self._service:
            return self._service

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError("google-api-python-client and google-auth are required for Gmail integration")

        tokens = self._load_tokens()
        if not tokens:
            raise RuntimeError("Gmail not authenticated. Complete OAuth flow first.")

        # Refresh if expired
        if tokens.get("expires_in") and tokens.get("refresh_token"):
            import time
            # We store a simple approach: just use refresh token
            pass

        creds = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=tokens.get("client_id", ""),
            client_secret=tokens.get("client_secret", ""),
        )

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def list_messages(
        self,
        query: str = "is:unread",
        max_results: int = 20,
        label_ids: list[str] | None = None,
    ) -> list[dict]:
        """List Gmail messages matching a query.

        Parameters
        ----------
        query : str
            Gmail search query (default: unread messages).
        max_results : int
            Maximum messages to return.
        label_ids : list[str], optional
            Filter by label IDs.

        Returns
        -------
        list[dict]
            Message summaries with id, threadId, snippet.
        """
        service = self._get_service()
        params = {"userId": "me", "maxResults": max_results, "q": query}
        if label_ids:
            params["labelIds"] = label_ids

        results = service.users().messages().list(**params).execute()
        messages = results.get("messages", [])

        summaries = []
        for msg in messages:
            try:
                detail = service.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()
                headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
                summaries.append({
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": detail.get("snippet", ""),
                    "label_ids": detail.get("labelIds", []),
                })
            except Exception as exc:
                logger.warning("Failed to fetch message %s: %s", msg["id"], exc)

        return summaries

    def get_message_body(self, message_id: str) -> str:
        """Get the plain-text body of a Gmail message."""
        service = self._get_service()
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        return self._extract_body(msg.get("payload", {}))

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain text from a message payload."""
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Fallback: try HTML
        for part in parts:
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Recurse into nested parts
        for part in parts:
            result = self._extract_body(part)
            if result:
                return result

        return ""

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> dict:
        """Send an email via Gmail.

        Parameters
        ----------
        to : str
            Recipient email address.
        subject : str
            Email subject.
        body : str
            Plain-text body.
        thread_id : str, optional
            Gmail thread ID for threading.
        reply_to_message_id : str, optional
            Message ID being replied to (for threading).

        Returns
        -------
        dict
            Sent message details.
        """
        service = self._get_service()

        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject

        if reply_to_message_id:
            # Fetch original message headers for threading
            original = service.users().messages().get(
                userId="me", id=reply_to_message_id, format="metadata",
                metadataHeaders=["From", "Subject", "Message-Id", "References"]
            ).execute()
            orig_headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
            message["In-Reply-To"] = orig_headers.get("Message-Id", "")
            message["References"] = orig_headers.get("References", "") + " " + orig_headers.get("Message-Id", "")
            if not thread_id:
                thread_id = original.get("threadId")

        message.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        sent = service.users().messages().send(userId="me", body=send_body).execute()

        return {
            "id": sent["id"],
            "thread_id": sent.get("threadId"),
            "label_ids": sent.get("labelIds", []),
        }

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    def apply_label(self, message_id: str, label_name: str) -> dict:
        """Apply a label to a message. Creates the label if it doesn't exist."""
        service = self._get_service()

        # Find or create label
        label_id = self._get_or_create_label(label_name)

        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()

        return {"message_id": message_id, "label": label_name, "label_id": label_id}

    def _get_or_create_label(self, name: str) -> str:
        """Get a label ID by name, creating it if necessary."""
        service = self._get_service()
        labels = service.users().labels().list(userId="me").execute().get("labels", [])

        for label in labels:
            if label["name"].lower() == name.lower():
                return label["id"]

        new_label = service.users().labels().create(
            userId="me",
            body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
        return new_label["id"]

    # ------------------------------------------------------------------
    # Token persistence
    # ------------------------------------------------------------------

    def _save_tokens(self, tokens: dict) -> None:
        """Persist tokens to disk."""
        from flask import current_app

        config = self._config or current_app.config
        tokens["client_id"] = config.get("GOOGLE_CLIENT_ID", "")
        tokens["client_secret"] = config.get("GOOGLE_CLIENT_SECRET", "")

        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as fh:
            json.dump(tokens, fh, indent=2)

    @staticmethod
    def _load_tokens() -> dict | None:
        """Load persisted tokens from disk."""
        if not os.path.exists(TOKEN_PATH):
            return None
        with open(TOKEN_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
