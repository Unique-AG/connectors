---
name: review
description: Review implementation against design for alignment and quality gaps.
disable-model-invocation: true
---

# Review Implementation Against Design

## Overview

Comprehensive review of a completed implementation against its original design document. This is a separate session from implementation to get fresh perspective.

**Input required:** Design doc path (e.g., `@docs/plans/YYYY-MM-DD-<topic>-design.md`)

## Before Starting

1. Read the design doc completely
2. Read `CLAUDE.md` and `AGENTS.md` for coding standards
3. Identify the feature branch and get the diff from base branch:

```bash
git log --oneline main..HEAD  # or master
git diff main..HEAD --stat
```

## The Review Process

### Phase 1: Design Alignment Review

Compare implementation against each section of the design doc:

**For each design section, check:**

| Section | Verify |
|---------|--------|
| Problem | Does the implementation solve the stated problem? |
| Solution Overview | Does the approach match what was designed? |
| Architecture | Are components structured as specified? |
| Error Handling | Are errors handled as designed? |
| Testing Strategy | Do tests follow the strategy (behavioral, not mocks)? |
| Out of Scope | Was anything built that was explicitly out of scope? |

**For each task in the design:**
- Was it implemented?
- Does implementation match the task description?
- Any deviations?

### Phase 2: Code Quality Review

Review the actual code changes:

**Check for:**
- Code clarity and readability
- Proper error handling
- Test quality (behavioral tests, not shallow mocks)
- Follows existing patterns in codebase
- No obvious bugs or security issues
- Follows CLAUDE.md and AGENTS.md standards

### Phase 3: Gap Analysis

Identify:
- **Missing:** What was in design but not implemented?
- **Extra:** What was implemented but not in design?
- **Different:** What was implemented differently than designed?

## Report Format

Present findings in this structure:

```markdown
# Implementation Review: <topic>

## Summary
<1-2 sentences: overall assessment>

## Design Alignment

### ✅ Implemented as Designed
- <item>
- <item>

### ⚠️ Deviations
- <item>: <what differs and why it matters>

### ❌ Missing
- <item>: <what was expected>

### ➕ Extra (not in design)
- <item>: <what was added>

## Code Quality

### Strengths
- <item>

### Issues

**Critical** (must fix):
- <issue with file:line>

**Important** (should fix):
- <issue with file:line>

**Minor** (nice to have):
- <issue with file:line>

## Test Coverage
- <assessment of test quality>
- <any gaps in behavioral testing>

## Recommendations
1. <actionable recommendation>
2. <actionable recommendation>

## Verdict
- [ ] Ready to ship
- [ ] Needs minor fixes (list above)
- [ ] Needs significant work (list above)
```

## After Review

Based on findings:

**If ready to ship:**
```
Review complete. Implementation looks good.

To push and create PR:
/ship @docs/pr-proposals/YYYY-MM-DD-<topic>.md
```

**If needs fixes:**
```
Review complete. Found issues that should be addressed:
<summary of Critical/Important issues>

Fix these issues, then either:
- Run /review again for fresh review
- Or proceed to /ship if you've addressed the feedback
```

## Key Principles

- **Fresh perspective** - This is a new session, review everything from scratch
- **Design is the contract** - Implementation should match the design
- **Be specific** - Include file:line references for issues
- **Actionable feedback** - Every issue should have a clear fix path
- **Severity matters** - Distinguish Critical/Important/Minor
