# Golden evaluation set (Phase 0.2)

The golden set is the yardstick for every gate in the program. Each task has a versioned set of labelled cases. Each case holds a typed input, the expected route, and an expected output or acceptance rubric. A held-out split is kept and never used for tuning. Joel is the domain expert who labels the cases, and Claude drafts every case and its proposed label.

## Size: 300 cases per task, 900 in v1

| Task | Dev | Held-out | Total |
| --- | --- | --- | --- |
| T1 RuleSpeak generation | 200 | 100 | 300 |
| T2 RuleSpeak validation | 200 | 100 | 300 |
| T3 Gherkin requirements | 200 | 100 | 300 |

The v1 size comes from the targets in the [program of work](program-of-work.md#success-criteria-and-program-metrics):

- **Routing accuracy of at least 99%, with no regression allowed.** With zero routing errors in 300 cases, the 95% upper bound on the error rate is 1% (the rule of three). 300 is the smallest size per task at which "≥ 99%" can be shown at all.
- **Task success of at least 85%, then at least 90%.** At 90% success, a 300-case estimate is within about ±3.4 points (95% interval). That is enough to show a target is met, not to show it is barely met.
- **Gate tolerances of 1 to 2 points.** The plan compares candidates with a paired test on the same cases. The detectable difference depends on how many cases flip between the two candidates. Typically 3 to 5% of cases flip, and at 80% power 300 cases then detect a change of about 3 to 3.5 points. A 1 to 2 point tolerance needs about 1,000 cases. So in v1, a drop inside 3 points is flagged for review instead of failing the gate automatically. The set grows toward 1,000 from production traces, as the plan says. Phase 0.3 recalibrates the tolerances on the measured flip rate.
- **Validation precision of at least 90% and recall of at least 85%.** Recall is measured over real defects. T2 therefore keeps about 60% of its cases defective, which gives about 180 defective statements, many with more than one finding.

The held-out split is one third of each task. It guards against the optimizer overfitting (see the plan's risk table). With 100 cases it gives a coarse check, about ±6 points, so it is used to catch overfitting, not to tune.

## Coverage within each task

Every stratum is covered in both splits. The minimums below apply per task.

- **T1 generation:** every template family (obligation, prohibition, restricted permission and eligibility, classification, computation, procedure, both advice forms) appears at least 15 times. About 15% of cases are ambiguous intents, where the expected behavior is to *ask*, not to draft. About 10% are compound intents that need more than one statement. About 10% are system-phrased intents, and about 5% are adversarial inputs such as injected instructions. Cases are spread over at least six business domains.
- **T2 validation:** about 40% conform, 40% need revision and 20% are undetermined. Every diagnostic code has at least 10 positive cases. Every RS form check (RS-01 to RS-11) appears at least 10 times. About 15% are traps where the checker and the RuleSpeak assessment disagree. Examples are "must have only one" and a leading condition. Each case records the checker snapshot next to the expert label.
- **T3 Gherkin:** the cases cover happy paths, negative paths, boundaries (Scenario Outlines), workflows, rules, timing and permissions. About 10% are ambiguous requirements where the expected behavior is to ask, and about 5% are adversarial.

## Case format

The batches live in [`golden/v1/`](../golden/v1/). Every case has `id`, `task`, `split`, `stratum`, `input`, `expected` and `label`. `expected.route` is the routing label: the task the router must send the case to. `label.status` is `draft` until the expert labels the case, and only labelled cases count in a gate.

| Task | `input` | `expected` |
| --- | --- | --- |
| T1 | `intent` (free text for now; see below), `vocabulary` | `behavior` (draft or ask), `reference_statements`, `guidance_type`, `rs_refs` |
| T2 | `statement` (and later `intent`, for fidelity) | `form`, `fidelity`, `rs_refs`, `reason`, plus a `checker` snapshot |
| T3 | `requirement` (`role`, `capability`, `benefit`, `acceptance_criteria`) | `behavior`, `reference_feature`, `acceptance_checks` |

T1 intents are kept as free text because they are what a business user types today. The typed request carries them in `intent.free_text`, and typed fields can be added once the 0.6 intake sprint picks a pattern. Every golden case converts to a valid v1 request (`determinagent.golden.to_request`), and a test checks this.

Generated outputs are not compared word for word against a reference statement or feature. The reference shows one acceptable answer. Acceptance comes from the deterministic checkers plus a rubric built from `rs_refs` (T1) or `acceptance_checks` (T3). The rubric is defined in 0.3.

## Labelling workflow

1. Claude drafts a batch, with a proposed label on every case, and checks every reference with both checkers.
2. [`tools/golden/workbook.py`](../tools/golden/workbook.py) builds a spreadsheet with one sheet per task. Grey columns show the case and the draft. Yellow columns are for the expert: **Agree**, **Correct** (with the corrected values) or **Drop**.
3. The expert returns the workbook. `workbook.py import` writes the labels back into the YAML.
4. Disagreements between the draft and the label are reviewed to improve the labelling guide and the drafting for the next batch.

**Batches:** a pilot of 60 cases (20 per task), then 7 batches of 120. The pilot calibrates the format and the guide before most of the effort is spent. It is all in the dev split.

**Expert time:** reviewing a pre-drafted case takes about 1 to 2 minutes, so the full set needs about 15 to 30 hours. The pilot needs about 1 to 2 hours.

## Open points

- The repository is public, so the held-out split will be public too. Public held-out data can leak into future model training. If that matters, the held-out batches can live in a private location and the tests can read them from there.
