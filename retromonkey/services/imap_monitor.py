"""IMAP email monitor — polls Gmail for new messages, applies sender rules.

Replaces the broken Google Pub/Sub push pipeline with simple IMAP polling.
Requires a Gmail App Password — no Google API credentials needed.

Important emails (customers, boss, suppliers) get Telegram alerts with
inline action buttons for human approval. Routine emails (eBay notifications,
Stripe receipts) are auto-processed.

Env vars:
    IMAP_USER      — Gmail address (default: retromonkey.com.au@gmail.com)
    IMAP_PASSWORD  — Gmail App Password (required)
    IMAP_HOST      — IMAP server (default: imap.gmail.com)
    IMAP_PORT      — IMAP port (default: 993)
"""

import email
import imaplib
import logging
import os
from email.header import decode_header

logger = logging.getLogger(__name__)


class IMAPMonitor:
    """Poll Gmail via IMAP for new messages."""

    def __init__(self, config=None):
        cfg = config or {}
        self.host = cfg.get('IMAP_HOST', 'imap.gmail.com')
        self.port = int(cfg.get('IMAP_PORT', 993))
        self.user = cfg.get('IMAP_USER', os.environ.get('IMAP_USER', 'retromonkey.com.au@gmail.com'))
        self.password = cfg.get('IMAP_PASSWORD', os.environ.get('IMAP_PASSWORD', ''))
        self._conn = None

    @property
    def is_configured(self) -> bool:
        return bool(self.user and self.password)

    def connect(self):
        """Establish SSL IMAP connection."""
        if self._conn:
            return
        self._conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=30)
        self._conn.login(self.user, self.password)
        self._conn.select('INBOX')
        logger.info("IMAP connected to %s as %s", self.host, self.user)

    def close(self):
        """Close IMAP connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def fetch_unread(self, max_messages: int = 20) -> list[dict]:
        """Fetch unread messages from INBOX."""
        self.connect()
        status, msg_uids = self._conn.uid('search', None, 'UNSEEN')
        if status != 'OK' or not msg_uids[0]:
            return []

        uid_list = msg_uids[0].split()
        messages = []
        for uid in uid_list[:max_messages]:
            try:
                msg = self._fetch_message(uid)
                if msg:
                    messages.append(msg)
            except Exception as exc:
                logger.warning("IMAP: failed to fetch UID %s: %s", uid, exc)

        return messages

    def _fetch_message(self, uid: bytes) -> dict | None:
        """Fetch a single message's metadata and snippet."""
        status, data = self._conn.uid('fetch', uid, '(BODY.PEEK[])')
        if status != 'OK':
            return None

        raw = None
        for part in data:
            if isinstance(part, tuple) and isinstance(part[1], bytes):
                raw = part[1]
                break

        if not raw:
            return None

        msg = email.message_from_bytes(raw)
        from_addr = self._decode_header(msg.get('From', ''))
        subject = self._decode_header(msg.get('Subject', ''))
        date_str = msg.get('Date', '')
        snippet = self._extract_text(msg, max_chars=300)

        return {
            'id': uid.decode() if isinstance(uid, bytes) else str(uid),
            'from': from_addr,
            'subject': subject,
            'date': date_str,
            'snippet': snippet,
            'label_ids': [],
        }

    def mark_read(self, msg_id: str) -> bool:
        """Mark a message as read via IMAP."""
        try:
            self.connect()
            self._conn.uid('store', msg_id, '+FLAGS', '\\Seen')
            return True
        except Exception as exc:
            logger.warning("IMAP: mark_read failed for %s: %s", msg_id, exc)
            return False

    def apply_label(self, msg_id: str, label_name: str) -> bool:
        """Apply a Gmail label via IMAP COPY to label folder."""
        try:
            self.connect()
            self._conn.uid('copy', msg_id, label_name)
            return True
        except Exception as exc:
            logger.warning("IMAP: label failed for %s (%s): %s", msg_id, label_name, exc)
            return False

    @staticmethod
    def _extract_text(msg, max_chars: int = 300) -> str:
        """Extract plain text body from email message."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode('utf-8', errors='replace')[:max_chars].strip()
            for part in msg.walk():
                if part.get_content_type() == 'text/html':
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode('utf-8', errors='replace')[:max_chars].strip()
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode('utf-8', errors='replace')[:max_chars].strip()
        return ''

    @staticmethod
    def _decode_header(value: str) -> str:
        """Decode RFC 2047 encoded header value."""
        if not value:
            return ''
        parts = decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                decoded.append(part)
        return ''.join(decoded)


# ── Sender Rule Routing ──

def process_imap_messages(config=None) -> dict:
    """Poll IMAP for unread messages and apply sender rules.

    Scheduler entry point. Returns summary dict.
    """
    from flask import current_app

    cfg = config or current_app.config
    monitor = IMAPMonitor(cfg)

    if not monitor.is_configured:
        return {'status': 'not_configured'}

    try:
        messages = monitor.fetch_unread()
        if not messages:
            return {'status': 'ok', 'processed': 0, 'alerts': 0}

        try:
            from retromonkey.services.telegram_client import TelegramClient
            tg = TelegramClient()
        except Exception:
            tg = None

        results = {'status': 'ok', 'processed': 0, 'alerts': 0, 'waiting_human': 0}
        for msg in messages:
            try:
                action = _apply_sender_rules(msg, monitor, tg)
                monitor.mark_read(msg['id'])
                results['processed'] += 1
                if action == 'alert':
                    results['alerts'] += 1
                elif action == 'human':
                    results['alerts'] += 1
                    results['waiting_human'] += 1
            except Exception as exc:
                logger.error("IMAP: error processing UID %s: %s", msg.get('id'), exc)
                try:
                    monitor.mark_read(msg['id'])
                except Exception:
                    pass

        return results
    except Exception as exc:
        logger.error("IMAP poll failed: %s", exc)
        return {'status': 'error', 'error': str(exc)}
    finally:
        monitor.close()


def _apply_sender_rules(msg: dict, monitor: IMAPMonitor, tg) -> str:
    """Route message based on sender. Returns 'alert', 'human', or 'auto'.

    - 'alert': sent Telegram notification (auto-processed)
    - 'human': sent Telegram with action buttons (waiting for human response)
    - 'auto': processed silently (no notification needed)
    """
    sender = msg.get('from', '').lower()
    subject = msg.get('subject', '')
    snippet = msg.get('snippet', '')
    msg_id = msg.get('id', '')

    # ── Boss (always alert, no buttons needed) ──
    if 'aaronjking86' in sender or 'slothitudegames' in sender:
        monitor.apply_label(msg_id, 'RM-Boss')
        if tg:
            tg.send_message(
                f"<b>Command from Boss</b>\n"
                f"<b>From:</b> {msg.get('from', '')}\n"
                f"<b>Subject:</b> {subject}\n"
                f"<b>Snippet:</b> {snippet[:200]}",
                parse_mode="HTML",
            )
        return 'alert'

    # ── eBay ──
    elif 'ebay' in sender or 'reply.ebay' in sender:
        sub_lower = subject.lower()
        if any(kw in sub_lower for kw in [
            'sold', 'order', 'purchase', 'payment received', 'payout',
        ]):
            # eBay sale or payment — auto-alert, no human needed
            monitor.apply_label(msg_id, 'RM-eBay-Action')
            if tg:
                tg.send_message(
                    f"<b>eBay — Order/Payment</b>\n"
                    f"<b>Subject:</b> {subject}\n"
                    f"{snippet[:150]}",
                    parse_mode="HTML",
                )
            return 'alert'
        elif any(kw in sub_lower for kw in [
            'question', 'message from buyer', 'contact', 'feedback',
        ]):
            # eBay buyer inquiry — needs human response
            monitor.apply_label(msg_id, 'RM-eBay-Action')
            if tg:
                tg.send_message(
                    f"<b>eBay — Buyer Inquiry (needs response)</b>\n"
                    f"<b>From:</b> {msg.get('from', '')}\n"
                    f"<b>Subject:</b> {subject}\n"
                    f"{snippet[:200]}",
                    parse_mode="HTML",
                    reply_markup={
                        "inline_keyboard": [[
                            {"text": "Draft Reply", "callback_data": f"draft_reply:email:{msg_id}"},
                            {"text": "Mark Read", "callback_data": f"mark_read:email:{msg_id}"},
                        ]]
                    },
                )
            return 'human'
        else:
            # Routine eBay (listing confirmed, promo, etc.)
            monitor.apply_label(msg_id, 'RM-eBay-Routine')
            return 'auto'

    # ── Customer (human check needed) ──
    elif any(kw in subject.lower() for kw in ['order', 'shipping', 'product', 'return', 'refund', 'question']):
        monitor.apply_label(msg_id, 'RM-Customer')
        if tg:
            tg.send_message(
                f"<b>Customer Email (needs response)</b>\n"
                f"<b>From:</b> {msg.get('from', '')}\n"
                f"<b>Subject:</b> {subject}\n"
                f"{snippet[:200]}",
                parse_mode="HTML",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "Draft Reply", "callback_data": f"draft_reply:email:{msg_id}"},
                        {"text": "Ignore", "callback_data": f"mark_read:email:{msg_id}"},
                    ]]
                },
            )
        return 'human'

    # ── Supplier (human check for quotes/orders) ──
    elif 'alibaba' in sender or 'supplier' in sender or 'wholesale' in sender:
        monitor.apply_label(msg_id, 'RM-Supplier')
        if tg:
            tg.send_message(
                f"<b>Supplier Email</b>\n"
                f"<b>From:</b> {msg.get('from', '')}\n"
                f"<b>Subject:</b> {subject}\n"
                f"{snippet[:200]}",
                parse_mode="HTML",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "Acknowledge", "callback_data": f"mark_read:email:{msg_id}"},
                        {"text": "Ignore", "callback_data": f"mark_read:email:{msg_id}"},
                    ]]
                },
            )
        return 'human'

    # ── Stripe (auto-alert on critical, silent on routine) ──
    elif 'stripe' in sender:
        monitor.apply_label(msg_id, 'RM-Stripe')
        sub_lower = subject.lower()
        if any(kw in sub_lower for kw in ['chargeback', 'dispute', 'reversal', 'failed payment']):
            if tg:
                tg.send_message(
                    f"<b>CRITICAL: Stripe Alert</b>\n<b>Subject:</b> {subject}",
                    parse_mode="HTML",
                    reply_markup={
                        "inline_keyboard": [[
                            {"text": "Acknowledge", "callback_data": f"mark_read:stripe:{msg_id}"},
                        ]]
                    },
                )
            return 'human'
        return 'auto'

    # ── AliExpress order updates (auto-alert) ──
    elif 'aliexpress' in sender or 'alixpress' in sender:
        monitor.apply_label(msg_id, 'RM-Supplier')
        if tg:
            tg.send_message(
                f"<b>AliExpress Update</b>\n<b>Subject:</b> {subject}\n{snippet[:150]}",
                parse_mode="HTML",
            )
        return 'alert'

    # ── Everything else ──
    else:
        monitor.apply_label(msg_id, 'RM-Other')
        return 'auto'
