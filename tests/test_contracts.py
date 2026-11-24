import json
from pathlib import Path

import pytest
import yaml

from determinagent import contracts, golden

ROOT = Path(__file__).parent.parent
CASES = yaml.safe_load((ROOT / "tests" / "fixtures" / "contracts.yaml").read_text(encoding="utf-8"))["cases"]
GOLDEN = [c for p in sorted((ROOT / "golden" / "v1").glob("*.yaml")) for c in yaml.safe_load(p.read_text())["cases"]]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_examples(case):
    errors = contracts.validate(case["contract"], case["doc"])
    assert (errors == []) == case["valid"], errors


def test_schemas_are_valid_2020_12():
    from jsonschema import Draft202012Validator

    for name in contracts.SCHEMAS:
        Draft202012Validator.check_schema(contracts.schema(name))


def test_schema_ids_match_file_names():
    for name in contracts.SCHEMAS:
        assert contracts.schema(name)["$id"] == f"urn:determinagent:contracts:v1:{name}"


def test_statement_length_limit():
    doc = {"statements": [{"id": "s1", "text": "A" * 501}]}
    assert contracts.validate("rulespeak_validation_input", doc)
    doc["statements"][0]["text"] = "A" * 500
    assert contracts.validate("rulespeak_validation_input", doc) == []


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["id"])
def test_every_golden_case_is_a_valid_request(case):
    assert contracts.validate("request", golden.to_request(case)) == []


def test_checker_findings_fit_the_finding_contract():
    from determinagent.conformance import rulespeak

    for text in ("A visitor may enter the archive if accompanied by a curator.", "Customers must register."):
        for f in rulespeak.check(text).to_dict()["findings"]:
            assert contracts.validate("finding", f) == [], f


def test_contract_files_are_canonical_json():
    for p in (ROOT / "src" / "determinagent" / "contracts" / "v1").glob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))
