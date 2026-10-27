<!-- confluence-page-id: <NO CONFLUENCE ID REQUEST> -->
<!-- confluence-space-key: <NO CONFLUENCE ID REQUEST> -->

# Dependencies

A nightly job updates our dependencies, direct and indirect. It opens one PR for each dependency. The PR changes that dependency in every project that uses it, so one dependency has one version everywhere. For the whole process, read [SECURITY-PROCESS.md](../../SECURITY-PROCESS.md).

## The nightly update

```mermaid
flowchart TD
  nightly[Nightly job] --> pr[One PR for each dependency]
  pr --> ci[Full CI]
  ci -->|green| review[A person reviews and merges]
  ci -->|red| failed[Label deps-ci-failed]
  failed --> agent[Fix agent pushes a fix]
  agent -->|CI green| review
  agent -->|second attempt fails| human[Label deps-needs-human]
```

| Rule | Value |
|---|---|
| Scope | Direct and indirect dependencies, in pnpm (Node) and uv (Python) |
| One PR for | One dependency, or one group that must move together, for example `opentelemetry-*` |
| Cooldown | A version younger than 3 days waits. The job passes `--config.minimumReleaseAge=4320` to pnpm and `--exclude-newer "3 days"` to uv. |
| Labels | `dependencies`, and `npm` or `uv` |
| CI | The full CI runs on every PR. A red CI blocks the merge. |
| Cap | At most 5 new PRs each night |
| Merge | A person merges. The agent never merges. |

## If CI is red

The job adds the label `deps-ci-failed`. A Cursor Automation then starts the fix agent. The agent pushes a fix to the PR branch and tries at most 2 times. After that, it adds `deps-needs-human` and a comment.

The agent edits only the paths in the PR. It never edits a lockfile by hand. The skill `dependency-pr-review` is the base for the review.

## Each day

1. Run `gh pr list --label dependencies --state open`.
2. If a PR has a green CI, review it and merge it.
3. If a PR has the label `deps-needs-human`, fix it or close it.
4. Every month, read each pin and override. Remove the entry when upstream fixes the problem.

Pins are `override-dependencies` in `pyproject.toml` and `pnpm.overrides` in the root `package.json`. A pin holds a dependency at one version, so the nightly job cannot move it.

## Dependency review

The dependency review runs on a PR that changes a lockfile or a manifest. It fails for a known HIGH advisory or worse. It checks only what the PR adds.

If the dependency review blocks your PR, raise the version of the dependency you added. If a parent pins it exactly, add a pnpm override. If you cannot take the fix, add the label `security-exception`.

The policy needs written approval from the engineering council for a new dependency with a known critical or high vulnerability.

## Not covered by the nightly job

The nightly job updates npm and Python. No bot updates GitHub Actions, Docker base images, or Terraform. A person updates them.

- **GitHub Actions:** raise the pinned commit and keep the version comment. The pinned-actions check keeps the pins valid.
- **Docker base images:** raise the digest in the Dockerfile. The change starts a release for that service.
- **Terraform:** raise the provider or module version in the service folder.

| File | What it holds |
|---|---|
| `.github/workflows/deps-nightly.yaml` | The nightly job |
| `.github/workflows/deps-ci-label.yaml` | The job that sets `deps-ci-failed` |
| `agentic/skills/deps-ci-fix/SKILL.md` | The skill that fixes a red dependency PR |
| `.github/workflows/security-dependency-review.yaml` | The dependency review |
| `agentic/skills/dependency-pr-review/SKILL.md` | The skill that reviews a dependency PR |
