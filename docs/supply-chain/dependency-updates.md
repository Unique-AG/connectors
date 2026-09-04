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
| Friday to Monday | The pins do not move, as long as the pull request is merged before the next Friday | `rebase-strategy: disabled` |
| Monday | The team reviews and merges them | people |

There is no automated gate. The three days are a merge policy the team follows, which is what the
standard asks for. Two mechanisms make it real, and both live in `.github/dependabot.yaml`.

`cooldown: default-days: 3` stops Dependabot offering a version until it has been public three days.
Dependabot applies that same three days **by default, even when the key is absent**, so every
ecosystem gets it and the explicit setting only makes it visible. In the ordinary case a pin is
already three days old when the pull request opens, before anyone waits at all.

`rebase-strategy: disabled` stops Dependabot rebasing an open pull request when the base branch
moves. It does **not** stop Dependabot force-pushing a newer version of the dependency into that
same pull request on its next scheduled run. Read the two apart, because the difference decides
whether the three days are real.

Within one cycle the pin is stable: a pull request opened Friday and merged Monday sees no Dependabot
run in between, so the pin merged is the pin opened. Survive to the next Friday and it is not. Pull
request #788 opened 2026-08-14, was force-pushed 2026-08-21 at 04:11:40Z — Dependabot's own Friday
run — and merged 2026-08-26. Six of the last thirty Dependabot pull requests have a head commit
later than `createdAt`, by three to twenty-one days.

The failure direction is the dangerous one. `createdAt` still reads the original Friday, so a pin
pushed in this morning looks a week old. That is why "clear it before the next Friday" below is a
correctness rule, not tidiness.

Docker is the one to watch, because the standard is about base images and its cooldown is the least
certain. GitHub lists docker as supporting `default-days`, and the three-day default applies whether
or not the key is set — so omitting it, as this configuration does, changes nothing either way.

What is not established is whether that cooldown ever **binds** for these images. Dependabot needs a
release date. `Last-Modified` is absent from a `ghcr.io` manifest HEAD — checked directly with a
pull token — and that is the header the omission was originally justified against. A date does exist
one level down, in the OCI image config blob: `ghcr.io/astral-sh/uv:0.11.33` reports
`created = 2026-07-28T09:39:24Z`, reachable in four requests. Nothing documents whether Dependabot
reads it, and it cannot be observed from outside.

So treat docker's cooldown as unverified rather than absent, and do not lean on it. If you want
certainty for docker, the `created` field makes a custom check cheap — see the open items.

## What rides, and what does not

Routing is the Dependabot group identifier, which appears in the branch name.

| Group | Branch contains | Merge policy |
|---|---|---|
| `minor-and-patch` | `minor-and-patch` | wait three days, then merge on Monday |
| `major` | `major` | separate review. It may need code changes |
| `python-runtime` | `python-runtime` | separate review. It moves the interpreter |
| security updates | the dependency name | merge on the day it arrives |

Security updates do not wait. Holding a published, exploitable fix until Monday is worse than merging
it the day it arrives. They are also never grouped, so they never carry `minor-and-patch` in the
branch name.

## Design notes

**The age that matters is the head commit, not `createdAt`.** The standard documents a hole — a
rebase resets the pin age while the ticket keeps its original date — and accepts it. This repository
does not close it. `rebase-strategy: disabled` narrows it to one cycle, and nothing checks the
remainder. The deleted gate read `commits(last:1).committedDate` and was the only thing in the
repository that ever looked at the real pin date; the Monday routine replaces that with a command
the operator has to run.

