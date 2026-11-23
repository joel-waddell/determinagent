#!/usr/bin/env node
// determinagent check {rulespeak|gherkin} [FILE] [--vocabulary a,b,c]
//
// Reads FILE (or stdin), prints the verdict as JSON, and exits 0 when the
// input is conformant, 1 when it is not, 2 on a usage error. RuleSpeak input
// is one statement per line. Output matches the Python CLI.
import { readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import * as gherkin from '../src/conformance/gherkin.js'
import * as rulespeak from '../src/conformance/rulespeak.js'

const USAGE = 'usage: determinagent check {rulespeak|gherkin} [FILE] [--vocabulary TERMS]'

export function main(argv = process.argv.slice(2), { stdin = () => readFileSync(0, 'utf8'), out = process.stdout } = {}) {
  let parsed
  try {
    parsed = parseArgs({ args: argv, allowPositionals: true, options: { vocabulary: { type: 'string' } } })
  } catch (err) {
    process.stderr.write(`${err.message}\n${USAGE}\n`)
    return 2
  }
  const [cmd, profile, file] = parsed.positionals
  if (cmd !== 'check' || !['rulespeak', 'gherkin'].includes(profile)) {
    process.stderr.write(`${USAGE}\n`)
    return 2
  }
  const text = file && file !== '-' ? readFileSync(file, 'utf8') : stdin()

  let results
  let output
  if (profile === 'gherkin') {
    results = [gherkin.check(text)]
    output = [results[0].toDict()]
  } else {
    const vocab = parsed.values.vocabulary ? parsed.values.vocabulary.split(',') : null
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    results = lines.map((l) => rulespeak.check(l, vocab))
    output = lines.map((l, i) => ({ input: l, ...results[i].toDict() }))
  }
  out.write(`${JSON.stringify(output.length === 1 ? output[0] : output, null, 2)}\n`)
  return results.every((r) => r.conformant) ? 0 : 1
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main()
}
