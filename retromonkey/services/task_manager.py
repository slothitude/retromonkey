"""Task Manager — daily checklist generation and task lifecycle."""

from datetime import datetime, timedelta, timezone, date

from retromonkey.app import db
from retromonkey.models.task import Task


# ---------------------------------------------------------------------------
# Daily checklist template
# ---------------------------------------------------------------------------
DAILY_CHECKLIST = [
    {"title": "Check Gmail", "category": "email", "priority": "high",
     "description": "Poll inbox, process by sender rules, flag anything needing action."},
    {"title": "Check eBay Orders", "category": "order", "priority": "high",
     "description": "Pull new orders, flag shipments needed, update statuses."},
    {"title": "Store Health Check", "category": "general", "priority": "medium",
     "description": "Hit /health endpoint, verify site is up and responsive."},
    {"title": "Review Business Plan", "category": "business_plan", "priority": "medium",
     "description": "Compare units sold vs plan targets, track progress."},
    {"title": "Check Inventory", "category": "listing", "priority": "medium",
     "description": "Flag low stock, items needing reorder, sync issues."},
    {"title": "Competitor Price Check", "category": "market", "priority": "low",
     "description": "Search eBay AU for our 5 products, compare prices and positioning."},
    {"title": "Check Accounts", "category": "accounts", "priority": "medium",
     "description": "Today's revenue, fees, profit running total."},
    {"title": "Brainstorm One Idea", "category": "idea", "priority": "low",
     "description": "Generate one actionable idea (rotates focus by day of week)."},
    {"title": "End of Day Summary", "category": "general", "priority": "medium",
     "description": "Aggregate day's activity, flag decisions needed for tomorrow."},
]


# Idea focus rotates by day of week
IDEA_FOCUS = {
    0: "New product sourcing — find one product idea worth researching",
    1: "Listing optimization — improve one existing listing's title or description",
    2: "Marketing — one promotional idea (social, email, bundle deal)",
    3: "Operations — one process improvement or automation opportunity",
    4: "Customer experience — one way to improve buyer satisfaction",
    5: "Expansion — one new marketplace or sales channel idea",
    6: "Strategy — one long-term business growth idea",
}


class TaskManager:
    """Business logic for task lifecycle and daily checklist management."""

    def __init__(self, database=None):
        self.db = database or db

    # ------------------------------------------------------------------
    # Daily checklist
    # ------------------------------------------------------------------
    def generate_daily_checklist(self) -> list[Task]:
        """Create today's routine tasks if they don't already exist."""
        today = date.today()
        existing = (
            self.db.session.query(Task)
            .filter(self.db.func.date(Task.created_at) == today)
            .filter(Task.recurrence == "daily")
            .count()
        )
        if existing > 0:
            return self.get_todays_tasks()

        tasks = []
        today_dt = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        weekday = today.weekday()

        for template in DAILY_CHECKLIST:
            desc = template["description"]
            # Rotate brainstorm description by day
            if template["category"] == "idea":
                desc = f"{IDEA_FOCUS.get(weekday, 'General improvement')}. {desc}"

            task = Task(
                title=template["title"],
                description=desc,
                category=template["category"],
                priority=template["priority"],
                status="pending",
                recurrence="daily",
                due_at=today_dt + timedelta(hours=18),  # due by 6pm
            )
            self.db.session.add(task)
            tasks.append(task)

        self.db.session.commit()
        return tasks

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------
    def complete_task(self, task_id: int, notes: str | None = None) -> Task:
        task = self.db.session.get(Task, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
        task.result_notes = notes
        self.db.session.commit()
        return task

    def update_task(self, task_id: int, **kwargs) -> Task:
        task = self.db.session.get(Task, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        for key, value in kwargs.items():
            if hasattr(task, key) and value is not None:
                setattr(task, key, value)
        self.db.session.commit()
        return task

    def create_task(self, title: str, **kwargs) -> Task:
        task = Task(title=title, **kwargs)
        self.db.session.add(task)
        self.db.session.commit()
        return task

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_todays_tasks(self) -> list[Task]:
        today = date.today()
        return (
            self.db.session.query(Task)
            .filter(self.db.func.date(Task.created_at) == today)
            .order_by(
                self.db.case(
                    {"high": 0, "critical": 0, "medium": 1, "low": 2},
                    value=Task.priority,
                ),
                Task.created_at,
            )
            .all()
        )

    def get_overdue_tasks(self) -> list[Task]:
        now = datetime.now(timezone.utc)
        return (
            self.db.session.query(Task)
            .filter(Task.due_at < now)
            .filter(Task.status.in_(["pending", "in_progress"]))
            .order_by(Task.due_at)
            .all()
        )

    def get_tasks(self, status: str | None = None, category: str | None = None,
                  days: int | None = None) -> list[Task]:
        q = self.db.session.query(Task)
        if status:
            q = q.filter(Task.status == status)
        if category:
            q = q.filter(Task.category == category)
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            q = q.filter(Task.created_at >= cutoff)
        return q.order_by(Task.created_at.desc()).all()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def get_daily_summary(self) -> dict:
        tasks = self.get_todays_tasks()
        completed = [t for t in tasks if t.status == "completed"]
        pending = [t for t in tasks if t.status == "pending"]
        in_progress = [t for t in tasks if t.status == "in_progress"]
        overdue = self.get_overdue_tasks()

        return {
            "date": date.today().isoformat(),
            "total": len(tasks),
            "completed": len(completed),
            "pending": len(pending),
            "in_progress": len(in_progress),
            "overdue": len(overdue),
            "completion_pct": round(len(completed) / len(tasks) * 100) if tasks else 0,
            "tasks": tasks,
            "categories": {
                cat: {"done": sum(1 for t in tasks_by_cat if t.status == "completed"),
                      "total": len(tasks_by_cat)}
                for cat in set(t.category for t in tasks)
                for tasks_by_cat in [[t for t in tasks if t.category == cat]]
            },
        }

    def get_business_plan_progress(self) -> dict:
        """Compare actual sales against business plan targets."""
        from retromonkey.models import Order, OrderItem

        today = date.today()
        month_start = today.replace(day=1)
        month_start_dt = datetime.combine(month_start, datetime.min.time()).replace(tzinfo=timezone.utc)

        # This month's stats
        month_orders = (
            self.db.session.query(Order)
            .filter(Order.ordered_at >= month_start_dt)
            .all()
        )
        month_revenue = sum(o.total or 0 for o in month_orders)
        month_units = sum(
            item.quantity
            for o in month_orders
            for item in (o.items or [])
        )

        # All-time stats
        all_orders = self.db.session.query(Order).all()
        all_revenue = sum(o.total or 0 for o in all_orders)
        all_units = sum(
            item.quantity
            for o in all_orders
            for item in (o.items or [])
        )

        return {
            "this_month": {
                "orders": len(month_orders),
                "revenue": round(month_revenue, 2),
                "units_sold": month_units,
            },
            "all_time": {
                "orders": len(all_orders),
                "revenue": round(all_revenue, 2),
                "units_sold": all_units,
            },
        }
