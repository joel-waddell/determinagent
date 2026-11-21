# Domain specification (Phase 0.1)

This is workstream 0.1 of the [program of work](../program-of-work.md). It defines the two POC domains, the three tasks and the grammar for each output format, precisely enough that most checking is deterministic and the SLM is left with the semantic work.

- [RuleSpeak](rulespeak.md): sentence templates, keywords and defect taxonomy
- [Gherkin](gherkin.md): official grammar plus the DeterminAgent profile

## What is deterministic and what is not

| Check | Who does it |
| --- | --- |
| Statement is one sentence, has one rule keyword, matches an approved template | Checker |
| Avoided modals, system or procedural wording, vague terms, `and/or` | Checker |
| Subject uses a term from the supplied vocabulary | Checker |
| Gherkin parses with the official parser | Checker |
| Scenario structure: names, Given/When/Then order, outlines and examples | Checker |
| The rule or scenario says what the business intended | SLM, scored by rubric |
| Terms are used consistently with their definitions | SLM |
| A rule is atomic in meaning, not just in wording | SLM |
| A scenario's steps are concrete and testable | SLM, scored by rubric |

## Tasks

Field lists below are the working definition for 0.2 (golden set) and 0.7 (contracts). They are not frozen until 0.7.

### T1 RuleSpeak generation

- **Input:** business intent (one constraint, stated in plain terms), the domain vocabulary (fact model terms), and optional context such as the policy source.
- **Output:** one or more rule statements, each conformant to the RuleSpeak profile and using only vocabulary terms as subjects.
- **Deterministic acceptance:** every statement passes `rulespeak.check(statement, vocabulary)`.
- **Semantic acceptance:** the statements express the intent, no more and no less (rubric, Phase 0.2).

### T2 RuleSpeak validation

- **Input:** one or more rule statements and the domain vocabulary.
- **Output:** per statement, a verdict (conformant or not) and a list of defects, each with a code from the RuleSpeak defect taxonomy or a semantic defect code (to be defined in 0.2).
- **Deterministic part:** the checker's defects are taken as given. The SLM adds semantic defects only.
- **Metric:** precision and recall of the reported defects against labelled cases.

### T3 Gherkin requirements

- **Input:** a user requirement (role, capability, benefit and acceptance criteria where available).
- **Output:** one Gherkin Feature with at least one Scenario, conformant to the Gherkin profile.
- **Deterministic acceptance:** `gherkin.check(document)` is conformant.
- **Semantic acceptance:** scenarios cover the acceptance criteria and are testable (rubric, Phase 0.2).

## Versioning

The profiles in `src/determinagent/spec/` carry a `version`. Any change to a template, keyword list or defect code changes what "well-formed" means for the golden set, so it is a versioned change that goes through the same review as the golden set itself.
