import json
from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from retromonkey.app import db


class Customer(db.Model):
    __tablename__ = 'customers'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    address_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    @property
    def address(self):
        if self.address_json:
            try:
                return json.loads(self.address_json)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    @address.setter
    def address(self, value):
        self.address_json = json.dumps(value) if value else None
