---
name: bump-service
description: Use when a connectors service needs a new release or its dev build on one cluster or on all clusters. It changes the ArgoCD pin in the monorepo and the Terraform pin in the infrastructure repo.
---

# Bump a service

This skill works for every service in `services/`. It replaces `bump-teams-mcp`.

Local checkouts: `~/Projects/monorepo` (default branch `master`) and `~/Projects/infrastructure` (default branch `main`). Always read `origin/<default-branch>`. The local branch is often old.

Never write a cluster path or a file name from memory. Clusters change. Find every target with `git grep` for the marker `x-<service>-version`.

Never edit a pin by hand or with `sed`. Use `scripts/set-pin.sh` in this skill. The pin shapes differ between services, and a `sed` for one shape does nothing on another. The script changes the exact lines it finds, and it stops if git shows a different number of changed lines.

Ask the user for three inputs if the request does not give them:
- The service (the directory name in `services/`).
- The target: `latest`, a release version, or `dev`.
- The clusters: all, a list, or QA only.

## Step 1 - Resolve the target

For a release, list the tags of the service. Do not use `gh api .../tags`. It returns only the first 100 tags, and they can all belong to one service.

```bash
git ls-remote --tags https://github.com/Unique-AG/connectors.git "refs/tags/<service>@*" \
  | sed -E 's#.*refs/tags/<service>@##' | grep -v '\^{}$' | sort -V | tail -5
```

The last line is the newest release. Call the chosen version `<VERSION>`. Some pins use the commit SHA of the tag. Get it with the command below. Use the `^{}` line if it exists, and the other line if not.

```bash
git ls-remote https://github.com/Unique-AG/connectors.git "refs/tags/<service>@<VERSION>^{}" "refs/tags/<service>@<VERSION>"
```

For `dev`, the target is the branch `dev/<service>`. The workflow `[Release] Dev Build` creates and moves it. Make sure the branch exists:

```bash
git ls-remote --heads https://github.com/Unique-AG/connectors.git "dev/<service>"
```

If it does not exist, tell the user to run `[Release] Dev Build` first. Do not point a cluster at a branch that does not exist.

## Step 2 - Find every deployment

```bash
cd ~/Projects/monorepo && git fetch origin master -q
git grep -n 'x-<service>-version' origin/master -- gitops-resources
```

Each hit is one deployment. Run the command every time. The number of deployments grows.

A pin has one of three shapes:

| Pin | Shape |
|---|---|
| `targetRevision: <service>@<version> # x-<service>-version` | `tag` |
| `targetRevision: <40-character SHA> # x-<service>-version: <service>@<version>` | `sha` |
| `targetRevision: dev/<service> # x-<service>-version: <service>@<release>` | `dev` |

In a `dev` pin, the version after the marker is the release to return to. Do not change it by hand.

When the target is a release, keep the shape of the line you change. A `dev` line takes the shape that the other deployments of the service use. If no other deployment exists, use `sha`.

Skip each deployment that already has the target. Show the user the list of cluster, environment, and current pin. Ask which ones to change, unless the user already said.

Clusters have object names such as `burger` and `teapot`, not customer names. If the user gives a customer name, find the cluster with `git grep -ril '<customer>' origin/master -- gitops-resources/argocd/clusters`. Known: capstone is `burger`. Tell the user which cluster you found.

Never move a prod cluster to `dev`. Do it only if the user names that cluster and says `dev` in the same request.

## Step 3 - Decide what else the change needs

Fetch the target in a connectors checkout, then compare the deploy directory with the current release:

```bash
git fetch origin --tags -q
git fetch origin "dev/<service>"
git diff --stat "<service>@<OLD>".."<service>@<VERSION>" -- services/<service>/deploy
```

The second `git fetch` is only for the `dev` target.

For the `dev` target, use `FETCH_HEAD` in place of `<service>@<VERSION>`.

- Only `Chart.yaml` and the image tag in `values.yaml` changed: this is an image bump. No `values.yaml` edit is needed.
- Other files in `helm-charts/` changed: read the diff. Copy each new, renamed, or removed key to the `values.yaml` of each cluster. A chart can ignore an unknown key without an error, and ArgoCD still shows a green sync.
- `deploy/terraform/` changed: do Step 5. A change that adds a Graph scope must reach the infrastructure repo before the overlay uses the scope.
- `deploy/terraform/` did not change: do not open an infrastructure PR. The pin points at the same module code.

