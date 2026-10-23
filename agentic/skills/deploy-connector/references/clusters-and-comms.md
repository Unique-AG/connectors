# Clusters, Argo CD Lookup, and Communication Map

Do not hardcode customer names or customer-specific domains in `Unique-AG/connectors` (this repository is public). Use cluster codenames (`<tenant>/<env>`) and look up the customer name, tenant domain, Argo CD URL, and `#ps-<customer>` Slack channel dynamically from `Unique-AG/monorepo`, `Unique-AG/infrastructure`, and Slack.

---

## 1. Unique Internal & Multi-Tenant Clusters

Manifest path in `Unique-AG/monorepo`:
`gitops-resources/argocd/clusters/unique/<env>/application-specs/{connectors,mcp}/<service>/app.yaml`

| Cluster | Argo CD URL | Auto-Sync | Deployed Connectors & MCPs |
| --- | --- | --- | --- |
| `unique/qa` | `https://qa-argo.alpine-bowfin.ts.net` | `true` (verify in UI; some apps require manual sync) | `confluence-connector` (`confluence-connector-v2`), `sharepoint-connector`, `backstop-mcp`, `kb-mcp`, `office-365-mcp`, `outlook-semantic-mcp`, `teams-mcp`, `with-intelligence-mcp` |
| `unique/uat01` | `https://argo.uat1.unique.app` | `false` | `confluence-connector` (`confluence-connector-v2`), `sharepoint-connector`, `backstop-mcp`, `kb-mcp`, `outlook-semantic-mcp`, `teams-mcp`, `with-intelligence-mcp` *(Note: `office-365-mcp` is not deployed on `uat01`)* |
| `unique/prod` | `https://prod-argo.alpine-bowfin.ts.net` | `false` | `confluence-connector` (`confluence-connector-v2`), `sharepoint-connector` (3 releases: `sharepoint-connector`, `sharepoint-connector-central-sales-demo`, `sharepoint-connector-seedling`), `kb-mcp`, `office-365-mcp`, `outlook-semantic-mcp`, `teams-mcp`, `with-intelligence-mcp` *(Note: `backstop-mcp` is not deployed on `prod`)* |
| `unique/ch01` | `https://argo.ch.one.unique.app` | `false` | `outlook-semantic-mcp` (2 apps: `outlook-semantic` and `outlook-semantic-01`) |
| `unique/us01` | `https://argo.us1.unique.app` | `false` | `outlook-semantic-mcp` |

---

## 2. Customer Single-Tenant Clusters

Manifest path in `Unique-AG/monorepo`:
`gitops-resources/argocd/clusters/<tenant>/<env>/application-specs/{connectors,mcp}/<service>/app.yaml`

All customer single-tenant clusters have `autoSync: false`.

| Cluster Codename | Provider Path in `Unique-AG/infrastructure` | Deployed Connectors & MCPs | Notes |
| --- | --- | --- | --- |
| `burger/prod` | `providers/azure/unique-ag/tenants/burger/prod` | `sharepoint-connector`, `teams-mcp`, `outlook-semantic-mcp`, `backstop-mcp` | Uses managed Azure Postgres for `backstop-mcp`. |
| `ps/terra` | `providers/azure/unique-ag/tenants/ps/terra` | `sharepoint-connector`, `kb-mcp` | Ensure Cilium `networkPolicy.egress` on `kb-mcp` allows the tenant's Zitadel `id.<tenant-domain>:443` host. |
| `sparkles/prod` | `providers/azure/unique-ag/tenants/sparkles/prod` | `teams-mcp`, `outlook-semantic-mcp`, `office-365-mcp` | |
| `teapot/prod` | `providers/azure/unique-ag/tenants/teapot/prod` | `teams-mcp`, `office-365-mcp` | |
| `skyline/prod` | `providers/azure/unique-ag/tenants/skyline/prod` | `sharepoint-connector` | |
| `tree/evx` | `providers/azure/unique-enterprise/tenants/tree/evx` | `teams-mcp` | Restricted Entra ID login on Argo CD — ask `@soleng-on-call` (`<!subteam^S0AJ8T5CKFD>`) in `#sig-solution-engineering` to sync if you lack access. |

---

## 3. How to Look Up Clusters, Customer Names, Argo CD URLs, and Slack Channels

### 3.1 Find every cluster running a connector or MCP server

Search `Unique-AG/monorepo` for all Argo CD application specs referencing `Unique-AG/connectors.git`:

```bash
gh search code --repo Unique-AG/monorepo "https://github.com/Unique-AG/connectors.git" \
  --limit 100 --json path --jq '.[].path' | sort
```

### 3.2 Resolve a cluster codename (`<tenant>/<env>`) to its customer domain and Argo CD URL

1. **Across all tenants at once (`Unique-AG/infrastructure`)**:
   Every cluster's Argo CD `values.by-ref.yaml` sets `configs.cm.url` (the Argo CD URL), `configs.cm."ui.bannercontent"` (`<customer-domain>@<codename>`), and `configs.cm."ui.bannerurl"` (the customer's chat URL):
   ```bash
   gh search code --repo Unique-AG/infrastructure "ui.bannercontent" --limit 30 \
     --json path,textMatches --jq '.[] | {path, matches: [.textMatches[].fragment]}'
   ```
