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
            for mp in Marketplace.query.filter_by(active=True).all():
                if mp.name == 'eBay':
                    try:
                        conn = EbayConnector(mp, app.config)
                        if conn.is_authenticated():
                            conn.get_orders()
                    except Exception:
                        pass

    @scheduler.task('interval', id='sync_inventory', minutes=30)
    def sync_inventory():
        with app.app_context():
            try:
                from .services.sync import InventorySyncService
                sync_svc = InventorySyncService(db, _connector_factory)
                sync_svc.sync_all()
            except Exception:
                pass

    @scheduler.task('cron', id='reorder_check', hour=7)
    def reorder_check():
        with app.app_context():
            try:
                from .services.inventory import InventoryService
                inv = InventoryService(db)
                inv.check_reorder_needed()
            except Exception:
                pass

    @scheduler.task('cron', id='daily_checklist', hour=8, minute=30)
    def daily_checklist():
        with app.app_context():
            try:
                from .services.task_manager import TaskManager
                tm = TaskManager(db)
                tm.generate_daily_checklist()
            except Exception:
                pass

    @scheduler.task('cron', id='daily_summary', hour=18)
    def daily_summary():
        with app.app_context():
            try:
                from .services.task_manager import TaskManager
                tm = TaskManager(db)
                summary = tm.get_daily_summary()
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
            except Exception:
                pass


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
