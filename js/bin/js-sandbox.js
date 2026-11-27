#!/usr/bin/env node
// determinagent-js-sandbox: run JavaScript jobs in the 0.8 sandbox.
//
// Reads JSON on stdin and prints JSON on stdout. Python calls this
// (determinagent.sandbox), so the JS checker and sandbox have one implementation.
//
//   {"code": ..., "spec": {...}, "tests": [...], "limits": {...}}   -> one js_execution report
//   [job, job, ...]                                                -> an array of reports, in order
//   {"info": true}                                                 -> how this machine isolates code
//   {"mutants": code, "max": 120}                                  -> mutants of code
//   {"without_comments": code}                                     -> code with comments blanked
//
// Jobs in a batch run up to --concurrency at a time (default 4). Exit code 0
// on success, 2 on bad input.
import { readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import { defaultProfile } from '../src/conformance/javascript.js'
import { execute, isolation } from '../src/sandbox/index.js'
import { mutants, withoutComments } from '../src/sandbox/mutate.js'

export async function runJobs(jobs, concurrency = 4) {
  const out = new Array(jobs.length)
  let next = 0
  const worker = async () => {
    while (next < jobs.length) {
      const i = next++
      out[i] = await execute(jobs[i])
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, jobs.length)) }, worker))
  return out
}

export async function main(argv = process.argv.slice(2), { stdin = () => readFileSync(0, 'utf8'), out = process.stdout } = {}) {
  let opts
  let input
  try {
    opts = parseArgs({ args: argv, options: { concurrency: { type: 'string', default: '4' } } }).values
    input = JSON.parse(stdin())
  } catch (e) {
    process.stderr.write(`${e.message}\n`)
    return 2
  }
  let result
  if (input && !Array.isArray(input) && input.info) {
    result = { ...isolation(), profile_version: defaultProfile().version }
  } else if (input && typeof input.mutants === 'string') {
    result = mutants(input.mutants, { max: input.max ?? 120 })
  } else if (input && typeof input.without_comments === 'string') {
    result = withoutComments(input.without_comments)
  } else if (Array.isArray(input)) {
    result = await runJobs(input, Number(opts.concurrency) || 4)
  } else if (input && typeof input.code === 'string') {
    result = await execute(input)
  } else {
    process.stderr.write('expected a job object, an array of jobs or {"info": true}\n')
    return 2
  }
  out.write(`${JSON.stringify(result)}\n`)
  return 0
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main()
}
