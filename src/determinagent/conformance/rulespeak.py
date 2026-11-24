"""Deterministic RuleSpeak checker (profile v0.2.0).

Checks one statement against the supported templates and the surface
diagnostics in ``spec/rulespeak.yaml``, and returns separate outcomes for
profile acceptance, RuleSpeak form, review and local policy. Every finding
carries its evidence chain (basis, RS ids and source locators). No model is
involved: the same input always gives the same result.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

PROFILE = "rulespeak"


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    guidance: str
    form: str
    regex: re.Pattern[str]
    example: str
    basis: str
    rs_refs: tuple[str, ...]


@dataclass(frozen=True)
class Finding:
    code: str
    title: str
    message: str
    kind: str
    disposition: str
    basis: str
    rs_refs: tuple[str, ...]
    source: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "kind": self.kind,
            "disposition": self.disposition,
            "basis": self.basis,
            "rs_refs": list(self.rs_refs),
            "source": list(self.source),
        }


def _sources(register: dict[str, Any], refs: Iterable[str]) -> list[str]:
    out: list[str] = []
    for r in refs:
        for loc in register[r]["source"]:
            if loc not in out:
                out.append(loc)
    return out


@dataclass
class RuleSpeakResult:
    profile_version: str
    findings: list[Finding] = field(default_factory=list)
    template: Template | None = None
    slots: dict[str, str] = field(default_factory=dict)
    term_hits: list[str] | None = None
    register: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]

    def _any(self, disposition: str, kind: str | None = None) -> bool:
        return any(f.disposition == disposition and (kind is None or f.kind == kind) for f in self.findings)

    @property
    def profile_acceptance(self) -> str:
        ok = self.template is not None and not self._any("error", "profile")
        return "accepted" if ok else "rejected"

    @property
    def form(self) -> str:
        if self._any("error", "form"):
            return "needs_revision"
        if self._any("review", "form") or self.profile_acceptance == "rejected":
            return "undetermined"
        return "conforms"

    @property
    def guidance_type(self) -> str | None:
        return self.template.guidance if self.template else None

    @property
    def review_required(self) -> bool:
        return self._any("review")

    @property
    def local_policy(self) -> str:
        return "fail" if self._any("error", "local") else "pass"

    @property
    def passed(self) -> bool:
        """Accepted, form conforms and local policy passes. Review findings do not fail this."""
        return self.profile_acceptance == "accepted" and self.form == "conforms" and self.local_policy == "pass"

    def to_dict(self) -> dict[str, Any]:
        t = self.template
        return {
            "profile": PROFILE,
            "profile_version": self.profile_version,
            "outcome": {
                "profile_acceptance": self.profile_acceptance,
                "form": self.form,
                "guidance_type": self.guidance_type,
                "fidelity": "unverified",
                "review_required": self.review_required,
                "local_policy": self.local_policy,
            },
            "template": None
            if t is None
            else {
                "id": t.id,
                "name": t.name,
                "basis": t.basis,
                "rs_refs": list(t.rs_refs),
                "source": _sources(self.register, t.rs_refs),
            },
            "slots": dict(self.slots),
            "term_hits": None if self.term_hits is None else list(self.term_hits),
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class RuleSpeakProfile:
    version: str
    templates: tuple[Template, ...]
    diagnostics: dict[str, dict[str, Any]]
    register: dict[str, Any]
    lexicon: dict[str, list[str]]
    max_words: int

    def finding(self, code: str, message: str | None = None) -> Finding:
        d = self.diagnostics[code]
        refs = tuple(d["rs_refs"])
        return Finding(
            code=code,
            title=d["title"],
            message=message or d["title"],
            kind=d["kind"],
            disposition=d["disposition"],
            basis=d["basis"],
            rs_refs=refs,
            source=tuple(_sources(self.register, refs)),
        )


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
            guidance=t["guidance"],
            form=t["form"],
            regex=re.compile(t["pattern"].replace("{det}", det), re.IGNORECASE),
            example=t["example"],
            basis=t["basis"],
            rs_refs=tuple(t["rs_refs"]),
        )
        for t in data["templates"]
    )
    return RuleSpeakProfile(
        version=str(data["version"]),
        templates=templates,
        diagnostics=data["diagnostics"],
        register=data["rs_register"],
        lexicon=data["lexicon"],
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


def check(
    statement: str,
    vocabulary: Iterable[str] | None = None,
    profile: RuleSpeakProfile | None = None,
) -> RuleSpeakResult:
    """Check a single RuleSpeak statement.

    ``vocabulary`` is an optional list of business terms. When given, the
    subject must contain one of them (a local policy check).
    """
    p = profile or default_profile()
    s = normalize(statement)
    result = RuleSpeakResult(profile_version=p.version, register=p.register)
    add = result.findings.append
    lex = p.lexicon

    if not s:
        add(p.finding("RS-PRF-003", "Empty statement"))
        add(p.finding("RS-KW-001"))
        return result

    # One sentence, ending in a full stop.
    masked = _DECIMAL.sub("_", _ABBREV.sub(lambda m: m.group(0).replace(".", "_"), s))
    if _SENTENCE_BREAK.search(masked) or not s.endswith("."):
        add(p.finding("RS-PRF-003"))

    lower = s.lower()
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", lower)

    # Leading qualification: a RuleSpeak style warning, and separately a parser limit.
    if _phrase_regex(lex["leading_qualification_words"]).match(s):
        add(p.finding("RS-STY-001"))
        add(p.finding("RS-PRF-002"))

    # Keywords.
    musts, onlys = words.count("must"), words.count("only")
    has_advice = "may" in words or re.search(r"\bneed\s+not\b", lower) is not None
    if musts == 0 and onlys == 0 and not has_advice:
        add(p.finding("RS-KW-001"))
    if musts > 1 or onlys > 1:
        add(p.finding("RS-KW-003"))
    if musts and onlys:
        add(p.finding("RS-KW-004"))
    if m := _phrase_regex(lex["modals_needing_interpretation"]).search(s):
        add(p.finding("RS-KW-002", f'Modal "{m.group(0)}" needs interpretation'))

    if m := _phrase_regex(lex["system_terms"]).search(s):
        add(p.finding("RS-STY-002", f'System term "{m.group(0)}" detected'))
    if m := _phrase_regex(lex["sequence_terms"]).search(s):
        add(p.finding("RS-STY-003", f'Sequence term "{m.group(0)}" detected'))
    if re.search(r"\bmust\s+(?:" + "|".join(lex["redundant_adverbs"]) + r")\b", lower):
        add(p.finding("RS-STY-004"))
    if m := _phrase_regex(lex["vague_terms"]).search(s):
        add(p.finding("RS-VAG-001", f'Vague term "{m.group(0)}" detected'))
    if re.search(r"\band\s*/\s*or\b", lower):
        add(p.finding("RS-VAG-002"))
    if len(words) > p.max_words:
        add(p.finding("RS-LOC-001", f"{len(words)} words (local limit {p.max_words})"))

    # Template match, on a single subject-first sentence only.
    if not {"RS-PRF-002", "RS-PRF-003"} & set(result.codes):
        for t in p.templates:
            m = t.regex.match(s)
            if m:
                result.template = t
                result.slots = {k: v for k, v in m.groupdict().items() if v is not None}
                break
        else:
            add(p.finding("RS-PRF-001"))

    t, slots = result.template, result.slots
    if t is not None:
        cond_kw = slots.get("cond_kw", "").lower()
        if cond_kw == "unless":
            add(p.finding("RS-EXT-001"))
        if t.id == "RS-T05b":
            add(p.finding("RS-EXT-002"))
        if t.id == "RS-T07" and cond_kw == "if":
            add(p.finding("RS-ADV-001"))
        if t.id == "RS-T03" and slots.get("restriction_kw", "").lower() in lex["temporal_restriction_words"]:
            add(p.finding("RS-APP-001"))

    if vocabulary is not None and t is not None:
        subject = slots.get("subject", "")
        terms = [v.strip().lower() for v in vocabulary if v.strip()]
        result.term_hits = [v for v in terms if re.search(r"\b" + re.escape(v) + r"s?\b", subject.lower())]
        if not result.term_hits:
            add(p.finding("RS-VOC-001", f'No vocabulary term found in subject "{subject}"'))

    return result
