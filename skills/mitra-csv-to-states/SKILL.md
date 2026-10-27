---
name: mitra-csv-to-states
description: |
  Generate a Mitra voice-bot's global_context.txt and per-question state_<step_number>_prompt.txt files from a question-bank CSV (columns: Step Number, Main Question, Expected responses, When To Probe). Use whenever the user has a survey/interview question bank in a CSV or spreadsheet and wants it turned into the state-machine prompt files for the Mitra chatbot harness (the one with structured_memory_output-style JSON turns, PRIMARY questions, one-probe-then-complete state derivation). Trigger on mentions of "question bank", "state prompts", "global_context.txt", "state_N_prompt", or a CSV of survey questions meant to become interview-bot states — even if the user just pastes a CSV and says "turn this into states" or "build the prompts for this".
---

# Mitra CSV → state files

Turns a question-bank CSV into the exact file set the Mitra harness consumes: one `global_context.txt` (fixed — persona, guardrails, JSON contract, probe budget, generic completion-judgment logic) plus one `state_<step_number>_prompt.txt` per question (just PRIMARY + a completion goal).

## Step 1 — global_context.txt: copy, don't regenerate

`assets/global_context_template.txt` in this skill IS the global_context.txt — persona, domain vocabulary, and programme context are hardcoded there because they're the same across every Mitra survey. Copy it to the target directory verbatim as `global_context.txt`. Do not rewrite its prose, add fields, or change the JSON schema — if the user wants persona/tone changed, edit the template file in this skill (so it stays the shared source of truth for next time), then copy.

If the target directory already has a `global_context.txt`, read it first and diff mentally against the template — if someone customized it on purpose (e.g. a different persona for a different bot), ask before overwriting rather than clobbering it.

## Step 2 — parse the CSV

Run:
```
python3 scripts/parse_questions_csv.py <path-to-csv> --out <scratchpad>/questions.json
```

Columns are matched by header name (case/space-insensitive): Step Number, Main Question, Expected responses, When To Probe — all four required. Output is a flat JSON array, one record per CSV row:

```json
{
  "step_number": "14",
  "main_question": "...",
  "expected_responses": "...",
  "when_to_probe": "..."
}
```

`main_question`, `expected_responses`, `when_to_probe` are lowercased. Multi-line cells are flattened (main question lines joined with a space, other fields with "; "). Blank `when_to_probe` = `""`. The script errors on a row missing Step Number or a duplicate Step Number — fix the CSV, don't work around it.

Read the resulting JSON before writing anything.

## Step 3 — one state_<N>_prompt.txt per question

For each record, write `state_<step_number>_prompt.txt` in this shape:

```
<state id="<STATE_NAME>">
=== PRIMARY ===

"<main_question, exactly as in the JSON>"

=== COMPLETION GOAL ===

<one short paragraph — see below>

</state>
```

**State id**: `<STATE_NAME>` is a name you generate from the question's topic, in ALL-CAPS words joined by underscores (e.g. "what is your address?" → `LOCATION_INFORMATION`; a question about school visits → `SCHOOL_VISITS`). 2–4 words, describing what the question collects, not how it's worded. Must be unique across all states in this run. The step number goes only in the filename, not in `id`.

**Writing the completion goal.** This is the part that needs judgment, not templating. The goal describes the answer and never the action. The decision table in global_context.txt decides when to probe and when to complete, so a state file never says probe, ask, skip, move on, complete after, or no probe.

Write every goal in this shape:

```
=== COMPLETION GOAL ===

Parts: <part>, <part>
- <part>: <what counts as this part>
- <part>: <what counts as this part>

Complete: <which parts must be given>
Incomplete: <what an answer that falls short looks like, with one or two example replies>
```

