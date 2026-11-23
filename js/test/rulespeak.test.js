import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { check, defaultProfile } from '../src/conformance/rulespeak.js'
import { fixture, sorted } from './helpers.js'

const CASES = fixture('rulespeak_cases')

describe('conformant statements', () => {
  for (const c of CASES.conformant) {
    test(c.text, () => {
      const r = check(c.text)
      assert.ok(r.conformant, JSON.stringify(r.toDict()))
      assert.equal(r.templateId, c.template)
    })
  }
})

describe('conformant with warnings', () => {
  for (const c of CASES.warnings) {
    test(c.text, () => {
      const r = check(c.text)
      assert.ok(r.conformant)
      assert.equal(r.templateId, c.template)
      assert.deepEqual(sorted(r.codes), sorted(c.codes))
    })
  }
})

describe('defective statements', () => {
  for (const c of CASES.defective) {
    test(c.text || '(empty)', () => {
      const r = check(c.text)
      assert.ok(!r.conformant)
      assert.deepEqual(sorted(r.codes), sorted(c.codes), JSON.stringify(r.toDict()))
    })
  }
})

test('every defect code is tested', () => {
  const tested = new Set([...CASES.defective, ...CASES.warnings].flatMap((c) => c.codes))
  const untested = Object.keys(defaultProfile().defects).filter(
    (c) => !tested.has(c) && !['RS-STY-004', 'RS-VOC-001'].includes(c),
  )
  assert.deepEqual(untested, [])
})

test('template examples match their own template', () => {
  for (const t of defaultProfile().templates) {
    const r = check(t.example)
    assert.ok(r.conformant && r.templateId === t.id, `${t.id}: ${JSON.stringify(r.toDict())}`)
  }
})

test('slots are extracted', () => {
  const r = check('An order must not be shipped if the outstanding balance exceeds the credit limit.')
  assert.equal(r.slots.subject, 'order')
  assert.equal(r.slots.predicate, 'be shipped')
  assert.equal(r.slots.cond_kw, 'if')
  assert.equal(r.slots.condition, 'the outstanding balance exceeds the credit limit')
})

test('vocabulary check', () => {
  const vocab = ['order', 'customer', 'line item']
  assert.ok(check('Each order must have at least one line item.', vocab).conformant)
  assert.deepEqual(check('Each shipment must have a carrier.', vocab).codes, ['RS-VOC-001'])
})

test('long statement is a warning only', () => {
  const r = check(`A customer must ${['provide', ...Array(25).fill('a document')].join(' ')}.`)
  assert.ok(r.codes.includes('RS-STY-004'))
  assert.ok(r.conformant)
})

test('deterministic', () => {
  const text = 'A refund may be issued only if the purchase was made within the last 30 days.'
  assert.deepEqual(check(text).toDict(), check(text).toDict())
})
