"""Deterministic RuleSpeak conformance checker.

Checks one rule statement against the approved sentence templates and the
keyword and style guidance in ``spec/rulespeak.yaml``. No model is involved:
the same input always produces the same verdict.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from .result import ConformanceResult, Defect, Severity

PROFILE = "rulespeak"


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    kind: str
    form: str
    regex: re.Pattern[str]
    example: str


@dataclass(frozen=True)
class RuleSpeakProfile:
    version: str
    templates: tuple[Template, ...]
    defects: dict[str, dict[str, Any]]
    lexicon: dict[str, list[str]]
    rule_keywords: frozenset[str]
    max_words: int

    def defect(self, code: str, message: str | None = None) -> Defect:
        spec = self.defects[code]
        return Defect(code, Severity(spec["severity"]), message or spec["title"])


def _phrase_regex(phrases: Iterable[str]) -> re.Pattern[str]:
    alts = sorted((re.escape(p).replace(r"\ ", r"\s+") for p in phrases), key=len, reverse=True)
    return re.compile(r"(?<![\w/])(?:" + "|".join(alts) + r")(?![\w/])", re.IGNORECASE)


def load_profile(data: dict[str, Any] | None = None) -> RuleSpeakProfile:
    """Build a profile from YAML data, or from the packaged spec when omitted."""
    if data is None:
        text = resources.files("determinagent.spec").joinpath("rulespeak.yaml").read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    det = "|".join(re.escape(d) for d in data["determiners"])
    templates = tuple(
        Template(
            id=t["id"],
            name=t["name"],
            kind=t["kind"],
            form=t["form"],
            regex=re.compile(t["pattern"].replace("{det}", det), re.IGNORECASE),
            example=t["example"],
        )
        for t in data["templates"]
    )
    return RuleSpeakProfile(
        version=str(data["version"]),
        templates=templates,
        defects=data["defects"],
        lexicon=data["lexicon"],
        rule_keywords=frozenset(k.lower() for k in data["rule_keywords"]),
        max_words=int(data["max_words"]),
    )


@lru_cache(maxsize=1)
def default_profile() -> RuleSpeakProfile:
    return load_profile()


_WS = re.compile(r"\s+")
_SENTENCE_BREAK = re.compile(r"[.!?;](?=\s+\S)")
_ABBREV = re.compile(r"\b(?:e\.g|i\.e|etc|vs|no|approx)\.", re.IGNORECASE)
_DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")


def normalize(statement: str) -> str:
    return _WS.sub(" ", statement).strip()


def _first_word(text: str) -> str:
    m = re.match(r"[A-Za-z]+", text)
    return m.group(0).lower() if m else ""


def check(
    statement: str,
    vocabulary: Iterable[str] | None = None,
    profile: RuleSpeakProfile | None = None,
) -> ConformanceResult:
    """Check a single RuleSpeak rule statement.

    ``vocabulary`` is an optional list of business terms (the fact model).
    When given, the subject of the statement must contain one of them.
    """
    p = profile or default_profile()
    s = normalize(statement)
    result = ConformanceResult(profile=PROFILE, profile_version=p.version)
    add = result.defects.append
    lex = p.lexicon

    if not s:
        add(p.defect("RS-KW-001", "Empty statement"))
        return result

    # Structure: exactly one sentence, ending in a full stop.
    masked = _DECIMAL.sub("_", _ABBREV.sub(lambda m: m.group(0).replace(".", "_"), s))
    if _SENTENCE_BREAK.search(masked) or not s.endswith("."):
        add(p.defect("RS-STR-001"))

    lower = s.lower()
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", lower)

    if _first_word(s) in {w for w in lex["leading_condition_words"] if " " not in w} or any(
        lower.startswith(w + " ") for w in lex["leading_condition_words"] if " " in w
    ):
        add(p.defect("RS-STR-003"))

    keyword_count = sum(1 for w in words if w in p.rule_keywords)
    if keyword_count > 1:
        add(p.defect("RS-STR-002"))

    modal = _phrase_regex(lex["non_rulespeak_modals"]).search(s)
    if modal:
        add(p.defect("RS-KW-002", f'Non-RuleSpeak modal "{modal.group(0)}"'))

    if keyword_count == 0 and not modal and not re.search(r"\bconsidered\b|\bcomputed as\b", lower):
        add(p.defect("RS-KW-001"))

    if re.search(r"\bmay\b", lower) and not re.search(r"\bonly\b", lower):
        add(p.defect("RS-KW-003"))

    if m := _phrase_regex(lex["system_terms"]).search(s):
        add(p.defect("RS-STY-001", f'System-centric wording "{m.group(0)}"'))
    if m := _phrase_regex(lex["procedural_terms"]).search(s):
        add(p.defect("RS-STY-002", f'Procedural wording "{m.group(0)}"'))
    if re.search(r"\bmust\s+(?:" + "|".join(lex["redundant_adverbs"]) + r")\b", lower):
        add(p.defect("RS-STY-003"))
    if len(words) > p.max_words:
        add(p.defect("RS-STY-004", f"Long statement ({len(words)} words)"))

    if m := _phrase_regex(lex["vague_terms"]).search(s):
        add(p.defect("RS-VAG-001", f'Vague term "{m.group(0)}"'))
    if re.search(r"\band\s*/\s*or\b", lower):
        add(p.defect("RS-VAG-002"))

    # Template match, on the single-sentence form only.
    if "RS-STR-001" not in result.codes:
        for t in p.templates:
            m = t.regex.match(s)
            if m:
                result.template_id = t.id
                result.slots = {k: v for k, v in m.groupdict().items() if v is not None}
                break
        else:
            if not {"RS-STR-003", "RS-KW-001", "RS-KW-002", "RS-KW-003"} & set(result.codes):
                add(p.defect("RS-TPL-001"))

    if vocabulary is not None and result.template_id:
        subject = result.slots.get("subject", "")
        terms = [t.strip().lower() for t in vocabulary if t.strip()]
        if not any(re.search(r"\b" + re.escape(t) + r"s?\b", subject.lower()) for t in terms):
            add(p.defect("RS-VOC-001", f'Subject "{subject}" uses no vocabulary term'))

    return result
