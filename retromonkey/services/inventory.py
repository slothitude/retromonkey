import uuid
from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.inventory import Inventory


class InventoryService:
    def __init__(self, db_session=None):
        self.db = db_session or db

    def get_product(self, product_id: int) -> Product | None:
        return self.db.session.get(Product, product_id)

    def create_product(self, data: dict) -> Product:
        if 'sku' not in data or not data['sku']:
            data['sku'] = f"RM-{uuid.uuid4().hex[:8].upper()}"

        product = Product(
            sku=data['sku'],
            title=data['title'],
            description=data.get('description'),
            category=data.get('category'),
            condition=data.get('condition'),
            images=data.get('images'),
            cost_price=data.get('cost_price'),
        )
        self.db.session.add(product)
        self.db.session.flush()

        inventory = Inventory(
            product_id=product.id,
            quantity_on_hand=data.get('initial_stock', 0),
            quantity_reserved=0,
            reorder_threshold=data.get('reorder_threshold', 10),
            reorder_qty=data.get('reorder_qty'),
        )
        self.db.session.add(inventory)
        self.db.session.commit()
        return product

    def update_product(self, product_id: int, data: dict) -> Product:
        product = self.get_product(product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")
        for key in ('title', 'description', 'category', 'condition', 'images', 'cost_price'):
            if key in data:
                setattr(product, key, data[key])
        self.db.session.commit()
        return product

    def list_products(self, filters: dict = None, page: int = 1, per_page: int = 50) -> dict:
        query = self.db.session.query(Product)
        if filters:
            if filters.get('category'):
                query = query.filter_by(category=filters['category'])
            if filters.get('condition'):
                query = query.filter_by(condition=filters['condition'])
            if filters.get('search'):
                query = query.filter(Product.title.ilike(f"%{filters['search']}%"))

        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
        return {'items': items, 'total': total, 'page': page}

    def get_stock_level(self, product_id: int) -> dict:
        product = self.get_product(product_id)
        if not product or not product.inventory:
            return {}
        inv = product.inventory
        available = inv.quantity_on_hand - inv.quantity_reserved
        return {
            'product_id': product_id,
            'on_hand': inv.quantity_on_hand,
            'reserved': inv.quantity_reserved,
            'available': available,
            'reorder_threshold': inv.reorder_threshold,
            'needs_reorder': available <= inv.reorder_threshold,
        }

    def reserve_stock(self, product_id: int, qty: int) -> bool:
        inv = self.db.session.query(Inventory).filter_by(product_id=product_id).first()
        if not inv:
            return False
        available = inv.quantity_on_hand - inv.quantity_reserved
        if available < qty:
            return False
        inv.quantity_reserved += qty
        self.db.session.commit()
        return True

    def release_stock(self, product_id: int, qty: int) -> None:
        inv = self.db.session.query(Inventory).filter_by(product_id=product_id).first()
        if not inv:
            return
        inv.quantity_reserved = max(0, inv.quantity_reserved - qty)
        self.db.session.commit()

    def commit_stock(self, product_id: int, qty: int) -> None:
        inv = self.db.session.query(Inventory).filter_by(product_id=product_id).first()
        if not inv:
            return
        inv.quantity_on_hand -= qty
        inv.quantity_reserved = max(0, inv.quantity_reserved - qty)
        self.db.session.commit()

    def adjust_stock(self, product_id: int, qty: int, reason: str = '') -> None:
        inv = self.db.session.query(Inventory).filter_by(product_id=product_id).first()
        if not inv:
            return
        inv.quantity_on_hand += qty
        self.db.session.commit()

    def get_low_stock_products(self) -> list[Product]:
        results = []
        inventories = self.db.session.query(Inventory).all()
        for inv in inventories:
            available = inv.quantity_on_hand - inv.quantity_reserved
            if available <= inv.reorder_threshold:
                results.append(inv.product)
        return results

    def check_reorder_needed(self) -> list[dict]:
        from retromonkey.models.supplier import Supplier, PurchaseOrder
        results = []
        for product in self.get_low_stock_products():
            inv = product.inventory
            available = inv.quantity_on_hand - inv.quantity_reserved
            last_po = self.db.session.query(PurchaseOrder).filter_by(
                product_id=product.id
            ).order_by(PurchaseOrder.id.desc()).first()

            supplier = last_po and last_po.supplier
            if not supplier:
                supplier = self.db.session.query(Supplier).filter_by(
                    trade_assurance=True
                ).order_by(Supplier.rating.desc()).first()

            results.append({
                'product_id': product.id,
                'sku': product.sku,
                'title': product.title,
                'available_qty': available,
                'reorder_threshold': inv.reorder_threshold,
                'suggested_qty': inv.reorder_qty or max(inv.reorder_threshold * 3, 50),
                'preferred_supplier': {'id': supplier.id, 'name': supplier.name} if supplier else None,
            })
        return results
