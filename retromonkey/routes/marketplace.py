from flask import Blueprint, request, jsonify, current_app
from retromonkey.app import db
from retromonkey.models.product import Product
from retromonkey.models.marketplace import Marketplace, Listing
from retromonkey.connectors.ebay import EbayConnector
from retromonkey.connectors.amazon import AmazonConnector

marketplace_bp = Blueprint('marketplace', __name__)


def _get_ebay_connector():
    mp = db.session.query(Marketplace).filter_by(name='eBay', active=True).first()
    if not mp:
        return None
    return EbayConnector(mp, current_app.config)


# --- eBay ---
@marketplace_bp.route('/ebay/auth-url')
def ebay_auth_url():
    conn = _get_ebay_connector()
    if not conn:
        mp = Marketplace(name='eBay', active=True, credentials={})
        db.session.add(mp)
        db.session.commit()
        conn = EbayConnector(mp, current_app.config)
    return jsonify({'url': conn.get_auth_url()})


@marketplace_bp.route('/ebay/callback', methods=['POST'])
def ebay_callback():
    data = request.json
    conn = _get_ebay_connector()
    if not conn:
        return jsonify({'error': 'eBay marketplace not configured'}), 400
    tokens = conn.exchange_code(data['code'])
    return jsonify({'status': 'ok'})


@marketplace_bp.route('/ebay/list', methods=['POST'])
def ebay_list():
    data = request.json
    product = db.session.get(Product, data['product_id'])
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    conn = _get_ebay_connector()
    if not conn:
        return jsonify({'error': 'eBay not configured'}), 400
    result = conn.list_item(product, {
        'title': product.title,
        'price': data['price'],
        'quantity': data['quantity'],
        'category_id': data.get('category_id'),
    })
    mp = db.session.query(Marketplace).filter_by(name='eBay').first()
    listing = Listing(
        product_id=product.id, marketplace_id=mp.id,
        external_id=result.get('offer_id', ''), title=product.title,
        price=data['price'], status='active',
    )
    db.session.add(listing)
    db.session.commit()
    return jsonify({'listing': result}), 201


@marketplace_bp.route('/ebay/bulk-list', methods=['POST'])
def ebay_bulk_list():
    data = request.json
    conn = _get_ebay_connector()
    if not conn:
        return jsonify({'error': 'eBay not configured'}), 400
    items = []
    for pid in data.get('product_ids', []):
        product = db.session.get(Product, pid)
        if product:
            items.append({'product': product, 'listing_data': {
                'title': product.title,
                'price': data.get('default_price', product.cost_price * 2 if product.cost_price else 9.99),
                'quantity': 1,
            }})
    results = conn.bulk_list(items)
    return jsonify({'results': results})


@marketplace_bp.route('/ebay/orders')
def ebay_orders():
    conn = _get_ebay_connector()
    if not conn:
        return jsonify({'error': 'eBay not configured'}), 400
    orders = conn.get_orders({'status': request.args.get('status'), 'days': request.args.get('days', 7, type=int)})
    return jsonify({'orders': orders})


@marketplace_bp.route('/ebay/ship', methods=['POST'])
def ebay_ship():
    data = request.json
    conn = _get_ebay_connector()
    if not conn:
        return jsonify({'error': 'eBay not configured'}), 400
    result = conn.ship_order(data['order_id'], data['carrier'], data['tracking_number'])
    return jsonify(result)


@marketplace_bp.route('/ebay/inventory')
def ebay_inventory():
    conn = _get_ebay_connector()
    if not conn:
        return jsonify({'error': 'eBay not configured'}), 400
    items = conn.get_inventory()
    return jsonify({'items': items})


@marketplace_bp.route('/ebay/search', methods=['POST'])
def ebay_search():
    data = request.json
    conn = _get_ebay_connector()
    if not conn:
        return jsonify({'error': 'eBay not configured'}), 400
    results = conn.search(data['query'], {'price_max': data.get('price_max')})
    return jsonify({'results': results})


# --- Amazon ---
@marketplace_bp.route('/amazon/list', methods=['POST'])
def amazon_list():
    return jsonify({'error': 'Amazon SP-API not yet implemented'}), 501


@marketplace_bp.route('/amazon/orders')
def amazon_orders():
    return jsonify({'error': 'Amazon SP-API not yet implemented'}), 501


# --- Sync ---
@marketplace_bp.route('/sync', methods=['POST'])
def sync():
    from retromonkey.app import _connector_factory
    from retromonkey.services.sync import InventorySyncService
    sync_svc = InventorySyncService(db, _connector_factory)
    results = sync_svc.sync_all()
    return jsonify({'results': results})


# --- Status ---
@marketplace_bp.route('/status')
def status():
    marketplaces = db.session.query(Marketplace).filter_by(active=True).all()
    result = []
    for mp in marketplaces:
        healthy = False
        try:
            if mp.name == 'eBay':
                conn = EbayConnector(mp, current_app.config)
                healthy = conn.is_authenticated()
            elif mp.name == 'Amazon':
                conn = AmazonConnector(mp, current_app.config)
                healthy = conn.is_authenticated()
        except Exception:
            pass
        result.append({'name': mp.name, 'active': mp.active, 'healthy': healthy})
    return jsonify({'marketplaces': result})
