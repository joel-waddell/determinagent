"""Verify J2 golden cases in the sandbox, and snapshot their mutation scores.

    python tools/golden/j2_verify.py golden/v1/j2-pilot.yaml            # check and report
    python tools/golden/j2_verify.py golden/v1/j2-pilot.yaml --write    # also update expected.mutation

For every case that expects a module:

1. The reference solution is linted and run against the visible examples and
   the hidden tests. It must be accepted with no findings at all.
2. Every single-token mutant of the reference (one operator, boolean or number
   changed) is run against the same tests. A mutant the tests still accept
   survives. The mutation score is killed / mutants.

Survivors are listed for review. Some are equivalent to the reference (for
example changing ``>`` to ``>=`` where the two never differ). A reviewed
equivalent goes in the case's ``expected.equivalent_mutants`` and is left out
of the score. Cases below MIN_SCORE fail the check, and so does a listed
equivalent that no longer survives (the list has gone stale).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from determinagent import contracts, sandbox  # noqa: E402
from determinagent.eval.score import js_tests  # noqa: E402
from determinagent.golden import to_request  # noqa: E402

MIN_SCORE = 0.8


def write_snapshots(path: Path, snaps: dict[str, dict[str, Any]]) -> None:
    """Put each case's snapshot on one ``mutation:`` line, before its draft_note.

    Edits the text in place, so the hand-written layout of the batch is kept.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    current = None
    for line in lines:
        if line.startswith("- id: "):
            current = line[len("- id: ") :].strip()
        if current in snaps and line.startswith("    mutation: "):
            continue
        if current in snaps and line.startswith("  draft_note:"):
            out.append(f"    mutation: {json.dumps(snaps[current], ensure_ascii=False)}\n")
        out.append(line)
    path.write_text("".join(out), encoding="utf-8")


def verify_case(case: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None]:
    """Problems with one case, and its mutation snapshot (None for ask cases)."""
    problems = [f"request: {e}" for e in contracts.validate("request", to_request(case))]
    e = case["expected"]
    if e["behavior"] == "ask":
        if e.get("reference_solution") or e.get("hidden_tests"):
            problems.append("an ask case has no reference solution or hidden tests")
        if not e.get("open_questions"):
            problems.append("an ask case lists its open questions")
        return problems, None
    spec, tests, ref = case["input"]["spec"], js_tests(case), e["reference_solution"]
    if len(e.get("hidden_tests", [])) < 5:
        problems.append("fewer than 5 hidden tests")
    report = sandbox.execute(ref, spec=spec, tests=tests)
    for f in report["lint"]:
        problems.append(f"reference lint {f['code']} line {f['range']['start_line']}: {f['message']}")
    for t in report["tests"]:
        if t["status"] != "pass":
            problems.append(f"reference fails {t['name']}: {t.get('message', t['status'])}")
    if report["violations"]:
        problems.append(f"reference violations: {report['violations']}")
    muts = sandbox.mutants(ref)
    reports = sandbox.execute_many([{"code": m["code"], "spec": spec, "tests": tests} for m in muts])
    label = lambda m: f"line {m['line']} col {m['column']}: {m['from']} -> {m['to']}"  # noqa: E731
    survivors = [label(m) for m, r in zip(muts, reports, strict=True) if sandbox.accepted(r)]
    equivalent = set(e.get("equivalent_mutants", []))
    stale = sorted(equivalent - set(survivors))
    if stale:
        problems.append(f"listed equivalent mutants no longer survive: {stale}")
    counted = len(muts) - len(equivalent & set(survivors))
    killed = len(muts) - len(survivors)
    snap = {
        "mutants": len(muts),
        "killed": killed,
        "equivalent": len(equivalent & set(survivors)),
        "score": round(killed / counted, 3) if counted else 1.0,
        "survivors": [s for s in survivors if s not in equivalent],
    }
    if counted and snap["score"] < MIN_SCORE:
        problems.append(f"mutation score {snap['score']} is below {MIN_SCORE}")
    return problems, snap


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batch")
    ap.add_argument("--write", action="store_true", help="update expected.mutation in the batch")
    a = ap.parse_args(argv)
    path = Path(a.batch)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    failed = 0
    snaps: dict[str, dict[str, Any]] = {}
    for case in data["cases"]:
        if case["task"] != "js_generation":
            continue
        problems, snap = verify_case(case)
        if snap is not None:
            snaps[case["id"]] = snap
            print(
                f"{case['id']}: {snap['killed']}/{snap['mutants']} mutants killed, "
                f"{snap['equivalent']} equivalent ({snap['score']:.0%})"
            )
            for s in snap["survivors"]:
                print(f"    survivor {s}")
        else:
            print(f"{case['id']}: ask case")
        for p in problems:
            print(f"  PROBLEM {p}")
        failed += bool(problems)
    if a.write:
        write_snapshots(path, snaps)
    print(f"{failed} case(s) with problems")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
