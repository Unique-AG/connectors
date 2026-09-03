# Dependency updates

How this repository updates its dependencies, and how that satisfies the Unique base-image standard
("Central Docker base images", Confluence space Q).

This repository does **not** consume `uniqueapp.azurecr.io/base/*`. That registry refuses anonymous
pull, and this repository is public and source-disclosed, so a private base in a `FROM` line would
make it unbuildable outside Unique. The standard's *rules* still apply, and the table below maps
each one to the control that satisfies it here.

## The weekly cycle

| When | What happens | Where |
|---|---|---|
| Friday 06:00 Berlin | Dependabot opens the grouped update pull requests | `.github/dependabot.yaml` |
| Within a few minutes | They are converted to draft | `dependency-updates.yaml` |
| Friday to Monday | The pins age. Nothing changes them | `rebase-strategy: disabled` |
| Monday | A maintainer marks each held pull request ready for review, then the team reviews and merges | people |

Draft is a server-side merge block. Nobody can merge a held pull request early, and auto-merge
cannot be armed on one — verified across every open pull request: `viewerCanEnableAutoMerge` is
false on all six drafts and true on all nine non-drafts, with `mergeStateStatus` mixed within both
groups. Nothing lifts that block on a schedule. A person does, by hand, on Monday.

Dependabot cannot open a draft, so it opens ready for review and the CODEOWNERS request fires at
the Friday open. Converting to draft does not withdraw it, and marking a pull request ready a second
time sends no new request — pull request #164 shows four `review_requested` events on the first
ready, none on the second. The Monday click lifts the merge block. It is not the review request.

The daily runs re-freeze a pin that moved. Dependabot force-pushes released pull requests often
enough to matter, and a force push resets the pin to zero age with the merge block already lifted.

## What rides, and what does not

Routing is the Dependabot group identifier, which appears in the branch name.

| Group | Branch contains | Held? |
|---|---|---|
| `minor-and-patch` | `minor-and-patch` | yes, three days |
| `major` | `major` | no — opens ready for review |
| `python-runtime` | `python-runtime` | no — opens ready for review |
| security updates | the dependency name | no — never grouped, never held |

Security updates are never held. Holding a published, exploitable fix until Monday is worse than
merging it on the day it arrives. This is an allowlist, so the failure direction is "a weekly pull
request was not frozen", never "a critical fix was silently held".

## Design notes

**The clock is the head commit, not `createdAt`.** A rebase, an `@dependabot recreate`, or a
conflict refresh replaces the pinned digest and leaves `createdAt` untouched. Ageing the ticket
instead of the artifact would merge a zero-age pin while recording three days. Because a ready pull
request whose head commit is younger than the window is pushed back to draft, a rebase re-freezes
it and restarts its clock. The standard documents this hole and accepts it. This closes it.

**One reconciler, not a Friday job and a Monday job.** Two scheduled jobs have four failure modes
that each need their own handling: a dropped Friday run, a dropped Monday run, a holiday Monday and
a holiday Friday. A convergent reconciler absorbs all four as latency. It also avoids the token
problem: a workflow triggered by a Dependabot pull request gets a read-only token, and
`pull_request_target` is read-only with no secrets when the pull request was opened by Dependabot.
A `schedule` run is not Dependabot-initiated and has neither restriction.

**The state machine is derived, not recorded.** Every decision comes from `(draft, aged)`. No label
holds state, so the workflow cannot disagree with itself, and a human who flips draft state by hand
is simply converged back on the next run.

**The hold converts a pull request as soon as it sees it, without waiting for checks.** An earlier
version waited up to an hour for the check rollup to settle, on the theory that a third-party review
app abandoning an in-flight run would leave a check stuck for merge-gatekeeper. That wait was
removed: no workflow in `.github/workflows` triggers on `draft`, `ready_for_review` or
`converted_to_draft`, so converting a pull request to draft cancels nothing, and the wait only
widened the window in which a fresh pin was mergeable. The rollup is still queried and still shown
in the step summary, because it is what a maintainer wants to see before releasing a hold, but no
decision reads it.

**`cancel-in-progress: false` on the pin check is deliberate.** merge-gatekeeper de-duplicates check
runs by name and the check-runs API ordering is unspecified, so a cancelled run and a successful run
under one name can resolve to the cancelled one and hard-fail the gate.

