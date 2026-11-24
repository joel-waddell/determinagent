import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from determinagent import contracts, prompts
from determinagent.eval import score_run
from determinagent.eval.__main__ import main
from determinagent.eval.runner import REPLY_SCHEMAS, prepare, run, run_case
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


def oracle_reply(case):
    """A model reply that matches the golden expectation."""
    e = case["expected"]
    ask = [{"text": "Which case is meant?", "alternatives": []}]
    if case["task"] == "rulespeak_generation":
        if e["behavior"] == "ask":
            return {"statements": [], "questions": ask, "vocabulary_proposals": []}
        trace = [{"claim": "obligation", "rs_refs": ["RS-04"], "application": "must states the requirement"}]
        return {
            "statements": [{"text": s, "assumptions": [], "trace": trace} for s in e["reference_statements"]],
            "questions": [],
            "vocabulary_proposals": [
                dict(p, rationale=p.get("rationale", "")) for p in e.get("vocabulary_proposals", [])
            ],
        }
    if case["task"] == "rulespeak_validation":
        return {"form": e["form"], "rationale": "per RS-04", "rs_refs": ["RS-04"], "questions": []}
    if e["behavior"] == "ask":
        return {"feature": "", "covered_criteria": [], "questions": ask}
    n = len(case["input"]["requirement"].get("acceptance_criteria", []))
    return {
        "feature": e["reference_feature"],
        "covered_criteria": [{"criterion": i, "scenarios": ["reference"]} for i in range(n)],
        "questions": [],
    }


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
    partial = dict(oracle_reply(case), covered_criteria=[])
    fake = FakeAdapter([partial, oracle_reply(case)])
    rec = run_case(case, fake)
    assert rec["attempts"] == 2 and "not covered" in fake.calls[1]["messages"][-1]["content"]


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
