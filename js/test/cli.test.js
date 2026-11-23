import assert from 'node:assert/strict'
import { test } from 'node:test'

import { main } from '../bin/determinagent.js'

function run(argv, input) {
  let buf = ''
  const code = main(argv, { stdin: () => input, out: { write: (s) => (buf += s) } })
  return { code, out: JSON.parse(buf) }
}

test('rulespeak, one statement', () => {
  const { code, out } = run(['check', 'rulespeak'], 'Each order must have at least one line item.\n')
  assert.equal(code, 0)
  assert.ok(out.conformant)
  assert.equal(out.template_id, 'RS-T01')
})

test('rulespeak, several lines', () => {
  const { code, out } = run(['check', 'rulespeak'], 'Each order must have a customer.\nOrders ship fast.\n')
  assert.equal(code, 1)
  assert.deepEqual(
    out.map((o) => o.conformant),
    [true, false],
  )
})

test('gherkin', () => {
  const { code, out } = run(['check', 'gherkin'], 'Feature: f\n  Scenario: s\n    Given a\n    When b\n    Then c\n')
  assert.equal(code, 0)
  assert.ok(out.conformant)
})
