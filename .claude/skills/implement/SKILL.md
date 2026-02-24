---
name: implement
description: Implement tasks from a design doc using a structured workflow.
disable-model-invocation: true
---

# Implementation from Design Doc

## Overview

Execute implementation using subagent-driven development. Each task gets:
1. Implementation by a subagent
2. Two parallel review subagents (design alignment + code quality)
3. User approval before committing

**Input required:** Design doc path (e.g., `@docs/plans/YYYY-MM-DD-<topic>-design.md`)

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
│    └─> Implements, tests, does NOT commit                   │
├─────────────────────────────────────────────────────────────┤
│ 2. Dispatch TWO review subagents IN PARALLEL :               │
│    ├─> Design alignment reviewer                            │
│    └─> Code quality reviewer                                │
├─────────────────────────────────────────────────────────────┤
│ 3. If issues found:                                         │
│    └─> Dispatch fix subagent with specific issues           │
│    └─> Re-run reviews                                       │
├─────────────────────────────────────────────────────────────┤
│ 4. Present summary, wait for user confirmation              │
├─────────────────────────────────────────────────────────────┤
│ 5. On approval: commit and mark task complete               │
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
    - Behavioral tests only (not shallow mocks)
    - Use existing test setup or skip tests
    - Exception: pure standalone functions can have unit tests

    ## Before You Begin
    If anything is unclear about the requirements or approach, ask now.

    ## Your Job
    1. Implement exactly what the task specifies
    2. Write behavioral tests if appropriate
    3. Verify implementation works
    4. Do NOT commit - report back for review

    ## Report Format
    Keep it short:
    - What you implemented (1-2 sentences)
    - Files changed
    - Only mention things that were unexpected or had to differ from design
```

### Design Alignment Reviewer (run in parallel with code quality)

```
Task tool (generalPurpose):
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

Design alignment: ✅ / ❌ <brief result>
Code quality: Ready / Needs fixes - <brief result>

<Any notes: unexpected things, deviations from design, unaddressed review feedback>

Ready to commit and continue to next task.
```

Keep summaries short - don't summarize changes (user sees them in Cursor).

**Wait for user response:**
- "Looks good, continue" / "Made adjustments, continue" / ok / etc → commit changes, mark task complete, proceed
- User provides feedback → address it, then present summary again


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
- Skip reviews (both design alignment AND code quality)
- Proceed with unfixed Critical/Important issues
- Commit without user approval
- Make subagent read the design doc file (paste relevant content)
- Write implementation details not in design (ask first)

**Always:**
- Run both reviews in parallel after implementation
- Wait for user confirmation before committing
- Keep summaries short
- Dispatch fix subagent for issues (don't fix manually - context pollution)
- keep your output on short and on point - we're not writing stories here we are communicate technicalities only
