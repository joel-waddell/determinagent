// The J2 execution sandbox (Phase 0.8).
//
// execute() lints a module with the JS checker, then runs it in a fresh child
// process and reports the js_execution contract. Layers, outermost first:
//
// 1. A network namespace with no interfaces (`unshare -rn`), where the OS
//    allows it. DETERMINAGENT_SANDBOX_NETNS=require fails closed without it;
//    =off skips it.
// 2. A child Node process with an empty environment, TZ=UTC, a V8 heap limit,
//    code generation from strings disabled, and Node's permission model on:
//    no file system access beyond the runner file, no child processes, no
//    workers, no native add-ons, no WASI.
// 3. A vm context holding only the ECMAScript built-ins, a fixed clock, a
//    seeded Math.random and traps on every host global (see child.mjs).
//    Imports are refused at link time. Touching a blocked global or module is
//    recorded as a violation of its kind.
// 4. A per-test time limit inside the child, and a wall-clock kill outside it.
//
// The model never sees or fills the report. Docs: docs/sandbox.md.
import { spawn, spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { check, defaultProfile } from '../conformance/javascript.js'

export const CHILD = fileURLToPath(new URL('./child.mjs', import.meta.url))
const STARTUP_MS = 3000

const PERMISSION_FLAG = process.allowedNodeEnvironmentFlags.has('--permission') ? '--permission' : '--experimental-permission'

let netnsCache
/** Whether `unshare -rn` works here. Cached per process. */
export function networkNamespaceAvailable() {
  if (netnsCache === undefined) {
    if (process.platform !== 'linux') netnsCache = false
    else {
      const r = spawnSync('unshare', ['-rn', 'true'], { stdio: 'ignore', timeout: 5000 })
      netnsCache = r.status === 0
    }
  }
  return netnsCache
}

/** How the sandbox isolates code on this machine. */
export function isolation() {
  const mode = (process.env.DETERMINAGENT_SANDBOX_NETNS || 'auto').toLowerCase()
  const netns = mode !== 'off' && networkNamespaceAvailable()
  if (mode === 'require' && !netns) {
    throw new Error('DETERMINAGENT_SANDBOX_NETNS=require, but unshare -rn is not available here')
  }
  return { network_namespace: netns, permission_flag: PERMISSION_FLAG, node_version: process.version }
}

/** Turn a spec's visible examples into sandbox tests. */
export function testsFromSpec(spec) {
  return (spec?.examples ?? []).map((ex, i) => {
    const t = { name: `example ${i + 1}`, args: ex.args }
    if ('throws' in ex) t.throws = ex.throws
    else t.returns = ex.returns
    return t
  })
}

export function limitsFor(limits = {}, profile = defaultProfile()) {
  const d = profile.sandbox.defaults
  return {
    timeout_ms: limits.timeout_ms ?? d.timeout_ms,
    memory_mb: limits.memory_mb ?? d.memory_mb,
    clock: limits.clock ?? d.clock,
    seed: limits.seed ?? d.seed,
  }
}

function environment(lim, profile) {
  return {
    node_version: process.version,
    profile_version: profile.version,
    timeout_ms: lim.timeout_ms,
    memory_mb: lim.memory_mb,
    clock: lim.clock,
    seed: lim.seed,
  }
}

function childCommand(lim) {
  const node = [
    process.execPath,
    PERMISSION_FLAG,
    `--allow-fs-read=${CHILD}`,
    `--max-old-space-size=${lim.memory_mb}`,
    '--stack-size=984',
    '--disallow-code-generation-from-strings',
    '--experimental-vm-modules',
    '--no-warnings',
    CHILD,
  ]
  return isolation().network_namespace ? ['unshare', ['-rn', ...node]] : [node[0], node.slice(1)]
}

const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

function runChild(job, lim, nTests) {
  const budget = STARTUP_MS + lim.timeout_ms * (nTests + 2)
  const [cmd, args] = childCommand(lim)
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      env: { TZ: 'UTC', LANG: 'C.UTF-8' },
      cwd: '/',
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    let killed = false
    const timer = setTimeout(() => {
      killed = true
      child.kill('SIGKILL')
    }, budget)
    child.stdout.on('data', (d) => {
      if (stdout.length < 4_000_000) stdout += d
    })
    child.stderr.on('data', (d) => {
      if (stderr.length < 100_000) stderr += d
    })
    child.on('error', (e) => {
      clearTimeout(timer)
      resolve({ events: [], stderr: String(e), killed, code: null, signal: null })
    })
    child.on('close', (code, signal) => {
      clearTimeout(timer)
      const events = []
      for (const line of stdout.split('\n')) {
        if (!line.trim()) continue
        try {
          events.push(JSON.parse(line))
        } catch {
          // a torn last line after a kill
        }
      }
      resolve({ events, stderr, killed, code, signal })
    })
    child.stdin.on('error', () => {})
    child.stdin.end(JSON.stringify(job))
  })
}