**The hold workflow's token scopes are all load-bearing.** `contents: write` is not provisional:
under `GITHUB_TOKEN`, `convertPullRequestToDraft` and `markPullRequestReadyForReview` both answer
`Resource not accessible by integration` while `contents` is `read`, and both succeed when it is
`write` (cli/cli#8910, reproduced February 2026, still open). `pull-requests: write` alone is not
enough, so a run will not prove `contents: write` unnecessary — it will fail.

`checks: read` and `statuses: read` are what make the rollup column real. `statusCheckRollup` is a
union over `CheckRun` and `StatusContext`, owned by those two permissions, and a token holding
neither is refused the whole `commit.statusCheckRollup` node. GitHub answers 200 with the node
nulled and a `FORBIDDEN` entry in `errors`, and `gh` turns any `errors` entry into a non-zero exit.
So the reconciler fails outright rather than silently showing every pull request as `NONE`. `gatekeeper.yaml` grants the same pair for the same reason. `actions: read` is not
needed: it covers `checkSuite.workflowRun`, which this query never selects.

## Mapping to the standard

| Standard rule | Control here |
|---|---|
| Major and minor move by hand. Patch and digest updates flow as pull requests | The `major` and `python-runtime` groups are never held. They open ready for review |
| node and nginx minors are the exception. python is excluded | Applied literally. We have no nginx. `node:X.Y.Z` minors ride; `python` and `uv` minors do not |
| No tooled age cooldown | `cooldown` removed from the docker entry. Dependabot reads a Docker release date from `Last-Modified` on the manifest HEAD, which neither registry returns, so it fails open |
| The cooldown is a manual merge policy, with the pin frozen | This is the cycle above. `rebase-strategy: disabled` is the freeze, draft state is the enforcement |
| A rebase resets the age (accepted hole) | Closed. See the design notes |
| Automerge off. A human approves every base pull request | No automerge. The workflow has no `checks: write`, never submits a review, and never lifts the merge block — only a person does |
| Every external `FROM` is digest-pinned | True for all 11 Dockerfiles today. **Not asserted by CI** — see the open items |
| Images are cosign-signed | Satisfied and exceeded. `_template-cd.yaml` signs **and** verifies, with SBOM and provenance |
| Two tag classes: rolling and immutable | Not applicable as written — we consume bases, we do not publish them. See the open items |
| Hardening and patch ownership | **Partial.** The Python Dockerfiles build and run on one interpreter, so the coupled-pin class is unrepresentable rather than checked. There is no image scanner. See the open items |

## Open items

These are accepted risks, not satisfied controls. Do not describe them as satisfied.

1. **No image scanning.** Nothing in `.github/workflows` runs Trivy, grype, or any SBOM scan.
   Measured on 2026-09-01 with Trivy at `CRITICAL,HIGH --ignore-unfixed`: `teams-mcp:0.4.5` carries
   108 findings, `outlook-semantic-mcp:3.4.1` carries 80, `office-365-mcp:0.1.0` carries 30. A
   gating scan would block every release on day one, so start report-only.
2. **No admission verification of signatures.** The standard's integrity model assumes a cluster
   rejects unsigned images. That is cluster-side and outside this repository.
3. **The deploy hop is unowned.** This process ends at "image published and signed". Moving
   `x-<service>-version` and syncing ArgoCD is a separate piece of work.
4. **`kyckr-mcp` and `temenos-mcp` ship by hand.** Both have a `deploy/deploy.sh` and no Helm
   chart, so their dependency updates cannot become a signed image. Wiring them to the release path
   is separate, tracked work.
5. **Nothing asserts that every external `FROM` carries a digest.** It is true for all 11
   Dockerfiles today and no gate keeps it true. A mutable tag would build and deploy normally.

## Operating it

The repository variable `DEPENDENCY_UPDATES` is both the arming switch and the kill switch. The
workflow runs in report mode until it is set to `on`, and returns to report mode if it is set to
anything else. Every run writes its full decision table to the job step summary.

To check the hold without waiting for a cron, run the workflow manually with `mode: report`.

**Releasing the hold.** Every Monday, open the held pull requests — the `held now` link in each run's
step summary, or `is:pr is:open is:draft author:app/dependabot` — click **Ready for review** on each,
then review and merge. Nothing else releases them. Wait until the pins are past 72h or the next run
puts them back to draft. A held pull request still in draft at 120h raises the `dependency-updates`
issue: that is the missed-Monday alarm, and it is the only one.

There is no supported API to trigger Dependabot itself. The only manual triggers are the
**Check for updates** button under Insights → Dependency graph → Dependabot, which is one click per
manifest row, and the `@dependabot rebase` / `@dependabot recreate` pull request comments. The
`@dependabot merge`, `close` and `reopen` commands were retired on 2026-01-27 and no longer work.
