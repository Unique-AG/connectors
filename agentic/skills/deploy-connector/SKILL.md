---
name: deploy-connector
description: >-
  Releases, updates, and deploys connectors and MCP servers from
  Unique-AG/connectors to Unique internal clusters (qa, uat01, prod, ch01,
  us01) and customer single-tenant clusters via Unique-AG/monorepo and Argo CD.
  Covers pre-release changelog checks, sequential release-please merges, commit
  SHA pinning, Helm values migrations and local diff verification, staged
  rollout (qa -> uat01 -> prod -> single tenants), Argo CD syncing, and who to
  inform in Slack and Jira at each step. Use whenever someone asks to release,
  bump, roll out, patch, or deploy a connector or MCP server across Unique
  environments or customer tenants.
metadata:
  internal: true
---

# Updating and Deploying a Connector or MCP Server

Deployments from `Unique-AG/connectors` to Unique and customer clusters follow five stages:

```
Task Progress:
- [ ] Step 0: Track the rollout in Jira and #pod-connectors
- [ ] Step 1: Audit changelogs and cut releases in Unique-AG/connectors
- [ ] Step 2: Bump Unique internal clusters (qa, uat01, prod) in Unique-AG/monorepo
- [ ] Step 3: Sync and verify Unique clusters in order (qa -> uat01 -> prod)
- [ ] Step 4: Bump customer single-tenant clusters in Unique-AG/monorepo
- [ ] Step 5: Sync single-tenant clusters in Argo CD, verify health, and close out
```

For the full cluster-to-service matrix, Argo CD URLs, and Slack communication map, read [references/clusters-and-comms.md](references/clusters-and-comms.md).

---

## Step 0: Track the Rollout in Jira and Slack

1. **Jira ticket**: Ensure a task exists in project `UN` on component `mcp-servers` (use the `jira` skill if one needs to be created). Reference `[UN-xxxxx]` in every `Unique-AG/monorepo` PR title and body, and post each PR URL as a comment on the Jira issue.
2. **Coordinate in `#pod-connectors`**: When rolling out multiple connectors or MCP servers with teammates, post a tracking thread in `#pod-connectors` listing each service, its owner, and the stages (`release` -> `monorepo PR - Unique` -> `monorepo PR - Tenants` -> `sync everywhere` per tenant cluster).
3. **Security / urgent rollouts**: Reply in `#sig-connectors` with the fix PRs from `Unique-AG/connectors` and tag `@connectors-on-call` (`<!subteam^S0C2M3PH61Z>`). Keep `#sig-connectors` updated as each stage completes.

---

## Step 1: Audit Changelogs and Cut Releases in `Unique-AG/connectors`

Once the code, dependency, or Dockerfile fix is merged to `Unique-AG/connectors` `main`, `release-please` opens or updates a `chore(main): release <service> <version>` PR per affected service.

### 1.1 Audit the Release-Please PR before merging

Inspect every entry in the release PR's `CHANGELOG.md` since the currently deployed version on each cluster:

- **Helm chart breaking changes**: Check if `values.yaml` keys moved or changed (for example, top-level `tenantGuidance` or `env` URLs moving under `mcpConfig`, `ZITADEL_CLIENT_ID` moving from `envVars` to `mcpConfig.zitadel.clientId`, a removed `connector:` wrapper, removed `extraEnvCM` ConfigMaps, newly added chart volumes such as `tenant-config` or `pg-cluster-ca`, or changed `fullnameOverride` defaults). Every cluster overlay in `Unique-AG/monorepo` jumping across that version must be migrated in Steps 2 and 4.
- **Terraform / Entra app changes**: If the changelog includes commits touching `deploy/terraform/` or Entra app registrations (such as service principal lifecycle changes), check with `#sig-infrastructure` (`<!subteam^S08C9H7TZFZ>`) and the author of the infra change before releasing to confirm whether the Helm chart is coupled to the Terraform module or can be deployed independently. If Terraform can be applied separately, file a follow-up `UN` ticket and sync the `#sig-infrastructure` thread to it.
- **MCP tool definition changes**: Check if tool names, descriptions, or parameter schemas changed.
  - **If tool definitions changed**: After deployment, a Unique Admin on each affected tenant must click **Refresh tools** in the MCP Hub; coordinate with the account's Solutions Engineer.
  - **If only internal code, base images, certs, or dependencies changed**: No MCP Hub tool refresh is needed.

