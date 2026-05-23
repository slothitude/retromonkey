from datetime import datetime, timezone
from sqlalchemy import Integer, String, Float, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from retromonkey.app import db


class Order(db.Model):
    __tablename__ = 'orders'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    marketplace_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('marketplaces.id'), nullable=True)
    external_order_id: Mapped[str | None] = mapped_column(String(128), index=True)
    buyer_name: Mapped[str | None] = mapped_column(String(128))
    buyer_email: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    total: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default='AUD')
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Web store (Stripe) fields
    stripe_session_id: Mapped[str | None] = mapped_column(String(256), index=True)
    stripe_payment_intent: Mapped[str | None] = mapped_column(String(256))
    address_json: Mapped[str | None] = mapped_column(Text)
    items_json: Mapped[str | None] = mapped_column(Text)
    gst: Mapped[float | None] = mapped_column(Float)     # GST component
    tracking: Mapped[str | None] = mapped_column(String(128))

    items: Mapped[list["OrderItem"]] = relationship("OrderItem", backref="order")
    shipments: Mapped[list["Shipment"]] = relationship("Shipment", backref="order")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", backref="order")


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey('orders.id'), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('products.id'), nullable=False)
    listing_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('listings.id'))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, nullable=False)


class Shipment(db.Model):
    __tablename__ = 'shipments'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey('orders.id'), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(64))
    tracking_number: Mapped[str | None] = mapped_column(String(128))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    label_url: Mapped[str | None] = mapped_column(String(512))
