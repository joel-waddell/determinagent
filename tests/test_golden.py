import importlib.util
import shutil
from pathlib import Path

import pytest
import yaml

from determinagent.conformance import gherkin, rulespeak

ROOT = Path(__file__).parent.parent
BATCHES = sorted((ROOT / "golden" / "v1").glob("*.yaml"))
TASKS = {"rulespeak_generation", "rulespeak_validation", "gherkin_requirements"}


def load(p):
    return yaml.safe_load(p.read_text(encoding="utf-8"))["cases"]


ALL = [c for p in BATCHES for c in load(p)]


def test_ids_are_unique_across_batches():
    ids = [c["id"] for c in ALL]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", ALL, ids=lambda c: c["id"])
def test_case_is_well_formed(case):
    assert case["task"] in TASKS
    assert case["split"] in {"dev", "heldout"}
    assert case["expected"]["route"] == case["task"]
    assert case["label"]["status"] in {"draft", "labelled"}
    register = rulespeak.default_profile().register
    assert set(case["expected"].get("rs_refs", [])) <= set(register)


@pytest.mark.parametrize("case", [c for c in ALL if c["task"] == "rulespeak_generation"], ids=lambda c: c["id"])
def test_generation_references_pass_the_checker(case):
    e = case["expected"]
    assert e["behavior"] in {"draft", "ask"}
    assert e["reference_statements"] or e["behavior"] == "ask"
    for s in e["reference_statements"]:
        assert rulespeak.check(s, case["input"]["vocabulary"]).passed, s


@pytest.mark.parametrize("case", [c for c in ALL if c["task"] == "rulespeak_validation"], ids=lambda c: c["id"])
def test_validation_checker_snapshot_is_current(case):
    r = rulespeak.check(case["input"]["statement"])
    assert case["checker"] == {"profile_acceptance": r.profile_acceptance, "form": r.form, "codes": r.codes}
    assert case["expected"]["form"] in {"conforms", "needs_revision", "undetermined"}


@pytest.mark.parametrize("case", [c for c in ALL if c["task"] == "gherkin_requirements"], ids=lambda c: c["id"])
def test_gherkin_references_pass_the_checker(case):
    e = case["expected"]
    assert e["behavior"] in {"draft", "ask"}
    if e["behavior"] == "draft":
        assert gherkin.check(e["reference_feature"]).conformant


@pytest.mark.skipif(importlib.util.find_spec("openpyxl") is None, reason="openpyxl not installed")
def test_workbook_round_trip(tmp_path):
    from openpyxl import load_workbook

    spec = importlib.util.spec_from_file_location("workbook", ROOT / "tools" / "golden" / "workbook.py")
    wb_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wb_mod)

    batch = tmp_path / "pilot.yaml"
    shutil.copy(ROOT / "golden" / "v1" / "pilot.yaml", batch)
    xlsx = tmp_path / "pilot.xlsx"
    wb_mod.build(batch, xlsx)

    wb = load_workbook(xlsx)
    t2 = wb["T2 Validation"]
    first_yellow = len(wb_mod.SHEETS["rulespeak_validation"][1]) + 1
    t2.cell(2, first_yellow, "Agree")
    t2.cell(3, first_yellow, "Correct")
    t2.cell(3, first_yellow + 1, "undetermined")
    t2.cell(3, first_yellow + 2, "RS-09, RS-13")
    t2.cell(4, first_yellow, "Drop")
    wb.save(xlsx)

    counts = wb_mod.import_labels(batch, xlsx, "tester")
    assert counts["labelled"] == 2 and counts["dropped"] == 1
    cases = {c["id"]: c for c in load(batch)}
    assert cases["T2-P001"]["label"]["status"] == "labelled"
    assert cases["T2-P002"]["expected"]["form"] == "undetermined"
    assert cases["T2-P002"]["expected"]["rs_refs"] == ["RS-09", "RS-13"]
    assert "T2-P003" not in cases
    assert cases["T1-P001"]["label"]["status"] == "draft"
    assert batch.read_text(encoding="utf-8").startswith("# DeterminAgent golden set v1")
