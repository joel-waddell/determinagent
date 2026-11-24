# Fine-tuning readiness (Phase 0.5)

The question this answers is whether we could fine-tune a small model for a task if prompt work leaves it short of its targets (0.4). It needs answering before fine-tuning is needed. It covers RuleSpeak generation (T1), RuleSpeak validation (T2) and Gherkin requirements (T3). The JavaScript J2 task has its own thread and reuses the compute and serving findings here.

The verdict below is a draft. Two inputs are still open: where Joel wants production serving, and what the 0.4 screen shows about which tasks, if any, miss their targets.

## Verdict

| Resource | Verdict | Gap | LOE to close |
| --- | --- | --- | --- |
| Data | **Not ready** | 0 labelled cases so far, and 200 dev cases per task is too few on its own | 3–5 sessions for a checker-filtered synthetic pipeline, plus Joel's spot review |
| Compute | **Ready for models up to about 4B; partly ready for 8B** | Free T4 sessions are time-limited, and 8B QLoRA on 16 GB is tight | 1 session to add checkpointing to the training notebook |
| Skills | **Ready, if training is scripted** | Hyperparameter search needs a run budget | 2–3 sessions for a training and evaluation notebook |
| Serving | **Ready for evaluation, not for production** | No always-on host yet | A decision from Joel, then 1–2 sessions |

The total to reach ready is 7 to 11 agent sessions, plus Joel's spot-review time on synthetic data. None of it should start until the 0.4 screen shows that a task needs fine-tuning.

## Data

**What exists.** There is a 60-case pilot, labelled by the domain expert. The full golden set is planned at 300 cases per task: 200 for dev and 100 held out ([golden-set.md](golden-set.md)). Held-out cases can never be used for training, so at most 200 labelled pairs per task come from the golden set.

**What fine-tuning needs.** For a narrow task with LoRA, a few hundred clean pairs per task is a reasonable floor, and 1,000 to 2,000 is more comfortable. These are rules of thumb, not measurements. The first fine-tuning run should check them with a learning curve at 25%, 50% and 100% of the data.

**How to get there.** The checkers make synthetic data cheap to verify, which most domains lack:

1. **T1 generation.** A larger model writes candidate statements for many varied intents. Each candidate is kept only if it passes the RuleSpeak checker and its guidance type matches the intent. Joel then spot-reviews a sample for fidelity, which the checker can't judge.
2. **T2 validation.** Known defects are injected into conformant statements: dropping the keyword, mixing keywords, putting the condition first, using system wording, and so on. The checker confirms each defect, so most labels come out right by construction. Meaning-level cases (undetermined) still need Joel.
3. **T3 Gherkin.** Typed requirements are expanded into features, and only features that pass the Gherkin profile and cover every criterion are kept. Joel spot-reviews whether the scenarios test the right thing.
4. **Decontamination.** Synthetic data is never generated from held-out inputs, and a near-duplicate check against the held-out split runs before training.

**Verdict: not ready.** The gap is labelled data plus a synthetic pipeline. The pipeline reuses the eval runner and the checkers, so it costs 3 to 5 sessions. Joel's time is the bigger cost: about 1 to 2 hours per task to spot-review a 10% sample of 1,000 synthetic pairs.

## Compute

Parameter-efficient fine-tuning (LoRA or QLoRA) of the shortlisted small models fits the free GPUs the screening notebook already uses:

- **Models up to about 4B parameters** (Qwen3 0.6B to 4B, Gemma 3 270M, SmolLM2, Phi-4-mini). QLoRA on a 16 GB T4 is routine for these sizes. A run over 1,000 to 2,000 short pairs should take well under an hour, which is my estimate and has not been measured.
- **8B models.** QLoRA fits on a T4 only with memory-saving settings (a 4-bit base, gradient checkpointing, short sequences). It is slower and closer to the session limits.
- **Limits.** Colab's free tier ends idle or long sessions. Kaggle gives a weekly GPU quota, about 30 hours at the time of writing, which should be checked. Either is enough for a handful of runs per task. If 8B is needed, or many runs are, a paid GPU at a few dollars an hour is the step up.

**Verdict: ready for models up to about 4B, partly ready for 8B.** The gap is checkpointing, so a stopped session can resume. That is one session's work, added to the training notebook.

## Skills

This program has no ML engineer. Training would be scripted the way the screen is: agent sessions write a notebook, Joel runs it on a free GPU, and the results come back as files. The notebook would hold fixed LoRA settings from the library defaults and a small sweep (learning rate times epochs, up to about 6 runs). It would evaluate each run with the same runner and gate as everything else, so a fine-tuned model has to win the same paired comparison as a prompted one.

**Verdict: ready, if training is scripted.** The gap is the training and evaluation notebook, at 2 to 3 sessions. Judging whether a learning curve has flattened, or whether a model overfits, is covered by the gate's held-out check and doesn't need a specialist.

## Serving

- **For evaluation:** a LoRA adapter can be merged into the base model or loaded beside it. Ollama can load a GGUF base model with an adapter through a Modelfile `ADAPTER` line, and vLLM can serve several LoRA adapters on one base model. Both expose the OpenAI-style endpoint the runner already uses, so a fine-tuned model is just another `--model` spec.
- **For the POC and beyond:** something always-on has to host the chosen models. Free notebooks can't do that. The options are Joel's own machine through Ollama, a small GPU VM, or a hosted inference provider that accepts custom adapters. A model up to 4B runs acceptably on a CPU or Apple silicon, so a GPU may not be needed for T2.

**Verdict: ready for evaluation, not for production.** Production needs a hosting decision from Joel, which depends on the screen's results. Once he decides, setup is 1 to 2 sessions.

## When to start

Start fine-tuning only for a task whose best prompted candidate misses its targets on the held-out split after prompt work. Use the smallest model within reach of the target as the base. If the 0.4 screen shows every task meeting its targets with a prompted model, this assessment stays on file and nothing more is built.
