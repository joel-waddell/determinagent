# DeterminAgent

DeterminAgent routes structured requests to narrow, specialized small language models (SLMs) using deterministic logic, and improves itself offline from its own execution traces.

The full plan is in [docs/program-of-work.md](docs/program-of-work.md): five phases, each closed by a measurable exit gate. Effort is tracked in agent sessions in [docs/loe-actuals.md](docs/loe-actuals.md).

## Status

| Phase | Workstream | State |
| --- | --- | --- |
| 0 Foundations | 0.1 Domain specification | RuleSpeak profile v0.2.0 after expert review |
| 0 Foundations | 0.2 Golden evaluation set | Design set; pilot of 60 labelled; batch 2 of 120 drafted, awaiting labels ([docs](docs/golden-set.md)) |
| 0 Foundations | 0.3 Baselines and targets | Harness and gate built; model-free checker baseline measured ([docs](docs/evaluation.md)); model baselines need model access |
| 0 Foundations | 0.4 SLM strategy | Screens 1 to 4 on free Colab: Qwen3 8B meets the targets on the pilot for T2 (90%) and T3 (95%); T1 meets it with Qwen3 14B (85%, screen 5), so T1 goes to 14B pending batch 2 held-out results ([docs](docs/slm-strategy.md)) |
| 0 Foundations | 0.5 Fine-tuning readiness | Draft verdict per resource; final once the 0.4 screen is in ([docs](docs/finetune-readiness.md)) |
| 0 Foundations | 0.6 Intake UX design sprint | Users mapped, three concepts, two clickable mock-ups; user testing needs Joel ([docs](docs/intake-ux.md)) |
| 0 Foundations | 0.7 Contracts | v1.0 release candidate, including the JavaScript J1–J3 contracts; freezes after 0.6 ([docs](docs/contracts.md)) |
| 0 Foundations | 0.1 Domain specification (JavaScript, tranche 1) | JS profile v0.1.0: ESLint rule set, defect taxonomy and checker ([docs](docs/domain/javascript.md)) |
| 0 Foundations | 0.2 to 0.4 JavaScript J2 (tranche 1) | Pilot of 20 J2 cases labelled; 12 corrected or clarified cases awaiting a re-check; scorer, runner and prompt hooks built ([docs](docs/golden-set.md#j2-javascript-generation-amendment-1)) |
| 0 Foundations | 0.8 Execution sandbox (JavaScript, tranche 1) | Built: isolated runner, limits, fixed clock and seed, escape suite ([docs](docs/sandbox.md)) |
| 1 to 4 | | Not started |

## The POC domains

Four tasks across three output formats. Each format has a deterministic conformance checker, so the SLM only does the semantic work. JavaScript J1 and J3 follow in tranche 2.

| Task | Input | Output | Deterministic check |
| --- | --- | --- | --- |
| RuleSpeak generation | Business intent | Rule statements | Template match, traced diagnostics, separate outcomes |
| RuleSpeak validation | Rule statements | Verdict and defects | Same checker, plus SLM for review and meaning findings |
| Gherkin requirements | User requirement | Feature with scenarios | Official Cucumber parser plus profile rules |
| JavaScript generation (J2) | Typed function spec | ES module exporting the function | Parser, ESLint profile and hidden tests in the sandbox |

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
golden/v1/                golden evaluation set batches (YAML), J2 in j2-*.yaml
tools/golden/             labelling workbook builder and importer, J2 verifier
config/gate.yaml          evaluation gate targets and tolerances
js/                       JavaScript core
  src/conformance/        deterministic checkers (the JavaScript checker lives only here)
  src/sandbox/            execution sandbox for model-written JavaScript (0.8)
  bin/                    CLIs: determinagent, js-sandbox
  test/                   tests, including the Python parity test
src/determinagent/        Python core
  spec/                   versioned conformance profiles (YAML), shared by both cores
  contracts/v1/           JSON Schema contracts, shared by both cores
  conformance/            deterministic checkers
  sandbox.py              calls the JS checker and sandbox through Node
  prompts/v1/             versioned task prompts, rendered from the profiles
  models.py               model adapters (Ollama/OpenAI-style, Claude)
  eval/                   scoring, gate, baselines and the model runner
tests/                    Python tests
  fixtures/               test cases shared by both cores
```
