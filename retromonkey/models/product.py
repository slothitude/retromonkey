import re
from datetime import datetime, timezone
from sqlalchemy import Boolean, Integer, String, Text, Float, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from retromonkey.app import db


class Product(db.Model):
    __tablename__ = 'products'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    tagline: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128))
    condition: Mapped[str | None] = mapped_column(String(32))
    images: Mapped[dict | None] = mapped_column(JSON)
    specs: Mapped[dict | None] = mapped_column(JSON)
    cost_price: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)          # Selling price (AUD)
    compare_price: Mapped[float | None] = mapped_column(Float)  # RRP / original price
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    badge: Mapped[str | None] = mapped_column(String(64))
    supplier_url: Mapped[str | None] = mapped_column(String(512))  # Direct supplier link for dropship
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    inventory: Mapped["Inventory"] = relationship("Inventory", backref="product", uselist=False)
    listings: Mapped[list["Listing"]] = relationship("Listing", backref="product")
    order_items: Mapped[list["OrderItem"]] = relationship("OrderItem", backref="product")

    @property
    def main_image(self):
        """Get the primary product image URL."""
        if self.images:
            if isinstance(self.images, list) and self.images:
                return self.images[0]
            if isinstance(self.images, dict):
                return self.images.get('main', self.images.get('url', ''))
            if isinstance(self.images, str):
                # Comma-separated URLs
                return self.images.split(',')[0].strip()
        return None

    @property
    def image_list(self):
        """Get all product image URLs as a list."""
        if not self.images:
            return []
        if isinstance(self.images, list):
            return self.images
        if isinstance(self.images, dict):
            return list(self.images.values())
        if isinstance(self.images, str):
            return [url.strip() for url in self.images.split(',') if url.strip()]
        return []

    @property
    def stock(self):
        """Get current stock level from inventory."""
        if self.inventory:
            return self.inventory.quantity_on_hand
        return 0

    def generate_slug(self):
        """Generate URL-safe slug from title."""
        if self.slug:
            return self.slug
        slug = re.sub(r'[^\w\s-]', '', self.title.lower())
        slug = re.sub(r'[\s_]+', '-', slug).strip('-')
        self.slug = slug
        return slug
