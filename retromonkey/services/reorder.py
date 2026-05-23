"""Reorder service — automatic purchase order creation and receiving."""

import logging
from datetime import datetime, timezone, timedelta

from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.inventory import Inventory
from retromonkey.models.supplier import Supplier, PurchaseOrder

logger = logging.getLogger(__name__)


class ReorderService:
    """Handle stock threshold detection, PO creation, and shipment receiving."""

    def __init__(self, db_instance):
        self.db = db_instance or db

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def check_reorder_needs(self) -> list[dict]:
        """Find all products at or below their reorder threshold.

        Returns a list of dicts with product info and suggested reorder qty.
        """
        inventories = self.db.session.query(Inventory).all()
        needs = []

        for inv in inventories:
            available = inv.quantity_on_hand - inv.quantity_reserved
            if available > inv.reorder_threshold:
                continue

            product = self.db.session.get(Product, inv.product_id)
            if not product:
                continue

            # Check if there is already a pending PO
            pending_po = (
                self.db.session.query(PurchaseOrder)
                .filter_by(product_id=product.id)
                .filter(PurchaseOrder.status.in_(["rfq_sent", "confirmed", "shipped"]))
                .first()
            )

            if pending_po:
                continue  # reorder already in progress

            # Find preferred supplier (last PO's supplier or best rated)
            last_po = (
                self.db.session.query(PurchaseOrder)
                .filter_by(product_id=product.id)
                .order_by(PurchaseOrder.id.desc())
                .first()
            )

            supplier = None
            if last_po:
                supplier = self.db.session.get(Supplier, last_po.supplier_id)

            if not supplier:
                supplier = (
                    self.db.session.query(Supplier)
                    .filter_by(trade_assurance=True)
                    .order_by(Supplier.rating.desc())
                    .first()
                )

            suggested_qty = inv.reorder_qty or max(inv.reorder_threshold * 3, 50)

            needs.append({
                "product_id": product.id,
                "sku": product.sku,
                "title": product.title,
                "available_qty": available,
                "reorder_threshold": inv.reorder_threshold,
                "suggested_qty": suggested_qty,
                "preferred_supplier": {
                    "id": supplier.id,
                    "name": supplier.name,
                    "platform": supplier.platform,
                } if supplier else None,
            })

        return needs

    def create_reorder(
        self,
        product_id: int,
        supplier_id: int,
        qty: int,
        unit_cost: float,
    ) -> dict:
        """Create a purchase order for restocking.

        Parameters
        ----------
        product_id : int
            Product to reorder.
        supplier_id : int
            Supplier to order from.
        qty : int
            Quantity to order.
        unit_cost : float
            Agreed unit cost.

        Returns
        -------
        dict
            Created PO details.
        """
        product = self.db.session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        supplier = self.db.session.get(Supplier, supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")

        po = PurchaseOrder(
            supplier_id=supplier_id,
            product_id=product_id,
            status="confirmed",
            qty=qty,
            unit_cost=unit_cost,
            total_cost=round(qty * unit_cost, 2),
            currency="AUD",
            expected_delivery=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.db.session.add(po)
        self.db.session.commit()

        logger.info(
            "Created PO #%d: %d x %s @ $%.2f from %s",
            po.id, qty, product.sku, unit_cost, supplier.name,
        )

        return {
            "po_id": po.id,
            "product_id": product_id,
            "sku": product.sku,
            "supplier_id": supplier_id,
            "supplier_name": supplier.name,
            "qty": qty,
            "unit_cost": unit_cost,
            "total_cost": po.total_cost,
            "status": po.status,
            "expected_delivery": po.expected_delivery.isoformat() if po.expected_delivery else None,
        }

    def receive_shipment(self, po_id: int, actual_qty: int | None = None) -> dict:
        """Mark a PO as received and update inventory.

        Parameters
        ----------
        po_id : int
            Purchase order ID.
        actual_qty : int, optional
            Actual quantity received. Defaults to PO qty if not specified.

        Returns
        -------
        dict
            Updated PO and inventory details.
        """
        po = self.db.session.get(PurchaseOrder, po_id)
        if not po:
            raise ValueError(f"Purchase order {po_id} not found")

        received_qty = actual_qty if actual_qty is not None else po.qty

        po.status = "received"
        po.actual_delivery = datetime.now(timezone.utc)
        self.db.session.commit()

        # Update inventory
        inv = self.db.session.query(Inventory).filter_by(product_id=po.product_id).first()
        if inv:
            inv.quantity_on_hand += received_qty
            self.db.session.commit()

        product = self.db.session.get(Product, po.product_id)
        logger.info(
            "Received PO #%d: %d units of %s",
            po_id, received_qty, product.sku if product else "unknown",
        )

        return {
            "po_id": po.id,
            "status": po.status,
            "ordered_qty": po.qty,
            "received_qty": received_qty,
            "actual_delivery": po.actual_delivery.isoformat() if po.actual_delivery else None,
            "new_on_hand": inv.quantity_on_hand if inv else None,
            "product_id": po.product_id,
        }
