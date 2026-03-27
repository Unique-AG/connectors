<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

## Overview

The Confluence Connector authenticates in two directions:

1. **Confluence authentication** -- to read pages and attachments from Confluence Cloud or Data Center.
2. **Unique platform authentication** -- to ingest content into the Unique knowledge base.

This guide covers both authentication paths, including credential setup, secret management, and token flows.

## Confluence Authentication Methods

| Instance Type | Auth Method | Config Value (`auth.mode`) | Description |
|---|---|---|---|
| **Cloud** | OAuth 2.0 (2LO) | `oauth_2lo` | Client credentials flow via `https://api.atlassian.com/oauth/token` |
| **Data Center** | OAuth 2.0 (2LO) | `oauth_2lo` | Client credentials flow via `{baseUrl}/rest/oauth2/latest/token` |
| **Data Center** (below 10.1) | Personal Access Token | `pat` | Static token-based authentication (not recommended; use OAuth 2.0 2LO on Data Center 10.1+) |

- Confluence Cloud supports **only** OAuth 2.0 two-legged (2LO).
- Confluence Data Center 10.1+ supports **both** OAuth 2.0 (2LO) and Personal Access Token (PAT). OAuth 2.0 (2LO) is recommended.
- Confluence Data Center below 10.1 must use **Personal Access Token (PAT)**, as OAuth 2.0 (2LO) is not available on those versions.

## Unique Platform Authentication Methods

The connector's tenant YAML field for selecting the Unique auth mode is `serviceAuthMode` (not `authMode`).

> **Note:** The Helm chart `values.yaml` uses `unique.authMode`, which the Helm template maps to `serviceAuthMode` in the generated tenant config YAML.

| Auth Mode | Config Value (`serviceAuthMode`) | Description |
|---|---|---|
| **Cluster-local** | `cluster_local` | For connectors running in the same Kubernetes cluster as Unique. Uses service headers (`x-company-id`, `x-user-id`) instead of OAuth tokens. |
| **External** | `external` | For connectors running outside the cluster. Authenticates via Zitadel OAuth client credentials. |

## Setup Steps

### 1. Create a Unique Service User

The connector requires a service user in the Unique platform (Zitadel) with the following permissions:

| Permission | Purpose |
|------------|---------|
| `chat.admin.all` | Scope management (create child scopes, grant access, set external IDs) |
| `chat.knowledge.read` | Read knowledge base content (file diff, file queries) |
| `chat.knowledge.write` | Write knowledge base content (ingestion, file deletion) |

This user identity is referenced:

- In `cluster_local` mode: as the `x-user-id` header value in `serviceExtraHeaders`. This **must** be the ID of an actual service user in Zitadel -- it cannot be an arbitrary value.
- In `external` mode: implicitly via the Zitadel client credentials (`zitadelClientId` / `zitadelClientSecret`).

Steps:

1. Navigate to Zitadel.
2. Create a new service user.
3. Assign the required permissions listed above.
4. Note the user ID for configuration.

For detailed instructions on creating and configuring a service user, see:
- [How To Configure A Service User](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1411023075/How+To+Configure+A+Service+User)
- [Understand Roles and Permissions](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1411023168)

### 2. Create the Root Scope in Unique

The connector requires a pre-existing root scope in Unique. The root scope ID is configured in the tenant YAML under `ingestion.scopeId`. If the scope does not exist at startup, the connector fails with an assertion error.

