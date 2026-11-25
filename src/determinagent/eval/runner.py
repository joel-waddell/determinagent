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
* JavaScript (J2): the module is linted and run in the 0.8 sandbox against
  the spec's visible examples. Lint errors, failing examples and violations
  are the retry feedback. Hidden tests are never run here, so nothing about
  them reaches the model; the scorer runs them.

Records follow docs/evaluation.md, so ``score`` and ``compare`` read them.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable
from typing import Any

import jsonschema

from .. import contracts, prompts, sandbox
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
        "required": ["statements", "questions", "vocabulary_proposals"],
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
            "vocabulary_proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["term", "definition", "rationale"],
                    "properties": {
                        "term": {"type": "string"},
                        "definition": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                },
            },
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
    # The model fills in the parts of the feature; the runner writes the Gherkin
    # text, so keywords, indentation and tables are right by construction.
    "gherkin_requirements": {
        "type": "object",
        "additionalProperties": False,
        "required": ["feature_name", "scenarios", "questions"],
        "properties": {
            "feature_name": {"type": "string", "description": "The feature's name, or an empty string when asking."},
            "scenarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "criteria", "steps", "examples"],
                    "properties": {
                        "name": {"type": "string"},
                        "criteria": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Numbers of the acceptance criteria this scenario tests, from 0.",
                        },
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["keyword", "text"],
                                "properties": {
                                    "keyword": {"enum": ["Given", "When", "Then", "And", "But"]},
                                    "text": {"type": "string"},
                                },
                            },
                        },
                        "examples": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["columns", "rows"],
                            "description": "Only for a Scenario Outline; otherwise no columns and no rows.",
                            "properties": {
                                "columns": _STR_LIST,
                                "rows": {"type": "array", "items": _STR_LIST},
                            },
                        },
                    },
                },
            },
            "questions": _QUESTIONS,
        },
    },
    "js_generation": {
        "type": "object",
        "additionalProperties": False,
        "required": ["code", "assumptions", "questions"],
        "properties": {
            "code": {"type": "string", "description": "The whole ES module, or an empty string when asking."},
            "assumptions": _STR_LIST,
            "questions": _QUESTIONS,
        },
    },
}

# Visible-example reports, keyed by (code, spec), so a reply is run once.
_JS_REPORTS: dict[tuple[str, str], dict[str, Any]] = {}


def _visible_report(code: str, spec: dict[str, Any]) -> dict[str, Any]:
    key = (code, json.dumps(spec, sort_keys=True))
    if key not in _JS_REPORTS:
        if len(_JS_REPORTS) > 256:
            _JS_REPORTS.clear()
        _JS_REPORTS[key] = sandbox.execute(code, spec=spec, tests=sandbox.tests_from_spec(spec))
    return _JS_REPORTS[key]


def _js_problems(report: dict[str, Any]) -> list[str]:
    out = []
    if not report["parsed"]:
        f = report["lint"][0] if report["lint"] else None
        where = f" (line {f['range']['start_line']}: {f['message']})" if f else ""
        return [f"the module does not parse{where}"]
    for f in sandbox.lint_errors(report):
        out.append(f"line {f['range']['start_line']}: {f['code']} {f['message']}")
    for t in report["tests"]:
        if t["status"] != "pass":
            out.append(f"{t['name']} {t['status']}: {t.get('message', '')}".rstrip(": "))
    for v in report["violations"]:
        out.append(f"the sandbox blocked a {v} attempt; use only the ECMAScript built-ins")
    return out


