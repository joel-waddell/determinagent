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
3. The expert returns the workbook. `workbook.py import` writes the labels back into the YAML. Spreadsheets often flatten a multi-line cell into one line, so the importer restores the line breaks in a corrected feature, using the Gherkin keywords and table rows. Acceptance checks have no such markers, so a flattened list is split by hand.
4. Disagreements between the draft and the label are reviewed to improve the labelling guide and the drafting for the next batch.

**Batches:** a pilot of 60 cases (20 per task), then 7 batches of 120. The pilot calibrates the format and the guide before most of the effort is spent. It is all in the dev split.

**Expert time:** reviewing a pre-drafted case takes about 1 to 2 minutes, so the full set needs about 15 to 30 hours. The pilot needs about 1 to 2 hours.

## Pilot labelling results (2026-11-24)

Joel labelled all 60 pilot cases and dropped none. He agreed with 40 drafts and corrected 20.

| Task | Agreed | Corrected | What the corrections changed |
| --- | --- | --- | --- |
| T1 Generation | 15 | 5 | One behaviour flipped from draft to ask (P015), four statements reworded, more RS references |
| T2 Validation | 16 | 4 | Two form verdicts changed (P015, P017), two reasons reworded |
| T3 Gherkin | 9 | 11 | Reference features rewritten, acceptance checks rewritten |

These are the lessons for drafting batches 2 to 8:

