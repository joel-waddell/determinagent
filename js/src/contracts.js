// Versioned JSON Schema contracts (Phase 0.7), shared with the Python core.
//
//   import { validate } from 'determinagent/contracts'
//   validate('request', obj)   // [] when valid
//
// The schemas live in src/determinagent/contracts/v1/. Validity must agree
// with the Python validator on every shared example (parity test).
import { readFileSync } from 'node:fs'

import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'

export const VERSION = 'v1'
export const SCHEMAS = ['common', 'request', 'response', 'handoff-artifact', 'governance-change']

const urn = (name) => `urn:determinagent:contracts:${VERSION}:${name}`
const dir = new URL(`../../src/determinagent/contracts/${VERSION}/`, import.meta.url)

let ajv
function instance() {
  if (ajv) return ajv
  ajv = new Ajv2020({ allErrors: true, strict: false })
  addFormats(ajv)
  for (const name of SCHEMAS) ajv.addSchema(JSON.parse(readFileSync(new URL(`${name}.schema.json`, dir), 'utf8')))
  return ajv
}

const validators = new Map()
function validator(name) {
  if (!validators.has(name)) {
    const a = instance()
    const v = SCHEMAS.includes(name) ? a.getSchema(urn(name)) : a.compile({ $ref: `${urn('common')}#/$defs/${name}` })
    if (!v) throw new Error(`Unknown contract "${name}"`)
    validators.set(name, v)
  }
  return validators.get(name)
}

export const schema = (name) => instance().getSchema(urn(name)).schema

/** Validation errors as "path: message" strings, sorted; [] when valid. */
export function validate(name, obj) {
  const v = validator(name)
  return v(obj) ? [] : v.errors.map((e) => `${e.instancePath || '/'}: ${e.message}`).sort()
}

export const isValid = (name, obj) => validator(name)(obj)
