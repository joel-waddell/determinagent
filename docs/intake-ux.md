# Intake UX design sprint (Phase 0.6)

Phase 0.6 picks how users get their intent into DeterminAgent. The plan's first design principle drives the choice: constrain input at the edge, with free text as the exception. A good intake gets a typed request through that the schema accepts, from people who don't know RuleSpeak or Gherkin. The sprint has five steps:

1. Map the users.
2. Sketch three concepts.
3. Prototype the two strongest as clickable mock-ups.
4. Test them with users.
5. Choose the pattern.

Steps 1 to 3 are done here. Step 4 needs real users, so it needs Joel.

This covers the RuleSpeak and Gherkin tasks. The JavaScript J2 spec form belongs to the JavaScript workstream, but it would reuse whichever pattern wins.

## 1. Who writes rules and requirements, and what they start from

| User | What they start from | What they need from intake | Risk |
| --- | --- | --- | --- |
| **Business analyst** (main user) | Policy documents, meeting notes, a stakeholder's sentence ("refunds over $500 need a manager") | To turn one constraint into a correct statement quickly, without learning RuleSpeak first | Pastes whole paragraphs as free text |
| **Policy or compliance owner** | Regulations, internal policy with thresholds and exceptions | Confidence that the meaning is kept (thresholds, "more than" vs "at least", exceptions) | Can't see what the system assumed |
| **Product owner** | User stories ("As a … I want … so that …") and acceptance criteria | A Gherkin feature that covers every criterion, and questions where a criterion is vague | Vague criteria ("fast", "easy") |
| **QA engineer** | Acceptance criteria, bug reports, existing scenarios | Concrete, runnable scenarios with real example values | Wants to edit steps directly |
| **Rule steward or reviewer** (Joel's role) | A batch of statements written by others | To validate many statements and see each finding's evidence | Volume. Needs bulk paste, not one at a time |

Three things follow from this:

- **The intake must accept the raw starting point.** Most users begin with a sentence or a user story. The intake should take that sentence, then help turn it into typed fields, instead of making users start from a blank form.
- **Assumptions must be visible.** Compliance owners need to see and confirm the threshold, quantifier and condition type, since that is where meaning drifts (RS-17).
- **Validation needs bulk input.** One statement at a time is fine for authors but not for reviewers. The T2 request already accepts up to 50 statements.

## 2. Three concepts

### A. Typed form

There is one form per task. Generation asks for the constraint type (obligation, prohibition, restricted permission and so on), the subject (picked from the vocabulary), the action, conditions (each with if, when, before, after or unless, plus its text) and a qualification. Gherkin asks for the role, the capability, the benefit and a list of acceptance criteria. A free-text box is offered only behind "I can't fit it into the fields".

- **For it:** it maps one-to-one onto the v1 request schema, so schema rejections should be near zero. It's quick to build, and accessible by default.
- **Against it:** users must know which constraint type they mean before they start, which is the hardest question for a non-expert. The output can feel distant from the input.

### B. Template-guided editor

The user first types or pastes their sentence. The editor suggests the RuleSpeak template that fits (for example, "<subject> must <predicate> if <condition>") and shows it as a sentence with slots. The user fills or corrects each slot inline, choosing the subject from the vocabulary and the condition kind from a menu. A live preview shows the statement and the checker's result as they type. For Gherkin, the user fills Given, When and Then slots for each acceptance criterion, with "add a negative case" prompts.

- **For it:** it starts from what users already have, a sentence. It teaches RuleSpeak by showing it. The checker gives feedback before submission. Slots make the assumptions visible.
- **Against it:** it is more complex to build, because it needs a client-side template matcher. That already exists, since the checker runs in JavaScript. Suggesting a template from a sentence is a guess, which the user has to confirm.

### C. Node canvas

The user drags blocks for the subject, the action, each condition and the exceptions onto a canvas and wires them together. Several rules can share a subject or a threshold node, which shows how they connect (RS-18, RS-25).

- **For it:** it is the best view of how rules relate and where they conflict. It would be strong for a rule steward reviewing a whole rule set.
- **Against it:** it is the slowest way to write one rule, and the hardest to make accessible and keyboard-friendly. Its main strength, relating many rules, is not what the POC tasks do: they handle one constraint or one requirement per request.

### Choice for prototyping

**A and B are prototyped. C is set aside**, and kept as a candidate for a later rule-set view in developer tooling (Phase 4). The POC tasks are single-constraint and single-requirement, so the canvas's strength isn't exercised, and it costs the most.

## 3. Mock-ups

Both mock-ups use the same refund example: "Refunds over $500 need a manager to approve them." Each one produces the same typed request, so the two can be compared on equal terms in testing. They are clickable artboards on a design canvas: [DeterminAgent intake mock-ups](https://claude.ai/artifact/DBRWDe4Kqusmd89nobQ2ss). The canvas is private to Joel until he shares it. Nothing is sent anywhere: the preview and checker result are simulated in the page.

- **A. Typed form:** the generation form with the constraint type, a subject from the vocabulary, the action and a list of conditions. It shows the resulting request JSON, and an expandable free-text fallback.
- **B. Template-guided editor:** a sentence box. A suggested template has inline slots for the subject, the predicate and the condition kind. It shows a live RuleSpeak preview with its checker result, and the same request JSON.

## 4. Test plan (needs Joel)

**Participants:** 5 to 6 people from the user map, at least two analysts and one compliance owner. Five users typically find most usability problems in a design this size. That is a common rule of thumb, not a measurement here.

**Tasks** (the same on both concepts, in alternating order to balance learning effects):

1. An obligation with a threshold: refunds over $500 need a manager's approval.
2. A conditional permission: a visitor may enter the archive only if a curator accompanies them.
3. Advice (exemption): returning customers don't have to give a phone number.
4. A Gherkin requirement with two acceptance criteria, one of them vague ("fast").

**Measures**, as named in the plan:

| Measure | How it is measured | What would decide it |
| --- | --- | --- |
| Completion | Task ends with a request the schema accepts and the user says matches their intent | Below 80% on any task fails that concept for that task |
| Time taken | Start to submit, per task | Median under 2 minutes for tasks 1 to 3 |
| Free-text leakage | Share of submissions that used the free-text fallback | Under 10%: this is the plan's "free text is the exception" |
| Schema rejection rate | Share of submit attempts the v1 request schema rejected | Under 5% |
| Meaning kept | An expert compares the request with the task's intent (threshold, direction, guidance type) | Any change of meaning is a severity-1 finding |

## 5. Decision rule

Pick B if it is at least as good as A on completion and meaning kept, and better on time or free-text leakage. Otherwise pick A. A is cheaper and maps directly onto the schema, so it wins ties. Then choose the UI stack. The JavaScript core already runs the checker in the browser, which favors a plain web front end on the existing `js/` core.

The choice may add typed intent fields, so the 0.7 contracts freeze after this decision ([contracts.md](contracts.md)).
