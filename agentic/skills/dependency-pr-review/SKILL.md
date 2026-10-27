---
name: dependency-pr-review
description: Use when asked to review, check, or assess a dependency update PR, a version bump, a major bump, or a breaking change, or when asked if a bump is safe to merge. Trigger words are "dependency PR", "bump", "major version", "breaking change", "deps-needs-human", "safe to merge".
metadata:
  internal: true
---

# Dependency PR review

Answer one question: **does this version bump break our code?**
Start from how we use the dependency. Do not start from the changelog.

The user gives one PR at a time. Review only that PR. Do not edit repo files, comment on the PR, approve, or merge.

## Modes

| The user says | Do |
|---|---|
| Only a PR link | Full review: steps 1 to 6. |
| "Code wise only, tests ran in CI" | Skip the scratch run (step 4, lens C). Read CI as evidence. |

## Step 1: Facts about the PR (do this yourself, no agent)

```bash
gh pr view <n> --repo Unique-AG/connectors --json title,headRefName,files,body
gh pr checks <n> --repo Unique-AG/connectors
```

- Read the changed files. Name the ecosystem and the services that use the dependency.
  - `uv.lock` and `pyproject.toml`: Python service, driven by `uv`.
  - `pnpm-lock.yaml` and `pnpm-workspace.yaml`: Node. A `catalog:` entry changes the version for every package that uses it.
- Read the release notes in the PR body. Read **every release between the two versions**, not only the last one. A middle release can carry the real change.
- Decide: direct or transitive dependency? Run `grep -n 'name = "<pkg>"' uv.lock` for Python. List which packages require it.
- Grep our code for the dependency. Quote the globs in zsh: `--include='*.ts'`.
  - Exclude `node_modules`, `dist` and `.venv`.
  - For a transitive dependency, grep for the direct dependency that pulls it in.

## Step 2: Read CI before you trust it

- Only the newest run per check counts. Older runs show `cancelled` when a push replaced them.
- `gatekeeper` can fail by timeout while 0 jobs failed. The log says `context deadline exceeded` and `Completed job count`. Report it as a timeout. Recommend a re-run.
- `skipping` means the job did not apply to this change. Name which test jobs did not run. A shared package with its own test job (for example `mcp-credential-auth`) can be skipped while services still use its code. Report that gap.
- Check if the tests prove the changed behavior:
  - `vi.mock` or `unittest.mock` on the dependency means CI does not call the real library.
  - `overrideGuard` or a stubbed client means CI does not exercise the real path.
  - State this in the report. Suggest one concrete manual check, for example one real request in QA.

## Step 3: Fan out agents (read-only, in parallel, one message)

Use `subagent_type: general-purpose` and `model: sonnet`. Run in the background.
Put these in every brief:

- The repo path and the rule: do not edit repo files.
- The scratch path for temporary files (the session scratchpad directory).
- The facts from steps 1 and 2. Do not hand over a conclusion.
- The output format: a verdict, a table of change, used or not, and evidence with `file:line`, and what was **not** verified.

Pick the lenses that fit the PR. Three cover most PRs.

### Lens A: runtime reachability

- Build the dependency chain from the root package to the dependency, with `file:line` in the lockfile.
- Decide: runtime or dev group only?
  - Python: read `deploy/Dockerfile`. `uv sync --frozen --no-dev` removes the dev group.
  - Node: `pnpm deploy` ships devDependencies in this repo, so a dev dependency can still reach the image. Check the Dockerfile.
- Grep for configuration that the change could touch (proxy variables, driver names, pool settings).

### Lens B: changes against our usage

- Read all of our usage first. List the APIs we call.
- Fetch the official changelog and migration notes for every release in the range. Use `gh release view`, `gh api`, or the docs site.
- Produce a table: each breaking, deprecated, or behavior change, then used or not, then evidence.
- Show the riskiest API as a snippet pair: our call and the changed behavior.
- Check each neighbor package that depends on the same library. Does its declared bound allow the new version? Use PyPI JSON `requires_dist` or `npm view`.
- Check the runtime floor (Python, Node) and the Docker base image.

### Lens C: real run (skip in "code wise only" mode)

- Copy the service and its local path dependencies into the scratchpad. Never edit the repo.
- Apply the PR lockfile change to the copy only: `gh pr diff <n> > pr.diff`, then `git apply`.
- Run the checks the service documents: tests, lint, type check. Add a warnings-as-errors pass filtered to the dependency.
- Run a control on the old version. A failure that also appears on the old version is not caused by the bump.
- Tools: `uv` and `node` come from the flake. If a command is missing, use `nix develop -c <cmd>`. Do not install anything globally and do not run `direnv allow`.
- Tests that need Postgres use testcontainers. Check `docker ps` first. Say what could not run.

## Step 4: Verify the agent claims you will repeat

An agent report is a claim, not a fact. Before you write the verdict:

- Re-check any claim that decides the verdict (for example, "the body limit does not apply because we pass a parsed body"). Open the cited `file:line` yourself.
- If two agents disagree, find the cause. Do not average them.
- Delete any claim that you cannot trace to a file, a log line, or a release note.

## Step 5: Write the report

Load the `simple-english` skill. Write in pragmatic mode. Procedural text has 20 words per sentence at most. Descriptive text has 25.

Use this shape. Keep it to about one page.

```markdown
# PR <n>: <package> <old> to <new> (<services>)

## Verdict: <safe to merge | safe with a gap | do not merge>. <one sentence why>

## What changes
## How we use it            (short, with file:line)
## Changes that could affect us   (table: change | effect on us)
## The one change worth checking  (snippet pair: ours vs changed behavior)
## What CI shows            (checks, counts, gatekeeper state)
## What we did not prove    (mocked tests, skipped jobs, no live call)
```

Rules for the report:

- The verdict comes first.
- Every row in the table has evidence or says "not used" plus the grep that proved it.
- Include one code snippet. It shows our real usage next to the changed API.
- Add a "Gap" or "Limit of the evidence" section when it applies. Give one concrete command or manual check that closes it.
- Do not write "should". Write "must", or state the fact.
- Mention a newer release if one exists and the nightly dependency job has not proposed it yet.
- Say plainly what you did not run. Do not claim a result you did not see.

## Step 6: Stop

Give the report in chat. Do not publish it as a file or comment unless the user asks.
Wait for the next PR link.

## Verdict guide

| Evidence | Verdict |
|---|---|
| Breaking change exists and we use the API | Do not merge. Name the change and the fix. |
| Breaking change exists and we do not use the API, and CI is green | Safe to merge. |
| No breaking change, but tests are mocked or a test job is skipped | Safe with a gap. Give the check that closes it. |
| CI failed for a reason that the bump caused | Do not merge. Show the log line. |
| CI failed only by timeout or cancel | Not a code verdict. Recommend a re-run. |
