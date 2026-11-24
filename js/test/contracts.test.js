import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { describe, test } from 'node:test'

import { parse } from 'yaml'

import { SCHEMAS, schema, validate } from '../src/contracts.js'
import { check } from '../src/conformance/rulespeak.js'
import { toRequest } from '../src/golden.js'
import { fixture } from './helpers.js'

const CASES = fixture('contracts').cases
const GOLDEN_DIR = new URL('../../golden/v1/', import.meta.url)
const GOLDEN = readdirSync(GOLDEN_DIR)
  .filter((f) => f.endsWith('.yaml'))
  .sort()
  .flatMap((f) => parse(readFileSync(new URL(f, GOLDEN_DIR), 'utf8')).cases)

describe('contract examples', () => {
  for (const c of CASES) {
    test(c.name, () => {
      const errors = validate(c.contract, c.doc)
      assert.equal(errors.length === 0, c.valid, JSON.stringify(errors))
    })
  }
})

test('schema ids match file names', () => {
  for (const name of SCHEMAS) assert.equal(schema(name).$id, `urn:determinagent:contracts:v1:${name}`)
})

test('statement length limit', () => {
  assert.ok(validate('rulespeak_validation_input', { statements: [{ id: 's1', text: 'A'.repeat(501) }] }).length)
  assert.deepEqual(validate('rulespeak_validation_input', { statements: [{ id: 's1', text: 'A'.repeat(500) }] }), [])
})

describe('every golden case is a valid request', () => {
  for (const c of GOLDEN) test(c.id, () => assert.deepEqual(validate('request', toRequest(c)), []))
})

test('checker findings fit the finding contract', () => {
  for (const text of ['A visitor may enter the archive if accompanied by a curator.', 'Customers must register.']) {
    for (const f of check(text).toDict().findings) assert.deepEqual(validate('finding', f), [])
  }
})
