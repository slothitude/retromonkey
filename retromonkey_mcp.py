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
    Task,
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
    return WorkflowEngine(db)


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
