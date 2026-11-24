// The sandbox child process (Phase 0.8). Do not import this file: the parent
// (./index.js) runs it as `node child.mjs` with Node's permission model on,
// a V8 heap limit and an empty environment. It may import Node built-ins only,
// because the permission model lets it read this one file and nothing else.
//
// Protocol: one JSON job on stdin; one JSON line per event on stdout:
//   {"type":"load","ok":true} | {"type":"load","ok":false,"message":...}
//   {"type":"test","index":0,"status":"pass"|"fail"|"timeout","message":...,"duration_ms":...}
//   {"type":"done","violations":[...]}
//
// The model's module runs in a fresh vm context that holds only the
// ECMAScript built-ins plus what the prelude below installs: a fixed clock, a
// seeded Math.random, a no-op console and traps on the host globals. Nothing
// from this realm is ever handed to that context. Values cross only as
// strings, so the module never holds a host object it could climb out of.
import vm from 'node:vm'

const out = (o) => process.stdout.write(`${JSON.stringify(o)}\n`)

async function readStdin() {
  const chunks = []
  for await (const c of process.stdin) chunks.push(c)
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

// Runs inside the context, before the module. Its source is compiled there,
// so every object it creates belongs to the context's realm. It must not
// reference anything outside its own body.
function prelude(cfgJson) {
  'use strict'
  const cfg = JSON.parse(cfgJson)
  const g = globalThis
  // Captured before the module runs, so the module cannot change what the
  // harness uses to judge it.
  const { apply, ownKeys, getPrototypeOf, defineProperty } = Reflect
  const { is, freeze, keys: objectKeys } = Object
  const isArray = Array.isArray
  const stringify = JSON.stringify
  const parse = JSON.parse
  const RealDate = Date
  const getTime = RealDate.prototype.getTime
  const toISOString = RealDate.prototype.toISOString
  const mapGet = Map.prototype.get
  const mapHas = Map.prototype.has
  const mapSize = getOwnGetter(Map.prototype, 'size')
  const mapEntries = Map.prototype.entries
  const setHas = Set.prototype.has
  const setSize = getOwnGetter(Set.prototype, 'size')
  const setValues = Set.prototype.values
  const iterNext = getPrototypeOf(new Map().entries()).next
  const setIterNext = getPrototypeOf(new Set().values()).next
  const arrayPush = Array.prototype.push
  const strIncludes = String.prototype.includes
  const strSlice = String.prototype.slice
  const regexExec = RegExp.prototype.exec
  const ObjectProto = Object.prototype
  const ArrayProto = Array.prototype
  const MapProto = Map.prototype
  const SetProto = Set.prototype
  const DateProto = RealDate.prototype
  const PromiseThen = Promise.prototype.then
  const ErrorCtor = Error
  const errorNameRe = /^([A-Z][A-Za-z]*(?:Error|Exception))(?::\s*(.*))?$/s
  const hasOwn = Object.hasOwn
  const { String: Str, BigInt: Big, Map: MapCtor, Set: SetCtor, Promise: PromiseCtor } = g
  const mapSet = Map.prototype.set
  const setAdd = Set.prototype.add
  const resolveP = (v) => new PromiseCtor((res) => res(v))

  function getOwnGetter(o, k) {
    return Object.getOwnPropertyDescriptor(o, k).get
  }

  const violations = []
  function violate(kind) {
    for (let i = 0; i < violations.length; i++) if (violations[i] === kind) return
    apply(arrayPush, violations, [kind])
  }

  // Fixed clock.
  const FIXED = RealDate.parse(cfg.clock)
  function FixedDate(...args) {
    if (!new.target) return new RealDate(FIXED).toString()
    return Reflect.construct(RealDate, args.length ? args : [FIXED], new.target)
  }
  FixedDate.prototype = DateProto
  FixedDate.now = () => FIXED
  FixedDate.parse = RealDate.parse
  FixedDate.UTC = RealDate.UTC
  defineProperty(DateProto, 'constructor', { value: FixedDate, writable: true, configurable: true })
  defineProperty(g, 'Date', { value: FixedDate, writable: true, configurable: true })

  // Seeded Math.random (mulberry32), reset before each test.
  let rngState = 0
  const reseed = () => {
    rngState = cfg.seed >>> 0
  }
  Math.random = function random() {
    rngState = (rngState + 0x6d2b79f5) >>> 0
    let t = rngState
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  reseed()

  // A console that goes nowhere.
  const noop = () => undefined
  const consoleStub = {}
  for (const k of ['log', 'info', 'warn', 'error', 'debug', 'trace', 'dir', 'table']) consoleStub[k] = noop
  defineProperty(g, 'console', { value: freeze(consoleStub), writable: true, configurable: true })

  // Host globals: touching one is a violation of its kind.
  for (const name of objectKeys(cfg.blocked)) {
    const kind = cfg.blocked[name]
    defineProperty(g, name, {
      configurable: false,
      enumerable: false,
      get() {
        violate(kind)
        throw new ReferenceError(`${name} is not available in the sandbox`)
      },
      set() {
        violate(kind)
        throw new ReferenceError(`${name} is not available in the sandbox`)
      },
    })
  }

  // --- typed values ------------------------------------------------------
  // Test values are JSON. Values JSON cannot hold use {"$js": kind, ...}.
  function decode(v) {
    if (v === null || typeof v !== 'object') return v
    if (isArray(v)) {
      const a = []
      for (let i = 0; i < v.length; i++) a[i] = decode(v[i])
      return a
    }
    if (typeof v.$js === 'string') {
      switch (v.$js) {
        case 'undefined':
          return undefined
        case 'NaN':
          return NaN
        case 'Infinity':
          return Infinity
        case '-Infinity':
          return -Infinity
        case '-0':
          return -0
        case 'bigint':
          return Big(v.value)
        case 'Date':
          return new RealDate(v.value)
        case 'Map': {
          const m = new MapCtor()
          for (let i = 0; i < v.entries.length; i++) apply(mapSet, m, [decode(v.entries[i][0]), decode(v.entries[i][1])])
          return m
        }
        case 'Set': {
          const s = new SetCtor()
          for (let i = 0; i < v.values.length; i++) apply(setAdd, s, [decode(v.values[i])])
          return s
        }
        default:
          throw new ErrorCtor(`unknown $js kind ${v.$js}`)
      }
    }
    const o = {}
    const ks = objectKeys(v)
    for (let i = 0; i < ks.length; i++) o[ks[i]] = decode(v[ks[i]])
    return o
  }

  function describe(v, depth = 0) {
    try {
      if (v === undefined) return 'undefined'
      if (typeof v === 'number') return is(v, -0) ? '-0' : String(v)
      if (typeof v === 'bigint') return `${v}n`
      if (typeof v === 'string') return stringify(v)
      if (typeof v === 'function') return '[function]'
      if (typeof v === 'symbol') return 'Symbol()'
      if (v === null || typeof v !== 'object') return String(v)
      if (depth > 3) return '…'
      const proto = getPrototypeOf(v)
      if (proto === DateProto) return `Date(${apply(toISOString, v, [])})`
      if (isArray(v)) {
        let s = '['
        for (let i = 0; i < v.length && i < 20; i++) s += (i ? ', ' : '') + describe(v[i], depth + 1)
        return `${s}${v.length > 20 ? ', …' : ''}]`
      }
      if (proto === MapProto) return `Map(${apply(mapSize, v, [])})`
      if (proto === SetProto) return `Set(${apply(setSize, v, [])})`
      const ks = objectKeys(v)
      let s = '{'
      for (let i = 0; i < ks.length && i < 20; i++) s += `${i ? ', ' : ''}${ks[i]}: ${describe(v[ks[i]], depth + 1)}`
      return `${s}}`
    } catch {
      return '[unprintable]'
    }
  }

  function deepEqual(a, b, depth = 0) {
    if (is(a, b)) return true
    if (depth > 100) return false
    if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false
    const pa = getPrototypeOf(a)
    if (pa !== getPrototypeOf(b)) return false
    if (pa === DateProto) return is(apply(getTime, a, []), apply(getTime, b, []))
    if (pa === MapProto) {
      if (apply(mapSize, a, []) !== apply(mapSize, b, [])) return false
      const it = apply(mapEntries, a, [])
      for (let r = apply(iterNext, it, []); !r.done; r = apply(iterNext, it, [])) {
        const k = r.value[0]
        const v = r.value[1]
        if (!apply(mapHas, b, [k]) || !deepEqual(v, apply(mapGet, b, [k]), depth + 1)) return false
      }
      return true
    }
    if (pa === SetProto) {
      if (apply(setSize, a, []) !== apply(setSize, b, [])) return false
      const it = apply(setValues, a, [])
      for (let r = apply(setIterNext, it, []); !r.done; r = apply(setIterNext, it, [])) {
        if (!apply(setHas, b, [r.value])) return false
      }
      return true
    }
    if (pa === ArrayProto) {
      if (a.length !== b.length) return false
      for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i], depth + 1)) return false
      return true
    }
    if (pa !== ObjectProto && pa !== null) {
      if (a instanceof ErrorCtor) return a.name === b.name && a.message === b.message
    }
    const ka = ownKeys(a)
    const kb = ownKeys(b)
    if (ka.length !== kb.length) return false
    for (let i = 0; i < ka.length; i++) {
      const k = ka[i]
      if (!hasOwn(b, k)) return false
      if (!deepEqual(a[k], b[k], depth + 1)) return false
    }
    return true
  }

  function errorMatches(e, want) {
    let name
    let message
    try {
      name = e != null && typeof e === 'object' ? String(e.name) : typeof e
      message = e != null && typeof e === 'object' ? String(e.message) : String(e)
    } catch {
      return [false, 'the thrown value could not be read']
    }
    const m = apply(regexExec, errorNameRe, [want])
    if (m) {
      if (name !== m[1]) return [false, `threw ${name}: ${message}; expected ${want}`]
      if (m[2] && !apply(strIncludes, message, [m[2]])) return [false, `threw ${name}: ${message}; expected ${want}`]
      return [true, '']
    }
    return apply(strIncludes, message, [want]) ? [true, ''] : [false, `threw ${name}: ${message}; expected ${want}`]
  }

  class AssertionFailure extends ErrorCtor {}
  const assert = freeze({
    equal(actual, expected, msg) {
      if (!deepEqual(actual, expected)) {
        throw new AssertionFailure(msg || `expected ${describe(expected)}, got ${describe(actual)}`)
      }
    },
    notEqual(actual, expected, msg) {
      if (deepEqual(actual, expected)) throw new AssertionFailure(msg || `expected a value other than ${describe(expected)}`)
    },
    ok(value, msg) {
      if (!value) throw new AssertionFailure(msg || `expected a truthy value, got ${describe(value)}`)
    },
    throws(fn, want, msg) {
      try {
        fn()
      } catch (e) {
        if (want === undefined) return
        const [ok, why] = errorMatches(e, want)
        if (!ok) throw new AssertionFailure(msg || why)
        return
      }
      throw new AssertionFailure(msg || `expected ${want ?? 'an error'} to be thrown`)
    },
    async rejects(p, want, msg) {
      try {
        await (typeof p === 'function' ? p() : p)
      } catch (e) {
        if (want === undefined) return
        const [ok, why] = errorMatches(e, want)
        if (!ok) throw new AssertionFailure(msg || why)
        return
      }
      throw new AssertionFailure(msg || `expected ${want ?? 'a rejection'}`)
    },
    deepClone(v) {
      return parse(stringify(v))
    },
    describe,
  })

  // --- harness ----------------------------------------------------------
  let fn = null
  const snippets = []
  const isThenable = (v) => v !== null && (typeof v === 'object' || typeof v === 'function') && typeof v.then === 'function'
  const result = (status, message) =>
    stringify(message ? { status, message: apply(strSlice, Str(message), [0, 1000]) } : { status })
  const failure = (e) => {
    if (e instanceof AssertionFailure) return result('fail', e.message)
    try {
      return result('fail', `threw ${e && e.name ? `${e.name}: ${e.message}` : describe(e)}`)
    } catch {
      return result('fail', 'threw an unreadable value')
    }
  }

  function bind(ns) {
    const v = cfg.exportKind === 'default' ? ns.default : ns[cfg.name]
    if (typeof v !== 'function') {
      return stringify({ ok: false, message: `the module does not export a function ${cfg.exportKind === 'default' ? 'as default' : `named ${cfg.name}`}` })
    }
    fn = v
    return stringify({ ok: true })
  }

  function registerSnippet(i, f) {
    snippets[i] = f
  }

  function judgeValue(t, value) {
    if (t.throws !== undefined) return result('fail', `returned ${describe(value)}; expected it to throw ${t.throws}`)
    const want = decode(t.returns)
    return deepEqual(value, want) ? result('pass') : result('fail', `expected ${describe(want)}, got ${describe(value)}`)
  }

  function judgeError(t, e) {
    if (t.throws === undefined) return failure(e)
    const [ok, why] = errorMatches(e, t.throws)
    return ok ? result('pass') : result('fail', why)
  }

  // Settled async results, read by poll(). The host never touches a promise
  // from this realm: calling its then() would hand the module host functions.
  const settled = []
  const later = (i, p, onValue, onError) => {
    apply(PromiseThen, resolveP(p), [
      (v) => {
        settled[i] = onValue(v)
      },
      (e) => {
        settled[i] = onError(e)
      },
    ])
    return ''
  }

  // Returns a JSON result, or '' when the result is async; poll(i) then has it.
  function run(i) {
    reseed()
    const t = cfg.tests[i]
    if (t.code !== undefined) {
      try {
        const r = snippets[i](fn, assert)
        if (isThenable(r)) return later(i, r, () => result('pass'), failure)
        return result('pass')
      } catch (e) {
        return failure(e)
      }
    }
    let value
    try {
      value = apply(fn, undefined, decode(t.args))
    } catch (e) {
      if (cfg.async) return result('fail', `threw synchronously instead of returning a Promise: ${describe(e && e.message)}`)
      return judgeError(t, e)
    }
    if (cfg.async) {
      if (!isThenable(value)) return result('fail', `returned ${describe(value)}; expected a Promise`)
      return later(i, value, (v) => judgeValue(t, v), (e) => judgeError(t, e))
    }
    if (isThenable(value)) return result('fail', 'returned a Promise; expected a synchronous result')
    return judgeValue(t, value)
  }

  const poll = (i) => (settled[i] === undefined ? '' : settled[i])

  defineProperty(g, '__determinagent', {
    value: freeze({ bind, run, poll, registerSnippet, violations: () => stringify(violations) }),
    enumerable: false,
    writable: false,
    configurable: false,
  })
}

