import re
from pathlib import Path

import pytest
import yaml

from determinagent.conformance import rulespeak

FIXTURES = yaml.safe_load((Path(__file__).parent / "fixtures" / "rulespeak_cases.yaml").read_text(encoding="utf-8"))
PROFILE = rulespeak.default_profile()
OUTCOME_KEYS = ("profile_acceptance", "form", "guidance_type", "review_required", "local_policy")


def assert_checker(case, result):
    d = result.to_dict()
    want = case["checker"]
    for k in OUTCOME_KEYS:
        if k in want:
            assert d["outcome"][k] == want[k], (k, d)
    if "template" in want:
        assert (d["template"] or {}).get("id") == want["template"], d
    if "term_hits" in want:
        assert d["term_hits"] == want["term_hits"], d
    assert sorted(result.codes) == sorted(want["codes"]), d


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda c: c["id"])
def test_cases(case):
    assert_checker(case, rulespeak.check(case["text"]))


@pytest.mark.parametrize("case", FIXTURES["vocabulary_cases"], ids=lambda c: c["id"])
def test_vocabulary_cases(case):
    assert_checker(case, rulespeak.check(case["text"], case["vocabulary"]))


def test_fixture_labels_are_well_formed():
    ids = [c["id"] for c in FIXTURES["cases"]]
    assert len(ids) == len(set(ids))
    for c in FIXTURES["cases"]:
        assert c["rulespeak"]["form"] in {"conforms", "needs_revision", "undetermined"}
        assert c["reason"]
        assert set(c["rulespeak"]["rs_refs"]) <= set(PROFILE.register), c["id"]


def test_every_cited_rs_id_exists_and_reaches_a_locator():
    items = [*PROFILE.diagnostics.values(), *({"rs_refs": t.rs_refs} for t in PROFILE.templates)]
    for item in items:
        for ref in item["rs_refs"]:
            assert re.fullmatch(r"RS-\d\d", ref)
            assert PROFILE.register[ref]["source"], ref


def test_every_template_and_diagnostic_has_a_basis():
    for t in PROFILE.templates:
        assert t.basis in {"sourced", "inferred", "local"}, t.id
        assert t.basis == "local" or t.rs_refs, t.id
    for code, d in PROFILE.diagnostics.items():
        assert d["basis"] in {"sourced", "inferred", "local"}, code
        assert d["kind"] in {"form", "meaning", "style", "principle", "application", "profile", "local"}, code
        assert d["disposition"] in {"error", "review", "warning", "info"}, code
        assert d["basis"] == "local" or d["rs_refs"], code


def test_every_diagnostic_is_exercised():
    seen = {code for c in FIXTURES["cases"] + FIXTURES["vocabulary_cases"] for code in c["checker"]["codes"]}
    assert set(PROFILE.diagnostics) - seen == {"RS-LOC-001"}  # covered by test_word_limit_is_local


def test_template_examples_match_their_own_template():
    for t in PROFILE.templates:
        r = rulespeak.check(t.example)
        assert r.template is not None and r.template.id == t.id, (t.id, r.to_dict())
        assert r.profile_acceptance == "accepted"


def test_findings_carry_the_evidence_chain():
    f = rulespeak.check("A visitor may enter the archive if accompanied by a curator.").findings[0]
    assert f.code == "RS-ADV-001"
    assert f.rs_refs == ("RS-10",)
    assert "SF Table 2 forms 4.1–4.2, p. 10" in f.source


def test_slots_and_quantifier_are_preserved():
    r = rulespeak.check("Every employee must complete safety training.")
    assert r.slots["det"] == "Every"
    r = rulespeak.check("An order must not be shipped if the outstanding balance exceeds the credit limit.")
    assert r.slots == {
        "det": "An",
        "subject": "order",
        "predicate": "be shipped",
        "cond_kw": "if",
        "condition": "the outstanding balance exceeds the credit limit",
    }


def test_word_limit_is_local():
    r = rulespeak.check("A customer must " + " ".join(["provide"] + ["a document"] * 25) + ".")
    assert r.codes == ["RS-LOC-001"]
    assert r.passed and r.local_policy == "pass"


def test_fidelity_is_always_unverified():
    assert rulespeak.check("Each order must have a customer.").to_dict()["outcome"]["fidelity"] == "unverified"


def test_deterministic():
    text = "A supplier may submit an invoice only after the buyer issues the purchase order for the invoice."
    assert rulespeak.check(text).to_dict() == rulespeak.check(text).to_dict()
