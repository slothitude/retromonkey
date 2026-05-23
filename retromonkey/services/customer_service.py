"""Customer service — auto-response, message classification, review requests."""

import json
import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.communication import Message
from retromonkey.models.order import Order, Shipment
from retromonkey.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

# FAQ patterns for auto-response
FAQ_PATTERNS = [
    {
        "keywords": ["track", "tracking", "where is my order", "shipment"],
        "category": "tracking",
        "response": (
            "Thank you for reaching out! You can track your order using the "
            "tracking number provided in your shipping confirmation email. "
            "If you haven't received a tracking number yet, your order is "
            "likely still being processed and will ship within 1-2 business days."
        ),
    },
    {
        "keywords": ["return", "refund", "money back", "send back"],
        "category": "returns",
        "response": (
            "We're sorry to hear you'd like to return your item. We accept "
            "returns within 30 days of delivery. Please reply with your order "
            "number and reason for return, and we'll send you a prepaid "
            "return label."
        ),
    },
    {
        "keywords": ["cancel", "cancel order", "stop order"],
        "category": "cancellation",
        "response": (
            "We'll do our best to cancel your order. If it hasn't shipped yet, "
            "we can cancel it immediately. Please reply with your order number "
            "and we'll confirm the cancellation within a few hours."
        ),
    },
    {
        "keywords": ["shipping", "delivery time", "how long", "when will"],
        "category": "shipping",
        "response": (
            "Standard delivery typically takes 3-7 business days within "
            "Australia. Express shipping (1-3 business days) is available at "
            "checkout. International orders may take 7-14 business days."
        ),
    },
    {
        "keywords": ["damaged", "broken", "defective", "wrong item"],
        "category": "damaged",
        "response": (
            "We're sorry about the issue with your order. Please send us a "
            "photo of the damaged/incorrect item along with your order number, "
            "and we'll arrange a replacement or full refund immediately."
        ),
    },
]

AUTO_SAFE_CATEGORIES = {"tracking", "shipping"}
ESCALATION_CATEGORIES = {"damaged", "returns", "cancellation"}


