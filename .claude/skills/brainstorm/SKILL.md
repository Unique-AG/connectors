---
name: brainstorm
description: Turn ideas into design docs and PR proposals through guided questioning.
disable-model-invocation: true
---

# Brainstorming Ideas Into Designs

## Overview

Turn ideas into fully formed designs through collaborative dialogue. This command produces:
1. A design document at `docs/plans/YYYY-MM-DD-<topic>-design.md`
2. A PR proposal at `docs/pr-proposals/YYYY-MM-DD-<topic>.md`

**Do NOT start implementation in this session.** After design is complete, tell the user to start a new session with `/implement`.

## Tool Reference: AskQuestion

Use the AskQuestion tool for all multiple-choice interactions. Always include an "Other" option for open-ended responses.

```
AskQuestion:
  title: "<context title>"
  questions:
    - id: "<unique-id>"
      prompt: "<your question>"
      options:
        - id: "<option-id>"
          label: "<option label>"
        - id: "other"
          label: "Other (I'll explain)"
```

Use regular text messages only when questions are truly open-ended and don't fit a multiple choice format.

## The Process

### Phase 1: Understanding the Idea

**Capture initial context:**
- Check current project state (files, docs, recent commits)
- Note ticket reference if provided (e.g., UN-12345) for inclusion in outputs

**Then ask questions one at a time:**
- Use AskQuestion for exploratory questions
- Focus on: purpose, constraints, success criteria, edge cases
- Only one question per message - if a topic needs more exploration, break it into multiple questions

**Example:** `{id: "scope", prompt: "What's the primary goal?", options: [{id: "new-feature", label: "New feature"}, {id: "refactor", label: "Refactor existing"}, ...]}`

### Phase 2: Exploring Approaches

1. **First, write out the approaches as visible text** - Present 2-3 different approaches with their trade-offs. This MUST be actual text output the user can read, not just internal reasoning.
2. Lead with your recommended option and explain why
3. **Only after presenting all approaches in text**, use AskQuestion to let user choose

**Important:** The AskQuestion options will only show short labels. The user needs to see the full explanation of each approach BEFORE you ask them to choose. Never reference "Option A" or trade-offs in a question without first explaining them in visible text.

**Example flow:**
```
[Text message explaining approaches]
Option A: In-memory cache
- Pro: Simple, no external dependencies
- Con: Lost on restart

Option B: Redis cache (recommended)
- Pro: Persists across restarts, shared between instances
- Con: Additional infrastructure

[Then AskQuestion]
{id: "approach", prompt: "Which approach?", options: [{id: "a", label: "In-memory cache"}, {id: "b", label: "Redis cache (recommended)"}, {id: "other", label: "Different approach"}]}
```

### Phase 3: Presenting the Design

Once you understand what we're building:

1. Present the design in sections of 200-300 words
2. After each section, use AskQuestion to validate
3. Cover: architecture, components, data flow, error handling, testing strategy
4. Be ready to go back and clarify if something doesn't make sense

**Example:** `{id: "validate-arch", prompt: "Does this architecture look right?", options: [{id: "yes", label: "Looks good, continue"}, {id: "tweak", label: "Minor tweaks (I'll explain)"}, {id: "rethink", label: "Let's rethink this"}]}`

**Design sections to cover:**
- Problem statement
- Solution overview
- Architecture and components
- Error handling approach
- Testing strategy (behavioral tests, existing setup or skip)
- Out of scope (YAGNI - be ruthless)

### Phase 4: Task Outlines

After the design is validated, add task outlines:

- Each task: **title** + 1-3 sentences of description
- Tasks should stem naturally from the design
- No implementation details - just what needs to be done
- Order tasks by dependency (what must come first)

### Phase 5: PR Proposal

Create a PR proposal file with:
- Suggested PR title (conventional commits format per CLAUDE.md)
- Brief description (2-5 bullet points)

## Output Files

### Design Doc: `docs/plans/YYYY-MM-DD-<topic>-design.md`

```markdown
# Design: <topic>

**Ticket:** <ticket-key> (if provided, otherwise omit this line)

## Problem
What we're solving and why.

## Solution

### Overview
High-level approach in 2-3 paragraphs.

### Architecture
Components, data flow, interactions.

### Error Handling
How failures are managed.

### Testing Strategy
What kinds of tests. Focus on behavioral tests.
Note: Use existing test setup or skip tests. Exception: pure standalone functions.

## Out of Scope
What we're explicitly not doing.

## Tasks

1. **<Task title>** - <1-3 sentences describing what needs to be done>
2. **<Task title>** - <1-3 sentences>
...
```

### PR Proposal: `docs/pr-proposals/YYYY-MM-DD-<topic>.md`

```markdown
# PR Proposal

## Ticket
<ticket-key> (if provided, otherwise omit this section)

## Title
<type>(<scope>): <description>

## Description
- <bullet point 1>
- <bullet point 2>
- <bullet point 3>
```

## After Completion

Tell the user:

```
Design complete! Files created:
- docs/plans/YYYY-MM-DD-<topic>-design.md
- docs/pr-proposals/YYYY-MM-DD-<topic>.md

To implement, start a new session and run:
/implement @docs/plans/YYYY-MM-DD-<topic>-design.md
```

**Do NOT commit.** The design doc and PR proposal will be committed by the `/implement` command after creating a feature branch.

## Key Principles

- **One question at a time** - Don't overwhelm
- **Use AskQuestion tool** - Multiple choice via Cursor UI, always include "Other" option
- **YAGNI ruthlessly** - Remove unnecessary features
- **Explore alternatives** - Always propose 2-3 approaches
- **Incremental validation** - Present design in sections, validate each
- **Design-first** - Tasks are secondary, stemming from the design
- **No implementation** - This session is for design only
