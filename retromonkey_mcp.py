"""
RetroMonkey MCP Server — exposes all services as MCP tools for Claude Code.
Run as stdio JSON-RPC server. Register in .mcp.json.
"""
import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

os.environ['MCP_MODE'] = '1'

from retromonkey.app import create_app, db
from retromonkey.models import (
    Product, Inventory, Marketplace, Listing, Order, OrderItem, Shipment,
    Transaction, Fee, Supplier, PurchaseOrder, RFQ, SupplierScore, Message,
    Task, DropshipOrder,
)

app = create_app()

# ---------------------------------------------------------------------------
# Lazy singletons — services constructed on first use
# ---------------------------------------------------------------------------
_llm_router = None
_connectors = {}


def svc_llm():
    global _llm_router
    if _llm_router is None:
        from retromonkey.services.llm_router import LLMRouter
        _llm_router = LLMRouter(app)
    return _llm_router


def _connector_factory(marketplace_record):
    key = marketplace_record.name
    if key not in _connectors:
        from retromonkey.connectors.ebay import EbayConnector
        from retromonkey.connectors.amazon import AmazonConnector
        from retromonkey.connectors.kogan import KoganConnector
        cls = {'eBay': EbayConnector, 'Amazon': AmazonConnector, 'Kogan': KoganConnector}.get(key)
        if not cls:
            raise ValueError(f"Unknown marketplace: {key}")
        _connectors[key] = cls(marketplace_record, app.config)
    return _connectors[key]


def _get_ebay():
    with app.app_context():
        mp = db.session.query(Marketplace).filter_by(name='eBay', active=True).first()
        if not mp:
            raise Exception("No active eBay marketplace configured")
        return _connector_factory(mp)


def svc_inventory():
    from retromonkey.services.inventory import InventoryService
    return InventoryService(db)


def svc_sync():
    from retromonkey.services.sync import InventorySyncService
    return InventorySyncService(db, _connector_factory)


def svc_research():
    from retromonkey.services.research import ResearchService
    return ResearchService(db, svc_llm())


def svc_sourcing():
    from retromonkey.services.sourcing import SourcingService
    return SourcingService(db)


def svc_scoring():
    from retromonkey.services.scoring import ScoringService
    return ScoringService(db)


def svc_rfq():
    from retromonkey.services.rfq import RFQService
    return RFQService(db, svc_llm())


def svc_reorder():
    from retromonkey.services.reorder import ReorderService
    return ReorderService(db)


def svc_quality():
    from retromonkey.services.quality import QualityService
    return QualityService(db)


def svc_planner():
    from retromonkey.services.business_planner import BusinessPlannerService
    return BusinessPlannerService(db, svc_llm())


def svc_workflow():
    from retromonkey.services.workflow import WorkflowEngine
    import os
    workflows_dir = os.path.join(os.path.dirname(__file__), 'retromonkey', 'workflows')
    return WorkflowEngine(db, workflows_dir=workflows_dir)


def svc_gmail():
    from retromonkey.services.gmail_client import GmailClient
    return GmailClient(db, app.config)


def svc_comms():
    from retromonkey.services.communications import CommunicationsService
    return CommunicationsService(db, svc_llm())


def svc_listing_ai():
    from retromonkey.services.listing_ai import ListingAIService
    return ListingAIService(db, svc_llm())


def svc_pricing():
    from retromonkey.services.pricing import PricingEngine
    return PricingEngine(db, svc_llm())


def svc_accounting():
    from retromonkey.services.accounting import AccountingService
    return AccountingService(db)


def svc_support():
    from retromonkey.services.customer_service import CustomerServiceService
    return CustomerServiceService(db, svc_llm())


def svc_task():
    from retromonkey.services.task_manager import TaskManager
    return TaskManager(db)


def svc_alert():
    from retromonkey.services.alert_service import AlertService
    return AlertService(db, app.config)