Tell the user which of these you found. Do not skip the infrastructure PR without saying so.

## Step 4 - Monorepo PRs

Open one PR for each cluster and environment. Branch each PR from `origin/master`. Do not stack them. Each PR must stay independent to merge and to revert.

```bash
cd ~/Projects/monorepo
git worktree add --detach "${TMPDIR:-/tmp}/bump-<service>" origin/master
```

For each deployment, run these commands at the top level of the shell. Do not put them in a shell function.

```bash
cd "${TMPDIR:-/tmp}/bump-<service>"
git checkout -q -B bump-<service>-<VERSION or dev>-<slug> origin/master
<skill dir>/scripts/set-pin.sh argocd <file> <service> tag <VERSION>
<skill dir>/scripts/set-pin.sh argocd <file> <service> sha <FULL_SHA> <VERSION>
<skill dir>/scripts/set-pin.sh argocd <file> <service> dev <RELEASE_TO_RETURN_TO>
git diff --stat
git add -A && git commit --no-verify -q -m "<title>"
git push -q -u origin bump-<service>-<VERSION or dev>-<slug>
```

Run only the one `set-pin.sh` line that matches the shape. `<slug>` is the cluster and environment with `/` changed to `-`. The `git diff --stat` must show one file. A file can hold more than one pin of the service, and the script changes all of them. Use `--no-verify` because the monorepo hooks run the full lint on a worktree that has no build.

Title for a release: `chore(<service>): bump <service> to <VERSION> in <cluster>/<env>`.
Title for the dev target: `chore(<service>): run <service> from its dev branch in <cluster>/<env>`.

Body:

```
## Summary
- Changes <service> from <OLD> to <VERSION> in the <cluster>/<env> ArgoCD app spec.
- <The values.yaml changes, or "No values.yaml changes needed.">

## Test plan
- [ ] ArgoCD syncs the new pin after the merge.
```

For the `dev` target, use this summary: "ArgoCD follows the branch `dev/<service>`. Each `[Release] Dev Build` moves the branch, and the cluster follows without a new PR. The marker keeps release <RELEASE_TO_RETURN_TO>. Bump to a release to return."

If the cluster has a customer name, write it in brackets after the cluster name in the body.

## Step 5 - Infrastructure PR

Do this step only if Step 3 found changes in `deploy/terraform/`. Do not do it for the `dev` target. A dev build has no release commit to pin. If a dev branch changes Terraform, stop and ask the user.

```bash
cd ~/Projects/infrastructure && git fetch origin main -q
git grep -n 'x-<service>-version' origin/main -- providers
```

This command lists every `.tf` file to change. File names have changed before. Change every hit unless the user gave a narrower scope.

Get the full SHA of the release tag (Step 1). Then, for each file:

```bash
<skill dir>/scripts/set-pin.sh terraform <file> <service> <FULL_SHA> <VERSION>
```

Rules for the pin:
- Use `?ref=<FULL_SHA>`. Never use `?depth=1`. A shallow clone cannot fetch a SHA.
- Never pin a tag name. A tag can move.
- Do not add a renovate comment.

Branch: `chore/bump-<service>-<VERSION>-<slug>`.
Title: `chore(cloud/azure): bump <service> to <VERSION> for <env>`.
Body: `bump <service> module version from <OLD> to <VERSION> for <env>`.

If the diff adds or removes a Graph scope, the module rewrites the grant for all principals. Users then get a new admin-approval prompt. The clusters share a few app registrations, so the change must reach every cluster that shares the registration. Tell the user before you open the PR.

## Step 6 - Verify and clean up

```bash
for p in <PR numbers>; do gh pr view "$p" --repo Unique-AG/monorepo \
  --json title,files --jq '"\(.title) | \(.files|length) file(s): \(.files[].path)"'; done
git -C ~/Projects/monorepo worktree remove "${TMPDIR:-/tmp}/bump-<service>" --force
```

Each PR must show one file that belongs to its own cluster. Give the user a table of cluster and PR URL. Say which clusters you skipped and why. Say if you opened an infrastructure PR or skipped it on purpose.