### 1.2 Merge Release-Please PRs sequentially

- **Manifest conflict trap**: Every release-please PR edits `.release-please-manifest.json`. When releasing multiple services, merge them **one at a time** and wait for `release-please` to rebase/update the remaining PRs (or resolve the `.release-please-manifest.json` conflict) before merging the next one.
- Merging the release PR triggers `[Release] Please` -> `[Template] CD`, which:
  1. Builds the container image from `refs/tags/<service>@<version>` and pushes it to `ghcr.io/unique-ag/connectors/services/<service>:<version>` and `uniquecr.azurecr.io/connectors/services/<service>:<version>`.
  2. Signs both images with Cosign (OIDC).
  3. Packages and pushes the Helm chart to `uniquecr.azurecr.io`, `ghcr.io`, and `getunique.azurecr.io`.
  4. Runs Trivy vulnerability and license scans and publishes `services/<service>/docs` to Confluence.
- **If a release workflow fails halfway**: Do **not** use "Re-run failed jobs" on the `release-please` job (it finds no release on a second run). Trigger `[Release] Manual Re-Run` from `main` with the service name and version (without a leading `v`). If only the Confluence docs step failed, run `[Docs] Publish to Confluence` from `main`.

### 1.3 Resolve the release commit SHA

`Unique-AG/monorepo` pins the **40-character commit SHA** of the release tag, not the tag name itself. Resolve it once the release tag exists:

```bash
gh api "repos/Unique-AG/connectors/git/ref/tags/<service>@<version>" --jq '.object.sha'
```

---

## Step 2: Bump Unique Internal Clusters (`qa`, `uat01`, `prod`) in `Unique-AG/monorepo`

Create a PR in `Unique-AG/monorepo` updating the Unique internal environments first (`unique/qa`, `unique/uat01`, `unique/prod`). Do not bundle customer single-tenant clusters into this first PR.

### 2.1 Update `app.yaml` and `values.yaml`

Application specs live under `gitops-resources/argocd/clusters/unique/{qa,uat01,prod}/application-specs/`:
- Connectors (`confluence-connector`, `sharepoint-connector`): `application-specs/connectors/<service>/app.yaml`
- MCP servers (`backstop`, `kb-mcp`, `office-365`, `outlook-semantic`, `teams`, `with-intelligence`): `application-specs/mcp/<service>/app.yaml`

For each environment where the service is deployed (see [references/clusters-and-comms.md](references/clusters-and-comms.md)):

1. **Pin `targetRevision`**: Set `targetRevision` on every `https://github.com/Unique-AG/connectors.git` source in `app.yaml` to the 40-character release commit SHA, keeping the version in the trailing `x-<service>-version` comment:
   ```yaml
   - repoURL: https://github.com/Unique-AG/connectors.git
     path: services/<service>/deploy/helm-charts/<service>
     targetRevision: <40-char-commit-sha> # x-<service>-version: <service>@<version>
   ```
   *(Check for multi-instance `app.yaml` files: `sharepoint-connector` on `unique/prod` defines three Helm sources in one `app.yaml` — `sharepoint-connector`, `sharepoint-connector-central-sales-demo`, and `sharepoint-connector-seedling`. Update all three.)*
2. **Apply chart value migrations**: Update `values.yaml` (or `valuesObject` in `app.yaml`) for any chart changes identified in Step 1.1.
   - **Resource naming guard (`confluence-connector-v2`)**: On `unique/uat01` and `unique/prod`, ensure `nameOverride: confluence-connector-v2` and `fullnameOverride: confluence-connector-v2` are set when the chart defaults `fullnameOverride` to `confluence-connector`, so the deployment does not rename itself, break Cilium ingress label selectors (`app.kubernetes.io/name: confluence-connector-v2`), or collide with legacy resources in `finance-gpt`.
   - **Database & CA differences**: Remember that `unique/qa` and `unique/prod` often use in-cluster CloudNativePG (`*-pg-cluster`), whereas `unique/uat01` and customer single tenants typically use managed Azure Postgres. Do not switch database backends inside an urgent rollout PR.

