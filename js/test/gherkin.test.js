import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { check, defaultProfile } from '../src/conformance/gherkin.js'
import { fixture, sorted } from './helpers.js'

const CASES = fixture('gherkin_cases')

describe('conformant features', () => {
  for (const [i, c] of CASES.conformant.entries()) {
    test(`case ${i}`, () => {
      const r = check(c.source)
      assert.ok(r.conformant)
      assert.deepEqual(r.defects, [], JSON.stringify(r.toDict()))
    })
  }
})

describe('errors', () => {
  for (const c of CASES.errors) {
    test(c.codes.join(','), () => {
      const r = check(c.source)
      assert.ok(!r.conformant)
      assert.deepEqual(sorted(r.codes), sorted(c.codes), JSON.stringify(r.toDict()))
    })
  }
})

describe('warnings', () => {
  for (const c of CASES.warnings) {
    test(c.codes.join(','), () => {
      const r = check(c.source)
      assert.ok(r.conformant, JSON.stringify(r.toDict()))
      assert.deepEqual(sorted(r.codes), sorted(c.codes))
    })
  }
})

test('parse error has a location', () => {
  const r = check('Feature: f\n  Scenario: s\n    Given a\nFeature: g\n')
  assert.equal(r.codes[0], 'GK-PARSE-001')
  assert.notEqual(r.defects[0].line, null)
})

test('every defect code is a GK- code', () => {
  assert.ok(Object.keys(defaultProfile().defects).every((c) => c.startsWith('GK-')))
})
