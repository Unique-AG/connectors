<!-- confluence-page-id: 2535522323 -->
<!-- confluence-space-key: PUBDOC -->

Enabling Recordings & Transcripts means configuring **two** systems: the [Teams MCP Server](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1802633229/Teams-MCP), which captures meeting transcripts into the knowledge base, and the **Unique platform**, which presents them in the Recordings area. Both must point at the same knowledge-base root scope — that single shared value is the most common source of misconfiguration.

!!! warning "Read the eligibility section first"
    This feature stores copies of meeting transcripts and recordings in the Unique knowledge base. Confirm that this is acceptable to your organisation before enabling it — see [Is this feature for you?](./README.md#is-this-feature-for-you).

## Prerequisites

| Prerequisite | Details |
|---|---|
| **Teams MCP Server deployed** | See [Teams MCP - Deployment](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1802141709/Teams+MCP+-+Deployment) |
| **RabbitMQ** | Required for the ingestion pipeline; chat-only deployments do not need it |
| **Admin consent granted** | The four Microsoft Graph permissions on Unique's capture app — see [Grant admin consent](#Grant-admin-consent) |
| **Graph transcript API access enabled** | Tenant-wide Teams meeting setting `EnableGraphTranscriptAccess` — see [Teams Graph transcript API access](#Teams-Graph-transcript-API-access). Entra consent alone is not enough |
| **Zitadel service account** | With the roles listed below — see [Zitadel service account](#Zitadel-service-account) |
| **Root scope created** | Created manually in Unique before deployment — see [Root scope](#Root-scope) |
| **Teams transcription enabled** | By Microsoft Teams meeting policy, otherwise there is nothing to capture |

## Grant admin consent

Capture uses a **dedicated Entra ID app registration**, separate from the chat-only Teams MCP app. Consent granted for chat does not cover this feature.

Two of the scopes below read meeting content and are therefore privileged: `OnlineMeetingTranscript.Read.All` and `OnlineMeetingRecording.Read.All`. Both require **admin consent** — users cannot approve them for themselves. Until an administrator has granted it, users see an error when they try to connect.

Admin consent alone is **not** enough. You must also enable Microsoft Graph transcript API access in Teams meeting settings — see [Teams Graph transcript API access](#Teams-Graph-transcript-API-access).

**Recommended for most clients.** When Unique runs Teams MCP with capture enabled, Unique provisions this app registration for you. You only need to grant admin consent:

```
https://login.microsoftonline.com/organizations/adminconsent?client_id=c55409b0-c2c3-4dcc-96c9-ceb85a729ba5
```

The consent prompt lists **only** these Microsoft Graph delegated permissions — there are no Teams chat or channel messaging scopes on this app:

| Permission | Type | Admin consent | Description |
|------------|------|---------------|-------------|
| `OnlineMeetingRecording.Read.All` | Delegated | **Yes** | Read all recordings of online meetings |
| `OnlineMeetings.Read` | Delegated | No | Read user's online meetings |
| `OnlineMeetingTranscript.Read.All` | Delegated | **Yes** | Read all transcripts of online meetings |
| `User.Read` | Delegated | No | Sign in and read user profile |

Least-privilege justification for each scope is in [Required Microsoft Graph permissions](./technical.md#required-microsoft-graph-permissions).

If your organization uses multiple Azure tenants, confirm you are granting consent for the correct directory. See [Grant tenant-wide admin consent to an application](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) for a tenant-specific admin consent URL; use application (client) ID `c55409b0-c2c3-4dcc-96c9-ceb85a729ba5`.

Consenting the correct directory is not enough if Unique hosts a dedicated Teams MCP for that customer: the MCP OAuth authority still defaults to `/common`, and Microsoft can open the signed-in admin's home tenant (often production) instead of the directory that granted consent. Pin SSO with `mcpConfig.microsoft.signInTenant` (env `MICROSOFT_SIGN_IN_TENANT`) set to that directory's GUID — see [Teams MCP - Authentication — OAuth authority](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1803026436/Teams+MCP+-+Authentication#OAuth-authority-MICROSOFT_SIGN_IN_TENANT).

Self-hosted deployments provision their own app registration instead — see [Teams MCP - Authentication](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1803026436/Teams+MCP+-+Authentication#Self-Hosted). Request only the permissions in the table above (`UNIQUE_INTEGRATION=enabled`, `CHAT_INTEGRATION=disabled`).

## Teams Graph transcript API access

Microsoft treats Graph access to meeting transcripts as a **tenant-wide Teams meeting setting**, separate from Entra admin consent. Unique cannot enable this via OAuth or Graph — a Teams or Global administrator must turn it on.

| Control | What it does |
|---------|--------------|
| Entra admin consent | Grants `OnlineMeetingTranscript.Read.All` so the app may call the API |
| `EnableGraphTranscriptAccess` | Whether **any** app/agent in the tenant may use transcript Graph APIs at all |

By default, Graph access to transcripts is **off**, regardless of app-level permissions. Consent covers the Entra permission half; the Teams toggle is the other half. There is no Graph or consent API for an app to set `EnableGraphTranscriptAccess` on behalf of the tenant.

Until this toggle is on, creating or renewing transcript subscriptions and fetching transcripts returns **403** (`GraphAccessToTranscriptsDisabled`). This is easy to misdiagnose as a consent, wrong-app, or bad-id problem — re-consent will not fix it.

### Teams admin center

1. **Meetings → Meeting settings**
2. Under **Transcript API access**, set **Microsoft Graph access → On**
3. Optionally open **Configure** and enable **Include speaker attribution** (needed for attributed VTT; Unique expects that)

Docs: [Manage meeting transcript API access](https://learn.microsoft.com/en-us/microsoftteams/meeting-transcript-api-access)

### PowerShell

```powershell
Set-CsTeamsMeetingConfiguration -Identity Global -EnableGraphTranscriptAccess $true
# optional, for speaker-attributed transcripts:
Set-CsTeamsMeetingConfiguration -Identity Global -EnableAttributedTranscripts $true
```

### After it’s enabled

1. Wait a few minutes for propagation.
2. Have the user call `start_kb_integration` again (or reconnect if the local subscription was deleted after failed renewals).
3. Confirm with `verify_kb_integration_status` → `active`.

## Enable ingestion on the Teams MCP Server

Set `UNIQUE_INTEGRATION=enabled`. This registers the transcript ingestion pipeline and the four knowledge-base tools, and makes the Unique API and Zitadel configuration mandatory.

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `UNIQUE_INTEGRATION` | `mcpConfig.unique.integration` | (required) | Set to `enabled` for this feature. `disabled` is chat-only and captures nothing |
| `UNIQUE_SERVICE_AUTH_MODE` | `mcpConfig.unique.serviceAuthMode` | `cluster_local` | `cluster_local` or `external` |
| `UNIQUE_API_BASE_URL` | `mcpConfig.unique.apiBaseUrl` | (required) | Unique API endpoint |
| `UNIQUE_API_VERSION` | `mcpConfig.unique.apiVersion` | `2023-12-06` | API version |
| `UNIQUE_ROOT_SCOPE_ID` | `mcpConfig.unique.rootScopeId` | (required) | Root scope all meetings are ingested under. **Must match `RECORDING_KB_SCOPE_ID`** |
| `UNIQUE_USER_FETCH_CONCURRENCY` | `mcpConfig.unique.userFetchConcurrency` | `5` | Parallel participant lookups |
| `UNIQUE_INGESTION_SERVICE_BASE_URL` | `mcpConfig.unique.ingestionServiceBaseUrl` | (required with `cluster_local`) | Ingestion service endpoint |
| `UNIQUE_SERVICE_EXTRA_HEADERS` | `mcpConfig.unique.serviceExtraHeaders` | (required) | Zitadel service account headers (`x-company-id`, `x-user-id`, …) |
| `UNIQUE_AUTO_START_INGESTION` | `mcpConfig.unique.autoStartIngestion` | `false` | When enabled, every user gets a transcript subscription at login instead of having to call `start_kb_integration` |

Subscription and webhook behaviour is configured with the following variables. Their lifecycle is described in the [Technical Manual](./technical.md#subscription-lifecycle).

| Variable | Default | Description |
|----------|---------|-------------|
| `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` | `3` | Hour of day (UTC, 0–23) at which scheduled subscription expirations are set. Choose an off-peak hour to avoid disrupting incoming notifications |
| `MICROSOFT_WEBHOOK_SECRET` | (required) | Secret sent as the subscription `clientState` and validated on every incoming notification |
| `SELF_URL` / `MICROSOFT_PUBLIC_WEBHOOK_URL` | `SELF_URL` | Public URL Microsoft Graph posts notifications to |

For the full Teams MCP variable reference, including the variables that are shared with chat-only deployments, see [Teams MCP - Configuration](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1802338327/Teams+MCP+-+Configuration).

### Example Helm values

```yaml
mcpConfig:
  unique:
    integration: enabled
    serviceAuthMode: cluster_local
    apiBaseUrl: http://api-gateway.unique:8080
    apiVersion: "2023-12-06"
    rootScopeId: scope_abc123xyz # must equal RECORDING_KB_SCOPE_ID
    userFetchConcurrency: 5
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    serviceExtraHeaders:
      x-company-id: "<your-company-id>"
      x-user-id: "<your-service-account-user-id>"
```

For deployments outside the Unique cluster, use `serviceAuthMode: external` with an API key:

```yaml
mcpConfig:
  unique:
    serviceAuthMode: external
    apiBaseUrl: https://api.unique.app
    serviceExtraHeaders:
      authorization: "Bearer <api-key>"
      x-app-id: "app-id"
      x-user-id: "user-id"
      x-company-id: "company-id"
```

## Zitadel service account

### Why it is required

Ingestion happens on behalf of the server, not the end user, so the Teams MCP Server needs its own identity against the Unique Public API. The service account is used to:

1. **Resolve participants** — look up meeting attendees in Unique by email or username
2. **Create scopes** — create the folder structure that holds each meeting
3. **Set access permissions** — grant the organiser and participants their access
4. **Upload content** — write the transcript and recording into the knowledge base

Credentials are passed as the `x-company-id` and `x-user-id` headers on every API request.

### Creating the service account

1. **Log in to Zitadel** and select the organisation where meetings should be ingested
2. **Create the service account** — under **Service Accounts**, click **New Service Account** and give it a descriptive name (e.g. "Teams MCP Server Service Account")
3. **Note the identifiers** — the organisation ID becomes `x-company-id`, the service account user ID becomes `x-user-id`
4. **Configure the headers** in `mcpConfig.unique.serviceExtraHeaders` as shown above

### Required roles

The Unique Public API authorises each request against the Zitadel roles of the calling identity. Grant both of the following roles to the service account in the target organisation:

| Role | Why it is required |
|------|--------------------|
| `chat.admin.all` | **Mandatory.** The only role accepted when updating a scope (setting its `externalId`/name, `PATCH /folder/{id}`) — there is no alternative. It also covers creating scope access (`PATCH /folder/add-access`), upserting content (`POST /content/upsert`), and resolving participants (`GET /users`) |
| `chat.knowledge.read` | **Mandatory.** Required to query existing content (`POST /content/infos`), which the server uses to deduplicate and list already-ingested meetings. `chat.admin.all` is **not** accepted by this endpoint, so this role must be granted in addition |

Each operation maps to a downstream role check as follows:

| Operation | Endpoint | Accepted roles |
|-----------|----------|----------------|
| Resolve meeting participant | `GET /users` | `chat.admin.all`, `admin.space.write`, `chat.knowledge.write` |
| Create meeting scope | `POST /folder` | Service-identity only (no user role required) |
| Grant participant scope access | `PATCH /folder/add-access` | `chat.admin.all`, `chat.knowledge.write` |
| Set scope `externalId` / name | `PATCH /folder/{id}` | `chat.admin.all` **only** |
| Upsert transcript / recording content | `POST /content/upsert` | `chat.admin.all`, `chat.knowledge.write` |
| Query existing content | `POST /content/infos` | `chat.knowledge.read`, `admin.space.write` |
| Search content | `POST /search/search` | None (header auth only) |
| Upload blob | `PUT /scoped/upload` | None (secured by encrypted key) |

!!! note "Participants need their own roles"
    When the server grants scope access to a meeting participant, Unique additionally requires that *participant's* own Zitadel account to already hold `chat.knowledge.write` (or `chat.admin.all`) for write access, or `chat.knowledge.read` for read access. A participant with no roles assigned in Zitadel is rejected. This is a property of the users being granted access, not of the service account.

!!! note "Role enforcement toggle"
    Downstream role checks are only enforced when `unique-api` runs with `ENABLE_ROLE_AUTHORIZATION=true` (the platform default). When disabled, `unique-api` calls downstream services with a service identity that bypasses these checks, and the roles above are not required.

## Root scope

### Why it is required

All meetings are ingested as child scopes under one root scope (folder), giving a single organisational entry point for Teams content and one place to manage its permissions and visibility. The Recordings area in Unique reads from exactly this scope.

### Creating the root scope

The root scope must be created **manually** in the Unique platform before deploying — there is no automated provisioning for this step.

1. **Log in to the Unique platform** as an administrator
2. **Create a new top-level scope (folder)** with a descriptive name (e.g. "Teams Recordings") and note its ID — it starts with `scope_`
3. **Grant the service account access** — give the Zitadel service account `MANAGE`, `READ`, and `WRITE` on the root scope. This is a required manual step: the server cannot provision access on a scope it has no rights to
4. **Configure both systems** with the scope ID — `UNIQUE_ROOT_SCOPE_ID` on Teams MCP and `RECORDING_KB_SCOPE_ID` on the platform

On startup the server re-issues these three grants for its service user against the configured root scope. The call is additive, so re-affirming existing access on every boot is safe. If it is rejected — a wrong or missing scope ID, or a service account that was never granted management of the scope — the pod **hard-fails at boot** rather than surfacing the error mid-ingestion. Look for `root scope <id> permission bootstrap failed` in the startup logs.

!!! warning "One scope per environment"
    Each environment (QA, production, …) requires its own root scope. Do not reuse a scope ID across environments.

## Enable the Recordings area in Unique

The UI is gated by a feature flag and needs to know which scope to read from.

| Setting | Required | Description |
|---|---|---|
| `FEATURE_FLAG_ENABLE_RECORDING_UN_19218` | Yes | Unlocks the Recordings area: list, detail, participants, reports, and sharing. Disabled by default; while it is off, the navigation entry is hidden and the route redirects away |
| `RECORDING_KB_SCOPE_ID` | Yes | The knowledge-base scope the Recordings area reads from. **Must be the same value as `UNIQUE_ROOT_SCOPE_ID`** on the Teams MCP Server. The application fails to start if the flag is on and this is unset |
| `RECORDING_CHAT_SPACE_ID` | No | The assistant space used by the **Open chat** action on the recording detail view. Without it, users can still browse and play recordings |

!!! important "The two scope IDs must match"
    If `RECORDING_KB_SCOPE_ID` and `UNIQUE_ROOT_SCOPE_ID` differ, ingestion will succeed and the Recordings area will stay permanently empty — with no error anywhere. Verify both values whenever the list is unexpectedly empty.

For Unique SaaS deployments, Unique applies the flag and both settings for you; confirm the root scope with your Unique contact.

## Enablement checklist

1. **Knowledge base**
    - [ ] Root scope created in Unique, scope ID noted
    - [ ] Zitadel service account created with `chat.admin.all` and `chat.knowledge.read`
    - [ ] Service account granted `MANAGE`, `READ`, `WRITE` on the root scope
2. **Microsoft Entra ID**
    - [ ] The four Microsoft Graph permissions in [Grant admin consent](#Grant-admin-consent) added
    - [ ] Admin consent granted — see [Grant admin consent](#Grant-admin-consent)
    - [ ] Teams meeting policy has transcription enabled
3. **Teams meeting settings** (Unique cannot set this via OAuth)
    - [ ] Microsoft Graph transcript access enabled (`EnableGraphTranscriptAccess`) — see [Teams Graph transcript API access](#Teams-Graph-transcript-API-access)
    - [ ] Speaker attribution enabled (`EnableAttributedTranscripts`) — recommended; Unique expects attributed VTT
4. **Teams MCP Server**
    - [ ] RabbitMQ reachable
    - [ ] `UNIQUE_INTEGRATION=enabled` with the Unique API and service header values set
    - [ ] `UNIQUE_ROOT_SCOPE_ID` set to the root scope
    - [ ] Pod starts without `root scope … permission bootstrap failed`
5. **Unique platform**
    - [ ] `FEATURE_FLAG_ENABLE_RECORDING_UN_19218` enabled
    - [ ] `RECORDING_KB_SCOPE_ID` equals `UNIQUE_ROOT_SCOPE_ID`
    - [ ] `RECORDING_CHAT_SPACE_ID` set if the **Open chat** action is wanted
6. **Verification**
    - [ ] A test user connects and calls `start_kb_integration`, then `verify_kb_integration_status` reports `active`
    - [ ] A recorded, transcribed test meeting appears in the knowledge base under the root scope
    - [ ] The same meeting appears in the Recordings area, plays back, and shows its transcript

## Troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| Recordings area is not in the navigation | Feature flag off | `FEATURE_FLAG_ENABLE_RECORDING_UN_19218` |
| Recordings area is empty, but content exists in the knowledge base | Scope mismatch | `RECORDING_KB_SCOPE_ID` versus `UNIQUE_ROOT_SCOPE_ID` |
| `start_kb_integration` / renewal / transcript fetch returns 403 | Graph transcript API access off | `EnableGraphTranscriptAccess` — see [Teams Graph transcript API access](#Teams-Graph-transcript-API-access); re-consent will not fix this |
| Nothing is captured at all | No active subscription | `verify_kb_integration_status`; call `start_kb_integration`, or enable `UNIQUE_AUTO_START_INGESTION` |
| Nothing is captured for one user | That user never enabled ingestion, or their token expired | Have the user reconnect, then call `start_kb_integration` |
| Capture stopped after a few days | Subscription renewal failed | Logs for `subscription_renewal_failed`; see [Subscription failure handling](./technical.md#subscription-failure-handling). If the error is `GraphAccessToTranscriptsDisabled`, fix the Teams toggle first |
| Meeting appears without video | Meeting was not recorded, or the recording download timed out | Ingestion logs for the recording step; the transcript is captured either way |
| Transcript present, participants have no access | Participants do not resolve to Unique accounts, or lack Zitadel roles | Participant emails against Unique accounts; see the participant roles note above |
| Pod fails to start | Root scope missing or service account lacks access on it | `root scope … permission bootstrap failed` in the startup logs |
| Meetings stop being captured for everyone | Webhook secret changed | Rotating `MICROSOFT_WEBHOOK_SECRET` invalidates every existing subscription — see the [FAQ](./faq.md#what-happens-if-the-webhook-secret-changes) |

## Related Documentation

- [Recordings & Transcripts](./README.md) — what the feature is and who it is for
- [Technical Manual](./technical.md) — architecture, ingestion pipeline, subscription lifecycle, and tools
- [FAQ](./faq.md) — frequently asked questions
- [Teams MCP - Operator Manual](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1801683279/Teams+MCP+-+Operator+Manual) — deploying and operating the server itself
- [Teams MCP - Configuration](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1802338327/Teams+MCP+-+Configuration) — the full environment variable reference
- [Teams MCP - Authentication](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1803026436/Teams+MCP+-+Authentication) — Entra ID app registration and admin consent
