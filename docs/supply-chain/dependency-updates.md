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
| Friday to Monday | The pins do not move | `rebase-strategy: disabled` |
| Monday | The team reviews and merges them | people |

There is no automated gate. The three days are a merge policy the team follows, which is what the
standard asks for. Two mechanisms make it real, and both live in `.github/dependabot.yaml`.

`cooldown: default-days: 3` stops Dependabot offering a version until it has been public three days.
So on npm, uv, github-actions, terraform and helm every pin is already three days old when the pull
request opens, before anyone waits at all.

`rebase-strategy: disabled` stops Dependabot re-pointing an open pull request at a newer digest. The
pin merged on Monday is the pin opened on Friday. This is what the standard calls the freeze, and it
is the part that survives without a gate.

Docker is the exception and it matters, because the standard is about base images. Its `cooldown` is
deliberately absent — Dependabot reads a Docker release date from `Last-Modified` on the manifest
HEAD, which neither `registry-1.docker.io` nor `ghcr.io` returns, so the setting fails open. For
docker the three days come only from the pull request sitting from Friday to Monday. Nothing enforces
that. Merging a docker update on Friday takes a pin that may be hours old.

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

**`rebase-strategy: disabled` is the whole freeze.** Without it Dependabot re-points an open pull
request at the newest digest and the three-day age resets silently, while `createdAt` stays put — so
you would merge a zero-age pin and record three days. The standard documents that hole and accepts
it. This closes it.

Its known cost is unchanged: Dependabot supersedes and replaces an unmerged group pull request on the
next Friday run (#746 to #754 to #788 to #865), and the review threads go with it. That is an
argument for merging on Monday, which is the point of the process.

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
| No tooled age cooldown | Read the other way here. `cooldown: 3` is set on the five ecosystems where release dates resolve, and omitted on docker where it fails open |
| The cooldown is a manual merge policy, with the pin frozen | This is the cycle above. `rebase-strategy: disabled` is the freeze. The three days are the merge policy, and nothing enforces them — see the open items |
| A rebase resets the age (accepted hole) | Closed. See the design notes |
| Automerge off. A human approves every base pull request | No dependency pull request has automerge armed, and every merge to `main` carries an approval. The repository does allow automerge, so nothing prevents someone arming it — see the open items |
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
6. **Nothing enforces the three days.** The wait is a written policy. Anyone with write access can
   merge a Friday pull request on Friday, and for docker that pin may be hours old. A gate was built
   and deleted: see the design notes for why. If this needs to become a control, the honest options
   are a required status check on `main` — which needs repo admin and would be the repository's
   first — or restoring the draft gate and accepting its cost.
7. **Automerge is allowed on this repository.** `allow_auto_merge` is true, and the team uses it: 4
   of the last 60 pull requests had it armed, by two different people. None was a Dependabot pull
   request, and nothing stops someone arming one — which would merge it as soon as checks pass
   rather than on Monday. Draft state used to make that impossible; nothing does now.

## Operating it

There is nothing to arm and nothing to operate. The process is the routine below.

**Every Monday.** Open `is:pr is:open author:app/dependabot` and work the list.

1. Merge the `minor-and-patch` pull request for each ecosystem. Their pins opened on Friday and have
   not moved.
2. Review `major` and `python-runtime` separately. They may need code changes.
3. Merge any security update as soon as you see it, whatever day it is.
4. If a `minor-and-patch` pull request is still open next Friday, Dependabot will replace it and its
   review threads will go with it. Merge it or close it before then.

**Do not merge a docker update before Monday.** It is the one ecosystem with no version cooldown, so
the three days come only from the pull request sitting there. Nothing will stop you.

Nobody is notified when the week's pull requests are ready, because the CODEOWNERS review request
fires when Dependabot opens them on Friday. Monday is a routine, not a response to a prompt.

There is no supported API to trigger Dependabot itself. The only manual triggers are the
**Check for updates** button under Insights → Dependency graph → Dependabot, which is one click per
manifest row, and the `@dependabot rebase` / `@dependabot recreate` pull request comments. The
`@dependabot merge`, `close` and `reopen` commands were retired on 2026-01-27 and no longer work.
