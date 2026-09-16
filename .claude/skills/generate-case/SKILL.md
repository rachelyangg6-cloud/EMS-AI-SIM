---
name: generate-case
description: >
  Draft a new EMS practice call grounded in the vetted wiki, gate it against the
  playability checks, and save it as pending for EMT review. You are the LLM —
  no Anthropic API is called. Use when the user wants more practice calls, or
  calls covering a particular condition. Takes one or more condition slugs.
---

# Generate Case

Write one new practice call from the wiki's own pages, then let the deterministic
gate decide whether it is good enough to save. **You are the LLM here** — no
Anthropic API is called, exactly as in `generate-scenarios` and `ingest-source`.

Input: one or more condition slugs (ask if not given).

## Why the gate exists

The corpus is 196 approved scenarios and only 95 can be played as a call. The
other 101 fail for reasons found by actually playing them: a dispatch that names
no patient, a Presentation written as "You are…", a blank monitor, an oxygen
order with no device. **Adding more of those is worse than adding nothing**, so
nothing unplayable is saved — the gate reports what is wrong and you fix it.

## 1. Read the grounding

```bash
python -m ems.cli.generate --context asthma hypoxia
```

That prints the wiki pages retrieved for those slugs, with their citations. It is
the only clinical source you may use. If a step is not supported by something in
there, leave the step out — do not fall back on what you happen to know.

Read the accumulated lessons too. They are failures real reviewers found, and
they are the difference between a draft that gets approved and one that repeats a
known mistake:

```bash
python -m ems.cli.review --lessons
```

## 2. Write the call

Six sections, in this order, in a scratch file:

```markdown
## Dispatch
62-year-old man, chest pain and short of breath, conscious and alert.

## Presentation
He is sitting on the edge of the bed, gray and sweating, one hand on his chest…

## Vitals
RR 24, pulse 108, SpO2 93%, BP 156/94; skin cool and diaphoretic, alert.

## Correct actions
1. Take Standard Precautions and perform a primary assessment [SRC-20:p578]
2. …

### Write each step as the sentence the trainee will say

This is the single thing that goes wrong most often, and it went wrong in every
draft reviewed so far. The rubric is not a summary of the source for a reader.
**It is the list of things a person will say out loud on this call**, and it is
matched against their words. Write the sentence first, then attach the citation.

Before you write a step, ask: *would an EMT say this?* If not, it is not a step.

| Written as prose (all of these failed) | What the trainee would actually say |
|---|---|
| "Do not delay epinephrine to finish the history — it is the priority" | *number the epinephrine step before the history step* |
| "Ensure a safe scene, because patients with diabetic emergencies can be agitated" | "Ensure the scene is safe and take Standard Precautions" |
| "Be prepared to give a second dose if she does not improve" | "Reassess two minutes after the dose and give a second if she has not improved" |
| "Recognize that she is not awake enough to swallow, and withhold oral glucose" | "Withhold oral glucose and stop the coworker putting gel in her mouth" |
| "Understand that alcohol withdrawal can be fatal" | *delete — this is rationale, not an action* |

Four rules follow from that:

1. **Lead with the verb.** An action behind a `because` clause matches nothing —
   a trainee who sized up the scene got no credit, because the step began
   "Ensure a safe scene, because…" and the grader saw commentary.
2. **No contingencies.** "Be ready to ventilate" puts a ventilation step in the
   answer key, and the trainee is then nudged to bag a patient breathing at 22
   with a saturation of 97. Write the action the call needs; put the *if* in
   `## Rationale`.
3. **Ordering is expressed by numbering**, never by prose. The grader reads the
   numbers as the sequence and marks a time-critical treatment down when it is
   done after steps listed later.
4. **Facts go in `## Rationale`, findings in `## Red flags`.** Red flags are not
   scored and are never spoken — they are what the case turns on.

**Two steps must not be interchangeable.** If one step's meaning is contained in
another — "Obtain a SAMPLE history" beside "Ask specifically about previous
allergic reactions" — a trainee who says only the general thing gets credit for
the specific one they never asked. Either make the second name something
concrete the first does not, or fold them together.

### Check before saving

```bash
python -m ems.cli.rubric_check --generated
```

The gate refuses any step carrying no action it can see, so a draft that fails
this is not saved at all. Fix the wording rather than arguing with it — every
rule here exists because a reviewer lost points on a step they had performed.

## Rationale`; warning signs go in `## Red flags`.

**Express ordering by position.** If epinephrine must precede the history,
number it before the history. The grader reads the numbering as the order the
call should run in and marks a time-critical treatment down when it is done
after steps the rubric puts later. "Do not delay X" leaves it ungraded.

**Express a contingency as the action that reveals it** — "Reassess 2 minutes
after the dose and give a second if she has not improved."

Check before saving:

```bash
python -m ems.cli.rubric_check --generated
```

## Rationale
Why these are the right steps, in plain language.

## Red flags
- …
```

Rules the gate enforces, so writing to them saves a round trip:

- **Dispatch names a person AND a complaint.** It is read aloud as a radio
  tone-out. "Chest-pain patient; a family member offers a pill" is a teaching
  frame, not a dispatch.
- **Presentation is third person, on arrival.** Never "You are…" — that cannot be
  narrated when the doors open, and the patient ends up reciting it back.
- **Vitals give RR, pulse, SpO2 and BP as numbers**, consistent with the
  condition and with the patient's age. An SpO2 of 97% beside "severe distress"
  teaches the wrong reflex; a five-month-old does not have a BP of 118/68.
- **Every oxygen step names the device AND the rate** — NC 2–6 L/min, NRB 12–15,
  BVM 15 with a reservoir.
- **Every `## Correct actions` line ends with a citation** copied exactly from
  the grounding. Invented citations are stripped before saving.
- **US English.**

## 3. Gate it and save

```bash
python -m ems.cli.generate --from-file /tmp/draft.md --conditions asthma hypoxia
```

Playable → written to `wiki/scenarios/generated/gen-YYYYMMDD-NN.md` as
`status: pending`. Not playable → nothing is written and each problem is printed.
Fix and run it again; that is faster than any retry loop.

Nothing in `wiki/scenarios/generated/` is approved and the simulator cannot deal
it. It becomes a real case only when an EMT reviews it.

## 4. Hand it over

Tell the user the draft is ready, show them the dispatch and presentation, and
offer to play it (`protocol-practice --scenario gen-…`) or review it
(`protocol-review`). Approving promotes it into `wiki/scenarios/`; rejecting
keeps it and turns the critique into a lesson for the next draft.

## Wrap-up

Report the file written, the pages it was grounded in, and any citations that
were stripped. If the gate refused it, say what was wrong and what you changed —
those failures are worth the user seeing, because they are what the gate is for.
