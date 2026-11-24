import copy
from pathlib import Path

import pytest
import yaml

from determinagent import contracts
from determinagent.eval import baselines, compare, gate, score_run
from determinagent.eval.gate import load_config, mcnemar_exact

ROOT = Path(__file__).parent.parent
CASES = yaml.safe_load((ROOT / "golden" / "v1" / "pilot.yaml").read_text(encoding="utf-8"))["cases"]


@pytest.fixture(scope="module")
def oracle():
    return baselines.oracle(CASES)


def test_oracle_records_are_valid_responses(oracle):
    for r in oracle:
        assert contracts.validate("response", r["response"]) == [], r["case_id"]


def test_oracle_scores_perfectly(oracle):
    m = score_run(CASES, oracle).metrics()
    assert m["cases"] == 60
    for k in ("routing_accuracy", "wellformed_final", "task_success", "validation_precision", "validation_recall"):
        assert m[k] == 1.0, k
    assert m["violation_rate"] == 0.0


def test_missing_record_is_a_failure(oracle):
    rep = score_run(CASES, oracle[1:])
    s = next(x for x in rep.scores if x.case_id == oracle[0]["case_id"])
    assert not s.success and s.reasons == ["no record in run"]


def test_misrouted_and_invalid_responses_fail(oracle):
    recs = copy.deepcopy(oracle)
    recs[0]["response"]["route"]["target"] = "gherkin_requirements"
    recs[1]["response"]["status"] = "maybe"
    rep = score_run(CASES, recs)
    s0, s1 = rep.scores[0], rep.scores[1]
    assert not s0.routed_correctly and not s0.success
    assert not s1.contract_valid and not s1.success
    assert rep.metrics()["routing_accuracy"] == pytest.approx(58 / 60)


def test_violated_status_counts_toward_violation_rate(oracle):
    recs = copy.deepcopy(oracle)
    r = recs[0]["response"]
    r.update(status="violated", reason_code="OUTPUT_NONCONFORMANT")
    r.pop("output")
    assert score_run(CASES, recs).metrics()["violation_rate"] == pytest.approx(1 / 60)


def test_generation_statement_failing_the_checker_is_not_wellformed(oracle):
    recs = copy.deepcopy(oracle)
    i = next(i for i, c in enumerate(CASES) if c["id"] == "T1-P001")
    recs[i]["response"]["output"]["statements"][0]["text"] = "Orders should have items."
    s = score_run(CASES, recs).scores[i]
    assert not s.wellformed and not s.success


def test_gherkin_uncovered_criterion_fails(oracle):
    recs = copy.deepcopy(oracle)
    i = next(i for i, c in enumerate(CASES) if c["id"] == "T3-P001")
    recs[i]["response"]["output"]["covered_criteria"] = recs[i]["response"]["output"]["covered_criteria"][:1]
    s = score_run(CASES, recs).scores[i]
    assert s.wellformed and not s.success


def test_checker_baseline_runs_and_is_imperfect():
    recs = baselines.checker(CASES)
    rep = score_run(CASES, recs).subset(task="rulespeak_validation")
    m = rep.metrics()
    assert m["cases"] == 20 and m["routing_accuracy"] == 1.0
    assert 0 < m["task_success"] < 1


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 10) == pytest.approx(2 / 1024)


def test_compare_verdicts(oracle):
    base = score_run(CASES, oracle, "base")
    assert compare(base, score_run(CASES, oracle, "same"))["verdict"] == "pass"

    worse = copy.deepcopy(oracle)
    worse[0]["response"]["route"]["target"] = "gherkin_requirements"  # routing has zero tolerance
    res = compare(base, score_run(CASES, worse, "worse"))
    assert res["metrics"]["routing_accuracy"]["verdict"] == "fail"
    assert res["verdict"] == "fail"
    assert res["task_success_pairs"]["lost"] == 1


def test_small_task_success_drop_is_review_not_fail(oracle):
    cfg = load_config()
    cfg["metrics"] = {"task_success": cfg["metrics"]["task_success"]}
    base = score_run(CASES, oracle, "base")
    recs = copy.deepcopy(oracle)
    i = next(i for i, c in enumerate(CASES) if c["id"] == "T2-P001")
    recs[i]["response"]["output"]["results"][0]["form"] = "needs_revision"  # 1/60 = 1.7 points
    res = compare(base, score_run(CASES, recs, "cand"), cfg)
    assert res["metrics"]["task_success"]["verdict"] == "review"


def test_gate_reports_targets(oracle):
    g = gate(score_run(CASES, oracle))
    assert g["routing_accuracy"]["met"] and g["task_success"]["met"]
