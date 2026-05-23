from datetime import datetime, timezone
from sqlalchemy import Integer, String, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from retromonkey.app import db


class Marketplace(db.Model):
    __tablename__ = 'marketplaces'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    credentials: Mapped[dict | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    settings: Mapped[dict | None] = mapped_column(JSON)

    listings: Mapped[list["Listing"]] = relationship("Listing", backref="marketplace")
    orders: Mapped[list["Order"]] = relationship("Order", backref="marketplace")
    fees: Mapped[list["Fee"]] = relationship("Fee", backref="marketplace")


class Listing(db.Model):
    __tablename__ = 'listings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('products.id'), nullable=False, index=True)
    marketplace_id: Mapped[int] = mapped_column(Integer, ForeignKey('marketplaces.id'), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(256))
    price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default='draft')
    listed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
