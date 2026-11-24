// Deterministic RuleSpeak checker (profile v0.2.0).
//
// Checks one statement against the supported templates and the surface
// diagnostics in src/determinagent/spec/rulespeak.yaml, and returns separate
// outcomes for profile acceptance, RuleSpeak form, review and local policy.
// Every finding carries its evidence chain (basis, RS ids and source
// locators). A port of src/determinagent/conformance/rulespeak.py; the parity
// test requires identical output.
import { readProfile } from '../spec.js'

export const PROFILE = 'rulespeak'

const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function phraseRegex(phrases, { anchored = false } = {}) {
  const alts = phrases.map((p) => escapeRegex(p).replace(/ /g, '\\s+')).sort((a, b) => b.length - a.length)
  return new RegExp(`${anchored ? '^' : ''}(?<![\\w/])(?:${alts.join('|')})(?![\\w/])`, 'i')
}

// The YAML patterns use Python's (?P<name>...) group syntax.
const toJsPattern = (pattern) => pattern.replaceAll('(?P<', '(?<')

function sources(register, refs) {
  const out = []
  for (const r of refs) for (const loc of register[r].source) if (!out.includes(loc)) out.push(loc)
  return out
}

export class Finding {
  constructor(fields) {
    Object.assign(this, fields)
    Object.freeze(this)
  }

  toDict() {
    return {
      code: this.code,
      title: this.title,
      message: this.message,
      kind: this.kind,
      disposition: this.disposition,
      basis: this.basis,
      rs_refs: [...this.rsRefs],
      source: [...this.source],
    }
  }
}

export class RuleSpeakResult {
  constructor(profileVersion, register) {
    this.profileVersion = profileVersion
    this.register = register
    this.findings = []
    this.template = null
    this.slots = {}
    this.termHits = null
  }

  get codes() {
    return this.findings.map((f) => f.code)
  }

