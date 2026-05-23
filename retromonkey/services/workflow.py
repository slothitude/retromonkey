"""Workflow engine — event-driven trigger-action pipelines."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Parse YAML workflow templates and execute them on events."""

    def __init__(self, db_instance=None, workflows_dir: str | None = None):
        self.db = db_instance
        self.workflows: dict[str, dict] = {}
        self._action_handlers = {
            "send_email": self._action_send_email,
            "reserve_stock": self._action_reserve_stock,
            "create_po": self._action_create_po,
            "call_llm": self._action_call_llm,
            "notify": self._action_notify,
            "wait": self._action_wait,
            "condition": self._action_condition,
            "update_order_status": self._action_update_order_status,
            "adjust_price": self._action_adjust_price,
            "log_event": self._action_log_event,
        }
        if workflows_dir:
            self.load_workflows(workflows_dir)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_workflows(self, workflows_dir: str) -> dict:
        """Load all YAML workflow templates from a directory.

        Parameters
        ----------
        workflows_dir : str
            Path to directory containing ``*.yml`` workflow files.

        Returns
        -------
        dict
            Mapping of workflow name -> parsed workflow dict.
        """
        wf_dir = Path(workflows_dir)
        if not wf_dir.is_dir():
            logger.warning("Workflows directory not found: %s", workflows_dir)
            return {}

        loaded = {}
        for yml_file in sorted(wf_dir.glob("*.yml")):
            try:
                with open(yml_file, "r", encoding="utf-8") as fh:
                    wf = yaml.safe_load(fh)

                if not wf or "name" not in wf:
                    logger.warning("Skipping invalid workflow: %s", yml_file.name)
                    continue

                self.workflows[wf["name"]] = wf
                loaded[wf["name"]] = wf
                logger.info("Loaded workflow: %s", wf["name"])
            except Exception as exc:
                logger.error("Failed to load workflow %s: %s", yml_file.name, exc)

        return loaded

    def get_workflow(self, name: str) -> dict | None:
        """Return a loaded workflow by name."""
        return self.workflows.get(name)

    def list_workflows(self) -> list[dict]:
        """Return a summary list of all loaded workflows."""
        return [
            {
                "name": wf["name"],
                "trigger": wf.get("trigger", {}),
                "description": wf.get("description", ""),
                "steps": len(wf.get("actions", [])),
            }
            for wf in self.workflows.values()
        ]

    # ------------------------------------------------------------------
    # Triggering
    # ------------------------------------------------------------------

    def trigger(self, event_type: str, event_data: dict) -> list[dict]:
        """Match an event against loaded workflows and execute matching ones.

        Parameters
        ----------
        event_type : str
            The event that occurred (e.g. ``order_received``).
        event_data : dict
            Event payload data.

        Returns
        -------
        list[dict]
            Results from all executed workflows.
        """
        results = []

        for wf_name, wf in self.workflows.items():
            trigger = wf.get("trigger", {})
            if trigger.get("event") == event_type:
                logger.info("Triggering workflow '%s' for event '%s'", wf_name, event_type)
                result = self._execute_workflow(wf, event_data)
                results.append({
                    "workflow": wf_name,
                    "status": "completed",
                    "steps_executed": len(result),
                    "results": result,
                })

        if not results:
            logger.debug("No workflows matched event: %s", event_type)

        return results

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_workflow(self, workflow: dict, event_data: dict) -> list[dict]:
        """Execute a workflow's actions sequentially, passing context."""
        actions = workflow.get("actions", [])
        context = {"event": event_data, "data": dict(event_data)}
        step_results = []

        for i, action in enumerate(actions):
            action_type = action.get("type")
            handler = self._action_handlers.get(action_type)

            if not handler:
                logger.warning("Unknown action type: %s", action_type)
                step_results.append({"step": i, "type": action_type, "status": "skipped", "reason": "unknown type"})
                continue

            try:
                result = handler(action, context)
                step_results.append({"step": i, "type": action_type, "status": "success", "result": result})

                # Merge result into context for subsequent steps
                if isinstance(result, dict):
                    context["data"].update(result)

            except Exception as exc:
                logger.error("Workflow action failed (step %d, type %s): %s", i, action_type, exc)
                step_results.append({"step": i, "type": action_type, "status": "failed", "error": str(exc)})

                if action.get("continue_on_error", False):
                    continue
                break

        return step_results

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _action_send_email(self, action: dict, context: dict) -> dict:
        """Send an email via the Gmail client."""
        to = self._resolve_template(action.get("to", ""), context)
        subject = self._resolve_template(action.get("subject", ""), context)
        body = self._resolve_template(action.get("body", ""), context)

        if self.db is not None:
            try:
                from retromonkey.services.gmail_client import GmailClient
                gmail = GmailClient(self.db)
                gmail.send_email(to=to, subject=subject, body=body)
            except Exception as exc:
                logger.warning("Gmail send failed: %s", exc)
                return {"email_sent": False, "error": str(exc)}

        return {"email_sent": True, "to": to, "subject": subject}

    def _action_reserve_stock(self, action: dict, context: dict) -> dict:
        """Reserve stock for a product."""
        product_id = self._resolve_value(action.get("product_id"), context)
        qty = self._resolve_value(action.get("qty", 1), context)

        if self.db is None:
            return {"reserved": False, "reason": "no db"}

        from retromonkey.services.inventory import InventoryService
        inv_svc = InventoryService(self.db)
        success = inv_svc.reserve_stock(int(product_id), int(qty))

        return {"reserved": success, "product_id": product_id, "qty": qty}

    def _action_create_po(self, action: dict, context: dict) -> dict:
        """Create a purchase order."""
        if self.db is None:
            return {"po_created": False, "reason": "no db"}

        from retromonkey.services.reorder import ReorderService
        reorder = ReorderService(self.db)

        product_id = int(self._resolve_value(action.get("product_id"), context))
        supplier_id = int(self._resolve_value(action.get("supplier_id"), context))
        qty = int(self._resolve_value(action.get("qty", 1), context))
        unit_cost = float(self._resolve_value(action.get("unit_cost", 0), context))

        return reorder.create_reorder(product_id, supplier_id, qty, unit_cost)

    def _action_call_llm(self, action: dict, context: dict) -> dict:
        """Call the LLM router with a templated prompt."""
        from retromonkey.services.llm_router import LLMRouter

        prompt = self._resolve_template(action.get("prompt", ""), context)
        system = action.get("system", "")
        mode = action.get("mode", "auto")
        max_tokens = action.get("max_tokens", 512)

        llm = LLMRouter()
        result = llm.query(prompt, mode=mode, system=system, max_tokens=max_tokens)

        return {"text": result.get("text", ""), "mode_used": result.get("mode_used"), "cost": result.get("cost", 0)}

    def _action_notify(self, action: dict, context: dict) -> dict:
        """Log a notification message."""
        message = self._resolve_template(action.get("message", ""), context)
        level = action.get("level", "info")
        channel = action.get("channel", "log")

        getattr(logger, level, logger.info)("NOTIFY [%s]: %s", channel, message)

        return {"notified": True, "message": message, "channel": channel}

    def _action_wait(self, action: dict, context: dict) -> dict:
        """Wait for a specified number of seconds."""
        seconds = action.get("seconds", 1)
        time.sleep(seconds)
        return {"waited": seconds}

    def _action_condition(self, action: dict, context: dict) -> dict:
        """Evaluate a condition and optionally branch."""
        field = action.get("field", "")
        operator = action.get("operator", "==")
        value = action.get("value")
        then_action = action.get("then")
        else_action = action.get("else")

        actual = context.get("data", {}).get(field)

        passed = False
        if operator == "==":
            passed = str(actual) == str(value)
        elif operator == "!=":
            passed = str(actual) != str(value)
        elif operator == ">":
            passed = actual is not None and value is not None and float(actual) > float(value)
        elif operator == "<":
            passed = actual is not None and value is not None and float(actual) < float(value)
        elif operator == ">=":
            passed = actual is not None and value is not None and float(actual) >= float(value)
        elif operator == "<=":
            passed = actual is not None and value is not None and float(actual) <= float(value)
        elif operator == "in":
            passed = str(actual) in str(value)

        branch = then_action if passed else else_action
        if branch:
            branch_type = branch.get("type")
            handler = self._action_handlers.get(branch_type)
            if handler:
                return {"condition_passed": passed, "branch_result": handler(branch, context)}

        return {"condition_passed": passed}

    def _action_update_order_status(self, action: dict, context: dict) -> dict:
        """Update an order's status in the database."""
        if self.db is None:
            return {"updated": False, "reason": "no db"}

        from retromonkey.models.order import Order

        order_id = int(self._resolve_value(action.get("order_id"), context))
        status = self._resolve_template(action.get("status", ""), context)

        order = self.db.session.get(Order, order_id)
        if order:
            order.status = status
            self.db.session.commit()
            return {"updated": True, "order_id": order_id, "status": status}

        return {"updated": False, "reason": "order not found"}

    def _action_adjust_price(self, action: dict, context: dict) -> dict:
        """Adjust a listing price (placeholder for pricing engine)."""
        product_id = self._resolve_value(action.get("product_id"), context)
        adjustment = action.get("adjustment", 0)
        return {"adjusted": True, "product_id": product_id, "adjustment": adjustment}

    def _action_log_event(self, action: dict, context: dict) -> dict:
        """Log an event to the database as a message record."""
        if self.db is None:
            return {"logged": False}

        from retromonkey.models.communication import Message

        msg = Message(
            channel=action.get("channel", "system"),
            direction="outbound",
            subject=self._resolve_template(action.get("subject", ""), context),
            body=self._resolve_template(action.get("message", ""), context),
            ai_draft=False,
            approved=True,
        )
        self.db.session.add(msg)
        self.db.session.commit()
        return {"logged": True, "message_id": msg.id}

    # ------------------------------------------------------------------
    # Template helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_template(template: str, context: dict) -> str:
        """Resolve ``{{field}}`` placeholders in a template string."""
        if not template:
            return ""
        data = context.get("data", {})
        for key, val in data.items():
            placeholder = "{{" + str(key) + "}}"
            if placeholder in template:
                template = template.replace(placeholder, str(val))
        return template

    @staticmethod
    def _resolve_value(value, context: dict):
        """Resolve a value that may reference context data via dot notation."""
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            key = value[2:-2].strip()
            return context.get("data", {}).get(key, value)
        return value
