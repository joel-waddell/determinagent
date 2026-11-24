"""Versioned JSON Schema contracts (Phase 0.7), shared with the JavaScript core.

from determinagent import contracts
errors = contracts.validate("request", obj)   # [] when valid
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

VERSION = "v1"
SCHEMAS = ("common", "request", "response", "handoff-artifact", "governance-change")


def _urn(name: str) -> str:
    return f"urn:determinagent:contracts:{VERSION}:{name}"


@lru_cache(maxsize=1)
def _registry() -> tuple[Registry, dict[str, dict[str, Any]]]:
    base = resources.files("determinagent.contracts").joinpath(VERSION)
    docs = {n: json.loads(base.joinpath(f"{n}.schema.json").read_text(encoding="utf-8")) for n in SCHEMAS}
    registry = Registry().with_resources((d["$id"], Resource.from_contents(d)) for d in docs.values())
    return registry, docs


def schema(name: str) -> dict[str, Any]:
    return _registry()[1][name]


@cache
def _validator(name: str) -> Draft202012Validator:
    registry, docs = _registry()
    if name in docs:
        target = docs[name]
    else:  # a definition inside common, such as "rulespeak_generation_output"
        target = {"$ref": f"{_urn('common')}#/$defs/{name}"}
    return Draft202012Validator(target, registry=registry, format_checker=FormatChecker())


def validate(name: str, instance: Any) -> list[str]:
    """Return validation errors as "path: message" strings, sorted; [] when valid."""
    errors = _validator(name).iter_errors(instance)
    return sorted(f"/{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors)


def is_valid(name: str, instance: Any) -> bool:
    return _validator(name).is_valid(instance)
