import { readFileSync } from 'node:fs'
import { parse } from 'yaml'

export const fixture = (name) =>
  parse(readFileSync(new URL(`../../tests/fixtures/${name}.yaml`, import.meta.url), 'utf8'))

export const sorted = (xs) => [...xs].sort()
