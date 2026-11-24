# Domain specification (Phase 0.1)

This is workstream 0.1 of the [program of work](../program-of-work.md). It defines the two POC domains, the three tasks and the grammar for each output format, precisely enough that most checking is deterministic and the SLM is left with the semantic work.

- [RuleSpeak](rulespeak.md): sentence templates, keywords and defect taxonomy
- [Gherkin](gherkin.md): official grammar plus the DeterminAgent profile

## What is deterministic and what is not

| Check | Who does it |
| --- | --- |
| Statement is one sentence, has a rule or advice keyword, and matches a supported template | Checker |
| Surface patterns that need review: modals, repeated keywords, system or sequence terms, vague terms, `and/or` | Checker flags, reviewer or SLM decides |
| Subject contains a term from the supplied vocabulary (local policy) | Checker |
| Gherkin parses with the official parser | Checker |
| Scenario structure: names, Given/When/Then order, outlines and examples | Checker |
| The rule or scenario says what the business intended (fidelity) | SLM, scored by rubric |
| Terms are used consistently with their definitions | SLM |
| A rule is atomic in meaning, not just in wording | SLM |
| A scenario's steps are concrete and testable | SLM, scored by rubric |

## Tasks

Field lists below are the working definition for 0.2 (golden set) and 0.7 (contracts). They are not frozen until 0.7.

### T1 RuleSpeak generation

- **Input:** business intent (one constraint, stated in plain terms), the domain vocabulary (fact model terms), and optional context such as the policy source.
- **Output:** one or more rule statements, each conformant to the RuleSpeak profile and using only vocabulary terms as subjects.
- **Deterministic acceptance:** every statement passes `rulespeak.check(statement, vocabulary)` in either core, with `guidance_type: rule`. Review findings are sent to the rubric.
- **Semantic acceptance:** the statements express the intent, no more and no less (rubric, Phase 0.2).

### T2 RuleSpeak validation

- **Input:** one or more rule statements and the domain vocabulary.
- **Output:** per statement, the RuleSpeak form verdict (conforms, needs revision, undetermined) and fidelity (preserved, changed, unverified), with each finding traced to RS ids, following the response contract in RuleSpeak-Agent.md.
- **Deterministic part:** the checker's form errors are taken as given. The SLM resolves its review findings and adds meaning findings.
- **Metric:** precision and recall of the reported defects against labelled cases.

### T3 Gherkin requirements

- **Input:** a user requirement (role, capability, benefit and acceptance criteria where available).
- **Output:** one Gherkin Feature with at least one Scenario, conformant to the Gherkin profile.
- **Deterministic acceptance:** `gherkin.check(document)` is conformant in either core.
- **Semantic acceptance:** scenarios cover the acceptance criteria and are testable (rubric, Phase 0.2).

## Versioning

The profiles in `src/determinagent/spec/` carry a `version`. Any change to a template, keyword list or defect code changes what "well-formed" means for the golden set, so it is a versioned change that goes through the same review as the golden set itself.