/**
 * Lint and run one module. Returns a js_execution report.
 *
 * tests: [{name, args, returns} | {name, args, throws} | {name, code}]
 * spec:  the J2 js_function_spec (name, export, async); null skips the export check
 * options.durations: include per-test duration_ms (off by default, so reports
 *   are byte-identical across runs)
 */
export async function execute({ code, spec = null, tests = [], limits = {}, durations = false } = {}) {
  const profile = defaultProfile()
  const lim = limitsFor(limits, profile)
  const lint = check(code, { spec, profile })
  const report = { parsed: lint.parsed, lint: lint.findings, tests: [], violations: [], environment: environment(lim, profile) }
  const named = tests.map((t, i) => clip(String(t.name ?? `test ${i + 1}`), 500))
  if (!lint.parsed) {
    report.tests = named.map((name) => ({ name, status: 'skip', message: 'the module did not parse' }))
    return report
  }
  const job = {
    code,
    name: spec?.name ?? null,
    exportKind: spec?.export ?? 'named',
    async: spec?.async ?? false,
    tests: tests.map((t) => {
      const o = {}
      if (t.code !== undefined) o.code = String(t.code)
      else {
        o.args = t.args ?? []
        if ('throws' in t) o.throws = t.throws
        else o.returns = t.returns ?? null
      }
      return o
    }),
    limits: lim,
    blockedGlobals: profile.blockedGlobals,
    moduleViolations: profile.sandbox.module_violations,
  }
  if (!job.name) {
    // Without a spec, run the module's only export, whatever its name.
    job.exportKind = 'default'
  }
  const res = await runChild(job, lim, tests.length)
  const load = res.events.find((e) => e.type === 'load')
  const done = res.events.find((e) => e.type === 'done')
  const crash = res.events.find((e) => e.type === 'crash')
  const byIndex = new Map(res.events.filter((e) => e.type === 'test').map((e) => [e.index, e]))
  const violations = new Set(done?.violations ?? [])
  const oom = /heap out of memory|Allocation failed|invalid array length|Reached heap limit/i.test(res.stderr)
  if (oom) violations.add('memory')
  if (res.killed) violations.add('timeout')
  const abnormal = !done
  const why = oom
    ? 'the sandbox ran out of memory'
    : res.killed
      ? 'the sandbox was stopped at its time limit'
      : crash
        ? `the sandbox failed: ${crash.message}`
        : `the sandbox exited early (${res.signal ?? res.code})${res.stderr ? `: ${res.stderr.trim().split('\n').pop()}` : ''}`
  report.tests = named.map((name, i) => {
    const e = byIndex.get(i)
    let t
    if (e) {
      t = { name, status: e.status }
      if (e.message) t.message = clip(e.message, 4000)
      if (durations && e.duration_ms !== undefined) t.duration_ms = e.duration_ms
    } else if (load && !load.ok) {
      t = { name, status: 'fail', message: clip(load.message, 4000) }
    } else {
      t = { name, status: res.killed ? 'timeout' : 'fail', message: clip(abnormal ? why : 'no result', 4000) }
    }
    return t
  })
  report.violations = [...violations].sort()
  return report
}

/** The acceptance rule from the profile: parsed, no error finding, every test passes, no violation. */
export function accepted(report) {
  return (
    report.parsed &&
    !report.lint.some((f) => f.severity === 'error') &&
    report.tests.every((t) => t.status === 'pass') &&
    report.violations.length === 0
  )
}
