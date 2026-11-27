// Mutants of a module, for checking that a golden case's hidden tests can
// tell a correct solution from a nearly correct one (Phase 0.2).
// Each mutant makes one small change to the reference solution:
// - token: one operator, boolean or number literal swapped;
// - structural: a condition negated (if, while, for, ?:), a statement removed
//   (an expression statement, break or continue), or a returned value
//   replaced by undefined.
// A mutant the tests still accept "survives".
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

const short = (s) => {
  const one = s.replace(/\s+/g, ' ').trim()
  return one.length > 40 ? `${one.slice(0, 39)}…` : one
}

function walk(node, visit) {
  if (!node || typeof node.type !== 'string') return
  visit(node)
  for (const key of Object.keys(node)) {
    if (key === 'parent') continue
    const v = node[key]
    if (Array.isArray(v)) for (const c of v) walk(c, visit)
    else if (v && typeof v.type === 'string') walk(v, visit)
  }
}

function structural(code, ecmaVersion) {
  const ast = espree.parse(code, { ecmaVersion, sourceType: 'module', range: true, loc: true })
  const out = []
  const at = (node, from, to, replacement, range = node.range) => {
    const [a, b] = range
    out.push({
      line: node.loc.start.line,
      column: node.loc.start.column + 1,
      from,
      to,
      code: code.slice(0, a) + replacement + code.slice(b),
      pos: a,
    })
  }
  walk(ast, (n) => {
    const test = ['IfStatement', 'WhileStatement', 'DoWhileStatement', 'ForStatement', 'ConditionalExpression'].includes(n.type)
      ? n.test
      : null
    if (test) {
      const text = code.slice(...test.range)
      at(test, short(text), 'negated', `!(${text})`)
    }
    if (n.type === 'BlockStatement' || n.type === 'Program' || n.type === 'SwitchCase') {
      for (const st of n.type === 'SwitchCase' ? n.consequent : n.body) {
        if (['ExpressionStatement', 'BreakStatement', 'ContinueStatement'].includes(st.type)) {
          at(st, short(code.slice(...st.range)), 'removed', ';')
        }
      }
    }
    if ((n.type === 'IfStatement' || n.type === 'ForOfStatement' || n.type === 'ForStatement' || n.type === 'WhileStatement') &&
      ['ExpressionStatement', 'BreakStatement', 'ContinueStatement'].includes((n.consequent ?? n.body)?.type)) {
      const st = n.consequent ?? n.body
      at(st, short(code.slice(...st.range)), 'removed', ';')
    }
    if (n.type === 'ReturnStatement' && n.argument && !(n.argument.type === 'Identifier' && n.argument.name === 'undefined')) {
      at(n.argument, short(code.slice(...n.argument.range)), 'undefined', 'undefined')
    }
  })
  return out
}

/**
 * Every single-token and structural mutant of `code`, as {id, line, column, from, to, code}.
 * At most `max` mutants, chosen evenly across the module so the set is stable.
 */
export function mutants(code, { max = 120, ecmaVersion = 2023 } = {}) {
  const tokens = espree.tokenize(code, { ecmaVersion, sourceType: 'module', range: true, loc: true })
  const out = []
  for (const t of tokens) {
    let to = null
    if (t.type === 'Punctuator' && SWAP[t.value]) to = SWAP[t.value]
    else if (t.type === 'Boolean') to = t.value === 'true' ? 'false' : 'true'
    else if (t.type === 'Numeric') to = numberMutant(t.value)
    if (to === null) continue
    const [a, b] = t.range
    out.push({ line: t.loc.start.line, column: t.loc.start.column + 1, from: t.value, to, code: code.slice(0, a) + to + code.slice(b), pos: a })
  }
  out.push(...structural(code, ecmaVersion))
  out.sort((x, y) => x.pos - y.pos || (x.to < y.to ? -1 : x.to > y.to ? 1 : 0))
  for (const m of out) delete m.pos
  let picked = out
  if (out.length > max) {
    const step = out.length / max
    picked = Array.from({ length: max }, (_, i) => out[Math.floor(i * step)])
  }
  return picked.map((m, i) => ({ id: `M${String(i + 1).padStart(3, '0')}`, ...m }))
}
