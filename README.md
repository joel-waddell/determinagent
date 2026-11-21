# DeterminAgent

DeterminAgent routes structured requests to narrow, specialized small language models (SLMs) using deterministic logic, and improves itself offline from its own execution traces.

The full plan is in [docs/program-of-work.md](docs/program-of-work.md): five phases, each closed by a measurable exit gate. Effort is tracked in agent sessions in [docs/loe-actuals.md](docs/loe-actuals.md).

## Status

| Phase | Workstream | State |
| --- | --- | --- |
| 0 Foundations | 0.1 Domain specification | Draft, pending domain-expert review |
| 0 Foundations | 0.2 to 0.7 | Not started |
| 1 to 4 | | Not started |

## The POC domains

Three tasks across two output formats. Each format has a deterministic conformance checker, so the SLM only does the semantic work.

| Task | Input | Output | Deterministic check |
| --- | --- | --- | --- |
| RuleSpeak generation | Business intent | Rule statements | Template match and defect rules |
| RuleSpeak validation | Rule statements | Verdict and defects | Same checker, plus SLM for semantic defects |
| Gherkin requirements | User requirement | Feature with scenarios | Official Cucumber parser plus profile rules |

Specs: [docs/domain/](docs/domain/README.md). Machine-readable profiles: [src/determinagent/spec/](src/determinagent/spec/).

## Quick start

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest

echo "Each order must have at least one line item." | determinagent check rulespeak
determinagent check gherkin path/to/requirement.feature
```

`check` prints the verdict as JSON and exits 0 when the input is conformant, 1 when it is not.

## Layout

```
docs/                     plan, domain specs, effort actuals
src/determinagent/
  spec/                   versioned conformance profiles (YAML)
  conformance/            deterministic checkers
tests/                    checker tests and fixtures
```
