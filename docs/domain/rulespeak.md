# RuleSpeak profile v0.2.0

RuleSpeak is Ronald G. Ross's notation for writing business rules in structured English. This profile is a deterministic surface checker for a supported subset of it. It is traced to Joel's derived ruleset, *RuleSpeak-Agent.md* v2.0 (RS-01 to RS-29). That ruleset cites the original sources by locator: *RuleSpeak Sentence Forms* (SF), *Basic RuleSpeak Guidelines* (DD), *Tabulation of Lists in RuleSpeak* (TL) and *The Business Rules Manifesto* (BM).

The machine-readable source of truth is [`rulespeak.yaml`](../../src/determinagent/spec/rulespeak.yaml). It is implemented in [`js/src/conformance/rulespeak.js`](../../js/src/conformance/rulespeak.js) and [`conformance/rulespeak.py`](../../src/determinagent/conformance/rulespeak.py), and a parity test keeps the two identical.

> Status: draft v0.2.0, revised after Joel's review of v0.1.0. The case labels in `tests/fixtures/rulespeak_cases.yaml` are drafts until Joel labels them.

## What changed from v0.1.0

- **One verdict became separate outcomes.** "Non-conformant" used to mean any of three things: a RuleSpeak violation, a form the checker cannot parse, or a local policy failure. Each now has its own outcome.
- **Keywords follow RS-01 and RS-02.** The rule keywords are *must* and *only*. The advice keywords are *may* and *need not*.
- **Classification uses the published form.** That form is *must be considered … if …* (RS-06). *is always considered* is no longer accepted. *is considered … only if* is kept as a marked profile extension and always goes to review, because it states the reverse implication.
- **Advice is recognized, not rejected.** *may* (RS-10) and *need not* (RS-11) are templates with `guidance_type: advice`. *may … if* is flagged for revision, as RS-10 requires.
- **Conditions:** *if* and *when* are distinct (RS-15). *must be performed … when* (RS-07) has been added. *unless* is accepted as a documented profile extension. *may … only after* is labelled as an application of form 3.2 (RS-16).
- **Diagnostics are named after what they detect.** Surface matches that cannot establish a defect now go to review instead of failing. Examples are a repeated keyword, a system or sequence term, a vague term and *and/or*.
- **Evidence chain.** Every template and diagnostic records whether it is sourced, inferred or local, along with its RS ids. Every finding the checker returns carries those ids and their source locators.
- **Review answers applied.** *Every* is allowed and kept as written. *must … only* is not a template; it goes to review (RS-KW-004). A leading condition is a style warning (RS-STY-001), with the parser's subject-first limit reported separately (RS-PRF-002).

## Outcomes

| Outcome | Values | Meaning |
| --- | --- | --- |
| `profile_acceptance` | accepted, rejected | Whether the statement fits a supported template. A rejection is a limit of the checker. It does not mean the statement is bad RuleSpeak. |
| `form` | conforms, needs_revision, undetermined | The RuleSpeak form verdict, taken from `form` diagnostics only, because a style preference alone is not a form defect. The value is `undetermined` when a form question needs review, or when the profile rejected the statement and found no form defect. |
| `guidance_type` | rule, advice, null | A business rule or a Statement of Advice. A task that needs rules, such as generation, treats advice as out of scope. |
| `fidelity` | unverified | Always unverified. A surface checker has no independent statement of intent. |
| `review_required` | true, false | Whether any finding needs a reviewer or the SLM to confirm it. |
| `local_policy` | pass, fail | Project choices that RuleSpeak doesn't make, such as the vocabulary check. |

A statement **passes** the checker, and exits 0 from the command-line tool, when the profile accepts it, its form conforms and local policy passes. Review findings are reported, but they don't fail a statement.

## Templates

They are tried in this order, and the first match wins. The **basis** column says how firmly each template is grounded. `sourced` means an RS check states it directly. `inferred` means it is the checker's reading of an RS check. `local` means it is a project or parser choice.

| Id | Name | Guidance | Form | Basis | RS ids |
| --- | --- | --- | --- | --- | --- |
| RS-T06 | Computation | rule | `<result> must be computed as <formula>.` | sourced | RS-05 |
| RS-T05 | Classification (sufficient condition) | rule | `<term> must be considered <classification> if <condition>.` | sourced | RS-06, RS-12 |
| RS-T05b | Classification (necessary condition), profile extension | rule | `<term> is considered <classification> only if <condition>.` | local | none |
| RS-T09 | Procedure at an occurrence | rule | `<procedure> must be performed [<qualification>] when <occurrence>.` | sourced | RS-07, RS-15 |
| RS-T02 | Prohibition | rule | `<subject> must not <predicate> [if/when <condition>].` | sourced | RS-01, RS-08 |
| RS-T03 | Restricted permission | rule | `<subject> may <predicate> only if <condition> / only <qualification>.` | sourced | RS-01, RS-09, RS-13 |
| RS-T03b | Restricted permission, "only" before the verb | rule | `<subject> may only <predicate>.` | inferred | RS-01, RS-09 |
| RS-T04 | Restricted eligibility | rule | `Only <qualified subject> may <predicate>.` | inferred | RS-01, RS-09 |
| RS-T01 | Obligation | rule | `<subject> must <predicate> [if/when <condition>].` | sourced | RS-01, RS-04, RS-12, RS-15 |
| RS-T08 | Advice, exemption or optionality | advice | `<subject> need not <predicate> [<qualification>].` | sourced | RS-02, RS-11 |
| RS-T07 | Advice, permission | advice | `<subject> may <predicate>.` | sourced | RS-02, RS-10 |

