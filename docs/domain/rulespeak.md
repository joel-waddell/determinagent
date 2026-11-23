# RuleSpeak profile v0.1.0

RuleSpeak is a set of guidelines from Business Rule Solutions (Ronald G. Ross) for writing business rules in structured natural language. This profile formalizes the parts that can be checked deterministically. The machine-readable source of truth is [`rulespeak.yaml`](../../src/determinagent/spec/rulespeak.yaml), and the checker is [`js/src/conformance/rulespeak.js`](../../js/src/conformance/rulespeak.js), with a Python twin in [`conformance/rulespeak.py`](../../src/determinagent/conformance/rulespeak.py). Patterns use Python's `(?P<name>…)` group syntax, which the JavaScript loader converts.

> Status: draft. The templates and word lists need review by someone who writes RuleSpeak professionally before golden-set labelling starts (0.2).

## Basic shape

A rule statement is one sentence that:

1. opens with the subject, introduced by a determiner (*A, An, Each, Every, The*) or by *Only*,
2. carries exactly one rule keyword, *must* or *may … only*, early in the sentence,
3. puts any condition after the rule, introduced by *if* or *unless*,
4. ends with a full stop.

## Approved sentence templates

Templates are tried in this order, and the first match wins.

| Id | Name | Kind | Form | Example |
| --- | --- | --- | --- | --- |
| RS-T06 | Computation | definitional | *term* must be computed as *expression* | The order total must be computed as the sum of the line item amounts. |
| RS-T05 | Classification | definitional | *term* is always / never considered *classification* if / unless *condition* | A customer is always considered preferred if the customer has placed more than 10 orders. |
| RS-T05b | Restricted classification | definitional | *term* is considered *classification* only if *condition* | A shipment is considered late only if it is delivered after its promised date. |
| RS-T02 | Prohibition | behavioral | *subject* must not *predicate* [if / unless *condition*] | An order must not be shipped if the outstanding balance exceeds the credit limit. |
| RS-T03 | Restricted permission | behavioral | *subject* may *predicate* only *restriction* | A refund may be issued only if the purchase was made within the last 30 days. |
| RS-T04 | Restricted eligibility | behavioral | Only *qualified subject* may *predicate* | Only a manager may approve a discount above 20 percent. |
| RS-T01 | Obligation | behavioral | *subject* must *predicate* [if / unless *condition*] | Each order must have at least one line item. |

A match returns named slots (`subject`, `predicate`, `condition` and so on), which later phases can use for routing and for semantic checks.

## Defect taxonomy

Errors make a statement non-conformant. Warnings are reported only. These codes are the labels for the RuleSpeak validation golden set.

| Code | Severity | Defect | Example that triggers it |
| --- | --- | --- | --- |
| RS-STR-001 | error | Not a single sentence | A customer must have an account. The account must be active. |
| RS-STR-002 | error | More than one rule | An order must have a customer and must have at least one line item. |
| RS-STR-003 | error | Leading condition | If the balance is overdue, an order must not be shipped. |
| RS-KW-001 | error | Missing rule keyword | Orders are shipped within two days. |
| RS-KW-002 | error | Non-RuleSpeak modal (should, shall, can, will, has to …) | A customer should provide a delivery address. |
| RS-KW-003 | error | Unrestricted permission (*may* without *only*) | A customer may cancel an order. |
| RS-TPL-001 | error | No approved template | Customers must register. |
| RS-STY-001 | error | System-centric wording | The system must reject an order without a customer. |
| RS-STY-002 | error | Procedural wording (then, upon, afterwards …) | An order must be checked and then shipped. |
| RS-STY-003 | warning | Redundant *always* / *never* after *must* | An invoice must always have a due date. |
| RS-STY-004 | warning | Over 40 words | |
| RS-VAG-001 | error | Vague term (appropriate, as soon as possible, etc …) | A complaint must be answered as soon as possible. |
| RS-VAG-002 | error | *and/or* | A claim must be reviewed if it exceeds 1000 dollars and/or is flagged. |
| RS-VOC-001 | error | Subject not in the supplied vocabulary | (vocabulary: order, customer) Each shipment must have a carrier. |

## Known limits, for review

- **Word lists are heuristics.** *Some*, *many* and *upon* are flagged everywhere, which can catch legitimate uses. The golden set will show how often that happens, and the lists can then be tuned.
- **Subject extraction is positional.** The subject is everything between the determiner and the rule keyword. Adjectives are kept (*gold customer*), and the vocabulary check matches any vocabulary term inside it.
- **No grammar parse.** The checker does not parse English. It checks shape, keywords and wording; meaning is the SLM's job.
- **Questions for the reviewer:** should *Every* be allowed alongside *Each*? Should *must … only* (for example *A loan must be approved only by a credit officer*) be its own template? Is a leading condition always an error, or a warning?
