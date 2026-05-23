"""Page routes — serves all HTML views for the RetroMonkey dashboard."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request

from retromonkey.app import db
from retromonkey.models import (
    Product,
    Inventory,
    Marketplace,
    Listing,
    Order,
    OrderItem,
    Shipment,
    Transaction,
    Fee,
    Supplier,
    PurchaseOrder,
    RFQ,
    SupplierScore,
    Message,
)

pages_bp = Blueprint("pages", __name__)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@pages_bp.route("/")
def dashboard():
    today = datetime.now(timezone.utc).date()
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

    # Active listings
    active_listings = db.session.query(Listing).filter(
        Listing.status.in_(["active", "live", "listed"])
    ).count()

    # Orders today
    orders_today = db.session.query(Order).filter(
        Order.ordered_at >= today_start
    ).count()

    # Revenue today
    revenue_row = db.session.query(
        db.func.coalesce(db.func.sum(Order.total), 0)
    ).filter(Order.ordered_at >= today_start).first()
    revenue_today = float(revenue_row[0]) if revenue_row else 0.0

    # Pending shipments
    pending_shipments = db.session.query(Order).filter(
        Order.status == "pending"
    ).count()

    # Low stock alerts
    low_stock = db.session.query(Inventory).filter(
        Inventory.quantity_on_hand <= Inventory.reorder_threshold
    ).count()

    # Total counts
    total_products = db.session.query(Product).count()
    total_orders = db.session.query(Order).count()

    # Marketplace connections
    marketplaces = db.session.query(Marketplace).filter(Marketplace.active == True).all()
    ebay_connected = any(mp.name == "eBay" and mp.credentials for mp in marketplaces)
    amazon_connected = any(mp.name == "Amazon" and mp.credentials for mp in marketplaces)

    # Recent orders (last 10)
    recent_orders = (
        db.session.query(Order)
        .options(db.joinedload(Order.items), db.joinedload(Order.marketplace))
        .order_by(Order.ordered_at.desc())
        .limit(10)
        .all()
    )

    # Revenue chart data (last 30 days)
    thirty_days_ago = today_start - timedelta(days=30)
    chart_rows = (
        db.session.query(
            db.func.date(Order.ordered_at).label("date"),
            db.func.coalesce(db.func.sum(Order.total), 0).label("amount"),
        )
        .filter(Order.ordered_at >= thirty_days_ago)
        .group_by(db.func.date(Order.ordered_at))
        .order_by(db.func.date(Order.ordered_at))
        .all()
    )
    chart_data = [{"date": str(r.date), "amount": float(r.amount)} for r in chart_rows]

    stats = {
        "date_label": today.strftime("%A, %B %d"),
        "active_listings": active_listings,
        "orders_today": orders_today,
        "revenue_today": f"{revenue_today:.2f}",
        "pending_shipments": pending_shipments,
        "low_stock": low_stock,
        "total_products": total_products,
        "total_orders": total_orders,
        "ebay_connected": ebay_connected,
        "amazon_connected": amazon_connected,
        "llm_mode": "auto",
        "last_sync": "15 min ago",
    }

    return render_template(
        "dashboard.html",
        page="dashboard",
        stats=stats,
        recent_orders=recent_orders,
        chart_data=chart_data,
    )


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@pages_bp.route("/products")
def product_list():
    query = request.args.get("q", "")
    category = request.args.get("category", "")
    status_filter = request.args.get("status", "")

    q = db.session.query(Product).options(db.joinedload(Product.inventory))

    if query:
        q = q.filter(
            db.or_(
                Product.title.ilike(f"%{query}%"),
                Product.sku.ilike(f"%{query}%"),
            )
        )
    if category:
        q = q.filter(Product.category == category)

    products = q.order_by(Product.created_at.desc()).all()

    # Extract unique categories
    categories = [
        row[0]
        for row in db.session.query(Product.category)
        .distinct()
        .filter(Product.category.isnot(None))
        .all()
    ]

    return render_template(
        "products.html",
        page="products",
        products=products,
        categories=categories,
    )


@pages_bp.route("/products/<int:product_id>")
def product_detail(product_id):
    product = (
        db.session.query(Product)
        .options(
            db.joinedload(Product.inventory),
            db.joinedload(Product.listings).joinedload(Listing.marketplace),
            db.joinedload(Product.order_items).joinedload(OrderItem.order),
        )
        .get_or_404(product_id)
    )
    return render_template(
        "product_detail.html",
        page="products",
        product=product,
    )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@pages_bp.route("/orders")
def order_list():
    status_filter = request.args.get("status", "")
    marketplace_filter = request.args.get("marketplace", "")

    q = db.session.query(Order).options(
        db.joinedload(Order.items), db.joinedload(Order.marketplace)
    )

    if status_filter:
        q = q.filter(Order.status == status_filter)
    if marketplace_filter:
        q = q.filter(Order.marketplace_id == int(marketplace_filter))

    orders = q.order_by(Order.ordered_at.desc()).all()
    marketplaces = db.session.query(Marketplace).all()

    return render_template(
        "orders.html",
        page="orders",
        orders=orders,
        marketplaces=marketplaces,
    )


@pages_bp.route("/orders/<int:order_id>")
def order_detail(order_id):
    order = (
        db.session.query(Order)
        .options(
            db.joinedload(Order.items).joinedload(OrderItem.product),
            db.joinedload(Order.shipments),
            db.joinedload(Order.transactions),
            db.joinedload(Order.marketplace),
        )
        .get_or_404(order_id)
    )

    # Calculate COGS
    cogs = 0.0
    for item in order.items:
        if item.product and item.product.cost_price:
            cogs += item.product.cost_price * item.quantity

    # Total fees
    total_fees = sum(
        t.amount for t in order.transactions if t.type == "fee"
    )

    # Profit
    revenue = order.total or 0
    profit = revenue - cogs - total_fees

    return render_template(
        "order_detail.html",
        page="orders",
        order=order,
        cogs=cogs,
        profit=profit,
    )


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------
@pages_bp.route("/listings")
def listings():
    marketplace_filter = request.args.get("marketplace", "")
    status_filter = request.args.get("status", "")

    q = db.session.query(Listing).options(
        db.joinedload(Listing.product), db.joinedload(Listing.marketplace)
    )

    if marketplace_filter:
        q = q.filter(Listing.marketplace_id == int(marketplace_filter))
    if status_filter:
        q = q.filter(Listing.status == status_filter)

    listings = q.order_by(Listing.updated_at.desc()).all()
    marketplaces = db.session.query(Marketplace).all()

    return render_template(
        "listings.html",
        page="listings",
        listings=listings,
        marketplaces=marketplaces,
    )


# ---------------------------------------------------------------------------
# Sourcing
# ---------------------------------------------------------------------------
@pages_bp.route("/sourcing")
def sourcing():
    suppliers = db.session.query(Supplier).all()
    rfqs = (
        db.session.query(RFQ)
        .options(db.joinedload(RFQ.supplier), db.joinedload(RFQ.product))
        .order_by(RFQ.sent_at.desc())
        .all()
    )
    purchase_orders = (
        db.session.query(PurchaseOrder)
        .options(db.joinedload(PurchaseOrder.supplier), db.joinedload(PurchaseOrder.product))
        .order_by(PurchaseOrder.id.desc())
        .all()
    )
    supplier_scores = (
        db.session.query(SupplierScore)
        .options(db.joinedload(SupplierScore.supplier))
        .all()
    )

    return render_template(
        "sourcing.html",
        page="sourcing",
        suppliers=suppliers,
        rfqs=rfqs,
        purchase_orders=purchase_orders,
        supplier_scores=supplier_scores,
    )


# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------
@pages_bp.route("/finance")
def finance():
    period = request.args.get("period", "30d")

    # Determine date range
    now = datetime.now(timezone.utc)
    if period == "7d":
        start = now - timedelta(days=7)
    elif period == "30d":
        start = now - timedelta(days=30)
    elif period == "90d":
        start = now - timedelta(days=90)
    else:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    # Revenue & profit
    revenue = float(
        db.session.query(db.func.coalesce(db.func.sum(Order.total), 0))
        .filter(Order.ordered_at >= start)
        .scalar()
    )

    total_fees = float(
        db.session.query(db.func.coalesce(db.func.sum(Fee.amount), 0))
        .filter(Fee.order.has(Order.ordered_at >= start))
        .scalar()
    )

    # COGS
    cogs_result = (
        db.session.query(
            db.func.coalesce(
                db.func.sum(OrderItem.quantity * db.func.coalesce(Product.cost_price, 0)),
                0,
            )
        )
        .join(Product, OrderItem.product_id == Product.id)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.ordered_at >= start)
        .scalar()
    )
    cogs = float(cogs_result)

    profit = revenue - cogs - total_fees
    margin = (profit / revenue * 100) if revenue > 0 else 0

    # Revenue chart data
    chart_rows = (
        db.session.query(
            db.func.date(Order.ordered_at).label("date"),
            db.func.coalesce(db.func.sum(Order.total), 0).label("revenue"),
        )
        .filter(Order.ordered_at >= start)
        .group_by(db.func.date(Order.ordered_at))
        .order_by(db.func.date(Order.ordered_at))
        .all()
    )
    # Build profit chart data alongside revenue
    revenue_chart_data = [{"date": str(r.date), "revenue": float(r.revenue), "profit": 0} for r in chart_rows]

    # Fee breakdown
    fee_rows = (
        db.session.query(
            Fee.fee_type,
            db.func.coalesce(db.func.sum(Fee.amount), 0).label("amount"),
        )
        .filter(Fee.order.has(Order.ordered_at >= start))
        .group_by(Fee.fee_type)
        .all()
    )
    fee_breakdown = [{"type": r.fee_type, "amount": float(r.amount)} for r in fee_rows]

    # Top products by profit
    top_rows = (
        db.session.query(
            OrderItem.product_id,
            Product.title,
            db.func.sum(OrderItem.quantity).label("sold"),
            db.func.sum(OrderItem.subtotal).label("revenue"),
            db.func.sum(OrderItem.quantity * db.func.coalesce(Product.cost_price, 0)).label("cost"),
        )
        .join(Product, OrderItem.product_id == Product.id)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.ordered_at >= start)
        .group_by(OrderItem.product_id, Product.title)
        .order_by(db.text("revenue DESC"))
        .limit(20)
        .all()
    )
    top_products = []
    for r in top_rows:
        sold = int(r.sold)
        rev = float(r.revenue)
        cost = float(r.cost)
        fees = total_fees * (rev / revenue) if revenue > 0 else 0
        p = rev - cost - fees
        top_products.append({
            "product_id": r.product_id,
            "title": r.title,
            "sold": sold,
            "revenue": rev,
            "cost": cost,
            "fees": fees,
            "profit": p,
            "margin": (p / rev * 100) if rev > 0 else 0,
        })
    top_products.sort(key=lambda x: x["profit"], reverse=True)

    stats = {
        "revenue": revenue,
        "profit": profit,
        "margin": margin,
        "total_fees": total_fees,
    }

    return render_template(
        "finance.html",
        page="finance",
        period=period,
        stats=stats,
        revenue_chart_data=revenue_chart_data,
        fee_breakdown=fee_breakdown,
        top_products=top_products,
    )


# ---------------------------------------------------------------------------
# Communications / Inbox
# ---------------------------------------------------------------------------
@pages_bp.route("/inbox")
def inbox():
    message_id = request.args.get("message", type=int)

    messages = (
        db.session.query(Message)
        .order_by(Message.created_at.desc())
        .limit(50)
        .all()
    )

    selected_message = None
    if message_id:
        selected_message = db.session.query(Message).get(message_id)
    elif messages:
        selected_message = messages[0]

    return render_template(
        "communications.html",
        page="inbox",
        messages=messages,
        selected_message=selected_message,
        selected_message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@pages_bp.route("/settings")
def settings():
    marketplaces = db.session.query(Marketplace).all()
    ebay_connected = any(mp.name == "eBay" and mp.credentials for mp in marketplaces)
    amazon_connected = any(mp.name == "Amazon" and mp.credentials for mp in marketplaces)

    products_with_inventory = (
        db.session.query(Product)
        .options(db.joinedload(Product.inventory))
        .join(Inventory, Product.id == Inventory.product_id)
        .all()
    )

    return render_template(
        "settings.html",
        page="settings",
        ebay_connected=ebay_connected,
        amazon_connected=amazon_connected,
        products_with_inventory=products_with_inventory,
        llm_mode="auto",
        claude_api_key="",
        ollama_endpoint="http://localhost:11434",
        ollama_model="qwen3",
        ebay_env="Sandbox",
        amazon_region="Australia",
    )
