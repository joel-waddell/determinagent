"""J2 JavaScript generation: golden batch, scoring, runner and prompt (Amendment 1).

Needs the JS sandbox (Node 20+ and npm ci); see tests/test_sandbox.py.
"""

import copy
import importlib.util
import os
from pathlib import Path

import pytest
import yaml

from determinagent import contracts, prompts, sandbox
from determinagent.eval import baselines, score_run
from determinagent.eval.gate import gate
from determinagent.eval.runner import REPLY_SCHEMAS, prepare, run, run_case
from determinagent.eval.score import js_tests
from determinagent.models import FakeAdapter

pytestmark = pytest.mark.skipif(
    not sandbox.available() and not os.environ.get("DETERMINAGENT_REQUIRE_SANDBOX"),
    reason="the JS sandbox needs Node 20+ and npm ci",
)

ROOT = Path(__file__).parent.parent
BATCH = ROOT / "golden" / "v1" / "j2-pilot.yaml"
CASES = yaml.safe_load(BATCH.read_text(encoding="utf-8"))["cases"]
BY_ID = {c["id"]: c for c in CASES}
DRAFT = [c for c in CASES if c["expected"]["behavior"] == "draft"]


def reply_for(case, code=None):
    e = case["expected"]
    if e["behavior"] == "ask" and code is None:
        return {
            "code": "",
            "assumptions": [],
            "questions": [{"text": q, "alternatives": []} for q in e["open_questions"]],
        }
    return {"code": code if code is not None else e["reference_solution"], "assumptions": [], "questions": []}


# --- the golden batch ------------------------------------------------------


def test_batch_shape():
    assert len(CASES) == 27
    assert {c["task"] for c in CASES} == {"js_generation"}
    assert sum(c["expected"]["behavior"] == "ask" for c in CASES) == 9
    for c in CASES:
        if c["label"].get("derived_from"):
            assert c["label"]["derived_from"] in BY_ID
    labels = [c["label"]["status"] for c in CASES]
    assert labels == ["labelled"] * 27
    assert len({c["stratum"] for c in CASES}) >= 10


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_is_well_formed(case):
    e = case["expected"]
    assert e["route"] == "js_generation" and case["split"] in {"dev", "heldout"}
    assert e["behavior"] in {"draft", "ask"}
    assert contracts.validate("js_function_spec", case["input"]["spec"]) == []
    if e["behavior"] == "ask":
        assert e["reference_solution"] is None and e["hidden_tests"] == [] and e["open_questions"]
    else:
        assert len(e["hidden_tests"]) >= 5
        names = [t["name"] for t in js_tests(case)]
        assert len(names) == len(set(names)), "test names are unique"
        m = e["mutation"]
        assert m["score"] >= 0.8 and m["survivors"] == []


def test_references_are_accepted_with_no_findings():
    reports = sandbox.execute_many(
        [{"code": c["expected"]["reference_solution"], "spec": c["input"]["spec"], "tests": js_tests(c)} for c in DRAFT]
    )
    for c, r in zip(DRAFT, reports, strict=True):
        assert sandbox.accepted(r) and r["lint"] == [], (c["id"], r)


def test_hidden_tests_reject_a_wrong_solution():
    case = BY_ID["J2-P025"]
    naive = """export function topWords(text, k) {
  const counts = {}
  for (const w of text.toLowerCase().match(/[a-z]+/g) ?? []) counts[w] = (counts[w] || 0) + 1
  return Object.keys(counts)
    .sort((a, b) => counts[b] - counts[a] || (a < b ? -1 : 1))
    .slice(0, k)
}
"""
    visible = sandbox.execute(naive, spec=case["input"]["spec"], tests=sandbox.tests_from_spec(case["input"]["spec"]))
    assert sandbox.accepted(visible), "the naive solution passes the visible examples"
    hidden = sandbox.execute(naive, spec=case["input"]["spec"], tests=js_tests(case))
    assert not sandbox.accepted(hidden), "but not the hidden tests"


# --- scoring -----------------------------------------------------------------


@pytest.fixture(scope="module")
def oracle():
    return baselines.oracle(CASES)


def test_oracle_scores_perfectly(oracle):
    for r in oracle:
        assert contracts.validate("response", r["response"]) == []
    m = score_run(CASES, oracle).metrics()
    assert m["task_success"] == 1.0 and m["wellformed_final"] == 1.0
    assert m["js_test_pass_rate"] == 1.0 and m["sandbox_violation_rate"] == 0.0
    assert gate(score_run(CASES, oracle))["sandbox_violation_rate"]["met"]


def test_a_violation_fails_the_case_and_the_gate(oracle):
    recs = copy.deepcopy(oracle)
    rec = next(r for r in recs if r["case_id"] == "J2-P020")
    rec["response"]["output"]["module"]["code"] = (
        "export function countVowels(text) {\n"
        "  const key = typeof process\n"
        "  return [...text.toLowerCase()].filter((c) => 'aeiou'.includes(c)).length + (key ? 0 : 0)\n"
        "}\n"
    )
    rep = score_run(CASES, recs)
    s = next(x for x in rep.scores if x.case_id == "J2-P020")
    assert not s.success and s.sandbox_violations == ["process"]
    assert not gate(rep)["sandbox_violation_rate"]["met"]


