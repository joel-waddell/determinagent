# Level of effort: actuals

The baseline estimates are in [program-of-work.md](program-of-work.md#level-of-effort). One agent session is one reviewed, committed increment. Record actuals here as workstreams close, then recalibrate the estimates.

| Workstream | Estimate | Actual so far | Notes |
| --- | --- | --- | --- |
| Repo scaffold | (not estimated) | 1 (shared with 0.1) | README, packaging, CI |
| 0.1 Domain specification | 6–10 | 2 | Draft specs and checkers, then RuleSpeak profile v0.2.0 after Joel's review. |
| JavaScript core | (not estimated) | 1 | Port alongside Python, shared fixtures, parity test |
| 0.2 Golden evaluation set | 16–24 | 3 | Design, sizing, pilot batch of 60, workbook tooling; pilot labels imported, drafting lessons, B0 re-run; batch 2 of 120 drafted. Labelling is expert time, not counted. |
| 0.7 Contracts | 4–10 | 1 | v1.0 release candidate: request, response, task I/O, handoff and governance schemas, validators in both cores. |
| 0.3 Baselines and targets | 6–10 | 1 | Harness, gate, oracle and checker baselines. Model baselines pending model access. |
| 0.4 SLM strategy | 8–14 | 3 | Shortlist, selection method, prompts v1, adapters (Ollama/OpenAI-style, Claude) and the runner with checker-driven retries; screens 1 to 5 scored on expert labels, with runner fixes (Gherkin from parts, per-scenario coverage, id clean-up, kept replies), prompts T1 1.4.0 (ambiguity checklist) and T3 1.2.0, a model warm-up in the notebook, and a runner guard on the binding item. |
| 0.7 Contracts, JS (Amendment 1) | 3–4 (tranche 1 share) | 1 | J1–J3 inputs and outputs, sandbox report, handoff `js_module`, two reason codes; examples in both cores. |
| 0.5 Fine-tuning readiness | 4–6 | 1 | Draft verdict for data, compute, skills and serving; 7–11 sessions to close the gaps if fine-tuning is needed. |
| 0.6 Intake UX design sprint | 10–20 | 1 | Steps 1–3: user map, three concepts, typed-form and template-editor mock-ups, test plan and decision rule. Testing pending. |
| 0.1 Domain specification, JS (Amendment 1) | 4–6 (tranche 1 share) | 1 (shared with 0.8) | JS profile v0.1.0 as YAML: ESLint rule set, defect taxonomy, export rule, checker and fixtures, in `js/` only. |
| 0.8 Execution sandbox | 6–12 | 1 (shared with 0.1) | Child process with permission model, network namespace, heap limit; vm context with fixed clock, seeded random and host-global traps; escape suite; Python bridge. |
| 0.2 Golden set, J2 (Amendment 1) | 7–12 (tranche 1 share) | 1 (shared with 0.3/0.4 J2) | J2 design, 20-case pilot with reference solutions and hidden tests, mutation verifier, workbook sheet. Labelling is expert time, not counted. |
| 0.3/0.4 J2 hooks (Amendment 1) | 4–8 (tranche 1 share) | (shared with 0.2 J2) | J2 scoring, `js_test_pass_rate` and `sandbox_violation_rate` in the gate, runner with sandbox feedback on visible examples, prompt v1. Model runs pending model access. |
| 0.2 Golden set, J2 pilot review | (within 0.2 J2) | 1 | Imported the pilot labels: 8 agreed, 5 corrected, 7 ask cases split into clarified variants; structural mutants; source check for adversarial cases; re-check workbook. |
| 0.2 Golden set, J2 pilot re-check | (within 0.2 J2) | 1 | Ported the expert's in-sheet edits to 7 cases, closed 2 test gaps the verifier found, comment-blind source check with P020 evidence, verifier on the Node 20 and 22 CI matrix. |
| 0.2 Golden set, J2-P020 final check | (within 0.2 J2) | 1 | ASCII vowel rule and dotted-I regression test; grader policy controls as a fixture, a runner script and recorded evidence. |
