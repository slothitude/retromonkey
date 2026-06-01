"""Intelligence API routes — workflows, Gmail, communications, listing, pricing, accounting, customer service."""

import os
from flask import Blueprint, request, jsonify, current_app
from retromonkey.app import db

intelligence_bp = Blueprint("intelligence", __name__)


# =====================================================================
# Workflows
# =====================================================================

@intelligence_bp.route("/workflows")
def list_workflows():
    """GET /api/intelligence/workflows — List all loaded workflow templates."""
    from retromonkey.services.workflow import WorkflowEngine

    workflows_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "workflows"
    )
    engine = WorkflowEngine(db, workflows_dir)
    workflows = engine.list_workflows()
    return jsonify({"workflows": workflows})


@intelligence_bp.route("/workflows/<name>/trigger", methods=["POST"])
def trigger_workflow(name):
    """POST /api/intelligence/workflows/<name>/trigger — Execute a workflow.

    Body: event_data dict passed to the workflow actions.
    """
    event_data = request.json or {}

    from retromonkey.services.workflow import WorkflowEngine

    workflows_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "workflows"
    )
    engine = WorkflowEngine(db, workflows_dir)

    workflow = engine.get_workflow(name)
    if not workflow:
        return jsonify({"error": f"Workflow '{name}' not found"}), 404

    # Get the event type from the workflow trigger
    event_type = workflow.get("trigger", {}).get("event", "")
    results = engine.trigger(event_type, event_data)
    return jsonify({"workflow": name, "results": results})


# =====================================================================
# Gmail
# =====================================================================

@intelligence_bp.route("/gmail/auth-url")
def gmail_auth_url():
    """GET /api/intelligence/gmail/auth-url — Get Google OAuth 2.0 authorization URL."""
    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)
    url = gmail.get_auth_url()
    return jsonify({"auth_url": url})


@intelligence_bp.route("/gmail/callback")
def gmail_callback():
    """GET /api/intelligence/gmail/callback — Exchange OAuth code for tokens."""
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "authorization code required"}), 400

    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        tokens = gmail.exchange_code(code)
        return jsonify({"status": "authenticated", "token_type": tokens.get("token_type")})
    except Exception as e:
        # Fallback: try with explicit redirect URI from config
        try:
            tokens = gmail.exchange_code(
                code,
                redirect_uri=current_app.config.get("GMAIL_REDIRECT_URI"),
            )
            return jsonify({"status": "authenticated", "token_type": tokens.get("token_type")})
        except Exception as e2:
            return jsonify({"error": f"{e}; fallback: {e2}"}), 400


