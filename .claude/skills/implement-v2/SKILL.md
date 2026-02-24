---
name: implement-v2
description: Implement tasks from a design doc using a structured subagent workflow with a dedicated GPT-5.3-Codex unit-test agent and GPT-5.3-Codex reviewers. Use when executing implementation plans that require strict implementation, testing, and review separation.
disable-model-invocation: true
---

# Implementation from Design Doc (v2)

## Overview

Execute implementation using subagent-driven development. Each task gets:
1. Implementation by an implementer subagent (feature code only)
2. Unit tests by a dedicated unit-test implementer subagent (`gpt-5.3-codex`)
3. Two parallel review subagents (`gpt-5.3-codex` for both design alignment and code quality)
4. User approval before committing

**Input required:** Design doc path (e.g., `@docs/plans/YYYY-MM-DD-<topic>-design.md`)

## Model Requirements (Strict)

For every task:
- Unit-test implementer MUST use `model: gpt-5.3-codex`
- Design alignment reviewer MUST use `model: gpt-5.3-codex`
- Code quality reviewer MUST use `model: gpt-5.3-codex`

If `gpt-5.3-codex` is unavailable, STOP and ask the user how to proceed. Do not silently fall back.

## Before Starting

1. Read the design doc completely
2. Read `CLAUDE.md` and `AGENTS.md` for coding standards
3. Ask user for ticket key if not mentioned in the design doc
4. Create a feature branch (see naming below)
5. Commit the design doc and PR proposal
6. Extract all tasks from the design doc
7. Create TodoWrite with all tasks (status: pending)

### Branch Naming

**Format:** `<scope>/feat/<ticket-key>-<brief-description>`

Example: `sharepoint-connector/feat/UN-12345-http-proxy`

**If branch already exists (not checked out):**
1. Check with `git branch --list "<branch-name>"`
2. If exists, append version suffix: `-v2`, `-v3`, etc.
3. Example: `sharepoint-connector/feat/UN-12345-http-proxy-v2`

**To create:**
```bash
git checkout -b <branch-name>
```

## The Process

For each task:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Dispatch implementer subagent                            │
│    └─> If questions: answer, re-dispatch                    │
│    └─> Implements feature code only, does NOT commit        │
├─────────────────────────────────────────────────────────────┤
│ 2. Dispatch unit-test implementer subagent                  │
│    └─> MUST use model: gpt-5.3-codex                        │
│    └─> Writes/updates tests only, does NOT commit           │
├─────────────────────────────────────────────────────────────┤
│ 3. Dispatch TWO review subagents IN PARALLEL:               │
│    ├─> Design alignment reviewer (gpt-5.3-codex)            │
│    └─> Code quality reviewer (gpt-5.3-codex)                │
├─────────────────────────────────────────────────────────────┤
│ 4. If issues found:                                          │
│    └─> Dispatch fix subagent with specific issues            │
│    └─> Re-run test implementer/reviews as needed             │
├─────────────────────────────────────────────────────────────┤
│ 5. Present summary, wait for user confirmation               │
├─────────────────────────────────────────────────────────────┤
│ 6. On approval: commit and mark task complete                │
└─────────────────────────────────────────────────────────────┘
```

## Subagent Prompts

### Implementer Subagent

```
Task tool (generalPurpose):
  description: "Implement: <task title>"
  prompt: |
    You are implementing a task from a design document.

    ## Task
    <task title>: <task description from design doc>

    ## Design Context
    <relevant sections from design doc - paste here, don't make subagent read file>

    ## Coding Standards
    - Follow CLAUDE.md and AGENTS.md in the repo root
    - Implement feature code only in this step
    - Do not add unit tests in this step; tests are handled by the dedicated unit-test implementer subagent

    ## Before You Begin
    If anything is unclear about the requirements or approach, ask now.

    ## Your Job
    1. Implement exactly what the task specifies
    2. Verify implementation works
    3. Do NOT commit - report back for review

    ## Report Format
    Keep it short:
    - What you implemented (1-2 sentences)
    - Files changed
    - Only mention things that were unexpected or had to differ from design