Dependabot also supersedes and replaces an unmerged group pull request on the next Friday run (#746
to #754 to #788 to #865), and the review threads go with it. Same deadline, second reason.

**There is no gate workflow, on purpose.** An earlier version of this change added one: it converted
fresh Dependabot pull requests to draft and let a maintainer release them on Monday. It was deleted
before it ever ran. Dependabot cannot open a pull request as a draft, so a gate can only ever race to
convert one that is already mergeable, and the race is bounded by a cron. That made the hold
enforced against accident but advisory against anyone with write access — while costing a scheduled
workflow, a repository variable, a state machine and a weekly alarm. The standard asks for a manual
merge policy. This is one, written down, with the pin freeze done mechanically.

## Mapping to the standard

| Standard rule | Control here |
|---|---|
| Major and minor move by hand. Patch and digest updates flow as pull requests | `major` and `python-runtime` are their own groups and get their own review. Everything else rides the weekly pull request |
| node and nginx minors are the exception. python is excluded | Applied literally. We have no nginx. `node:X.Y.Z` minors ride; `python` and `uv` minors do not |
| No tooled age cooldown | Read the other way here. `cooldown: 3` is stated explicitly, and Dependabot applies the same three days by default even where the key is absent. Whether it binds for docker images is unverified — see the open items |
| The cooldown is a manual merge policy, with the pin frozen | This is the cycle above. `rebase-strategy: disabled` is the freeze. The three days are the merge policy, and nothing enforces them — see the open items |
| A rebase resets the age (accepted hole) | **Open, narrowed.** `rebase-strategy: disabled` holds the pin for one Friday-to-Monday cycle. A pull request that survives to the next Friday is force-pushed to a newer pin while `createdAt` stays put — see the open items |
| Automerge off. A human approves every base pull request | Observed, not read: each of the last sixty merges to `main` carries an approval, and open pull requests report `BLOCKED` with `REVIEW_REQUIRED`, so a review requirement is configured. The rule itself is not readable at push-level permission, and the repository has zero rulesets. Automerge is allowed and is used — see the open items |
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
6. **Nothing enforces the three days, and nothing reads the real pin age.** The wait is a written
   policy. Anyone with write access can merge a Friday pull request on Friday. Worse, a pull request that survives to the next Friday is force-pushed to a
   newer pin while `createdAt` keeps the original date, so a fresh pin reads as aged — observed on 6
   of the last 30 Dependabot pull requests, diverging by 3 to 21 days. The deleted gate was the only
   thing that ever computed age from the head commit. The routine now asks the operator to run one
   `gh` command instead. If this must become a control, the options are a required status check on
   `main` — which needs repo admin and would be this repository's first — or restoring the gate.
8. **A missed Monday is silent.** Nothing signals that the week's pull requests were not merged. The
   deleted gate raised one deduplicated issue for a pull request past its window; nothing replaces
   it. 72 of 115 Dependabot pull requests to date closed without merging, so this is the common path,
   and each abandonment costs a superseded pull request and its review threads.
9. **Docker's cooldown is unverified.** GitHub lists docker as supporting `default-days` and applies
   three days by default, but Dependabot needs a release date and `Last-Modified` is absent from a
   `ghcr.io` manifest HEAD. The OCI config blob does carry one — `ghcr.io/astral-sh/uv:0.11.33`
   reports `created = 2026-07-28T09:39:24Z` in four requests — so a check that reads it and compares
   against the pin in the diff is a small, self-contained job if docker staleness must be certain.
7. **Automerge is allowed on this repository.** `allow_auto_merge` is true, and the team uses it: 4
   of the last 60 pull requests had it armed, by two different people. None was a Dependabot pull
   request, and nothing stops someone arming one — which would merge it as soon as checks pass
   rather than on Monday. Draft state used to make that impossible; nothing does now.

## Operating it

There is nothing to arm and nothing to operate. The process is the routine below.

**Every Monday.** Open `is:pr is:open author:app/dependabot` and work the list.

1. Merge the `minor-and-patch` pull request for each ecosystem. Check the real pin age first — the
   pull request header shows when it was opened, not when the pin was pushed:

   ```bash
   gh pr view <number> --json commits --jq '.commits[-1].committedDate'
   ```
2. Review `major` and `python-runtime` separately. They may need code changes.
3. Merge any security update as soon as you see it, whatever day it is.
4. Clear every `minor-and-patch` pull request before the next Friday. Two things happen otherwise:
   Dependabot replaces it and the review threads go with it, and it force-pushes a newer pin into
   any that survive, so the three days silently restart.

Nothing warns you if a Monday is missed. The deleted gate raised one deduplicated issue when a pull
request sat past its window; no mechanism replaces it, so a forgotten Monday is silent. Treat that as
the likeliest failure of the whole process: 72 of 115 Dependabot pull requests to date closed without
merging, so abandonment is the norm here, not the exception.

**Be strictest with docker.** Its cooldown is the one that may not bind, so the Friday-to-Monday wait
is the only staleness you can count on. Nothing will stop you merging it on Friday.

Nobody is notified when the week's pull requests are ready, because the CODEOWNERS review request
fires when Dependabot opens them on Friday. Monday is a routine, not a response to a prompt.

There is no supported API to trigger Dependabot itself. The only manual triggers are the
**Check for updates** button under Insights → Dependency graph → Dependabot, which is one click per
manifest row, and the `@dependabot rebase` / `@dependabot recreate` pull request comments. The
`@dependabot merge`, `close` and `reopen` commands were retired on 2026-01-27 and no longer work.
