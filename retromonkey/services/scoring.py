"""Supplier scoring service — 6-factor weighted algorithm."""

import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.supplier import Supplier, SupplierScore

logger = logging.getLogger(__name__)

# Weight configuration for the 6 scoring factors
WEIGHTS = {
    "trade_assurance": 0.25,
    "rating": 0.20,
    "response_time": 0.15,
    "moq_fit": 0.15,
    "price": 0.15,
    "platform_history": 0.10,
}


class ScoringService:
    """Score and rank suppliers using a weighted multi-factor algorithm."""

    def __init__(self, db_instance):
        self.db = db_instance or db

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def score_supplier(
        self,
        supplier: Supplier,
        target_qty: int | None = None,
        price_range: tuple | None = None,
    ) -> dict:
        """Score a single supplier on a 0-100 scale.

        Parameters
        ----------
        supplier : Supplier
            The supplier model instance to score.
        target_qty : int, optional
            Desired order quantity — used to compute MOQ fit.
        price_range : tuple, optional
            ``(low, high)`` acceptable price range for price scoring.

        Returns
        -------
        dict
            Individual factor scores and the weighted total.
        """
        factors = {
            "trade_assurance": self._score_trade_assurance(supplier),
            "rating": self._score_rating(supplier),
            "response_time": self._score_response_time(supplier),
            "moq_fit": self._score_moq_fit(supplier, target_qty),
            "price": self._score_price(supplier, price_range),
            "platform_history": self._score_platform_history(supplier),
        }

        total = sum(
            factors[key] * WEIGHTS[key] for key in WEIGHTS
        )

        return {
            "supplier_id": supplier.id,
            "supplier_name": supplier.name,
            "factors": {k: round(v, 2) for k, v in factors.items()},
            "weights": WEIGHTS,
            "total_score": round(total, 2),
        }

    def rank_suppliers(
        self,
        product_keyword: str | None = None,
        target_qty: int | None = None,
    ) -> list[dict]:
        """Score and rank all suppliers, best first.

        Optionally filter by a keyword match on the supplier name.
        """
        query = self.db.session.query(Supplier)
        if product_keyword:
            query = query.filter(Supplier.name.ilike(f"%{product_keyword}%"))

        suppliers = query.all()
        scored = []
        for s in suppliers:
            result = self.score_supplier(s, target_qty=target_qty)
            scored.append(result)

        scored.sort(key=lambda x: x["total_score"], reverse=True)
        for i, entry in enumerate(scored, 1):
            entry["rank"] = i

        return scored

    def score_with_pricing(
        self,
        supplier: Supplier,
        price_data: dict,
    ) -> dict:
        """Enhanced scoring incorporating actual quoted prices.

        Parameters
        ----------
        supplier : Supplier
            The supplier to score.
        price_data : dict
            Keys: ``unit_price``, ``target_price``, ``target_qty``.

        Returns
        -------
        dict
            Factor scores with an enhanced price score.
        """
        base = self.score_supplier(
            supplier,
            target_qty=price_data.get("target_qty"),
        )

        unit_price = price_data.get("unit_price", 0)
        target_price = price_data.get("target_price", 0)
        if unit_price and target_price:
            ratio = unit_price / target_price
            # Perfect match = 100, 2x target = 0
            price_score = max(0, min(100, (2 - ratio) * 100))
            base["factors"]["price"] = round(price_score, 2)
            base["factors"]["price_source"] = "actual_quote"
            base["total_score"] = round(
                sum(
                    base["factors"].get(k, 0) * WEIGHTS.get(k, 0)
                    for k in WEIGHTS
                ),
                2,
            )

        base["price_data"] = price_data
        return base

    # ------------------------------------------------------------------
    # Individual factor scorers (each returns 0-100)
    # ------------------------------------------------------------------

    @staticmethod
    def _score_trade_assurance(supplier: Supplier) -> float:
        """Binary: 100 if trade assurance, 20 otherwise."""
        return 100.0 if supplier.trade_assurance else 20.0

    @staticmethod
    def _score_rating(supplier: Supplier) -> float:
        """Convert 0-5 rating to 0-100 scale."""
        if supplier.rating is None:
            return 50.0  # neutral
        return min(100.0, supplier.rating * 20)

    @staticmethod
    def _score_response_time(supplier: Supplier) -> float:
        """Score based on response time in hours. Faster = higher score."""
        if supplier.response_time_hours is None:
            return 50.0
        if supplier.response_time_hours <= 1:
            return 100.0
        if supplier.response_time_hours <= 4:
            return 80.0
        if supplier.response_time_hours <= 12:
            return 60.0
        if supplier.response_time_hours <= 24:
            return 40.0
        return 20.0

    @staticmethod
    def _score_moq_fit(supplier: Supplier, target_qty: int | None) -> float:
        """Score based on how well MOQ matches target quantity."""
        if target_qty is None or supplier.min_order_qty is None:
            return 50.0
        if supplier.min_order_qty <= target_qty:
            # MOQ meets or is below target — good fit
            ratio = supplier.min_order_qty / target_qty
            if ratio >= 0.5:
                return 100.0
            return 80.0
        # MOQ exceeds target — penalty proportional to excess
        excess_ratio = (supplier.min_order_qty - target_qty) / target_qty
        return max(0, 60 - excess_ratio * 40)

    @staticmethod
    def _score_price(supplier: Supplier, price_range: tuple | None) -> float:
        """Score based on price position relative to acceptable range.

        Without a price range the score defaults to neutral (50).
        """
        if price_range is None:
            return 50.0
        low, high = price_range
        # We cannot score price without actual prices on the supplier model.
        # Default to neutral.
        return 50.0

    @staticmethod
    def _score_platform_history(supplier: Supplier) -> float:
        """Score based on years on platform. More years = higher score."""
        if supplier.years_on_platform is None:
            return 50.0
        if supplier.years_on_platform >= 10:
            return 100.0
        if supplier.years_on_platform >= 5:
            return 80.0
        if supplier.years_on_platform >= 3:
            return 60.0
        if supplier.years_on_platform >= 1:
            return 40.0
        return 20.0
