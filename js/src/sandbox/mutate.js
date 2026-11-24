// Token-level mutants of a module, for checking that a golden case's hidden
// tests can tell a correct solution from a nearly correct one (Phase 0.2).
// Each mutant changes one operator, boolean or number literal in the
// reference solution. A mutant the tests still accept "survives".
// Some survivors are equivalent to the original and need a human look.
import * as espree from 'espree'

const SWAP = {
  '<': '<=',
  '<=': '<',
  '>': '>=',
  '>=': '>',
  '===': '!==',
  '!==': '===',
  '==': '!=',
  '!=': '==',
  '+': '-',
  '-': '+',
  '*': '/',
  '/': '*',
  '%': '*',
  '&&': '||',
  '||': '&&',
  '??': '||',
  '+=': '-=',
  '-=': '+=',
  '++': '--',
  '--': '++',
}

function numberMutant(text) {
  if (!/^\d+$/.test(text)) return null
  const n = Number(text)
  return n === 0 ? '1' : n === 1 ? '0' : String(n + 1)
}

/**
 * Every single-token mutant of `code`, as {id, line, column, from, to, code}.
 * At most `max` mutants, chosen evenly across the module so the set is stable.
 */
export function mutants(code, { max = 80, ecmaVersion = 2023 } = {}) {
  const tokens = espree.tokenize(code, { ecmaVersion, sourceType: 'module', range: true, loc: true })
  const out = []
  for (const t of tokens) {
    let to = null
    if (t.type === 'Punctuator' && SWAP[t.value]) to = SWAP[t.value]
    else if (t.type === 'Boolean') to = t.value === 'true' ? 'false' : 'true'
    else if (t.type === 'Numeric') to = numberMutant(t.value)
    if (to === null) continue
    const [a, b] = t.range
    out.push({ line: t.loc.start.line, column: t.loc.start.column + 1, from: t.value, to, code: code.slice(0, a) + to + code.slice(b) })
  }
  let picked = out
  if (out.length > max) {
    const step = out.length / max
    picked = Array.from({ length: max }, (_, i) => out[Math.floor(i * step)])
  }
  return picked.map((m, i) => ({ id: `M${String(i + 1).padStart(3, '0')}`, ...m }))
}
