"""
MCP server exposing eBay operations as tools for Claude integration.
Run as stdio MCP server. Register in .mcp.json.
"""
import json
import sys

from retromonkey.app import create_app, db
from retromonkey.models import Marketplace, Product, Listing, Order
from retromonkey.connectors.ebay import EbayConnector

app = create_app()


def get_ebay_connector():
    with app.app_context():
        mp = db.session.query(Marketplace).filter_by(name='eBay', active=True).first()
        if not mp:
            raise Exception("No active eBay marketplace configured")
        return EbayConnector(mp, app.config)


TOOLS = [
    {'name': 'ebay_list_item', 'description': 'List a product on eBay',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}, 'price': {'type': 'number'},
         'quantity': {'type': 'integer'}, 'category_id': {'type': 'string'}},
         'required': ['product_id', 'price', 'quantity']}},
    {'name': 'ebay_get_orders', 'description': 'Pull recent eBay orders',
     'inputSchema': {'type': 'object', 'properties': {
         'status': {'type': 'string', 'enum': ['pending', 'processing', 'shipped']},
         'days': {'type': 'integer', 'default': 7}}}},
    {'name': 'ebay_ship_order', 'description': 'Mark an eBay order as shipped',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'string'}, 'carrier': {'type': 'string'},
         'tracking_number': {'type': 'string'}},
         'required': ['order_id', 'carrier', 'tracking_number']}},
    {'name': 'ebay_get_inventory', 'description': 'Get eBay inventory levels',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'ebay_update_price', 'description': 'Update listing price on eBay',
     'inputSchema': {'type': 'object', 'properties': {
         'listing_id': {'type': 'string'}, 'new_price': {'type': 'number'}},
         'required': ['listing_id', 'new_price']}},
    {'name': 'ebay_search', 'description': 'Search eBay for competitor research',
     'inputSchema': {'type': 'object', 'properties': {
         'query': {'type': 'string'}, 'price_max': {'type': 'number'}},
         'required': ['query']}},
    {'name': 'ebay_create_campaign', 'description': 'Create eBay Promoted Listings campaign',
     'inputSchema': {'type': 'object', 'properties': {
         'listing_ids': {'type': 'array', 'items': {'type': 'string'}},
         'budget': {'type': 'number'}, 'strategy': {'type': 'string', 'enum': ['CPS', 'CPC']},
         'rate': {'type': 'number'}}, 'required': ['listing_ids', 'budget']}},
    {'name': 'ebay_get_analytics', 'description': 'Get eBay traffic/sales analytics',
     'inputSchema': {'type': 'object', 'properties': {
         'listing_id': {'type': 'string'}, 'days': {'type': 'integer', 'default': 7}}}},
    {'name': 'ebay_get_messages', 'description': 'Get eBay buyer messages',
     'inputSchema': {'type': 'object', 'properties': {'days': {'type': 'integer', 'default': 7}}}},
    {'name': 'ebay_bulk_list', 'description': 'Bulk list up to 25 products on eBay',
     'inputSchema': {'type': 'object', 'properties': {
         'product_ids': {'type': 'array', 'items': {'type': 'integer'}},
         'default_price': {'type': 'number'}}, 'required': ['product_ids']}},
]


def handle_tool(name, args):
    conn = get_ebay_connector()
    with app.app_context():
        if name == 'ebay_list_item':
            product = db.session.get(Product, args['product_id'])
            return conn.list_item(product, {
                'title': product.title, 'price': args['price'],
                'quantity': args['quantity'], 'category_id': args.get('category_id'),
            })
        elif name == 'ebay_get_orders':
            return conn.get_orders({'status': args.get('status'), 'days': args.get('days', 7)})
        elif name == 'ebay_ship_order':
            return conn.ship_order(args['order_id'], args['carrier'], args['tracking_number'])
        elif name == 'ebay_get_inventory':
            return conn.get_inventory()
        elif name == 'ebay_update_price':
            listing = db.session.query(Listing).filter_by(external_id=args['listing_id']).first()
            return conn.update_listing(listing, {'pricingSummary': {'price': {'value': str(args['new_price']), 'currency': 'AUD'}}})
        elif name == 'ebay_search':
            return conn.search(args['query'], {'price_max': args.get('price_max')})
        elif name == 'ebay_create_campaign':
            return conn.create_campaign(args['listing_ids'], args['budget'], args.get('strategy', 'CPS'), args.get('rate', 5.0))
        elif name == 'ebay_get_analytics':
            return conn.get_traffic_report(args.get('listing_id', ''), ('2026-01-01', '2026-12-31'))
        elif name == 'ebay_get_messages':
            return []
        elif name == 'ebay_bulk_list':
            results = []
            for pid in args['product_ids']:
                product = db.session.get(Product, pid)
                if product:
                    r = conn.list_item(product, {
                        'title': product.title,
                        'price': args.get('default_price', product.cost_price * 2 if product.cost_price else 9.99),
                        'quantity': 1,
                    })
                    results.append(r)
            return results


def main():
    """Simple stdio MCP protocol handler."""
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if msg.get('method') == 'tools/list':
            response = {'jsonrpc': '2.0', 'id': msg['id'], 'result': {'tools': TOOLS}}
        elif msg.get('method') == 'tools/call':
            name = msg['params']['name']
            args = msg['params'].get('arguments', {})
            try:
                result = handle_tool(name, args)
                response = {'jsonrpc': '2.0', 'id': msg['id'], 'result': {'content': [{'type': 'text', 'text': json.dumps(result)}]}}
            except Exception as e:
                response = {'jsonrpc': '2.0', 'id': msg['id'], 'error': {'code': -1, 'message': str(e)}}
        else:
            response = {'jsonrpc': '2.0', 'id': msg.get('id'), 'error': {'code': -1, 'message': 'Unknown method'}}

        sys.stdout.write(json.dumps(response) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
