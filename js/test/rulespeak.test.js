import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { check, defaultProfile } from '../src/conformance/rulespeak.js'
import { fixture, sorted } from './helpers.js'

const FIXTURES = fixture('rulespeak_cases')
const PROFILE = defaultProfile()
const OUTCOME_KEYS = ['profile_acceptance', 'form', 'guidance_type', 'review_required', 'local_policy']

function assertChecker(c, result) {
  const d = result.toDict()
  const want = c.checker
  for (const k of OUTCOME_KEYS) if (k in want) assert.equal(d.outcome[k], want[k], `${k}: ${JSON.stringify(d)}`)
  if ('template' in want) assert.equal(d.template?.id ?? null, want.template)
  if ('term_hits' in want) assert.deepEqual(d.term_hits, want.term_hits)
  assert.deepEqual(sorted(result.codes), sorted(want.codes), JSON.stringify(d))
}

describe('cases', () => {
  for (const c of FIXTURES.cases) test(`${c.id} ${c.text}`, () => assertChecker(c, check(c.text)))
})

describe('vocabulary cases', () => {
  for (const c of FIXTURES.vocabulary_cases) test(c.id, () => assertChecker(c, check(c.text, c.vocabulary)))
})

test('every cited RS id exists and reaches a locator', () => {
  const items = [...Object.values(PROFILE.diagnostics), ...PROFILE.templates.map((t) => ({ rs_refs: t.rsRefs }))]
  for (const item of items) {
    for (const ref of item.rs_refs) {
      assert.match(ref, /^RS-\d\d$/)
      assert.ok(PROFILE.register[ref]?.source?.length, ref)
    }
  }
  for (const c of FIXTURES.cases) for (const ref of c.rulespeak.rs_refs) assert.ok(PROFILE.register[ref], c.id)
})

test('template examples match their own template', () => {
  for (const t of PROFILE.templates) {
    const r = check(t.example)
    assert.equal(r.template?.id, t.id)
    assert.equal(r.profileAcceptance, 'accepted')
  }
})

test('findings carry the evidence chain', () => {
  const f = check('A visitor may enter the archive if accompanied by a curator.').findings[0]
  assert.equal(f.code, 'RS-ADV-001')
  assert.deepEqual([...f.rsRefs], ['RS-10'])
  assert.ok(f.source.includes('SF Table 2 forms 4.1–4.2, p. 10'))
})

test('the quantifier is preserved', () => {
  assert.equal(check('Every employee must complete safety training.').slots.det, 'Every')
})

test('word limit is local', () => {
  const r = check(`A customer must ${['provide', ...Array(25).fill('a document')].join(' ')}.`)
  assert.deepEqual(r.codes, ['RS-LOC-001'])
  assert.ok(r.passed)
})

test('fidelity is always unverified', () => {
  assert.equal(check('Each order must have a customer.').toDict().outcome.fidelity, 'unverified')
})
