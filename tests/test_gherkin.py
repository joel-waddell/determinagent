from pathlib import Path

import pytest
import yaml

from determinagent.conformance import gherkin

CASES = yaml.safe_load((Path(__file__).parent / "fixtures" / "gherkin_cases.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["conformant"])
def test_conformant_feature(case):
    r = gherkin.check(case["source"])
    assert r.conformant and r.defects == [], r.to_dict()


@pytest.mark.parametrize("case", CASES["errors"], ids=lambda c: ",".join(c["codes"]))
def test_errors(case):
    r = gherkin.check(case["source"])
    assert not r.conformant
    assert sorted(r.codes) == sorted(case["codes"]), r.to_dict()


@pytest.mark.parametrize("case", CASES["warnings"], ids=lambda c: ",".join(c["codes"]))
def test_warnings(case):
    r = gherkin.check(case["source"])
    assert r.conformant, r.to_dict()
    assert sorted(r.codes) == sorted(case["codes"]), r.to_dict()


def test_parse_error_has_location():
    r = gherkin.check("Feature: f\n  Scenario: s\n    Given a\nFeature: g\n")
    assert r.codes and r.codes[0] == "GK-PARSE-001"
    assert r.defects[0].line is not None


def test_every_defect_code_is_documented():
    codes = set(gherkin.default_profile().defects)
    assert all(c.startswith("GK-") for c in codes)
