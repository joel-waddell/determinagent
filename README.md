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

## Two cores, one spec

The core is JavaScript (Node 20+), in [js/](js/). The original Python implementation in [src/determinagent/](src/determinagent/) is kept alongside it. Both read the same YAML profiles and run the same test fixtures in [tests/fixtures/](tests/fixtures/), and a parity test checks that they return identical JSON verdicts for every fixture. A change to either core that breaks agreement fails CI.

## Quick start

JavaScript:

```sh
npm install
npm test          # runs the parity test too if the Python core is installed
echo "Each order must have at least one line item." | npx determinagent check rulespeak
npx determinagent check gherkin path/to/requirement.feature
```

Python:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
echo "Each order must have at least one line item." | determinagent check rulespeak
```

Both CLIs print the verdict as the same JSON and exit 0 when the input is conformant, 1 when it is not.

## Layout

```
docs/                     plan, domain specs, effort actuals
js/                       JavaScript core
  src/conformance/        deterministic checkers
  bin/                    CLI
  test/                   tests, including the Python parity test
src/determinagent/        Python core
  spec/                   versioned conformance profiles (YAML), shared by both cores
  conformance/            deterministic checkers
tests/                    Python tests
  fixtures/               test cases shared by both cores
```
