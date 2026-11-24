import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { check, defaultProfile } from '../src/conformance/javascript.js'
import { validate } from '../src/contracts.js'
import { fixture, sorted } from './helpers.js'

const CASES = fixture('javascript_cases')
const specOf = (c) => c.spec ?? CASES.default_spec
const codes = (r) => sorted(new Set(r.findings.map((f) => f.code)))

describe('clean modules', () => {
  for (const c of CASES.clean) {
    test(c.name, () => {
      const r = check(c.code, { spec: specOf(c) })
      assert.ok(r.passed)
      assert.deepEqual(r.findings, [], JSON.stringify(r.findings))
    })
  }
})

describe('findings', () => {
  for (const c of CASES.findings) {
    test(c.name, () => {
      const r = check(c.code, { spec: specOf(c) })
      assert.deepEqual(codes(r), sorted(c.codes), JSON.stringify(r.findings))
      for (const f of r.findings) assert.deepEqual(validate('js_finding', f), [], JSON.stringify(f))
    })
  }
})

describe('profile', () => {
  const p = defaultProfile()

  test('every rule maps to a known code and every code is well-formed', () => {
    for (const r of p.data.rules) assert.ok(p.codes[r.code], r.rule)
    for (const [code, spec] of Object.entries(p.codes)) {
      assert.match(code, /^JS-[A-Z]+-[0-9]{3}$/)
      assert.ok(['error', 'warning', 'info'].includes(spec.severity), code)
    }
  })

  test('a finding with error severity fails the check; a warning does not', () => {
    assert.equal(check('export function total(items) { var n = items.length; return n }', { spec: CASES.default_spec }).passed, true)
    assert.equal(check('export function total(items) { return eval(items) }', { spec: CASES.default_spec }).passed, false)
  })

  test('without a spec the export check is skipped', () => {
    const r = check('export const anything = 1')
    assert.ok(r.passed)
  })

  test('the result is deterministic', () => {
    const code = CASES.findings.map((c) => c.code).join('\n')
    assert.deepEqual(check(code), check(code))
  })

  test('inline eslint comments cannot switch rules off', () => {
    const r = check('/* eslint-disable */\nexport function total(items) { return eval(items) }', { spec: CASES.default_spec })
    assert.ok(codes(r).includes('JS-SEC-001'))
  })
})