At startup, the connector automatically grants itself access on the root scope and will create child scopes for each Confluence space that has content to ingest. See the [Scope Management](../technical/README.md#scope-management) concept and the [scope mechanics](../technical/flows.md#scope-management) for details on access inheritance, external IDs, and parent scope traversal.

### 3. Set Up Confluence Authentication

#### Option A: OAuth 2.0 (2LO) -- Cloud

1. In the [Atlassian Admin Console](https://admin.atlassian.com/), go to **Settings** > **User Management** > **Service Accounts**.
2. Create a new service account and generate credentials.
3. Grant the service account access to the Confluence application and assign the following scopes:

> **Note:** The scopes listed below are preliminary and subject to validation. The minimum required set may change before the stable release.

| Scope | Purpose |
|-------|---------|
| `search:confluence` | CQL search for labeled pages |
| `read:confluence-content.all` | Read full page content (body, metadata) |
| `read:confluence-content.summary` | Read content summaries and version info |
| `read:confluence-space.summary` | Read space metadata (key, name, type) |
| `read:label:confluence` | Read page labels to determine sync eligibility |
| `read:page:confluence` | Read individual pages |
| `read:attachment:confluence` | Download file attachments (required when attachment ingestion is enabled) |

4. Note the **Client ID** and **Client Secret**.
5. Obtain the **Cloud ID** for your Confluence instance (see [How do I find my Atlassian Cloud ID?](../faq.md#how-do-i-find-my-atlassian-cloud-id)).

**Required tenant YAML fields:**

```yaml
confluence:
  instanceType: cloud
  baseUrl: https://your-domain.atlassian.net
  cloudId: your-cloud-id
  auth:
    mode: oauth_2lo
    clientId: your-oauth-client-id
    clientSecret: os.environ/CONFLUENCE_CLIENT_SECRET
```

The `clientSecret` field uses the `os.environ/` prefix to resolve the value from an environment variable at runtime (see [Secret Resolution](#secret-resolution)).

#### Option B: OAuth 2.0 (2LO) -- Data Center

1. In the [Atlassian Admin Console](https://admin.atlassian.com/), go to **Settings** > **User Management** > **Service Accounts**.
2. Create a new service account and generate credentials.
3. Grant the service account access to the Confluence application and assign the following scopes:

> **Note:** The scopes listed below are preliminary and subject to validation. The minimum required set may change before the stable release.

| Scope | Purpose |
|-------|---------|
| `search:confluence` | CQL search for labeled pages |
| `read:confluence-content.all` | Read full page content (body, metadata) |
| `read:confluence-content.summary` | Read content summaries and version info |
| `read:confluence-space.summary` | Read space metadata (key, name, type) |
| `read:label:confluence` | Read page labels to determine sync eligibility |
| `read:page:confluence` | Read individual pages |
| `read:attachment:confluence` | Download file attachments (required when attachment ingestion is enabled) |

4. Note the **Client ID** and **Client Secret**.

**Required tenant YAML fields:**

```yaml
confluence:
  instanceType: data-center
  baseUrl: https://confluence.your-company.com
  auth:
    mode: oauth_2lo
    clientId: your-confluence-app-client-id
    clientSecret: os.environ/CONFLUENCE_CLIENT_SECRET
```

#### Option C: Personal Access Token -- Data Center Below 10.1 Only (Not Recommended)

> **Note:** PATs are not recommended. Use OAuth 2.0 (2LO) on Data Center 10.1+ instead. PATs are static tokens that do not expire automatically and must be manually rotated. Only use this option on Data Center versions below 10.1 where OAuth 2.0 (2LO) is not available.

1. In Confluence Data Center, go to **Profile** > **Personal Access Tokens**.
2. Create a new token (the token inherits the creating user's permissions).
3. Note the generated token value.

**Required tenant YAML fields:**

```yaml
confluence:
  instanceType: data-center
  baseUrl: https://confluence.your-company.com
  auth:
    mode: pat
    token: os.environ/CONFLUENCE_PAT
```

The `token` field uses the `os.environ/` prefix to resolve the value from an environment variable at runtime (see [Secret Resolution](#secret-resolution)).

### 4. Set Up Unique Platform Authentication

#### Option A: Cluster-Local

Use this mode when the connector is deployed in the same Kubernetes cluster as the Unique platform.

**Required tenant YAML fields:**

```yaml
unique:
  serviceAuthMode: cluster_local
  serviceExtraHeaders:
    x-company-id: your-company-id
    x-user-id: your-user-id
  ingestionServiceBaseUrl: http://node-ingestion.<namespace>:8091
  scopeManagementServiceBaseUrl: http://node-scope-management.<namespace>:8094
```

| Header | Description |
|---|---|
| `x-company-id` | The company ID in the Unique platform |
| `x-user-id` | The user ID of the service user in Zitadel. Must be an actual service user -- not an arbitrary value. |

Both headers are validated at config load time. The schema requires that `serviceExtraHeaders` contains both `x-company-id` and `x-user-id`.

#### Option B: External (Zitadel)

Use this mode when the connector is deployed outside the Unique platform's Kubernetes cluster.

**Required tenant YAML fields:**

```yaml
unique:
  serviceAuthMode: external
  zitadelOauthTokenUrl: https://auth.your-unique-instance.com/oauth/v2/token
  zitadelProjectId: your-zitadel-project-id
  zitadelClientId: confluence-connector
  zitadelClientSecret: os.environ/ZITADEL_CLIENT_SECRET
  ingestionServiceBaseUrl: https://ingestion.your-unique-instance.com
  scopeManagementServiceBaseUrl: https://scope-management.your-unique-instance.com
```

| Field | Description |
|---|---|
| `zitadelOauthTokenUrl` | Zitadel OAuth token endpoint URL |
| `zitadelProjectId` | Zitadel project ID (resolved via `os.environ/` if prefixed) |
| `zitadelClientId` | Zitadel client ID for the connector's service user |
| `zitadelClientSecret` | Zitadel client secret (resolved via `os.environ/` if prefixed) |

## Secret Resolution

Secret fields in the tenant YAML support the `os.environ/ENV_VAR_NAME` format to resolve values from environment variables at runtime:

```
os.environ/ENV_VAR_NAME
```

If the referenced environment variable is not set or is empty, startup fails with a validation error. Secret values are automatically redacted in logs.

**Fields that support `os.environ/` resolution:**

| Field | Example Environment Variable |
|---|---|
| `confluence.auth.clientSecret` | `CONFLUENCE_CLIENT_SECRET` |
| `confluence.auth.token` (PAT) | `CONFLUENCE_PAT` |
| `unique.zitadelClientSecret` | `ZITADEL_CLIENT_SECRET` |
| `unique.zitadelProjectId` | `ZITADEL_PROJECT_ID` |

### Providing Secrets in Kubernetes

Use Kubernetes Secrets to inject environment variables into the connector pod. The Helm chart supports this via the `connector.envVars` field in `values.yaml`:

```yaml
connector:
  envVars:
    - name: CONFLUENCE_CLIENT_SECRET
      valueFrom:
        secretKeyRef:
          name: confluence-connector-secret
          key: CONFLUENCE_CLIENT_SECRET
    - name: ZITADEL_CLIENT_SECRET
      valueFrom:
        secretKeyRef:
          name: confluence-connector-secret
          key: ZITADEL_CLIENT_SECRET
```

## Secret Rotation

The connector uses three types of secrets. All must be stored in Kubernetes Secrets (not ConfigMaps).

| Secret | Used By | Purpose |
|--------|---------|---------|
| OAuth 2.0 client secret | Confluence Cloud and Data Center | Authenticates the connector to the Confluence OAuth token endpoint |
| Personal Access Token | Confluence Data Center < 10.1 only | Static bearer token for API requests (not recommended) |
| Zitadel client secret | Unique platform (`external` mode only) | Authenticates the connector to the Unique platform via Zitadel OAuth |

### OAuth 2.0 Client Secret (Confluence)

The client secret from the Atlassian service account. The connector uses it to obtain access tokens via the client credentials grant.

**What happens if it expires or is revoked:** All Confluence API requests fail once the cached token expires. No new tokens can be acquired. The sync cycle stops producing results until the secret is replaced.

**How to rotate:**

1. Generate a new client secret in the Atlassian Admin Console for the service account
2. Update the Kubernetes Secret with the new value
3. Restart the connector pods to pick up the new secret
4. Verify the connector logs show successful token acquisition

### Personal Access Token (Data Center < 10.1 only)

A static bearer token associated with a Confluence Data Center user account.

**What happens if it expires or is revoked:** All Confluence API requests immediately return `401 Unauthorized`. The sync cycle stops.

**How to rotate:**

1. Generate a new PAT in Confluence Data Center (**Profile** > **Personal Access Tokens**)
2. Update the Kubernetes Secret with the new value
3. Restart the connector pods
4. Verify the connector logs show successful API requests

> **Note:** PATs do not expire automatically unless an expiration date was set at creation time. However, they can be revoked at any time by the user or an administrator.

### Zitadel Client Secret (External Mode)

The client secret for the connector's Zitadel service account. Used only when `serviceAuthMode: external`.

**What happens if it expires or is revoked:** All requests to the Unique Ingestion and Scope Management services fail. Content is read from Confluence but cannot be ingested into the Unique knowledge base.

**How to rotate:**

1. Generate a new client secret in Zitadel for the connector's service user
2. Update the Kubernetes Secret with the new value
3. Restart the connector pods
4. Verify the connector logs show successful Zitadel token acquisition

### Best Practices

- **Rotate before expiration** — create the new secret before the old one expires to avoid downtime
- **Use Kubernetes Secrets or a secret manager** — never store secrets in ConfigMaps or plain text
- **Monitor for authentication failures** — failed token acquisition is logged and indicates an expired or revoked secret
- **Document rotation procedures** — include secret rotation in your operational runbook

## Helm Chart Field Mapping

The Helm chart `values.yaml` uses `unique.authMode`, which the Helm template maps to `serviceAuthMode` in the generated tenant config. The following table shows how Helm values map to the actual tenant config fields:

| Helm `values.yaml` Field | Tenant Config YAML Field |
|---|---|
| `unique.authMode` | `unique.serviceAuthMode` |
| `unique.zitadel.oauthTokenUrl` | `unique.zitadelOauthTokenUrl` |
| `unique.zitadel.projectId` | `unique.zitadelProjectId` |
| `unique.zitadel.clientId` | `unique.zitadelClientId` |
| (hardcoded in template) | `unique.zitadelClientSecret: "os.environ/ZITADEL_CLIENT_SECRET"` |
| `unique.serviceExtraHeaders` | `unique.serviceExtraHeaders` |

## Token Flows

### Confluence Cloud OAuth 2.0 (2LO)

```mermaid
sequenceDiagram
    participant Connector
    participant Atlassian as Atlassian OAuth<br/>(api.atlassian.com)
    participant Confluence as Confluence Cloud API<br/>(api.atlassian.com)

    Connector->>Atlassian: POST /oauth/token<br/>Content-Type: application/json<br/>(client_id, client_secret, grant_type=client_credentials)
    Atlassian->>Connector: access_token, expires_in

    Connector->>Confluence: GET /ex/confluence/{cloudId}/...<br/>Authorization: Bearer {token}
    Confluence->>Connector: API response
```

**Token endpoint:** `https://api.atlassian.com/oauth/token`

**Request format:** JSON body with `grant_type`, `client_id`, `client_secret`.

### Confluence Data Center OAuth 2.0 (2LO)

```mermaid
sequenceDiagram
    participant Connector
    participant DC as Confluence Data Center

    Connector->>DC: POST {baseUrl}/rest/oauth2/latest/token<br/>Content-Type: application/x-www-form-urlencoded<br/>(client_id, client_secret, grant_type=client_credentials, scope=READ)
    DC->>Connector: access_token, expires_in

    Connector->>DC: GET {baseUrl}/rest/api/...<br/>Authorization: Bearer {token}
    DC->>Connector: API response
```

**Token endpoint:** `{baseUrl}/rest/oauth2/latest/token`

**Request format:** URL-encoded form body with `grant_type`, `client_id`, `client_secret`, and `scope=READ`.

### Confluence Data Center PAT

No token exchange is required. The PAT is sent directly as a `Bearer` token in the `Authorization` header on every API request.

### Token Caching

OAuth 2.0 tokens are cached in memory and automatically refreshed before expiry. PAT tokens are not cached (the static token is sent directly on every request).

## Hosting Models

### Self-Hosted (SH)

Client hosts the connector and manages Confluence authentication credentials:

```mermaid
flowchart LR
    subgraph Client["Client Infrastructure"]
        Connector["Confluence Connector"]
    end

    subgraph Atlassian["Atlassian Cloud / Data Center"]
        ConfluenceAPI["Confluence API"]
        AtlassianAuth["Atlassian OAuth"]
    end

    subgraph Unique["Unique Platform"]
        IngestionSvc["Ingestion Service"]
        ScopeMgmt["Scope Management"]
    end

    Connector -->|"OAuth2 / PAT"| AtlassianAuth
    Connector -->|"HTTPS"| ConfluenceAPI
    Connector -->|"HTTPS"| IngestionSvc
    Connector -->|"HTTPS"| ScopeMgmt
```

| Aspect | Responsibility |
|--------|---------------|
| Connector hosting | Client |
| Confluence service account or PAT (PAT only for DC < 10.1; not recommended) | Client |
| Unique deliverable | Container image, Helm chart, documentation |

### Single-Tenant: Client-Hosted

Client uses Unique Single Tenant but hosts the connector:

- Suitable for on-premise Confluence Data Center deployments
- Client manages the connector and Confluence credentials
- Connector connects to Unique via external API (`serviceAuthMode: external`)

### Single-Tenant: Unique-Hosted

Unique hosts the connector on behalf of the client:

- Client creates the service account in their own Atlassian Admin Console and provides the credentials (client ID and client secret) to Unique
- Client provides their Confluence instance details (Cloud ID, base URL, label configuration)
- For Data Center below 10.1: client provides a PAT instead (not recommended)

### Multi-Tenant: Unique-Hosted

Unique hosts a single connector deployment serving multiple tenants:

- Each tenant is configured via a separate tenant YAML file
- Each tenant has its own Confluence instance, credentials, and Unique platform endpoints
- Tenants are isolated at the configuration level (separate scopes, separate sync schedules, separate credentials)
- The connector processes all tenants within a single pod

**Customer onboarding:**

1. Create a new tenant YAML file with the customer's Confluence instance details, credentials, and Unique platform endpoints
2. Mount the file into the connector pod via the tenant config ConfigMap
3. Restart the connector to pick up the new tenant

**Data isolation:** Each tenant has its own root scope and child scopes in the Unique knowledge base. Content from different tenants is never mixed. Credentials are per-tenant and resolved from separate environment variables.

**Compliance:** Some organizations may require dedicated infrastructure for data residency. In that case, deploy a separate connector instance with single-tenant configuration instead.

## Configuration Summary

### Confluence Configuration Fields

| Field | Required | Auth Mode | Type | Description |
|---|---|---|---|---|
| `confluence.auth.mode` | Yes | All | `oauth_2lo` or `pat` | Authentication method |
| `confluence.auth.clientId` | Yes | `oauth_2lo` | String | OAuth 2.0 application client ID |
| `confluence.auth.clientSecret` | Yes | `oauth_2lo` | String (`os.environ/` supported) | OAuth 2.0 client secret |
| `confluence.auth.token` | Yes | `pat` | String (`os.environ/` supported) | Personal Access Token |
| `confluence.cloudId` | Yes | Cloud only | String | Atlassian Cloud ID (UUID) |
| `confluence.baseUrl` | Yes | All | URL | Confluence instance base URL (no trailing slash) |
| `confluence.ingestSingleLabel` | Yes | All | String | Label for single-page sync (required, no default) |
| `confluence.ingestAllLabel` | Yes | All | String | Label for all-descendants sync (required, no default) |
| `confluence.apiRateLimitPerMinute` | Yes | All | Number | Number of Confluence API requests allowed per minute (required, no default) |

### Unique Configuration Fields

| Field | Required | Auth Mode | Type | Description |
|---|---|---|---|---|
| `unique.serviceAuthMode` | Yes | All | `cluster_local` or `external` | Unique platform auth mode |
| `unique.serviceExtraHeaders` | Yes | `cluster_local` | Object | Must contain `x-company-id` and `x-user-id` |
| `unique.zitadelOauthTokenUrl` | Yes | `external` | URL | Zitadel OAuth token endpoint |
| `unique.zitadelProjectId` | Yes | `external` | String (`os.environ/` supported) | Zitadel project ID |
| `unique.zitadelClientId` | Yes | `external` | String | Zitadel client ID |
| `unique.zitadelClientSecret` | Yes | `external` | String (`os.environ/` supported) | Zitadel client secret |
| `unique.ingestionServiceBaseUrl` | Yes | All | URL | Unique Ingestion Service URL (no trailing slash) |
| `unique.scopeManagementServiceBaseUrl` | Yes | All | URL | Unique Scope Management Service URL (no trailing slash) |
| `unique.apiRateLimitPerMinute` | No | All | Number | Number of Unique API requests allowed per minute (default: 100) |

## Troubleshooting

### OAuth Token Acquisition Failure

**Symptom:** `Failed to acquire Confluence {instanceType} token via OAuth 2.0 2LO` in logs.

**Causes:**
- Incorrect `clientId` or `clientSecret`
- OAuth application not configured for client credentials grant
- Network connectivity issues to the token endpoint
- For Cloud: incorrect or missing `cloudId`
- For Data Center: incorrect `baseUrl` (the token endpoint is derived as `{baseUrl}/rest/oauth2/latest/token`)

**Resolution:**
1. Verify `clientId` and `clientSecret` are correct
2. Confirm the OAuth application is configured for the client credentials grant type
3. Check network egress to the token endpoint (Cloud: `api.atlassian.com:443`, Data Center: your instance host)
4. Verify the environment variable referenced by `os.environ/` is set and non-empty

### PAT Authentication Failure

**Symptom:** `401 Unauthorized` responses from Confluence Data Center.

**Causes:**
- Token expired or revoked
- The user who created the token lacks read access
- Incorrect environment variable reference

**Resolution:**
1. Verify the PAT is still valid in Confluence Data Center administration
2. Regenerate the token if expired
3. Confirm the environment variable referenced by `os.environ/` is set and non-empty

### Root Scope Assertion Failure

**Symptom:** `Root scope with ID {scopeId} not found` assertion error at startup.

**Cause:** The `ingestion.scopeId` references a scope that does not exist in the Unique platform.

**Resolution:**
1. Create the root scope in the Unique platform before starting the connector
2. Verify the scope ID in the tenant configuration matches the actual scope ID

### Cluster-Local Header Validation Failure

**Symptom:** Config validation error: `serviceExtraHeaders must contain x-company-id and x-user-id headers`.

**Cause:** The `serviceExtraHeaders` object is missing one or both required headers.

**Resolution:**
1. Ensure both `x-company-id` and `x-user-id` are present in `serviceExtraHeaders`
2. The `x-user-id` must be the ID of an actual service user in Zitadel

### TLS Certificate Validation Errors

**Symptom:** `UNABLE_TO_VERIFY_LEAF_SIGNATURE`, `SELF_SIGNED_CERT_IN_CHAIN`, or similar TLS errors when connecting to Confluence or Unique APIs.

**Cause:** The pod's default trust store does not include the CA that signed the endpoint certificates. This typically happens in environments with a corporate proxy that re-signs TLS traffic or a custom PKI.

**Resolution:** Provide a CA bundle via the `NODE_EXTRA_CA_CERTS` environment variable:

```yaml
connector:
  env:
    NODE_EXTRA_CA_CERTS: /app/certs/ca-bundle.pem
```

Mount the PEM file containing the additional CA certificates into the pod and point the variable to its path.

### Secret Resolution Failure

**Symptom:** Config validation fails with an empty string error for a secret field.

**Cause:** The environment variable referenced by `os.environ/VAR_NAME` is not set or is empty.

**Resolution:**
1. Verify the Kubernetes Secret exists and contains the expected key
2. Verify the `envVars` entry in the Helm chart references the correct secret name and key
3. Check that the `os.environ/` prefix in the tenant YAML matches the environment variable name exactly
