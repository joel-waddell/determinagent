"""The evaluation gate: targets for one run, and paired comparison of two runs."""

from __future__ import annotations

from math import comb
from pathlib import Path
from typing import Any

import yaml

from .score import Report

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "gate.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def gate(report: Report, config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Check each metric that has an absolute target. Returns metric -> {value, target, met}."""
    cfg = config or load_config()
    m = report.metrics()
    out: dict[str, dict[str, Any]] = {}
    for name, spec in cfg["metrics"].items():
        if "target" not in spec or m.get(name) is None:
            continue
        v, t = m[name], spec["target"]
        out[name] = {"value": v, "target": t, "met": v >= t if spec["direction"] == "higher" else v <= t}
    return out


def compare(baseline: Report, candidate: Report, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Paired comparison of a candidate against a baseline on the same cases.

    Each metric gets a verdict: pass (no regression past tolerance), review
    (a regression inside the review band, which 300 cases cannot resolve), or
    fail. Metrics with zero tolerance fail on any regression.
    """
    cfg = config or load_config()
    band = cfg.get("review_band", 0.0)
    bm, cm = baseline.metrics(), candidate.metrics()
    metrics: dict[str, Any] = {}
    for name, spec in cfg["metrics"].items():
        b, c = bm.get(name), cm.get(name)
        if b is None or c is None:
            continue
        worse = (b - c) if spec["direction"] == "higher" else (c - b)
        tol = spec.get("tolerance")
        if tol is None and "relative_tolerance" in spec:
            tol = abs(b) * spec["relative_tolerance"]
        tol = tol or 0.0
        if worse <= tol + 1e-12:
            verdict = "pass"
        elif tol == 0.0 and spec.get("tolerance") == 0.0:
            verdict = "fail"
        elif "relative_tolerance" not in spec and worse <= band:
            verdict = "review"
        else:
            verdict = "fail"
        metrics[name] = {"baseline": b, "candidate": c, "regression": worse, "tolerance": tol, "verdict": verdict}

    base_by_id = {s.case_id: s.success for s in baseline.scores}
    pairs = [(base_by_id[s.case_id], s.success) for s in candidate.scores if s.case_id in base_by_id]
    lost = sum(1 for b, c in pairs if b and not c)
    gained = sum(1 for b, c in pairs if c and not b)
    verdicts = {v["verdict"] for v in metrics.values()}
    overall = "fail" if "fail" in verdicts else "review" if "review" in verdicts else "pass"
    return {
        "baseline": baseline.system,
        "candidate": candidate.system,
        "paired_cases": len(pairs),
        "task_success_pairs": {"lost": lost, "gained": gained, "mcnemar_p": mcnemar_exact(lost, gained)},
        "metrics": metrics,
        "verdict": overall,
    }
