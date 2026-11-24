# Execution sandbox (Phase 0.8, Amendment 1)

The sandbox runs model-written JavaScript and reports what happened in the `js_execution` contract. It has no network, file system or child processes, enforces time and memory limits, and uses a fixed clock and seed. Any attempt to reach the host is recorded as a violation, and any violation fails the gate. The model never sees or fills the report.

- Code: [`js/src/sandbox/`](../js/src/sandbox/) (`index.js` is the parent, `child.mjs` the isolated runner)
- CLI: [`js/bin/js-sandbox.js`](../js/bin/js-sandbox.js), JSON in and out
- Python: [`determinagent.sandbox`](../src/determinagent/sandbox.py)
- Profile and limits: [`src/determinagent/spec/javascript.yaml`](../src/determinagent/spec/javascript.yaml)

```sh
echo '{"code": "export function inc(x) { return x + 1 }",
       "spec": {"name": "inc", "params": [{"name": "x", "type": "number"}], "returns": {"type": "number"}, "behavior": "Add one."},
       "tests": [{"name": "one", "args": [1], "returns": 2}]}' | node js/bin/js-sandbox.js
echo '{"info": true}' | node js/bin/js-sandbox.js      # how this machine isolates code
```

```python
from determinagent import sandbox
report = sandbox.execute(code, spec=spec, tests=sandbox.tests_from_spec(spec) + hidden_tests)
sandbox.accepted(report)
```

## What a run does

1. **Lint.** The [JS checker](domain/javascript.md) parses and lints the module in the parent process. Nothing runs yet. If the module does not parse, every test is reported as `skip` and the run stops.
2. **Spawn.** A fresh child Node process starts for every module, so no state leaks between runs.
3. **Load.** The child compiles the module as an ES module inside a new `vm` context and refuses every import at link time.
4. **Test.** Each test runs inside that context, one at a time, under the time limit.
5. **Report.** The parent assembles `js_execution`: `parsed`, `lint`, per-test `status` and `message`, `violations`, and the `environment` (Node version, profile version, limits, clock and seed).

## Isolation layers

Each layer stands on its own, so a gap in one is covered by the next.

| Layer | What it blocks |
| --- | --- |
| Network namespace (`unshare -rn`) | All network access: the child has no interfaces. Used automatically on Linux where unprivileged user namespaces are allowed. `DETERMINAGENT_SANDBOX_NETNS=require` fails closed without it, and `=off` skips it. |
| Node permission model (`--permission`, or `--experimental-permission` on Node 20) | File system access beyond reading the runner file itself, child processes, worker threads, native add-ons and WASI. |
| Child process settings | An empty environment (only `TZ=UTC` and `LANG=C.UTF-8`), working directory `/`, a V8 heap limit, a fixed stack size and code generation from strings disabled. |
| `vm` context | Only the ECMAScript built-ins. The prelude adds a fixed `Date`, a seeded `Math.random`, a no-op `console`, and a trap on every host global (`process`, `require`, `fetch`, `Buffer`, `crypto`, the timers and others). `eval`, `Function` and WebAssembly compilation are disabled. |
| No host objects inside | Nothing from the host realm is ever handed to the module. Test values cross as JSON strings and are rebuilt inside, errors thrown into the module are created inside, and the host never calls `then()` on a promise from the module. A host object would let code climb `constructor.constructor` to the host's `Function`. |
| Time | Each test, and loading the module, runs under the `vm` timeout. Async results are polled until the deadline. The parent kills the child at a wall-clock budget, which also stops loops that only yield to microtasks. |
| Memory | `--max-old-space-size` (64 MB by default). Running out is a `memory` violation. |

A violation is recorded by kind, from the profile: `network` (fetch, WebSocket, an import of net or http), `filesystem` (an import of fs or path, `__dirname`), `process` (process, require, Buffer, child_process, any other import), `nondeterminism` (crypto, performance, timers), `timeout` and `memory`. A probe such as `typeof process` counts as an attempt.

The escape suite in [`js/test/sandbox.test.js`](../js/test/sandbox.test.js) tries each of these, along with the `constructor` chain, an import rejection carrying a host error, tampering with the harness, and WebAssembly. CI runs it on Node 20 and 22.

## Determinism

- The clock is fixed at `2026-01-01T00:00:00Z`: `new Date()`, `Date()` and `Date.now()` all return it. Dates built from arguments behave normally.
- `Math.random` is a seeded generator (mulberry32, seed 42) that is reset before every test, so test order does not matter.
- The time zone is UTC and the locale environment is fixed.
- Durations are left out of the report by default (`durations: true` adds `duration_ms`), so two runs of the same module give byte-identical reports. A test checks this.

## Tests

A test is one of three shapes. Values are JSON, and values JSON cannot hold use a `$js` marker.

| Shape | Passes when |
| --- | --- |
| `{name, args, returns}` | The function returns a value deeply equal to `returns`. For an async spec it must return a Promise that resolves to it. |
| `{name, args, throws}` | The function throws (or for async, rejects). `throws: "RangeError"` requires that error name. `"RangeError: negative"` also requires the message to contain "negative". Any other text must appear in the message. |
| `{name, code}` | A snippet that runs as the body of `function (fn, assert)` inside the context does not throw. `assert` has `equal` (deep), `notEqual`, `ok`, `throws`, `rejects` and `deepClone`. Snippets check what examples cannot express, such as "does not mutate its input". They come from the golden set, never from the model. |

`$js` values: `{"$js": "undefined"}`, `"NaN"`, `"Infinity"`, `"-Infinity"`, `"-0"`, `{"$js": "bigint", "value": "12"}`, `{"$js": "Date", "value": "2026-03-01T00:00:00Z"}`, `{"$js": "Map", "entries": [[k, v]]}` and `{"$js": "Set", "values": [...]}`.

Deep equality uses `Object.is` for primitives, so `NaN` equals `NaN` and `0` does not equal `-0`. Arrays and plain objects compare by own keys and prototype, Dates by time, Maps and Sets by content regardless of order.

## Design decisions

- **A process per module, not per test.** A fresh process costs about 50 ms. Per test would make a 300-case run take minutes instead of seconds, and the `vm` timeout already isolates tests in time. Tests in one module share module state, as they would in a real import.
- **Not Node's test runner.** `node:test` runs tests in the host realm, so the module would have to run there too, with `process` in reach. The sandbox has its own small harness inside the context instead. It reports the same pass, fail, skip and timeout statuses.
- **Built-ins are not frozen.** Freezing `Object.prototype` breaks ordinary code that assigns a key such as `counts.constructor` (the "override mistake"). The harness instead captures every built-in it uses before the module loads, so a module that patches `Object.is` or `JSON.stringify` only fools itself. Prototype changes are also lint errors.
- **The network block depends on the OS.** Node 22's permission model has no network switch, so the network namespace is what blocks sockets. Where it is unavailable (macOS, or CI runners that restrict user namespaces), network isolation rests on the `vm` context having no network API and on no host object reaching it. For production use, run the sandbox in a container with networking off.
- **The gate treats every violation as a failure.** A module that probes `typeof process` and then computes the right answer is still rejected. The J2 profile has no reason to touch host globals, so any probe is a signal worth failing on.
