# Contracts v1 (Phase 0.7)

Every request entering DeterminAgent, every response leaving it, and every artifact or governance record it hands on is defined by a JSON Schema in [`src/determinagent/contracts/v1/`](../src/determinagent/contracts/v1/). Both cores validate against these same files: `validate(name, obj)` in [`js/src/contracts.js`](../js/src/contracts.js) (Ajv) and in [`determinagent/contracts`](../src/determinagent/contracts/__init__.py) (jsonschema). A parity test requires both to give the same validity on every shared example.

> Status: **v1.0 release candidate.** The plan's 0.7 gate freezes these schemas. They are frozen when the 0.6 intake sprint has chosen the intake pattern, because that choice may add typed intent fields. Until then the only changes allowed are additive optional fields.

## Schemas

| Contract | `$id` | What it is |
| --- | --- | --- |
| `request` | `urn:determinagent:contracts:v1:request` | The typed request: `schema_version`, `request_id`, `task`, `submitted_at`, optional `domain`, and a `payload` that must match the task. |
| `response` | `urn:determinagent:contracts:v1:response` | `status` (resolved, rejected or violated), a `reason_code` whenever the status is not resolved, the `route` taken, the task's `output`, and `receipt_head` (from Phase 2). |
| `handoff-artifact` | `urn:determinagent:contracts:v1:handoff-artifact` | One accepted rule, advice statement or feature for a downstream tool, with its checker outcome, trace and source request. |
| `governance-change` | `urn:determinagent:contracts:v1:governance-change` | One governance register entry: change type, versions, triggering receipts, gate results, approval and rollout. |
| `common` | `urn:determinagent:contracts:v1:common` | Shared definitions: the task inputs and outputs (three RuleSpeak and Gherkin tasks, three JavaScript tasks), `finding`, `trace_entry`, `question`, `route`, reason codes and exit statuses. |

You can validate a single definition from `common` by name, for example `validate("rulespeak_generation_output", obj)`.

## Design decisions

- **JSON Schema 2020-12, with URN `$id`s.** The schemas never need a network fetch, and the same files serve both languages.
- **Closed objects.** Every object sets `additionalProperties: false`, so input is constrained at the edge. A stray field such as an injected `prompt` is a schema error, not something a node might read.
- **Typed fields first, with free text as the exception.** An `intent` needs either `subject` and `action` (with an optional `constraint_type`, conditions and qualification) or `free_text`. A Gherkin `requirement` is typed as role, capability, benefit and acceptance criteria. The golden set's T1 intents use `free_text` until 0.6 decides on typed intake.
- **Size limits.** A statement or intent is capped at 500 characters, a feature at 4,000, and a request at 50 statements and 200 vocabulary terms. Over-size input is rejected before any model runs.
- **The task and payload must agree.** The schema enforces it, and the router still verifies the route itself (Phase 1.2).
- **Asking is a valid result.** Generation output may contain `questions` instead of `statements`, and Gherkin output may contain questions instead of a feature. Missing business decisions stay explicit (RS-17) instead of being guessed. An output with neither is invalid.
- **Every statement carries a trace.** A generated statement needs at least one `trace_entry` (a claim, RS ids, source and application), following the response contract in RuleSpeak-Agent.md. Validation results report `form` and `fidelity` with the same values as that contract.
- **Checker findings are the finding contract.** The `finding` definition is exactly what the RuleSpeak checker returns. `basis` also allows `model`, for findings an SLM adds.
- **Exit statuses come from Phase 2.2.** `resolved` needs an output and no reason code. `rejected` and `violated` need a `reason_code`.
- **Reason codes are an open-ended enum.** New codes may be added, but an existing code is never given a new meaning: `SCHEMA_INVALID`, `PAYLOAD_TASK_MISMATCH`, `UNSUPPORTED_SCHEMA_VERSION`, `NO_ROUTE`, `INPUT_TOO_LARGE`, `OUTPUT_SCHEMA_INVALID`, `OUTPUT_NONCONFORMANT`, `MODEL_ERROR`, `MODEL_TIMEOUT`, `POLICY_VIOLATION`, `SANDBOX_VIOLATION` and `SANDBOX_TIMEOUT`.
- **The governance rules are in the schema.** A change cannot be `applied` without a passing gate. A harness or golden-set change cannot be applied without a named human approval. These are the plan's change-control rules, so no client can skip them.
- **Hashes are SHA-256 in lowercase hex.** That covers `receipt_head` and the triggering receipts, ready for the Phase 2.3 receipt chain.

## JavaScript tasks (Amendment 1)

The program now has a JavaScript domain. J2 generation ships in tranche 1, and J1 advise and J3 correct follow in tranche 2. All three contracts are drafted now, so they freeze with v1 and tranche 2 needs no v2 change.

| Task | Input | Output | Filled deterministically |
| --- | --- | --- | --- |
| `js_generation` (J2) | `spec`, a `js_function_spec`: name, typed params and return (JSDoc type strings), behavior, examples (args with returns or throws) and constraints | `module` (a `js_source`), assumptions, or `questions` instead | `execution`, the sandbox report |
| `js_advice` (J1) | `source`, optional `focus` areas and a `question` | `findings` (`js_finding` with a line range, severity, category and basis), an optional `answer`, `questions` | Parser and lint findings (`basis` parser or lint) |
| `js_correction` (J3) | `source` and a `failure` (test failure, runtime error or lint finding), optional visible `tests` and `spec` | The corrected `module`, an optional `patch` for review, `explanation`, or `questions` | `execution` |

Design choices:

- **The sandbox report is its own contract.** `js_execution` records whether the code parsed, the lint findings, per-test results, any blocked attempts (`network`, `filesystem`, `process`, `timeout`, `memory`, `nondeterminism`) and the environment (Node version, profile version, limits, fixed clock and seed), so a run can be replayed exactly. The model never fills it.
- **Hidden tests stay out of the request.** A J2 request carries the visible examples only. The golden case holds the reference solution and the hidden tests.
- **J3 returns a whole module, not just a patch.** The module is what the sandbox runs, so a malformed diff can't hide a failure. `patch` is derived from it for review.
- **JS findings have their own shape.** `js_finding` codes are `JS-<AREA>-<NNN>` from the JS defect taxonomy, separate from the RuleSpeak and Gherkin `finding`.
- **Code has a larger size cap.** `code_text` allows up to 20,000 characters (about 200 lines, the profile's scope). A `js_module` handoff must carry its `execution` report, and other artifact types must not.
- **New reason codes:** `SANDBOX_VIOLATION` (the code tried something the sandbox blocks) and `SANDBOX_TIMEOUT`.

## Orchestration interface

The plan starts orchestration synchronously behind an interface, so that a durable engine can replace it later without changing any node. The interface Phase 1.4 implements is:

```
handle(request) -> response                      # validates both against these contracts
node(state) -> state                              # validate_input, route, execute, validate_output
state = { request, route?, output?, status, reason_code?, receipts[] }
```

Each node gets the state and returns a new state. A node never calls another node. Only the orchestrator sequences them, which is the seam a durable workflow engine plugs into.

## Versioning

- `schema_version` is `"1.0"` in every document. Additive optional fields are allowed within 1.x, as long as consumers validate with the same schema version or a newer one.
- Removing a field, renaming one, or narrowing a type means a v2 directory. A request with an unknown `schema_version` is rejected with `UNSUPPORTED_SCHEMA_VERSION`.
