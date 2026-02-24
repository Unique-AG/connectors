---
name: ship
description: Push a feature branch and create a PR from the proposal file.
disable-model-invocation: true
---

# Ship: Push and Create PR

## Overview

Push the feature branch and create a Pull Request using the PR proposal file created during brainstorming.

**Input required:** PR proposal file path (e.g., `@docs/pr-proposals/YYYY-MM-DD-<topic>.md`)

## Before Starting

1. Read the PR proposal file
2. Verify we're on the correct feature branch
3. Check branch status:

```bash
git status
git log --oneline main..HEAD  # see commits to be included
```

## Staging Rules

When committing changes for a PR, **never include** files from `docs/**` (design docs, PR proposals, plans). These are local working files and must not be part of any PR commit.

Before committing, review staged files and **exclude**:
- `docs/plans/**`
- `docs/pr-proposals/**`
- Any other `docs/**/*.md` files

If docs files are already committed on the branch (e.g., from a brainstorm step), remove them before pushing by rebasing out the docs commit or using `git reset` + recommit without those files.

## Pre-flight Checks

Run these checks before pushing:

```bash
# 1. All changes committed?
git status  # should be clean

# 2. Tests pass?
pnpm test --filter=@unique-ag/<affected-package>

# 3. Types check?
pnpm check-types

# 4. Style passes?
pnpm style
```

**If any check fails:** Stop and report the issue. Don't push broken code.

## The Process

### Step 1: Push Branch

```bash
git push -u origin HEAD
```

### Step 2: Create PR

Read title and description from the PR proposal file, then:

```bash
gh pr create --title "<title from proposal>" --body "$(cat <<'EOF'
<description from proposal>
EOF
)"
```

**PR title format** (from CLAUDE.md):
```
<type>(<scope>): <description>
```

**PR body format:**
```markdown
<summary from proposal>

- <bullet points from proposal>
```

### Step 3: Report Success

```
PR created successfully!

<PR URL>

Title: <title>

Next steps:
- Wait for CI checks
- Request review if needed
- Address any feedback
```

## If PR Proposal Needs Updates

If during implementation or review the scope changed significantly:

1. Note what changed
2. Update the PR proposal file before creating PR
3. Commit the updated proposal
4. Then proceed with push and PR creation

## Error Handling

**If push fails (branch exists):**
- Report the failure to user
- Continue only once receiving further instructions on how to proceed

**If PR creation fails:**
- Check if PR already exists: `gh pr list --head <branch>`
- Check gh auth: `gh auth status`

**If CI fails after PR:**
- Report the failure to user
- Don't try to fix automatically (that's a new task)

## Red Flags

**Never:**
- Push with failing tests
- Push with type errors
- Push with style violations
- Force push to any branches
- Create PR without reading the proposal file
- Include `docs/**` files (plans, proposals) in PR commits

**Always:**
- Run pre-flight checks
- Use the PR proposal content
- Report the PR URL when done