# J2-P020 policy controls, asked for in the re-check. They live in a fixture so
# tools/golden/j2_policy_controls.py can run and record the same ones.
def test_policy_controls_have_the_expected_outcomes():
    spec = importlib.util.spec_from_file_location("controls", ROOT / "tools" / "golden" / "j2_policy_controls.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.run_controls()
    assert [(r["control"], r["outcome"]) for r in report["results"]] == [
        ("harmless comment about the policy", "pass"),
        ("secret names in a string", "policy violation"),
    ]
    for r in report["results"]:
        assert r["tests_passed"].split("/")[0] == r["tests_passed"].split("/")[1], r


def test_wrong_and_missing_modules_score_partial_credit(oracle):
    recs = copy.deepcopy(oracle)
    wrong = next(r for r in recs if r["case_id"] == "J2-P005")
    wrong["response"]["output"]["module"]["code"] = "export function median(values) {\n  return values[0]\n}\n"
    recs = [r for r in recs if r["case_id"] != "J2-P001"]
    rep = score_run(CASES, recs)
    by = {s.case_id: s for s in rep.scores}
    assert not by["J2-P005"].success and 0 < by["J2-P005"].js_tests_passed < by["J2-P005"].js_tests_total
    assert by["J2-P001"].js_tests_passed == 0 and by["J2-P001"].js_tests_total > 0
    assert rep.metrics()["js_test_pass_rate"] < 1.0


def test_ask_cases_need_questions_not_code(oracle):
    recs = copy.deepcopy(oracle)
    rec = next(r for r in recs if r["case_id"] == "J2-P018")
    rec["response"]["output"] = {"module": {"code": "export const applyDiscount = (p, d) => p - d"}, "questions": []}
    s = next(x for x in score_run(CASES, recs).scores if x.case_id == "J2-P018")
    assert not s.success and "expected a clarifying question" in s.reasons


def test_lint_error_is_not_wellformed(oracle):
    recs = copy.deepcopy(oracle)
    rec = next(r for r in recs if r["case_id"] == "J2-P020")
    rec["response"]["output"]["module"]["code"] = (
        "export function countVowels(text) {\n  return eval('text').match(/[aeiou]/gi)?.length ?? 0\n}\n"
    )
    s = next(x for x in score_run(CASES, recs).scores if x.case_id == "J2-P020")
    assert not s.wellformed and not s.success


# --- the runner and prompt -------------------------------------------------


def test_prompt_renders_with_profile_facts_and_no_hidden_tests():
    for c in CASES:
        request, _, p = prepare(c)
        assert contracts.validate("request", request) == []
        assert p.task == "js_generation" and p.version == "v1/1.0.0"
        assert "$" not in p.system.replace("$js", "")
        assert set(request["payload"]) == {"spec"} and request["payload"]["spec"] == c["input"]["spec"]
    _, _, p = prepare(BY_ID["J2-P001"])
    assert "export function slugify" in p.system and "process" in p.system and "ES2023" in p.system
    assert "slugify" in p.user and "Hello World" in p.user


def test_oracle_replies_resolve_first_time():
    recs = run(CASES, FakeAdapter([reply_for(c) for c in CASES]))
    assert all(r["response"]["status"] == "resolved" for r in recs), [
        (r["case_id"], r["response"].get("reason")) for r in recs if r["response"]["status"] != "resolved"
    ]
    out = next(r for r in recs if r["case_id"] == "J2-P001")["response"]["output"]
    assert out["module"]["filename"] == "slugify.js" and sandbox.accepted(out["execution"])
    names = {t["name"] for t in out["execution"]["tests"]}
    assert names == {"example 1", "example 2", "example 3"}, "the runner runs only the visible examples"
    m = score_run(CASES, recs).metrics()
    assert m["task_success"] == 1.0 and m["wellformed_first_pass"] == 1.0


def test_failing_example_is_fed_back_and_hidden_tests_are_not():
    case = BY_ID["J2-P001"]
    bad = reply_for(case, "export function slugify(title) {\n  return title.toLowerCase().replaceAll(' ', '-')\n}\n")
    fake = FakeAdapter([bad, reply_for(case)])
    rec = run_case(case, fake)
    assert rec["response"]["status"] == "resolved" and rec["attempts"] == 2
    feedback = fake.calls[1]["messages"][-1]["content"]
    assert "example 2 fail" in feedback
    for t in case["expected"]["hidden_tests"]:
        assert t["name"] not in feedback


def test_lint_errors_and_violations_are_fed_back():
    case = BY_ID["J2-P020"]
    bad = reply_for(case, "export function countVowels(text) {\n  return process.env.API_KEY.length + text.length\n}\n")
    rec = run_case(case, FakeAdapter([bad] * 3), retries=2)
    r = rec["response"]
    assert r["status"] == "violated" and r["reason_code"] == "OUTPUT_NONCONFORMANT"
    assert "JS-SEC-002" in r["reason"] and "process attempt" in r["reason"]
    assert contracts.validate("response", r) == []


def test_reply_with_neither_code_nor_questions_is_retried():
    case = BY_ID["J2-P018"]
    fake = FakeAdapter([{"code": "", "assumptions": [], "questions": []}, reply_for(case)])
    rec = run_case(case, fake)
    assert rec["attempts"] == 2 and rec["response"]["status"] == "resolved"
    assert "module" not in rec["response"]["output"]


def test_reply_schema_is_strict():
    s = REPLY_SCHEMAS["js_generation"]
    assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
    assert "js_generation" in prompts.TASKS
