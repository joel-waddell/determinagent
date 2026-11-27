"""The JavaScript checker and the 0.8 execution sandbox, called from Python.

Both exist only in the JavaScript core (js/src/conformance/javascript.js and
js/src/sandbox/), so Python runs them through ``js/bin/js-sandbox.js`` and
gets back the ``js_execution`` contract. This needs Node 20+ and ``npm ci``
in the repository. Set ``DETERMINAGENT_NODE`` to choose the node binary and
``DETERMINAGENT_JS_ROOT`` when the package is not installed from the repo.

    from determinagent import sandbox
    report = sandbox.execute(code, spec=spec, tests=sandbox.tests_from_spec(spec))
    sandbox.accepted(report)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from functools import cache
from pathlib import Path
from typing import Any


class SandboxUnavailable(RuntimeError):
    """Node or the JavaScript core's dependencies are missing."""


def js_root() -> Path:
    env = os.environ.get("DETERMINAGENT_JS_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def _node() -> str:
    return os.environ.get("DETERMINAGENT_NODE") or shutil.which("node") or "node"


def _script() -> Path:
    return js_root() / "js" / "bin" / "js-sandbox.js"


@cache
def available() -> bool:
    """True when Node and the JS core (with node_modules) can be run."""
    root = js_root()
    if not _script().exists() or not (root / "node_modules" / "eslint").exists():
        return False
    try:
        out = subprocess.run([_node(), "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    major = out.stdout.strip().lstrip("v").split(".")[0]
    return out.returncode == 0 and major.isdigit() and int(major) >= 20


def _call(payload: Any, *, concurrency: int = 4, timeout: float = 600.0) -> Any:
    if not available():
        raise SandboxUnavailable(f"the JS sandbox needs Node 20+ and `npm ci` in {js_root()}")
    try:
        p = subprocess.run(
            [_node(), str(_script()), "--concurrency", str(concurrency)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=js_root(),
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxUnavailable(f"the JS sandbox did not answer within {timeout:.0f} s") from e
    if p.returncode != 0:
        raise SandboxUnavailable(f"the JS sandbox failed ({p.returncode}): {p.stderr.strip()[-500:]}")
    return json.loads(p.stdout)


def tests_from_spec(spec: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The spec's visible examples as sandbox tests, named "example 1", "example 2", ..."""
    tests = []
    for i, ex in enumerate((spec or {}).get("examples", []), 1):
        t: dict[str, Any] = {"name": f"example {i}", "args": ex["args"]}
        if "throws" in ex:
            t["throws"] = ex["throws"]
        else:
            t["returns"] = ex["returns"]
        tests.append(t)
    return tests


def _job(
    code: str, spec: dict[str, Any] | None, tests: Sequence[dict[str, Any]], limits: dict[str, Any] | None
) -> dict:
    job: dict[str, Any] = {"code": code, "tests": list(tests)}
    if spec is not None:
        job["spec"] = spec
    if limits:
        job["limits"] = limits
    return job


def execute(
    code: str,
    *,
    spec: dict[str, Any] | None = None,
    tests: Sequence[dict[str, Any]] = (),
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lint ``code`` and run ``tests`` against it. Returns a js_execution report."""
    return _call(_job(code, spec, tests, limits))


def execute_many(jobs: Iterable[dict[str, Any]], *, concurrency: int = 4) -> list[dict[str, Any]]:
    """Run several jobs (dicts with code, spec, tests, limits) in one call, in order."""
    batch = [_job(j["code"], j.get("spec"), j.get("tests", ()), j.get("limits")) for j in jobs]
    if not batch:
        return []
    return _call(batch, concurrency=concurrency, timeout=60.0 + 10.0 * len(batch))


def info() -> dict[str, Any]:
    """How this machine isolates code: network namespace, permission flag, Node version."""
    return _call({"info": True})


def mutants(code: str, *, max_mutants: int = 120) -> list[dict[str, Any]]:
    """Single-token and structural mutants of ``code``: [{id, line, column, from, to, code}]."""
    return _call({"mutants": code, "max": max_mutants})


def lint_errors(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in report["lint"] if f["severity"] == "error"]


def accepted(report: dict[str, Any]) -> bool:
    """The JS profile's acceptance rule: parsed, no error finding, every test passes, no violation."""
    return (
        report["parsed"]
        and not lint_errors(report)
        and all(t["status"] == "pass" for t in report["tests"])
        and not report["violations"]
    )
