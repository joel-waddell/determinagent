"""Build a labelling workbook from a golden-set YAML batch, and read labels back.

    python tools/golden/workbook.py build golden/v1/pilot.yaml out.xlsx
    python tools/golden/workbook.py import golden/v1/pilot.yaml labelled.xlsx

The workbook has one sheet per task. Grey columns are the case and Claude's
draft; yellow columns are for the domain expert. "import" copies the expert's
columns back into the YAML: a row marked Agree keeps the draft, a row marked
Correct takes the expert's values, and either way the case becomes
label.status "labelled". Rows left blank stay drafts.
"""

from __future__ import annotations

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
            ("draft note", 40, lambda c: c.get("draft_note") or ""),
        ],
        [
            ("verdict", 10, VERDICTS),
            ("behavior", 10, BEHAVIORS),
            ("reference statement(s), one per line", 55, None),
            ("RS ids", 16, None),
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
    "Checker result (T2) is what the deterministic checker returns today. It is shown for context, not as the answer.",
]


def _requirement_text(r: dict) -> str:
    lines = [f"Role: {r['role']}"] if r.get("role") else []
    lines.append(f"Capability: {r['capability']}")
    if r.get("benefit"):
        lines.append(f"Benefit: {r['benefit']}")
    lines += [f"- {a}" for a in r.get("acceptance_criteria", [])]
    return "\n".join(lines)


def build(batch_path: Path, out_path: Path) -> None:
    data = yaml.safe_load(batch_path.read_text(encoding="utf-8"))
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    for i, line in enumerate(README, 1):
        ws.cell(i, 1, line).font = Font(bold=(i == 1), size=14 if i == 1 else 11)
    ws.column_dimensions["A"].width = 140
    for task, (title, draft_cols, expert_cols) in SHEETS.items():
        sh = wb.create_sheet(title)
        cases = [c for c in data["cases"] if c["task"] == task]
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


def _split_lines(v: str) -> list[str]:
    return [x.strip() for x in str(v).splitlines() if x.strip()]


def _split_ids(v: str) -> list[str]:
    return [x.strip() for x in str(v).replace(";", ",").split(",") if x.strip()]


def import_labels(batch_path: Path, xlsx_path: Path, labeller: str = "domain expert") -> dict[str, int]:
    data = yaml.safe_load(batch_path.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in data["cases"]}
    wb = load_workbook(xlsx_path, data_only=True)
    counts = {"labelled": 0, "dropped": 0, "unlabelled": 0}
    drop: set[str] = set()
    for task, (title, draft_cols, expert_cols) in SHEETS.items():
        sh = wb[title]
        n = len(draft_cols)
        for row in sh.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            c = by_id[row[0]]
            verdict, *vals = row[n : n + len(expert_cols)]
            vals = [v if v not in (None, "") else None for v in vals]
            if not verdict:
                counts["unlabelled"] += 1
                continue
            if verdict == "Drop":
                drop.add(c["id"])
                counts["dropped"] += 1
                continue
            e = c["expected"]
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
                    behavior, stmts, ids, _ = vals
                    if behavior:
                        e["behavior"] = behavior
                    if stmts:
                        e["reference_statements"] = _split_lines(stmts)
                    if ids:
                        e["rs_refs"] = _split_ids(ids)
                else:
                    behavior, feature, checks, _ = vals
                    if behavior:
                        e["behavior"] = behavior
                    if feature:
                        e["reference_feature"] = _Lit(str(feature).rstrip("\n") + "\n")
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
    batch_path.write_text(header + yaml.dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in {"build", "import"}:
        print(__doc__)
        return 2
    cmd, batch, xlsx = argv
    if cmd == "build":
        build(Path(batch), Path(xlsx))
    else:
        print(import_labels(Path(batch), Path(xlsx)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
