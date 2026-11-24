# DeterminAgent

DeterminAgent routes structured requests to narrow, specialized small language models (SLMs) using deterministic logic, and improves itself offline from its own execution traces.

The full plan is in [docs/program-of-work.md](docs/program-of-work.md): five phases, each closed by a measurable exit gate. Effort is tracked in agent sessions in [docs/loe-actuals.md](docs/loe-actuals.md).

## Status

| Phase | Workstream | State |
| --- | --- | --- |
| 0 Foundations | 0.1 Domain specification | RuleSpeak profile v0.2.0 after expert review; case labels pending |
| 0 Foundations | 0.2 Golden evaluation set | Design set; pilot batch of 60 drafted, awaiting labels ([docs](docs/golden-set.md)) |
| 0 Foundations | 0.3 Baselines and targets | Harness and gate built; model-free checker baseline measured ([docs](docs/evaluation.md)); model baselines need model access |
| 0 Foundations | 0.4 SLM strategy | Shortlist, selection method, prompts v1, model adapters and eval runner built; runs need model access ([docs](docs/slm-strategy.md)) |
| 0 Foundations | 0.5 to 0.6 | Not started |
| 0 Foundations | 0.7 Contracts | v1.0 release candidate; freezes after 0.6 ([docs](docs/contracts.md)) |
| 1 to 4 | | Not started |

## The POC domains

Three tasks across two output formats. Each format has a deterministic conformance checker, so the SLM only does the semantic work.

| Task | Input | Output | Deterministic check |
| --- | --- | --- | --- |
| RuleSpeak generation | Business intent | Rule statements | Template match, traced diagnostics, separate outcomes |
| RuleSpeak validation | Rule statements | Verdict and defects | Same checker, plus SLM for review and meaning findings |
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
docs/                     plan, domain specs, golden-set design, effort actuals
golden/v1/                golden evaluation set batches (YAML)
tools/golden/             labelling workbook builder and importer
config/gate.yaml          evaluation gate targets and tolerances
js/                       JavaScript core
  src/conformance/        deterministic checkers
  bin/                    CLI
  test/                   tests, including the Python parity test
src/determinagent/        Python core
  spec/                   versioned conformance profiles (YAML), shared by both cores
  contracts/v1/           JSON Schema contracts, shared by both cores
  conformance/            deterministic checkers
  prompts/v1/             versioned task prompts, rendered from the profiles
  models.py               model adapters (Ollama/OpenAI-style, Claude)
  eval/                   scoring, gate, baselines and the model runner
tests/                    Python tests
  fixtures/               test cases shared by both cores
```
