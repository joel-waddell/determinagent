// Deterministic JavaScript checker (Phase 0.1, Amendment 1).
//
// Parses and lints one ES module under the JS profile in
// src/determinagent/spec/javascript.yaml, using ESLint's in-memory Linter.
// Nothing here runs the code: execution is the sandbox's job
// (../sandbox/index.js). Findings follow the js_finding contract.
//
// This checker exists only in the JavaScript core. Python calls it through
// determinagent.sandbox, so it is exempt from the parity test.
import { Linter } from 'eslint'

import { readProfile } from '../spec.js'

export const PROFILE = 'javascript'

const SHORT = 500

export function loadProfile(data = readProfile('javascript')) {
  const byRule = new Map()
  for (const r of data.rules) {
    if (!data.codes[r.code]) throw new Error(`rule ${r.rule} maps to unknown code ${r.code}`)
    byRule.set(r.rule, r.code)
  }
  return Object.freeze({
    version: String(data.version),
    data,
    codes: data.codes,
    byRule,
    blockedGlobals: data.globals.blocked,
    providedGlobals: data.globals.provided,
    sandbox: data.sandbox,
  })
}

let cached
export const defaultProfile = () => (cached ??= loadProfile())

// ---------------------------------------------------------------------------
// determinagent/spec-export: the module exports the spec's function, the way
// the spec says. Options: { name, export: 'named'|'default', async, params }.

const FUNCTION_NODES = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'])
const NOT_FUNCTION = new Set([
  'Literal',
  'TemplateLiteral',
  'ObjectExpression',
  'ArrayExpression',
  'ClassDeclaration',
  'ClassExpression',
  'BinaryExpression',
  'UnaryExpression',
])

export const SPEC_EXPORT_MESSAGES = {
  missing: 'JS-MOD-001',
  wrongKind: 'JS-MOD-002',
  asyncMismatch: 'JS-MOD-003',
  notFunction: 'JS-MOD-005',
  paramCount: 'JS-MOD-006',
}

const specExportRule = {
  meta: {
    type: 'problem',
    schema: [{ type: 'object', additionalProperties: true }],
    messages: {
      missing: "The module does not export '{{name}}'.",
      wrongKind: "'{{name}}' must be a {{want}} export, not a {{got}} export.",
      asyncMismatch: "'{{name}}' must not be async; the spec describes a synchronous function.",
      notFunction: "The exported '{{name}}' is not a function.",
      paramCount: "'{{name}}' declares {{got}} parameter(s); the spec has {{want}}.",
    },
  },
  create(context) {
    const opt = context.options[0] ?? {}
    const name = opt.name
    const want = opt.export ?? 'named'
    return {
      'Program:exit'(program) {
        if (!name) return
        const locals = new Map()
        const named = new Map() // exported name -> node (declaration or local identifier)
        let deflt = null
        for (const st of program.body) {
          const decl = st.type === 'ExportNamedDeclaration' || st.type === 'ExportDefaultDeclaration' ? st.declaration : st
          if (decl?.type === 'FunctionDeclaration' && decl.id) locals.set(decl.id.name, decl)
          if (decl?.type === 'ClassDeclaration' && decl.id) locals.set(decl.id.name, decl)
          if (decl?.type === 'VariableDeclaration') {
            for (const d of decl.declarations) if (d.id.type === 'Identifier') locals.set(d.id.name, d.init ?? d)
          }
          if (st.type === 'ExportNamedDeclaration') {
            if (st.declaration?.type === 'VariableDeclaration') {
              for (const d of st.declaration.declarations) if (d.id.type === 'Identifier') named.set(d.id.name, d.init ?? d)
            } else if (st.declaration?.id) {
              named.set(st.declaration.id.name, st.declaration)
            }
            for (const sp of st.specifiers ?? []) {
              const exported = sp.exported.type === 'Identifier' ? sp.exported.name : sp.exported.value
              const ref = { type: 'Identifier', name: sp.local.name, loc: sp.loc }
              if (exported === 'default') deflt = ref
              else named.set(exported, ref)
            }
          }
          if (st.type === 'ExportDefaultDeclaration') deflt = st.declaration
        }
        const resolve = (n, seen = 0) => (n?.type === 'Identifier' && seen < 5 ? resolve(locals.get(n.name), seen + 1) : n)

        let target
        if (want === 'named') {
          target = named.get(name)
          if (!target) {
            const asDefault = resolve(deflt)
            const kindWrong = deflt && (asDefault?.id?.name === name || deflt.name === name || !named.size)
            context.report({
              node: program,
              loc: { line: 1, column: 0 },
              messageId: kindWrong ? 'wrongKind' : 'missing',
              data: { name, want: 'named', got: 'default' },
            })
            return
          }
        } else {
          target = deflt
          if (!target) {
            context.report({
              node: program,
              loc: { line: 1, column: 0 },
              messageId: named.has(name) ? 'wrongKind' : 'missing',
              data: { name, want: 'default', got: 'named' },
            })
            return
          }
        }
        const fn = resolve(target)
        if (!fn) return
        const where = fn.loc ? { loc: fn.loc } : { node: program }
        if (NOT_FUNCTION.has(fn.type)) {
          context.report({ ...where, messageId: 'notFunction', data: { name } })
          return
        }
        if (!FUNCTION_NODES.has(fn.type)) return // a call result or similar: the tests decide
        if (fn.async && opt.async === false) context.report({ ...where, messageId: 'asyncMismatch', data: { name } })
        if (Number.isInteger(opt.params) && fn.params.length !== opt.params) {
          context.report({ ...where, messageId: 'paramCount', data: { name, got: fn.params.length, want: opt.params } })
        }
      },
    }
  },
}