- **T1: lead with what the rule constrains.** "A timesheet may be approved only by a team lead" (P003) and "The number of people occupying a hotel room must not exceed 3" (P016) put the governed thing or quantity first. RS-17 (precise terms) was added to four of the five corrections, so drafts should cite it whenever a term is chosen.
- **T1: ask when the business rule itself is unclear.** System-phrased intent with open questions about scope, counting and duration (P015) is an ask, even if a plausible draft exists. Any draft statement kept on an ask case is illustrative only.
- **T1: name the domain term, and propose it when the vocabulary lacks it.** P002 uses "shipment" for what is sent. The vocabulary is closed, so the expected output proposes `shipment` with a definition instead of assuming it (see [contracts.md](contracts.md#design-decisions)). A T1 case can carry `expected.vocabulary_proposals`. The workbook shows them, and the expert can correct them as `term: definition` lines.
- **T2: a vague term does not make the form undetermined.** P017 ("in a timely manner") conforms in form, with the vague term flagged for clarification. The checker already said this, so the draft label was wrong.
- **T2: must plus only is a revision, not an open question.** P015 needs revision, because both keywords are operative and the author must say which policy is meant.
- **T3: test both sides of every boundary, tightly.** For example 59:59 against 60:01 minutes, $500 against $500.01, and 14:59 against 15:01. Drafts used one-minute or whole-unit gaps.
- **T3: add nothing beyond the acceptance criteria.** The P008 draft assumed a notification, and Joel removed it. He added the pending state that the criteria do state.
- **T3: one behaviour per scenario, in domain terms.** Outlines whose rows differ in kind became separate scenarios (P007, P009). Implementation details gave way to the outcome, such as "a second factor" instead of "a one-time code" (P012). Steps describe the triggering event, not a batch job (P018, P020). The `Rule:` keyword was dropped where it added nothing (P016).

T3 drafting is the weak spot, with only 45% of drafts agreed. Batch 2 applies these rules before it goes to Joel.

## Batch 2 (2026-11-24, drafted)

[`golden/v1/batch2.yaml`](../golden/v1/batch2.yaml) holds 120 draft cases, 40 per task. Each task has 27 dev and 13 held-out cases, chosen by a seeded shuffle, which starts the held-out split. Cases span retail, banking, insurance, healthcare, logistics, HR, education, travel, property and hospitality.

- **T1:** every template family appears at least twice, except the "Only <subject> may" form. Following the pilot corrections, eligibility is drafted with the governed thing first ("may be approved only by"). 8 cases are asks, 4 are compound, 4 are system-phrased (2 drafts, 2 asks) and 2 are adversarial.
- **T2:** 16 conform, 17 need revision and 7 are undetermined. 7 are deliberate traps, and in 17 cases the checker's verdict differs from the expected label. One trap is a checker false positive: "the application of a tenant" trips the system-term finding (T2-B2-016). Two T1 cases (T1-B2-031 and T1-B2-035) expect a vocabulary proposal, because the intent needs a term the vocabulary lacks.
- **T3:** boundaries are tested on both sides, with the smallest step the data allows. No scenario asserts behaviour that the criteria don't state, and 4 cases are asks.

On the draft labels, the checker-only baseline gets 58% of batch 2's T2 cases right, with 94% precision and 63% recall. That is lower than on the pilot because batch 2 has more traps.

## Open points

- The repository is public, so the held-out split will be public too. Public held-out data can leak into future model training. If that matters, the held-out batches can live in a private location and the tests can read them from there.

## J2 JavaScript generation (Amendment 1)

J2 gets its own 300 cases (200 dev, 100 held-out), sized by the same reasoning as the other tasks. The batches are separate files (`golden/v1/j2-*.yaml`), so a JavaScript change never touches the RuleSpeak and Gherkin batches.

**Coverage.** Each stratum appears at least 15 times across the set: strings, arrays, numbers, objects, dates, parsing, validation, algorithms, error handling (the function must throw the right error), async functions, and immutability (the function must not change its input). About 10% are *ask* cases, where the spec leaves open a decision that changes results, such as a rounding rule or who pays leftover cents. About 5% are adversarial, with instructions injected into the spec text. The test there is that the model ignores them: any attempt to reach `process`, files or the network is a sandbox violation and fails the case.

**Case format.** `input.spec` is the `js_function_spec` the model sees, including 0 to 3 visible examples. `expected` holds:

| Field | What it is |
| --- | --- |
| `behavior` | `draft` or `ask` |
| `reference_solution` | One correct module (null for ask cases) |
| `hidden_tests` | At least 5 tests in the [sandbox test format](sandbox.md#tests): value tests, throws tests and snippet tests |
| `open_questions` | Ask cases only: the decisions the spec leaves open |
| `mutation` | Snapshot of the mutation check, written by the verifier |
| `equivalent_mutants`, `equivalent_note` | Mutants reviewed as unable to change any result, with the reason |

A case is scored on its visible examples plus its hidden tests. The hidden tests never reach the model, not even in retry feedback.

**Verification.** [`tools/golden/j2_verify.py`](../tools/golden/j2_verify.py) runs before a batch goes to labelling:

1. The reference solution must be accepted by the sandbox with no lint findings at all, warnings included.
2. Every single-token mutant of the reference (one operator, boolean or number changed) is run against the tests. The tests must catch at least 80% of the mutants that are not listed as equivalent, and in practice the pilot catches all of them. An equivalent mutant needs a written reason, and the verifier fails if a listed equivalent stops surviving, so the list can't go stale.

Writing the pilot this way found real gaps. The first draft of `ageOn` had no test for a century year, `retry` had no test with exactly one attempt, and `topWords` had no test that a plain-object counter fails on the word "constructor". Each gap got a test.

```sh
python tools/golden/j2_verify.py golden/v1/j2-pilot.yaml --write     # check, and refresh the mutation snapshots
python tools/golden/workbook.py build golden/v1/j2-pilot.yaml j2.xlsx
```

**Labelling.** The workbook has a *J2 JavaScript* sheet. It shows the spec as the model sees it, the reference, the hidden tests and the mutation result. The expert can **Agree**, **Drop**, or **Correct**: set the behavior and/or describe what to change. Code and test changes are applied by hand, so a corrected case gets `label.status: revise` with the requested changes, and comes back for a quick re-check. Only `labelled` cases count in a gate.

**Batches.** A pilot of 20 (`j2-pilot.yaml`, 18 draft and 2 ask, all dev), then batches of 70. Reviewing a case takes longer than a RuleSpeak case, about 3 to 5 minutes, because the expert reads code. That puts the pilot at about 1 to 1.5 hours, within the plan's 20 to 40 hours for the full 300.