### 2.2 Validate Helm rendering locally

Before requesting review, render both the previous chart version and the new chart version with each environment's values and diff them:

```bash
helm lint services/<service>/deploy/helm-charts/<service> --strict -f <path-to-cluster-values.yaml>
helm template <release-name> services/<service>/deploy/helm-charts/<service> -f <path-to-cluster-values.yaml>
```

Or from a `Unique-AG/monorepo` checkout:

```bash
./bin/helm-diff.sh --mode local --cluster unique/qa,unique/uat01,unique/prod --app <app-name>
```

Verify that:
- No duplicate volumes (e.g., `tenant-config`), duplicate env vars, or references to removed ConfigMaps (`extraEnvCM`) exist.
- Resource names, `Deployment` selectors, and pod labels are unchanged.
- If the new chart verifies CloudNativePG server certificates (e.g., `with-intelligence-mcp`, `backstop-mcp`), confirm the cluster's CNPG server secret includes the `fqdn-uri` host in `subjectAltName`:
  ```bash
  kubectl -n <ns> get secret <service>-pg-cluster-server -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -ext subjectAltName
  ```

### 2.3 Review and merge

- Name the PR `chore(<scope>): bump unique qa, uat01 and prod [UN-xxxxx]`.
- Request review from a teammate in `#pod-connectors` (and check with the service owner if a chart migration is non-trivial).

---

## Step 3: Sync and Verify Unique Clusters (`qa` -> `uat01` -> `prod`)

Roll out and verify strictly in order: **`unique/qa` -> `unique/uat01` -> `unique/prod`**.

1. **Check Argo CD sync status**:
   - `unique/qa` (`https://qa-argo.alpine-bowfin.ts.net`) has `autoSync: true` on most apps, while `unique/uat01` (`https://argo.uat1.unique.app`) and `unique/prod` (`https://prod-argo.alpine-bowfin.ts.net`) have `autoSync: false`. Always verify in the Argo CD UI; do not assume `autoSync` is enabled.
   - Immediately after merging a `monorepo` PR, Argo CD may briefly report `ComparisonError: Failed to load target state ... Manifest generation error (cached)` for 1–2 minutes while branch state updates. Wait a moment, click **Refresh**, and then click **Sync**.
   - Check **Prune** when syncing if the chart upgrade removed or renamed ConfigMaps, PrometheusRules, or other resources.
2. **Verify health on `qa`, then `uat01`, then `prod`**:
   - Confirm the `Deployment` rolls out cleanly, pods are `Running`/`Healthy`, and any pre-upgrade/sync migration `Job` completes (`teams-mcp`, `outlook-semantic-mcp`, `backstop-mcp`, `with-intelligence-mcp`).
   - Test `/ready`, OAuth login, and a representative tool call or connector sync in `qa` and `uat01`.
   - If `uat01` fails to sync or pods fail to start, fix the values in a follow-up `Unique-AG/monorepo` PR and re-sync `uat01` **with Prune** before syncing `prod`.
3. **Inform `#sig-connectors`**: Once `qa`, `uat01`, and `prod` are healthy, post a status update in `#sig-connectors` (and comment on the `UN` Jira ticket) before starting the single-tenant rollout.

---

## Step 4: Bump Customer Single-Tenant Clusters in `Unique-AG/monorepo`

Once Unique internal clusters are healthy, open a single consolidated PR (or per-service PR) in `Unique-AG/monorepo` for all customer single-tenant clusters (`burger/prod`, `ps/terra`, `sparkles/prod`, `teapot/prod`, `skyline/prod`, `tree/evx`) and regional clusters (`unique/ch01`, `unique/us01`) that run the updated services.

1. **Find every deployed instance**:
   Search `gitops-resources/argocd/clusters/` in `Unique-AG/monorepo` for `services/<service>/deploy/helm-charts/<service>` or consult [references/clusters-and-comms.md](references/clusters-and-comms.md).
