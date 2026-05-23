"""RFQ (Request For Quote) service — generate, send, compare, record."""

import json
import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.supplier import Supplier, RFQ as RFQModel
from retromonkey.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class RFQService:
    """Manage RFQs: generation, sending, response tracking, comparison."""

    MAX_SUPPLIERS_PER_RFQ = 5

    def __init__(self, db_instance, llm_router=None):
        self.db = db_instance or db
        self.llm = llm_router or LLMRouter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate_rfq(
        self,
        product_id: int,
        target_qty: int,
        target_price: float | None = None,
    ) -> dict:
        """Generate an RFQ document for a product using LLM.

        Returns a dict with the RFQ text and structured specifications.
        """
        product = self.db.session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        specs = self._build_specifications(product, target_qty, target_price)

        prompt = (
            "You are a professional procurement specialist. Generate a concise "
            "Request For Quote (RFQ) email for the following product:\n\n"
            f"Product: {product.title}\n"
            f"Category: {product.category or 'N/A'}\n"
            f"Description: {product.description or 'N/A'}\n"
            f"Target Quantity: {target_qty}\n"
            f"Target Price: {'${:.2f} per unit'.format(target_price) if target_price else 'Open'}\n\n"
            "Output a JSON object with these keys:\n"
            "- subject: RFQ email subject line\n"
            "- body: professional RFQ email body (3-4 paragraphs)\n"
            "- specifications: JSON object of key product specs to quote\n"
            "- requirements: list of strings for supplier requirements\n"
            "- delivery_terms: suggested delivery terms\n"
            "- payment_terms: suggested payment terms"
        )

        result = self.llm.query(prompt, mode="claude", max_tokens=1024)
        text = result.get("text", "").strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]

        try:
            rfq_doc = json.loads(text)
        except json.JSONDecodeError:
            rfq_doc = {
                "subject": f"RFQ: {product.title}",
                "body": text or f"Please provide a quote for {product.title}, qty {target_qty}.",
                "specifications": specs,
                "requirements": ["Sample before bulk order", "Quality certification"],
                "delivery_terms": "FOB",
                "payment_terms": "30% deposit, 70% before shipping",
            }

        rfq_doc["product_id"] = product_id
        rfq_doc["target_qty"] = target_qty
        rfq_doc["target_price"] = target_price
        return rfq_doc

    def send_rfq(
        self,
        product_id: int,
        supplier_ids: list[int],
        target_qty: int,
        target_price: float | None = None,
    ) -> list[dict]:
        """Create RFQ records and (conceptually) send them to suppliers.

        Parameters
        ----------
        product_id : int
            Product to quote.
        supplier_ids : list[int]
            Supplier IDs. Capped at ``MAX_SUPPLIERS_PER_RFQ``.
        target_qty : int
            Desired quantity.
        target_price : float, optional
            Target unit price.

        Returns
        -------
        list[dict]
            Created RFQ records.
        """
        product = self.db.session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        supplier_ids = supplier_ids[: self.MAX_SUPPLIERS_PER_RFQ]
        rfq_doc = self.generate_rfq(product_id, target_qty, target_price)

        created = []
        for sid in supplier_ids:
            supplier = self.db.session.get(Supplier, sid)
            if not supplier:
                logger.warning("Supplier %s not found, skipping", sid)
                continue

            rfq = RFQModel(
                supplier_id=sid,
                product_id=product_id,
                status="sent",
                specifications=rfq_doc.get("specifications"),
                target_qty=target_qty,
                target_price_range=(
                    f"${target_price:.2f}" if target_price else "Open"
                ),
                sent_at=datetime.now(timezone.utc),
            )
            self.db.session.add(rfq)
            self.db.session.flush()

            created.append({
                "rfq_id": rfq.id,
                "supplier_id": sid,
                "supplier_name": supplier.name,
                "status": "sent",
                "subject": rfq_doc.get("subject", ""),
            })

        self.db.session.commit()
        return created

    def compare_rfq_responses(self, product_id: int) -> dict:
        """Compare all responded RFQs for a product side-by-side."""
        rfqs = (
            self.db.session.query(RFQModel)
            .filter_by(product_id=product_id)
            .filter(RFQModel.response_data.isnot(None))
            .all()
        )

        if not rfqs:
            return {"product_id": product_id, "comparisons": [], "best": None}

        comparisons = []
        for rfq in rfqs:
            supplier = self.db.session.get(Supplier, rfq.supplier_id)
            resp = rfq.response_data or {}

            comparisons.append({
                "rfq_id": rfq.id,
                "supplier": {
                    "id": supplier.id if supplier else None,
                    "name": supplier.name if supplier else "Unknown",
                    "rating": supplier.rating if supplier else None,
                    "trade_assurance": supplier.trade_assurance if supplier else False,
                },
                "quoted_price": resp.get("unit_price"),
                "quoted_moq": resp.get("moq"),
                "lead_time_days": resp.get("lead_time_days"),
                "sample_available": resp.get("sample_available"),
                "payment_terms": resp.get("payment_terms"),
                "notes": resp.get("notes"),
            })

        # Determine best by quoted price (lowest wins)
        priced = [c for c in comparisons if c["quoted_price"] is not None]
        best = None
        if priced:
            best = min(priced, key=lambda c: c["quoted_price"])

        return {
            "product_id": product_id,
            "total_responses": len(comparisons),
            "comparisons": comparisons,
            "best": best,
        }

    def record_response(self, rfq_id: int, response_data: dict) -> dict:
        """Record a supplier's response to an RFQ.

        Parameters
        ----------
        rfq_id : int
            The RFQ record ID.
        response_data : dict
            Keys: ``unit_price``, ``moq``, ``lead_time_days``,
            ``sample_available``, ``payment_terms``, ``notes``.

        Returns
        -------
        dict
            Updated RFQ record summary.
        """
        rfq = self.db.session.get(RFQModel, rfq_id)
        if not rfq:
            raise ValueError(f"RFQ {rfq_id} not found")

        rfq.response_data = response_data
        rfq.response_at = datetime.now(timezone.utc)
        rfq.status = "responded"
        self.db.session.commit()

        return {
            "rfq_id": rfq.id,
            "status": rfq.status,
            "response_data": rfq.response_data,
            "responded_at": rfq.response_at.isoformat() if rfq.response_at else None,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_specifications(
        self,
        product: Product,
        target_qty: int,
        target_price: float | None,
    ) -> dict:
        """Build a structured specifications dict from product data."""
        specs = {
            "product_title": product.title,
            "category": product.category,
            "condition": product.condition,
            "target_quantity": target_qty,
        }
        if target_price:
            specs["target_unit_price"] = target_price
        if product.images:
            specs["images"] = product.images
        return specs
