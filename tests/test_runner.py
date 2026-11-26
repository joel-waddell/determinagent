import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from determinagent import contracts, prompts
from determinagent.eval import score_run
from determinagent.eval.__main__ import main
from determinagent.eval.runner import AMBIGUITY, REPLY_SCHEMAS, prepare, run, run_case
from determinagent.models import (
    AnthropicAdapter,
    FakeAdapter,
    ModelError,
    OpenAICompatAdapter,
    from_spec,
    strip_thinking,
)

ROOT = Path(__file__).parent.parent
CASES = yaml.safe_load((ROOT / "golden" / "v1" / "pilot.yaml").read_text(encoding="utf-8"))["cases"]
BY_ID = {c["id"]: c for c in CASES}


def checklist(**open_):
    """An ambiguity checklist with the given items open, quoting the given words."""
    return {k: {"words": open_.get(k, ""), "open": k in open_} for k in AMBIGUITY}


def oracle_reply(case):
    """A model reply that matches the golden expectation."""
    e = case["expected"]
    ask = [{"text": "Which case is meant?", "alternatives": []}]
    if case["task"] == "rulespeak_generation":
        if e["behavior"] == "ask":
            return {
                "ambiguity": checklist(scope=case["input"]["intent"].split()[0]),
                "statements": [],
                "questions": ask,
                "vocabulary_proposals": [],
            }
        trace = [{"claim": "obligation", "rs_refs": ["RS-04"], "application": "must states the requirement"}]
        return {
            "ambiguity": checklist(),
            "statements": [{"text": s, "assumptions": [], "trace": trace} for s in e["reference_statements"]],
            "questions": [],
            "vocabulary_proposals": [
                dict(p, rationale=p.get("rationale", "")) for p in e.get("vocabulary_proposals", [])
            ],
        }
    if case["task"] == "rulespeak_validation":
        return {"form": e["form"], "rationale": "per RS-04", "rs_refs": ["RS-04"], "questions": []}
    if e["behavior"] == "ask":
        return {"feature_name": "", "scenarios": [], "questions": ask}
    n = len(case["input"]["requirement"].get("acceptance_criteria", []))
    parts = feature_parts(e["reference_feature"])
    for sc in parts["scenarios"]:
        sc["criteria"] = list(range(n))
    return dict(parts, questions=[])


def feature_parts(text):
    """The reply parts for a reference feature, read with the official Gherkin parser."""
    from gherkin.parser import Parser

    doc = Parser().parse(text)["feature"]
    scenarios = []
    for child in doc["children"]:
        sc = child["scenario"]
        table = sc["examples"][0] if sc["examples"] else None
        scenarios.append(
            {
                "name": sc["name"],
                "steps": [{"keyword": st["keyword"].strip(), "text": st["text"]} for st in sc["steps"]],
                "examples": {
                    "columns": [c["value"] for c in table["tableHeader"]["cells"]] if table else [],
                    "rows": [[c["value"] for c in r["cells"]] for r in table["tableBody"]] if table else [],
                },
            }
        )
    return {"feature_name": doc["name"], "scenarios": scenarios}


def test_prompts_render_for_every_pilot_case():
    for c in CASES:
        request, _, p = prepare(c)
        assert contracts.validate("request", request) == []
        assert "$" not in p.system.replace("$templates", "") and p.user
        assert p.version == prompts.load(c["task"]).version


def test_prompts_carry_profile_facts():
    p = prompts.render("rulespeak_generation", prepare(BY_ID["T1-P001"])[0])
    assert "RS-T01" in p.system and "need not" in p.system and "RS-17" in p.system
    assert "Every order needs at least one item" in p.user


def test_validation_prompt_includes_checker_evidence():
    _, chk, p = prepare(BY_ID["T2-P001"])
    assert chk is not None and chk.template.id in p.user


def test_oracle_replies_score_perfectly():
    recs = run(CASES, FakeAdapter([oracle_reply(c) for c in CASES]))
    assert all(r["response"]["status"] == "resolved" for r in recs), [
        (r["case_id"], r["response"].get("reason")) for r in recs if r["response"]["status"] != "resolved"
    ]
    m = score_run(CASES, recs).metrics()
    assert m["task_success"] == 1.0 and m["wellformed_first_pass"] == 1.0 and m["violation_rate"] == 0.0


