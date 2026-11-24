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
3. It asks the model for a reply that matches the task's reply schema. For Gherkin, the reply gives the feature's parts, and the runner writes the file (`eval/runner.py`, `REPLY_SCHEMAS`). The backend constrains decoding to that schema where it can: `response_format` with `json_schema` for OpenAI-style servers (Ollama, vLLM, llama.cpp server) and `output_config.format` for Claude.
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

## LLM baseline

The quality and cost reference is a general-purpose Claude model, run once over the same cases with the same prompts and the same runner. I recommend Claude Sonnet 5.5 (`claude-sonnet-5-5`, $2 input and $10 output per million tokens). It is the balanced tier, so the 20% cost target is meaningful. The adapter uses the official `anthropic` SDK with structured outputs and caches the system prompt. It also uses the server-side refusal fallback, which Opus 5.5 and Sonnet 5.5 support.

The estimated cost is under USD 3 for the 60 pilot cases and USD 15–30 for the full 900-case set, including retries. Every paid run needs `--max-cost`. No paid run has been made.

## Open decisions for Joel

- **API access for the baseline:** a key this environment can use, and a spending cap.
- **Where the small models run:** Ollama on Joel's machine through a remote session, or a hosted provider with an OpenAI-style endpoint. This environment can't download model weights.
