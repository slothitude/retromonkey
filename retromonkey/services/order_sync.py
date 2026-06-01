"""Order sync service — syncs external marketplace orders into the local DB."""

import json
import logging
from datetime import datetime, timezone

from retromonkey.app import db
from retromonkey.models.order import Order, OrderItem
from retromonkey.models.product import Product

logger = logging.getLogger(__name__)


class OrderSyncService:
    """Fetch orders from connectors and persist them to the local database."""

    def __init__(self, db_instance=None):
        self.db = db_instance or db

    def sync_order(self, order_data: dict, marketplace_id: int) -> dict:
        """Sync a single order from an external marketplace into the DB.

        Parameters
        ----------
        order_data : dict
            Parsed order dict from a connector (eBay, etc.).
            Must contain ``external_order_id``.
        marketplace_id : int
            The Marketplace record ID this order came from.

        Returns
        -------
        dict
            ``{"created": bool, "order_id": int|None, "status": str}``
        """
        external_id = order_data.get('external_order_id', '')
        if not external_id:
            return {"created": False, "order_id": None, "status": "no_external_id"}

        # Dedup: check if we already have this order
        existing = self.db.session.query(Order).filter_by(
            external_order_id=external_id
        ).first()
        if existing:
            # Update status if changed
            new_status = order_data.get('status', existing.status)
            if new_status != existing.status:
                existing.status = new_status
                self.db.session.commit()
                logger.info("Updated order #%s status to %s", existing.id, new_status)
            return {"created": False, "order_id": existing.id, "status": "exists"}

        # Parse the ordered_at timestamp
        ordered_at = None
        ordered_at_str = order_data.get('ordered_at', '')
        if ordered_at_str:
            try:
                # ISO format with Z or +00:00
                ordered_at_str = ordered_at_str.replace('Z', '+00:00')
                if '+' not in ordered_at_str and ordered_at_str.count('-') == 2:
                    ordered_at = datetime.fromisoformat(ordered_at_str).replace(tzinfo=timezone.utc)
                else:
                    ordered_at = datetime.fromisoformat(ordered_at_str)
            except (ValueError, TypeError):
                ordered_at = datetime.now(timezone.utc)

        # Build shipping address JSON
        shipping_addr = order_data.get('shipping_address', {})
        address_json = json.dumps(shipping_addr) if shipping_addr else None

        # Build items JSON for the order record
        items_list = order_data.get('items', [])
        items_json = json.dumps(items_list) if items_list else None

        # Create the Order record
        order = Order(
            marketplace_id=marketplace_id,
            external_order_id=external_id,
            buyer_name=order_data.get('buyer_name', ''),
            buyer_email=order_data.get('buyer_email', ''),
            status=order_data.get('status', 'pending'),
            total=order_data.get('total', 0),
            currency=order_data.get('currency', 'AUD'),
            ordered_at=ordered_at,
            address_json=address_json,
            items_json=items_json,
            source='ebay',
        )
        self.db.session.add(order)
        self.db.session.flush()

        # Create OrderItem records
        for item_data in items_list:
            if not isinstance(item_data, dict):
                continue
            sku = item_data.get('sku', '')
            qty = item_data.get('quantity', 1)
            unit_price = item_data.get('unit_price', 0)

            # Match SKU to local product
            product = None
            if sku:
                product = self.db.session.query(Product).filter_by(sku=sku).first()

            oi = OrderItem(
                order_id=order.id,
                product_id=product.id if product else None,
                quantity=qty,
                unit_price=unit_price,
                subtotal=unit_price * qty,
            )
            self.db.session.add(oi)

        self.db.session.commit()
        logger.info(
            "Synced new order #%s (external: %s, total: %.2f)",
            order.id, external_id, order.total or 0,
        )
        return {"created": True, "order_id": order.id, "status": "created"}