  #any(disposition, kind = null) {
    return this.findings.some((f) => f.disposition === disposition && (kind === null || f.kind === kind))
  }

  get profileAcceptance() {
    return this.template !== null && !this.#any('error', 'profile') ? 'accepted' : 'rejected'
  }

  get form() {
    if (this.#any('error', 'form')) return 'needs_revision'
    if (this.#any('review', 'form') || this.profileAcceptance === 'rejected') return 'undetermined'
    return 'conforms'
  }

  get guidanceType() {
    return this.template ? this.template.guidance : null
  }

  get reviewRequired() {
    return this.#any('review')
  }

  get localPolicy() {
    return this.#any('error', 'local') ? 'fail' : 'pass'
  }

  /** Accepted, form conforms and local policy passes. Review findings do not fail this. */
  get passed() {
    return this.profileAcceptance === 'accepted' && this.form === 'conforms' && this.localPolicy === 'pass'
  }

  toDict() {
    const t = this.template
    return {
      profile: PROFILE,
      profile_version: this.profileVersion,
      outcome: {
        profile_acceptance: this.profileAcceptance,
        form: this.form,
        guidance_type: this.guidanceType,
        fidelity: 'unverified',
        review_required: this.reviewRequired,
        local_policy: this.localPolicy,
      },
      template:
        t === null
          ? null
          : { id: t.id, name: t.name, basis: t.basis, rs_refs: [...t.rsRefs], source: sources(this.register, t.rsRefs) },
      slots: { ...this.slots },
      term_hits: this.termHits === null ? null : [...this.termHits],
      findings: this.findings.map((f) => f.toDict()),
    }
  }
}

/** Build a profile from YAML data, or from the shared spec when omitted. */
export function loadProfile(data = readProfile('rulespeak')) {
  const det = data.determiners.map(escapeRegex).join('|')
  const register = data.rs_register
  const lex = data.lexicon
  const templates = data.templates.map((t) =>
    Object.freeze({
      id: t.id,
      name: t.name,
      guidance: t.guidance,
      form: t.form,
      regex: new RegExp(toJsPattern(t.pattern).replaceAll('{det}', det), 'i'),
      example: t.example,
      basis: t.basis,
      rsRefs: Object.freeze([...t.rs_refs]),
    }),
  )
  return Object.freeze({
    version: String(data.version),
    templates,
    diagnostics: data.diagnostics,
    register,
    lexicon: lex,
    maxWords: Number(data.max_words),
    re: {
      leading: phraseRegex(lex.leading_qualification_words, { anchored: true }),
      modals: phraseRegex(lex.modals_needing_interpretation),
      system: phraseRegex(lex.system_terms),
      sequence: phraseRegex(lex.sequence_terms),
      vague: phraseRegex(lex.vague_terms),
      redundant: new RegExp(`\\bmust\\s+(?:${lex.redundant_adverbs.join('|')})\\b`),
    },
    finding(code, message) {
      const d = data.diagnostics[code]
      return new Finding({
        code,
        title: d.title,
        message: message ?? d.title,
        kind: d.kind,
        disposition: d.disposition,
        basis: d.basis,
        rsRefs: Object.freeze([...d.rs_refs]),
        source: Object.freeze(sources(register, d.rs_refs)),
      })
    },
  })
}

let cached
export const defaultProfile = () => (cached ??= loadProfile())

const SENTENCE_BREAK = /[.!?;](?=\s+\S)/
const ABBREV = /\b(?:e\.g|i\.e|etc|vs|no|approx)\./gi
const DECIMAL = /(?<=\d)\.(?=\d)/g

export const normalize = (statement) => statement.replace(/\s+/g, ' ').trim()

/**
 * Check a single RuleSpeak statement.
 *
 * @param {string} statement
 * @param {string[] | null} [vocabulary] business terms. When given, the
 *   subject must contain one of them (a local policy check).
 * @param {ReturnType<typeof loadProfile>} [profile]
 * @returns {RuleSpeakResult}
 */
export function check(statement, vocabulary = null, profile = defaultProfile()) {
  const p = profile
  const s = normalize(statement)
  const result = new RuleSpeakResult(p.version, p.register)
  const add = (f) => result.findings.push(f)
  const has = (...codes) => codes.some((c) => result.codes.includes(c))
  const lex = p.lexicon

  if (!s) {
    add(p.finding('RS-PRF-003', 'Empty statement'))
    add(p.finding('RS-KW-001'))
    return result
  }

  // One sentence, ending in a full stop.
  const masked = s.replace(ABBREV, (m) => m.replaceAll('.', '_')).replace(DECIMAL, '_')
  if (SENTENCE_BREAK.test(masked) || !s.endsWith('.')) add(p.finding('RS-PRF-003'))

  const lower = s.toLowerCase()
  const words = lower.match(/[a-z]+(?:'[a-z]+)?/g) ?? []

  // Leading qualification: a RuleSpeak style warning, and separately a parser limit.
  if (p.re.leading.test(s)) {
    add(p.finding('RS-STY-001'))
    add(p.finding('RS-PRF-002'))
  }

  // Keywords.
  const musts = words.filter((w) => w === 'must').length
  const onlys = words.filter((w) => w === 'only').length
  const hasAdvice = words.includes('may') || /\bneed\s+not\b/.test(lower)
  if (musts === 0 && onlys === 0 && !hasAdvice) add(p.finding('RS-KW-001'))
  if (musts > 1 || onlys > 1) add(p.finding('RS-KW-003'))
  if (musts && onlys) add(p.finding('RS-KW-004'))
  let m
  if ((m = s.match(p.re.modals))) add(p.finding('RS-KW-002', `Modal "${m[0]}" needs interpretation`))

  if ((m = s.match(p.re.system))) add(p.finding('RS-STY-002', `System term "${m[0]}" detected`))
  if ((m = s.match(p.re.sequence))) add(p.finding('RS-STY-003', `Sequence term "${m[0]}" detected`))
  if (p.re.redundant.test(lower)) add(p.finding('RS-STY-004'))
  if ((m = s.match(p.re.vague))) add(p.finding('RS-VAG-001', `Vague term "${m[0]}" detected`))
  if (/\band\s*\/\s*or\b/.test(lower)) add(p.finding('RS-VAG-002'))
  if (words.length > p.maxWords) add(p.finding('RS-LOC-001', `${words.length} words (local limit ${p.maxWords})`))

  // Template match, on a single subject-first sentence only.
  if (!has('RS-PRF-002', 'RS-PRF-003')) {
    for (const t of p.templates) {
      const hit = s.match(t.regex)
      if (hit) {
        result.template = t
        result.slots = Object.fromEntries(Object.entries(hit.groups ?? {}).filter(([, v]) => v !== undefined))
        break
      }
    }
    if (result.template === null) add(p.finding('RS-PRF-001'))
  }

  const t = result.template
  const slots = result.slots
  if (t !== null) {
    const condKw = (slots.cond_kw ?? '').toLowerCase()
    if (condKw === 'unless') add(p.finding('RS-EXT-001'))
    if (t.id === 'RS-T05b') add(p.finding('RS-EXT-002'))
    if (t.id === 'RS-T07' && condKw === 'if') add(p.finding('RS-ADV-001'))
    if (t.id === 'RS-T03' && lex.temporal_restriction_words.includes((slots.restriction_kw ?? '').toLowerCase())) {
      add(p.finding('RS-APP-001'))
    }
  }

  if (vocabulary != null && t !== null) {
    const subject = slots.subject ?? ''
    const terms = vocabulary.map((v) => v.trim().toLowerCase()).filter(Boolean)
    result.termHits = terms.filter((v) => new RegExp(`\\b${escapeRegex(v)}s?\\b`).test(subject.toLowerCase()))
    if (!result.termHits.length) add(p.finding('RS-VOC-001', `No vocabulary term found in subject "${subject}"`))
  }

  return result
}
