# Gherkin profile v0.1.0

Gherkin output is checked in two layers. The machine-readable source of truth is [`gherkin.yaml`](../../src/determinagent/spec/gherkin.yaml), and the checker is [`conformance/gherkin.py`](../../src/determinagent/conformance/gherkin.py).

1. **Official grammar.** The document must parse with the official Cucumber parser, the [`gherkin-official`](https://pypi.org/project/gherkin-official/) package. That is the grammar the plan names, so we use it rather than re-implementing it.
2. **DeterminAgent profile.** The official parser is permissive: free text under a Feature or Scenario becomes a description, so a document with no steps can still parse. The profile adds the structure a generated requirement must have.

> Status: draft for review alongside the RuleSpeak profile.

## Profile rules

- English only for the POC.
- Exactly one Feature, with a name, containing at least one Scenario or Scenario Outline (directly or inside a Rule).
- Every scenario has a name and at least one step, with at most 12 steps.
- Steps run Given, then When, then Then. *And* and *But* continue the previous step type. Every scenario has at least one When and one Then. A Given is expected unless a Background supplies the context.
- A Background contains only Given steps.
- A Scenario Outline has Examples with at least one row, and every `<placeholder>` in its steps has a matching Examples column.

## Defect taxonomy

| Code | Severity | Defect |
| --- | --- | --- |
| GK-PARSE-001 | error | Does not parse (official parser error, with line and column) |
| GK-LANG-001 | error | Language outside the profile |
| GK-STR-001 | error | No Feature |
| GK-STR-002 | error | Feature has no name |
| GK-STR-003 | error | No scenarios |
| GK-STR-004 | error | Scenario has no name |
| GK-STR-005 | error | Scenario has no steps |
| GK-STR-006 | warning | Duplicate scenario name |
| GK-SEQ-001 | error | Missing When |
| GK-SEQ-002 | error | Missing Then |
| GK-SEQ-003 | warning | Missing Given, and no Background |
| GK-SEQ-004 | error | Steps out of order (for example a When after a Then) |
| GK-SEQ-005 | error | Scenario starts with And or But |
| GK-SEQ-006 | error | Background has a non-Given step |
| GK-OUT-001 | error | Outline without Examples |
| GK-OUT-002 | error | Placeholder not in Examples |
| GK-OUT-003 | error | Examples table has no rows |
| GK-STY-001 | warning | Free text in a scenario |
| GK-STY-002 | warning | `*` used as a step keyword |
| GK-STY-003 | warning | Too many steps |

## Left to the SLM and the rubric

Whether the scenarios cover the requirement's acceptance criteria, whether steps are concrete (*Given an order delivered 10 days ago*, not *Given some order*) and whether each scenario tests one behavior in meaning. A deterministic step-wording lint (for example banning UI words like *click* in business-level scenarios) could be added once the golden set shows it is needed.
