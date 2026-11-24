"""Golden-set helpers: turn a golden case into the typed v1 request it stands for."""

from __future__ import annotations

from typing import Any

FIXED_TIME = "2026-01-01T00:00:00Z"  # golden requests are timeless; a fixed stamp keeps them deterministic


def to_request(case: dict[str, Any]) -> dict[str, Any]:
    """Build the v1 request for a golden case. Free-text inputs go in the schema's free_text fields."""
    task, inp = case["task"], case["input"]
    if task == "rulespeak_generation":
        payload: dict[str, Any] = {"intent": {"free_text": inp["intent"]}, "vocabulary": list(inp["vocabulary"])}
    elif task == "rulespeak_validation":
        payload = {"statements": [{"id": "s1", "text": inp["statement"]}]}
        if inp.get("vocabulary"):
            payload["vocabulary"] = list(inp["vocabulary"])
    elif task == "gherkin_requirements":
        payload = {"requirement": dict(inp["requirement"])}
    elif task == "js_generation":
        payload = {"spec": dict(inp["spec"])}
    else:
        raise ValueError(f"Unknown task {task!r}")
    return {
        "schema_version": "1.0",
        "request_id": case["id"],
        "task": task,
        "submitted_at": FIXED_TIME,
        "payload": payload,
    }
