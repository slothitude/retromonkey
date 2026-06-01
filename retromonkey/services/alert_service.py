"""Unified alert service — dispatches to email and/or Telegram."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AlertService:
    """Central dispatch for all RetroMonkey alerts.

    Sends to whichever channels are configured (email via Gmail, Telegram via Bot API).
    """

    def __init__(self, db_instance=None, config=None):
        self.db = db_instance
        self._config = config

    def _get_config(self):
        if self._config:
            return self._config
        from flask import current_app
        return current_app.config

    def _telegram(self):
        from retromonkey.services.telegram_client import TelegramClient
        return TelegramClient(self._get_config())

    def _gmail(self):
        from retromonkey.services.gmail_client import GmailClient
        return GmailClient(self.db)

    @property
    def telegram_enabled(self) -> bool:
        return self._get_config().get("ALERT_TELEGRAM_ENABLED", False)

    @property
    def alert_email(self) -> str:
        return self._get_config().get("ALERT_EMAIL", "aaronjking86@gmail.com")

    def send_alert(self, subject: str, plain_text: str, html_text: str = "",
                   telegram_buttons: list | None = None) -> dict:
        """Send an alert to all configured channels.

        Parameters
        ----------
        subject : str
            Email subject line.
        plain_text : str
            Plain text body (used for email body and Telegram fallback).
        html_text : str
            HTML-formatted text for Telegram (Telegram supports HTML).
        telegram_buttons : list | None
            Optional list of inline keyboard button rows for Telegram.
            Each row is a list of dicts: [{"text": "Label", "callback_data": "action:payload"}]
        """
        results = {"email": None, "telegram": None}

        # Email via Resend
        try:
            from retromonkey.services.resend_sender import send_email
            html_body = html_text.replace("\n", "<br>") if html_text else plain_text.replace("\n", "<br>")
            send_email(
                to=self.alert_email,
                subject=subject,
                html=f"<div style='font-family:sans-serif'>{html_body}</div>",
                text=plain_text,
                from_addr="alerts@retromonkey.com.au",
            )
            results["email"] = "sent"
        except Exception as exc:
            logger.error("Alert email via Resend failed: %s", exc)
            # Fallback to Gmail
            try:
                gmail = self._gmail()
                gmail.send_email(
                    to=self.alert_email,
                    subject=subject,
                    body=plain_text,
                )
                results["email"] = "sent (gmail fallback)"
            except Exception as exc2:
                logger.error("Alert email fallback also failed: %s", exc2)
                results["email"] = f"failed: {exc}"

        # Telegram
        if self.telegram_enabled:
            try:
                tg = self._telegram()
                reply_markup = None
                if telegram_buttons:
                    reply_markup = {"inline_keyboard": telegram_buttons}
                tg_text = html_text or plain_text
                resp = tg.send_message(tg_text, parse_mode="HTML", reply_markup=reply_markup)
                results["telegram"] = "sent" if resp.get("ok") else f"failed: {resp.get('description', 'unknown')}"
            except Exception as exc:
                logger.error("Alert Telegram failed: %s", exc)
                results["telegram"] = f"failed: {exc}"
        else:
            results["telegram"] = "disabled"

        return results

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def alert_new_order(self, order_data: dict) -> dict:
        """Alert for a new order (eBay or web store)."""
        order_id = order_data.get("order_id", "?")
        buyer = order_data.get("buyer", "Unknown")
        total = order_data.get("total", "0.00")
        items = order_data.get("items", [])
        source = order_data.get("source", "web")

        item_lines = "\n".join(f"  - {i}" for i in items) if items else "  (no item details)"

        plain = (
            f"New Order #{order_id}\n"
            f"Source: {source}\n"
            f"Buyer: {buyer}\n"
            f"Total: ${total} AUD\n"
            f"Items:\n{item_lines}"
        )
        html = (
            f"<b>New Order #{order_id}</b>\n"
            f"Source: {source}\n"
            f"Buyer: {buyer}\n"
            f"Total: <b>${total} AUD</b>\n"
            f"Items:\n{item_lines}"
        )

        buttons = [[
            {"text": "View Order", "callback_data": f"view_order:{order_id}"},
            {"text": "Mark Processing", "callback_data": f"mark_processing:{order_id}"},
        ]]

        return self.send_alert(
            subject=f"[RetroMonkey] New Order #{order_id}",
            plain_text=plain,
            html_text=html,
            telegram_buttons=buttons,
        )

    def alert_low_stock(self, product_data: dict) -> dict:
        """Alert for a product below reorder threshold."""
        sku = product_data.get("sku", "?")
        title = product_data.get("title", "Unknown Product")
        qty = product_data.get("quantity", 0)
        threshold = product_data.get("reorder_threshold", "?")

        plain = (
            f"Low Stock Alert: {title}\n"
            f"SKU: {sku}\n"
            f"Remaining: {qty}\n"
            f"Reorder Threshold: {threshold}"
        )
        html = (
            f"<b>Low Stock Alert</b>\n"
            f"{title}\n"
            f"SKU: {sku}\n"
            f"Remaining: <b>{qty}</b> (threshold: {threshold})"
        )

        buttons = [[
            {"text": "Create Reorder", "callback_data": f"reorder:{sku}"},
            {"text": "View Product", "callback_data": f"view_product:{sku}"},
        ]]

        return self.send_alert(
            subject=f"[RetroMonkey] Low Stock: {title} ({qty} left)",
            plain_text=plain,
            html_text=html,
            telegram_buttons=buttons,
        )

    def alert_customer_message(self, msg_data: dict) -> dict:
        """Alert for a customer message requiring attention."""
        sender = msg_data.get("from", "Unknown")
        subject = msg_data.get("subject", "(no subject)")
        snippet = msg_data.get("snippet", "")
        message_id = msg_data.get("message_id", "")

        plain = (
            f"Customer Message\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Snippet: {snippet[:200]}"
        )
        html = (
            f"<b>Customer Message</b>\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"<i>{snippet[:200]}</i>"
        )

        buttons = [[
            {"text": "Draft Reply", "callback_data": f"draft_reply:{message_id}"},
            {"text": "Mark Read", "callback_data": f"mark_read:{message_id}"},
        ]]

        return self.send_alert(
            subject=f"[RetroMonkey] Customer: {subject}",
            plain_text=plain,
            html_text=html,
            telegram_buttons=buttons,
        )

    def alert_morning_briefing(self) -> dict:
        """Morning briefing — checklist, overnight orders, low stock."""
        from retromonkey.services.task_manager import TaskManager
        from retromonkey.services.inventory import InventoryService

        tm = TaskManager(self.db)
        inv = InventoryService(self.db)

        # Today's checklist
        summary = tm.get_daily_summary()
        categories = summary.get("categories", {})
        cat_lines = "\n".join(f"  {k}: {v.get('done', 0)}/{v.get('total', 0)}" if isinstance(v, dict) else f"  {k}: {v}" for k, v in categories.items()) if categories else "  (none)"

        # Low stock
        low_stock = inv.get_low_stock_products()
        low_count = len(low_stock)
        stock_warn = ""
        if low_count:
            stock_warn = f"\nLow Stock: <b>{low_count} items</b> below threshold"

        # Overnight orders (poll eBay)
        overnight = ""
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
                        overnight = f"\nOvernight Orders: <b>{len(orders)} new</b>"
        except Exception:
            pass

        plain = (
            f"RetroMonkey Morning Briefing\n"
            f"Today's Tasks: {summary.get('pending', 0)} pending across {len(categories)} categories\n"
            f"Categories:\n{cat_lines}"
            f"{stock_warn}\n"
            f"{overnight}"
        )
        html = (
            f"<b>RetroMonkey Morning Briefing</b>\n"
            f"Today's Tasks: <b>{summary.get('pending', 0)} pending</b> across {len(categories)} categories\n"
            f"Categories:\n{cat_lines}"
            f"{stock_warn}\n"
            f"{overnight}"
        )

        buttons = [
            [
                {"text": "View Checklist", "callback_data": "view_checklist"},
                {"text": "Check eBay", "callback_data": "check_ebay"},
            ],
            [
                {"text": "View Stock", "callback_data": "view_stock"},
            ],
        ]

        return self.send_alert(
            subject="[RetroMonkey] Morning Briefing",
            plain_text=plain,
            html_text=html,
            telegram_buttons=buttons,
        )

    def alert_daily_summary(self, summary: dict) -> dict:
        """Enhanced daily summary — tasks, P&L, stock, business plan progress."""
        completed = summary.get("completed", 0)
        total = summary.get("total", 0)
        pct = summary.get("completion_pct", 0)
        categories = summary.get("categories", {})
        cat_lines = "\n".join(f"  {k}: {v.get('done', 0)}/{v.get('total', 0)}" if isinstance(v, dict) else f"  {k}: {v}" for k, v in categories.items()) if categories else "  (none)"

        # P&L snapshot
        pnl_section = ""
        try:
            from retromonkey.services.accounting import AccountingService
            acc = AccountingService(self.db)
            pnl = acc.get_pnl_report("daily")
            revenue = pnl.get("revenue", 0)
            fees = pnl.get("fees", 0)
            profit = pnl.get("profit", 0)
            pnl_section = f"\nP&L Today: Rev ${revenue:.2f} | Fees ${fees:.2f} | Profit ${profit:.2f}"
        except Exception:
            pass

        # Low stock count
        stock_count = 0
        try:
            from retromonkey.services.inventory import InventoryService
            inv = InventoryService(self.db)
            stock_count = len(inv.get_low_stock_products())
        except Exception:
            pass
        stock_section = f"\nLow Stock: {stock_count} items" if stock_count else "\nStock: All OK"

        # Business plan progress
        plan_section = ""
        try:
            from retromonkey.services.task_manager import TaskManager
            tm = TaskManager(self.db)
            progress = tm.get_business_plan_progress()
            monthly_orders = progress.get("monthly_orders", 0)
            monthly_revenue = progress.get("monthly_revenue", 0)
            target = progress.get("monthly_target", 0)
            plan_section = f"\nPlan: {monthly_orders} orders | ${monthly_revenue:.0f}/${target:.0f} rev"
        except Exception:
            pass

        plain = (
            f"RetroMonkey Daily Summary\n"
            f"Tasks: {completed}/{total} completed ({pct}%)\n"
            f"By Category:\n{cat_lines}"
            f"{pnl_section}"
            f"{stock_section}"
            f"{plan_section}"
        )
        html = (
            f"<b>RetroMonkey Daily Summary</b>\n"
            f"Tasks: <b>{completed}/{total}</b> completed ({pct}%)\n"
            f"By Category:\n{cat_lines}"
            f"{pnl_section}"
            f"{stock_section}"
            f"{plan_section}"
        )

        buttons = [
            [
                {"text": "View P&L", "callback_data": "view_pnl"},
                {"text": "View Tasks", "callback_data": "view_tasks"},
            ],
            [
                {"text": "Check Stock", "callback_data": "view_stock"},
                {"text": "Tomorrow's Plan", "callback_data": "tomorrow_plan"},
            ],
        ]

        return self.send_alert(
            subject="[RetroMonkey] Daily Summary",
            plain_text=plain,
            html_text=html,
            telegram_buttons=buttons,
        )

    def alert_weekly_report(self) -> dict:
        """Weekly report — P&L, top sellers, stock status, task completion."""
        from retromonkey.services.accounting import AccountingService
        from retromonkey.services.inventory import InventoryService
        from retromonkey.services.task_manager import TaskManager

        acc = AccountingService(self.db)
        inv = InventoryService(self.db)
        tm = TaskManager(self.db)

        # Weekly P&L
        pnl = acc.get_pnl_report("weekly")
        revenue = pnl.get("revenue", 0)
        fees = pnl.get("fees", 0)
        cogs = pnl.get("cogs", 0)
        profit = pnl.get("profit", 0)
        margin = (profit / revenue * 100) if revenue else 0

        # Top sellers
        top_sellers = []
        try:
            from retromonkey.models import Product
            products = self.db.session.query(Product).all()
            # Sort by sales count if available
            top_sellers = [f"{p.title} ({p.stock} in stock)" for p in products[:5]]
        except Exception:
            pass
        top_lines = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(top_sellers)) if top_sellers else "  (no data)"

        # Stock status
        low_stock = inv.get_low_stock_products()
        from retromonkey.models import Product
        total_skus = self.db.session.query(Product).count()

        # Task completion
        daily = tm.get_daily_summary()

        plain = (
            f"RetroMonkey Weekly Report\n"
            f"\nP&L (Weekly):\n"
            f"  Revenue: ${revenue:.2f}\n"
            f"  COGS: ${cogs:.2f}\n"
            f"  Fees: ${fees:.2f}\n"
            f"  Profit: ${profit:.2f} ({margin:.1f}%)\n"
            f"\nTop Products:\n{top_lines}\n"
            f"\nStock: {total_skus} SKUs, {len(low_stock)} low\n"
            f"\nTasks today: {daily.get('completed', 0)}/{daily.get('total', 0)} done"
        )
        html = (
            f"<b>RetroMonkey Weekly Report</b>\n"
            f"\n<b>P&L (Weekly)</b>\n"
            f"  Revenue: ${revenue:.2f}\n"
            f"  COGS: ${cogs:.2f}\n"
            f"  Fees: ${fees:.2f}\n"
            f"  Profit: <b>${profit:.2f}</b> ({margin:.1f}%)\n"
            f"\n<b>Top Products</b>\n{top_lines}\n"
            f"\nStock: {total_skus} SKUs, <b>{len(low_stock)} low</b>\n"
            f"\nTasks today: {daily.get('completed', 0)}/{daily.get('total', 0)} done"
        )

        buttons = [
            [
                {"text": "Full P&L", "callback_data": "full_pnl"},
                {"text": "Reorder Low Stock", "callback_data": "reorder_low"},
            ],
            [
                {"text": "View Products", "callback_data": "view_products"},
            ],
        ]

        return self.send_alert(
            subject="[RetroMonkey] Weekly Report",
            plain_text=plain,
            html_text=html,
            telegram_buttons=buttons,
        )

    def alert_system_health(self, health_data: dict) -> dict:
        """Alert for system health issues (site down, errors)."""
        status = health_data.get("status", "unknown")
        details = health_data.get("details", "")

        plain = f"System Health Alert\nStatus: {status}\nDetails: {details}"
        html = f"<b>System Health Alert</b>\nStatus: <b>{status}</b>\n{details}"

        return self.send_alert(
            subject=f"[RetroMonkey] System Health: {status}",
            plain_text=plain,
            html_text=html,
        )

    def send_test_alert(self) -> dict:
        """Send a test alert to verify all channels work."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        plain = f"RetroMonkey Test Alert\nSent at: {now}\nAll systems operational."
        html = f"<b>RetroMonkey Test Alert</b>\nSent at: {now}\nAll systems operational."

        return self.send_alert(
            subject="[RetroMonkey] Test Alert",
            plain_text=plain,
            html_text=html,
        )
