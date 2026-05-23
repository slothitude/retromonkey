"""Accounting engine — P&L, fee calculation, tax estimation."""

import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.order import Order, OrderItem
from retromonkey.models.finance import Transaction, Fee
from retromonkey.models.marketplace import Marketplace

logger = logging.getLogger(__name__)

# eBay fee structure (AU, 2024-2025 approximations)
EBAY_FINAL_VALUE_FEE_RATE = 0.132  # 13.2% incl. GST on fee
EBAY_MIN_FVF = 0.30  # Minimum FVF per transaction
EBAY_PAYMENT_PROCESSING_RATE = 0.026  # 2.6% managed payments
EBAY_PAYMENT_FIXED = 0.30  # $0.30 fixed per transaction

# Tax rates
TAX_RATES = {
    "AU": {"gst": 0.10, "name": "GST"},
    "NZ": {"gst": 0.15, "name": "GST"},
    "UK": {"vat": 0.20, "name": "VAT"},
    "EU": {"vat": 0.21, "name": "VAT"},
    "US_CA": {"rate": 0.0825, "name": "Sales Tax"},  # California example
    "US_TX": {"rate": 0.0625, "name": "Sales Tax"},  # Texas example
    "US_NY": {"rate": 0.08, "name": "Sales Tax"},  # New York example
}

# Average shipping cost per unit
DEFAULT_SHIPPING_COST = 5.00


