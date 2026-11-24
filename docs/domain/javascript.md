# JavaScript profile (Phase 0.1, Amendment 1)

The JavaScript domain has three tasks. J2 Generate ships in tranche 1. J1 Advise and J3 Correct follow in tranche 2 and use the same profile. This page defines what "well-formed" means for model-written JavaScript, precisely enough that the checker and the [sandbox](../sandbox.md) decide acceptance and the model does only the semantic work.

- Machine-readable profile: [`src/determinagent/spec/javascript.yaml`](../../src/determinagent/spec/javascript.yaml), version 0.1.0
- Checker: [`js/src/conformance/javascript.js`](../../js/src/conformance/javascript.js), built on ESLint's in-memory `Linter`
- Contracts: `js_function_spec`, `js_source`, `js_finding` and `js_execution` in [contracts v1](../contracts.md#javascript-tasks-amendment-1)

The checker and sandbox exist only in the JavaScript core. Python calls them through [`determinagent.sandbox`](../../src/determinagent/sandbox.py), which runs `js/bin/js-sandbox.js`, so there is one implementation and no parity test for this profile.

## Scope

| Item | Rule |
| --- | --- |
| Language | Plain ECMAScript in an ES module. The parser is pinned to ES2023, the newest level Node 20 implements in full. No TypeScript, JSX or frameworks. |
| Runtime | Node 20 or later, ECMAScript built-ins only. |
| Imports | None. Every J2 function is pure computation over its arguments, so it needs no module. A static or dynamic import is a finding and is blocked at run time. |
| Globals | The ECMAScript built-ins and a no-op `console`. Host globals such as `process`, `require`, `fetch`, `Buffer`, `crypto`, `performance` and the timers are not available. |
| Size | At most 200 lines (`code_text` allows 20,000 characters). |
| Shape (J2) | The module exports the spec's function by its name (`export: named`, the default) or as the default export. It is `async` only when the spec says so. |

## Acceptance

A module is **accepted** when it parses, has no error-severity finding, passes every test it is run with, and the sandbox records no violation. Warnings are reported but do not fail it. For J2 the tests are the spec's visible examples plus the golden case's hidden tests.

| Check | Who does it |
| --- | --- |
| The module parses as ES2023 | Checker (`JS-SYN-001`) |
| It exports the spec's function, the right way, with the right async-ness | Checker (`JS-MOD-001` to `-006`) |
| No imports, no code from strings, no host globals, no prototype changes | Checker flags; sandbox blocks and records a violation |
| Lint rules for correctness and idiom | Checker |
| It returns the right values and throws the right errors | Sandbox, from examples and hidden tests |
| It does not read the clock, randomness, network, file system or processes | Sandbox (fixed clock, seeded random, traps, isolation) |
| The function does what the behavior text meant, beyond the tests | Model, then rubric (later); mutation-checked hidden tests narrow the gap |

## Defect taxonomy

Codes are `JS-<AREA>-<NNN>`, as the `js_finding` contract requires. Severity comes from the code, not from the ESLint rule, so one place sets it.

| Area | Codes | What it covers |
| --- | --- | --- |
| SYN | 001 | The module does not parse (basis `parser`) |
| MOD | 001–007 | Module shape: missing or wrongly exported function, async mismatch, imports, not a function, parameter count (warning), length (warning) |
| SEC | 001–004 | Code from strings, host globals, prototype changes, reassigned read-only globals |
| DET | 001 | `Math.random` or `Date.now` (warning: the sandbox makes them deterministic, but a spec function should not depend on them) |
| COR | 001–018 | Correctness lint: undefined names, constant reassignment, duplicate keys, unreachable code, NaN comparisons, fall-through, assignment in conditions, and more |
| STY | 001–007 | Readability and idiom, all warnings: unused variables, loose equality, `var`, `let` where `const` would do, console output, direct `hasOwnProperty`, empty blocks |
| TST | 001–002 | A test fails or times out (reserved for J1 and J3, which report test results as findings) |

The full list, with the ESLint rule behind each code, is in the profile. The rule set is a deliberate subset of `eslint:recommended` plus security and determinism rules. Rules that judge style a model cannot see from the spec, such as formatting, are left out.

## Design decisions

- **Severity lives on the code.** The YAML maps each ESLint rule to one code and the code sets the severity, so the taxonomy is the single source of truth.
- **Inline ESLint comments are ignored.** `noInlineConfig` is on, so a model cannot write `/* eslint-disable */` to switch rules off.
- **The export check is a profile rule.** `determinagent/spec-export` is a small ESLint rule configured from the J2 spec. It reports through the same path as every other rule.
- **Blocked globals get a specific code.** They are declared to the linter, so `no-undef` stays quiet and `no-restricted-globals` reports `JS-SEC-002` with the reason.
- **Async in one direction only.** An `async` function where the spec is sync is an error (`JS-MOD-003`). A sync function where the spec is async is caught by the sandbox, which requires a Promise.
- **Warnings never fail a case.** Style is reported for J1 and for review, but J2 acceptance depends on behavior, not taste.

## Versioning

The profile carries a `version`, and every sandbox report records it. Changing a rule, a code or a limit changes what "accepted" means for the golden set, so it goes through the same review as the golden set.
