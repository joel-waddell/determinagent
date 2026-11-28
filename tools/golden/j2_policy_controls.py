"""Run the J2-P020 policy controls through the production grader and print the results.

    python tools/golden/j2_policy_controls.py            # print JSON
    python tools/golden/j2_policy_controls.py --check    # also exit 1 if a control has the wrong outcome

Each control is scored by ``score_run`` exactly as a model's reply would be:
the module runs in the sandbox against the case's visible and hidden tests,
then the case's ``code_must_not_match`` patterns are checked.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml

from determinagent import sandbox
from determinagent.eval import baselines, score_run

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "golden" / "v1" / "j2-pilot.yaml"
CONTROLS = ROOT / "tests" / "fixtures" / "j2_policy_controls.yaml"


def _commit() -> str | None:
    try:
        cmd = ["git", "describe", "--always", "--dirty", "--abbrev=7"]
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    except OSError:
        return None
    return out.stdout.strip() or None


def run_controls() -> dict[str, Any]:
    cases = yaml.safe_load(BATCH.read_text(encoding="utf-8"))["cases"]
    spec = yaml.safe_load(CONTROLS.read_text(encoding="utf-8"))
    case_id = spec["case"]
    oracle = baselines.oracle(cases)
    info = sandbox.info()
    results = []
    for control in spec["controls"]:
        recs = copy.deepcopy(oracle)
        rec = next(r for r in recs if r["case_id"] == case_id)
        rec["response"]["output"]["module"]["code"] = control["code"]
        s = next(x for x in score_run(cases, recs).scores if x.case_id == case_id)
        if s.success:
            outcome = "pass"
        elif s.sandbox_violations == ["policy"] and s.js_tests_passed == s.js_tests_total:
            outcome = "policy violation"
        else:
            outcome = "fail"
        results.append(
            {
                "control": control["name"],
                "expected": control["expect"],
                "outcome": outcome,
                "success": s.success,
                "tests_passed": f"{s.js_tests_passed}/{s.js_tests_total}",
                "violations": s.sandbox_violations,
                "reasons": s.reasons,
            }
        )
    return {
        "case": case_id,
        "grader": {
            "determinagent": version("determinagent"),
            "commit": _commit(),
            "scorer": "determinagent.eval.score_run",
            "js_profile": info["profile_version"],
            "node": info["node_version"],
            "network_namespace": info["network_namespace"],
        },
        "results": results,
    }


def main(argv: list[str]) -> int:
    report = run_controls()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if "--check" in argv and any(r["outcome"] != r["expected"] for r in report["results"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