Examples:

- **RS-T06:** The net amount of an invoice must be computed as the gross amount of the invoice minus the discount applied to the invoice.
- **RS-T05:** A customer must be considered preferred if the customer has placed more than 10 orders.
- **RS-T05b:** A shipment is considered late only if it is delivered after its promised date.
- **RS-T09:** A credit check must be performed when a new customer places an order.
- **RS-T02:** An order must not be shipped if the outstanding balance exceeds the credit limit.
- **RS-T03:** A supplier may submit an invoice only after the buyer issues the purchase order for the invoice.
- **RS-T03b:** A loan may only be approved by a credit officer.
- **RS-T04:** Only a manager may approve a discount above 20 percent.
- **RS-T01:** A delivery must have a signed receipt if the value of the delivery exceeds USD 10,000.
- **RS-T08:** A nonprofit applicant need not pay the deposit.
- **RS-T07:** A visitor accompanied by a curator may enter the archive.

The subject must open with *A, An, Each, Every, The* or *Only*. That restriction is a parser choice. RS-19 asks for an explicit subject, and RS-20 allows a plural group subject when the collective is meant. So "Customers must register." is valid RuleSpeak that this profile rejects as unsupported.

## Diagnostics

**Kind** follows the ruleset's categories (form, meaning, style, principle, application), plus `profile` and `local` for checker and project limits. Each disposition works as follows:

- **error** decides its outcome.
- **review** needs a reviewer to confirm it.
- **warning** is reported only.
- **info** is a note.

| Code | Detects | Kind | Disposition | Basis | RS ids |
| --- | --- | --- | --- | --- | --- |
| RS-KW-001 | No rule or advice keyword detected | form | error | sourced | RS-01, RS-02 |
| RS-KW-002 | Modal needing interpretation detected | meaning | review | sourced | RS-03 |
| RS-KW-003 | More than one rule keyword detected | form | review | inferred | RS-01 |
| RS-KW-004 | "must … only" detected | form | review | inferred | RS-01, RS-04, RS-09 |
| RS-ADV-001 | "may … if" detected | form | error | sourced | RS-10 |
| RS-APP-001 | Temporal application of form 3.2 | application | info | sourced | RS-16 |
| RS-STY-001 | Leading qualification | style | warning | sourced | RS-20 |
| RS-STY-002 | System term detected | principle | review | inferred | RS-24 |
| RS-STY-003 | Sequence term detected | principle | review | inferred | RS-24 |
| RS-STY-004 | Redundant emphasis detected | style | warning | inferred | RS-23 |
| RS-VAG-001 | Vague term detected | style | review | inferred | RS-23 |
| RS-VAG-002 | "and/or" detected | meaning | review | inferred | RS-27 |
| RS-EXT-001 | "unless" condition, profile extension | profile | info | local | none |
| RS-EXT-002 | Necessary-condition classification, profile extension | meaning | review | inferred | RS-06, RS-12, RS-13 |
| RS-PRF-001 | Form not supported by this profile | profile | error | local | none |
| RS-PRF-002 | Parser requires the subject first | profile | error | local | none |
| RS-PRF-003 | Not one sentence ending in a full stop | profile | error | local | none |
| RS-LOC-001 | Over the local word limit | local | warning | local | none |
| RS-VOC-001 | No supplied vocabulary term found in the subject | local | error | local | RS-22 |
| RS-VOC-002 | Subject uses a proposed vocabulary term | local | review | local | RS-22 |

## Golden case format

Every case in [`tests/fixtures/rulespeak_cases.yaml`](../../tests/fixtures/rulespeak_cases.yaml) records two expectations separately:

- **`checker`** is what the deterministic checker must return. The tests in both cores assert it.
- **`rulespeak`** is the expert's assessment: the form verdict, fidelity, and the RS ids that justify it. The checker tests don't assert it. It labels the agent and SLM evaluations, and it shows where the checker and RuleSpeak disagree.

Each case also carries a one-line `reason`, and an `origin` when it comes from a traced example in the ruleset.

Here is how the two can differ. "A temporary badge must expire at midnight when the badge is issued." (E4) is accepted by the checker and conforms on form there. A RuleSpeak expert marks it undetermined, because the time relation is unclear (RS-15, RS-17). "Customers must register." is rejected by the checker but labelled as conforming RuleSpeak.

## Known limits

- The word lists are heuristics. That is why they produce review findings, not errors.
- The subject is everything between the determiner and the keyword. A vocabulary hit means only that a term string occurs there (RS-22).
- The vocabulary is closed. `check(statement, vocabulary, proposed=[...])` also takes the terms a response proposes. A subject that uses only a proposed term gets RS-VOC-002, a review finding, so the statement still passes and waits for the user to confirm the term. Only the subject is checked, so terms in the predicate or condition are not.
- The checker doesn't parse English, and it can't check meaning (RS-12 to RS-18), lists (RS-26 to RS-29) or fidelity. Those are left to the SLM and review.