def svc_telegram():
    from retromonkey.services.telegram_client import TelegramClient
    return TelegramClient(app.config)


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------
def _serialize(obj):
    """Convert SQLAlchemy model or dict to JSON-safe structure."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, '__table__'):
        return {c.name: _serialize(getattr(obj, c.name)) for c in obj.__table__.columns}
    if isinstance(obj, (int, float, bool)):
        return obj
    return str(obj)


def _ok(data):
    return {'content': [{'type': 'text', 'text': json.dumps(_serialize(data), default=str)}]}


def _err(msg):
    return {'content': [{'type': 'text', 'text': json.dumps({'error': str(msg)})}], 'isError': True}


def _ctx(func):
    """Wrap a handler to run inside Flask app context."""
    def wrapper(args):
        with app.app_context():
            try:
                return _ok(func(args))
            except Exception as e:
                return _err(e)
    return wrapper


# ===========================================================================
# TOOL DEFINITIONS — 76 tools across 21 domains
# ===========================================================================
TOOLS = [
    # ---- Health ----
    {'name': 'health', 'description': 'Check RetroMonkey system health',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Products ----
    {'name': 'product_list', 'description': 'List products with optional filters',
     'inputSchema': {'type': 'object', 'properties': {
         'filters': {'type': 'object', 'description': 'Optional filters (category, status, etc.)'},
         'page': {'type': 'integer', 'default': 1},
         'per_page': {'type': 'integer', 'default': 50}}}},

    {'name': 'product_get', 'description': 'Get a single product by ID',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}},
         'required': ['product_id']}},

    {'name': 'product_create', 'description': 'Create a new product',
     'inputSchema': {'type': 'object', 'properties': {
         'data': {'type': 'object', 'description': 'Product fields (title, sku, category, cost_price, etc.)'}},
         'required': ['data']}},

    {'name': 'product_update', 'description': 'Update an existing product',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'},
         'data': {'type': 'object', 'description': 'Fields to update'}},
         'required': ['product_id', 'data']}},

    {'name': 'product_delete', 'description': 'Delete a product by ID',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}},
         'required': ['product_id']}},

    # ---- Stock ----
    {'name': 'stock_level', 'description': 'Get current stock level for a product',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}},
         'required': ['product_id']}},

    {'name': 'stock_reserve', 'description': 'Reserve stock for a pending order',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}, 'qty': {'type': 'integer'}},
         'required': ['product_id', 'qty']}},

    {'name': 'stock_release', 'description': 'Release reserved stock (e.g. cancelled order)',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}, 'qty': {'type': 'integer'}},
         'required': ['product_id', 'qty']}},

    {'name': 'stock_commit', 'description': 'Commit reserved stock (order confirmed)',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}, 'qty': {'type': 'integer'}},
         'required': ['product_id', 'qty']}},

    {'name': 'stock_adjust', 'description': 'Adjust stock level with a reason (stocktake, correction)',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}, 'qty': {'type': 'integer'},
         'reason': {'type': 'string', 'default': ''}},
         'required': ['product_id', 'qty']}},

    {'name': 'stock_low', 'description': 'List products below reorder threshold',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'stock_reorder_check', 'description': 'Check which products need reordering',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Orders ----
    {'name': 'order_list', 'description': 'List orders with optional filters',
     'inputSchema': {'type': 'object', 'properties': {
         'filters': {'type': 'object', 'description': 'Optional filters (status, marketplace_id, date range)'},
         'page': {'type': 'integer', 'default': 1},
         'per_page': {'type': 'integer', 'default': 50}}}},

    {'name': 'order_get', 'description': 'Get a single order with items and shipment details',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'integer'}},
         'required': ['order_id']}},

    {'name': 'order_update_status', 'description': 'Update order status',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'integer'},
         'status': {'type': 'string', 'enum': ['pending', 'processing', 'shipped', 'delivered', 'cancelled']}},
         'required': ['order_id', 'status']}},

    {'name': 'order_profit', 'description': 'Calculate profit for an order',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'integer'}},
         'required': ['order_id']}},

    # ---- Marketplace ----
    {'name': 'marketplace_list', 'description': 'List all configured marketplaces',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'marketplace_update', 'description': 'Update marketplace configuration',
     'inputSchema': {'type': 'object', 'properties': {
         'marketplace_id': {'type': 'integer'},
         'data': {'type': 'object', 'description': 'Fields to update (active, settings, etc.)'}},
         'required': ['marketplace_id', 'data']}},

    {'name': 'marketplace_sync', 'description': 'Sync inventory across all active marketplaces',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'marketplace_status', 'description': 'Check authentication status for all marketplaces',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- eBay ----
    {'name': 'ebay_list', 'description': 'List a product on eBay',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}, 'price': {'type': 'number'},
         'quantity': {'type': 'integer'}, 'category_id': {'type': 'string'}},
         'required': ['product_id', 'price', 'quantity']}},

    {'name': 'ebay_bulk_list', 'description': 'Bulk list multiple products on eBay',
     'inputSchema': {'type': 'object', 'properties': {
         'product_ids': {'type': 'array', 'items': {'type': 'integer'}},
         'default_price': {'type': 'number'}},
         'required': ['product_ids']}},

    {'name': 'ebay_get_orders', 'description': 'Pull recent eBay orders',
     'inputSchema': {'type': 'object', 'properties': {
         'status': {'type': 'string'},
         'days': {'type': 'integer', 'default': 7}}}},

    {'name': 'order_sync_ebay', 'description': 'Sync eBay orders into the local database. Fetches recent orders and creates Order + OrderItem records.',
     'inputSchema': {'type': 'object', 'properties': {
         'days': {'type': 'integer', 'default': 7, 'description': 'How many days back to sync'}},
     'required': []}},

    {'name': 'ebay_ship', 'description': 'Mark an eBay order as shipped',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'string'}, 'carrier': {'type': 'string'},
         'tracking_number': {'type': 'string'}},
         'required': ['order_id', 'carrier', 'tracking_number']}},

    {'name': 'ebay_inventory', 'description': 'Get eBay inventory levels',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'ebay_search', 'description': 'Search eBay for competitor research',
     'inputSchema': {'type': 'object', 'properties': {
         'query': {'type': 'string'}, 'price_max': {'type': 'number'}},
         'required': ['query']}},

    {'name': 'ebay_update_price', 'description': 'Update listing price on eBay',
     'inputSchema': {'type': 'object', 'properties': {
         'listing_id': {'type': 'string'}, 'new_price': {'type': 'number'}},
         'required': ['listing_id', 'new_price']}},

    {'name': 'ebay_end_listing', 'description': 'End/remove an eBay listing',
     'inputSchema': {'type': 'object', 'properties': {
         'listing_id': {'type': 'string'}},
         'required': ['listing_id']}},

    {'name': 'ebay_auth_url', 'description': 'Get eBay OAuth authorization URL',
     'inputSchema': {'type': 'object', 'properties': {
         'state': {'type': 'string', 'default': ''}}}},

    {'name': 'ebay_campaign', 'description': 'Create eBay Promoted Listings campaign',
     'inputSchema': {'type': 'object', 'properties': {
         'listing_ids': {'type': 'array', 'items': {'type': 'string'}},
         'budget': {'type': 'number'},
         'strategy': {'type': 'string', 'enum': ['CPS', 'CPC'], 'default': 'CPS'},
         'rate': {'type': 'number', 'default': 5.0}},
         'required': ['listing_ids', 'budget']}},

    # ---- Sourcing ----
    {'name': 'sourcing_search_suppliers', 'description': 'Search Alibaba for suppliers by keyword',
     'inputSchema': {'type': 'object', 'properties': {
         'keyword': {'type': 'string'},
         'filters': {'type': 'object', 'description': 'Optional filters (price range, MOQ, etc.)'}},
         'required': ['keyword']}},

    {'name': 'sourcing_score_supplier', 'description': 'Score a supplier using weighted algorithm',
     'inputSchema': {'type': 'object', 'properties': {
         'supplier_id': {'type': 'integer'},
         'target_qty': {'type': 'integer'},
         'price_range': {'type': 'array', 'items': {'type': 'number'}, 'description': '[min, max]'}},
         'required': ['supplier_id']}},

    {'name': 'sourcing_rank_suppliers', 'description': 'Rank all suppliers for a product/keyword',
     'inputSchema': {'type': 'object', 'properties': {
         'product_keyword': {'type': 'string'},
         'target_qty': {'type': 'integer'}}}},

    {'name': 'sourcing_research_niche', 'description': 'Research a product niche (trends, competition, margins)',
     'inputSchema': {'type': 'object', 'properties': {
         'niche': {'type': 'string'},
         'depth': {'type': 'string', 'enum': ['quick', 'standard', 'deep'], 'default': 'standard'}},
         'required': ['niche']}},

    # ---- RFQ ----
    {'name': 'rfq_generate', 'description': 'Generate an RFQ for a product',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'},
         'target_qty': {'type': 'integer'},
         'target_price': {'type': 'number'}},
         'required': ['product_id', 'target_qty']}},

    {'name': 'rfq_send', 'description': 'Send RFQ to selected suppliers',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'},
         'supplier_ids': {'type': 'array', 'items': {'type': 'integer'}},
         'target_qty': {'type': 'integer'},
         'target_price': {'type': 'number'}},
         'required': ['product_id', 'supplier_ids', 'target_qty']}},

    {'name': 'rfq_compare', 'description': 'Compare RFQ responses for a product',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}},
         'required': ['product_id']}},

    {'name': 'rfq_record_response', 'description': 'Record a supplier RFQ response',
     'inputSchema': {'type': 'object', 'properties': {
         'rfq_id': {'type': 'integer'},
         'response_data': {'type': 'object', 'description': 'Response details (price, lead time, etc.)'}},
         'required': ['rfq_id', 'response_data']}},

    # ---- Reorder ----
    {'name': 'reorder_check', 'description': 'Check which products need reordering',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'reorder_create', 'description': 'Create a reorder purchase order',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'},
         'supplier_id': {'type': 'integer'},
         'qty': {'type': 'integer'},
         'unit_cost': {'type': 'number'}},
         'required': ['product_id', 'supplier_id', 'qty', 'unit_cost']}},

    {'name': 'reorder_receive', 'description': 'Receive a reorder shipment and update stock',
     'inputSchema': {'type': 'object', 'properties': {
         'po_id': {'type': 'integer'},
         'actual_qty': {'type': 'integer'}},
         'required': ['po_id']}},

    # ---- Quality ----
    {'name': 'quality_log', 'description': 'Log quality metrics for a supplier batch',
     'inputSchema': {'type': 'object', 'properties': {
         'supplier_id': {'type': 'integer'},
         'po_id': {'type': 'integer'},
         'defect_rate': {'type': 'number', 'default': 0.0},
         'delivery_on_time': {'type': 'number', 'default': 100.0},
         'packaging_quality': {'type': 'number', 'default': 80.0},
         'communication_rating': {'type': 'number', 'default': 80.0},
         'notes': {'type': 'string'}},
         'required': ['supplier_id']}},

    {'name': 'quality_get', 'description': 'Get quality metrics for a supplier',
     'inputSchema': {'type': 'object', 'properties': {
         'supplier_id': {'type': 'integer'}},
         'required': ['supplier_id']}},

    {'name': 'quality_flagged', 'description': 'List suppliers flagged for quality issues',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Business Plan ----
    {'name': 'plan_generate', 'description': 'Generate an AI business plan for a niche',
     'inputSchema': {'type': 'object', 'properties': {
         'niche': {'type': 'string'},
         'investment_budget': {'type': 'number'}},
         'required': ['niche', 'investment_budget']}},

    # ---- Workflow ----
    {'name': 'workflow_list', 'description': 'List all available workflows',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'workflow_get', 'description': 'Get details of a specific workflow',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string'}},
         'required': ['name']}},

    {'name': 'workflow_trigger', 'description': 'Trigger a workflow event',
     'inputSchema': {'type': 'object', 'properties': {
         'event_type': {'type': 'string'},
         'event_data': {'type': 'object', 'default': {}}},
         'required': ['event_type']}},

    # ---- Dropship ----
    {'name': 'dropship_record', 'description': 'Record a dropship order — link an Order to a supplier with cost and order URL',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'integer', 'description': 'Local order ID'},
         'supplier_id': {'type': 'integer', 'description': 'Supplier ID (optional)'},
         'supplier_order_url': {'type': 'string', 'description': 'URL of the order on supplier site'},
         'supplier_order_id': {'type': 'string', 'description': 'Order ID on supplier site'},
         'unit_cost': {'type': 'number', 'description': 'Cost per unit from supplier'},
         'currency': {'type': 'string', 'default': 'AUD'},
         'notes': {'type': 'string'}},
     'required': ['order_id', 'unit_cost']}},

    {'name': 'dropship_update_tracking', 'description': 'Add supplier tracking number to a dropship order',
     'inputSchema': {'type': 'object', 'properties': {
         'dropship_id': {'type': 'integer', 'description': 'DropshipOrder ID'},
         'tracking_number': {'type': 'string'}},
     'required': ['dropship_id', 'tracking_number']}},

    {'name': 'dropship_mark_shipped', 'description': 'Mark dropship order as shipped and update eBay if applicable',
     'inputSchema': {'type': 'object', 'properties': {
         'dropship_id': {'type': 'integer', 'description': 'DropshipOrder ID'},
         'carrier': {'type': 'string', 'default': 'Standard Shipping'}},
     'required': ['dropship_id']}},

    {'name': 'dropship_list_pending', 'description': 'List all pending dropship orders',
     'inputSchema': {'type': 'object', 'properties': {
         'status': {'type': 'string', 'description': 'Filter by status (pending, ordered, tracking_received, shipped, delivered)'}},
     'required': []}},

    # ---- AliExpress ----
    {'name': 'aliexpress_search', 'description': 'Search AliExpress for products to dropship',
     'inputSchema': {'type': 'object', 'properties': {
         'keywords': {'type': 'string'},
         'page_size': {'type': 'integer', 'default': 20}},
     'required': ['keywords']}},

    {'name': 'aliexpress_product_detail', 'description': 'Get product details from AliExpress',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'string'}},
     'required': ['product_id']}},

    {'name': 'aliexpress_create_order', 'description': 'Create a dropship order on AliExpress',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'string'},
         'address': {'type': 'object', 'description': 'Shipping address dict'},
         'quantity': {'type': 'integer', 'default': 1}},
     'required': ['product_id', 'address']}},

    {'name': 'aliexpress_order_tracking', 'description': 'Get tracking info for an AliExpress dropship order',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'string'}},
     'required': ['order_id']}},

    {'name': 'sourcing_add_manual', 'description': 'Manually add a supplier entry (workaround for broken Alibaba scraper)',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string'},
         'platform': {'type': 'string', 'default': 'AliExpress'},
         'url': {'type': 'string'},
         'contact_email': {'type': 'string'},
         'rating': {'type': 'number'},
         'min_order_qty': {'type': 'integer'},
         'notes': {'type': 'string'}},
     'required': ['name']}},

    # ---- Communications ----
    {'name': 'comms_inbox', 'description': 'Get unified inbox across all channels',
     'inputSchema': {'type': 'object', 'properties': {
         'filters': {'type': 'object', 'description': 'Optional filters (channel, unread, etc.)'}}}},

    {'name': 'comms_draft_reply', 'description': 'AI-draft a reply to a message',
     'inputSchema': {'type': 'object', 'properties': {
         'message_id': {'type': 'integer'}},
         'required': ['message_id']}},

    {'name': 'comms_send', 'description': 'Approve and send a drafted reply',
     'inputSchema': {'type': 'object', 'properties': {
         'message_id': {'type': 'integer'},
         'edited_body': {'type': 'string', 'description': 'Optionally edit the draft before sending'}},
         'required': ['message_id']}},

    {'name': 'comms_sync', 'description': 'Sync inbox from all connected channels',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Listing AI ----
    {'name': 'listing_optimize', 'description': 'AI-optimize a product listing (title, description, SEO)',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'},
         'marketplace': {'type': 'string', 'default': 'ebay'}},
         'required': ['product_id']}},

    # ---- Pricing ----
    {'name': 'pricing_calculate', 'description': 'Calculate optimal price for a product',
     'inputSchema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'},
         'strategy': {'type': 'string', 'enum': ['dynamic', 'cost_plus', 'competitive', 'penetration'], 'default': 'dynamic'}},
         'required': ['product_id']}},

    {'name': 'pricing_update_all', 'description': 'Recalculate and update prices for all active listings',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Finance ----
    {'name': 'finance_order_fees', 'description': 'Calculate all fees for an order',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'integer'}},
         'required': ['order_id']}},

    {'name': 'finance_pnl', 'description': 'Get profit & loss report',
     'inputSchema': {'type': 'object', 'properties': {
         'period': {'type': 'string', 'enum': ['daily', 'weekly', 'monthly', 'yearly'], 'default': 'monthly'},
         'marketplace_id': {'type': 'integer'}}}},

    {'name': 'finance_ebay_fees', 'description': 'Calculate eBay fees for a given order total',
     'inputSchema': {'type': 'object', 'properties': {
         'order_total': {'type': 'number'}},
         'required': ['order_total']}},

    {'name': 'finance_tax_estimate', 'description': 'Estimate tax for a given amount',
     'inputSchema': {'type': 'object', 'properties': {
         'amount': {'type': 'number'},
         'jurisdiction': {'type': 'string', 'default': 'AU'}},
         'required': ['amount']}},

    # ---- Customer Support ----
    {'name': 'support_auto_respond', 'description': 'AI auto-respond to a customer message',
     'inputSchema': {'type': 'object', 'properties': {
         'message_id': {'type': 'integer'}},
         'required': ['message_id']}},

    {'name': 'support_request_review', 'description': 'Request a product review from a buyer',
     'inputSchema': {'type': 'object', 'properties': {
         'order_id': {'type': 'integer'}},
         'required': ['order_id']}},

    # ---- LLM ----
    {'name': 'llm_query', 'description': 'Query the LLM router (Claude/Ollama/rule engine)',
     'inputSchema': {'type': 'object', 'properties': {
         'prompt': {'type': 'string'},
         'mode': {'type': 'string', 'enum': ['auto', 'simple', 'complex'], 'default': 'auto'},
         'system': {'type': 'string', 'default': ''},
         'max_tokens': {'type': 'integer', 'default': 1024}},
         'required': ['prompt']}},

    {'name': 'llm_daily_cost', 'description': 'Get today\'s LLM API spending',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Gmail ----
    {'name': 'gmail_auth_url', 'description': 'Get Gmail OAuth authorization URL',
     'inputSchema': {'type': 'object', 'properties': {
         'redirect_uri': {'type': 'string'}}}},

    {'name': 'gmail_messages', 'description': 'List Gmail messages',
     'inputSchema': {'type': 'object', 'properties': {
         'query': {'type': 'string', 'default': 'is:unread'},
         'max_results': {'type': 'integer', 'default': 20},
         'label_ids': {'type': 'array', 'items': {'type': 'string'}}}}},

    {'name': 'gmail_send', 'description': 'Send an email via Gmail',
     'inputSchema': {'type': 'object', 'properties': {
         'to': {'type': 'string'},
         'subject': {'type': 'string'},
         'body': {'type': 'string'},
         'thread_id': {'type': 'string'},
         'reply_to_message_id': {'type': 'string'}},
         'required': ['to', 'subject', 'body']}},

    {'name': 'email_send', 'description': 'Send an email via Resend from any @retromonkey.com.au address',
     'inputSchema': {'type': 'object', 'properties': {
         'to': {'type': 'string', 'description': 'Recipient email'},
         'subject': {'type': 'string', 'description': 'Email subject'},
         'html': {'type': 'string', 'description': 'HTML body'},
         'text': {'type': 'string', 'description': 'Plain text body (fallback if no html)'},
         'from_addr': {'type': 'string', 'description': 'Sender address (any @retromonkey.com.au, default: orders@)'},
         'reply_to': {'type': 'string', 'description': 'Reply-To header'}},
         'required': ['to', 'subject']}},

    {'name': 'gmail_label', 'description': 'Apply a label to a Gmail message',
     'inputSchema': {'type': 'object', 'properties': {
         'message_id': {'type': 'string'},
         'label_name': {'type': 'string'}},
         'required': ['message_id', 'label_name']}},

    {'name': 'gmail_watch_start', 'description': 'Start Gmail push notifications via Google Pub/Sub',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'gmail_watch_stop', 'description': 'Stop Gmail push notifications',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'gmail_watch_status', 'description': 'Check if Gmail Pub/Sub watch is configured and enabled',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Tasks ----
    {'name': 'task_list', 'description': 'List tasks with filters (status, category, days)',
     'inputSchema': {'type': 'object', 'properties': {
         'status': {'type': 'string', 'description': 'Filter by status (pending, in_progress, completed, skipped)'},
         'category': {'type': 'string', 'description': 'Filter by category'},
         'days': {'type': 'integer', 'description': 'Only tasks from last N days'}}}},

    {'name': 'task_create', 'description': 'Create an ad-hoc task',
     'inputSchema': {'type': 'object', 'properties': {
         'title': {'type': 'string'},
         'description': {'type': 'string'},
         'category': {'type': 'string', 'default': 'general'},
         'priority': {'type': 'string', 'default': 'medium'}},
         'required': ['title']}},

    {'name': 'task_complete', 'description': 'Complete a task with result notes',
     'inputSchema': {'type': 'object', 'properties': {
         'task_id': {'type': 'integer'},
         'notes': {'type': 'string', 'description': 'Result notes for the completed task'}},
         'required': ['task_id']}},

    {'name': 'task_daily', 'description': 'Get or generate today\'s daily management checklist',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'task_summary', 'description': 'Get daily summary (completed, pending, overdue counts)',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Alerts ----
    {'name': 'alert_send', 'description': 'Send a custom alert to any configured channel (email and/or Telegram)',
     'inputSchema': {'type': 'object', 'properties': {
         'subject': {'type': 'string', 'description': 'Alert subject line'},
         'body': {'type': 'string', 'description': 'Alert body text'}},
         'required': ['subject', 'body']}},

    {'name': 'alert_test', 'description': 'Send test alert to all configured channels',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'alert_config', 'description': 'Show alert channel configuration (email + Telegram status)',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'alert_daily_summary', 'description': 'Send daily summary alert now',
     'inputSchema': {'type': 'object', 'properties': {}}},

    # ---- Reports ----
    {'name': 'report_morning_briefing', 'description': 'Send morning briefing (checklist, overnight orders, low stock) to all channels',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'report_weekly', 'description': 'Send weekly report (P&L, top sellers, stock, tasks) to all channels',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'report_daily_summary', 'description': 'Send enhanced daily summary with P&L, stock, and business plan data',
     'inputSchema': {'type': 'object', 'properties': {}}},

    {'name': 'telegram_setup_webhook', 'description': 'Register Telegram webhook URL',
     'inputSchema': {'type': 'object', 'properties': {}}},
]

# ===========================================================================
# HANDLERS — dispatch table: tool name → handler function
# ===========================================================================
HANDLERS = {
    # ---- Health ----
    'health': _ctx(lambda a: {'status': 'ok', 'tools': len(TOOLS)}),

    # ---- Products ----
    'product_list': _ctx(lambda a: svc_inventory().list_products(
        filters=a.get('filters'), page=a.get('page', 1), per_page=a.get('per_page', 50))),

    'product_get': _ctx(lambda a: svc_inventory().get_product(a['product_id'])),

    'product_create': _ctx(lambda a: svc_inventory().create_product(a['data'])),

    'product_update': _ctx(lambda a: svc_inventory().update_product(a['product_id'], a['data'])),

    'product_delete': _ctx(lambda a: _product_delete(a['product_id'])),

    # ---- Stock ----
    'stock_level': _ctx(lambda a: svc_inventory().get_stock_level(a['product_id'])),

    'stock_reserve': _ctx(lambda a: svc_inventory().reserve_stock(a['product_id'], a['qty'])),

    'stock_release': _ctx(lambda a: svc_inventory().release_stock(a['product_id'], a['qty'])),

    'stock_commit': _ctx(lambda a: svc_inventory().commit_stock(a['product_id'], a['qty'])),

    'stock_adjust': _ctx(lambda a: svc_inventory().adjust_stock(
        a['product_id'], a['qty'], a.get('reason', ''))),

    'stock_low': _ctx(lambda a: svc_inventory().get_low_stock_products()),

    'stock_reorder_check': _ctx(lambda a: svc_inventory().check_reorder_needed()),

    # ---- Orders ----
    'order_list': _ctx(lambda a: _order_list(a)),

    'order_get': _ctx(lambda a: _order_get(a['order_id'])),

    'order_update_status': _ctx(lambda a: _order_update(a['order_id'], a['status'])),

    'order_profit': _ctx(lambda a: svc_accounting().calculate_order_profit(a['order_id'])),

    # ---- Marketplace ----
    'marketplace_list': _ctx(lambda a: db.session.query(Marketplace).all()),

    'marketplace_update': _ctx(lambda a: _marketplace_update(a['marketplace_id'], a['data'])),

    'marketplace_sync': _ctx(lambda a: svc_sync().sync_all()),

    'marketplace_status': _ctx(lambda a: _marketplace_status()),

    # ---- eBay ----
    'ebay_list': _ctx(lambda a: _ebay_list(a)),

    'ebay_bulk_list': _ctx(lambda a: _ebay_bulk_list(a)),

    'ebay_get_orders': _ctx(lambda a: _get_ebay().get_orders(
        {'status': a.get('status'), 'days': a.get('days', 7)})),

    'order_sync_ebay': _ctx(lambda a: _order_sync_ebay(a)),

    'ebay_ship': _ctx(lambda a: _get_ebay().ship_order(
        a['order_id'], a['carrier'], a['tracking_number'])),

    'ebay_inventory': _ctx(lambda a: _get_ebay().get_inventory()),

    'ebay_search': _ctx(lambda a: _get_ebay().search(a['query'], {'price_max': a.get('price_max')})),

    'ebay_update_price': _ctx(lambda a: _ebay_update_price(a)),

    'ebay_end_listing': _ctx(lambda a: _ebay_end_listing(a)),

    'ebay_auth_url': _ctx(lambda a: _get_ebay().get_auth_url(a.get('state', ''))),

    'ebay_campaign': _ctx(lambda a: _get_ebay().create_campaign(
        a['listing_ids'], a['budget'], a.get('strategy', 'CPS'), a.get('rate', 5.0))),

    # ---- Sourcing ----
    'sourcing_search_suppliers': _ctx(lambda a: svc_sourcing().search_suppliers(
        a['keyword'], a.get('filters'))),

    'sourcing_score_supplier': _ctx(lambda a: svc_scoring().score_supplier(
        db.session.get(Supplier, a['supplier_id']),
        target_qty=a.get('target_qty'),
        price_range=tuple(a['price_range']) if a.get('price_range') else None)),

    'sourcing_rank_suppliers': _ctx(lambda a: svc_scoring().rank_suppliers(
        product_keyword=a.get('product_keyword'),
        target_qty=a.get('target_qty'))),

    'sourcing_research_niche': _ctx(lambda a: svc_research().research_niche(
        a['niche'], a.get('depth', 'standard'))),

    # ---- RFQ ----
    'rfq_generate': _ctx(lambda a: svc_rfq().generate_rfq(
        a['product_id'], a['target_qty'], a.get('target_price'))),

    'rfq_send': _ctx(lambda a: svc_rfq().send_rfq(
        a['product_id'], a['supplier_ids'], a['target_qty'], a.get('target_price'))),

    'rfq_compare': _ctx(lambda a: svc_rfq().compare_rfq_responses(a['product_id'])),

    'rfq_record_response': _ctx(lambda a: svc_rfq().record_response(
        a['rfq_id'], a['response_data'])),

    # ---- Reorder ----
    'reorder_check': _ctx(lambda a: svc_reorder().check_reorder_needs()),

    'reorder_create': _ctx(lambda a: svc_reorder().create_reorder(
        a['product_id'], a['supplier_id'], a['qty'], a['unit_cost'])),

    'reorder_receive': _ctx(lambda a: svc_reorder().receive_shipment(
        a['po_id'], a.get('actual_qty'))),

    # ---- Quality ----
    'quality_log': _ctx(lambda a: svc_quality().log_batch_quality(
        supplier_id=a['supplier_id'], po_id=a.get('po_id'),
        defect_rate=a.get('defect_rate', 0.0),
        delivery_on_time=a.get('delivery_on_time', 100.0),
        packaging_quality=a.get('packaging_quality', 80.0),
        communication_rating=a.get('communication_rating', 80.0),
        notes=a.get('notes'))),

    'quality_get': _ctx(lambda a: svc_quality().get_supplier_quality(a['supplier_id'])),

    'quality_flagged': _ctx(lambda a: svc_quality().get_flagged_suppliers()),

    # ---- Business Plan ----
    'plan_generate': _ctx(lambda a: svc_planner().generate_plan(
        a['niche'], a['investment_budget'])),

    # ---- Workflow ----
    'workflow_list': _ctx(lambda a: svc_workflow().list_workflows()),

    'workflow_get': _ctx(lambda a: svc_workflow().get_workflow(a['name'])),

    'workflow_trigger': _ctx(lambda a: svc_workflow().trigger(
        a['event_type'], a.get('event_data', {}))),

    # ---- Dropship ----
    'dropship_record': _ctx(lambda a: _dropship_record(a)),
    'dropship_update_tracking': _ctx(lambda a: _dropship_update_tracking(a)),
    'dropship_mark_shipped': _ctx(lambda a: _dropship_mark_shipped(a)),
    'dropship_list_pending': _ctx(lambda a: _dropship_list_pending(a)),

    # ---- AliExpress ----
    'aliexpress_search': _ctx(lambda a: _aliexpress_search(a)),
    'aliexpress_product_detail': _ctx(lambda a: _aliexpress_product_detail(a)),
    'aliexpress_create_order': _ctx(lambda a: _aliexpress_create_order(a)),
    'aliexpress_order_tracking': _ctx(lambda a: _aliexpress_order_tracking(a)),
    'sourcing_add_manual': _ctx(lambda a: _sourcing_add_manual(a)),

    # ---- Communications ----
    'comms_inbox': _ctx(lambda a: svc_comms().get_unified_inbox(a.get('filters'))),

    'comms_draft_reply': _ctx(lambda a: svc_comms().draft_reply(a['message_id'])),

    'comms_send': _ctx(lambda a: svc_comms().approve_and_send(
        a['message_id'], a.get('edited_body'))),

    'comms_sync': _ctx(lambda a: svc_comms().sync_inbox()),

    # ---- Listing AI ----
    'listing_optimize': _ctx(lambda a: svc_listing_ai().optimize_listing(
        a['product_id'], a.get('marketplace', 'ebay'))),

    # ---- Pricing ----
    'pricing_calculate': _ctx(lambda a: svc_pricing().calculate_price(
        a['product_id'], a.get('strategy', 'dynamic'))),

    'pricing_update_all': _ctx(lambda a: svc_pricing().update_all_prices()),

    # ---- Finance ----
    'finance_order_fees': _ctx(lambda a: svc_accounting().calculate_order_profit(a['order_id'])),

    'finance_pnl': _ctx(lambda a: svc_accounting().get_pnl_report(
        a.get('period', 'monthly'), a.get('marketplace_id'))),

    'finance_ebay_fees': _ctx(lambda a: svc_accounting().calculate_ebay_fees(a['order_total'])),

    'finance_tax_estimate': _ctx(lambda a: svc_accounting().estimate_tax(
        a['amount'], a.get('jurisdiction', 'AU'))),

    # ---- Customer Support ----
    'support_auto_respond': _ctx(lambda a: svc_support().auto_respond(a['message_id'])),

    'support_request_review': _ctx(lambda a: svc_support().request_review(a['order_id'])),

    # ---- LLM ----
    'llm_query': _ctx(lambda a: svc_llm().query(
        a['prompt'], mode=a.get('mode', 'auto'),
        system=a.get('system', ''), max_tokens=a.get('max_tokens', 1024))),

    'llm_daily_cost': _ctx(lambda a: {'daily_cost': svc_llm().get_daily_cost()}),

    # ---- Gmail ----
    'gmail_auth_url': _ctx(lambda a: svc_gmail().get_auth_url(a.get('redirect_uri'))),

    'gmail_messages': _ctx(lambda a: svc_gmail().list_messages(
        query=a.get('query', 'is:unread'),
        max_results=a.get('max_results', 20),
        label_ids=a.get('label_ids'))),

    'gmail_send': _ctx(lambda a: svc_gmail().send_email(
        to=a['to'], subject=a['subject'], body=a['body'],
        thread_id=a.get('thread_id'),
        reply_to_message_id=a.get('reply_to_message_id'))),

    'email_send': _ctx(lambda a: _resend_send(
        to=a['to'], subject=a['subject'],
        html=a.get('html', ''), text=a.get('text', ''),
        from_addr=a.get('from_addr'), reply_to=a.get('reply_to'))),

    'gmail_label': _ctx(lambda a: svc_gmail().apply_label(a['message_id'], a['label_name'])),

    'gmail_watch_start': _ctx(lambda a: _gmail_watch_start()),
    'gmail_watch_stop': _ctx(lambda a: svc_gmail().stop_watch()),
    'gmail_watch_status': _ctx(lambda a: _gmail_watch_status()),

    # ---- Tasks ----
    'task_list': _ctx(lambda a: _task_list(a)),

    'task_create': _ctx(lambda a: svc_task().create_task(
        title=a['title'],
        description=a.get('description'),
        category=a.get('category', 'general'),
        priority=a.get('priority', 'medium'))),

    'task_complete': _ctx(lambda a: svc_task().complete_task(
        a['task_id'], notes=a.get('notes'))),

    'task_daily': _ctx(lambda a: svc_task().generate_daily_checklist()),

    'task_summary': _ctx(lambda a: svc_task().get_daily_summary()),

    # ---- Alerts ----
    'alert_send': _ctx(lambda a: svc_alert().send_alert(
        subject=a['subject'], plain_text=a['body'])),

    'alert_test': _ctx(lambda a: svc_alert().send_test_alert()),

    'alert_config': _ctx(lambda a: {
        'email': {
            'address': app.config.get('ALERT_EMAIL', ''),
            'configured': bool(app.config.get('SMTP_USER') or app.config.get('GOOGLE_CLIENT_ID')),
        },
        'telegram': {
            'enabled': app.config.get('ALERT_TELEGRAM_ENABLED', False),
            'bot_configured': bool(app.config.get('TELEGRAM_BOT_TOKEN')),
            'chat_id_set': bool(app.config.get('TELEGRAM_CHAT_ID')),
        },
    }),

    'alert_daily_summary': _ctx(lambda a: _alert_daily_summary()),

    # ---- Reports ----
    'report_morning_briefing': _ctx(lambda a: svc_alert().alert_morning_briefing()),
    'report_weekly': _ctx(lambda a: svc_alert().alert_weekly_report()),
    'report_daily_summary': _ctx(lambda a: _alert_daily_summary()),

    'telegram_setup_webhook': _ctx(lambda a: svc_telegram().set_webhook(
        f"{app.config.get('SITE_URL', 'https://retromonkey.com.au').rstrip('/')}/webhooks/telegram")),
}


# ===========================================================================
# Helper functions for complex handlers
# ===========================================================================
def _gmail_watch_start():
    topic = app.config.get('GOOGLE_PUBSUB_TOPIC', '')
    if not topic:
        raise ValueError('GOOGLE_PUBSUB_TOPIC not configured')
    return svc_gmail().watch(topic)


def _gmail_watch_status():
    return {
        'enabled': app.config.get('GOOGLE_GMAIL_WATCH_ENABLED', False),
        'topic_configured': bool(app.config.get('GOOGLE_PUBSUB_TOPIC', '')),
        'topic': app.config.get('GOOGLE_PUBSUB_TOPIC', ''),
    }


def _resend_send(to, subject, html='', text='', from_addr=None, reply_to=None):
    """Send email via Resend API from any @retromonkey.com.au address."""
    from retromonkey.services.resend_sender import send_email
    return send_email(
        to=to, subject=subject,
        html=html, text=text,
        from_addr=from_addr, reply_to=reply_to,
    )


def _product_delete(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        raise ValueError(f"Product {product_id} not found")
    db.session.delete(product)
    db.session.commit()
    return {'deleted': True, 'product_id': product_id}


def _order_list(args):
    q = db.session.query(Order)
    filters = args.get('filters') or {}
    if 'status' in filters:
        q = q.filter_by(status=filters['status'])
    if 'marketplace_id' in filters:
        q = q.filter_by(marketplace_id=filters['marketplace_id'])
    page = args.get('page', 1)
    per_page = args.get('per_page', 50)
    total = q.count()
    orders = q.offset((page - 1) * per_page).limit(per_page).all()
    return {'total': total, 'page': page, 'per_page': per_page, 'orders': orders}


def _order_get(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")
    items = db.session.query(OrderItem).filter_by(order_id=order_id).all()
    shipment = db.session.query(Shipment).filter_by(order_id=order_id).first()
    return {'order': order, 'items': items, 'shipment': shipment}


def _order_update(order_id, status):
    order = db.session.get(Order, order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")
    order.status = status
    db.session.commit()
    return {'updated': True, 'order_id': order_id, 'status': status}


def _marketplace_update(marketplace_id, data):
    mp = db.session.get(Marketplace, marketplace_id)
    if not mp:
        raise ValueError(f"Marketplace {marketplace_id} not found")
    for key, value in data.items():
        setattr(mp, key, value)
    db.session.commit()
    return mp


def _marketplace_status():
    results = []
    for mp in db.session.query(Marketplace).all():
        try:
            conn = _connector_factory(mp)
            authenticated = conn.is_authenticated()
        except Exception:
            authenticated = False
        results.append({'name': mp.name, 'id': mp.id, 'active': mp.active, 'authenticated': authenticated})
    return results


def _ebay_list(args):
    conn = _get_ebay()
    product = db.session.get(Product, args['product_id'])
    if not product:
        raise ValueError(f"Product {args['product_id']} not found")

    # Ensure business policies exist
    policies = conn.ensure_policies()

    images = product.images if isinstance(product.images, list) else (
        product.images.split(',') if isinstance(product.images, str) and product.images else []
    )

    return conn.list_item(product, {
        'title': product.title,
        'price': args['price'],
        'quantity': args['quantity'],
        'category_id': args.get('category_id'),
        'images': images,
        'condition': 'NEW',
        'item_specifics': {
            'Brand': product.title.split()[0] if product.title else '',
            'Type': 'Handheld Game Console',
            'Storage Capacity': '64GB',
            'Screen Size': '3.5"',
        },
        'listing_policies': {
            'paymentPolicyId': policies['payment_policy_id'],
            'returnPolicyId': policies['return_policy_id'],
            'fulfillmentPolicyId': policies['fulfillment_policy_id'],
        },
    })


def _ebay_bulk_list(args):
    conn = _get_ebay()
    results = []
    for pid in args['product_ids']:
        product = db.session.get(Product, pid)
        if product:
            price = args.get('default_price', product.cost_price * 2 if product.cost_price else 9.99)
            r = conn.list_item(product, {'title': product.title, 'price': price, 'quantity': 1})
            results.append(r)
    return results


def _order_sync_ebay(args):
    from retromonkey.services.order_sync import OrderSyncService
    from retromonkey.models import Marketplace
    conn = _get_ebay()
    mp = db.session.query(Marketplace).filter_by(name='eBay', active=True).first()
    if not mp:
        raise ValueError("No active eBay marketplace configured")
    days = args.get('days', 7)
    orders = conn.get_orders()
    sync_svc = OrderSyncService(db)
    results = []
    for order_data in (orders or []):
        if isinstance(order_data, dict):
            result = sync_svc.sync_order(order_data, mp.id)
            results.append(result)
    created = sum(1 for r in results if r.get('created'))
    return {"total_fetched": len(results), "new_orders": created, "results": results}


# ---- Dropship handlers ----

def _dropship_record(args):
    from datetime import datetime, timezone
    order_id = args['order_id']
    order = db.session.get(Order, order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")
    ds = DropshipOrder(
        order_id=order_id,
        supplier_id=args.get('supplier_id'),
        supplier_order_url=args.get('supplier_order_url'),
        supplier_order_id=args.get('supplier_order_id'),
        unit_cost=args.get('unit_cost'),
        currency=args.get('currency', 'AUD'),
        status='ordered',
        notes=args.get('notes'),
        ordered_at=datetime.now(timezone.utc),
    )
    db.session.add(ds)
    db.session.commit()
    return {"created": True, "dropship_id": ds.id, "order_id": order_id, "status": "ordered"}


def _dropship_update_tracking(args):
    from datetime import datetime, timezone
    ds = db.session.get(DropshipOrder, args['dropship_id'])
    if not ds:
        raise ValueError(f"DropshipOrder {args['dropship_id']} not found")
    ds.supplier_tracking = args['tracking_number']
    ds.status = 'tracking_received'
    ds.tracking_received_at = datetime.now(timezone.utc)
    # Also update the parent order tracking
    ds.order.tracking = args['tracking_number']
    db.session.commit()
    return {"updated": True, "dropship_id": ds.id, "tracking": args['tracking_number'], "status": "tracking_received"}


def _dropship_mark_shipped(args):
    from datetime import datetime, timezone
    ds = db.session.get(DropshipOrder, args['dropship_id'])
    if not ds:
        raise ValueError(f"DropshipOrder {args['dropship_id']} not found")
    ds.status = 'shipped'
    ds.shipped_at = datetime.now(timezone.utc)
    ds.order.status = 'shipped'
    ds.order.shipped_at = datetime.now(timezone.utc)
    carrier = args.get('carrier', 'Standard Shipping')
    result = {"updated": True, "dropship_id": ds.id, "status": "shipped"}

    # If this is an eBay order, call ship_order
    if ds.order.external_order_id and ds.supplier_tracking:
        try:
            mp = db.session.query(Marketplace).filter_by(name='eBay', active=True).first()
            if mp:
                conn = _get_ebay()
                ship_result = conn.ship_order(
                    ds.order.external_order_id, carrier, ds.supplier_tracking
                )
                result['ebay_ship'] = ship_result
        except Exception as exc:
            result['ebay_ship_error'] = str(exc)

    db.session.commit()
    return result


def _dropship_list_pending(args):
    query = db.session.query(DropshipOrder).order_by(DropshipOrder.created_at.desc())
    status_filter = args.get('status')
    if status_filter:
        query = query.filter_by(status=status_filter)
    else:
        query = query.filter(DropshipOrder.status.in_(['pending', 'ordered', 'tracking_received']))
    results = []
    for ds in query.limit(50).all():
        results.append({
            'id': ds.id,
            'order_id': ds.order_id,
            'order_total': ds.order.total if ds.order else None,
            'buyer': ds.order.buyer_name if ds.order else None,
            'supplier_id': ds.supplier_id,
            'unit_cost': ds.unit_cost,
            'currency': ds.currency,
            'status': ds.status,
            'tracking': ds.supplier_tracking,
            'created_at': ds.created_at.isoformat() if ds.created_at else None,
            'notes': ds.notes,
        })
    return {"count": len(results), "orders": results}


# ---- AliExpress handlers ----

def _get_aliexpress():
    from retromonkey.services.aliexpress import AliExpressConnector
    return AliExpressConnector()


def _aliexpress_search(args):
    ae = _get_aliexpress()
    if not ae.is_configured:
        raise RuntimeError("AliExpress API not configured (set ALIEXPRESS_APP_KEY and ALIEXPRESS_APP_SECRET)")
    return ae.search_products(args['keywords'], args.get('page_size', 20))


def _aliexpress_product_detail(args):
    ae = _get_aliexpress()
    if not ae.is_configured:
        raise RuntimeError("AliExpress API not configured")
    return ae.get_product_details(args['product_id'])


def _aliexpress_create_order(args):
    ae = _get_aliexpress()
    if not ae.is_configured:
        raise RuntimeError("AliExpress API not configured")
    if not ae.access_token:
        raise RuntimeError("AliExpress access token not set (ALIEXPRESS_ACCESS_TOKEN)")
    return ae.create_order(args['product_id'], args['address'], args.get('quantity', 1))


def _aliexpress_order_tracking(args):
    ae = _get_aliexpress()
    if not ae.is_configured:
        raise RuntimeError("AliExpress API not configured")
    return ae.get_order_tracking(args['order_id'])


def _sourcing_add_manual(args):
    supplier = Supplier(
        name=args['name'],
        platform=args.get('platform', 'AliExpress'),
        url=args.get('url'),
        contact_email=args.get('contact_email'),
        rating=args.get('rating'),
        min_order_qty=args.get('min_order_qty'),
        notes=args.get('notes'),
    )
    db.session.add(supplier)
    db.session.commit()
    return {"id": supplier.id, "name": supplier.name, "created": True}


def _ebay_update_price(args):
    conn = _get_ebay()
    listing = db.session.query(Listing).filter_by(external_id=args['listing_id']).first()
    if not listing:
        raise ValueError(f"Listing {args['listing_id']} not found")
    return conn.update_listing(listing, {
        'pricingSummary': {'price': {'value': str(args['new_price']), 'currency': 'AUD'}}
    })


def _ebay_end_listing(args):
    conn = _get_ebay()
    listing = db.session.query(Listing).filter_by(external_id=args['listing_id']).first()
    if not listing:
        raise ValueError(f"Listing {args['listing_id']} not found")
    return conn.end_listing(listing)


def _task_list(args):
    tm = svc_task()
    tasks = tm.get_tasks(
        status=args.get('status'),
        category=args.get('category'),
        days=args.get('days'),
    )
    return {
        'total': len(tasks),
        'tasks': [
            {
                'id': t.id,
                'title': t.title,
                'category': t.category,
                'priority': t.priority,
                'status': t.status,
                'due_at': str(t.due_at) if t.due_at else None,
                'completed_at': str(t.completed_at) if t.completed_at else None,
                'result_notes': t.result_notes,
            }
            for t in tasks
        ],
    }


def _alert_daily_summary():
    from retromonkey.services.task_manager import TaskManager
    tm = TaskManager(db)
    summary = tm.get_daily_summary()
    result = svc_alert().alert_daily_summary(summary)
    return {'summary': summary, 'alert': result}


# ===========================================================================
# MCP Protocol — stdio JSON-RPC
# ===========================================================================
def main():
    """Stdio MCP protocol handler."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get('method', '')
        msg_id = msg.get('id')
        params = msg.get('params', {})

        if method == 'initialize':
            response = {
                'jsonrpc': '2.0', 'id': msg_id,
                'result': {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'retromonkey', 'version': '1.0.0'},
                }
            }
        elif method == 'notifications/initialized':
            continue  # no response needed
        elif method == 'tools/list':
            response = {'jsonrpc': '2.0', 'id': msg_id, 'result': {'tools': TOOLS}}
        elif method == 'tools/call':
            name = params.get('name', '')
            arguments = params.get('arguments', {})
            handler = HANDLERS.get(name)
            if handler:
                response = {'jsonrpc': '2.0', 'id': msg_id, 'result': handler(arguments)}
            else:
                response = {'jsonrpc': '2.0', 'id': msg_id,
                            'error': {'code': -32601, 'message': f'Unknown tool: {name}'}}
        else:
            response = {'jsonrpc': '2.0', 'id': msg_id,
                        'error': {'code': -32601, 'message': f'Unknown method: {method}'}}

        sys.stdout.write(json.dumps(response) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
