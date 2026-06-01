import base64
import json
import logging

from flask import Blueprint, request, jsonify, current_app

webhook_bp = Blueprint('webhooks', __name__)
logger = logging.getLogger(__name__)


# ── AliExpress OAuth ──

@webhook_bp.route('/webhooks/aliexpress', methods=['GET'])
def aliexpress_oauth_callback():
    """Handle AliExpress OAuth callback — exchange code for tokens.

    The authorization flow redirects here with ?code=xxx after the user
    approves the app on AliExpress.
    """
    from flask import current_app

    code = request.args.get('code', '')
    error = request.args.get('error', '')
    error_desc = request.args.get('error_description', '')

    if error:
        logger.error("AliExpress OAuth error: %s — %s", error, error_desc)
        return f"<h2>AliExpress OAuth Failed</h2><p>{error}: {error_desc}</p>", 400

    if not code:
        return "<h2>No authorization code received</h2><p>The OAuth flow did not return a code.</p>", 400

    logger.info("AliExpress OAuth callback received with code=%s...", code[:20])

    try:
        from retromonkey.services.aliexpress import AliExpressConnector
        ae = AliExpressConnector()
        redirect_uri = (
            f"{current_app.config.get('SITE_URL', 'https://retromonkey.com.au')}"
            "/webhooks/aliexpress"
        )
        result = ae.exchange_code_for_token(code, redirect_uri)

        # Notify via Telegram
        try:
            from retromonkey.services.telegram_client import TelegramClient
            tg = TelegramClient()
            if tg.is_configured:
                tg.send_message(
                    f"<b>AliExpress OAuth Success</b>\n"
                    f"Access token: {result.get('access_token', 'N/A')}\n"
                    f"User: {result.get('user_nick', 'N/A')}\n"
                    f"Expires in: {result.get('expires_in', '?')}s",
                    parse_mode="HTML",
                )
        except Exception:
            pass

        return f"""
        <h2>AliExpress OAuth Success!</h2>
        <p>Access token saved. You can close this tab.</p>
        <pre>{json.dumps({k: v for k, v in result.items() if k != 'saved'}, indent=2)}</pre>
        """, 200

    except Exception as exc:
        logger.error("AliExpress OAuth token exchange failed: %s", exc)
        return f"<h2>Token Exchange Failed</h2><p>{exc}</p>", 500


@webhook_bp.route('/webhooks/ebay', methods=['POST'])
def ebay_webhook():
    data = request.json
    notification = data.get('notification', {})
    event_type = notification.get('metadata', {}).get('eventType')

    if event_type == 'ORDER_CREATED':
        order_id = notification.get('data', {}).get('orderId')
        try:
            from retromonkey.services.workflow import WorkflowEngine
            from retromonkey.app import db as _db
            import os as _os
            wf_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'workflows')
            wf = WorkflowEngine(_db, workflows_dir=wf_dir)
            wf.trigger('order_received', {
                'order_id': order_id,
                'source': 'ebay',
                'buyer': '',
                'total': '0',
                'items': '',
            })
        except Exception as exc:
            logger.error("Failed to trigger workflow for eBay order %s: %s", order_id, exc)

    return jsonify({'status': 'ok'}), 200


@webhook_bp.route('/webhooks/gmail', methods=['POST'])
def gmail_pubsub_webhook():
    """Handle Google Pub/Sub push notifications for Gmail.

    Google POSTs here when a new message arrives in INBOX.  The push payload
    contains a base64-encoded ``data`` field with ``emailAddress`` and
    ``historyId``.
    """
    data = request.json or {}
    message = data.get('message', {})
    raw_data = message.get('data', '')

    if not raw_data:
        logger.warning("Gmail Pub/Sub push with empty data")
        return jsonify({'status': 'ignored'}), 200

    try:
        decoded = json.loads(base64.b64decode(raw_data).decode('utf-8'))
    except Exception:
        logger.warning("Gmail Pub/Sub: failed to decode data")
        return jsonify({'status': 'error'}), 400

    history_id = decoded.get('historyId')
    if not history_id:
        logger.warning("Gmail Pub/Sub: no historyId in payload")
        return jsonify({'status': 'ignored'}), 200

    logger.info("Gmail Pub/Sub push: historyId=%s", history_id)

    try:
        from retromonkey.services.gmail_client import GmailClient
        from retromonkey.app import db

        gmail = GmailClient(db)
        messages = gmail.get_messages_from_history(str(history_id))

        for msg in messages:
            try:
                _process_gmail_message(msg, gmail)
            except Exception as exc:
                logger.error("Error processing Gmail message %s: %s", msg.get('id'), exc)

    except Exception as exc:
        logger.error("Gmail Pub/Sub handler error: %s", exc)

    # Always return 200 so Pub/Sub doesn't retry
    return jsonify({'status': 'ok', 'processed': len(messages) if 'messages' in dir() else 0}), 200


