"""Model-free systems that produce runs, for baselines and for testing the harness.

* ``oracle``: answers every case with its golden expectation (should score 100%).
* ``checker``: RuleSpeak validation answered by the deterministic checker alone.
  This is the first real baseline: what the validation task scores with no model.
"""

from __future__ import annotations

import time
from typing import Any

from ..conformance import rulespeak

TS = "2026-01-01T00:00:00Z"


def _route(task: str) -> dict[str, Any]:
    return {"tier": "lookup", "rule_id": "task-field", "config_version": "1.0.0", "target": task}


def _response(case: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "request_id": case["id"],
        "task": case["task"],
        "status": "resolved",
        "route": _route(case["task"]),
        "completed_at": TS,
        "output": output,
    }


def _trace() -> list[dict[str, Any]]:
    return [{"claim": "reference statement", "rs_refs": [], "application": "copied from the golden case"}]


def oracle(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for c in cases:
        e = c["expected"]
        if c["task"] == "rulespeak_generation":
            if e["behavior"] == "ask":
                out = {"statements": [], "questions": [{"text": "Which case is meant?"}]}
            else:
                out = {
                    "statements": [
                        {
                            "text": s,
                            "guidance_type": rulespeak.check(s).guidance_type,
                            "template_id": rulespeak.check(s).template.id,
                            "trace": _trace(),
                        }
                        for s in e["reference_statements"]
                    ],
                    "questions": [],
                }
                if e.get("vocabulary_proposals"):
                    out["vocabulary_proposals"] = list(e["vocabulary_proposals"])
        elif c["task"] == "js_generation":
            if e["behavior"] == "ask":
                out = {"questions": [{"text": "Which behavior is meant?"}]}
            else:
                out = {"module": {"code": e["reference_solution"], "filename": "reference.js"}, "questions": []}
        elif c["task"] == "rulespeak_validation":
            out = {"results": [{"statement_id": "s1", "form": e["form"], "fidelity": "unverified", "findings": []}]}
        else:
            if e["behavior"] == "ask":
                out = {"questions": [{"text": "What would count as fast?"}]}
            else:
                n = len(c["input"]["requirement"].get("acceptance_criteria", []))
                out = {
                    "feature": e["reference_feature"],
                    "covered_criteria": [{"criterion": i, "scenarios": ["reference"]} for i in range(n)],
                    "questions": [],
                }
        records.append({"case_id": c["id"], "response": _response(c, out), "system": "oracle", "attempts": 1})
    return records


def checker(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for c in cases:
        if c["task"] != "rulespeak_validation":
            continue
        t0 = time.perf_counter()
        r = rulespeak.check(c["input"]["statement"], c["input"].get("vocabulary"))
        ms = (time.perf_counter() - t0) * 1000
        d = r.to_dict()
        out = {"results": [{"statement_id": "s1", "form": r.form, "fidelity": "unverified", "findings": d["findings"]}]}
        records.append(
            {
                "case_id": c["id"],
                "response": _response(c, out),
                "system": "checker",
                "latency_ms": ms,
                "routing_latency_ms": 0.0,
                "cost_usd": 0.0,
                "attempts": 1,
                "first_pass_wellformed": True,
            }
        )
    return records
