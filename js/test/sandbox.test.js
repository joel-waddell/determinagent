// The 0.8 sandbox: results, limits, determinism and the escape suite.
// Every escape attempt must end with a recorded violation or a plain failure,
// never with the module reaching the host.
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { validate } from '../src/contracts.js'
import { accepted, execute, isolation, testsFromSpec } from '../src/sandbox/index.js'
import { mutants } from '../src/sandbox/mutate.js'

const SPEC = {
  name: 'inc',
  params: [{ name: 'x', type: 'number' }],
  returns: { type: 'number' },
  behavior: 'Add one.',
  examples: [
    { args: [1], returns: 2 },
    { args: [-1], returns: 0 },
  ],
}
const TESTS = testsFromSpec(SPEC)
const run = (code, extra = {}) => execute({ code, spec: SPEC, tests: TESTS, ...extra })
const statuses = (r) => r.tests.map((t) => t.status)

function valid(r) {
  assert.deepEqual(validate('js_execution', r), [], JSON.stringify(r))
}

describe('results', () => {
  test('a correct module is accepted', async () => {
    const r = await run('export function inc(x) {\n  return x + 1\n}\n')
    valid(r)
    assert.ok(accepted(r), JSON.stringify(r))
    assert.deepEqual(statuses(r), ['pass', 'pass'])
    assert.deepEqual(r.violations, [])
    assert.equal(r.environment.clock, '2026-01-01T00:00:00Z')
    assert.equal(r.environment.seed, 42)
  })

  test('a wrong answer fails with expected and actual', async () => {
    const r = await run('export function inc(x) {\n  return x * 2\n}\n')
    valid(r)
    assert.deepEqual(statuses(r), ['pass', 'fail'])
    assert.match(r.tests[1].message, /expected 0, got -2/)
  })

  test('a module that does not parse skips its tests', async () => {
    const r = await run('export function inc(x) { return x +')
    valid(r)
    assert.equal(r.parsed, false)
    assert.deepEqual(statuses(r), ['skip', 'skip'])
  })

  test('lint errors fail acceptance even when the tests pass', async () => {
    const r = await run('export function inc(x) {\n  return eval("x + 1")\n}\n')
    assert.ok(r.lint.some((f) => f.code === 'JS-SEC-001'))
    assert.ok(!accepted(r))
  })

  test('throws, typed values and snippet tests', async () => {
    const spec = {
      name: 'stats',
      params: [{ name: 'xs', type: 'number[]' }],
      returns: { type: 'object' },
      behavior: 'x',
    }
    const code = `export function stats(xs) {
  if (!Array.isArray(xs)) throw new TypeError('xs must be an array')
  if (xs.length === 0) return { mean: NaN, seen: new Set(), last: undefined }
  return { mean: xs.reduce((a, b) => a + b, 0) / xs.length, seen: new Set(xs), last: xs.at(-1) }
}
`
    const tests = [
      { name: 'empty', args: [[]], returns: { mean: { $js: 'NaN' }, seen: { $js: 'Set', values: [] }, last: { $js: 'undefined' } } },
      { name: 'two', args: [[1, 3]], returns: { mean: 2, seen: { $js: 'Set', values: [3, 1] }, last: 3 } },
      { name: 'type', args: ['no'], throws: 'TypeError: must be an array' },
      { name: 'wrong type', args: ['no'], throws: 'RangeError' },
      { name: 'no mutation', code: 'const xs = [1, 2]\nfn(xs)\nassert.equal(xs, [1, 2])' },
      { name: 'snippet failure', code: 'assert.equal(fn([1]).mean, 2)' },
    ]
    const r = await execute({ code, spec, tests })
    valid(r)
    assert.deepEqual(statuses(r), ['pass', 'pass', 'pass', 'fail', 'pass', 'fail'], JSON.stringify(r.tests))
    assert.match(r.tests[3].message, /threw TypeError.*expected RangeError/)
  })

  test('async functions are awaited; a sync result where async is promised fails', async () => {
    const spec = { ...SPEC, async: true }
    const ok = await execute({ code: 'export async function inc(x) { return x + 1 }', spec, tests: TESTS })
    assert.deepEqual(statuses(ok), ['pass', 'pass'])
    const sync = await execute({ code: 'export function inc(x) { return x + 1 }', spec, tests: TESTS })
    assert.deepEqual(statuses(sync), ['fail', 'fail'])
    const rejects = await execute({
      code: 'export async function inc(x) { if (x < 0) throw new RangeError("negative"); return x + 1 }',
      spec,
      tests: [{ name: 'rejects', args: [-1], throws: 'RangeError' }],
    })
    assert.deepEqual(statuses(rejects), ['pass'])
  })

  test('a default export is found', async () => {
    const r = await execute({ code: 'export default (x) => x + 1', spec: { ...SPEC, export: 'default' }, tests: TESTS })
    assert.deepEqual(statuses(r), ['pass', 'pass'])
  })

  test('a missing export fails every test', async () => {
    const r = await execute({ code: 'export const other = 1', spec: SPEC, tests: TESTS })
    assert.deepEqual(statuses(r), ['fail', 'fail'])
    assert.match(r.tests[0].message, /does not export/)
  })
})