- **Parts are the separate things a complete answer must contain.** The bot marks each part given or not given before it decides anything, and a part marked not given is what triggers the probe. Most questions have one part. Use two when the question asks for two things ("how satisfied, and why"; "easy or hard, and what makes it so"). If you reach three, merge the ones that are always answered together.
- **Name each part with one lowercase word** (`level`, `reason`, `school_type`). The bot copies these names into its reason line, so keep them short and distinct.
- **Define each part from `expected_responses`.** Describe the shape of an acceptable answer, not the literal strings. Don't paste the CSV cell: it is often a raw list such as "Government School/Private School", and the bot should judge meaning, not match keywords.
- **If `when_to_probe` is blank:** write one part, define it loosely, and end the definition with "A few words are enough." `Complete:` is that the part is given. `Incomplete:` is that nothing answers the question, for example a sentence that stops before the answer.
- **If `when_to_probe` is non-blank:** it tells you which part respondents usually leave out. Make that its own part and define it tightly enough that a vague answer does not count. Empty, off-topic and garbled replies need no line of their own, because no part is given in them. Never write a separate "ask them to rephrase" instruction.
- **Put the near-miss in `Incomplete:`, in the respondent's words.** Say which part a short verdict has and which it lacks: `"Very satisfied" on its own has the level and no reason.` If a part has a qualifier (the reason must be about the child's learning), repeat the near-miss here: `A reason that is not about the child's learning does not count as the reason.`
- **Do not copy question text from `when_to_probe` as a scripted probe.** Treat it as a hint about which part is missing. The bot composes its own probe from what the respondent said, following `<probe_rules>`. Don't write `probe by asking "Can you please tell us why it is easy for you?"`. Write the part: `reason: what specifically makes it easy or hard for them`.
- **Conditional cases** (`when_to_probe` has several "If X: ..." lines) become conditions inside a part's definition, never an if/else of actions. Easy/hard: `reason: what makes it easy if they said easy, or what makes it hard if they said hard or mixed`. A branch that needs no detail goes into the definition too: `detail: what happened, or a statement that nothing happened or that they don't remember`.
- Skip refusal handling, the probe budget, position and the JSON contract. Those live in global_context.txt and apply to every state. A state file is PRIMARY plus this block.

Two-part example (`when_to_probe` non-blank):

```
Parts: level, reason
- level: how satisfied the parent is with their child's studies. Any position counts: satisfied, unsatisfied, okay, mixed.
- reason: at least one reason about how the school is or isn't helping the child learn (teaching quality, teachers, what the child is learning, skills beyond marks).

Complete: level and reason are both given.
Incomplete: a part is not given. "Very satisfied" or "not happy" on its own has the level and no reason. A reason that is not about the child's learning at school does not count as the reason.
```

One-part example (`when_to_probe` blank):

```
Parts: reason
- reason: any reason or occasion for visiting the school (meetings, talking with teachers, events, volunteering), or a statement that they don't usually visit. A few words are enough.

Complete: the reason is given.
Incomplete: no reason or occasion is named, for example a sentence that stops before the reason.
```
## Step 4 — verify persona matches the questions

Runs only after global_context.txt and every state_<N>_prompt.txt are written. Read the `<persona>` block of the copied `global_context.txt` and check it against the full set of questions in the parsed JSON:

- **Respondent**: who the questions are addressed to (parents, teachers, students, headmasters, community members...). Persona must name that group.
- **Topic**: what the survey is about (child's school, teaching practice, a programme, health...). Persona's subject must cover it.
- **Language/tone fit**: anything in the persona that contradicts the questions (e.g. "avoid education jargon" when questions are for teachers and use pedagogical terms).

If persona matches, leave it untouched. If not, edit only the `<persona>` block in the target directory's `global_context.txt` — swap respondent group, topic, and any mismatched tone line, keeping the same structure, length, and the second paragraph (silence on completion) verbatim. Don't touch the template in `assets/`, and don't touch any other block of global_context.txt. Tell the user what changed and why.

## Step 5 — sanity check before handing back

- Every `step_number` from the parsed JSON has exactly one `state_<step_number>_prompt.txt`.
- Every `<state id>` is an ALL-CAPS name joined by underscores, and no two states share one.
- No state file's completion goal contains a verbatim scripted question in quotes for the probe — only PRIMARY should have quoted respondent-facing text.
- No state file re-implements REFUSAL, probe-budget, or JSON-shape rules that global_context.txt already owns.
- If the user only gave you a subset of questions or an updated CSV for an existing survey, only touch the state files for Step Numbers present in this run — don't delete or renumber others unless asked.

Tell the user which files you wrote and flag any question where the CSV data was ambiguous enough that you had to make a judgment call (e.g. unclear probe condition, missing Expected responses) so they can double check it.
