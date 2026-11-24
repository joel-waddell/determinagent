"""Command line entry point: ``python -m determinagent check {rulespeak|gherkin} [FILE]``.

Reads FILE (or stdin), prints the result as JSON, and exits 0 when every input
passes, 1 when one does not. A Gherkin document passes when it is conformant. A
RuleSpeak statement passes when the profile accepts it, its form conforms and
local policy passes; review findings are reported but do not fail it. RuleSpeak
input is one statement per line.
"""

from __future__ import annotations

import argparse
import json
import sys

from .conformance import gherkin, rulespeak


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="determinagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="check conformance of RuleSpeak statements or a Gherkin feature")
    chk.add_argument("profile", choices=["rulespeak", "gherkin"])
    chk.add_argument("file", nargs="?", type=argparse.FileType("r", encoding="utf-8"), default=sys.stdin)
    chk.add_argument("--vocabulary", help="comma-separated business terms (RuleSpeak only)")
    args = ap.parse_args(argv)

    text = args.file.read()
    if args.profile == "gherkin":
        results = [gherkin.check(text)]
        out = [results[0].to_dict()]
    else:
        vocab = args.vocabulary.split(",") if args.vocabulary else None
        lines = [line for line in text.splitlines() if line.strip()]
        results = [rulespeak.check(line, vocab) for line in lines]
        out = [{"input": line, **r.to_dict()} for line, r in zip(lines, results, strict=True)]
    json.dump(out if len(out) != 1 else out[0], sys.stdout, indent=2)
    sys.stdout.write("\n")
    ok = [r.conformant for r in results] if args.profile == "gherkin" else [r.passed for r in results]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