describe('determinism', () => {
  test('the clock is fixed and Math.random is seeded per test', async () => {
    const code = 'export function inc(x) { return [new Date().toISOString(), Date.now(), Math.random(), Date()] }'
    const t = [
      { name: 'a', code: 'globalThis.first = fn(0)' },
      { name: 'b', code: 'const v = fn(0)\nassert.equal(v[0], "2026-01-01T00:00:00.000Z")\nassert.equal(v[1], 1767225600000)\nassert.equal(v[2], globalThis.first[2])\nassert.ok(v[3].startsWith("Thu Jan 01 2026"))' },
    ]
    const r = await execute({ code, spec: SPEC, tests: t })
    assert.deepEqual(statuses(r), ['pass', 'pass'], JSON.stringify(r.tests))
  })

  test('two runs give the same report', async () => {
    const code = 'export function inc(x) { return x + Math.floor(Math.random() * 3) }'
    const a = await run(code)
    const b = await run(code)
    assert.deepEqual(a, b)
  })

  test('durations are reported only when asked for', async () => {
    const r = await run('export function inc(x) { return x + 1 }', { durations: true })
    assert.ok(r.tests.every((t) => typeof t.duration_ms === 'number'))
    valid(r)
  })
})

describe('limits', () => {
  test('an endless loop times out', async () => {
    const r = await run('export function inc(x) {\n  for (;;) x++\n}\n', { limits: { timeout_ms: 200 } })
    valid(r)
    assert.deepEqual(statuses(r), ['timeout', 'timeout'])
    assert.deepEqual(r.violations, ['timeout'])
  })

  test('an endless loop at load time times out', async () => {
    const r = await run('for (;;) {}\nexport function inc(x) { return x + 1 }', { limits: { timeout_ms: 200 } })
    assert.deepEqual(r.violations, ['timeout'])
    assert.ok(!accepted(r))
  })

  test('a promise that never settles times out', async () => {
    const spec = { ...SPEC, async: true }
    const r = await execute({ code: 'export function inc() { return new Promise(() => {}) }', spec, tests: TESTS, limits: { timeout_ms: 200 } })
    assert.deepEqual(statuses(r), ['timeout', 'timeout'])
    assert.deepEqual(r.violations, ['timeout'])
  })

  test('an endless microtask loop is stopped by the wall clock', async () => {
    const spec = { ...SPEC, async: true }
    const r = await execute({ code: 'export async function inc(x) { for (;;) await null }', spec, tests: TESTS.slice(0, 1), limits: { timeout_ms: 100 } })
    assert.deepEqual(statuses(r), ['timeout'])
    assert.deepEqual(r.violations, ['timeout'])
  })

  test('memory is capped', async () => {
    const r = await run('export function inc(x) {\n  const a = []\n  for (;;) a.push(new Array(1e6).fill(x))\n}\n')
    valid(r)
    assert.ok(r.violations.includes('memory'), JSON.stringify(r))
    assert.ok(!accepted(r))
  })

  test('deep recursion is an ordinary failure', async () => {
    const r = await run('export function inc(x) {\n  return inc(x) + 1\n}\n')
    assert.deepEqual(statuses(r), ['fail', 'fail'])
    assert.match(r.tests[0].message, /RangeError/)
    assert.deepEqual(r.violations, [])
  })
})

