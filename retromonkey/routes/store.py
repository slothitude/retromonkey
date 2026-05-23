"""Store routes — public-facing product catalog, cart, checkout, Stripe integration."""
import json
import logging
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, current_app
)
import stripe
from retromonkey.app import db
from retromonkey.models import Product, Order, OrderItem, StripeEvent, Inventory

store_bp = Blueprint("store", __name__)
log = logging.getLogger(__name__)


# ── Helpers ──

def get_cart():
    return session.get("cart", [])


def save_cart(cart):
    session["cart"] = cart
    session.modified = True


def cart_item_count():
    return sum(item["qty"] for item in get_cart())


def calculate_shipping(total_dollars):
    """Tiered domestic shipping for Australia."""
    if total_dollars >= 50:
        return 0.0
    elif total_dollars >= 30:
        return 5.99
    else:
        return 8.99


def calculate_gst(total_dollars):
    """Calculate GST component from GST-inclusive total."""
    return round(total_dollars - (total_dollars / 1.10), 2)


def send_order_confirmation(order):
    """Send order confirmation email (best effort)."""
    smtp_host = current_app.config.get('SMTP_HOST')
    if not smtp_host:
        log.info("SMTP not configured, skipping confirmation email")
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        items = json.loads(order.items_json) if isinstance(order.items_json, str) else (order.items_json or [])
        gst = calculate_gst(order.total or 0)

        item_rows = ""
        for item in items:
            item_rows += f"<tr><td>{item.get('name', '')}</td><td>x{item.get('qty', 1)}</td><td>${item.get('price', 0):.2f}</td></tr>"

        html = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
            <h1 style="color: #6c5ce7;">Order Confirmed!</h1>
            <p>Thanks for your order, {order.buyer_name or 'valued customer'}!</p>
            <h2>Order #{order.id}</h2>
            <table style="width:100%; border-collapse: collapse;">
                <tr style="background: #f0f0f0;"><th>Item</th><th>Qty</th><th>Price</th></tr>
                {item_rows}
            </table>
            <p><strong>Total (incl. GST):</strong> ${order.total:.2f}</p>
            <p><strong>GST:</strong> ${gst:.2f}</p>
            <hr>
            <p style="color: #888; font-size: 12px;">
                {current_app.config['BUSINESS_NAME']} ABN: {current_app.config['ABN']}<br>
                Prices include GST where applicable.
            </p>
        </div>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"RetroMonkey Order #{order.id} — Confirmed!"
        msg["From"] = current_app.config["SMTP_FROM"]
        msg["To"] = order.buyer_email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"]) as server:
            server.starttls()
            if current_app.config.get("SMTP_USER"):
                server.login(current_app.config["SMTP_USER"], current_app.config["SMTP_PASS"])
            server.sendmail(current_app.config["SMTP_FROM"], order.buyer_email, msg.as_string())

        log.info("Order confirmation sent to %s for order #%s", order.buyer_email, order.id)
    except Exception:
        log.exception("Failed to send order confirmation email")


@store_bp.context_processor
def inject_cart():
    return {"cart_items": cart_item_count()}


# ── Public Pages ──

@store_bp.route("/")
def index():
    products = (
        db.session.query(Product)
        .outerjoin(Inventory, Product.id == Inventory.product_id)
        .filter(db.or_(Inventory.quantity_on_hand > 0, Inventory.id.is_(None)))
        .all()
    )
    featured = [p for p in products if p.featured]
    return render_template("store/index.html", featured=featured, products=products)


@store_bp.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("store.index"))

    products = (
        db.session.query(Product)
        .filter(
            db.or_(
                Product.title.ilike(f"%{q}%"),
                Product.tagline.ilike(f"%{q}%"),
                Product.category.ilike(f"%{q}%"),
                Product.description.ilike(f"%{q}%"),
            )
        )
        .all()
    )
    return render_template("store/search.html", products=products, query=q)


@store_bp.route("/product/<slug>")
def product(slug):
    product = db.session.query(Product).filter(Product.slug == slug).first_or_404()
    return render_template("store/product.html", product=product)


# ── Cart ──