def _module(code: str, spec: dict[str, Any]) -> dict[str, Any]:
    stem = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in spec["name"])[:61] or "module"
    return {"code": code, "filename": f"{stem}.js"}


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
        proposed = _proposed(reply)
        agreed = {v.strip().lower() for v in vocab or ()}
        for term in sorted(proposed & agreed):
            out.append(f"{term!r} is already in the vocabulary; do not propose it")
        for p in reply["vocabulary_proposals"]:
            if not p["term"].strip() or not p["definition"].strip():
                out.append("each vocabulary proposal needs a term and a one-line definition")
        texts = " ".join(st["text"].lower() for st in stmts)
        # A proposal that comes with questions and no statements is part of
        # agreeing the vocabulary, so it need not be used yet.
        for term in sorted(proposed - agreed) if stmts else []:
            if not re.search(r"\b" + re.escape(term) + r"s?\b", texts):
                out.append(f"the proposed term {term!r} is not used in any statement; drop it or use it")
        for i, st in enumerate(stmts, 1):
            if not st["trace"]:
                out.append(f"statement {i} needs at least one trace entry")
            r = rulespeak.check(st["text"], vocab, proposed=sorted(proposed))
            if r.passed and r.template is None:
                out.append(f"statement {i} matches no template")
            elif not r.passed:
                fs = [f for f in r.findings if f.disposition in ("error", "review")] or r.findings
                why = "; ".join(f"{f.code} {f.title}" for f in fs)
                out.append(f"statement {i} ({st['text']!r}) fails the RuleSpeak checker: {why}")
    elif task == "gherkin_requirements":
        feature, qs = render_feature(reply), reply["questions"]
        if not feature and not qs:
            out.append("return a feature or at least one question")
        if feature:
            res = gherkin.check(feature)
            if not res.conformant:
                why = "; ".join(f"{d.code} {d.message}" for d in res.defects if d.severity == "error")
                out.append(f"the feature fails the Gherkin profile: {why}")
            n = len(pay["requirement"].get("acceptance_criteria", []))
            covered = {c["criterion"] for c in _covered(reply, n)}
            missing = sorted(set(range(n)) - covered)
            if missing:
                out.append(
                    f"acceptance criteria {missing} are not tested by any scenario; add scenarios for them, "
                    "and list in each scenario's criteria the numbers (from 0) of the criteria it tests"
                )
            bad = sorted({i for sc in reply["scenarios"] for i in sc["criteria"] if not 0 <= i < n})
            if bad:
                out.append(f"criteria numbers {bad} do not exist; the criteria are numbered 0 to {n - 1}")
    elif task == "js_generation":
        code, qs = reply["code"].strip(), reply["questions"]
        if not code and not qs:
            out.append("return a module or at least one question")
        if len(reply["code"]) > 20000:
            out.append("the module is longer than 20,000 characters")
        elif code:
            out += _js_problems(_visible_report(reply["code"], pay["spec"]))
    return out


def _proposed(reply: dict[str, Any]) -> set[str]:
    return {p["term"].strip().lower() for p in reply.get("vocabulary_proposals", []) if p["term"].strip()}


def _is_rs_ref(ref: str) -> bool:
    return len(ref) == 5 and ref.startswith("RS-") and ref[3:].isdigit()


def _output(task: str, reply: dict[str, Any], request: dict[str, Any], chk: rulespeak.RuleSpeakResult | None) -> dict:
    vocab = request["payload"].get("vocabulary")
    if task == "rulespeak_generation":
        statements = []
        proposed = sorted(_proposed(reply))
        for st in reply["statements"]:
            r = rulespeak.check(st["text"], vocab, proposed=proposed)
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
        out: dict[str, Any] = {"statements": statements, "questions": _questions(reply["questions"])}
        proposals = []
        for p in reply["vocabulary_proposals"]:
            item = {"term": p["term"].strip()[:80], "definition": p["definition"].strip()[:500]}
            if p["rationale"].strip():
                item["rationale"] = p["rationale"].strip()[:500]
            proposals.append(item)
        if proposals:
            out["vocabulary_proposals"] = proposals[:20]
        return out
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
    if task == "js_generation":
        spec = request["payload"]["spec"]
        js: dict[str, Any] = {"questions": _questions(reply["questions"])}
        if reply["code"].strip():
            js["module"] = _module(reply["code"], spec)
            js["execution"] = _visible_report(reply["code"], spec)
        assumptions = [a[:500] for a in reply["assumptions"] if a]
        if assumptions:
            js["assumptions"] = assumptions
        return js
    n = len(request["payload"]["requirement"].get("acceptance_criteria", []))
    out: dict[str, Any] = {
        "covered_criteria": _covered(reply, n),
        "questions": _questions(reply["questions"]),
    }
    feature = render_feature(reply)
    if feature:
        out["feature"] = feature
    return out


