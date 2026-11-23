// Deterministic Gherkin conformance checker.
//
// Parses with the official Cucumber parser (@cucumber/gherkin), then applies
// the DeterminAgent profile in src/determinagent/spec/gherkin.yaml. This is a
// port of src/determinagent/conformance/gherkin.py and must agree with it on
// every shared fixture.
import { AstBuilder, GherkinClassicTokenMatcher, Parser } from '@cucumber/gherkin'
import { IdGenerator } from '@cucumber/messages'

import { ConformanceResult, Defect } from '../result.js'
import { readProfile } from '../spec.js'

export const PROFILE = 'gherkin'

// keywordType values emitted by the official parser.
const CONTEXT = 'Context'
const ACTION = 'Action'
const OUTCOME = 'Outcome'
const CONJUNCTION = 'Conjunction'
const UNKNOWN = 'Unknown'
const PHASE = { [CONTEXT]: 0, [ACTION]: 1, [OUTCOME]: 2 }
const PLACEHOLDER = /<([^<>]+)>/g

export function loadProfile(data = readProfile('gherkin')) {
  return Object.freeze({
    version: String(data.version),
    languages: new Set(data.languages),
    maxSteps: Number(data.max_steps_per_scenario),
    defects: data.defects,
    defect(code, message, loc) {
      const spec = data.defects[code]
      return new Defect(code, spec.severity, message ?? spec.title, loc?.line ?? null, loc?.column ?? null)
    },
  })
}

let cached
export const defaultProfile = () => (cached ??= loadProfile())

/** Parse with the official parser. Throws the parser's exceptions. */
export function parse(source) {
  return new Parser(new AstBuilder(IdGenerator.incrementing()), new GherkinClassicTokenMatcher()).parse(source)
}

const stepLabel = (step) => `"${step.keyword.trim()} ${step.text}"`
const placeholdersIn = (text = '') => [...text.matchAll(PLACEHOLDER)].map((m) => m[1])

/** @returns {ConformanceResult} */
export function check(source, profile = defaultProfile()) {
  const p = profile
  const result = new ConformanceResult(PROFILE, p.version)
  const add = (d) => result.defects.push(d)

  let doc
  try {
    doc = parse(source)
  } catch (err) {
    const errors = Array.isArray(err.errors) && err.errors.length ? err.errors : [err]
    for (const e of errors) add(p.defect('GK-PARSE-001', e.message, e.location))
    return result
  }

  const feature = doc.feature
  if (!feature) {
    add(p.defect('GK-STR-001'))
    return result
  }
  const floc = feature.location
  if (!p.languages.has(feature.language)) {
    add(p.defect('GK-LANG-001', `Language "${feature.language}" is not in the profile`, floc))
  }
  if (!(feature.name ?? '').trim()) add(p.defect('GK-STR-002', undefined, floc))

  let scenarios = 0
  const names = new Map()

  const walk = (children, inheritedContext) => {
    let hasContext = inheritedContext
    for (const child of children) {
      if (!child.background) continue
      const steps = child.background.steps ?? []
      for (const step of steps) {
        if (step.keywordType !== CONTEXT && step.keywordType !== CONJUNCTION) {
          add(p.defect('GK-SEQ-006', `Background step ${stepLabel(step)}`, step.location))
        }
      }
      if (steps.length) hasContext = true
    }
    for (const child of children) {
      if (child.rule) walk(child.rule.children ?? [], hasContext)
      else if (child.scenario) {
        scenarios += 1
        checkScenario(p, child.scenario, hasContext, names, add)
      }
    }
  }

  walk(feature.children ?? [], false)
  if (scenarios === 0) add(p.defect('GK-STR-003', undefined, floc))
  return result
}

function checkScenario(p, sc, hasContext, names, add) {
  const loc = sc.location
  const name = (sc.name ?? '').trim()
  if (!name) add(p.defect('GK-STR-004', undefined, loc))
  else if (names.has(name.toLowerCase())) add(p.defect('GK-STR-006', `Duplicate scenario name "${name}"`, loc))
  else names.set(name.toLowerCase(), loc)
  if ((sc.description ?? '').trim()) add(p.defect('GK-STY-001', undefined, loc))

  const steps = sc.steps ?? []
  if (!steps.length) {
    add(p.defect('GK-STR-005', undefined, loc))
    return
  }
  if (steps.length > p.maxSteps) add(p.defect('GK-STY-003', `${steps.length} steps (max ${p.maxSteps})`, loc))

  let phase = -1
  let prev = null
  const seen = new Set()
  steps.forEach((step, i) => {
    let kt = step.keywordType
    if (kt === UNKNOWN) {
      add(p.defect('GK-STY-002', undefined, step.location))
      kt = prev
    } else if (kt === CONJUNCTION) {
      if (i === 0) add(p.defect('GK-SEQ-005', undefined, step.location))
      kt = prev
    }
    if (kt in PHASE) {
      if (PHASE[kt] < phase) {
        add(p.defect('GK-SEQ-004', `${stepLabel(step)} after a later step type`, step.location))
      }
      phase = Math.max(phase, PHASE[kt])
      seen.add(kt)
    }
    prev = kt
  })

  if (!seen.has(ACTION)) add(p.defect('GK-SEQ-001', undefined, loc))
  if (!seen.has(OUTCOME)) add(p.defect('GK-SEQ-002', undefined, loc))
  if (!seen.has(CONTEXT) && !hasContext) add(p.defect('GK-SEQ-003', undefined, loc))

  const placeholders = new Set()
  for (const step of steps) {
    placeholdersIn(step.text).forEach((x) => placeholders.add(x))
    for (const row of step.dataTable?.rows ?? []) {
      for (const cell of row.cells ?? []) placeholdersIn(cell.value).forEach((x) => placeholders.add(x))
    }
    placeholdersIn(step.docString?.content).forEach((x) => placeholders.add(x))
  }

  const examples = sc.examples ?? []
  const keyword = (sc.keyword ?? '').toLowerCase()
  const isOutline = examples.length > 0 || keyword.includes('outline') || keyword.includes('template')
  if (!isOutline) return
  if (!examples.length) {
    add(p.defect('GK-OUT-001', undefined, loc))
    return
  }
  for (const ex of examples) {
    const cols = new Set((ex.tableHeader?.cells ?? []).map((c) => c.value))
    if (!(ex.tableBody ?? []).length) add(p.defect('GK-OUT-003', undefined, ex.location))
    for (const missing of [...placeholders].filter((x) => !cols.has(x)).sort()) {
      add(p.defect('GK-OUT-002', `Placeholder <${missing}> has no Examples column`, ex.location))
    }
  }
}