@store_bp.route("/cart")
def cart():
    cart = get_cart()
    items = []
    total = 0.0
    for ci in cart:
        p = db.session.query(Product).get(ci["id"])
        if p:
            price = p.price or 0
            line_total = price * ci["qty"]
            items.append({
                "id": p.id,
                "title": p.title,
                "slug": p.slug,
                "image": p.main_image,
                "price": price,
                "qty": ci["qty"],
                "line_total": line_total,
                "stock": p.stock,
            })
            total += line_total
    gst = calculate_gst(total) if total > 0 else 0
    shipping = calculate_shipping(total)
    return render_template("store/cart.html", items=items, total=total, gst=gst, shipping=shipping)


@store_bp.route("/cart/add", methods=["POST"])
def cart_add():
    product_id = request.form.get("product_id", type=int)
    qty = request.form.get("qty", 1, type=int)
    if not product_id:
        flash("Invalid product.", "error")
        return redirect(url_for("store.index"))

    product = db.session.query(Product).get(product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("store.index"))

    cart = get_cart()
    max_qty = product.stock or 10
    for item in cart:
        if item["id"] == product_id:
            item["qty"] = min(item["qty"] + qty, max_qty)
            save_cart(cart)
            flash(f"Updated {product.title} in cart.", "success")
            return redirect(url_for("store.cart"))

    cart.append({"id": product_id, "qty": min(qty, max_qty)})
    save_cart(cart)
    flash(f"Added {product.title} to cart.", "success")
    return redirect(url_for("store.cart"))


@store_bp.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):
    cart = get_cart()
    cart = [item for item in cart if item["id"] != product_id]
    save_cart(cart)
    flash("Item removed from cart.", "success")
    return redirect(url_for("store.cart"))


# ── Checkout ──

@store_bp.route("/checkout")
def checkout():
    cart = get_cart()
    if not cart:
        flash("Your cart is empty.", "error")
        return redirect(url_for("store.index"))

    items = []
    total = 0.0
    for ci in cart:
        p = db.session.query(Product).get(ci["id"])
        if p:
            price = p.price or 0
            line_total = price * ci["qty"]
            items.append({
                "id": p.id,
                "title": p.title,
                "price": price,
                "qty": ci["qty"],
                "line_total": line_total,
            })
            total += line_total

    shipping = calculate_shipping(total)
    gst = calculate_gst(total + shipping) if total > 0 else 0

    return render_template(
        "store/checkout.html",
        items=items,
        total=total,
        shipping=shipping,
        gst=gst,
        stripe_key=current_app.config["STRIPE_PUBLIC_KEY"],
    )


@store_bp.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    cart = get_cart()
    if not cart:
        return jsonify({"error": "Cart is empty"}), 400

    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    line_items = []
    items_json = []

    for ci in cart:
        p = db.session.query(Product).get(ci["id"])
        if not p:
            continue
        price = p.price or 0
        if price <= 0:
            continue

        # Stock validation
        if p.stock < ci["qty"]:
            return jsonify({"error": f"Not enough stock for {p.title}"}), 400

        line_items.append({
            "price_data": {
                "currency": current_app.config["CURRENCY"],
                "product_data": {"name": p.title, "description": p.tagline or ""},
                "unit_amount": int(price * 100),  # Convert dollars to cents
            },
            "quantity": ci["qty"],
        })
        items_json.append({
            "id": p.id,
            "name": p.title,
            "slug": p.slug,
            "qty": ci["qty"],
            "price": price,
        })

    # Add shipping line item
    cart_total = sum(item["price"] * item["qty"] for item in items_json)
    shipping = calculate_shipping(cart_total)
    if shipping > 0:
        line_items.append({
            "price_data": {
                "currency": current_app.config["CURRENCY"],
                "product_data": {"name": "Shipping (Australia)"},
                "unit_amount": int(shipping * 100),
            },
            "quantity": 1,
        })

    try:
        sess = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=request.host_url + "order/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.host_url + "cart",
            metadata={"items_json": json.dumps(items_json)},
        )
        return jsonify({"url": sess.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@store_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, current_app.config["STRIPE_WEBHOOK_SECRET"]
        )
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    event_id = event.get("id", "")

    # Replay protection
    existing = db.session.query(StripeEvent).get(event_id)
    if existing:
        return jsonify({"status": "ok", "note": "duplicate_event"})

    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]

        # Idempotency
        dup_order = db.session.query(Order).filter(
            Order.stripe_session_id == sess["id"]
        ).first()
        if dup_order:
            db.session.add(StripeEvent(event_id=event_id, event_type=event["type"]))
            db.session.commit()
            return jsonify({"status": "ok", "note": "duplicate"})

        items = json.loads(sess.get("metadata", {}).get("items_json", "[]"))
        total_cents = sess.get("amount_total", 0)
        total_dollars = total_cents / 100

        # Create order
        order = Order(
            stripe_session_id=sess["id"],
            stripe_payment_intent=sess.get("payment_intent", ""),
            buyer_email=sess.get("customer_details", {}).get("email", ""),
            buyer_name=sess.get("customer_details", {}).get("name", ""),
            address_json=json.dumps(sess.get("shipping", {}).get("address", {})),
            items_json=sess.get("metadata", {}).get("items_json", "[]"),
            total=total_dollars,
            gst=calculate_gst(total_dollars),
            status="paid",
            ordered_at=datetime.now(timezone.utc),
            currency="AUD",
        )
        db.session.add(order)

        # Create order items and decrement stock
        for item in items:
            product = db.session.query(Product).get(item.get("id"))
            if product:
                oi = OrderItem(
                    order=order,
                    product_id=product.id,
                    quantity=item.get("qty", 1),
                    unit_price=item.get("price", 0),
                    subtotal=item.get("price", 0) * item.get("qty", 1),
                )
                db.session.add(oi)

                # Decrement stock
                if product.inventory:
                    product.inventory.quantity_on_hand = max(
                        0, product.inventory.quantity_on_hand - item.get("qty", 1)
                    )

        # Record event
        db.session.add(StripeEvent(event_id=event_id, event_type=event["type"]))
        db.session.commit()

        # Send confirmation email (best effort)
        send_order_confirmation(order)

    return jsonify({"status": "ok"})