def _covered(reply: dict[str, Any], n: int) -> list[dict[str, Any]]:
    """Criterion-to-scenario coverage, from the criteria each scenario says it tests."""
    by: dict[int, list[str]] = {}
    for sc in reply.get("scenarios", []):
        for i in sc["criteria"]:
            if 0 <= i < n and _line(sc["name"]) not in by.setdefault(i, []):
                by[i].append(_line(sc["name"]))
    return [{"criterion": i, "scenarios": by[i]} for i in sorted(by)]


def _line(text: str) -> str:
    return " ".join(str(text).split())


def _cell(text: str) -> str:
    return _line(text).replace("|", "\\|")


def render_feature(reply: dict[str, Any]) -> str:
    """Write the Gherkin document from the reply's parts. Empty when there is nothing to write."""
    name, scenarios = _line(reply.get("feature_name", "")), reply.get("scenarios", [])
    if not name and not scenarios:
        return ""
    lines = [f"Feature: {name}"]
    for sc in scenarios:
        ex = sc["examples"]
        outline = bool(ex["columns"])
        lines += ["", f"  {'Scenario Outline' if outline else 'Scenario'}: {_line(sc['name'])}"]
        lines += [f"    {st['keyword']} {_line(st['text'])}" for st in sc["steps"]]
        if outline:
            lines += ["", "    Examples:", "      | " + " | ".join(_cell(c) for c in ex["columns"]) + " |"]
            lines += ["      | " + " | ".join(_cell(c) for c in row) + " |" for row in ex["rows"]]
    return "\n".join(lines) + "\n"


_RS_PREFIX = re.compile(r"^\s*(RS-\d{2})\b")
_TEMPLATE_PREFIX = re.compile(r"^\s*(RS-T\d{2}b?)\b")


def _tidy_ref(ref: Any) -> list[Any]:
    """An rs_refs entry as RS ids: the id alone when a model copies an index line
    ("RS-04 form: ..."), and a template's own RS ids when it cites a template ("RS-T05 ...")."""
    if not isinstance(ref, str):
        return [ref]
    if m := _RS_PREFIX.match(ref):
        return [m.group(1)]
    if m := _TEMPLATE_PREFIX.match(ref):
        t = next((t for t in rulespeak.default_profile().templates if t.id == m.group(1)), None)
        if t is not None:
            return list(t.rs_refs)
    return [ref]


def _tidy_refs(node: Any) -> None:
    """Normalize every rs_refs list in a reply, in place, keeping order and dropping repeats."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "rs_refs" and isinstance(v, list):
                node[k] = list(dict.fromkeys(x for r in v for x in _tidy_ref(r)))
            else:
                _tidy_refs(v)
    elif isinstance(node, list):
        for v in node:
            _tidy_refs(v)


def _parse(task: str, text: str, request: dict[str, Any]) -> tuple[Any, list[str], str]:
    """Parse and check one reply: (reply, problems, reason code if it fails)."""
    try:
        reply = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [f"the reply is not valid JSON: {e}"], "OUTPUT_SCHEMA_INVALID"
    if not isinstance(reply, dict):
        return reply, ["the reply is not a JSON object"], "OUTPUT_SCHEMA_INVALID"
    _tidy_refs(reply)
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
    record["last_reply"] = c.text[:4000]
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