2. **For a single cluster (`Unique-AG/infrastructure`)**:
   Read `providers/azure/{unique-ag,unique-enterprise}/tenants/<tenant>/<env>/gitops/1-argo/values.by-ref.yaml`:
   ```bash
   gh api -H "Accept: application/vnd.github.raw" \
     "repos/Unique-AG/infrastructure/contents/providers/azure/unique-ag/tenants/<tenant>/<env>/gitops/1-argo/values.by-ref.yaml" \
     | yq '{argoUrl: .configs.cm.url, banner: .configs.cm."ui.bannercontent", appUrl: .configs.cm."ui.bannerurl"}'
   ```
   *(For enterprise clusters such as `tree/evx`, `tree/prod`, `deer/prod`, `opera/prod`, or `gondola/prod`, replace `unique-ag` with `unique-enterprise` in the path.)*
3. **From the app's own Helm values (`Unique-AG/monorepo`)**:
   Read `gitops-resources/argocd/clusters/<tenant>/<env>/application-specs/mcp/<service>/values.yaml` — `mcpConfig.app.publicBaseUrl`, `mcpConfig.app.frontendBaseUrl`, and `mcpConfig.zitadel.baseUrl` contain the tenant's public domain.

### 3.3 Resolve a cluster codename to its `#ps-<customer>` Slack channel

1. **From Alertmanager / LiteLLM overlays in `Unique-AG/infrastructure`**:
   Customer alert routing labels (`slack_channel: ps-<customer>`) are configured in the tenant's `gitops/3-system/litellm/values-extras.yaml` or Prometheus alert rules:
   ```bash
   gh search code --repo Unique-AG/infrastructure "slack_channel: ps-" --limit 30 \
     --json path,textMatches --jq '.[] | {path, matches: [.textMatches[].fragment]}'
   ```
2. **From Slack directly**:
   - Alertmanager posts cluster alerts with the K8s cluster name (`<tenant>-prod` or `ps-<tenant>`) into the customer's `#ps-<customer>` channel. Search Slack messages for `k8s_cluster` and `<tenant>-prod` (or `ps-<tenant>`) to see which `#ps-<customer>` channel receives alerts for that cluster.
   - Or search Slack channels (`slack_search_channels`) for `#ps-` matching the customer name from `ui.bannercontent` in Step 3.2.

---

## 4. Who to Inform at Each Step

| Step / Situation | Channel / System | Who to Tag / Inform | What to Communicate |
| --- | --- | --- | --- |
| **0. Start of rollout & task tracking** | Jira (`UN` project) & `#pod-connectors` | Connector pod teammates (`@connectors-on-call` / `<!subteam^S0C2M3PH61Z>`) | Create/assign `UN` ticket(s) on component `mcp-servers`; open a coordination thread in `#pod-connectors` with service ownership and cluster checklist. |
| **1. Unreleased Terraform / infra changes in changelog** | `#sig-infrastructure` | `@infra-on-call` (`<!subteam^S08C9H7TZFZ>`) / infra PR author | Confirm whether the Helm chart can roll out before the Terraform change; file a follow-up `UN` ticket if infra needs a separate rollout. |
| **2. Non-trivial chart values migration** | `#pod-connectors` | Service author / maintainer | Confirm `values.yaml` / `valuesObject` migration (e.g. `mcpConfig`, `fullnameOverride`) and request PR review for Unique clusters (`qa`, `uat01`, `prod`). |
| **3. Unique internal clusters (`qa`, `uat01`, `prod`) synced** | `#sig-connectors` & Jira `UN` ticket | Stakeholders / Product / Security | Confirm `qa`, `uat01`, and `prod` are updated and healthy; link the `monorepo` PR on the Jira ticket and state that single-tenant PRs are next. |
| **4. Single-tenant `monorepo` PR ready for review** | `#sig-solution-engineering` & `#sig-connectors` | `@soleng-on-call` (`<!subteam^S0AJ8T5CKFD>`) on Slack; `@Unique-AG/solutions-engineering` on GitHub | Share the single-tenant `monorepo` PR, explain the reason for the bump (e.g. security patch), note any major chart version bumps and whether functionality changed, and confirm whether pre-sync client comms are needed. |
| **5a. Starting single-tenant Argo CD syncs** | `#sig-connectors` & `#pod-connectors` | Stakeholders in `#sig-connectors`; teammates in `#pod-connectors` | Announce start of tenant syncs in `#sig-connectors`; claim individual clusters by codename (`burger/prod`, `sparkles/prod`, etc.) in `#pod-connectors`. |
| **5b. Restricted Argo CD access (e.g. `tree/evx`)** | `#sig-solution-engineering` | `@soleng-on-call` (`<!subteam^S0AJ8T5CKFD>`) | Ask someone in Solutions Engineering with access to that tenant's Argo CD to sync the application. |
| **5c. Downtime or hotfix on a customer cluster (e.g. NetworkPolicy deny)** | `#ps-<customer>` & `#2_support` | Customer delivery team in `#ps-<customer>`; `@soleng-on-call` (`<!subteam^S0AJ8T5CKFD>`) in `#2_support` | Resolve the cluster codename to `#ps-<customer>` (Section 3.3), inform them of the update/brief downtime, and post the hotfix `monorepo` PR in `#2_support` tagging `@soleng-on-call` for fast approval. |
| **5d. MCP tool definitions changed in the release** | `#sig-connectors` / `#ps-<customer>` | Account Solutions Engineer / Delivery Owner | Inform them that a Unique Admin on the tenant must click **Refresh tools** in the MCP Hub. (Skip if no tool definitions changed.) |
| **5e. Rollout complete** | `#pod-connectors`, `#sig-connectors`, & Jira | Stakeholders in `#sig-connectors`; transition Jira `UN` ticket(s) to **Done** | Confirm all environments are synced and healthy, post all PR links on the Jira issue(s), and mark the ticket(s) **Done**. |
