"""Run a model over golden cases and write an eval run (Phase 0.4).

For each case the runner builds the v1 request, renders the task prompt, asks
the adapter for a schema-constrained reply and validates it. Validation is
deterministic: the reply must match the task's reply schema, and what it
claims must pass the same checkers the scorer uses (RuleSpeak for generated
statements, the Gherkin profile and criterion coverage for features). A
failing reply is sent back with the checker's findings, up to ``retries``
times. The model never decides anything a checker can decide:

* generation: ``guidance_type`` and ``template_id`` come from the checker;
* validation: the checker runs first, its findings are the evidence in the
  prompt and the findings in the output; the model settles only the form
  verdict;
* Gherkin: conformance is the profile's verdict, not the model's.

Records follow docs/evaluation.md, so ``score`` and ``compare`` read them.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

import jsonschema

from .. import contracts, prompts
from ..conformance import gherkin, rulespeak
from ..golden import to_request
from ..models import Adapter, ModelError
from .baselines import TS, _route

_STR_LIST = {"type": "array", "items": {"type": "string"}}
_QUESTIONS = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "alternatives"],
        "properties": {"text": {"type": "string"}, "alternatives": _STR_LIST},
    },
}

# What the model is asked to return. Smaller than the v1 output contract:
# fields a checker can fill are left out, and every field is required so
# strict constrained decoding accepts the schema.
REPLY_SCHEMAS: dict[str, dict[str, Any]] = {
    "rulespeak_generation": {
        "type": "object",
        "additionalProperties": False,
        "required": ["statements", "questions"],
        "properties": {
            "statements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "assumptions", "trace"],
                    "properties": {
                        "text": {"type": "string"},
                        "assumptions": _STR_LIST,
                        "trace": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["claim", "rs_refs", "application"],
                                "properties": {
                                    "claim": {"type": "string"},
                                    "rs_refs": _STR_LIST,
                                    "application": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "questions": _QUESTIONS,
        },
    },
    "rulespeak_validation": {
        "type": "object",
        "additionalProperties": False,
        "required": ["form", "rationale", "rs_refs", "questions"],
        "properties": {
            "form": {"type": "string", "enum": ["conforms", "needs_revision", "undetermined"]},
            "rationale": {"type": "string"},
            "rs_refs": _STR_LIST,
            "questions": _QUESTIONS,
        },
    },
    "gherkin_requirements": {
        "type": "object",
        "additionalProperties": False,
        "required": ["feature", "covered_criteria", "questions"],
        "properties": {
            "feature": {"type": "string", "description": "The Gherkin document, or an empty string when asking."},
            "covered_criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["criterion", "scenarios"],
                    "properties": {"criterion": {"type": "integer"}, "scenarios": _STR_LIST},
                },
            },
            "questions": _QUESTIONS,
        },
    },
}


def _questions(qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for q in qs:
        item: dict[str, Any] = {"text": q["text"][:500]}
        alts = [a[:500] for a in q.get("alternatives", []) if a][:5]
        if alts:
            item["alternatives"] = alts
        out.append(item)
    return out


def _refs(refs: list[str]) -> list[str]:
    return list(dict.fromkeys(refs))


def _checker_evidence(r: rulespeak.RuleSpeakResult) -> str:
    d = r.to_dict()
    brief = {
        "outcome": d["outcome"],
        "template": None if d["template"] is None else {k: d["template"][k] for k in ("id", "name", "basis")},
        "findings": [{k: f[k] for k in ("code", "title", "kind", "disposition", "rs_refs")} for f in d["findings"]],
    }
    return json.dumps(brief, indent=2)


def _problems(task: str, reply: dict[str, Any], request: dict[str, Any]) -> list[str]:
    """Deterministic checks on a parsed reply. An empty list means accept."""
    pay = request["payload"]
    errs = [e.message for e in jsonschema.Draft202012Validator(REPLY_SCHEMAS[task]).iter_errors(reply)]
    if errs:
        return [f"reply does not match the schema: {m}" for m in errs[:5]]
    bad_refs = {
        ref for st in reply.get("statements", []) for t in st["trace"] for ref in t["rs_refs"] if not _is_rs_ref(ref)
    } | {ref for ref in reply.get("rs_refs", []) if not _is_rs_ref(ref)}
    out = [f"unknown RS id {ref!r}; use ids like RS-04" for ref in sorted(bad_refs)]
    vocab = pay.get("vocabulary")
    if task == "rulespeak_generation":
        stmts, qs = reply["statements"], reply["questions"]
        if not stmts and not qs:
            out.append("return at least one statement or one question")
        for i, st in enumerate(stmts, 1):
            if not st["trace"]:
                out.append(f"statement {i} needs at least one trace entry")
            r = rulespeak.check(st["text"], vocab)
            if r.passed and r.template is None:
                out.append(f"statement {i} matches no template")
            elif not r.passed:
                fs = [f for f in r.findings if f.disposition in ("error", "review")] or r.findings
                why = "; ".join(f"{f.code} {f.title}" for f in fs)
                out.append(f"statement {i} ({st['text']!r}) fails the RuleSpeak checker: {why}")
    elif task == "gherkin_requirements":
        feature, qs = reply["feature"].strip(), reply["questions"]
        if not feature and not qs:
            out.append("return a feature or at least one question")
        if feature:
            res = gherkin.check(feature)
            if not res.conformant:
                why = "; ".join(f"{d.code} {d.message}" for d in res.defects if d.severity == "error")
                out.append(f"the feature fails the Gherkin profile: {why}")
            n = len(pay["requirement"].get("acceptance_criteria", []))
            covered = {c["criterion"] for c in reply["covered_criteria"] if c["scenarios"]}
            missing = sorted(set(range(n)) - covered)
            if missing:
                out.append(f"acceptance criteria {missing} are not covered by any scenario")
    return out


def _is_rs_ref(ref: str) -> bool:
    return len(ref) == 5 and ref.startswith("RS-") and ref[3:].isdigit()


def _output(task: str, reply: dict[str, Any], request: dict[str, Any], chk: rulespeak.RuleSpeakResult | None) -> dict:
    vocab = request["payload"].get("vocabulary")
    if task == "rulespeak_generation":
        statements = []
        for st in reply["statements"]:
            r = rulespeak.check(st["text"], vocab)
            item: dict[str, Any] = {
                "text": st["text"],
                "guidance_type": r.guidance_type,
                "template_id": r.template.id,
                "trace": [
                    {"claim": t["claim"] or "-", "rs_refs": _refs(t["rs_refs"]), "application": t["application"] or "-"}
                    for t in st["trace"]
                ],
            }
            if st["assumptions"]:
                item["assumptions"] = [a[:500] for a in st["assumptions"] if a]
            statements.append(item)
        return {"statements": statements, "questions": _questions(reply["questions"])}
    if task == "rulespeak_validation":
        result: dict[str, Any] = {
            "statement_id": request["payload"]["statements"][0]["id"],
            "form": reply["form"],
            "fidelity": "unverified",
            "findings": chk.to_dict()["findings"] if chk else [],
        }
        if reply["questions"]:
            result["questions"] = _questions(reply["questions"])
        return {"results": [result]}
    out: dict[str, Any] = {
        "covered_criteria": [c for c in reply["covered_criteria"] if c["criterion"] >= 0],
        "questions": _questions(reply["questions"]),
    }
    if reply["feature"].strip():
        out["feature"] = reply["feature"]
    return out


def _parse(task: str, text: str, request: dict[str, Any]) -> tuple[Any, list[str], str]:
    """Parse and check one reply: (reply, problems, reason code if it fails)."""
    try:
        reply = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [f"the reply is not valid JSON: {e}"], "OUTPUT_SCHEMA_INVALID"
    if not isinstance(reply, dict):
        return reply, ["the reply is not a JSON object"], "OUTPUT_SCHEMA_INVALID"
    problems = _problems(task, reply, request)
    schema_bad = bool(problems) and problems[0].startswith("reply does not match")
    return reply, problems, "OUTPUT_SCHEMA_INVALID" if schema_bad else "OUTPUT_NONCONFORMANT"


def _response(
    case: dict[str, Any], status: str, output: dict | None = None, code: str | None = None, why: str = ""
) -> dict[str, Any]:
    resp: dict[str, Any] = {
        "schema_version": "1.0",
        "request_id": case["id"],
        "task": case["task"],
        "status": status,
        "route": _route(case["task"]),
        "completed_at": TS,
    }
    if status == "resolved":
        resp["output"] = output
    else:
        resp["reason_code"] = code
        resp["reason"] = why[:2000]
    return resp


def prepare(case: dict[str, Any]) -> tuple[dict[str, Any], rulespeak.RuleSpeakResult | None, prompts.Prompt]:
    """The request, the checker result (validation only) and the rendered prompt for a case."""
    request = to_request(case)
    chk = extra = None
    if case["task"] == "rulespeak_validation":
        pay = request["payload"]
        chk = rulespeak.check(pay["statements"][0]["text"], pay.get("vocabulary"))
        extra = {"checker": _checker_evidence(chk)}
    return request, chk, prompts.render(case["task"], request, extra)


def run_case(case: dict[str, Any], adapter: Adapter, *, retries: int = 2) -> dict[str, Any]:
    task = case["task"]
    request, chk, prompt = prepare(case)
    messages = [{"role": "user", "content": prompt.user}]
    record: dict[str, Any] = {
        "case_id": case["id"],
        "system": adapter.name,
        "prompt_version": prompt.version,
        "routing_latency_ms": 0.0,
        "latency_ms": 0.0,
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "attempts": 0,
        "first_pass_wellformed": False,
    }
    problems: list[str] = []
    code = "OUTPUT_NONCONFORMANT"
    for attempt in range(retries + 1):
        record["attempts"] = attempt + 1
        t0 = time.perf_counter()
        try:
            c = adapter.complete(prompt.system, messages, REPLY_SCHEMAS[task], task)
        except ModelError as e:
            record["latency_ms"] += (time.perf_counter() - t0) * 1000
            record["response"] = _response(case, "rejected", code="MODEL_ERROR", why=str(e))
            return record
        record["latency_ms"] += c.latency_ms if c.latency_ms is not None else (time.perf_counter() - t0) * 1000
        if c.cost_usd is None or record["cost_usd"] is None:
            record["cost_usd"] = None
        else:
            record["cost_usd"] += c.cost_usd
        record["input_tokens"] += c.input_tokens
        record["output_tokens"] += c.output_tokens
        reply, problems, code = _parse(task, c.text, request)
        if not problems:
            record["first_pass_wellformed"] = attempt == 0
            resp = _response(case, "resolved", _output(task, reply, request, chk))
            errs = contracts.validate("response", resp)
            if errs:
                resp = _response(case, "violated", code="OUTPUT_SCHEMA_INVALID", why="; ".join(map(str, errs[:3])))
            record["response"] = resp
            return record
        messages += [
            {"role": "assistant", "content": c.text},
            {
                "role": "user",
                "content": "Your reply was checked and has these problems:\n- "
                + "\n- ".join(problems)
                + "\nReply again with corrected JSON only.",
            },
        ]
    record["problems"] = problems
    record["response"] = _response(case, "violated", code=code, why="; ".join(problems))
    return record


def run(
    cases: Iterable[dict[str, Any]],
    adapter: Adapter,
    *,
    retries: int = 2,
    max_cost_usd: float | None = None,
) -> list[dict[str, Any]]:
    """Run every case. Stops before the next case once ``max_cost_usd`` is spent."""
    records, spent = [], 0.0
    for case in cases:
        if max_cost_usd is not None and spent >= max_cost_usd:
            break
        rec = run_case(case, adapter, retries=retries)
        spent += rec.get("cost_usd") or 0.0
        records.append(rec)
    return records
