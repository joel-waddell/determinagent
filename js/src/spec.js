// Loads the versioned YAML profiles. Both cores read the same files in
// src/determinagent/spec/, so there is one definition of "well-formed".
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parse } from 'yaml'

export const SPEC_DIR = fileURLToPath(new URL('../../src/determinagent/spec/', import.meta.url))

export function readProfile(name) {
  return parse(readFileSync(new URL(`${name}.yaml`, `file://${SPEC_DIR}`), 'utf8'))
}