```

### Unit-Test Implementer Subagent

```
Task tool (unit-test-specialist):
  model: gpt-5.3-codex
  description: "Implement unit tests: <task title>"
  prompt: |
    You are writing and validating tests for code implemented from a design task.

    ## Task
    <task title>: <task description from design doc>

    ## Implementation Context
    <brief summary of what implementer changed>
    <files changed by implementer>

    ## Rules
    - Follow CLAUDE.md and AGENTS.md in the repo root
    - Update/add tests only unless tiny testability adjustments are strictly required
    - Prefer behavioral tests over implementation-detail assertions
    - Reuse existing test setup and patterns in this repository
    - Do NOT commit

    ## Your Job
    1. Identify required test scenarios for this task
    2. Write or update tests
    3. Run relevant tests and fix failures
    4. Report back concisely

    ## Report Format
    - Scenarios covered
    - Files changed
    - Any assumptions/blockers
```

### Design Alignment Reviewer (run in parallel with code quality)

```
Task tool (generalPurpose):
  model: gpt-5.3-codex
  description: "Review design alignment: <task title>"
  readonly: true
  prompt: |
    Review whether this implementation matches the design document.

    ## Design Requirements
    <relevant sections from design doc>

    ## Task Being Reviewed
    <task title>: <task description>

    ## Your Job
    Read the actual code and verify:

    **Missing requirements:**
    - Did they implement everything requested?
    - Are there requirements they skipped?

    **Extra work:**
    - Did they build things not in the design?
    - Over-engineering?

    **Misunderstandings:**
    - Did they interpret requirements differently?

    ## Report
    - ✅ Aligned with design
    - ❌ Issues: [specific list with file:line references]
```

### Code Quality Reviewer (run in parallel with design alignment)

```
Task tool (generalPurpose):
  model: gpt-5.3-codex
  description: "Review code quality: <task title>"
  readonly: true
  prompt: |
    Review code quality for this implementation.

    ## What Was Implemented
    <brief summary>

    ## Your Job
    Check:
    - Code clarity and maintainability
    - Proper error handling
    - Test quality (behavioral, not shallow mocks)
    - Follows existing patterns in codebase
    - No obvious bugs or issues

    ## Report Format
    **Strengths:** (brief)
    **Issues:**
    - Critical: [blocks progress]
    - Important: [should fix]
    - Minor: [nice to have]
    **Assessment:** Ready / Needs fixes
```

## After Each Task

Present the summary and wait for user confirmation. Do NOT use AskQuestion - user needs to review changes first.

```
Task complete: <task title>

Unit tests: ✅ / ❌ <brief result>
Design alignment: ✅ / ❌ <brief result>
Code quality: Ready / Needs fixes - <brief result>

<Any notes: unexpected things, deviations from design, unaddressed review feedback>

Ready to commit and continue to next task.
```

Keep summaries short - do not summarize full changes (user sees them in Cursor).

**Wait for user response:**
- "Looks good, continue" / "Made adjustments, continue" / ok / etc -> commit changes, mark task complete, proceed
- User provides feedback -> address it, then present summary again

## After All Tasks Complete

1. Update PR proposal file if implementation differed from design
2. Tell the user:

```
Implementation complete!

To review the full implementation against the design, start a new session and run:
/review @docs/plans/YYYY-MM-DD-<topic>-design.md

To push and create PR:
/ship @docs/pr-proposals/YYYY-MM-DD-<topic>.md
```

## Red Flags

**Never:**
- Skip the dedicated unit-test implementer step
- Skip reviews (both design alignment AND code quality)
- Proceed with unfixed Critical/Important issues
- Commit without user approval
- Make subagents read the design doc file (paste relevant content)
- Write implementation details not in design (ask first)

**Always:**
- Run unit-test implementer after feature implementation and before reviews
- Run both reviews in parallel after implementation and test updates
- Use `gpt-5.3-codex` for unit-test implementer and both review subagents
- Wait for user confirmation before committing
- Keep summaries short
- Dispatch fix subagent for issues (do not fix manually - context pollution)
