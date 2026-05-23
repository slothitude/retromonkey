"""Customer account routes — registration, login, logout, order history."""
import json
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from retromonkey.app import db
from retromonkey.models import Customer, Order

customers_bp = Blueprint("customers", __name__)


def customer_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("customer_id"):
            flash("Please log in to access your account.", "error")
            return redirect(url_for("customers.login"))
        return f(*args, **kwargs)
    return decorated


@customers_bp.route("/account/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()

        if not email or not password or len(password) < 8:
            flash("Email and password (8+ characters) are required.", "error")
            return render_template("customers/register.html")

        existing = db.session.query(Customer).filter(Customer.email == email).first()
        if existing:
            flash("An account with that email already exists.", "error")
            return render_template("customers/register.html")

        customer = Customer(
            email=email,
            password_hash=generate_password_hash(password),
            name=name,
        )
        db.session.add(customer)
        db.session.commit()

        session["customer_id"] = customer.id
        session["customer_email"] = customer.email
        session["customer_name"] = customer.name
        flash("Account created! Welcome to RetroMonkey.", "success")
        return redirect(url_for("customers.account"))

    return render_template("customers/register.html")


@customers_bp.route("/account/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        customer = db.session.query(Customer).filter(Customer.email == email).first()
        if customer and check_password_hash(customer.password_hash, password):
            session["customer_id"] = customer.id
            session["customer_email"] = customer.email
            session["customer_name"] = customer.name
            flash("Logged in.", "success")
            return redirect(url_for("customers.account"))

        flash("Invalid email or password.", "error")
    return render_template("customers/login.html")


@customers_bp.route("/account/logout")
def logout():
    session.pop("customer_id", None)
    session.pop("customer_email", None)
    session.pop("customer_name", None)
    flash("Logged out.", "success")
    return redirect(url_for("store.index"))


@customers_bp.route("/account")
@customer_login_required
def account():
    customer = db.session.query(Customer).get(session["customer_id"])
    orders = (
        db.session.query(Order)
        .filter(Order.buyer_email == session["customer_email"])
        .order_by(Order.ordered_at.desc())
        .all()
    )
    # Parse items for display
    parsed_orders = []
    for o in orders:
        items = json.loads(o.items_json) if o.items_json else []
        parsed_orders.append({"order": o, "items": items})

    return render_template(
        "customers/account.html",
        customer=customer,
        orders=parsed_orders,
    )


@customers_bp.route("/account/address", methods=["POST"])
@customer_login_required
def update_address():
    address = {
        "line1": request.form.get("line1", "").strip(),
        "line2": request.form.get("line2", "").strip(),
        "city": request.form.get("city", "").strip(),
        "state": request.form.get("state", "").strip(),
        "postal_code": request.form.get("postal_code", "").strip(),
        "country": "AU",
    }
    customer = db.session.query(Customer).get(session["customer_id"])
    customer.address = address
    db.session.commit()
    flash("Address updated.", "success")
    return redirect(url_for("customers.account"))
