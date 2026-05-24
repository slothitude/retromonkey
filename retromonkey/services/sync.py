import logging
from retromonkey.models.product import Product
from retromonkey.models.marketplace import Marketplace, Listing

logger = logging.getLogger('sync')


class InventorySyncService:
    def __init__(self, db, connector_factory):
        self.db = db
        self.connector_factory = connector_factory

    def sync_all(self) -> dict:
        results = {}
        marketplaces = self.db.session.query(Marketplace).filter_by(active=True).all()

        for mp in marketplaces:
            try:
                connector = self.connector_factory(mp)
                if not connector.is_authenticated():
                    results[mp.name] = {'error': 'not authenticated'}
                    continue

                remote_inventory = connector.get_inventory()
                pulled = len(remote_inventory)

                discrepancies = 0
                pushed = 0
                for item in remote_inventory:
                    local = self.db.session.query(Product).filter_by(sku=item['sku']).first()
                    if local and local.inventory:
                        available = local.inventory.quantity_on_hand - local.inventory.quantity_reserved
                        if item['quantity'] != available:
                            discrepancies += 1
                            logger.warning(
                                f"Inventory discrepancy: {item['sku']} on {mp.name} "
                                f"remote={item['quantity']} local={available}"
                            )
                            # Push local quantity to eBay
                            listing = self.db.session.query(Listing).filter_by(
                                product_id=local.id, marketplace_id=mp.id, status='active'
                            ).first()
                            if listing:
                                try:
                                    connector.update_listing(listing, {'availableQuantity': available})
                                    pushed += 1
                                    logger.info(f"Pushed {available} units for {item['sku']} to {mp.name}")
                                except Exception as e:
                                    logger.error(f"Failed to push quantity for {item['sku']}: {e}")

                results[mp.name] = {'pulled': pulled, 'discrepancies': discrepancies, 'pushed': pushed}

            except Exception as e:
                results[mp.name] = {'error': str(e)}

        return results

    def reserve_for_order(self, product_id: int, qty: int, marketplace_id: int) -> bool:
        from retromonkey.services.inventory import InventoryService
        inv_svc = InventoryService(self.db)

        if not inv_svc.reserve_stock(product_id, qty):
            return False

        product = self.db.session.get(Product, product_id)
        if not product or not product.inventory:
            return True
        available = product.inventory.quantity_on_hand - product.inventory.quantity_reserved

        for mp in self.db.session.query(Marketplace).filter_by(active=True).all():
            if mp.id == marketplace_id:
                continue
            try:
                connector = self.connector_factory(mp)
                listing = self.db.session.query(Listing).filter_by(
                    product_id=product_id, marketplace_id=mp.id, status='active'
                ).first()
                if listing:
                    connector.update_listing(listing, {'availableQuantity': available})
            except Exception:
                pass

        return True

    def release_on_cancel(self, product_id: int, qty: int, marketplace_id: int) -> None:
        from retromonkey.services.inventory import InventoryService
        inv_svc = InventoryService(self.db)
        inv_svc.release_stock(product_id, qty)

        product = self.db.session.get(Product, product_id)
        if not product or not product.inventory:
            return
        available = product.inventory.quantity_on_hand - product.inventory.quantity_reserved

        for mp in self.db.session.query(Marketplace).filter_by(active=True).all():
            if mp.id == marketplace_id:
                continue
            try:
                connector = self.connector_factory(mp)
                listing = self.db.session.query(Listing).filter_by(
                    product_id=product_id, marketplace_id=mp.id, status='active'
                ).first()
                if listing:
                    connector.update_listing(listing, {'availableQuantity': available})
            except Exception:
                pass
