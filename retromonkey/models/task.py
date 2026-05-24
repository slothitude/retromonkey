"""Task model — daily management checklist and ad-hoc tasks."""

from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from retromonkey.app import db


class Task(db.Model):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="general")
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    recurrence: Mapped[str] = mapped_column(String(16), default="none")
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    result_notes: Mapped[str | None] = mapped_column(Text)

    # category: email, business_plan, market, accounts, idea, listing, order, general
    # status: pending, in_progress, completed, skipped
    # recurrence: none, daily, weekly, monthly
    # priority: low, medium, high, critical
