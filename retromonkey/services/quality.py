"""Quality control service — batch quality logging, supplier metrics, flagging."""

import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.supplier import Supplier, PurchaseOrder, SupplierScore

logger = logging.getLogger(__name__)

FLAG_THRESHOLD = 60.0


class QualityService:
    """Track and evaluate supplier quality over time."""

    def __init__(self, db_instance):
        self.db = db_instance or db

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def log_batch_quality(
        self,
        supplier_id: int,
        po_id: int | None = None,
        defect_rate: float = 0.0,
        delivery_on_time: float = 100.0,
        packaging_quality: float = 80.0,
        communication_rating: float = 80.0,
        notes: str | None = None,
    ) -> dict:
        """Log a quality assessment for a received batch.

        All individual scores should be 0-100. ``overall_score`` is
        calculated as a weighted average.

        Parameters
        ----------
        supplier_id : int
            Supplier who supplied the batch.
        po_id : int, optional
            Related purchase order.
        defect_rate : float
            Defect rate as a percentage (0-100).
        delivery_on_time : float
            On-time delivery score (0-100).
        packaging_quality : float
            Packaging quality score (0-100).
        communication_rating : float
            Communication quality score (0-100).
        notes : str, optional
            Free-text notes.

        Returns
        -------
        dict
            The logged score record.
        """
        supplier = self.db.session.get(Supplier, supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")

        overall = self._calculate_overall(
            defect_rate, delivery_on_time, packaging_quality, communication_rating
        )

        score = SupplierScore(
            supplier_id=supplier_id,
            purchase_order_id=po_id,
            defect_rate=defect_rate,
            delivery_on_time=delivery_on_time,
            packaging_quality=packaging_quality,
            communication_rating=communication_rating,
            overall_score=round(overall, 2),
            notes=notes,
        )
        self.db.session.add(score)
        self.db.session.commit()

        logger.info(
            "Quality logged for supplier %d: overall=%.1f, defect=%.1f%%",
            supplier_id, overall, defect_rate,
        )

        return {
            "score_id": score.id,
            "supplier_id": supplier_id,
            "po_id": po_id,
            "defect_rate": defect_rate,
            "delivery_on_time": delivery_on_time,
            "packaging_quality": packaging_quality,
            "communication_rating": communication_rating,
            "overall_score": score.overall_score,
        }

    def get_supplier_quality(self, supplier_id: int) -> dict:
        """Get rolling quality averages for a supplier.

        Returns overall and per-metric averages across all logged batches.
        """
        scores = (
            self.db.session.query(SupplierScore)
            .filter_by(supplier_id=supplier_id)
            .order_by(SupplierScore.id.desc())
            .all()
        )

        if not scores:
            return {
                "supplier_id": supplier_id,
                "batch_count": 0,
                "averages": None,
                "flagged": False,
            }

        count = len(scores)
        averages = {
            "defect_rate": round(sum(s.defect_rate or 0 for s in scores) / count, 2),
            "delivery_on_time": round(sum(s.delivery_on_time or 0 for s in scores) / count, 2),
            "packaging_quality": round(sum(s.packaging_quality or 0 for s in scores) / count, 2),
            "communication_rating": round(sum(s.communication_rating or 0 for s in scores) / count, 2),
            "overall_score": round(sum(s.overall_score or 0 for s in scores) / count, 2),
        }

        return {
            "supplier_id": supplier_id,
            "batch_count": count,
            "averages": averages,
            "latest_score": scores[0].overall_score,
            "flagged": averages["overall_score"] < FLAG_THRESHOLD,
            "recent_scores": [
                {
                    "id": s.id,
                    "overall_score": s.overall_score,
                    "defect_rate": s.defect_rate,
                }
                for s in scores[:10]
            ],
        }

    def get_flagged_suppliers(self) -> list[dict]:
        """Return suppliers whose rolling average overall_score is below threshold."""
        suppliers = self.db.session.query(Supplier).all()
        flagged = []

        for supplier in suppliers:
            quality = self.get_supplier_quality(supplier.id)
            if quality["batch_count"] > 0 and quality.get("flagged"):
                flagged.append({
                    "supplier_id": supplier.id,
                    "supplier_name": supplier.name,
                    "platform": supplier.platform,
                    "overall_score": quality["averages"]["overall_score"],
                    "batch_count": quality["batch_count"],
                    "defect_rate": quality["averages"]["defect_rate"],
                })

        flagged.sort(key=lambda x: x["overall_score"])
        return flagged

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_overall(
        defect_rate: float,
        delivery_on_time: float,
        packaging_quality: float,
        communication_rating: float,
    ) -> float:
        """Weighted overall quality score.

        Weights: low defects 35%, on-time delivery 25%, packaging 20%,
        communication 20%.
        """
        # Invert defect rate: 0% defects = 100, 100% defects = 0
        defect_score = 100 - defect_rate

        return (
            defect_score * 0.35
            + delivery_on_time * 0.25
            + packaging_quality * 0.20
            + communication_rating * 0.20
        )
