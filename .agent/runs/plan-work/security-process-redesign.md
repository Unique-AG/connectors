# Plan: redo the security process of Unique-AG/connectors

Baseline: `security-process-redesign.baseline.txt` (same folder), captured on origin/main 95eb367c9.
Source of the target: Confluence "Vulnerability Patch Management Process" (grRBUQ). We follow that page. One deviation is listed below.
Revision 2 (2026-10-27): the owner settled the decisions D1 to D4.

## Stack

GitHub Actions (SHA-pinned actions), Trivy (`aquasecurity/trivy-action`), release-please, `dependency-review-action`, CodeQL (default setup plus a repository ruleset), Slack incoming webhook, Node `node --test` for script tests, Cursor Automations (daily patch run and the dependency-fix follow-up), `gh`.

## Budget (net added lines, estimate)

- CI/CD draft PR: about -1700. It deletes the #1295 gate (+2154 lines when it landed) and adds about 450: release gate (~80 YAML + ~60 script), nightly Slack report (~120 script + ~150 test), Cursor automation and skill (~100).
- Docs PR (#1047): about +60 net. It rewrites the files that already exist and adds one deviation section.

## Decisions (settled by the owner)

| # | Decision | What it changes in the plan |
|---|---|---|
| D1 | We remove the #1295 PR gate. This is the only deviation from the page. | The docs state it in a section named "DEVIATION from monorepo setup". Reason given: we are a smaller team that iterates faster. The Confluence page stays as it is. |
| D2 | The release gate matches the page. | Gate on fixable critical and high findings. A finding with no fix is shown and does not block. A package fix younger than 3 days does not count. Shipping with a fixable critical or high finding needs two approvals (engineering council, and the Chief Customer Officers or their delegates). |
| D3 | We own the scan of our published images. The monorepo scan of connectors will be removed. | Our nightly job is the only Slack poster for connectors images. Dominik removes the connectors entries from the monorepo scan. |
| D4 | A human approves the workflow runs on release PRs. When they approve, the gate runs on the state at that moment. | No GitHub App token is needed for the release gate. |

| D5 | Age of a fix, for the 3-day rule: the registry publish date of the fixed version if available. Otherwise the published date of the advisory. Otherwise unknown. | The gate reads PyPI (`urls[].upload_time_iso_8601`) or the npm registry (`time[<version>]`). For an OS package it uses the Trivy `PublishedDate` of the finding. For unknown age the gate counts the finding as blocking (my reading, to confirm). |
| D6 | Anyone can skip the gate on the release PR, with an "approve stamp", when a release must ship with a critical or high finding. | The skip is the `security-exception` label on the release PR. The stamp is a PR comment that names the approvers. The gate does not check who they are. |

**Second deviation to document (D6).** The page says shipping with a fixable critical or high finding takes two approvals: the engineering council, and the Chief Customer Officers or their delegates. D6 lets anyone with write access set the skip. The docs list it under "DEVIATION from monorepo setup", next to D1. To stay close to the page, the stamp comment must name one engineering-council approver and one CCO (or delegate).

## Done predicate (every line has a command)

| # | Predicate | Check |
|---|---|---|
| P1 | No PR-triggered workflow runs the image vulnerability gate. | `grep -rn container-image-vuln-gate .github/workflows` returns nothing, and a test PR shows no gate step. |
| P2 | The dependency review still blocks a PR that adds a vulnerable dependency. | Test PR with a known-bad version in a lockfile: `dependency-review` fails. |
| P3 | A release-please PR cannot merge while its image has a fixable critical or high finding that is older than 3 days. | After a human approves the runs, the check `release-gate` fails on #1290 (kb-mcp 0.1.8) while Pillow 12.3.0 is in its lock, and passes after the fix. |
| P4 | The scan of published images runs every night and posts a Slack report with image tag and CVE per image. | `grep cron security-trivy-registry.yaml` shows a daily schedule. A manual run posts to the test channel. `node --test` of the payload builder passes. |
| P5 | CodeQL blocks a PR that adds an alert. | `gh api repos/Unique-AG/connectors/rulesets` lists a ruleset that requires code scanning results for CodeQL on `main`. A seeded test PR is blocked. |
| P6 | A daily automation opens patch PRs from the nightly findings. | The automation file and the skill exist in the repository. A dry run lists the planned batches. |
| P7 | The docs match the CI/CD PR, the deviation is marked, and the two PRs link to each other. | Link and file-path check script passes. The docs contain "DEVIATION from monorepo setup". Both PR bodies contain the other PR URL. |
| P8 | A nightly job updates direct and indirect dependencies, one PR per dependency across all consumers, with labels. CI runs on it. A failure gets a fix attempt or a label for a human. | Defined after the research report. |

## Units (ordered, each lands alone)

Riskiest unknown first. Delete before add.

| Unit | Change | Check |
|---|---|---|
| U0 | Done: decisions D1 to D4. Ask Dominik to remove connectors from the monorepo scan (D3). | Written in both PR bodies. |
| U1 | Release gate: workflow on the release-please PRs. It builds the image fresh from the PR head, scans it, and fails on a fixable critical or high finding (D2). | P3 |
| U2 | Remove the #1295 gate from `_template-containerize.yaml`. Delete `container-image-vuln-gate` if U1 does not reuse it. Keep the no-push image build. | P1, P2 |
| U3 | Nightly scan of published images: change `security-trivy-registry.yaml` from weekly to nightly. Add a Slack report with the image tag and each CVE. Keep the SARIF upload. | P4 |
| U4 | CodeQL ruleset (human step, admin). | P5 |
| U5 | Daily patch automation and the `vulna-squash` skill, ported to `agentic/skills/` (the Cursor cloud run reads the file from the repository). | P6 |
| U6 | Nightly dependency update process and the failure follow-up. Separate PR(s) after the research choice. Proposed split, in order: | P8 |
| U6a | Prerequisite owned by another team: merge the UN-27873 stack (#1291 to #1294). It aligns all 14 uv locks and adds the drift report and `each-python-project.sh`. | `uv run poe drift` reports no drift on main. |
| U6b | pnpm: one `pnpm dedupe` PR, then `minimumReleaseAge: 4320` and `catalogMode: strict` in `pnpm-workspace.yaml`, and `pnpm dedupe --check` in CI. | `pnpm dedupe --check` exits 0 on main. |
| U6c | uv: `exclude-newer = "3 days"` in every project `pyproject.toml`. | `uv lock --check` passes in all 14 projects. |
| U6d | Workflow `deps-nightly.yaml` plus scripts and tests: one PR per dependency, same version everywhere, labels, GitHub App token. | A manual run opens one test PR whose title matches its diff and whose CI runs without approval. |
| U6e | Remove the `dependencies` skip from the `gatekeeper` job, so a red CI blocks the merge. | A test PR with the label and a failing check cannot merge. |
| U6f | `workflow_run` job that sets `deps-ci-failed`, a Cursor Automation on that label, and the fix skill. Limits: 3 open PRs, 2 fix attempts, then `deps-needs-human`. No merge by the agent. | A seeded failing PR gets one fix attempt, then the label. |
| U7 | Rewrite the docs in PR #1047, mark the deviation, and link both PRs. | P7 |

Order inside the CI/CD draft PR: U1, U2, U3, U5. U4 is a settings change, not a commit. U6 is its own PR. U7 lands last, because the docs must describe what is merged.

## Fan out

- Done: research round 1 (pnpm bots, uv bots, uv workspace).
- Running: research round 2 for U6 (pnpm with Turborepo, uv with one version everywhere, nightly orchestration and failure handling).
- Later: U1 and U3 touch different files and can be written in parallel. U1 and U2 are sequential. U7 waits for the rest.

## Not in scope here

Any change to the uv layout. The assessment says do it later.