@store_bp.route("/order/success")
def order_success():
    session_id = request.args.get("session_id", "")
    return render_template("store/order_success.html", session_id=session_id)


# ── Order Tracking ──

@store_bp.route("/track", methods=["GET", "POST"])
def track_order():
    orders = []
    query = ""
    if request.method == "POST":
        query = request.form.get("query", "").strip()
    else:
        query = request.args.get("query", "").strip()

    if query:
        try:
            order_id = int(query)
            order = db.session.query(Order).get(order_id)
            if order:
                orders = [order]
        except ValueError:
            orders = (
                db.session.query(Order)
                .filter(
                    db.or_(
                        Order.buyer_email == query,
                        Order.stripe_session_id == query,
                    )
                )
                .order_by(Order.ordered_at.desc())
                .all()
            )

    # Parse items for display
    parsed = []
    for o in orders:
        items = json.loads(o.items_json) if o.items_json else []
        parsed.append({"order": o, "order_items": items})

    return render_template("store/track.html", results=parsed, query=query)


# ── Newsletter ──

@store_bp.route("/newsletter", methods=["POST"])
def newsletter_signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "Please enter a valid email address."}), 400
    # Best-effort — could store in a newsletter table
    log.info("Newsletter signup: %s", email)
    return jsonify({"message": "Thanks for subscribing!"}), 200


# ── Legal Pages ──

@store_bp.route("/privacy")
def privacy():
    return render_template("store/privacy.html")


@store_bp.route("/terms")
def terms():
    return render_template("store/terms.html")


# ── Health / SEO ──

@store_bp.route("/health")
def health_check():
    try:
        db.session.execute(db.text("SELECT 1")).scalar()
        return jsonify({"status": "healthy", "db": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "db": "error", "error": str(e)}), 503


@store_bp.route("/robots.txt")
def robots_txt():
    base = current_app.config["SITE_URL"].rstrip("/")
    return f"""User-agent: *
Allow: /
Disallow: /admin/
Disallow: /cart/
Disallow: /checkout
Disallow: /webhook

Sitemap: {base}/sitemap.xml
""", 200, {"Content-Type": "text/plain"}


@store_bp.route("/sitemap.xml")
def sitemap_xml():
    products = db.session.query(Product).all()
    base = current_app.config["SITE_URL"].rstrip("/")

    urls = [
        f"<url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"<url><loc>{base}/privacy</loc><changefreq>monthly</changefreq></url>",
        f"<url><loc>{base}/terms</loc><changefreq>monthly</changefreq></url>",
        f"<url><loc>{base}/track</loc><changefreq>yearly</changefreq></url>",
    ]
    for p in products:
        if p.slug:
            urls.append(
                f'<url><loc>{base}/product/{p.slug}</loc>'
                f'<changefreq>weekly</changefreq><priority>0.8</priority></url>'
            )

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>")
    return xml, 200, {"Content-Type": "application/xml"}
