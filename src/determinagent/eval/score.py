"""Per-case scoring and run-level metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .. import contracts
from ..conformance import gherkin, rulespeak

DEFECTIVE = {"needs_revision", "undetermined"}


@dataclass
class CaseScore:
    case_id: str
    task: str
    split: str
    labelled: bool
    contract_valid: bool
    routed_correctly: bool
    status: str | None
    wellformed: bool
    first_pass_wellformed: bool
    success: bool
    reasons: list[str] = field(default_factory=list)
    # RuleSpeak validation only: was the statement predicted / labelled defective?
    predicted_defective: bool | None = None
    expected_defective: bool | None = None
    latency_ms: float | None = None
    routing_latency_ms: float | None = None
    cost_usd: float | None = None


def _p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[max(0, math.ceil(0.95 * len(xs)) - 1)]


def _ratio(n: int, d: int) -> float | None:
    return n / d if d else None


@dataclass
class Report:
    system: str
    scores: list[CaseScore]

    def subset(self, *, task: str | None = None, split: str | None = None, labelled_only: bool = False) -> Report:
        keep = [
            s
            for s in self.scores
            if (task is None or s.task == task)
            and (split is None or s.split == split)
            and (not labelled_only or s.labelled)
        ]
        return Report(self.system, keep)

    def metrics(self) -> dict[str, float | int | None]:
        s = self.scores
        n = len(s)
        val = [x for x in s if x.task == "rulespeak_validation" and x.predicted_defective is not None]
        tp = sum(1 for x in val if x.predicted_defective and x.expected_defective)
        fp = sum(1 for x in val if x.predicted_defective and not x.expected_defective)
        fn = sum(1 for x in val if not x.predicted_defective and x.expected_defective)
        costs = [x.cost_usd for x in s if x.cost_usd is not None]
        return {
            "cases": n,
            "labelled": sum(x.labelled for x in s),
            "routing_accuracy": _ratio(sum(x.routed_correctly for x in s), n),
            "wellformed_final": _ratio(sum(x.wellformed for x in s), n),
            "wellformed_first_pass": _ratio(sum(x.first_pass_wellformed for x in s), n),
            "task_success": _ratio(sum(x.success for x in s), n),
            "validation_precision": _ratio(tp, tp + fp),
            "validation_recall": _ratio(tp, tp + fn),
            "violation_rate": _ratio(sum(x.status == "violated" for x in s), n),
            "cost_per_request": (sum(costs) / len(costs)) if costs else None,
            "latency_p95_ms": _p95([x.latency_ms for x in s if x.latency_ms is not None]),
            "routing_latency_p95_ms": _p95([x.routing_latency_ms for x in s if x.routing_latency_ms is not None]),
        }


def _score_generation(case: dict[str, Any], out: dict[str, Any], reasons: list[str]) -> tuple[bool, bool]:
    exp = case["expected"]
    stmts, questions = out.get("statements", []), out.get("questions", [])
    vocab = case["input"].get("vocabulary")
    wellformed = all(rulespeak.check(st["text"], vocab).passed for st in stmts)
    if not wellformed:
        reasons.append("statement fails the RuleSpeak checker")
    if exp["behavior"] == "ask":
        ok = bool(questions) and not stmts
        if not ok:
            reasons.append("expected a clarifying question")
        return ok, True
    if not stmts:
        reasons.append("expected statements, got none")
        return False, wellformed
    want = exp.get("guidance_type")
    types_ok = want is None or all(rulespeak.check(st["text"]).guidance_type == want for st in stmts)
    if not types_ok:
        reasons.append(f"expected guidance type {want}")
    if len(stmts) < len(exp.get("reference_statements", [])):
        reasons.append("fewer statements than the reference")
        return False, wellformed
    return wellformed and types_ok, wellformed


def _score_validation(case: dict[str, Any], out: dict[str, Any], reasons: list[str]) -> tuple[bool, bool, bool]:
    results = out.get("results", [])
    if len(results) != 1:
        reasons.append("expected exactly one validation result")
        return False, False, False
    form = results[0]["form"]
    ok = form == case["expected"]["form"]
    if not ok:
        reasons.append(f"form {form}, expected {case['expected']['form']}")
    return ok, True, form in DEFECTIVE


def _score_gherkin(case: dict[str, Any], out: dict[str, Any], reasons: list[str]) -> tuple[bool, bool]:
    exp = case["expected"]
    feature, questions = out.get("feature"), out.get("questions", [])
    if exp["behavior"] == "ask":
        ok = bool(questions) and not feature
        if not ok:
            reasons.append("expected a clarifying question")
        return ok, True
    if not feature:
        reasons.append("expected a feature, got none")
        return False, False
    wellformed = gherkin.check(feature).conformant
    if not wellformed:
        reasons.append("feature fails the Gherkin profile")
    n_criteria = len(case["input"]["requirement"].get("acceptance_criteria", []))
    covered = {c["criterion"] for c in out.get("covered_criteria", []) if c["scenarios"]}
    coverage_ok = covered >= set(range(n_criteria))
    if not coverage_ok:
        reasons.append("not every acceptance criterion is covered")
    return wellformed and coverage_ok, wellformed


def score_case(case: dict[str, Any], record: dict[str, Any] | None) -> CaseScore:
    labelled = case.get("label", {}).get("status") == "labelled"
    base = dict(case_id=case["id"], task=case["task"], split=case["split"], labelled=labelled)
    if record is None:
        return CaseScore(
            **base,
            contract_valid=False,
            routed_correctly=False,
            status=None,
            wellformed=False,
            first_pass_wellformed=False,
            success=False,
            reasons=["no record in run"],
            expected_defective=case["expected"].get("form") in DEFECTIVE
            if case["task"] == "rulespeak_validation"
            else None,
            predicted_defective=False if case["task"] == "rulespeak_validation" else None,
        )
    resp = record.get("response", {})
    reasons: list[str] = []
    errors = contracts.validate("response", resp)
    contract_valid = not errors
    if errors:
        reasons.append("response violates the v1 contract")
    routed = (
        contract_valid
        and resp.get("route", {}).get("target", resp.get("task")) == case["expected"]["route"]
        and resp.get("task") == case["task"]
    )
    status = resp.get("status") if contract_valid else None
    success = wellformed = False
    predicted_defective = expected_defective = None
    if case["task"] == "rulespeak_validation":
        expected_defective = case["expected"]["form"] in DEFECTIVE
        predicted_defective = False
    if contract_valid and status == "resolved" and routed:
        out = resp["output"]
        if case["task"] == "rulespeak_generation":
            success, wellformed = _score_generation(case, out, reasons)
        elif case["task"] == "rulespeak_validation":
            success, wellformed, predicted_defective = _score_validation(case, out, reasons)
        else:
            success, wellformed = _score_gherkin(case, out, reasons)
    elif contract_valid and status != "resolved":
        reasons.append(f"status {status} ({resp.get('reason_code')})")
    elif contract_valid:
        reasons.append("misrouted")
    first_pass = bool(record.get("first_pass_wellformed", wellformed)) and wellformed
    return CaseScore(
        **base,
        contract_valid=contract_valid,
        routed_correctly=routed,
        status=status,
        wellformed=wellformed,
        first_pass_wellformed=first_pass,
        success=success,
        reasons=reasons,
        predicted_defective=predicted_defective,
        expected_defective=expected_defective,
        latency_ms=record.get("latency_ms"),
        routing_latency_ms=record.get("routing_latency_ms"),
        cost_usd=record.get("cost_usd"),
    )


def score_run(cases: list[dict[str, Any]], records: list[dict[str, Any]], system: str | None = None) -> Report:
    by_id = {r["case_id"]: r for r in records}
    name = system or next((r.get("system") for r in records if r.get("system")), "unknown")
    return Report(name, [score_case(c, by_id.get(c["id"])) for c in cases])