function moduleViolation(job, specifier) {
  const bare = String(specifier).replace(/^node:/, '')
  for (const [kind, names] of Object.entries(job.moduleViolations)) if (names.includes(bare)) return kind
  return 'process'
}

async function main() {
  const job = await readStdin()
  const timeout = job.limits.timeout_ms
  const hostViolations = new Set()
  const context = vm.createContext(Object.create(null), {
    name: 'determinagent-sandbox',
    codeGeneration: { strings: false, wasm: false },
  })
  const inContext = (src, opts = {}) => new vm.Script(src, { filename: 'harness.js' }).runInContext(context, opts)
  const cfg = {
    name: job.name,
    exportKind: job.exportKind,
    async: job.async,
    clock: job.limits.clock,
    seed: job.limits.seed,
    blocked: job.blockedGlobals,
    tests: job.tests,
  }
  inContext(`(${prelude.toString()})(${JSON.stringify(JSON.stringify(cfg))})`)
  const api = inContext('__determinagent')

  // An error thrown into the module must come from its own realm.
  const contextError = (message) => inContext(`new Error(${JSON.stringify(message)})`)

  let loaded = { ok: false, message: 'the module did not load' }
  try {
    const mod = new vm.SourceTextModule(job.code, {
      context,
      identifier: 'file:///sandbox/module.js',
      importModuleDynamically(specifier) {
        hostViolations.add(moduleViolation(job, specifier))
        throw contextError(`import of ${specifier} is blocked in the sandbox`)
      },
    })
    await mod.link((specifier) => {
      hostViolations.add(moduleViolation(job, specifier))
      throw new Error(`import of ${specifier} is blocked in the sandbox`)
    })
    await mod.evaluate({ timeout })
    loaded = JSON.parse(api.bind(mod.namespace))
  } catch (e) {
    const msg = String(e?.message ?? e)
    if (/timed out/i.test(msg)) hostViolations.add('timeout')
    loaded = { ok: false, message: `the module did not load: ${msg}` }
  }
  out({ type: 'load', ...loaded })

  if (loaded.ok) {
    for (let i = 0; i < job.tests.length; i++) {
      const t = job.tests[i]
      const t0 = performance.now()
      let r
      try {
        if (t.code !== undefined) {
          const f = new vm.Script(`(async function (fn, assert) { 'use strict';\n${t.code}\n})`, {
            filename: `test-${i}.js`,
          }).runInContext(context)
          api.registerSnippet(i, f)
        }
        // Sync work runs under the vm timeout. Async work is polled until the deadline.
        r = runInTime(() => api.run(i), timeout)
        if (r === '') r = await pollUntil(() => api.poll(i), timeout)
        r = r === '' ? { status: 'timeout', message: `no result after ${timeout} ms` } : JSON.parse(r)
      } catch (e) {
        const msg = String(e?.message ?? e)
        r = /timed out/i.test(msg) ? { status: 'timeout', message: `no result after ${timeout} ms` } : { status: 'fail', message: msg }
      }
      if (r.status === 'timeout') hostViolations.add('timeout')
      out({ type: 'test', index: i, ...r, duration_ms: Math.round((performance.now() - t0) * 1000) / 1000 })
    }
  }
  const inner = JSON.parse(api.violations())
  out({ type: 'done', violations: [...new Set([...inner, ...hostViolations])] })
}

// Calls into the context run under a vm timeout through a one-line script, so
// an endless loop in the module cannot hold the process.
let callSlot
function runInTime(f, timeout) {
  callSlot = f
  return runner.runInThisContext({ timeout })
}
const runner = new vm.Script('callSlot()', { filename: 'call.js' })
globalThis.callSlot = () => callSlot()

const tick = () => new Promise((resolve) => setImmediate(resolve))
async function pollUntil(read, ms) {
  const deadline = performance.now() + ms
  for (;;) {
    await tick()
    const r = runInTime(read, ms)
    if (r !== '' || performance.now() > deadline) return r
  }
}

main().catch((e) => {
  out({ type: 'crash', message: String(e?.stack ?? e).slice(0, 2000) })
  process.exitCode = 70
})
