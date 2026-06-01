from flask import Blueprint, request, jsonify, current_app
from functools import wraps
from datetime import datetime, timedelta, timezone
from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.order import Order, OrderItem, Shipment
from retromonkey.models.marketplace import Marketplace, Listing
from retromonkey.services.inventory import InventoryService

api_bp = Blueprint('api', __name__)
inv_svc = InventoryService(db)


def agent_auth_required(f):
    """Require STORE_AGENT_TOKEN for agent access. Skipped if token not configured."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = current_app.config.get('STORE_AGENT_TOKEN', '')
        if not token:
            return f(*args, **kwargs)  # No token configured, open access
        auth = request.headers.get('Authorization', '')
        if auth == f'Bearer {token}':
            return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized'}), 401
    return decorated


# --- Health ---
@api_bp.route('/health')
def health():
    llm_status = {'claude': bool(current_app.config.get('CLAUDE_API_KEY')), 'ollama': True}
    return jsonify({'status': 'ok', 'llm': llm_status, 'db': 'ok', 'scheduler': 'running'})


# --- Agent Health (for store agent monitoring) ---
@api_bp.route('/health/detailed')
@agent_auth_required
def health_detailed():
    """Detailed health endpoint for the store agent."""
    product_count = db.session.query(Product).count()
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    orders_24h = db.session.query(Order).filter(Order.ordered_at >= since).count()
    low_stock = len(inv_svc.get_low_stock_products()) if hasattr(inv_svc, 'get_low_stock_products') else 0
    marketplaces = {}
    for mp in db.session.query(Marketplace).all():
        marketplaces[mp.name.lower()] = 'active' if mp.active else 'inactive'
    return jsonify({
        'store': current_app.config.get('STORE_NAME', 'RetroMonkey'),
        'status': 'healthy',
        'products': product_count,
        'orders_24h': orders_24h,
        'low_stock': low_stock,
        'marketplaces': marketplaces,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })


# --- Products ---
@api_bp.route('/products', methods=['GET'])
def list_products():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    filters = {
        'category': request.args.get('category'),
        'condition': request.args.get('condition'),
        'search': request.args.get('search'),
    }
    filters = {k: v for k, v in filters.items() if v}
    result = inv_svc.list_products(filters, page, per_page)
    return jsonify({
        'items': [{
            'id': p.id, 'sku': p.sku, 'title': p.title, 'category': p.category,
            'condition': p.condition, 'cost_price': p.cost_price,
            'stock': (p.inventory.quantity_on_hand - p.inventory.quantity_reserved) if p.inventory else 0,
        } for p in result['items']],
        'total': result['total'], 'page': result['page'],
    })


@api_bp.route('/products', methods=['POST'])
def create_product():
    data = request.json
    product = inv_svc.create_product(data)
    return jsonify({'product': {'id': product.id, 'sku': product.sku, 'title': product.title}}), 201


@api_bp.route('/products/<int:product_id>')
def get_product(product_id):
    product = inv_svc.get_product(product_id)
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    stock = inv_svc.get_stock_level(product_id)
    return jsonify({'product': {
        'id': product.id, 'sku': product.sku, 'title': product.title,
        'description': product.description, 'category': product.category,
        'condition': product.condition, 'images': product.images,
        'cost_price': product.cost_price, 'created_at': str(product.created_at),
    }, 'inventory': stock})


@api_bp.route('/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    data = request.json
    product = inv_svc.update_product(product_id, data)
    return jsonify({'product': {'id': product.id, 'sku': product.sku, 'title': product.title}})


@api_bp.route('/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    product = inv_svc.get_product(product_id)
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    db.session.delete(product)
    db.session.commit()
    return '', 204


# --- Inventory ---
@api_bp.route('/inventory')
def list_inventory():
    products = db.session.query(Product).all()
    return jsonify({'items': [{
        'product_id': p.id, 'sku': p.sku, 'title': p.title,
        'on_hand': p.inventory.quantity_on_hand if p.inventory else 0,
        'reserved': p.inventory.quantity_reserved if p.inventory else 0,
        'available': (p.inventory.quantity_on_hand - p.inventory.quantity_reserved) if p.inventory else 0,
    } for p in products]})


@api_bp.route('/inventory/<int:product_id>')
def get_inventory(product_id):
    stock = inv_svc.get_stock_level(product_id)
    if not stock:
        return jsonify({'error': 'Inventory not found'}), 404
    return jsonify(stock)


@api_bp.route('/inventory/<int:product_id>/adjust', methods=['POST'])
def adjust_inventory(product_id):
    data = request.json
    qty = data.get('qty', 0)
    reason = data.get('reason', '')
    inv_svc.adjust_stock(product_id, qty, reason)
    return jsonify({'inventory': inv_svc.get_stock_level(product_id)})


@api_bp.route('/inventory/low-stock')
def low_stock():
    products = inv_svc.get_low_stock_products()
    return jsonify({'items': [{
        'id': p.id, 'sku': p.sku, 'title': p.title,
        'available': (p.inventory.quantity_on_hand - p.inventory.quantity_reserved) if p.inventory else 0,
        'threshold': p.inventory.reorder_threshold if p.inventory else 0,
    } for p in products]})


# --- Orders ---
@api_bp.route('/orders')
def list_orders():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    status = request.args.get('status')
    query = db.session.query(Order)
    if status:
        query = query.filter_by(status=status)
    total = query.count()
    orders = query.order_by(Order.ordered_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        'items': [{
            'id': o.id, 'external_order_id': o.external_order_id,
            'buyer_name': o.buyer_name, 'status': o.status, 'total': o.total,
            'currency': o.currency, 'ordered_at': str(o.ordered_at),
            'marketplace': o.marketplace.name if o.marketplace else None,
        } for o in orders],
        'total': total, 'page': page,
    })


@api_bp.route('/orders/<int:order_id>')
def get_order(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    return jsonify({
        'order': {
            'id': order.id, 'external_order_id': order.external_order_id,
            'buyer_name': order.buyer_name, 'buyer_email': order.buyer_email,
            'status': order.status, 'total': order.total, 'currency': order.currency,
            'ordered_at': str(order.ordered_at), 'shipped_at': str(order.shipped_at),
            'marketplace': order.marketplace.name if order.marketplace else None,
        },
        'items': [{
            'id': oi.id, 'product_id': oi.product_id, 'quantity': oi.quantity,
            'unit_price': oi.unit_price, 'subtotal': oi.subtotal,
        } for oi in order.items],
        'shipments': [{
            'id': s.id, 'carrier': s.carrier, 'tracking_number': s.tracking_number,
            'shipped_at': str(s.shipped_at),
        } for s in order.shipments],
    })


@api_bp.route('/orders/<int:order_id>/status', methods=['PUT'])
def update_order_status(order_id):
    data = request.json
    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    order.status = data['status']
    db.session.commit()
    return jsonify({'order': {'id': order.id, 'status': order.status}})


# --- Marketplaces ---
@api_bp.route('/marketplaces')
def list_marketplaces():
    marketplaces = db.session.query(Marketplace).all()
    return jsonify({'items': [{'id': mp.id, 'name': mp.name, 'active': mp.active} for mp in marketplaces]})


@api_bp.route('/marketplaces/<int:mp_id>', methods=['PUT'])
def update_marketplace(mp_id):
    data = request.json
    mp = db.session.get(Marketplace, mp_id)
    if not mp:
        return jsonify({'error': 'Marketplace not found'}), 404
    if 'active' in data:
        mp.active = data['active']
    if 'settings' in data:
        mp.settings = data['settings']
    db.session.commit()
    return jsonify({'marketplace': {'id': mp.id, 'name': mp.name, 'active': mp.active}})


# --- Search ---
@api_bp.route('/search')
def global_search():
    q = request.args.get('q', '')
    if not q:
        return jsonify({'products': [], 'orders': [], 'suppliers': []})

    products = db.session.query(Product).filter(Product.title.ilike(f'%{q}%')).limit(10).all()
    orders = db.session.query(Order).filter(
        (Order.external_order_id.ilike(f'%{q}%')) | (Order.buyer_name.ilike(f'%{q}%'))
    ).limit(10).all()

    return jsonify({
        'products': [{'id': p.id, 'sku': p.sku, 'title': p.title} for p in products],
        'orders': [{'id': o.id, 'external_order_id': o.external_order_id, 'buyer_name': o.buyer_name} for o in orders],
    })
