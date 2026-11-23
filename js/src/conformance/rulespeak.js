// Deterministic RuleSpeak conformance checker.
//
// Checks one rule statement against the approved sentence templates and the
// keyword and style guidance in src/determinagent/spec/rulespeak.yaml. No
// model is involved: the same input always produces the same verdict. This is
// a port of src/determinagent/conformance/rulespeak.py and must agree with it
// on every shared fixture.
import { ConformanceResult, Defect } from '../result.js'
import { readProfile } from '../spec.js'

export const PROFILE = 'rulespeak'

const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function phraseRegex(phrases) {
  const alts = phrases
    .map((p) => escapeRegex(p).replace(/ /g, '\\s+'))
    .sort((a, b) => b.length - a.length)
  return new RegExp(`(?<![\\w/])(?:${alts.join('|')})(?![\\w/])`, 'i')
}

// The YAML patterns use Python's (?P<name>...) group syntax; JavaScript
// spells it (?<name>...).
const toJsPattern = (pattern) => pattern.replaceAll('(?P<', '(?<')

/** Build a profile from YAML data, or from the shared spec when omitted. */
export function loadProfile(data = readProfile('rulespeak')) {
  const det = data.determiners.map(escapeRegex).join('|')
  const templates = data.templates.map((t) =>
    Object.freeze({
      id: t.id,
      name: t.name,
      kind: t.kind,
      form: t.form,
      regex: new RegExp(toJsPattern(t.pattern).replaceAll('{det}', det), 'i'),
      example: t.example,
    }),
  )
  const lex = data.lexicon
  return Object.freeze({
    version: String(data.version),
    templates,
    defects: data.defects,
    lexicon: lex,
    ruleKeywords: new Set(data.rule_keywords.map((k) => k.toLowerCase())),
    maxWords: Number(data.max_words),
    re: {
      modals: phraseRegex(lex.non_rulespeak_modals),
      system: phraseRegex(lex.system_terms),
      procedural: phraseRegex(lex.procedural_terms),
      vague: phraseRegex(lex.vague_terms),
      redundant: new RegExp(`\\bmust\\s+(?:${lex.redundant_adverbs.join('|')})\\b`),
    },
    defect(code, message) {
      const spec = data.defects[code]
      return new Defect(code, spec.severity, message ?? spec.title)
    },
  })
}

let cached
export const defaultProfile = () => (cached ??= loadProfile())

const SENTENCE_BREAK = /[.!?;](?=\s+\S)/
const ABBREV = /\b(?:e\.g|i\.e|etc|vs|no|approx)\./gi
const DECIMAL = /(?<=\d)\.(?=\d)/g

export const normalize = (statement) => statement.replace(/\s+/g, ' ').trim()

const firstWord = (text) => (text.match(/^[A-Za-z]+/)?.[0] ?? '').toLowerCase()

/**
 * Check a single RuleSpeak rule statement.
 *
 * @param {string} statement
 * @param {string[] | null} [vocabulary] business terms (the fact model). When
 *   given, the subject of the statement must contain one of them.
 * @param {ReturnType<typeof loadProfile>} [profile]
 * @returns {ConformanceResult}
 */
export function check(statement, vocabulary = null, profile = defaultProfile()) {
  const p = profile
  const s = normalize(statement)
  const result = new ConformanceResult(PROFILE, p.version)
  const add = (d) => result.defects.push(d)
  const has = (...codes) => codes.some((c) => result.codes.includes(c))
  const lex = p.lexicon

  if (!s) {
    add(p.defect('RS-KW-001', 'Empty statement'))
    return result
  }

  // Structure: exactly one sentence, ending in a full stop.
  const masked = s.replace(ABBREV, (m) => m.replaceAll('.', '_')).replace(DECIMAL, '_')
  if (SENTENCE_BREAK.test(masked) || !s.endsWith('.')) add(p.defect('RS-STR-001'))

  const lower = s.toLowerCase()
  const words = lower.match(/[a-z]+(?:'[a-z]+)?/g) ?? []

  const leading = lex.leading_condition_words
  if (
    leading.filter((w) => !w.includes(' ')).includes(firstWord(s)) ||
    leading.filter((w) => w.includes(' ')).some((w) => lower.startsWith(`${w} `))
  ) {
    add(p.defect('RS-STR-003'))
  }

  const keywordCount = words.filter((w) => p.ruleKeywords.has(w)).length
  if (keywordCount > 1) add(p.defect('RS-STR-002'))

  const modal = s.match(p.re.modals)
  if (modal) add(p.defect('RS-KW-002', `Non-RuleSpeak modal "${modal[0]}"`))

  if (keywordCount === 0 && !modal && !/\bconsidered\b|\bcomputed as\b/.test(lower)) {
    add(p.defect('RS-KW-001'))
  }

  if (/\bmay\b/.test(lower) && !/\bonly\b/.test(lower)) add(p.defect('RS-KW-003'))

  let m
  if ((m = s.match(p.re.system))) add(p.defect('RS-STY-001', `System-centric wording "${m[0]}"`))
  if ((m = s.match(p.re.procedural))) add(p.defect('RS-STY-002', `Procedural wording "${m[0]}"`))
  if (p.re.redundant.test(lower)) add(p.defect('RS-STY-003'))
  if (words.length > p.maxWords) add(p.defect('RS-STY-004', `Long statement (${words.length} words)`))

  if ((m = s.match(p.re.vague))) add(p.defect('RS-VAG-001', `Vague term "${m[0]}"`))
  if (/\band\s*\/\s*or\b/.test(lower)) add(p.defect('RS-VAG-002'))

  // Template match, on the single-sentence form only.
  if (!has('RS-STR-001')) {
    const hit = p.templates.find((t) => t.regex.test(s))
    if (hit) {
      result.templateId = hit.id
      const groups = s.match(hit.regex).groups ?? {}
      result.slots = Object.fromEntries(Object.entries(groups).filter(([, v]) => v !== undefined))
    } else if (!has('RS-STR-003', 'RS-KW-001', 'RS-KW-002', 'RS-KW-003')) {
      add(p.defect('RS-TPL-001'))
    }
  }

  if (vocabulary != null && result.templateId) {
    const subject = result.slots.subject ?? ''
    const terms = vocabulary.map((t) => t.trim().toLowerCase()).filter(Boolean)
    const found = terms.some((t) => new RegExp(`\\b${escapeRegex(t)}s?\\b`).test(subject.toLowerCase()))
    if (!found) add(p.defect('RS-VOC-001', `Subject "${subject}" uses no vocabulary term`))
  }

  return result
}