// Each attempt: [name, code, the violation it must record (or null), and it must not pass].
const ESCAPES = [
  ['process global', 'export function inc(x) { return process.pid }', 'process'],
  ['require', 'export function inc(x) { return require("fs") }', 'process'],
  ['typeof probe', 'export function inc(x) { return typeof process === "undefined" ? x + 1 : 0 }', 'process'],
  ['Buffer', 'export function inc(x) { return Buffer.from("a").length + x }', 'process'],
  ['fetch', 'export function inc(x) { return fetch("http://127.0.0.1:1") }', 'network'],
  ['WebSocket', 'export function inc(x) { return new WebSocket("ws://127.0.0.1:1") }', 'network'],
  ['crypto', 'export function inc(x) { return crypto.randomUUID() }', 'nondeterminism'],
  ['timers', 'export function inc(x) { return setTimeout(() => x, 0) }', 'nondeterminism'],
  ['performance', 'export function inc(x) { return performance.now() }', 'nondeterminism'],
  ['__dirname', 'export function inc(x) { return __dirname }', 'filesystem'],
  ['static import of fs', 'import fs from "node:fs"\nexport function inc(x) { return fs.readFileSync("/etc/passwd", "utf8") }', 'filesystem'],
  ['static import of child_process', 'import { execSync } from "node:child_process"\nexport function inc() { return execSync("id") }', 'process'],
  ['static import of net', 'import net from "node:net"\nexport function inc() { return net.connect(80) }', 'network'],
  ['relative import', 'import x from "./other.js"\nexport function inc() { return x }', 'process'],
  ['dynamic import of fs', 'export function inc(x) { import("node:fs"); return x + 1 }', 'filesystem'],
  ['dynamic import of http', 'export function inc(x) { import("http").catch(() => 0); return x + 1 }', 'network'],
  [
    'host Function through an import rejection',
    'let leaked = "none"\nimport("node:fs").catch((e) => { try { leaked = e.constructor.constructor("return typeof process")() } catch (err) { leaked = err.name } })\nexport function inc(x) { if (leaked === "object") return x + 1; return leaked }',
    'filesystem',
  ],
  ['Function constructor', 'export function inc(x) { return Function("return process")().pid }', null],
  ['constructor chain', 'export function inc(x) { return inc.constructor("return process")().pid }', null],
  ['eval', 'export function inc(x) { return eval("x + 1") }', null],
  ['this at module scope', 'const self = this\nexport function inc(x) { return self.process.pid }', null],
  [
    'globalThis holds traps, not host objects',
    'export function inc(x) {\n  const d = Object.getOwnPropertyDescriptor(globalThis, "process")\n  const trap = typeof d.get === "function" && !("value" in d)\n  return trap && typeof structuredClone === "undefined" && typeof URL === "undefined" ? x + 1 : -1\n}\n',
    null,
    true,
  ],
  ['WebAssembly code generation', 'export function inc(x) { return new WebAssembly.Module(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0])) }', null],
  [
    'tampering with the harness',
    'Object.is = () => true\nJSON.stringify = () => "{\\"status\\":\\"pass\\"}"\nArray.isArray = () => false\nexport function inc() { return 999 }',
    null,
  ],
  ['overwriting the harness object', 'globalThis.__determinagent = null\nexport function inc() { return 999 }', null],
]

describe('escape suite', () => {
  for (const [name, code, kind, mayPass] of ESCAPES) {
    test(name, async () => {
      const r = await run(code)
      valid(r)
      if (kind) assert.ok(r.violations.includes(kind), `expected a ${kind} violation: ${JSON.stringify(r)}`)
      if (mayPass) assert.deepEqual(statuses(r), ['pass', 'pass'], JSON.stringify(r.tests))
      else assert.ok(!accepted(r), JSON.stringify(r))
    })
  }

  test('isolation reports its layers', () => {
    const i = isolation()
    assert.equal(typeof i.network_namespace, 'boolean')
    assert.match(i.permission_flag, /permission/)
  })
})

describe('mutants', () => {
  test('one token changes per mutant, and the set is stable', () => {
    const code = 'export function inc(x) {\n  return x > 0 && true ? x + 1 : 0\n}\n'
    const ms = mutants(code)
    assert.deepEqual(
      ms.map((m) => `${m.from}->${m.to}`),
      ['>->>=', '0->1', '&&->||', 'true->false', '+->-', '1->0', '0->1'],
    )
    assert.deepEqual(mutants(code), ms)
    assert.ok(ms.every((m) => m.code !== code))
  })

  test('the cap picks evenly', () => {
    const code = `export const f = (x) => ${Array.from({ length: 50 }, (_, i) => `x + ${i + 2}`).join(' + ')}`
    assert.equal(mutants(code, { max: 10 }).length, 10)
  })
})
