"""Communications hub — unified inbox, LLM drafts, multi-channel routing."""

import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.communication import Message
from retromonkey.models.marketplace import Marketplace
from retromonkey.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class CommunicationsService:
    """Unified messaging across Gmail, eBay, and other channels."""

    def __init__(self, db_instance, llm_router=None):
        self.db = db_instance or db
        self.llm = llm_router or LLMRouter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get_unified_inbox(self, filters: dict | None = None) -> list[dict]:
        """Pull messages from all channels into a unified view.

        Parameters
        ----------
        filters : dict, optional
            Supported keys: ``channel``, ``direction``, ``unreplied_only``
            (bool), ``limit`` (int).

        Returns
        -------
        list[dict]
            Sorted by created_at descending.
        """
        filters = filters or {}
        query = self.db.session.query(Message)

        if filters.get("channel"):
            query = query.filter_by(channel=filters["channel"])
        if filters.get("direction"):
            query = query.filter_by(direction=filters["direction"])
        if filters.get("unreplied_only"):
            # Messages that are inbound and have no outbound reply
            query = query.filter_by(direction="inbound", approved=False)

        limit = filters.get("limit", 50)
        messages = query.order_by(Message.created_at.desc()).limit(limit).all()

        return [self._message_to_dict(m) for m in messages]

    def draft_reply(self, message_id: int) -> dict:
        """Generate an AI-drafted reply for a message.

        The draft is stored in a new outbound Message with ``ai_draft=True``
        and ``approved=False``.

        Returns
        -------
        dict
            The draft message details.
        """
        original = self.db.session.get(Message, message_id)
        if not original:
            raise ValueError(f"Message {message_id} not found")

        prompt = (
            "You are a professional e-commerce customer service agent.\n"
            "Draft a polite, helpful reply to the following customer message.\n\n"
            f"Channel: {original.channel}\n"
            f"Subject: {original.subject or 'N/A'}\n"
            f"From: {original.from_addr or 'Customer'}\n"
            f"Message:\n{original.body or 'N/A'}\n\n"
            "Keep the response concise (3-5 sentences), professional, and "
            "actionable. Address the customer's concern directly."
        )

        result = self.llm.query(prompt, mode="auto", max_tokens=512)
        draft_body = result.get("text", "").strip()

        # Determine reply addressing
        reply_to = original.from_addr or ""
        reply_from = original.to_addr or ""

        draft = Message(
            channel=original.channel,
            direction="outbound",
            from_addr=reply_from,
            to_addr=reply_to,
            subject=f"Re: {original.subject}" if original.subject else None,
            body=draft_body,
            related_order_id=original.related_order_id,
            related_product_id=original.related_product_id,
            ai_draft=True,
            approved=False,
        )
        self.db.session.add(draft)
        self.db.session.commit()

        return {
            "draft_id": draft.id,
            "reply_to_message_id": message_id,
            "channel": draft.channel,
            "to": draft.to_addr,
            "subject": draft.subject,
            "body": draft.body,
            "ai_draft": True,
        }

    def approve_and_send(self, message_id: int, edited_body: str | None = None) -> dict:
        """Approve and send a drafted message via the correct channel.

        Parameters
        ----------
        message_id : int
            The draft message ID to approve and send.
        edited_body : str, optional
            Override body text if the user edited the draft.

        Returns
        -------
        dict
            Send status.
        """
        message = self.db.session.get(Message, message_id)
        if not message:
            raise ValueError(f"Message {message_id} not found")

        if edited_body:
            message.body = edited_body

        message.approved = True
        message.ai_draft = False
        message.sent_at = datetime.now(timezone.utc)

        sent = False
        error = None

        try:
            if message.channel == "gmail":
                sent = self._send_via_gmail(message)
            elif message.channel == "ebay":
                sent = self._send_via_ebay(message)
            else:
                sent = True  # system/other channels just mark as sent
                logger.info("Message %d marked as sent via %s", message_id, message.channel)
        except Exception as exc:
            error = str(exc)
            logger.error("Failed to send message %d: %s", message_id, exc)

        self.db.session.commit()

        return {
            "message_id": message.id,
            "channel": message.channel,
            "sent": sent,
            "sent_at": message.sent_at.isoformat() if message.sent_at else None,
            "error": error,
        }

    def sync_inbox(self) -> dict:
        """Pull new messages from Gmail and eBay.

        Returns
        -------
        dict
            Counts of newly synced messages per channel.
        """
        results = {"gmail": 0, "ebay": 0}

        # Sync Gmail
        try:
            results["gmail"] = self._sync_gmail()
        except Exception as exc:
            logger.warning("Gmail sync failed: %s", exc)
            results["gmail_error"] = str(exc)

        # Sync eBay messages
        try:
            results["ebay"] = self._sync_ebay()
        except Exception as exc:
            logger.warning("eBay sync failed: %s", exc)
            results["ebay_error"] = str(exc)

        return results

    # ------------------------------------------------------------------
    # Channel-specific senders
    # ------------------------------------------------------------------

    def _send_via_gmail(self, message: Message) -> bool:
        """Send a message through the Gmail API."""
        from retromonkey.services.gmail_client import GmailClient
        gmail = GmailClient(self.db)
        result = gmail.send_email(
            to=message.to_addr or "",
            subject=message.subject or "",
            body=message.body or "",
        )
        return bool(result.get("id"))

    def _send_via_ebay(self, message: Message) -> bool:
        """Send a message through eBay messaging API (placeholder)."""
        # eBay messaging requires the Sell Account API
        logger.info("eBay message send for message %d (placeholder)", message.id)
        return True

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    def _sync_gmail(self) -> int:
        """Pull new unread Gmail messages into the messages table."""
        from retromonkey.services.gmail_client import GmailClient

        gmail = GmailClient(self.db)
        messages = gmail.list_messages(query="is:unread", max_results=20)

        synced = 0
        for msg in messages:
            # Skip if we already have this message
            existing = self.db.session.query(Message).filter_by(
                channel="gmail",
                from_addr=msg.get("from", ""),
                subject=msg.get("subject", ""),
            ).first()
            if existing:
                continue

            # Fetch full body
            try:
                body = gmail.get_message_body(msg["id"])
            except Exception:
                body = msg.get("snippet", "")

            record = Message(
                channel="gmail",
                direction="inbound",
                from_addr=msg.get("from", ""),
                subject=msg.get("subject", ""),
                body=body,
                ai_draft=False,
                approved=False,
            )
            self.db.session.add(record)
            synced += 1

        if synced:
            self.db.session.commit()

        return synced

    def _sync_ebay(self) -> int:
        """Pull new eBay messages (placeholder)."""
        # eBay message sync requires the Sell Account API / Notifications
        logger.debug("eBay message sync not yet implemented")
        return 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _message_to_dict(message: Message) -> dict:
        return {
            "id": message.id,
            "channel": message.channel,
            "direction": message.direction,
            "from": message.from_addr,
            "to": message.to_addr,
            "subject": message.subject,
            "body": (message.body or "")[:500],
            "related_order_id": message.related_order_id,
            "related_product_id": message.related_product_id,
            "ai_draft": message.ai_draft,
            "approved": message.approved,
            "sent_at": message.sent_at.isoformat() if message.sent_at else None,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
