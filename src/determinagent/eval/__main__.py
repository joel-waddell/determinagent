"""python -m determinagent.eval {score|compare|baseline} ...

score    GOLDEN.yaml RUN.jsonl [--task T] [--split S] [--labelled-only]
compare  GOLDEN.yaml BASE.jsonl CANDIDATE.jsonl
baseline GOLDEN.yaml {oracle|checker} OUT.jsonl
run      GOLDEN.yaml --model SPEC --out OUT.jsonl [--task T] [--limit N] [--retries N]
         [--max-cost USD] [--dry-run]

A model SPEC is anthropic:<model>, ollama:<model> or openai-compat:<model>@<base_url>
(see determinagent.models.from_spec). --dry-run prints the first prompt and calls nothing.
A paid backend (anthropic:...) needs --max-cost, so a run cannot spend without a cap.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import baselines
from .gate import compare, gate
from .score import score_run


def _cases(paths: list[str]) -> list[dict]:
    return [c for p in paths for c in yaml.safe_load(Path(p).read_text(encoding="utf-8"))["cases"]]


def _records(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _run(a: argparse.Namespace) -> int:
    from ..models import from_spec
    from .runner import REPLY_SCHEMAS, prepare, run

    cases = [c for c in _cases([a.golden]) if not a.task or c["task"] == a.task][: a.limit]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2
    if a.dry_run:
        _, _, p = prepare(cases[0])
        print(f"# {len(cases)} cases selected; prompt {p.version} for {cases[0]['id']}\n")
        print(p.system, "\n\n---\n", p.user, "\n\n---\nreply schema:", json.dumps(REPLY_SCHEMAS[cases[0]["task"]]))
        return 0
    if not a.out:
        print("--out is required unless --dry-run", file=sys.stderr)
        return 2
    if a.model.startswith("anthropic:") and a.max_cost is None:
        print("a paid backend needs --max-cost USD", file=sys.stderr)
        return 2
    recs = run(cases, from_spec(a.model), retries=a.retries, max_cost_usd=a.max_cost)
    Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    spent = sum(r.get("cost_usd") or 0.0 for r in recs)
    print(f"{len(recs)} of {len(cases)} cases run, USD {spent:.4f}, written to {a.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="determinagent.eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("golden")
    s.add_argument("run")
    s.add_argument("--task")
    s.add_argument("--split")
    s.add_argument("--labelled-only", action="store_true")
    c = sub.add_parser("compare")
    c.add_argument("golden")
    c.add_argument("baseline")
    c.add_argument("candidate")
    b = sub.add_parser("baseline")
    b.add_argument("golden")
    b.add_argument("system", choices=["oracle", "checker"])
    b.add_argument("out")
    r = sub.add_parser("run")
    r.add_argument("golden")
    r.add_argument("--model", required=True)
    r.add_argument("--out")
    r.add_argument("--task")
    r.add_argument("--limit", type=int)
    r.add_argument("--retries", type=int, default=2)
    r.add_argument("--max-cost", type=float)
    r.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        return _run(a)

    if a.cmd == "baseline":
        cases = _cases([a.golden])
        recs = getattr(baselines, a.system)(cases)
        Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        print(f"{len(recs)} records written to {a.out}")
        return 0

    cases = _cases([a.golden])
    if a.cmd == "score":
        rep = score_run(cases, _records(a.run)).subset(task=a.task, split=a.split, labelled_only=a.labelled_only)
        json.dump({"system": rep.system, "metrics": rep.metrics(), "targets": gate(rep)}, sys.stdout, indent=2)
    else:
        base = score_run(cases, _records(a.baseline))
        cand = score_run(cases, _records(a.candidate))
        tasks = {r["response"]["task"] for r in _records(a.candidate) if "response" in r}
        if len(tasks) == 1:
            t = tasks.pop()
            base, cand = base.subset(task=t), cand.subset(task=t)
        json.dump(compare(base, cand), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
