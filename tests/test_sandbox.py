"""The Python bridge to the JS checker and the 0.8 sandbox.

These need Node 20+ and `npm ci`. Locally they are skipped without them; CI
sets DETERMINAGENT_REQUIRE_SANDBOX=1 so a missing sandbox fails instead.
"""

import os

import pytest

from determinagent import contracts, sandbox

needs_sandbox = pytest.mark.skipif(
    not sandbox.available() and not os.environ.get("DETERMINAGENT_REQUIRE_SANDBOX"),
    reason="the JS sandbox needs Node 20+ and npm ci",
)

SPEC = {
    "name": "slug",
    "params": [{"name": "title", "type": "string"}],
    "returns": {"type": "string"},
    "behavior": "Lower-case the title and join its words with hyphens.",
    "examples": [{"args": ["Hello World"], "returns": "hello-world"}, {"args": [42], "throws": "TypeError"}],
}
GOOD = """export function slug(title) {
  if (typeof title !== 'string') throw new TypeError('title must be a string')
  return title.trim().toLowerCase().split(/\\s+/).join('-')
}
"""


def test_tests_from_spec():
    assert sandbox.tests_from_spec(SPEC) == [
        {"name": "example 1", "args": ["Hello World"], "returns": "hello-world"},
        {"name": "example 2", "args": [42], "throws": "TypeError"},
    ]
    assert sandbox.tests_from_spec(None) == []


@needs_sandbox
def test_execute_returns_a_valid_report():
    r = sandbox.execute(GOOD, spec=SPEC, tests=sandbox.tests_from_spec(SPEC))
    assert contracts.validate("js_execution", r) == []
    assert sandbox.accepted(r)
    assert [t["status"] for t in r["tests"]] == ["pass", "pass"]


@needs_sandbox
def test_violations_and_lint_errors_are_reported():
    r = sandbox.execute("export function slug(t) { return process.env.HOME }", spec=SPEC, tests=[SPEC_TEST])
    assert "process" in r["violations"]
    assert [f["code"] for f in sandbox.lint_errors(r)] == ["JS-SEC-002"]
    assert not sandbox.accepted(r)


SPEC_TEST = {"name": "t", "args": ["A b"], "returns": "a-b"}


@needs_sandbox
def test_execute_many_keeps_order():
    jobs = [
        {"code": GOOD, "spec": SPEC, "tests": [SPEC_TEST]},
        {"code": "export function slug(t) { return t }", "spec": SPEC, "tests": [SPEC_TEST]},
        {"code": "export function slug(t) { return", "spec": SPEC, "tests": [SPEC_TEST]},
    ]
    out = sandbox.execute_many(jobs, concurrency=2)
    assert [sandbox.accepted(r) for r in out] == [True, False, False]
    assert out[2]["parsed"] is False


@needs_sandbox
def test_info():
    i = sandbox.info()
    assert set(i) >= {"network_namespace", "permission_flag", "node_version", "profile_version"}


def test_unavailable_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DETERMINAGENT_JS_ROOT", str(tmp_path))
    sandbox.available.cache_clear()
    try:
        with pytest.raises(sandbox.SandboxUnavailable):
            sandbox.execute(GOOD)
    finally:
        monkeypatch.delenv("DETERMINAGENT_JS_ROOT")
        sandbox.available.cache_clear()
