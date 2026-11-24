# Evaluation harness and baselines (Phase 0.3)

The harness scores a **run** against the golden set and gates a candidate against a baseline. It lives in [`determinagent.eval`](../src/determinagent/eval/). Evaluation is the one component that exists only in Python, because it sits next to the model and fine-tuning tooling. It reads the same contracts and checkers as the JavaScript core, and the parity test keeps those identical.

## Runs

A run is a JSON Lines file with one record per golden case:

```json
{"case_id": "T2-P001", "response": {"...": "v1 response"}, "latency_ms": 812.0,
 "routing_latency_ms": 3.1, "cost_usd": 0.0004, "attempts": 1,
 "first_pass_wellformed": true, "system": "qwen-2.5-3b-prompt-v1"}
```

`response` must validate against the v1 response contract. A record that doesn't, or a case with no record, is scored as a failure. Model runs from `eval run` also record `prompt_version`, `input_tokens`, `output_tokens` and, when retries ran out, the last `problems` ([slm-strategy.md](slm-strategy.md#how-a-run-works)).

## How a case is scored

| Task | Success means |
| --- | --- |
| All | The response is contract-valid, its status is `resolved`, and it is routed to the expected task. |
| T1 generation | If the expected behavior is *ask*: questions and no statements. Otherwise: at least as many statements as the reference, every statement passes the RuleSpeak checker with the case vocabulary, and the guidance type is the one expected. |
| T2 validation | The `form` verdict equals the expert label. For precision and recall, a statement counts as defective when its form is `needs_revision` or `undetermined`. |
| T3 Gherkin | If the expected behavior is *ask*: questions and no feature. Otherwise: the feature passes the Gherkin profile, and `covered_criteria` covers every acceptance criterion. |

This is the deterministic part of success. The rubric part, which judges whether a statement says what the intent meant and whether scenarios really test the criteria, is scored separately once rubrics are written. Until then, T1 and T3 success is an upper bound. Gate decisions use `--labelled-only` once labels exist.

Precision and recall are computed per statement for now, as defective or not. Once labels record the individual defects, they will be computed per finding.

## Metrics and the gate

The harness computes these metrics: routing accuracy, final and first-pass well-formedness, task success, validation precision and recall, violation rate, cost per request, and p95 end-to-end and routing latency. Targets and tolerances are in [`config/gate.yaml`](../config/gate.yaml), copied from the plan's metrics table.

`compare` pairs the two runs case by case and gives each metric a verdict:

- **pass:** no regression beyond tolerance.
- **fail:** any regression on a metric with zero tolerance (routing accuracy, final well-formedness, violation rate), or a regression beyond the review band.
- **review:** a regression inside the 3-point review band. 300 cases can't resolve a change that small (see [golden-set.md](golden-set.md)).

Task success also gets the paired counts of cases lost and gained, with an exact McNemar p-value.

```sh
python -m determinagent.eval baseline golden/v1/pilot.yaml checker run.jsonl
python -m determinagent.eval score    golden/v1/pilot.yaml run.jsonl --task rulespeak_validation
python -m determinagent.eval compare  golden/v1/pilot.yaml base.jsonl candidate.jsonl
```

The `oracle` system answers every case with its golden expectation. It scores 100%, and the tests use it to check the harness.

## Baselines

### B0: deterministic checker only, on T2 (2026-11-24)

This run answers RuleSpeak validation with the checker alone, with no model. It shows how much the model has to add. It was scored against the **draft** labels of the 20 pilot T2 cases, so it gets re-run once Joel has labelled them.

| Metric | Value | Target |
| --- | --- | --- |
| Routing accuracy | 100% | ≥ 99% |
| Task success (form verdict agrees) | 75% (15 of 20) | ≥ 85% |
| Validation precision | 86% | ≥ 90% |
| Validation recall | 67% | ≥ 85% |
| p95 latency | under 1 ms | — |
| Cost | 0 | — |

All five misses come from one gap. The checker's `form` verdict looks only at form diagnostics, while an expert marks a statement *undetermined* when a meaning, style or principle question is open. Three statements had only review findings, which the checker leaves as `conforms` but the draft labels call *undetermined*: system wording (P009), a necessary-condition classification (P012) and a vague term (P017). In P008, the profile can't parse a leading condition, but the draft label still says the form conforms. P010 has a repeated keyword, which the checker sends to review while the label says *needs revision*. The model's job in T2 is to settle exactly these review findings, and recall is the number to watch.

### Still to measure

- **LLM baseline:** a general-purpose LLM on all three tasks, for the quality and cost comparison.
- **SLM candidates:** off-the-shelf small models with prompt optimization (0.4).

The runner, adapters and prompts for both are built ([slm-strategy.md](slm-strategy.md)). What is missing is model access, which is the open question for Joel in 0.4 and 0.5.
