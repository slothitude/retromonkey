import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler

db = SQLAlchemy()
scheduler = APScheduler()


def create_app(config_name='dev'):
    app = Flask(__name__)

    from .config import DevConfig, ProdConfig
    config_map = {'dev': DevConfig, 'prod': ProdConfig}
    app.config.from_object(config_map.get(config_name, DevConfig))

    db.init_app(app)
    scheduler.init_app(app)

    # ── Public store blueprint (no prefix — serves /) ──
    from .routes.store import store_bp
    app.register_blueprint(store_bp)

    # ── Customer account blueprint ──
    from .routes.customers import customers_bp
    app.register_blueprint(customers_bp)

    # ── Admin dashboard (moved to /admin) ──
    from .routes.pages import pages_bp
    app.register_blueprint(pages_bp, url_prefix='/admin')

    # ── API blueprints ──
    from .routes.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from .routes.marketplace import marketplace_bp
    app.register_blueprint(marketplace_bp, url_prefix='/api/marketplace')

    from .routes.webhooks import webhook_bp
    app.register_blueprint(webhook_bp)

    from .routes.sourcing import sourcing_bp
    app.register_blueprint(sourcing_bp, url_prefix='/api/sourcing')

    from .routes.intelligence import intelligence_bp
    app.register_blueprint(intelligence_bp, url_prefix='/api/intelligence')

    from .routes.tasks import tasks_bp
    app.register_blueprint(tasks_bp, url_prefix='/api/tasks')

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()
        _seed_store_products(app)

    # Skip scheduler in MCP mode
    if not os.environ.get('MCP_MODE'):
        _setup_scheduler(app)
        scheduler.start()
        _register_telegram_webhook(app)
        _register_gmail_watch(app)

    return app


def _seed_store_products(app):
    """Ensure products have slugs and store-relevant data."""
    from .models import Product
    with app.app_context():
        for p in db.session.query(Product).all():
            if not p.slug:
                p.generate_slug()
        db.session.commit()


def _setup_scheduler(app):
    @scheduler.task('interval', id='poll_orders', minutes=15)
    def poll_orders():
        with app.app_context():
            from .models import Marketplace
            from .connectors.ebay import EbayConnector
            from .services.alert_service import AlertService
            from .services.order_sync import OrderSyncService
            alert_svc = AlertService(db)
            for mp in Marketplace.query.filter_by(active=True).all():
                if mp.name == 'eBay':
                    try:
                        conn = EbayConnector(mp, app.config)
                        if conn.is_authenticated():
                            orders = conn.get_orders()
                            if isinstance(orders, list):
                                sync_svc = OrderSyncService(db)
                                for order_data in orders:
                                    if isinstance(order_data, dict):
                                        sync_svc.sync_order(order_data, mp.id)
                                        alert_svc.alert_new_order(order_data)
                    except Exception as exc:
                        app.logger.error("poll_orders failed for %s: %s", mp.name, exc)

    @scheduler.task('interval', id='sync_inventory', minutes=30)
    def sync_inventory():
        with app.app_context():
            try:
                from .services.sync import InventorySyncService
                sync_svc = InventorySyncService(db, _connector_factory)
                sync_svc.sync_all()
            except Exception as exc:
                app.logger.error("sync_inventory failed: %s", exc)

    @scheduler.task('cron', id='reorder_check', hour=7)
    def reorder_check():
        with app.app_context():
            try:
                from .services.inventory import InventoryService
                from .services.alert_service import AlertService
                inv = InventoryService(db)
                low = inv.check_reorder_needed()
                alert_svc = AlertService(db)
                for item in low if isinstance(low, list) else []:
                    if isinstance(item, dict):
                        alert_svc.alert_low_stock(item)
            except Exception as exc:
                app.logger.error("reorder_check failed: %s", exc)

    @scheduler.task('cron', id='daily_checklist', hour=8, minute=30)
    def daily_checklist():
        with app.app_context():
            try:
                from .services.task_manager import TaskManager
                tm = TaskManager(db)
                tm.generate_daily_checklist()
            except Exception as exc:
                app.logger.error("daily_checklist failed: %s", exc)
            # Send morning briefing after checklist is generated
            try:
                from .services.alert_service import AlertService
                alert_svc = AlertService(db)
                alert_svc.alert_morning_briefing()
            except Exception as exc:
                app.logger.error("morning_briefing failed: %s", exc)

    @scheduler.task('cron', id='daily_summary', hour=18)
    def daily_summary():
        with app.app_context():
            try:
                from .services.task_manager import TaskManager
                from .services.alert_service import AlertService
                tm = TaskManager(db)
                summary = tm.get_daily_summary()
                # Send alert with daily summary
                alert_svc = AlertService(db)
                alert_svc.alert_daily_summary(summary)
                # Mark any remaining EOD summary task as in_progress
                from .models.task import Task
                eod = db.session.query(Task).filter(
                    Task.title == "End of Day Summary",
                    Task.status == "pending",
                ).first()
                if eod:
                    eod.status = "in_progress"
                    eod.result_notes = (
                        f"Auto-summary: {summary['completed']}/{summary['total']} tasks done "
                        f"({summary['completion_pct']}%)"
                    )
                    db.session.commit()
            except Exception as exc:
                app.logger.error("daily_summary failed: %s", exc)

    @scheduler.task('cron', id='weekly_report', day_of_week='mon', hour=9)
    def weekly_report():
        with app.app_context():
            try:
                from .services.alert_service import AlertService
                alert_svc = AlertService(db)
                alert_svc.alert_weekly_report()
            except Exception as exc:
                app.logger.error("weekly_report failed: %s", exc)

    @scheduler.task('cron', id='gmail_watch_renewal', hour=3)
    def gmail_watch_renewal():
        """Renew Gmail Pub/Sub watch daily (watches expire after ~7 days)."""
        with app.app_context():
            topic = app.config.get('GOOGLE_PUBSUB_TOPIC', '')
            if not topic:
                return
            try:
                from .services.gmail_client import GmailClient
                gmail = GmailClient(db)
                result = gmail.watch(topic)
                app.logger.info("Gmail watch renewed: %s", result.get('historyId'))
            except Exception as exc:
                app.logger.warning("Gmail watch renewal failed: %s", exc)

    @scheduler.task('interval', id='imap_poll', minutes=5)
    def imap_poll():
        """Poll Gmail via IMAP for new unread messages, apply sender rules."""
        with app.app_context():
            try:
                from .services.imap_monitor import process_imap_messages
                result = process_imap_messages()
                if result.get('processed', 0) > 0:
                    app.logger.info("IMAP poll: %d processed, %d alerts, %d waiting human",
                                   result.get('processed', 0), result.get('alerts', 0),
                                   result.get('waiting_human', 0))
            except Exception as exc:
                app.logger.error("imap_poll failed: %s", exc)


