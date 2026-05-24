"""Task API routes — daily management checklist and ad-hoc tasks."""

from flask import Blueprint, request, jsonify

from retromonkey.app import db
from retromonkey.models.task import Task
from retromonkey.services.task_manager import TaskManager

tasks_bp = Blueprint("tasks", __name__)
_tm = TaskManager(db)


@tasks_bp.route("", methods=["GET"])
def list_tasks():
    """List tasks with optional filters."""
    status = request.args.get("status")
    category = request.args.get("category")
    days = request.args.get("days", type=int)
    tasks = _tm.get_tasks(status=status, category=category, days=days)
    return jsonify([
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "category": t.category,
            "priority": t.priority,
            "status": t.status,
            "recurrence": t.recurrence,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "result_notes": t.result_notes,
        }
        for t in tasks
    ])


@tasks_bp.route("", methods=["POST"])
def create_task():
    """Create an ad-hoc task."""
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"error": "title is required"}), 400
    task = _tm.create_task(
        title=data["title"],
        description=data.get("description"),
        category=data.get("category", "general"),
        priority=data.get("priority", "medium"),
        recurrence=data.get("recurrence", "none"),
    )
    return jsonify({"id": task.id, "title": task.title, "status": task.status}), 201


@tasks_bp.route("/<int:task_id>", methods=["GET"])
def get_task(task_id):
    """Get task detail."""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "category": task.category,
        "priority": task.priority,
        "status": task.status,
        "recurrence": task.recurrence,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "result_notes": task.result_notes,
    })


@tasks_bp.route("/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    """Update a task."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400
    try:
        task = _tm.update_task(task_id, **data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"id": task.id, "status": task.status})


@tasks_bp.route("/<int:task_id>/complete", methods=["POST"])
def complete_task(task_id):
    """Complete a task with result notes."""
    data = request.get_json() or {}
    try:
        task = _tm.complete_task(task_id, notes=data.get("notes"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({
        "id": task.id,
        "status": task.status,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "result_notes": task.result_notes,
    })


@tasks_bp.route("/daily", methods=["GET"])
def daily_checklist():
    """Get or generate today's checklist."""
    tasks = _tm.generate_daily_checklist()
    return jsonify([
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "category": t.category,
            "priority": t.priority,
            "status": t.status,
            "due_at": t.due_at.isoformat() if t.due_at else None,
        }
        for t in tasks
    ])


@tasks_bp.route("/summary", methods=["GET"])
def daily_summary():
    """Today's summary — completed, pending, overdue counts."""
    summary = _tm.get_daily_summary()
    # Replace task objects with counts (tasks aren't JSON-serializable)
    return jsonify({
        "date": summary["date"],
        "total": summary["total"],
        "completed": summary["completed"],
        "pending": summary["pending"],
        "in_progress": summary["in_progress"],
        "overdue": summary["overdue"],
        "completion_pct": summary["completion_pct"],
        "categories": summary["categories"],
    })
