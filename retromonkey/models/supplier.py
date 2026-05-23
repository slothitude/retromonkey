from datetime import datetime, timezone
from sqlalchemy import Integer, String, Float, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from retromonkey.app import db


class Supplier(db.Model):
    __tablename__ = 'suppliers'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(String(512))
    contact_email: Mapped[str | None] = mapped_column(String(256))
    rating: Mapped[float | None] = mapped_column(Float)
    trade_assurance: Mapped[bool] = mapped_column(default=False)
    response_time_hours: Mapped[int | None] = mapped_column(Integer)
    min_order_qty: Mapped[int | None] = mapped_column(Integer)
    years_on_platform: Mapped[int | None] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    scores: Mapped[list["SupplierScore"]] = relationship("SupplierScore", backref="supplier")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship("PurchaseOrder", backref="supplier")
    rfqs: Mapped[list["RFQ"]] = relationship("RFQ", backref="supplier")


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey('suppliers.id'), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('products.id'), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='rfq_sent', index=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(Float)
    total_cost: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default='AUD')
    expected_delivery: Mapped[datetime | None] = mapped_column(DateTime)
    actual_delivery: Mapped[datetime | None] = mapped_column(DateTime)
    tracking_number: Mapped[str | None] = mapped_column(String(128))

    product: Mapped["Product"] = relationship("Product", backref="purchase_orders")


class RFQ(db.Model):
    __tablename__ = 'rfqs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey('suppliers.id'), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('products.id'), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='sent')
    specifications: Mapped[dict | None] = mapped_column(JSON)
    target_qty: Mapped[int | None] = mapped_column(Integer)
    target_price_range: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_data: Mapped[dict | None] = mapped_column(JSON)

    product: Mapped["Product"] = relationship("Product", backref="rfqs")


class SupplierScore(db.Model):
    __tablename__ = 'supplier_scores'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey('suppliers.id'), nullable=False, index=True)
    purchase_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('purchase_orders.id'))
    defect_rate: Mapped[float | None] = mapped_column(Float)
    delivery_on_time: Mapped[float | None] = mapped_column(Float)
    packaging_quality: Mapped[float | None] = mapped_column(Float)
    communication_rating: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
