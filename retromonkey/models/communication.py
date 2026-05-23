from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from retromonkey.app import db


class Message(db.Model):
    __tablename__ = 'messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    marketplace_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('marketplaces.id'))
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    from_addr: Mapped[str | None] = mapped_column(String(256))
    to_addr: Mapped[str | None] = mapped_column(String(256))
    subject: Mapped[str | None] = mapped_column(String(256))
    body: Mapped[str | None] = mapped_column(Text)
    related_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('orders.id'))
    related_product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('products.id'))
    ai_draft: Mapped[bool] = mapped_column(default=False)
    approved: Mapped[bool] = mapped_column(default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