def test_generation_fields_come_from_the_checker():
    rec = run_case(BY_ID["T1-P001"], FakeAdapter([oracle_reply(BY_ID["T1-P001"])]))
    st = rec["response"]["output"]["statements"][0]
    assert st["template_id"] == "RS-T01" and st["guidance_type"] == "rule"


def test_retry_feeds_back_checker_findings_and_recovers():
    case = BY_ID["T1-P001"]
    bad = {
        "ambiguity": checklist(),
        "statements": [{"text": "Orders need items", "assumptions": [], "trace": []}],
        "questions": [],
        "vocabulary_proposals": [],
    }
    fake = FakeAdapter([bad, oracle_reply(case)])
    rec = run_case(case, fake)
    assert rec["response"]["status"] == "resolved"
    assert rec["attempts"] == 2 and rec["first_pass_wellformed"] is False
    feedback = fake.calls[1]["messages"][-1]["content"]
    assert "fails the RuleSpeak checker" in feedback and "trace entry" in feedback
    assert fake.calls[1]["messages"][-2]["role"] == "assistant"


def test_retries_exhausted_is_violated_nonconformant():
    case = BY_ID["T1-P001"]
    bad = {
        "ambiguity": checklist(),
        "statements": [{"text": "Orders need items", "assumptions": [], "trace": []}],
        "questions": [],
        "vocabulary_proposals": [],
    }
    rec = run_case(case, FakeAdapter([bad] * 3), retries=2)
    r = rec["response"]
    assert r["status"] == "violated" and r["reason_code"] == "OUTPUT_NONCONFORMANT"
    assert rec["attempts"] == 3 and contracts.validate("response", r) == []


def test_bad_json_is_schema_invalid():
    rec = run_case(BY_ID["T2-P001"], FakeAdapter(["not json", "{}"]), retries=1)
    assert rec["response"]["reason_code"] == "OUTPUT_SCHEMA_INVALID"


def test_unknown_rs_id_is_rejected():
    case = BY_ID["T2-P001"]
    reply = dict(oracle_reply(case), rs_refs=["RS-4"])
    rec = run_case(case, FakeAdapter([reply]), retries=0)
    assert rec["response"]["status"] == "violated" and "unknown RS id" in rec["response"]["reason"]


def test_gherkin_uncovered_criterion_triggers_retry():
    case = next(c for c in CASES if c["task"] == "gherkin_requirements" and c["expected"]["behavior"] == "draft")
    partial = oracle_reply(case)
    for sc in partial["scenarios"]:
        sc["criteria"] = [0, 99]
    fake = FakeAdapter([partial, oracle_reply(case)])
    rec = run_case(case, fake)
    feedback = fake.calls[1]["messages"][-1]["content"]
    assert rec["attempts"] == 2 and "[1] are not tested" in feedback and "[99] do not exist" in feedback
    covered = rec["response"]["output"]["covered_criteria"]
    assert [c["criterion"] for c in covered] == [0, 1] and covered[0]["scenarios"]


def test_model_error_is_rejected():
    rec = run_case(BY_ID["T2-P001"], FakeAdapter([ModelError("timeout")]))
    assert rec["response"]["status"] == "rejected" and rec["response"]["reason_code"] == "MODEL_ERROR"


def test_cost_cap_stops_the_run():
    class Paid(FakeAdapter):
        def complete(self, *a, **k):
            c = super().complete(*a, **k)
            c.cost_usd = 0.4
            return c

    cases = [c for c in CASES if c["task"] == "rulespeak_validation"]
    recs = run(cases, Paid([oracle_reply(c) for c in cases]), max_cost_usd=1.0)
    assert len(recs) == 3


def test_reply_schemas_are_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])

    for s in REPLY_SCHEMAS.values():
        walk(s)


