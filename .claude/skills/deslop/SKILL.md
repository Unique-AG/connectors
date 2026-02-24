---
name: deslop
description: Reduce noisy AI-ish diffs to minimal behavior-preserving patches.
disable-model-invocation: true
---

# /deslop — Remove AI code slop

Reduce noisy or AI-ish changes into the smallest, clean, behavior-preserving patch for the SharePoint connector service.

**What it does:**

**Check the diff against main and remove AI-generated slop:**
- Extra comments or commentary a human wouldn't add, or that are inconsistent with the file
- Abnormal defensive checks or try/catch blocks that don't match local patterns
- Type escapes (e.g., casts to any) added to bypass type errors
- Other inconsistent style or drive-by edits unrelated to the intended change

**Simplify without changing behavior:**
- Tighten naming, extract small pure helpers only when it reduces duplication/complexity
- Remove dead code, unused imports, and redundant branches

**Protect correctness and scope:**
- Preserve public APIs and external contracts
- Keep actual intended changes; do not add features or speculative abstractions

**Produce a review-friendly output:**
- Provide a minimal diff
- End with a 1–3 sentence summary of what changed
- If any change risks behavior, list questions first and proceed conservatively

**When to use:**

- After making a large or messy edit before opening a PR
- When a diff includes unrelated churn or AI artifacts
- Prior to splitting work into small, reviewable commits
- After running /check-all to ensure cleanup doesn't reintroduce lint/type issues

**Recommended workflow:**

1. Run /deslop on the current diff or selection
2. Apply the minimal patch and commit with the suggested messages
3. Run /check-all and your test command to confirm behavior remains intact

**Note:** Strictly behavior-preserving. Flag any potential breaking or behavior-altering changes before proceeding.