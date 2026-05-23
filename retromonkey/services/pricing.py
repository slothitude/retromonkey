"""Dynamic pricing engine — cost-plus, competitive, and algorithmic strategies."""

import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.marketplace import Listing, Marketplace
from retromonkey.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

# Default margins and multipliers
DEFAULT_COST_PLUS_MARGIN = 0.40  # 40% gross margin
SHIPPING_BUFFER = 3.50  # AUD per unit
MIN_PROFIT_MARGIN = 2.00  # AUD minimum profit per unit


class PricingEngine:
    """Calculate and update prices using multiple strategies."""

    def __init__(self, db_instance, llm_router=None):
        self.db = db_instance or db
        self.llm = llm_router or LLMRouter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def calculate_price(
        self,
        product_id: int,
        strategy: str = "dynamic",
    ) -> dict:
        """Calculate the optimal price for a product.

        Parameters
        ----------
        product_id : int
            Product to price.
        strategy : str
            ``cost_plus``, ``competitive``, or ``dynamic``.

        Returns
        -------
        dict
            Pricing breakdown with recommended price.
        """
        product = self.db.session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        if strategy == "cost_plus":
            return self._cost_plus_pricing(product)
        elif strategy == "competitive":
            return self._competitive_pricing(product)
        elif strategy == "dynamic":
            return self._dynamic_algorithm(product_id)
        else:
            raise ValueError(f"Unknown pricing strategy: {strategy}")

    def update_all_prices(self) -> list[dict]:
        """Recalculate prices for all active listings using dynamic strategy.

        Returns
        -------
        list[dict]
            Updated pricing for each product.
        """
        active_listings = (
            self.db.session.query(Listing)
            .filter_by(status="active")
            .all()
        )

        updated = []
        for listing in active_listings:
            try:
                result = self._dynamic_algorithm(listing.product_id)

                # Update the listing price
                listing.price = result["recommended_price"]
                listing.updated_at = datetime.now(timezone.utc)
                updated.append({
                    "product_id": listing.product_id,
                    "listing_id": listing.id,
                    "old_price": listing.price,
                    "new_price": result["recommended_price"],
                    "strategy": "dynamic",
                })
            except Exception as exc:
                logger.warning(
                    "Price update failed for product %d: %s",
                    listing.product_id, exc,
                )

        self.db.session.commit()
        return updated

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _cost_plus_pricing(self, product: Product) -> dict:
        """Simple cost-plus pricing: cost * (1 + margin) + buffer."""
        cost = product.cost_price or 0
        if cost == 0:
            return {
                "product_id": product.id,
                "strategy": "cost_plus",
                "error": "No cost price set",
                "recommended_price": None,
            }

        price = round(cost * (1 + DEFAULT_COST_PLUS_MARGIN) + SHIPPING_BUFFER, 2)

        return {
            "product_id": product.id,
            "strategy": "cost_plus",
            "cost_price": cost,
            "margin": DEFAULT_COST_PLUS_MARGIN,
            "shipping_buffer": SHIPPING_BUFFER,
            "recommended_price": price,
            "profit_per_unit": round(price - cost - SHIPPING_BUFFER, 2),
        }

    def _competitive_pricing(self, product: Product) -> dict:
        """Price based on competitor average, positioned slightly below."""
        competitor_prices = self._get_competitor_prices(product.id)

        if not competitor_prices:
            # Fall back to cost-plus
            return self._cost_plus_pricing(product)

        avg = sum(competitor_prices) / len(competitor_prices)
        min_price = min(competitor_prices)
        max_price = max(competitor_prices)

        # Position at 5% below average
        target = round(avg * 0.95, 2)

        # Ensure minimum profit
        cost = product.cost_price or 0
        min_price_floor = cost + MIN_PROFIT_MARGIN + SHIPPING_BUFFER
        if target < min_price_floor:
            target = round(min_price_floor, 2)

        return {
            "product_id": product.id,
            "strategy": "competitive",
            "competitor_avg": round(avg, 2),
            "competitor_min": round(min_price, 2),
            "competitor_max": round(max_price, 2),
            "competitor_count": len(competitor_prices),
            "recommended_price": target,
            "cost_price": cost,
            "profit_per_unit": round(target - cost - SHIPPING_BUFFER, 2),
        }

    def _dynamic_algorithm(self, product_id: int) -> dict:
        """Full dynamic pricing: competitor avg + demand + inventory pressure.

        Factors:
        1. Base price from competitor average (or cost-plus)
        2. Demand multiplier from trend data
        3. Inventory pressure (low stock = higher price)
        4. Time-based adjustments (seasonal)
        """
        product = self.db.session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        # Step 1: Get base price from competitive analysis
        comp_result = self._competitive_pricing(product)
        base_price = comp_result.get("recommended_price")

        if not base_price:
            cost_result = self._cost_plus_pricing(product)
            base_price = cost_result.get("recommended_price", 0)

        if base_price == 0:
            return {
                "product_id": product_id,
                "strategy": "dynamic",
                "error": "Unable to determine base price",
                "recommended_price": None,
            }

        # Step 2: Demand multiplier (placeholder — would integrate with analytics)
        demand_multiplier = 1.0

        # Step 3: Inventory pressure
        inventory_multiplier = 1.0
        if product.inventory:
            available = product.inventory.quantity_on_hand - product.inventory.quantity_reserved
            threshold = product.inventory.reorder_threshold
            if available <= threshold:
                # Low stock → raise price slightly (5-15%)
                pressure_ratio = max(0, 1 - (available / max(threshold, 1)))
                inventory_multiplier = 1.0 + pressure_ratio * 0.15
            elif available > threshold * 5:
                # Overstocked → lower price slightly (5%)
                inventory_multiplier = 0.95

        # Step 4: Calculate final price
        final_price = round(base_price * demand_multiplier * inventory_multiplier, 2)

        # Floor: must cover cost + minimum profit
        cost = product.cost_price or 0
        min_floor = cost + MIN_PROFIT_MARGIN + SHIPPING_BUFFER
        if final_price < min_floor:
            final_price = round(min_floor, 2)

        return {
            "product_id": product_id,
            "strategy": "dynamic",
            "base_price": base_price,
            "demand_multiplier": demand_multiplier,
            "inventory_multiplier": inventory_multiplier,
            "recommended_price": final_price,
            "cost_price": cost,
            "profit_per_unit": round(final_price - cost - SHIPPING_BUFFER, 2),
            "factors": {
                "competitor_based": base_price == comp_result.get("recommended_price"),
                "inventory_pressure": inventory_multiplier != 1.0,
                "low_stock": inventory_multiplier > 1.0,
            },
        }

    # ------------------------------------------------------------------
    # Competitor price fetching
    # ------------------------------------------------------------------

    def _get_competitor_prices(self, product_id: int) -> list[float]:
        """Fetch competitor prices from eBay search."""
        product = self.db.session.get(Product, product_id)
        if not product:
            return []

        try:
            from retromonkey.connectors.ebay import EbayConnector
            from flask import current_app

            mp = self.db.session.query(Marketplace).filter_by(name="eBay", active=True).first()
            if not mp:
                return []

            connector = EbayConnector(mp, current_app.config)
            if not connector.is_authenticated():
                return []

            results = connector.search(product.title)
            return [r["price"] for r in results if r.get("price", 0) > 0]
        except Exception as exc:
            logger.warning("Competitor price fetch failed: %s", exc)
            return []