def _connector_factory(marketplace_record):
    from .connectors.ebay import EbayConnector
    from .connectors.amazon import AmazonConnector
    from .connectors.kogan import KoganConnector
    from flask import current_app

    connectors = {
        'eBay': EbayConnector,
        'Amazon': AmazonConnector,
        'Kogan': KoganConnector,
    }
    cls = connectors.get(marketplace_record.name)
    if cls:
        return cls(marketplace_record, current_app.config)
    raise ValueError(f"Unknown marketplace: {marketplace_record.name}")


def _register_telegram_webhook(app):
    """Register Telegram webhook on startup if configured."""
    if not app.config.get('ALERT_TELEGRAM_ENABLED'):
        return
    with app.app_context():
        try:
            from .services.telegram_client import TelegramClient
            tg = TelegramClient()
            if tg.is_configured:
                site_url = app.config.get('SITE_URL', 'https://retromonkey.com.au')
                webhook_url = f"{site_url.rstrip('/')}/webhooks/telegram"
                result = tg.set_webhook(webhook_url)
                if result.get('ok'):
                    app.logger.info("Telegram webhook registered: %s", webhook_url)
                else:
                    app.logger.warning("Telegram webhook failed: %s", result.get('description'))
        except Exception as exc:
            app.logger.warning("Telegram webhook registration failed: %s", exc)


def _register_gmail_watch(app):
    """Register Gmail Pub/Sub watch on startup if configured."""
    if not app.config.get('GOOGLE_GMAIL_WATCH_ENABLED'):
        return
    topic = app.config.get('GOOGLE_PUBSUB_TOPIC', '')
    if not topic:
        app.logger.warning("Gmail watch enabled but GOOGLE_PUBSUB_TOPIC not set")
        return
    with app.app_context():
        try:
            from .services.gmail_client import GmailClient
            gmail = GmailClient(db)
            result = gmail.watch(topic)
            app.logger.info("Gmail watch registered: historyId=%s", result.get('historyId'))
        except Exception as exc:
            app.logger.warning("Gmail watch registration failed: %s", exc)