class CustomerServiceService:
    """Automated customer service: FAQ matching, LLM classification, reviews."""

    def __init__(self, db_instance, llm_router=None):
        self.db = db_instance or db
        self.llm = llm_router or LLMRouter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def auto_respond(self, message_id: int) -> dict:
        """Attempt to auto-respond to a customer message.

        1. Check FAQ pattern match.
        2. If no match, classify with LLM.
        3. If auto-safe, generate and send response.
        4. Otherwise, flag for human review.

        Returns
        -------
        dict
            Classification and response status.
        """
        message = self.db.session.get(Message, message_id)
        if not message:
            raise ValueError(f"Message {message_id} not found")

        body = message.body or ""

        # Step 1: FAQ pattern matching
        faq_match = self._match_faq(body)

        if faq_match:
            classification = {
                "category": faq_match["category"],
                "severity": "low",
                "auto_safe": faq_match["category"] in AUTO_SAFE_CATEGORIES,
                "source": "faq_match",
            }
        else:
            # Step 2: LLM classification
            classification = self._classify_message(message)

        # Step 3: Determine response
        if classification.get("auto_safe"):
            if faq_match:
                response_text = faq_match["response"]
            else:
                response_text = self._generate_llm_response(message, classification)

            # Create draft response
            draft = Message(
                channel=message.channel,
                direction="outbound",
                from_addr=message.to_addr,
                to_addr=message.from_addr,
                subject=f"Re: {message.subject}" if message.subject else None,
                body=response_text,
                related_order_id=message.related_order_id,
                related_product_id=message.related_product_id,
                ai_draft=True,
                approved=False,
            )
            self.db.session.add(draft)
            self.db.session.commit()

            return {
                "message_id": message_id,
                "classification": classification,
                "auto_response": True,
                "draft_id": draft.id,
                "response_preview": response_text[:200],
                "status": "drafted_for_approval",
            }
        else:
            return {
                "message_id": message_id,
                "classification": classification,
                "auto_response": False,
                "status": "requires_human_review",
                "reason": classification.get("category", "unknown"),
            }

    def request_review(self, order_id: int) -> dict:
        """Send a post-delivery review request for an order.

        Parameters
        ----------
        order_id : int
            The delivered order ID.

        Returns
        -------
        dict
            Review request status.
        """
        order = self.db.session.get(Order, order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        if order.status != "delivered":
            # Check if shipped and past delivery window
            if order.status != "shipped":
                return {
                    "order_id": order_id,
                    "status": "skipped",
                    "reason": f"Order status is '{order.status}', not delivered",
                }

        # Determine channel
        marketplace_name = order.marketplace.name if order.marketplace else ""
        channel = "gmail" if order.buyer_email else "ebay"

        # Build review request message
        item_names = ", ".join(
            oi.product.title if hasattr(oi, "product") and oi.product else f"Item #{oi.product_id}"
            for oi in order.items
        ) if order.items else "your recent purchase"

        body = (
            f"Hi {order.buyer_name or 'there'},\n\n"
            f"Thank you for shopping with us! We hope you're loving {item_names}.\n\n"
            f"If you're happy with your purchase, we'd really appreciate a positive "
            f"review — it helps other buyers and supports our small business.\n\n"
            f"If there's anything we can improve, please let us know directly and "
            f"we'll make it right.\n\n"
            f"Best regards,\nRetroMonkey Team"
        )

        msg = Message(
            channel=channel,
            direction="outbound",
            to_addr=order.buyer_email or "",
            subject="How was your experience? We'd love your feedback!",
            body=body,
            related_order_id=order_id,
            ai_draft=False,
            approved=True,
            sent_at=datetime.now(timezone.utc),
        )
        self.db.session.add(msg)
        self.db.session.commit()

        return {
            "order_id": order_id,
            "status": "sent",
            "channel": channel,
            "message_id": msg.id,
        }

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_message(self, message: Message) -> dict:
        """Classify a message using LLM: category, severity, auto_safe flag."""
        prompt = (
            "You are a customer service triage system. Classify this message:\n\n"
            f"Subject: {message.subject or 'N/A'}\n"
            f"Body: {(message.body or '')[:500]}\n\n"
            "Respond with JSON:\n"
            '{"category": "tracking|returns|cancellation|shipping|damaged|'
            'product_question|complaint|billing|other",\n'
            ' "severity": "low|medium|high|critical",\n'
            ' "auto_safe": true|false,\n'
            ' "summary": "one sentence summary"}\n\n'
            "auto_safe=true only for simple informational queries (tracking, shipping times, "
            "product questions). auto_safe=false for complaints, returns, refunds, damage."
        )

        try:
            result = self.llm.query(prompt, mode="auto", max_tokens=256)
            text = result.get("text", "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            classification = json.loads(text)
            classification["source"] = "llm"
            return classification
        except Exception as exc:
            logger.warning("LLM classification failed: %s", exc)
            return {
                "category": "other",
                "severity": "medium",
                "auto_safe": False,
                "summary": "Classification failed",
                "source": "fallback",
            }

    # ------------------------------------------------------------------
    # FAQ matching
    # ------------------------------------------------------------------

    @staticmethod
    def _match_faq(text: str) -> dict | None:
        """Match message text against FAQ patterns."""
        text_lower = text.lower()
        for pattern in FAQ_PATTERNS:
            for keyword in pattern["keywords"]:
                if keyword in text_lower:
                    return pattern
        return None

    # ------------------------------------------------------------------
    # LLM response generation
    # ------------------------------------------------------------------

    def _generate_llm_response(self, message: Message, classification: dict) -> str:
        """Generate a contextual response using LLM."""
        prompt = (
            "You are a friendly, professional e-commerce customer service agent.\n"
            "Generate a concise response (3-5 sentences) to this customer message:\n\n"
            f"Category: {classification.get('category', 'general')}\n"
            f"Subject: {message.subject or 'N/A'}\n"
            f"Message: {(message.body or '')[:500]}\n\n"
            "Be helpful, empathetic, and action-oriented. If you cannot fully resolve "
            "the issue, acknowledge it and promise follow-up."
        )

        result = self.llm.query(prompt, mode="auto", max_tokens=256)
        return result.get("text", "").strip() or "Thank you for your message. We'll get back to you shortly."
