"""Versioned prompt templates for the model-backed tasks (Phase 0.4).

Each ``prompts/<version>/<task>.md`` file has a small front matter block, a
``# system`` section and a ``# user`` section. Placeholders use ``$name``
(``string.Template``), so JSON braces in a prompt need no escaping. Profile
facts (templates, keywords, lexicon) are rendered from the spec files, so a
prompt cannot drift from the checker that validates its output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from string import Template
from typing import Any

import yaml

from ..conformance import gherkin, rulespeak

VERSION = "v1"
TASKS = ("rulespeak_generation", "rulespeak_validation", "gherkin_requirements")


@dataclass(frozen=True)
class PromptTemplate:
    task: str
    version: str
    system: Template
    user: Template


@dataclass(frozen=True)
class Prompt:
    task: str
    version: str
    system: str
    user: str


def _text(version: str, name: str) -> str:
    return resources.files(__package__).joinpath(version, name).read_text(encoding="utf-8")


@cache
def load(task: str, version: str = VERSION) -> PromptTemplate:
    raw = _text(version, f"{task}.md")
    if not raw.startswith("---\n"):
        raise ValueError(f"{task}.md has no front matter")
    _, front, body = raw.split("---\n", 2)
    meta = yaml.safe_load(front)
    if meta.get("task") != task:
        raise ValueError(f"{task}.md declares task {meta.get('task')!r}")
    head, sep, user = body.partition("\n# user\n")
    if not sep or "# system\n" not in head:
        raise ValueError(f"{task}.md needs '# system' and '# user' sections")
    system = head.split("# system\n", 1)[1]
    return PromptTemplate(task, f"{version}/{meta['version']}", Template(system.strip()), Template(user.strip()))


def _profile_facts() -> dict[str, str]:
    p = rulespeak.default_profile()
    raw = yaml.safe_load(resources.files("determinagent.spec").joinpath("rulespeak.yaml").read_text(encoding="utf-8"))
    templates = "\n".join(f'- {t.id} ({t.guidance}): {t.form} Example: "{t.example}"' for t in p.templates)
    return {
        "templates": templates,
        "determiners": ", ".join(raw["determiners"]),
        "max_words": str(p.max_words),
        "system_terms": ", ".join(f'"{w}"' for w in p.lexicon.get("system_terms", [])[:8]),
        "vague_terms": ", ".join(f'"{w}"' for w in p.lexicon.get("vague_terms", [])[:8]),
        "rs_index": _text(VERSION, "rs_index.md").strip(),
        "max_steps": str(gherkin.default_profile().max_steps),
    }


def render(task: str, request: dict[str, Any], extra: dict[str, str] | None = None, version: str = VERSION) -> Prompt:
    """Render the prompt for a v1 request. ``extra`` supplies runtime values such as checker output."""
    t = load(task, version)
    pay = request["payload"]
    values = _profile_facts()
    vocab = pay.get("vocabulary") or []
    values["vocabulary"] = ", ".join(v if isinstance(v, str) else v.get("term", str(v)) for v in vocab) or "(none)"
    if task == "rulespeak_generation":
        values["intent"] = pay["intent"].get("free_text") or json.dumps(pay["intent"])
    elif task == "rulespeak_validation":
        values["statement"] = pay["statements"][0]["text"]
    elif task == "gherkin_requirements":
        values["requirement"] = json.dumps(pay["requirement"], indent=2, ensure_ascii=False)
    values.update(extra or {})
    return Prompt(task, t.version, t.system.substitute(values), t.user.substitute(values))
