# Small-model strategy (Phase 0.4)

The plan is to use off-the-shelf models first. Each task gets the smallest open-weight model that meets its targets after prompt work. A task moves to fine-tuning (0.5) only if no candidate meets its targets after prompt optimization.

This document covers the shortlist, how the models are run, and how a model is chosen. The code is in place, so runs can start as soon as a model can be reached. No model has been run yet, because this environment cannot download weights or reach a paid API.

## What the model does, and what it doesn't

The checkers decide everything they can decide, so the model only does the work that needs language judgement. This keeps the model's job small, which is what makes a small model viable.

| Task | Model does | Checker does |
| --- | --- | --- |
| T1 RuleSpeak generation | Writes the statements and their trace, or asks a question when a business decision is missing | Accepts or rejects each statement, and sets `guidance_type` and `template_id` |
| T2 RuleSpeak validation | Settles the form verdict where the checker found a review item or couldn't match a template | Runs first. Its findings are the evidence in the prompt and the findings in the output |
| T3 Gherkin requirements | Writes the feature, maps the criteria to scenarios, or asks about a vague criterion | Applies the Gherkin profile and checks that every criterion is covered |

The baseline B0 result ([evaluation.md](evaluation.md#b0-deterministic-checker-only-on-t2-2026-11-24-expert-labels)) shows where T2 needs the model. All five of the checker's misses are review items that only a judgement call can settle.

## How a run works

`python -m determinagent.eval run` runs one model over golden cases and writes a run file that `score` and `compare` read.

1. It builds the v1 request for the case (`golden.to_request`).
2. It renders the task prompt from `src/determinagent/prompts/v1/`. The template list, keywords, word limit and lexicon examples are rendered from the profile files, so the prompt can't drift from the checker.
3. It asks the model for a reply that matches the task's reply schema. For Gherkin, the reply gives the feature's parts, each scenario lists the criteria it tests, and the runner writes the file and the coverage (`eval/runner.py`, `REPLY_SCHEMAS`). The backend constrains decoding to that schema where it can: `response_format` with `json_schema` for OpenAI-style servers (Ollama, vLLM, llama.cpp server) and `output_config.format` for Claude.
4. It checks the reply against the schema and the checkers. If the reply fails, it sends the reply back with the findings, up to two times.
5. It writes a v1 response. Possible outcomes are `resolved`, `violated` (with `OUTPUT_SCHEMA_INVALID` or `OUTPUT_NONCONFORMANT` once retries run out) and `rejected` (with `MODEL_ERROR`). The record also logs the attempt count, whether the first reply passed, tokens, latency and cost.

The reply schemas are smaller than the v1 output contract. They leave out the fields a checker fills, and every field is required, because strict constrained decoding needs that.

```bash
# See the exact prompt and schema without calling anything
python -m determinagent.eval run golden/v1/pilot.yaml --model ollama:qwen3:4b --task rulespeak_validation --dry-run

# Run a local model through Ollama, then score it
python -m determinagent.eval run golden/v1/pilot.yaml --model ollama:qwen3:4b --out runs/qwen3-4b.jsonl
python -m determinagent.eval score golden/v1/pilot.yaml runs/qwen3-4b.jsonl

# Claude baseline: a paid backend needs a cost cap; the run stops before the next case once it is spent
pip install -e ".[models]"
python -m determinagent.eval run golden/v1/pilot.yaml --model anthropic:claude-sonnet-5-5 --max-cost 3 --out runs/sonnet.jsonl
```

**On a free GPU:** [notebooks/slm-screen.ipynb](../notebooks/slm-screen.ipynb) runs the screen on a free Colab or Kaggle T4. It installs Ollama, pulls each model, runs and scores the cases, and zips the run files for download. An optional cell exposes the Ollama server through a Cloudflare quick tunnel, so the runner can use it from elsewhere through `OLLAMA_BASE_URL`.

Model specs are `ollama:<model>`, `openai-compat:<model>@<base_url>` (hosted providers or vLLM, with the key in `DETERMINAGENT_API_KEY`) and `anthropic:<model>`. For a self-hosted model, set `DETERMINAGENT_PRICE_IN` and `DETERMINAGENT_PRICE_OUT` (USD per million tokens) from the hosting cost, so its cost is comparable with the LLM baseline.

## Shortlist

The candidates are open-weight models from 1.7B to 12B parameters with a licence that allows commercial use. At 4-bit quantization, an 8B model needs about 5 GB of memory, so all of them run on one consumer GPU or an Apple silicon laptop.

| Model | Sizes to screen | Licence | Why it is on the list |
| --- | --- | --- | --- |
| Qwen3 | 1.7B, 4B, 8B | Apache 2.0 | Strong instruction following and JSON output at small sizes; the widest size ladder |
| Gemma 4 | E4B, 12B | Apache 2.0 | Released April and June 2026; strong English writing quality for its size |
| Ministral 3 | 3B, 8B | Apache 2.0 | Built for edge and on-device use, with good function calling and JSON |
| IBM Granite 4.1 | 3B, 8B | Apache 2.0 (check the 4.1 model card) | Tuned for enterprise structured tasks, and it ships with governance documentation |
| Phi-4-mini | 3.8B | MIT (check the model card) | Strong reasoning for its size |
| SmolLM3 | 3B | Apache 2.0 | A fully open reference point, with open training data |

### Floor tier: under 1B

The checkers carry much of the load, so the screen also includes a floor tier of models under 1B parameters. A sub-1B model runs on a CPU at a fraction of the cost of the main tier, and it is also the cheapest base model for fine-tuning in 0.5.

| Model | Size | Licence | Why it is on the list |
| --- | --- | --- | --- |
| Qwen3 | 0.6B | Apache 2.0 | The smallest member of the main tier's family, so results compare directly with 1.7B–8B |
| SmolLM2 | 360M | Apache 2.0 | Fully open, and small enough to show where the floor is |
| Gemma 3 | 270M | Gemma terms of use (check before adoption) | Built to be fine-tuned for narrow tasks |

Expectations differ by task:

- **T2 validation** is the best fit for the floor tier. It is a three-way choice with the checker's evidence already in the prompt, so a sub-1B model may meet the targets on prompt work alone.
- **T1 generation** and **T3 Gherkin** ask the model to write. A sub-1B model is likely to fail the checkers more often and need more retries. Constrained decoding and checker feedback make the result measurable instead of guessable, and the screen records the retry rate and first-pass rate.

If a floor model misses on prompt work alone but comes close, it becomes the first fine-tuning candidate. Its training cost is small, and its serving cost is the lowest of any option.

These were left out:

- **Tiny Aya** has a non-commercial licence (CC-BY-NC).
- **Nemotron 3 Nano 30B-A3B** is a 30B mixture of experts, so it needs more memory than the rest. It is kept as a step up if no dense model meets the targets.
- **Gemma 4 26B/31B** are kept for the same reason.
- Closed small models such as GPT-5.4 mini and nano can't be self-hosted or fine-tuned.

Licences come from the vendors' announcements and need checking against each model card before a model is adopted. The list reflects what was current in November 2026, so it should be checked again when screening starts.

## Selection method

1. **Screen.** Run each candidate on the three tasks over the pilot dev cases, with prompt v1, temperature 0, constrained decoding and two retries. That is about 13 models, the floor tier included, times 60 cases. Record task success, first-pass well-formedness, p95 latency and cost.
2. **Cut.** For each task, keep the best three, plus any smaller model within 5 points of the best. A floor-tier model that is within 10 points also stays, as a fine-tuning candidate.
3. **Optimize prompts, on dev only.** Change one thing at a time: the instruction wording, two or three worked examples from dev cases, how the checker evidence is laid out, and the retry feedback. Each kept change becomes a new prompt version (`prompts/v1/<task>.md` front matter), so every run says which prompt it used. Never tune on held-out cases.
4. **Decide.** For each task, choose the smallest model that meets the gate targets on the held-out split ([config/gate.yaml](../config/gate.yaml)). Compare it with the LLM baseline using the paired McNemar test in `eval compare`. The cost target is 20% of the LLM baseline's cost per request.
5. **Escalate.** A task with no passing candidate goes to fine-tuning. The best candidate becomes the base model, and the 0.5 readiness verdict says whether that is possible now.

The final choice needs labelled held-out cases. The 60 pilot cases now carry Joel's labels, so screening results on the pilot are real but small-sample. They are all dev cases, so the final choice still waits for the held-out split.

## Screen 1 results (2026-11-24)

Joel ran the notebook on a free Colab T4 over the 60 pilot cases. It covered 7 models with prompts v1 1.0.0, temperature 0 and two retries. The scores below are re-scored against Joel's labels and are small-sample: 20 cases per task, all dev.

| Model | T1 generation | T2 validation (precision / recall) | T3 Gherkin | p95 latency (T1 / T2) |
| --- | --- | --- | --- | --- |
| Qwen3 8B | **75%** | **85%** (88% / 88%) | 0% | 12 s / 6 s |
| Qwen3 4B | 65% | **85%** (86% / 75%) | 0% | 9 s / 7 s |
| Qwen3 1.7B | 5% | 80% (83% / 62%) | 0% | 13 s / 3 s |
| Phi-4-mini 3.8B | 55% | 0% | 0% | 14 s / 99 s |
| Qwen3 0.6B | 40% | 35% (86% / 75%) | 0% | 6 s / 2 s |
| SmolLM2 360M | 0% | 5% | 0% | 35 s / 32 s |
| Gemma 3 270M | 0% | 5% | 0% | 19 s / 13 s |
| Checker only (B0) | — | 75% (86% / 75%) | — | under 1 ms |

**T2: the model adds value.** Qwen3 8B gets 85% against the checker's 75%, and it reaches the 85% target for success and recall. Precision is 88% against a 90% target. Qwen3 8B and 4B fix the two cases where the checker leaves a keyword question open (P010, P015). Both still miss the same three: P008, P009 and P012. In those, the checker's verdict and the expert's differ on whether a review finding makes the form undetermined, which is a prompt and worked-example target for step 3.

**T1: every miss by the top two models is a failure to ask.** Qwen3 8B's five misses are the five pilot cases whose expected behavior is *ask*, and Qwen3 4B misses the same five plus two. The models draft a plausible statement when the intent leaves a decision open. Prompt optimization should start there. T1 success is still an upper bound until the rubric exists.

**T3: a runner fault, not a model result.** No model passed any Gherkin case. Almost every feature that came back failed in the same way: the text starts with the user story instead of a `Feature:` line, so the official parser rejects it at line 1, and the retries didn't fix it. The reply asked the model to write the whole Gherkin file as one string. From prompt 1.1.0, the model fills in parts instead: a feature name and scenarios made of a keyword, the step text and an Examples table. The runner writes the Gherkin text, so keywords, indentation and tables are right by construction. T3 needs a re-run before it says anything about the models.

**Other faults found:**

- **RS ids copied with their index text.** Qwen3 1.7B wrote ids like "RS-04 form: ..." in 16 of 20 T1 cases, and they were rejected as unknown ids. The runner now keeps only the leading id, which is a deterministic clean-up. Its T1 score should be read after the re-run.
- **Truncated replies and server errors.** Phi-4-mini, SmolLM2 and Gemma 3 often stopped mid-string, and Ollama returned HTTP 500 for all 20 Phi-4-mini Gherkin cases. The likeliest cause is Ollama's default context window, which a retry with feedback outgrows. The notebook now starts Ollama with `OLLAMA_CONTEXT_LENGTH=8192`. This is unconfirmed, because the runs did not keep the replies.
- **Failed replies are now kept.** A record whose retries ran out now keeps `last_reply` (up to 4,000 characters), so the next fault can be read directly.

**Cut, provisionally.** Qwen3 8B and 4B go forward on all three tasks. Qwen3 1.7B goes forward for T2, where it is within 5 points of the best, and is re-checked on T1 after the id fix. The sub-1B models are out, except that Qwen3 0.6B keeps a place as a fine-tuning candidate if fine-tuning is needed. It is the only floor-tier model that produced valid output, but it is more than 10 points behind. Phi-4-mini is held until the context fix is re-run. The Gemma 4, Ministral 3, Granite 4.1 and SmolLM3 tags still need checking, so they have not been screened.

**Next run:** the same notebook from main once the fixes merge, with all three tasks for Qwen3 8B, 4B and 1.7B and Phi-4-mini. Keep the screen 1 run files for comparison.

## Screen 2 results (2026-11-25)

Joel re-ran the notebook after the screen 1 fixes, for the four models that went forward. It used prompts T1 1.1.0, T2 1.0.0 and T3 1.1.0, with Ollama's context raised to 8,192 tokens. Scores are on Joel's labels: 20 dev cases per task.

| Model | T1 generation | T2 validation (precision / recall) | T3 Gherkin | p95 latency (T1 / T2 / T3) |
| --- | --- | --- | --- | --- |
| Qwen3 8B | **75%** | **90%** (100% / 88%) | 10% | 14 s / 7 s / 38 s |
| Qwen3 4B | 65% | 85% (86% / 75%) | **95%** | 27 s / 7 s / 7 s |
| Qwen3 1.7B | 40% | 80% (83% / 62%) | **95%** | 45 s / 2 s / 6 s |
| Phi-4-mini 3.8B | 20% | 60% (60% / 38%) | 50% | 113 s / 112 s / 32 s |
| Checker only (B0) | — | 75% (86% / 75%) | — | under 1 ms |

**T2: Qwen3 8B meets all three T2 targets on the pilot.** It gets 90% success, 100% precision and 88% recall, against targets of 85%, 90% and 85%. It misses only P009 (system wording) and P012 (a necessary-condition classification). This is 20 dev cases, so the claim waits for the held-out split.

**T3: building the feature from parts worked.** Qwen3 4B and 1.7B pass 19 of 20 cases. The only miss is P017, the ask case ("the app to be fast"), where they drafted anyway. Qwen3 8B wrote good scenarios but left `covered_criteria` empty in 18 of 20 cases, even after feedback. Mapping criteria to scenarios in a separate list was bookkeeping the model skipped. From prompt 1.2.0, each scenario lists the numbers of the criteria it tests, the prompt numbers the criteria, and the runner derives the coverage. The retry feedback now says exactly what to add.

**T1: the asking gap is unchanged.** Qwen3 8B misses exactly the same five ask cases as in screen 1. From prompt 1.2.0, the generation prompt names the usual open decisions (an amount with no number, a period with no start, an unclear action, a non-binding modal). It also gives two invented worked examples, one draft and one ask. Neither example comes from any golden batch. Qwen3 1.7B rose from 5% to 40% with the RS id clean-up.

**Faults found and fixed:**

- **Proposals alongside a question:** the closed-vocabulary check rejected a term proposed alongside a clarifying question, because no statement used it. This cost Qwen3 1.7B the ask cases P012 and P013, and Qwen3 4B the case P012. A proposal that comes with questions and no statements is now allowed.
- **Template ids as RS ids:** Qwen3 1.7B cited template ids such as "RS-T05 (rule): ..." as RS ids. The runner now replaces a template id with that template's own RS ids. Replaying the failed replies, one more case (T1-P005) would now pass.
- **Timeouts:** Qwen3 4B and 1.7B timed out on 1 and 2 T1 cases. Phi-4-mini is still slow (p95 about 110 s) and still cuts JSON off about 3 KB in.

**Cut.** Phi-4-mini is out, on quality and latency. Qwen3 4B is the lead for T3. Qwen3 8B leads T1 and T2. Qwen3 1.7B stays as the small option for T2 and T3.

**Next run (screen 3):** prompts T1 1.2.0 and T3 1.2.0, for Qwen3 8B, 4B and 1.7B. Then run the same over batch 2 once it is labelled, which gives the first held-out numbers.

## Screen 3 results (2026-11-26)

Joel ran screen 3 on Qwen3 8B, 4B and 1.7B with prompts T1 1.2.0, T2 1.0.0 and T3 1.2.0. The run files carry those versions, so this is a new run, not a copy of screen 2. Scores are on Joel's labels: 20 dev cases per task.

| Model | T1 generation | T2 validation (precision / recall) | T3 Gherkin | p95 latency (T1 / T2 / T3) |
| --- | --- | --- | --- | --- |
| Qwen3 8B | **70%** | **90%** (100% / 88%) | **95%** | 10 s / 7 s / 18 s |
| Qwen3 4B | 65% | 85% (86% / 75%) | 90% | 23 s / 8 s / 8 s |
| Qwen3 1.7B | 40% | 80% (83% / 62%) | 95% | 45 s / 2 s / 5 s |

**Against the Phase 0 targets (85% task success on each task), on the pilot:**

- **T2 validation: met by Qwen3 8B**, with 90% success, 100% precision and 88% recall. Its two misses, P009 and P012, are the cases where a review finding should leave the form undetermined.
- **T3 Gherkin: met.** Qwen3 8B passes 19 of 20 now that each scenario lists its criteria (screen 2: 2 of 20). Qwen3 1.7B also passes 19 of 20. Its miss is P014, with steps out of order, and Qwen3 4B and 1.7B miss the ask case P017.
- **T1 generation: not met, at 70%.** Qwen3 8B drafts well: 14 of the 15 draft cases are right. The one miss is P020, where it wrote an exemption as a prohibition ("must not re-enter" instead of "need not re-enter"). It asks in none of the 5 ask cases. The asking guidance and examples in prompt 1.2.0 changed nothing. For example, it turns "Big orders need extra checks" into "A big order must undergo extra checks."

**Next for T1 (prompt 1.3.0, screen 4):** the reply now has an `open_decisions` list, which comes before the statements, so the model has to name what is open before it drafts. If it lists any open decision, the runner rejects statements and asks for one question per decision. Prompting alone didn't work, so this makes asking a structural step. If it still fails, the options are a separate ask-or-draft call before drafting, or a larger model for T1 only.

## Screen 4 results (2026-11-26)

Joel ran T1 only, on Qwen3 8B and 4B, with prompt 1.3.0 (the `open_decisions` step). The run files carry v1/1.3.0. Scores are on Joel's labels: 20 dev cases.

| Model | T1 generation | Draft cases right (of 15) | Ask cases right (of 5) | p95 latency |
| --- | --- | --- | --- | --- |
| Qwen3 8B | 55% (69% of the 16 it answered) | 10 | 1 | 45 s (timeouts) |
| Qwen3 4B | 30% | 1 | 5 | 7 s |

- **Qwen3 8B:** its first 4 cases (P001–P004) timed out, almost certainly while the model was still loading, so they say nothing about quality. On the other 16 it is where it was in screen 3. It asked only on P012 ("Big orders need extra checks") and still drafted P006, P013, P015 and P017. P020 is still an exemption written as a prohibition.
- **Qwen3 4B** swung the other way: it asked on 19 of 20 cases, with filler questions about agreed vocabulary terms ("What is the definition of 'item'?").

**Reading.** A free-text list of open decisions does not calibrate either model: 8B lists none, and 4B lists something every time. The ask decision needs to be narrower and checkable.

**Next for T1 (prompt 1.4.0, screen 5):** `open_decisions` is replaced by a fixed ambiguity checklist with five items: binding (should), amount, period, either_or and scope. For each item the model quotes the intent's words and says open or not. The runner, not the model, then decides:

- an open item must quote words that are really in the intent;
- any open item means no statements and at least one question;
- no open item means draft, not ask.

Record files keep which items were open (`ambiguity`), for diagnosis. The prompt's examples avoid every phrase in the pilot and batch 2, so batch 2 stays a fair held-out test. The notebook now loads each model before timing it, and adds Qwen3 14B (about 9 GB, so it fits the T4) as the bigger-model check. Screen 5 is T1 only, on Qwen3 8B and 14B. If the checklist still fails on 8B but 14B passes, T1 goes to the larger model and T2 and T3 stay on 8B.

## Screen 5 results (2026-11-27)

Joel ran T1 only, on Qwen3 8B and 14B, with prompt 1.4.0 (the ambiguity checklist) and the model warm-up. The run files carry v1/1.4.0, and no case timed out. Scores are on Joel's labels: 20 dev cases.

| Model | T1 generation | Draft cases right (of 15) | Ask cases right (of 5) | First pass | p95 latency |
| --- | --- | --- | --- | --- | --- |
| Qwen3 14B | **85%** | 15 | 2 | 100% | 24 s |
| Qwen3 8B | 65% | 10 | 3 | 90% | 23 s |

- **Qwen3 14B meets the T1 target on the pilot.** Every draft is right, including P020, the exemption that all earlier runs wrote as a prohibition. It asks on P012 (amount, "big") and P015 (binding, "should"). It still drafts three ask cases:
  - P006, "this year": calendar year or rolling year;
  - P013, "every 90 days": counted from when;
  - P017, "either ... or": one only, or at least one.

  On all three it marked the period or either_or item closed.
- **Qwen3 8B now asks:** it asks on P012, P015 and P017, against at most 1 of 5 before. But it marks binding open on words that are already settled:
  - P002, "can't";
  - P004, "don't have to";
  - P011, "are welcome";
  - P019 (the injection case), "write a rule";
  - P020, "don't need to".

  That cost it those 5 drafts.

**Decision.** T1 goes to Qwen3 14B, and T2 and T3 stay on Qwen3 8B, subject to batch 2 held-out results. Both fit the free T4, one at a time.

**Runner guard (after screen 5).** The binding item can only be open when the quoted words are should, ought, expected to or supposed to; otherwise the runner sends it back to be set closed. This targets 8B's five false asks. Whether 8B then drafts those cases correctly needs a run, so screen 5's numbers stay as measured.

**Next.** Run T1 on batch 2 with Qwen3 14B (and 8B, for comparison) once Joel's batch 2 labels are in, for the first held-out numbers. The remaining 14B misses, period and either_or, are the items to watch there: batch 2 has "every year" (an ask case) and several stated windows (draft cases).

## LLM baseline

The quality and cost reference is a general-purpose Claude model, run once over the same cases with the same prompts and the same runner. I recommend Claude Sonnet 5.5 (`claude-sonnet-5-5`, $2 input and $10 output per million tokens). It is the balanced tier, so the 20% cost target is meaningful. The adapter uses the official `anthropic` SDK with structured outputs and caches the system prompt. It also uses the server-side refusal fallback, which Opus 5.5 and Sonnet 5.5 support.

The estimated cost is under USD 3 for the 60 pilot cases and USD 15–30 for the full 900-case set, including retries. Every paid run needs `--max-cost`. No paid run has been made.

## Open decisions for Joel

- **API access for the baseline:** a key this environment can use, and a spending cap.
- **Where the small models run:** Ollama on Joel's machine through a remote session, or a hosted provider with an OpenAI-style endpoint. This environment can't download model weights.