const plugin = { rules: { 'spec-export': specExportRule } }

// ---------------------------------------------------------------------------

function ruleConfig(profile, spec) {
  const rules = {}
  for (const r of profile.data.rules) {
    const sev = profile.codes[r.code].severity === 'error' ? 'error' : 'warn'
    let options = r.options ?? []
    if (options === 'from_blocked_globals') {
      options = Object.keys(profile.blockedGlobals).map((name) => ({
        name,
        message: `${name} is not available in the sandbox.`,
      }))
    }
    rules[r.rule] = [sev, ...options]
  }
  if (spec) {
    rules['determinagent/spec-export'] = [
      'error',
      {
        name: spec.name,
        export: spec.export ?? 'named',
        async: spec.async ?? false,
        params: Array.isArray(spec.params) ? spec.params.length : undefined,
      },
    ]
  }
  return rules
}

function configFor(profile, spec) {
  const globals = {}
  for (const g of profile.providedGlobals) globals[g] = 'readonly'
  // Declared so no-undef stays quiet and no-restricted-globals gives the specific code.
  for (const g of Object.keys(profile.blockedGlobals)) globals[g] = 'readonly'
  return [
    {
      plugins: { determinagent: plugin },
      languageOptions: {
        ecmaVersion: profile.data.language.ecma_version,
        sourceType: profile.data.language.source_type,
        globals,
      },
      linterOptions: { reportUnusedDisableDirectives: 'off', noInlineConfig: true },
      rules: ruleConfig(profile, spec),
    },
  ]
}

const clip = (s, n = SHORT) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

function toFinding(profile, m) {
  let code
  let basis = 'lint'
  if (m.fatal || !m.ruleId) {
    code = 'JS-SYN-001'
    basis = 'parser'
  } else if (m.ruleId === 'determinagent/spec-export') {
    code = SPEC_EXPORT_MESSAGES[m.messageId]
  } else {
    code = profile.byRule.get(m.ruleId)
  }
  const spec = profile.codes[code]
  const range = { start_line: Math.max(1, m.line ?? 1), end_line: Math.max(1, m.endLine ?? m.line ?? 1) }
  if (m.column) range.start_column = m.column
  if (m.endColumn) range.end_column = m.endColumn
  const f = {
    code,
    category: spec.category,
    severity: spec.severity,
    basis,
    message: clip(m.message || spec.title),
    range,
  }
  if (basis === 'lint') f.rule = m.ruleId
  return f
}

const order = (a, b) =>
  a.range.start_line - b.range.start_line ||
  (a.range.start_column ?? 0) - (b.range.start_column ?? 0) ||
  a.code.localeCompare(b.code)

/**
 * Check one module. `spec` is the J2 js_function_spec, when there is one.
 * Returns { profile, profile_version, parsed, findings, errors, warnings, passed }.
 * `passed` means parsed with no error-severity finding.
 */
export function check(code, { spec = null, profile = defaultProfile() } = {}) {
  const linter = new Linter({ configType: 'flat' })
  const messages = linter.verify(code, configFor(profile, spec), { filename: 'module.js' })
  const parsed = !messages.some((m) => m.fatal)
  const findings = messages.map((m) => toFinding(profile, m)).sort(order)
  const errors = findings.filter((f) => f.severity === 'error').length
  return {
    profile: PROFILE,
    profile_version: profile.version,
    parsed,
    passed: parsed && errors === 0,
    errors,
    warnings: findings.length - errors,
    findings,
  }
}
