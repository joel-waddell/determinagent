// Golden-set helpers: turn a golden case into the typed v1 request it stands
// for. Mirrors src/determinagent/golden.py.

export const FIXED_TIME = '2026-01-01T00:00:00Z' // golden requests are timeless; a fixed stamp keeps them deterministic

export function toRequest(c) {
  const inp = c.input
  let payload
  if (c.task === 'rulespeak_generation') {
    payload = { intent: { free_text: inp.intent }, vocabulary: [...inp.vocabulary] }
  } else if (c.task === 'rulespeak_validation') {
    payload = { statements: [{ id: 's1', text: inp.statement }] }
    if (inp.vocabulary?.length) payload.vocabulary = [...inp.vocabulary]
  } else if (c.task === 'gherkin_requirements') {
    payload = { requirement: { ...inp.requirement } }
  } else {
    throw new Error(`Unknown task "${c.task}"`)
  }
  return { schema_version: '1.0', request_id: c.id, task: c.task, submitted_at: FIXED_TIME, payload }
}