def _process_gmail_message(msg: dict, gmail):
    """Apply sender rules to a Gmail message and take action."""
    from retromonkey.app import db
    from retromonkey.services.telegram_client import TelegramClient

    sender = msg.get('from', '').lower()
    subject = msg.get('subject', '')
    snippet = msg.get('snippet', '')
    msg_id = msg.get('id', '')
    tg = TelegramClient()

    # Boss — aaronjking86@gmail.com, slothitudegames@gmail.com
    if 'aaronjking86' in sender or 'slothitudegames' in sender:
        gmail.apply_label(msg_id, 'RM-Boss')
        tg.send_message(
            f"<b>Command from Boss</b>\n"
            f"<b>From:</b> {msg.get('from', '')}\n"
            f"<b>Subject:</b> {subject}\n"
            f"<b>Snippet:</b> {snippet[:200]}",
            parse_mode="HTML",
        )

    # eBay
    elif 'ebay' in sender or 'reply.ebay' in sender:
        sub_lower = subject.lower()
        if any(kw in sub_lower for kw in ['listed', 'listing', 'sold', 'order', 'purchase', 'payment', 'payout']):
            gmail.apply_label(msg_id, 'RM-eBay-Action')
            tg.send_message(
                f"<b>eBay Action</b>\n<b>Subject:</b> {subject}\n{snippet[:150]}",
                parse_mode="HTML",
            )
        else:
            gmail.apply_label(msg_id, 'RM-eBay-Routine')
            # Silently mark routine eBay mail as read
            service = gmail._get_service()
            service.users().messages().modify(
                userId='me', id=msg_id,
                body={'removeLabelIds': ['UNREAD']},
            ).execute()

    # Customer — anyone about orders/products/shipping
    elif any(kw in subject.lower() for kw in ['order', 'shipping', 'product', 'return', 'refund']):
        gmail.apply_label(msg_id, 'RM-Customer')
        tg.send_message(
            f"<b>Customer Email</b>\n"
            f"<b>From:</b> {msg.get('from', '')}\n"
            f"<b>Subject:</b> {subject}\n"
            f"{snippet[:200]}",
            parse_mode="HTML",
        )

    # Supplier
    elif 'alibaba' in sender or 'supplier' in sender or 'wholesale' in sender:
        gmail.apply_label(msg_id, 'RM-Supplier')
        tg.send_message(
            f"<b>Supplier Email</b>\n<b>From:</b> {msg.get('from', '')}\n<b>Subject:</b> {subject}",
            parse_mode="HTML",
        )

    # Stripe / Payments
    elif 'stripe' in sender:
        gmail.apply_label(msg_id, 'RM-Stripe')
        sub_lower = subject.lower()
        if any(kw in sub_lower for kw in ['chargeback', 'dispute', 'reversal', 'failed']):
            tg.send_message(
                f"<b>CRITICAL: Stripe Alert</b>\n<b>Subject:</b> {subject}",
                parse_mode="HTML",
            )
        # Mark as read
        service = gmail._get_service()
        service.users().messages().modify(
            userId='me', id=msg_id,
            body={'removeLabelIds': ['UNREAD']},
        ).execute()

    # Everything else
    else:
        gmail.apply_label(msg_id, 'RM-Other')
        service = gmail._get_service()
        service.users().messages().modify(
            userId='me', id=msg_id,
            body={'removeLabelIds': ['UNREAD']},
        ).execute()


