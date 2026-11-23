from pathlib import Path

import pytest
import yaml

from determinagent.conformance import rulespeak

CASES = yaml.safe_load((Path(__file__).parent / "fixtures" / "rulespeak_cases.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["conformant"], ids=lambda c: c["text"][:50])
def test_conformant(case):
    r = rulespeak.check(case["text"])
    assert r.conformant, r.to_dict()
    assert r.template_id == case["template"]


@pytest.mark.parametrize("case", CASES["warnings"], ids=lambda c: c["text"][:50])
def test_warnings(case):
    r = rulespeak.check(case["text"])
    assert r.conformant and r.template_id == case["template"]
    assert sorted(r.codes) == sorted(case["codes"]), r.to_dict()


@pytest.mark.parametrize("case", CASES["defective"], ids=lambda c: c["text"][:50] or "empty")
def test_defective(case):
    r = rulespeak.check(case["text"])
    assert not r.conformant
    assert sorted(r.codes) == sorted(case["codes"]), r.to_dict()


def test_every_defect_code_is_documented_and_tested():
    profile = rulespeak.default_profile()
    tested = {c for case in CASES["defective"] + CASES["warnings"] for c in case["codes"]}
    untested = set(profile.defects) - tested - {"RS-STY-004", "RS-VOC-001"}  # covered below
    assert not untested


def test_template_examples_match_their_own_template():
    for t in rulespeak.default_profile().templates:
        r = rulespeak.check(t.example)
        assert r.conformant and r.template_id == t.id, (t.id, r.to_dict())


def test_slots_are_extracted():
    r = rulespeak.check("An order must not be shipped if the outstanding balance exceeds the credit limit.")
    assert r.slots["subject"] == "order"
    assert r.slots["predicate"] == "be shipped"
    assert r.slots["cond_kw"] == "if"
    assert r.slots["condition"] == "the outstanding balance exceeds the credit limit"


def test_vocabulary_check():
    vocab = ["order", "customer", "line item"]
    assert rulespeak.check("Each order must have at least one line item.", vocab).conformant
    r = rulespeak.check("Each shipment must have a carrier.", vocab)
    assert r.codes == ["RS-VOC-001"]


def test_long_statement_is_a_warning_only():
    text = "A customer must " + " ".join(["provide"] + ["a document"] * 25) + "."
    r = rulespeak.check(text)
    assert "RS-STY-004" in r.codes
    assert r.conformant


def test_deterministic():
    text = "A refund may be issued only if the purchase was made within the last 30 days."
    assert rulespeak.check(text).to_dict() == rulespeak.check(text).to_dict()
