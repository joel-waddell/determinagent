// Cross-checks the two cores: every fixture input must give byte-identical
// JSON verdicts from Python and JavaScript. Skipped when the Python core is
// not installed (set DETERMINAGENT_PYTHON to choose the interpreter).
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'

import * as gherkin from '../src/conformance/gherkin.js'
import * as rulespeak from '../src/conformance/rulespeak.js'
import { fixture } from './helpers.js'

const PY = process.env.DETERMINAGENT_PYTHON ?? 'python3'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const hasPython = spawnSync(PY, ['-c', 'import determinagent'], { cwd: ROOT }).status === 0

const PY_SCRIPT = `
import json, sys
from determinagent.conformance import gherkin, rulespeak
req = json.load(sys.stdin)
out = {
  "rulespeak": [rulespeak.check(t, v).to_dict() for t, v in req["rulespeak"]],
  "gherkin": [gherkin.check(s).to_dict() for s in req["gherkin"]],
}
json.dump(out, sys.stdout)
`

test('Python and JavaScript cores agree on every fixture', { skip: !hasPython && 'Python core not installed' }, () => {
  const rs = fixture('rulespeak_cases')
  const gk = fixture('gherkin_cases')
  const req = {
    rulespeak: [...rs.cases, ...rs.vocabulary_cases].map((c) => [c.text, c.vocabulary ?? null]),
    gherkin: [...gk.conformant, ...gk.warnings, ...gk.errors].map((c) => c.source),
  }
  const res = spawnSync(PY, ['-c', PY_SCRIPT], { cwd: ROOT, input: JSON.stringify(req), encoding: 'utf8' })
  assert.equal(res.status, 0, res.stderr)
  const py = JSON.parse(res.stdout)

  req.rulespeak.forEach(([t, v], i) => assert.deepEqual(rulespeak.check(t, v).toDict(), py.rulespeak[i], t))
  req.gherkin.forEach((s, i) => assert.deepEqual(gherkin.check(s).toDict(), py.gherkin[i], s))
})
