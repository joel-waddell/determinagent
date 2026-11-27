"""Build a labelling workbook from a golden-set YAML batch, and read labels back.

    python tools/golden/workbook.py build golden/v1/pilot.yaml out.xlsx
    python tools/golden/workbook.py import golden/v1/pilot.yaml labelled.xlsx
    python tools/golden/workbook.py build golden/v1/j2-pilot.yaml recheck.xlsx --status draft

"--status draft" builds a re-check workbook of only the cases still in that
label status; it imports back the same way, since rows are matched by id.

The workbook has one sheet per task. Grey columns are the case and Claude's
draft; yellow columns are for the domain expert. "import" copies the expert's
columns back into the YAML: a row marked Agree keeps the draft, a row marked
Correct takes the expert's values, and either way the case becomes
label.status "labelled". Rows left blank stay drafts.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

GREY = PatternFill("solid", fgColor="EEEEEE")
YELLOW = PatternFill("solid", fgColor="FFF4C2")
WRAP = Alignment(wrap_text=True, vertical="top")

FORMS = ["conforms", "needs_revision", "undetermined"]
BEHAVIORS = ["draft", "ask"]
VERDICTS = ["Agree", "Correct", "Drop"]


class _Lit(str):
    pass


yaml.add_representer(
    _Lit, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None)
)

# (sheet, task, draft columns, expert columns)
SHEETS = {
    "rulespeak_generation": (
        "T1 Generation",
        [
            ("id", 12, lambda c: c["id"]),
            ("stratum", 16, lambda c: c["stratum"]),
            ("intent", 45, lambda c: c["input"]["intent"]),
            ("vocabulary", 22, lambda c: ", ".join(c["input"]["vocabulary"])),
            ("draft behavior", 10, lambda c: c["expected"]["behavior"]),
            ("draft reference statement(s)", 55, lambda c: "\n".join(c["expected"]["reference_statements"])),
            ("draft RS ids", 16, lambda c: ", ".join(c["expected"]["rs_refs"])),
            ("draft vocabulary proposals", 35, lambda c: _proposals_text(c["expected"].get("vocabulary_proposals"))),
            ("draft note", 40, lambda c: c.get("draft_note") or ""),
        ],
        [
            ("verdict", 10, VERDICTS),
            ("behavior", 10, BEHAVIORS),
            ("reference statement(s), one per line", 55, None),
            ("RS ids", 16, None),
            ("vocabulary proposals (term: definition, one per line)", 35, None),
            ("notes", 40, None),
        ],
    ),
    "rulespeak_validation": (
        "T2 Validation",
        [
            ("id", 12, lambda c: c["id"]),
            ("stratum", 16, lambda c: c["stratum"]),
            ("statement", 55, lambda c: c["input"]["statement"]),
            (
                "checker result",
                26,
                lambda c: (
                    f"{c['checker']['profile_acceptance']}, {c['checker']['form']}\n" + ", ".join(c["checker"]["codes"])
                ),
            ),
            ("draft form", 14, lambda c: c["expected"]["form"]),
            ("draft RS ids", 16, lambda c: ", ".join(c["expected"]["rs_refs"])),
            ("draft reason", 45, lambda c: c["expected"]["reason"]),
        ],
        [
            ("verdict", 10, VERDICTS),
            ("form", 14, FORMS),
            ("RS ids", 16, None),
            ("reason", 45, None),
            ("notes", 40, None),
        ],
    ),
    "js_generation": (
        "J2 JavaScript",
        [
            ("id", 12, lambda c: c["id"]),
            ("stratum", 14, lambda c: c["stratum"]),
            ("spec (what the model sees)", 60, lambda c: _spec_text(c["input"]["spec"])),
            ("draft behavior", 10, lambda c: c["expected"]["behavior"]),
            ("draft reference solution", 60, lambda c: c["expected"].get("reference_solution") or ""),
            ("draft hidden tests", 60, lambda c: _tests_text(c["expected"])),
            ("mutation check", 24, lambda c: _mutation_text(c["expected"])),
            ("draft note", 35, lambda c: c.get("draft_note") or ""),
        ],
        [
            ("verdict", 10, VERDICTS),
            ("behavior", 10, BEHAVIORS),
            ("changes to the spec, reference or tests", 55, None),
            ("notes", 40, None),
        ],
    ),
    "gherkin_requirements": (
        "T3 Gherkin",
        [
            ("id", 12, lambda c: c["id"]),
            ("stratum", 16, lambda c: c["stratum"]),
            ("requirement", 45, lambda c: _requirement_text(c["input"]["requirement"])),
            ("draft behavior", 10, lambda c: c["expected"]["behavior"]),
            ("draft reference feature", 70, lambda c: c["expected"].get("reference_feature") or ""),
            ("draft acceptance checks", 35, lambda c: "\n".join(c["expected"]["acceptance_checks"])),
            ("draft note", 35, lambda c: c.get("draft_note") or ""),
        ],
        [
            ("verdict", 10, VERDICTS),
            ("behavior", 10, BEHAVIORS),
            ("reference feature (if correcting)", 70, None),
            ("acceptance checks, one per line", 35, None),
            ("notes", 40, None),
        ],
    ),
}

README = [
    "DeterminAgent golden set: labelling workbook",
    "",
    "Each task has its own sheet. Grey columns hold the case and Claude's draft label. Yellow columns are yours.",
    "verdict: Agree keeps the draft as the label. Correct uses your values in the yellow columns "
    "(leave a yellow cell blank to keep that part of the draft). Drop removes the case.",
    "Leave verdict blank for any case you have not labelled yet; it stays a draft.",
    "form (T2): conforms, needs_revision or undetermined, as in the RuleSpeak-Agent.md response contract.",
    "behavior (T1, T3): draft = the system should produce output; ask = it should ask a clarifying question instead.",
    "RS ids: comma-separated, e.g. RS-04, RS-12.",
    "Vocabulary (T1): the case's vocabulary is closed. A term the statement needs but the vocabulary lacks is proposed",
    "  for the user to confirm, as 'term: definition', one per line. Correct it if the term or definition is wrong.",
    "Checker result (T2) is what the deterministic checker returns today. It is shown for context, not as the answer.",
    "J2 JavaScript: the model sees only the spec column. A case is right when the spec is clear enough to implement,",
    "  the reference solution is correct, and the hidden tests check what the behavior promises.",
    "  Agree if all three hold.",
    "  Correct: set behavior (draft or ask) and/or describe what to change. Claude applies it and the case comes back",
    "  for a quick re-check. ask = the spec leaves a decision open, so the model should ask instead of writing code.",
    "  Mutation check: how many one-token changes to the reference the tests catch.",
    "  Changes that cannot alter any result are listed as equivalent, with the reason.",
]


def _value(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _spec_text(spec: dict) -> str:
    params = ", ".join(f"{p['name']}{'?' if p.get('optional') else ''}: {p['type']}" for p in spec["params"])
    head = f"{'async ' if spec.get('async') else ''}{spec['name']}({params}) -> {spec['returns']['type']}"
    if spec.get("export") == "default":
        head += "  [default export]"
    lines = [head, "", spec["behavior"]]
    if spec.get("examples"):
        lines.append("")
        for ex in spec["examples"]:
            args = ", ".join(_value(a) for a in ex["args"])
            res = f"throws {ex['throws']}" if "throws" in ex else _value(ex["returns"])
            lines.append(f"{spec['name']}({args}) -> {res}")
    for c in spec.get("constraints", []):
        lines.append(f"Constraint: {c}")
    return "\n".join(lines)


def _tests_text(e: dict) -> str:
    if e["behavior"] == "ask":
        return "Open questions:\n" + "\n".join(f"- {q}" for q in e.get("open_questions", []))
    lines = []
    for t in e.get("hidden_tests", []):
        if "code" in t:
            lines.append(f"{t['name']}:\n" + "\n".join(f"    {x}" for x in t["code"].rstrip().splitlines()))
        else:
            args = ", ".join(_value(a) for a in t["args"])
            res = f"throws {t['throws']}" if "throws" in t else _value(t["returns"])
            lines.append(f"{t['name']}: ({args}) -> {res}")
    return "\n".join(lines)


def _mutation_text(e: dict) -> str:
    m = e.get("mutation")
    if not m:
        return ""
    text = f"{m['killed']} of {m['mutants']} caught"
    if m.get("equivalent"):
        text += f"; {m['equivalent']} equivalent ({e.get('equivalent_note', '')})"
    return text


def _requirement_text(r: dict) -> str:
    lines = [f"Role: {r['role']}"] if r.get("role") else []
    lines.append(f"Capability: {r['capability']}")
    if r.get("benefit"):
        lines.append(f"Benefit: {r['benefit']}")
    lines += [f"- {a}" for a in r.get("acceptance_criteria", [])]
    return "\n".join(lines)


def build(batch_path: Path, out_path: Path, status: str | None = None) -> None:
    data = yaml.safe_load(batch_path.read_text(encoding="utf-8"))
    if status:
        data["cases"] = [c for c in data["cases"] if c.get("label", {}).get("status") == status]
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    for i, line in enumerate(README, 1):
        ws.cell(i, 1, line).font = Font(bold=(i == 1), size=14 if i == 1 else 11)
    ws.column_dimensions["A"].width = 140
    for task, (title, draft_cols, expert_cols) in SHEETS.items():
        cases = [c for c in data["cases"] if c["task"] == task]
        if not cases:
            continue
        sh = wb.create_sheet(title)
        cols = [(h, w, GREY) for h, w, _ in draft_cols] + [(h, w, YELLOW) for h, w, _ in expert_cols]
        for j, (h, w, fill) in enumerate(cols, 1):
            cell = sh.cell(1, j, h)
            cell.font, cell.fill = Font(bold=True), fill
            sh.column_dimensions[cell.column_letter].width = w
        for i, c in enumerate(cases, 2):
            for j, (_, _, get) in enumerate(draft_cols, 1):
                cell = sh.cell(i, j, get(c))
                cell.alignment, cell.fill = WRAP, GREY
            for j in range(len(draft_cols) + 1, len(cols) + 1):
                cell = sh.cell(i, j)
                cell.alignment, cell.fill = WRAP, YELLOW
        for j, (_, _, choices) in enumerate(expert_cols, len(draft_cols) + 1):
            if choices and cases:
                dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True)
                letter = sh.cell(1, j).column_letter
                dv.add(f"{letter}2:{letter}{len(cases) + 1}")
                sh.add_data_validation(dv)
        sh.freeze_panes = "C2"
    wb.save(out_path)


def _literals(obj):
    """Multi-line strings (features, reference solutions, test snippets) as YAML block literals."""
    if isinstance(obj, dict):
        return {k: _literals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_literals(v) for v in obj]
    if isinstance(obj, str) and "\n" in obj:
        return _Lit(obj)
    return obj


def _split_lines(v: str) -> list[str]:
    return [x.strip() for x in str(v).splitlines() if x.strip()]


def _proposals_text(props: list[dict] | None) -> str:
    return "\n".join(f"{p['term']}: {p['definition']}" for p in props or [])


def _proposals(v: str) -> list[dict[str, str]]:
    out = []
    for line in _split_lines(v):
        term, _, definition = line.partition(":")
        out.append({"term": term.strip(), "definition": definition.strip()})
    return out


def _split_ids(v: str) -> list[str]:
    return [x.strip() for x in str(v).replace(";", ",").split(",") if x.strip()]


_GK_LINE = re.compile(
    r"\s+(?=(?:Feature|Rule|Background|Scenario Outline|Scenario Template|Scenario|Example|Examples):"
    r"|(?:Given|When|Then|And|But)\s)"
)
_GK_INDENT = {"Feature": 0, "Rule": 2, "Background": 2, "Scenario": 2, "Example": 2, "Examples": 4}


def _reflow_feature(text: str) -> str:
    """Restore line breaks in a feature that was pasted into one cell as a single line.

    Spreadsheet edits often flatten multi-line cells. Gherkin keywords and table
    rows mark where each line starts, so a feature with no line breaks is split
    back into lines and indented. A feature that already has line breaks is left
    as it is.
    """
    text = str(text).strip()
    if "\n" in text:
        return text + "\n"
    out: list[str] = []
    for part in _GK_LINE.split(text):
        head, bar, rows = part.partition("|")
        head = head.strip()
        key = head.split(":")[0] if ":" in head else ""
        key = "Scenario" if key.startswith("Scenario") else key
        if key in _GK_INDENT:
            if key != "Feature":
                out.append("")
            out.append(" " * _GK_INDENT[key] + head)
        elif head:
            out.append("    " + head)
        if bar:
            for row in (bar + rows).replace("| |", "|\n|").splitlines():
                out.append("      " + " ".join(row.split()))
    return "\n".join(out) + "\n"


def import_labels(batch_path: Path, xlsx_path: Path, labeller: str = "domain expert") -> dict[str, int]:
    data = yaml.safe_load(batch_path.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in data["cases"]}
    wb = load_workbook(xlsx_path, data_only=True)
    counts = {"labelled": 0, "revise": 0, "dropped": 0, "unlabelled": 0}
    drop: set[str] = set()
    for task, (title, _draft_cols, expert_cols) in SHEETS.items():
        if title not in wb.sheetnames:
            continue
        sh = wb[title]
        # Columns are found by header, so a workbook built before a column was
        # added still imports: a missing column reads as blank.
        header = list(next(sh.iter_rows(min_row=1, max_row=1, values_only=True)))
        start = header.index("verdict")
        pos = {h: i for i, h in enumerate(header) if i >= start and h}
        names = [h for h, _, _ in expert_cols]
        for row in sh.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            c = by_id[row[0]]
            verdict = row[pos["verdict"]]
            vals = [row[pos[h]] if h in pos and pos[h] < len(row) else None for h in names[1:]]
            vals = [v if v not in (None, "") else None for v in vals]
            if not verdict:
                counts["unlabelled"] += 1
                continue
            if verdict == "Drop":
                drop.add(c["id"])
                counts["dropped"] += 1
                continue
            e = c["expected"]
            if task == "js_generation":
                behavior, changes, notes = vals
                if verdict == "Correct" and behavior:
                    e["behavior"] = behavior
                # Code and test changes are applied by hand, then the case is re-checked.
                status = "revise" if verdict == "Correct" and (changes or behavior) else "labelled"
                c["label"] = {"status": status, "labelled_by": labeller, "verdict": verdict, "notes": notes}
                if changes:
                    c["label"]["requested_changes"] = str(changes)
                counts["labelled" if status == "labelled" else "revise"] += 1
                continue
            if verdict == "Correct":
                if task == "rulespeak_validation":
                    form, ids, reason, _ = vals
                    if form:
                        e["form"] = form
                    if ids:
                        e["rs_refs"] = _split_ids(ids)
                    if reason:
                        e["reason"] = reason
                elif task == "rulespeak_generation":
                    behavior, stmts, ids, props, _ = vals
                    if behavior:
                        e["behavior"] = behavior
                    if stmts:
                        e["reference_statements"] = _split_lines(stmts)
                    if ids:
                        e["rs_refs"] = _split_ids(ids)
                    if props:
                        e["vocabulary_proposals"] = _proposals(props)
                else:
                    behavior, feature, checks, _ = vals
                    if behavior:
                        e["behavior"] = behavior
                    if feature:
                        e["reference_feature"] = _Lit(_reflow_feature(feature))
                    if checks:
                        e["acceptance_checks"] = _split_lines(checks)
            if e.get("reference_feature"):
                e["reference_feature"] = _Lit(e["reference_feature"])
            c["label"] = {"status": "labelled", "labelled_by": labeller, "verdict": verdict, "notes": vals[-1]}
            counts["labelled"] += 1
    data["cases"] = [c for c in data["cases"] if c["id"] not in drop]
    header = "".join(
        line + "\n" for line in batch_path.read_text(encoding="utf-8").splitlines() if line.startswith("#")
    )
    body = yaml.dump(_literals(data), sort_keys=False, allow_unicode=True, width=120)
    batch_path.write_text(header + body, encoding="utf-8")
    return counts


def main(argv: list[str]) -> int:
    status = None
    if len(argv) == 5 and argv[0] == "build" and argv[3] == "--status":
        status, argv = argv[4], argv[:3]
    if len(argv) != 3 or argv[0] not in {"build", "import"}:
        print(__doc__)
        return 2
    cmd, batch, xlsx = argv
    if cmd == "build":
        build(Path(batch), Path(xlsx), status)
    else:
        print(import_labels(Path(batch), Path(xlsx)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
