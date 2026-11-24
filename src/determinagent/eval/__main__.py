"""python -m determinagent.eval {score|compare|baseline} ...

score    GOLDEN.yaml RUN.jsonl [--task T] [--split S] [--labelled-only]
compare  GOLDEN.yaml BASE.jsonl CANDIDATE.jsonl
baseline GOLDEN.yaml {oracle|checker} OUT.jsonl
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
    a = ap.parse_args(argv)

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
