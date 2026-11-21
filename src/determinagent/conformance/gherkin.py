"""Deterministic Gherkin conformance checker.

Parses with the official Cucumber parser (``gherkin-official``), then applies
the DeterminAgent profile in ``spec/gherkin.yaml``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml
from gherkin.errors import CompositeParserException, ParserError
from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner

from .result import ConformanceResult, Defect, Severity

PROFILE = "gherkin"

# keywordType values emitted by the official parser.
CONTEXT, ACTION, OUTCOME, CONJUNCTION, UNKNOWN = "Context", "Action", "Outcome", "Conjunction", "Unknown"
_PHASE = {CONTEXT: 0, ACTION: 1, OUTCOME: 2}
_PLACEHOLDER = re.compile(r"<([^<>]+)>")


@dataclass(frozen=True)
class GherkinProfile:
    version: str
    languages: frozenset[str]
    max_steps: int
    defects: dict[str, dict[str, Any]]

    def defect(self, code: str, message: str | None = None, loc: dict[str, int] | None = None) -> Defect:
        spec = self.defects[code]
        return Defect(
            code,
            Severity(spec["severity"]),
            message or spec["title"],
            line=(loc or {}).get("line"),
            column=(loc or {}).get("column"),
        )


def load_profile(data: dict[str, Any] | None = None) -> GherkinProfile:
    if data is None:
        text = resources.files("determinagent.spec").joinpath("gherkin.yaml").read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    return GherkinProfile(
        version=str(data["version"]),
        languages=frozenset(data["languages"]),
        max_steps=int(data["max_steps_per_scenario"]),
        defects=data["defects"],
    )


@lru_cache(maxsize=1)
def default_profile() -> GherkinProfile:
    return load_profile()


def parse(source: str) -> dict[str, Any]:
    """Parse with the official parser. Raises the parser's exceptions."""
    return Parser().parse(TokenScanner(source))


def check(source: str, profile: GherkinProfile | None = None) -> ConformanceResult:
    p = profile or default_profile()
    result = ConformanceResult(profile=PROFILE, profile_version=p.version)
    add = result.defects.append

    try:
        doc = parse(source)
    except CompositeParserException as exc:
        for err in exc.errors:
            add(p.defect("GK-PARSE-001", str(err), getattr(err, "location", None)))
        return result
    except ParserError as exc:
        add(p.defect("GK-PARSE-001", str(exc), getattr(exc, "location", None)))
        return result

    feature = doc.get("feature")
    if not feature:
        add(p.defect("GK-STR-001"))
        return result
    floc = feature["location"]
    if feature.get("language") not in p.languages:
        add(p.defect("GK-LANG-001", f'Language "{feature.get("language")}" is not in the profile', floc))
    if not feature.get("name", "").strip():
        add(p.defect("GK-STR-002", loc=floc))

    scenarios = 0
    names: dict[str, dict[str, int]] = {}

    def walk(children: list[dict[str, Any]], inherited_context: bool) -> None:
        nonlocal scenarios
        has_context = inherited_context
        for child in children:
            if "background" in child:
                bg = child["background"]
                for step in bg.get("steps", []):
                    if step["keywordType"] not in (CONTEXT, CONJUNCTION):
                        add(
                            p.defect(
                                "GK-SEQ-006",
                                f'Background step "{step["keyword"].strip()} {step["text"]}"',
                                step["location"],
                            )
                        )
                if bg.get("steps"):
                    has_context = True
        for child in children:
            if "rule" in child:
                walk(child["rule"].get("children", []), has_context)
            elif "scenario" in child:
                scenarios += 1
                _check_scenario(p, child["scenario"], has_context, names, add)

    walk(feature.get("children", []), False)
    if scenarios == 0:
        add(p.defect("GK-STR-003", loc=floc))
    return result


def _check_scenario(p: GherkinProfile, sc: dict[str, Any], has_context: bool, names: dict[str, Any], add: Any) -> None:
    loc = sc["location"]
    name = sc.get("name", "").strip()
    if not name:
        add(p.defect("GK-STR-004", loc=loc))
    elif name.lower() in names:
        add(p.defect("GK-STR-006", f'Duplicate scenario name "{name}"', loc))
    else:
        names[name.lower()] = loc
    if sc.get("description", "").strip():
        add(p.defect("GK-STY-001", loc=loc))

    steps = sc.get("steps", [])
    if not steps:
        add(p.defect("GK-STR-005", loc=loc))
        return
    if len(steps) > p.max_steps:
        add(p.defect("GK-STY-003", f"{len(steps)} steps (max {p.max_steps})", loc))

    phase, seen, prev = -1, set(), None
    for i, step in enumerate(steps):
        kt = step["keywordType"]
        if kt == UNKNOWN:
            add(p.defect("GK-STY-002", loc=step["location"]))
            kt = prev
        elif kt == CONJUNCTION:
            if i == 0:
                add(p.defect("GK-SEQ-005", loc=step["location"]))
            kt = prev
        if kt in _PHASE:
            if _PHASE[kt] < phase:
                add(
                    p.defect(
                        "GK-SEQ-004",
                        f'"{step["keyword"].strip()} {step["text"]}" after a later step type',
                        step["location"],
                    )
                )
            phase = max(phase, _PHASE[kt])
            seen.add(kt)
        prev = kt

    if ACTION not in seen:
        add(p.defect("GK-SEQ-001", loc=loc))
    if OUTCOME not in seen:
        add(p.defect("GK-SEQ-002", loc=loc))
    if CONTEXT not in seen and not has_context:
        add(p.defect("GK-SEQ-003", loc=loc))

    placeholders = set()
    for step in steps:
        placeholders.update(_PLACEHOLDER.findall(step["text"]))
        arg = step.get("dataTable") or {}
        for row in arg.get("rows", []):
            for cell in row.get("cells", []):
                placeholders.update(_PLACEHOLDER.findall(cell.get("value", "")))
        doc = step.get("docString") or {}
        placeholders.update(_PLACEHOLDER.findall(doc.get("content", "")))

    examples = sc.get("examples", [])
    is_outline = (
        bool(examples) or "outline" in sc.get("keyword", "").lower() or "template" in sc.get("keyword", "").lower()
    )
    if not is_outline:
        return
    if not examples:
        add(p.defect("GK-OUT-001", loc=loc))
        return
    for ex in examples:
        header = ex.get("tableHeader")
        cols = {c["value"] for c in header["cells"]} if header else set()
        if not ex.get("tableBody"):
            add(p.defect("GK-OUT-003", loc=ex["location"]))
        for missing in sorted(placeholders - cols):
            add(p.defect("GK-OUT-002", f"Placeholder <{missing}> has no Examples column", ex["location"]))