2. **Update `targetRevision` and tenant `values.yaml`**:
   - Pin the exact same 40-character release commit SHA tested in Step 3 (`# x-<service>-version: <service>@<version>`).
   - Port the same `values.yaml` migrations (such as `mcpConfig` restructuring or `mcpConfig.zitadel.clientId`) to each customer cluster's `values.yaml`.
   - Check each tenant's Cilium `networkPolicy.egress` rules in `values.yaml`: single-tenant clusters enforce default-deny egress (`enableDefaultDeny.egress: true`). Ensure any required hosts (such as the tenant's Zitadel host `id.<tenant-domain>:443` under `toFQDNs`) are permitted.
3. **Validate every tenant overlay locally**:
   - Run `helm template` (with schema validation) and `helm lint --strict` for every changed tenant app with its cluster's `values.yaml`, and compare the rendered manifests against `master`.
   - Include a `Cluster x Service` version table (`old -> new`) in the PR description.
4. **Inform and get approval before merging/syncing**:
   - **Solutions Engineering (`#sig-solution-engineering`)**: Post the PR in `#sig-solution-engineering` tagging `@soleng-on-call` (`<!subteam^S0AJ8T5CKFD>`). Call out any major chart version bumps and state clearly whether functionality or tool definitions changed.
   - **Product / Security (`#sig-connectors`)**: Post the PR link in `#sig-connectors` and confirm whether pre-sync customer communication is needed (for security vulnerabilities, sync as soon as Solutions Engineering / Product approves).
   - Wait for approval from `@Unique-AG/solutions-engineering` before merging.

---

## Step 5: Sync Customer Single-Tenant Clusters in Argo CD and Close Out

All customer single-tenant clusters have `autoSync: false` and require a manual sync in each cluster's Argo CD instance.

1. **Coordinate cluster syncs by cluster name in `#pod-connectors`**:
   - Announce in `#sig-connectors` (`proceeding with update in tenants`) and claim clusters by their cluster name in `#pod-connectors` (`I take burger/prod`, `I take sparkles/prod`, `I take skyline/prod`, `I take teapot/prod`, `I take ps/terra`, `I take tree/evx`) so teammates do not sync the same cluster concurrently.
2. **Sync each app in Argo CD** (see [references/clusters-and-comms.md](references/clusters-and-comms.md) for how to look up each tenant's Argo CD URL):
   - Open the application (`apps-<service>` or `<service>`), click **Sync** (check **Prune** if resources were removed), and wait for the pod and any migration hook `Job` to become `Healthy`.
   - **Access-restricted Argo CD instances (e.g., `tree/evx`)**: If you do not have access to a tenant's Argo CD, post in `#sig-solution-engineering` tagging `@soleng-on-call` (`<!subteam^S0AJ8T5CKFD>`) or the responsible Solutions Engineer to trigger the sync.
3. **Handle post-sync issues (NetworkPolicy / alerts)**:
   - Monitor the tenant's `#ps-<customer>` Slack channel (see [references/clusters-and-comms.md](references/clusters-and-comms.md) for how to resolve a cluster codename to its `#ps-<customer>` channel) and pod health after syncing.
   - If a pod crash-loops or Cilium drops egress (for example, `kb-mcp` denied egress to `id.<tenant-domain>:443`):
     1. Post a heads-up in the customer channel (`#ps-<customer>`) noting that the connector is being updated and brief downtime may occur.
     2. Open a hotfix PR in `Unique-AG/monorepo` updating `networkPolicy.egress` in the tenant's `values.yaml`.
     3. Post the hotfix PR in `#2_support` or `#sig-solution-engineering` tagging `@soleng-on-call` (`<!subteam^S0AJ8T5CKFD>`) for immediate review, merge, and re-sync in Argo CD.
4. **Final sign-off**:
   - Mark all services and tenant clusters as `:white_check_mark:` in the `#pod-connectors` tracking thread.
   - Post the final completion message in `#sig-connectors` confirming all connectors and MCP servers are updated and healthy across Unique and customer tenants.
   - Ensure all `Unique-AG/monorepo` PRs are linked on the Jira ticket(s) in project `UN` and transition the ticket(s) to **Done**.