def test_anthropic_adapter_uses_structured_output_and_fallback():
    seen = {}

    def create(**kw):
        seen.update(kw)
        usage = SimpleNamespace(
            input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="{}")], usage=usage, model=kw["model"]
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    a = AnthropicAdapter(model="claude-sonnet-5-5", client=client)
    c = a.complete("sys", [{"role": "user", "content": "hi"}], {"type": "object"}, "x")
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["fallbacks"] == "default" and seen["betas"] == ["server-side-fallback-2026-07-01"]
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert c.cost_usd == pytest.approx((1000 * 2 + 200 * 10) / 1e6)


def test_anthropic_refusal_is_a_model_error():
    resp = SimpleNamespace(stop_reason="refusal", content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=0))
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp))
    with pytest.raises(ModelError):
        AnthropicAdapter(model="claude-haiku-5-5", client=client).complete("s", [], {}, "x")


def test_openai_compat_request_shape(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
            body["usage"] = {"prompt_tokens": 10, "completion_tokens": 5}
            return json.dumps(body).encode()

    def urlopen(req, timeout):
        sent["url"], sent["body"] = req.full_url, json.loads(req.data)
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    a = OpenAICompatAdapter("http://h/v1", "qwen3:4b", price_in=1.0, price_out=2.0)
    c = a.complete("sys", [{"role": "user", "content": "u"}], {"type": "object"}, "t")
    assert sent["url"] == "http://h/v1/chat/completions"
    assert sent["body"]["response_format"]["json_schema"]["strict"] is True
    assert sent["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert c.cost_usd == pytest.approx(20 / 1e6)


def test_from_spec():
    assert from_spec("ollama:qwen3:4b").name == "ollama:qwen3:4b"
    assert isinstance(from_spec("anthropic:claude-sonnet-5-5"), AnthropicAdapter)
    assert from_spec("openai-compat:m@http://x/v1").base_url == "http://x/v1"
    with pytest.raises(ValueError):
        from_spec("nope")


def test_cli_refuses_paid_run_without_cap(tmp_path, capsys):
    rc = main(["run", str(ROOT / "golden/v1/pilot.yaml"), "--model", "anthropic:claude-sonnet-5-5", "--out", "x"])
    assert rc == 2 and "--max-cost" in capsys.readouterr().err


def test_cli_dry_run(capsys):
    golden = str(ROOT / "golden/v1/pilot.yaml")
    rc = main(["run", golden, "--model", "ollama:x", "--task", "gherkin_requirements", "--dry-run"])
    assert rc == 0 and "20 cases selected" in capsys.readouterr().out


def test_strip_thinking():
    assert strip_thinking('<think>\nhmm\n</think>\n{"a": 1}') == '{"a": 1}'
    assert strip_thinking('{"a": "</think>"}') == '{"a": "</think>"}'


def test_from_spec_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu:11434/v1")
    monkeypatch.setenv("DETERMINAGENT_EXTRA_BODY", '{"reasoning_effort": "none"}')
    a = from_spec("ollama:qwen3:0.6b")
    assert a.base_url == "http://gpu:11434/v1" and a.extra_body == {"reasoning_effort": "none"}


def test_closed_vocabulary_needs_a_proposal():
    case = BY_ID["T1-P002"]
    silent = dict(oracle_reply(case), vocabulary_proposals=[])
    unused = dict(
        oracle_reply(case),
        vocabulary_proposals=oracle_reply(case)["vocabulary_proposals"]
        + [{"term": "carrier", "definition": "A delivery firm.", "rationale": ""}],
    )
    fake = FakeAdapter([silent, unused, oracle_reply(case)])
    rec = run_case(case, fake)
    assert rec["response"]["status"] == "resolved" and rec["attempts"] == 3
    assert "RS-VOC-001" in fake.calls[1]["messages"][-1]["content"]
    assert "'carrier' is not used" in fake.calls[2]["messages"][-1]["content"]
    out = rec["response"]["output"]
    assert out["vocabulary_proposals"][0]["term"] == "shipment"
    assert contracts.validate("response", rec["response"]) == []


def test_feature_is_written_from_its_parts():
    from determinagent.conformance import gherkin
    from determinagent.eval.runner import render_feature

    for c in CASES:
        if c["task"] == "gherkin_requirements" and c["expected"]["behavior"] == "draft":
            text = render_feature(feature_parts(c["expected"]["reference_feature"]))
            assert gherkin.check(text).conformant, text
            assert feature_parts(text) == feature_parts(c["expected"]["reference_feature"])
    assert render_feature({"feature_name": "", "scenarios": []}) == ""
    p = prompts.render("gherkin_requirements", prepare(BY_ID["T3-P001"])[0])
    assert "0: a reset link is emailed" in p.user and "1: the link expires" in p.user


def test_rs_ids_copied_with_their_index_text_are_trimmed():
    case = BY_ID["T2-P001"]
    reply = dict(oracle_reply(case), rs_refs=["RS-04 form: obligation with must"])
    rec = run_case(case, FakeAdapter([reply]), retries=0)
    assert rec["response"]["status"] == "resolved"


def test_template_ids_in_rs_refs_become_the_templates_rs_ids():
    case = BY_ID["T2-P001"]
    reply = dict(oracle_reply(case), rs_refs=["RS-T05 (rule): A loan must be considered ...", "RS-06"])
    rec = run_case(case, FakeAdapter([reply]), retries=0)
    assert rec["response"]["status"] == "resolved"


def test_proposal_alongside_a_question_need_not_be_used():
    case = BY_ID["T1-P012"]
    reply = {
        "ambiguity": checklist(amount="Big"),
        "statements": [],
        "questions": [{"text": "What counts as a big order?", "alternatives": []}],
        "vocabulary_proposals": [
            {"term": "big order", "definition": "An order above a value to agree.", "rationale": ""}
        ],
    }
    rec = run_case(case, FakeAdapter([reply]), retries=0)
    assert rec["response"]["status"] == "resolved"


def test_non_string_rs_refs_get_schema_feedback_not_a_crash():
    case = BY_ID["T2-P001"]
    bad = dict(oracle_reply(case), rs_refs=[{"id": "RS-04"}, ["RS-04"]])
    rec = run_case(case, FakeAdapter([bad, oracle_reply(case)]))
    assert rec["response"]["status"] == "resolved" and rec["attempts"] == 2


def test_an_open_checklist_item_means_ask_not_draft():
    case = BY_ID["T1-P012"]
    drafted = {
        "ambiguity": checklist(amount="Big", scope="extra checks"),
        "statements": [{"text": "Each order must have a customer.", "assumptions": [], "trace": []}],
        "questions": [],
        "vocabulary_proposals": [],
    }
    fake = FakeAdapter([drafted, oracle_reply(case)])
    rec = run_case(case, fake)
    feedback = fake.calls[1]["messages"][-1]["content"]
    assert "amount, scope as open" in feedback and "do not draft" in feedback
    assert rec["response"]["status"] == "resolved" and rec["attempts"] == 2
    assert rec["ambiguity"] == {"scope": "Big"}


def test_an_open_item_must_quote_the_intent():
    case = BY_ID["T1-P012"]
    asked = {
        "ambiguity": checklist(amount="what is an order"),
        "statements": [],
        "questions": [{"text": "What is an order?", "alternatives": []}],
        "vocabulary_proposals": [],
    }
    empty = dict(asked, ambiguity=checklist(amount=""))
    empty["ambiguity"]["amount"]["open"] = True
    fake = FakeAdapter([asked, empty, oracle_reply(case)])
    rec = run_case(case, fake)
    assert "is not in the intent" in fake.calls[1]["messages"][-1]["content"]
    assert "quote the words" in fake.calls[2]["messages"][-1]["content"]
    assert rec["attempts"] == 3


def test_nothing_open_means_draft_not_ask():
    case = BY_ID["T1-P001"]
    asked = {
        "ambiguity": checklist(),
        "statements": [],
        "questions": [{"text": "What is an item?", "alternatives": []}],
        "vocabulary_proposals": [],
    }
    fake = FakeAdapter([asked, oracle_reply(case)])
    rec = run_case(case, fake)
    assert "draft the statements instead of asking" in fake.calls[1]["messages"][-1]["content"]
    assert rec["response"]["status"] == "resolved" and rec["attempts"] == 2