@intelligence_bp.route("/gmail/messages")
def gmail_messages():
    """GET /api/intelligence/gmail/messages — List Gmail messages.

    Query params: q (query, default "is:unread"), max_results (default 20)
    """
    query = request.args.get("q", "is:unread")
    max_results = request.args.get("max_results", 20, type=int)

    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        messages = gmail.list_messages(query=query, max_results=max_results)
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@intelligence_bp.route("/gmail/label", methods=["POST"])
def gmail_label():
    """POST /api/intelligence/gmail/label — Apply a label to a message.

    Body: {"message_id": "...", "label_name": "..."}
    """
    data = request.json or {}
    message_id = data.get("message_id")
    label_name = data.get("label_name")
    if not message_id or not label_name:
        return jsonify({"error": "message_id and label_name are required"}), 400

    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        result = gmail.apply_label(message_id, label_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@intelligence_bp.route("/gmail/mark-read", methods=["POST"])
def gmail_mark_read():
    """POST /api/intelligence/gmail/mark-read — Mark a message as read.

    Body: {"message_id": "..."}
    """
    data = request.json or {}
    message_id = data.get("message_id")
    if not message_id:
        return jsonify({"error": "message_id is required"}), 400

    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        service = gmail._get_service()
        service.users().messages().modify(
            userId="me", id=message_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        return jsonify({"status": "read", "message_id": message_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@intelligence_bp.route("/gmail/poll", methods=["POST"])
def gmail_poll():
    """POST /api/intelligence/gmail/poll — Poll for new emails, categorize, and return unread.

    Body: {"max_results": 10} (optional)
    """
    max_results = (request.json or {}).get("max_results", 10)

    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        messages = gmail.list_messages(query="is:unread", max_results=max_results)
        categorized = []

        for msg in messages:
            sender = msg.get("from", "").lower()
            subject = msg.get("subject", "").lower()
            category = "general"

            if "ebay" in sender:
                if "listed" in subject or "listing" in subject:
                    category = "ebay-listing"
                elif "sold" in subject or "order" in subject or "purchase" in subject:
                    category = "ebay-order"
                elif "payment" in subject or "payout" in subject:
                    category = "ebay-payment"
                else:
                    category = "ebay-account"
            elif "stripe" in sender:
                category = "stripe"
            elif "amazon" in sender:
                category = "amazon"
            elif "nvidia" in sender:
                category = "nvidia"
            elif "google" in sender:
                category = "security"
            elif "improvmx" in sender:
                category = "dns"

            categorized.append({**msg, "category": category})

        return jsonify({"messages": categorized, "count": len(categorized)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@intelligence_bp.route("/gmail/send", methods=["POST"])
def gmail_send():
    """POST /api/intelligence/gmail/send — Send an email via Gmail.

    Body: {"to": "...", "subject": "...", "body": "...", "thread_id": "..."}
    """
    data = request.json or {}
    to = data.get("to")
    subject = data.get("subject")
    body = data.get("body")

    if not all([to, subject, body]):
        return jsonify({"error": "to, subject, and body are required"}), 400

    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        result = gmail.send_email(
            to=to, subject=subject, body=body,
            thread_id=data.get("thread_id"),
            reply_to_message_id=data.get("reply_to_message_id"),
        )
        return jsonify(result), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@intelligence_bp.route("/gmail/watch", methods=["POST"])
def gmail_watch_start():
    """POST /api/intelligence/gmail/watch — Start Gmail push notifications via Pub/Sub."""
    topic = current_app.config.get("GOOGLE_PUBSUB_TOPIC", "")
    if not topic:
        return jsonify({"error": "GOOGLE_PUBSUB_TOPIC not configured"}), 400

    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        result = gmail.watch(topic)
        return jsonify({"status": "watching", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@intelligence_bp.route("/gmail/watch/stop", methods=["POST"])
def gmail_watch_stop():
    """POST /api/intelligence/gmail/watch/stop — Stop Gmail push notifications."""
    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db)

    try:
        result = gmail.stop_watch()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# =====================================================================
# Communications
# =====================================================================

@intelligence_bp.route("/communications/inbox")
def communications_inbox():
    """GET /api/intelligence/communications/inbox — Unified inbox.

    Query params: channel, direction, unreplied_only, limit
    """
    filters = {}
    if request.args.get("channel"):
        filters["channel"] = request.args.get("channel")
    if request.args.get("direction"):
        filters["direction"] = request.args.get("direction")
    if request.args.get("unreplied_only") == "true":
        filters["unreplied_only"] = True
    filters["limit"] = request.args.get("limit", 50, type=int)

    from retromonkey.services.communications import CommunicationsService
    svc = CommunicationsService(db)
    messages = svc.get_unified_inbox(filters)
    return jsonify({"messages": messages})


@intelligence_bp.route("/communications/draft", methods=["POST"])
def communications_draft():
    """POST /api/intelligence/communications/draft — AI-draft a reply.

    Body: {"message_id": 1}
    """
    data = request.json or {}
    message_id = data.get("message_id")
    if not message_id:
        return jsonify({"error": "message_id is required"}), 400

    from retromonkey.services.communications import CommunicationsService
    svc = CommunicationsService(db)

    try:
        draft = svc.draft_reply(message_id)
        return jsonify(draft)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@intelligence_bp.route("/communications/send", methods=["POST"])
def communications_send():
    """POST /api/intelligence/communications/send — Approve and send a draft.

    Body: {"message_id": 1, "edited_body": "optional edited text"}
    """
    data = request.json or {}
    message_id = data.get("message_id")
    if not message_id:
        return jsonify({"error": "message_id is required"}), 400

    from retromonkey.services.communications import CommunicationsService
    svc = CommunicationsService(db)

    try:
        result = svc.approve_and_send(message_id, data.get("edited_body"))
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@intelligence_bp.route("/communications/sync", methods=["POST"])
def communications_sync():
    """POST /api/intelligence/communications/sync — Pull new messages from all channels."""
    from retromonkey.services.communications import CommunicationsService
    svc = CommunicationsService(db)
    result = svc.sync_inbox()
    return jsonify(result)


# =====================================================================
# Listing Optimization
# =====================================================================

@intelligence_bp.route("/listing/optimize", methods=["POST"])
def optimize_listing():
    """POST /api/intelligence/listing/optimize — Generate optimized listing content.

    Body: {"product_id": 1, "marketplace": "ebay"}
    """
    data = request.json or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    marketplace = data.get("marketplace", "ebay")

    from retromonkey.services.listing_ai import ListingAIService
    svc = ListingAIService(db)

    try:
        result = svc.optimize_listing(product_id, marketplace)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


# =====================================================================
# Pricing
# =====================================================================

@intelligence_bp.route("/pricing/calculate", methods=["POST"])
def calculate_price():
    """POST /api/intelligence/pricing/calculate — Calculate optimal price.

    Body: {"product_id": 1, "strategy": "cost_plus|competitive|dynamic"}
    """
    data = request.json or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    strategy = data.get("strategy", "dynamic")

    from retromonkey.services.pricing import PricingEngine
    engine = PricingEngine(db)

    try:
        result = engine.calculate_price(product_id, strategy)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@intelligence_bp.route("/pricing/update-all", methods=["POST"])
def update_all_prices():
    """POST /api/intelligence/pricing/update-all — Recalculate all active listing prices."""
    from retromonkey.services.pricing import PricingEngine
    engine = PricingEngine(db)
    results = engine.update_all_prices()
    return jsonify({"updated": results, "count": len(results)})


# =====================================================================
# Accounting
# =====================================================================

@intelligence_bp.route("/accounting/pnl")
def pnl_report():
    """GET /api/intelligence/accounting/pnl — P&L report.

    Query params: period (daily|weekly|monthly|yearly), marketplace_id
    """
    period = request.args.get("period", "monthly")
    marketplace_id = request.args.get("marketplace_id", type=int)

    from retromonkey.services.accounting import AccountingService
    svc = AccountingService(db)
    result = svc.get_pnl_report(period, marketplace_id)
    return jsonify(result)


@intelligence_bp.route("/accounting/fees/<int:order_id>")
def order_fees(order_id):
    """GET /api/intelligence/accounting/fees/<order_id> — Calculate fees for an order."""
    from retromonkey.models.order import Order

    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    from retromonkey.services.accounting import AccountingService
    svc = AccountingService(db)
    profit = svc.calculate_order_profit(order_id)
    return jsonify(profit)


# =====================================================================
# Customer Service
# =====================================================================

@intelligence_bp.route("/customer-service/respond", methods=["POST"])
def customer_service_respond():
    """POST /api/intelligence/customer-service/respond — Auto-respond to a message.

    Body: {"message_id": 1}
    """
    data = request.json or {}
    message_id = data.get("message_id")
    if not message_id:
        return jsonify({"error": "message_id is required"}), 400

    from retromonkey.services.customer_service import CustomerServiceService
    svc = CustomerServiceService(db)

    try:
        result = svc.auto_respond(message_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@intelligence_bp.route("/customer-service/review", methods=["POST"])
def request_review():
    """POST /api/intelligence/customer-service/review — Send review request for an order.

    Body: {"order_id": 1}
    """
    data = request.json or {}
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"error": "order_id is required"}), 400

    from retromonkey.services.customer_service import CustomerServiceService
    svc = CustomerServiceService(db)

    try:
        result = svc.request_review(order_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


# =====================================================================
# Alerts
# =====================================================================

@intelligence_bp.route("/alerts/test", methods=["POST"])
def alert_test():
    """POST /api/intelligence/alerts/test — Send test alert to all configured channels."""
    from retromonkey.services.alert_service import AlertService
    svc = AlertService(db)
    result = svc.send_test_alert()
    return jsonify(result)


@intelligence_bp.route("/alerts/order", methods=["POST"])
def alert_order():
    """POST /api/intelligence/alerts/order — Send new order alert.

    Body: {"order_id": "...", "buyer": "...", "total": "99.00", "items": [...], "source": "ebay"}
    """
    data = request.json or {}
    from retromonkey.services.alert_service import AlertService
    svc = AlertService(db)
    result = svc.alert_new_order(data)
    return jsonify(result)


@intelligence_bp.route("/alerts/low-stock", methods=["POST"])
def alert_low_stock():
    """POST /api/intelligence/alerts/low-stock — Send low stock alert.

    Body: {"sku": "...", "title": "...", "quantity": 2, "reorder_threshold": 5}
    """
    data = request.json or {}
    from retromonkey.services.alert_service import AlertService
    svc = AlertService(db)
    result = svc.alert_low_stock(data)
    return jsonify(result)


@intelligence_bp.route("/alerts/daily-summary", methods=["POST"])
def alert_daily_summary():
    """POST /api/intelligence/alerts/daily-summary — Send enhanced daily summary alert."""
    from retromonkey.services.alert_service import AlertService
    from retromonkey.services.task_manager import TaskManager
    tm = TaskManager(db)
    summary = tm.get_daily_summary()
    svc = AlertService(db)
    result = svc.alert_daily_summary(summary)
    # Strip non-serializable Task objects before jsonify
    safe_summary = {k: v for k, v in summary.items() if k != "tasks"}
    return jsonify({"summary": safe_summary, "alert": result})


@intelligence_bp.route("/reports/morning-briefing", methods=["POST"])
def report_morning_briefing():
    """POST /api/intelligence/reports/morning-briefing — Send morning briefing now."""
    from retromonkey.services.alert_service import AlertService
    svc = AlertService(db)
    result = svc.alert_morning_briefing()
    return jsonify({"report": "morning_briefing", "alert": result})


@intelligence_bp.route("/reports/weekly", methods=["POST"])
def report_weekly():
    """POST /api/intelligence/reports/weekly — Send weekly report now."""
    from retromonkey.services.alert_service import AlertService
    svc = AlertService(db)
    result = svc.alert_weekly_report()
    return jsonify({"report": "weekly", "alert": result})


@intelligence_bp.route("/alerts/telegram/setup-webhook", methods=["POST"])
def alert_telegram_setup_webhook():
    """POST /api/intelligence/alerts/telegram/setup-webhook — Register Telegram webhook."""
    from retromonkey.services.telegram_client import TelegramClient
    tg = TelegramClient()
    site_url = current_app.config.get("SITE_URL", "https://retromonkey.com.au")
    webhook_url = f"{site_url.rstrip('/')}/webhooks/telegram"
    result = tg.set_webhook(webhook_url)
    return jsonify({"webhook_url": webhook_url, "result": result})


@intelligence_bp.route("/alerts/config")
def alert_config():
    """GET /api/intelligence/alerts/config — Show alert channel configuration."""
    from retromonkey.services.telegram_client import TelegramClient
    tg = TelegramClient()
    return jsonify({
        "email": {
            "address": current_app.config.get("ALERT_EMAIL", ""),
            "configured": bool(current_app.config.get("SMTP_USER") or current_app.config.get("GOOGLE_CLIENT_ID")),
        },
        "telegram": {
            "enabled": current_app.config.get("ALERT_TELEGRAM_ENABLED", False),
            "bot_configured": bool(current_app.config.get("TELEGRAM_BOT_TOKEN")),
            "chat_id_set": bool(current_app.config.get("TELEGRAM_CHAT_ID")),
        },
    })