class AccountingService:
    """Financial calculations: order profit, fees, P&L, tax."""

    def __init__(self, db_instance):
        self.db = db_instance or db

    # ------------------------------------------------------------------
    # Order profit
    # ------------------------------------------------------------------

    def calculate_order_profit(self, order_id: int) -> dict:
        """Calculate the full profit breakdown for an order.

        Revenue - fees - shipping - cost of goods = profit.

        Returns
        -------
        dict
            Detailed profit breakdown.
        """
        order = self.db.session.get(Order, order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Revenue
        revenue = order.total or 0

        # Fees
        marketplace_name = order.marketplace.name if order.marketplace else ""
        fee_breakdown = self.calculate_ebay_fees(revenue) if marketplace_name == "eBay" else {}
        total_fees = fee_breakdown.get("total_fees", 0)

        # COGS
        cogs = 0
        item_costs = []
        for item in order.items:
            product = item.product if hasattr(item, "product") else None
            if product and product.cost_price:
                item_cogs = product.cost_price * item.quantity
                cogs += item_cogs
                item_costs.append({
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "unit_cost": product.cost_price,
                    "total_cost": item_cogs,
                })
            else:
                # Estimate cost as 30% of subtotal if unknown
                estimated = item.subtotal * 0.3
                cogs += estimated
                item_costs.append({
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "unit_cost": round(estimated / max(item.quantity, 1), 2),
                    "total_cost": round(estimated, 2),
                    "estimated": True,
                })

        # Shipping
        shipping_cost = DEFAULT_SHIPPING_COST * sum(oi.quantity for oi in order.items)

        # Profit
        profit = revenue - total_fees - cogs - shipping_cost
        margin_pct = (profit / revenue * 100) if revenue > 0 else 0

        return {
            "order_id": order_id,
            "revenue": round(revenue, 2),
            "fees": fee_breakdown,
            "total_fees": round(total_fees, 2),
            "cogs": round(cogs, 2),
            "item_costs": item_costs,
            "shipping_cost": round(shipping_cost, 2),
            "profit": round(profit, 2),
            "margin_pct": round(margin_pct, 2),
            "currency": order.currency,
        }

    # ------------------------------------------------------------------
    # Fee calculation
    # ------------------------------------------------------------------

    def calculate_ebay_fees(self, order_total: float) -> dict:
        """Calculate eBay fees for an order total.

        Includes:
        - Final Value Fee (FVF): 13.2% on item price (incl. GST on fee)
        - Payment processing: 2.6% + $0.30

        Returns
        -------
        dict
            Fee breakdown.
        """
        if order_total <= 0:
            return {"fvf": 0, "payment_processing": 0, "total_fees": 0}

        fvf = max(round(order_total * EBAY_FINAL_VALUE_FEE_RATE, 2), EBAY_MIN_FVF)
        payment = round(order_total * EBAY_PAYMENT_PROCESSING_RATE + EBAY_PAYMENT_FIXED, 2)
        total = round(fvf + payment, 2)

        return {
            "fvf": fvf,
            "fvf_rate": EBAY_FINAL_VALUE_FEE_RATE,
            "payment_processing": payment,
            "payment_rate": EBAY_PAYMENT_PROCESSING_RATE,
            "payment_fixed": EBAY_PAYMENT_FIXED,
            "total_fees": total,
            "fee_percentage": round((total / order_total) * 100, 2),
        }

    # ------------------------------------------------------------------
    # P&L report
    # ------------------------------------------------------------------

    def get_pnl_report(
        self,
        period: str = "monthly",
        marketplace_id: int | None = None,
    ) -> dict:
        """Generate a P&L report for a given period.

        Parameters
        ----------
        period : str
            ``daily``, ``weekly``, ``monthly``, ``yearly``.
        marketplace_id : int, optional
            Filter to a specific marketplace.

        Returns
        -------
        dict
            P&L summary with revenue, costs, fees, profit.
        """
        from sqlalchemy import func

        now = datetime.now(timezone.utc)

        # Determine date range
        if period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "weekly":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = start.replace(day=now.day - now.weekday())
        elif period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "yearly":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Build query
        query = self.db.session.query(Order).filter(Order.ordered_at >= start)
        if marketplace_id:
            query = query.filter_by(marketplace_id=marketplace_id)

        orders = query.all()

        total_revenue = 0
        total_fees = 0
        total_cogs = 0
        total_shipping = 0
        order_count = len(orders)

        for order in orders:
            total_revenue += order.total or 0

            # Sum recorded fees
            for fee in order.fees if hasattr(order, "fees") else []:
                if hasattr(fee, "amount"):
                    total_fees += fee.amount

            # If no fees recorded, estimate
            if not (hasattr(order, "fees") and order.fees) and order.total:
                est = self.calculate_ebay_fees(order.total)
                total_fees += est["total_fees"]

            # COGS
            for item in order.items:
                product = item.product if hasattr(item, "product") else None
                if product and product.cost_price:
                    total_cogs += product.cost_price * item.quantity
                else:
                    total_cogs += item.subtotal * 0.3

                total_shipping += DEFAULT_SHIPPING_COST * item.quantity

        total_profit = total_revenue - total_fees - total_cogs - total_shipping
        margin_pct = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

        return {
            "period": period,
            "start_date": start.isoformat(),
            "end_date": now.isoformat(),
            "marketplace_id": marketplace_id,
            "order_count": order_count,
            "revenue": round(total_revenue, 2),
            "fees": round(total_fees, 2),
            "cogs": round(total_cogs, 2),
            "shipping": round(total_shipping, 2),
            "profit": round(total_profit, 2),
            "margin_pct": round(margin_pct, 2),
            "currency": "AUD",
        }

    # ------------------------------------------------------------------
    # Tax estimation
    # ------------------------------------------------------------------

    def estimate_tax(self, amount: float, jurisdiction: str = "AU") -> dict:
        """Estimate tax (GST/VAT/sales tax) for an amount.

        Parameters
        ----------
        amount : float
            Pre-tax amount.
        jurisdiction : str
            Tax jurisdiction code (e.g. AU, NZ, UK, EU, US_CA).

        Returns
        -------
        dict
            Tax breakdown.
        """
        tax_info = TAX_RATES.get(jurisdiction, {"rate": 0, "name": "Unknown"})

        rate = tax_info.get("gst", tax_info.get("vat", tax_info.get("rate", 0)))
        tax_name = tax_info.get("name", "Tax")
        tax_amount = round(amount * rate, 2)
        total = round(amount + tax_amount, 2)

        return {
            "jurisdiction": jurisdiction,
            "tax_name": tax_name,
            "pre_tax_amount": round(amount, 2),
            "tax_rate": rate,
            "tax_amount": tax_amount,
            "total_incl_tax": total,
        }
