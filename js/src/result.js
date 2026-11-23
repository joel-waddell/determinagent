// Shared result types for the deterministic conformance checkers.
// Mirrors src/determinagent/conformance/result.py; to_dict() output is identical.

export const Severity = Object.freeze({ ERROR: 'error', WARNING: 'warning' })

export class Defect {
  constructor(code, severity, message, line = null, column = null) {
    this.code = code
    this.severity = severity
    this.message = message
    this.line = line
    this.column = column
    Object.freeze(this)
  }

  toDict() {
    const d = { code: this.code, severity: this.severity, message: this.message }
    if (this.line != null) d.line = this.line
    if (this.column != null) d.column = this.column
    return d
  }
}

export class ConformanceResult {
  constructor(profile, profileVersion) {
    this.profile = profile
    this.profileVersion = profileVersion
    this.defects = []
    this.templateId = null
    this.slots = {}
  }

  /** Conformant means no error-level defects. */
  get conformant() {
    return !this.defects.some((d) => d.severity === Severity.ERROR)
  }

  get codes() {
    return this.defects.map((d) => d.code)
  }

  /** Same shape and key names as the Python core's to_dict(). */
  toDict() {
    return {
      profile: this.profile,
      profile_version: this.profileVersion,
      conformant: this.conformant,
      template_id: this.templateId,
      slots: { ...this.slots },
      defects: this.defects.map((d) => d.toDict()),
    }
  }
}