@webhook_bp.route('/webhooks/telegram', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram updates (callback queries and messages).

    Callback data format: ``action:payload`` (e.g. ``mark_read:12345``).
    """
    data = request.json or {}
    logger.info("Telegram webhook received: %s", data)

    # Handle callback queries (inline button presses)
    callback = data.get('callback_query')
    if callback:
        return _handle_callback(callback)

    # Handle regular messages (future: /status, /orders commands)
    message = data.get('message')
    if message:
        return _handle_message(message)

    return jsonify({'status': 'ok'}), 200


def _handle_callback(callback: dict):
    """Process a Telegram callback query from an inline button press."""
    from retromonkey.services.telegram_client import TelegramClient
    from retromonkey.app import db

    query_id = callback.get('id', '')
    callback_data = callback.get('data', '')
    chat_id = str(callback.get('message', {}).get('chat', {}).get('id', ''))

    logger.info("Telegram callback: %s", callback_data)

    parts = callback_data.split(':', 2)
    action = parts[0] if parts else ''
    source = parts[1] if len(parts) > 1 else ''
    payload = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else '')

    tg = TelegramClient()
    result_text = "Action received"

    try:
        if action == 'mark_read' and payload:
            if source == 'email':
                # IMAP-based mark read
                from retromonkey.services.imap_monitor import IMAPMonitor
                monitor = IMAPMonitor(current_app.config)
                monitor.mark_read(payload)
                monitor.close()
                result_text = "Marked as read"
            else:
                # Legacy Gmail API mark read (fallback)
                try:
                    from retromonkey.services.gmail_client import GmailClient
                    gmail = GmailClient(db)
                    service = gmail._get_service()
                    service.users().messages().modify(
                        userId='me', id=payload,
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                    result_text = "Marked as read"
                except Exception:
                    result_text = "Mark as read failed (Gmail API unavailable)"

        elif action == 'draft_reply' and payload:
            if source == 'email':
                # IMAP email — draft reply via sender rules
                from retromonkey.services.imap_monitor import IMAPMonitor
                monitor = IMAPMonitor(current_app.config)
                monitor.mark_read(payload)
                monitor.close()
                result_text = "Noted — reply pending. Email marked as read."
            else:
                from retromonkey.services.communications import CommunicationsService
                from retromonkey.services.llm_router import LLMRouter
                comms = CommunicationsService(db, LLMRouter())
                draft = comms.draft_reply(int(payload))
                result_text = f"Draft created: {draft.get('body', '')[:100]}..."

        elif action == 'view_order' and payload:
            result_text = f"Order #{payload}"

        elif action == 'mark_processing' and payload:
            from retromonkey.models.order import Order
            order = db.session.get(Order, int(payload))
            if order:
                order.status = 'processing'
                db.session.commit()
                result_text = f"Order #{payload} marked as processing"
            else:
                result_text = f"Order #{payload} not found"

        elif action == 'reorder' and payload:
            result_text = f"Reorder requested for {payload}"

        elif action == 'view_product' and payload:
            result_text = f"Product {payload}"

        # ---- Report button callbacks (Telegram-only) ----
        elif action == 'view_checklist':
            from retromonkey.services.task_manager import TaskManager
            tm = TaskManager(db)
            tasks = tm.get_daily_summary()
            categories = tasks.get("categories", {})
            cat_lines = "\n".join(f"  {k}: {v.get('done', 0)}/{v.get('total', 0)}" if isinstance(v, dict) else f"  {k}: {v}" for k, v in categories.items()) if categories else "  (none)"
            result_text = (
                f"<b>Today's Checklist</b>\n"
                f"Pending: {tasks.get('pending', 0)} | Done: {tasks.get('completed', 0)}/{tasks.get('total', 0)}\n"
                f"Categories:\n{cat_lines}"
            )
            tg.send_message(result_text, parse_mode="HTML")
            result_text = "Checklist sent"

        elif action == 'check_ebay':
            try:
                from retromonkey.models import Marketplace
                from retromonkey.connectors.ebay import EbayConnector
                from flask import current_app
                mp = Marketplace.query.filter_by(name="eBay", active=True).first()
                if mp:
                    conn = EbayConnector(mp, current_app.config)
                    if conn.is_authenticated():
                        orders = conn.get_orders()
                        if isinstance(orders, list) and orders:
                            lines = []
                            for o in orders[:10]:
                                if isinstance(o, dict):
                                    lines.append(f"#{o.get('external_order_id', '?')} - ${o.get('total', '0')} ({o.get('source', 'ebay')})")
                            msg = f"<b>eBay Orders ({len(orders)})</b>\n" + "\n".join(lines)
                        else:
                            msg = "<b>eBay Orders</b>\nNo new orders"
                        tg.send_message(msg, parse_mode="HTML")
                        result_text = "eBay orders sent"
                    else:
                        result_text = "eBay not authenticated"
                else:
                    result_text = "No eBay marketplace configured"
            except Exception as exc:
                result_text = f"eBay check failed: {exc}"

        elif action == 'view_stock':
            from retromonkey.services.inventory import InventoryService
            inv = InventoryService(db)
            low = inv.get_low_stock_products()
            if low:
                lines = [f"  {p.title}: <b>{p.stock}</b> left" for p in low[:10]]
                msg = f"<b>Low Stock ({len(low)} items)</b>\n" + "\n".join(lines)
            else:
                msg = "<b>Stock Status</b>\nAll products above threshold"
            tg.send_message(msg, parse_mode="HTML")
            result_text = "Stock report sent"

        elif action == 'view_pnl':
            from retromonkey.services.accounting import AccountingService
            acc = AccountingService(db)
            pnl = acc.get_pnl_report("daily")
            msg = (
                f"<b>Today's P&L</b>\n"
                f"Revenue: ${pnl.get('revenue', 0):.2f}\n"
                f"COGS: ${pnl.get('cogs', 0):.2f}\n"
                f"Fees: ${pnl.get('fees', 0):.2f}\n"
                f"Profit: <b>${pnl.get('profit', 0):.2f}</b>"
            )
            tg.send_message(msg, parse_mode="HTML")
            result_text = "P&L snapshot sent"

        elif action == 'view_tasks':
            from retromonkey.services.task_manager import TaskManager
            tm = TaskManager(db)
            summary = tm.get_daily_summary()
            categories = summary.get("categories", {})
            cat_lines = "\n".join(f"  {k}: {v.get('done', 0)}/{v.get('total', 0)}" if isinstance(v, dict) else f"  {k}: {v}" for k, v in categories.items()) if categories else "  (none)"
            msg = (
                f"<b>Task Detail</b>\n"
                f"Completed: {summary.get('completed', 0)}/{summary.get('total', 0)} ({summary.get('completion_pct', 0)}%)\n"
                f"Overdue: {summary.get('overdue', 0)}\n"
                f"By Category:\n{cat_lines}"
            )
            tg.send_message(msg, parse_mode="HTML")
            result_text = "Task detail sent"

        elif action == 'full_pnl':
            from retromonkey.services.accounting import AccountingService
            acc = AccountingService(db)
            pnl = acc.get_pnl_report("weekly")
            revenue = pnl.get("revenue", 0)
            profit = pnl.get("profit", 0)
            margin = (profit / revenue * 100) if revenue else 0
            msg = (
                f"<b>Weekly P&L</b>\n"
                f"Revenue: ${revenue:.2f}\n"
                f"COGS: ${pnl.get('cogs', 0):.2f}\n"
                f"Fees: ${pnl.get('fees', 0):.2f}\n"
                f"Profit: <b>${profit:.2f}</b> ({margin:.1f}%)"
            )
            tg.send_message(msg, parse_mode="HTML")
            result_text = "Weekly P&L sent"

        elif action == 'tomorrow_plan':
            from retromonkey.services.task_manager import TaskManager
            tm = TaskManager(db)
            summary = tm.get_daily_summary()
            overdue = summary.get("overdue", 0)
            msg = (
                f"<b>Tomorrow's Plan</b>\n"
                f"Carry-over tasks: {summary.get('pending', 0)}\n"
                f"Overdue to prioritize: {overdue}\n"
                f"Recurring tasks will be generated at 8:30 AM"
            )
            tg.send_message(msg, parse_mode="HTML")
            result_text = "Tomorrow's plan sent"

        elif action == 'reorder_low':
            from retromonkey.services.inventory import InventoryService
            inv = InventoryService(db)
            reorder = inv.check_reorder_needed()
            if reorder:
                lines = [f"  {r.get('title', '?')}: {r.get('quantity', 0)} left (min: {r.get('reorder_threshold', '?')})" for r in reorder[:10]]
                msg = f"<b>Reorder Suggestions ({len(reorder)})</b>\n" + "\n".join(lines)
            else:
                msg = "<b>Reorder Check</b>\nNo items need reordering"
            tg.send_message(msg, parse_mode="HTML")
            result_text = "Reorder report sent"

        elif action == 'view_products':
            from retromonkey.models import Product
            products = db.session.query(Product).all()
            if products:
                lines = [f"  {p.title}: <b>{p.stock}</b> in stock (${p.price:.2f})" for p in products[:15]]
                msg = f"<b>Products ({len(products)})</b>\n" + "\n".join(lines)
            else:
                msg = "<b>Products</b>\nNo products found"
            tg.send_message(msg, parse_mode="HTML")
            result_text = "Product list sent"

        else:
            result_text = f"Unknown action: {action}"

    except Exception as exc:
        logger.error("Telegram callback handler error: %s", exc)
        result_text = f"Error: {exc}"

    tg.answer_callback_query(query_id, text=result_text)
    return jsonify({'status': 'ok'}), 200


def _handle_message(message: dict):
    """Process a regular Telegram message — slash commands and freeform."""
    from retromonkey.services.telegram_client import TelegramClient
    from retromonkey.app import db

    tg = TelegramClient()
    chat_id = str(message.get('chat', {}).get('id', ''))
    text = (message.get('text') or '').strip()

    # Security: only respond to the configured chat
    if chat_id != tg._chat_id:
        logger.warning("Telegram message from unauthorized chat: %s", chat_id)
        return jsonify({'status': 'ignored'}), 200

    if not text:
        return jsonify({'status': 'ok'}), 200

    logger.info("Telegram command: %s", text)

    # Slash commands
    if text.startswith('/'):
        parts = text.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ''

        try:
            response = _dispatch_command(cmd, arg, db)
        except Exception as exc:
            logger.error("Telegram command error: %s", exc)
            response = f"Error: {exc}"

        tg.send_message(response, parse_mode="HTML")
        return jsonify({'status': 'ok'}), 200

    # Freeform message → LLM
    try:
        from retromonkey.services.llm_router import LLMRouter
        router = LLMRouter()
        system_prompt = (
            "You are RetroMonkey AI, an assistant for the RetroMonkey e-commerce platform. "
            "Answer questions about orders, products, stock, P&L, and operations concisely. "
            "Use HTML formatting for Telegram (bold, italic). Keep responses under 1000 chars."
        )
        result = router.query(text, mode='auto', system=system_prompt, max_tokens=512)
        reply = result.get('text') or "I couldn't process that. Try again."
        # Truncate for Telegram
        if len(reply) > 4000:
            reply = reply[:3997] + "..."
        tg.send_message(reply, parse_mode="HTML")
    except Exception as exc:
        logger.error("Telegram LLM error: %s", exc)
        tg.send_message(f"LLM error: {exc}", parse_mode="HTML")

    return jsonify({'status': 'ok'}), 200


def _dispatch_command(cmd: str, arg: str, db_instance) -> str:
    """Route a slash command to the appropriate handler and return an HTML response."""

    if cmd in ('/start', '/help'):
        return (
            "<b>RetroMonkey Bot</b>\n\n"
            "Commands:\n"
            "/status — System health\n"
            "/orders — Recent orders\n"
            "/stock — Low stock report\n"
            "/products — All products + prices\n"
            "/pnl [weekly] — P&L report\n"
            "/tasks — Today's tasks\n"
            "/ebay — eBay orders + listings\n"
            "/emails — Unread email count\n\n"
            "Or just type a question!"
        )

    if cmd == '/status':
        return _cmd_status(db_instance)

    if cmd == '/orders':
        return _cmd_orders(db_instance)

    if cmd == '/stock':
        return _cmd_stock(db_instance)

    if cmd == '/products':
        return _cmd_products(db_instance)

    if cmd == '/pnl':
        period = 'weekly' if 'week' in arg.lower() else 'daily'
        return _cmd_pnl(db_instance, period)

    if cmd == '/tasks':
        return _cmd_tasks(db_instance)

    if cmd == '/ebay':
        return _cmd_ebay(db_instance)

    if cmd == '/emails':
        return _cmd_emails(db_instance)

    return f"Unknown command: {cmd}. Try /help"


def _cmd_status(db_instance):
    from retromonkey.models import Product, Marketplace
    product_count = db_instance.session.query(Product).count()
    active_mp = db_instance.session.query(Marketplace).filter_by(active=True).count()
    return (
        f"<b>System Status</b>\n"
        f"Products: {product_count}\n"
        f"Active marketplaces: {active_mp}\n"
        f"Status: Operational"
    )


def _cmd_orders(db_instance):
    from retromonkey.models.order import Order
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=7)
    orders = db_instance.session.query(Order).filter(Order.ordered_at >= since).order_by(Order.ordered_at.desc()).limit(10).all()
    if not orders:
        return "<b>Orders</b>\nNo orders in the last 7 days"
    lines = []
    for o in orders:
        lines.append(f"#{o.id} — ${o.total:.2f} ({o.status}) {o.source or ''}")
    return f"<b>Recent Orders ({len(orders)})</b>\n" + "\n".join(lines)


def _cmd_stock(db_instance):
    from retromonkey.services.inventory import InventoryService
    inv = InventoryService(db_instance)
    low = inv.get_low_stock_products()
    if low:
        lines = [f"  {p.title}: <b>{p.stock}</b> left" for p in low[:10]]
        return f"<b>Low Stock ({len(low)})</b>\n" + "\n".join(lines)
    return "<b>Stock</b>\nAll products above threshold"


def _cmd_products(db_instance):
    from retromonkey.models import Product
    products = db_instance.session.query(Product).all()
    if not products:
        return "<b>Products</b>\nNo products found"
    lines = [f"  {p.title}: <b>{p.stock}</b> @ ${p.price:.2f}" for p in products[:15]]
    return f"<b>Products ({len(products)})</b>\n" + "\n".join(lines)


def _cmd_pnl(db_instance, period):
    from retromonkey.services.accounting import AccountingService
    acc = AccountingService(db_instance)
    pnl = acc.get_pnl_report(period)
    revenue = pnl.get('revenue', 0)
    profit = pnl.get('profit', 0)
    margin = (profit / revenue * 100) if revenue else 0
    label = 'Weekly' if period == 'weekly' else "Today's"
    return (
        f"<b>{label} P&L</b>\n"
        f"Revenue: ${revenue:.2f}\n"
        f"COGS: ${pnl.get('cogs', 0):.2f}\n"
        f"Fees: ${pnl.get('fees', 0):.2f}\n"
        f"Profit: <b>${profit:.2f}</b> ({margin:.1f}%)"
    )


def _cmd_tasks(db_instance):
    from retromonkey.services.task_manager import TaskManager
    tm = TaskManager(db_instance)
    summary = tm.get_daily_summary()
    return (
        f"<b>Today's Tasks</b>\n"
        f"Done: {summary.get('completed', 0)}/{summary.get('total', 0)} "
        f"({summary.get('completion_pct', 0)}%)\n"
        f"Pending: {summary.get('pending', 0)}\n"
        f"Overdue: {summary.get('overdue', 0)}"
    )


def _cmd_ebay(db_instance):
    from retromonkey.models import Marketplace, Listing
    from retromonkey.connectors.ebay import EbayConnector
    from flask import current_app

    lines = []
    mp = Marketplace.query.filter_by(name='eBay', active=True).first()
    if not mp:
        return "<b>eBay</b>\nNot configured"

    try:
        conn = EbayConnector(mp, current_app.config)
        if conn.is_authenticated():
            orders = conn.get_orders()
            if isinstance(orders, list) and orders:
                lines.append(f"<b>eBay Orders ({len(orders)})</b>")
                for o in orders[:5]:
                    if isinstance(o, dict):
                        lines.append(f"  #{o.get('external_order_id', '?')} — ${o.get('total', '0')}")
            else:
                lines.append("<b>eBay Orders</b>\n  No new orders")
        else:
            lines.append("eBay not authenticated")
    except Exception as exc:
        lines.append(f"eBay error: {exc}")

    listings = db_instance.session.query(Listing).filter_by(status='ACTIVE').all()
    lines.append(f"\nActive listings: {len(listings)}")

    return "\n".join(lines)


def _cmd_emails(db_instance):
    from retromonkey.services.gmail_client import GmailClient
    gmail = GmailClient(db_instance)
    messages = gmail.list_messages(query='is:unread', max_results=5)
    if not messages:
        return "<b>Emails</b>\nNo unread messages"
    lines = [f"  {m.get('from', '?').split('<')[0].strip()}: {m.get('subject', '')[:50]}" for m in messages]
    total = len(messages)
    return f"<b>Unread Emails</b> (showing {total})\n" + "\n".join(lines)
