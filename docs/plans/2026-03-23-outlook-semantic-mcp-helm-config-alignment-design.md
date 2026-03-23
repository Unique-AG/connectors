# Design: Helm Config Alignment for outlook-semantic-mcp

## Problem

`templates/config.yaml` is a monolith that is hard to trace back to `src/config` domains. Several env vars defined in `src/config` are missing from `values.yaml` (`BUFFER_LOGS`, `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC`, `UNIQUE_STORE_INTERNALLY`). Optional fields (those with zod `default`/`prefault`) are always rendered in the ConfigMap, silently overriding zod defaults. `.env.example` has 5 stale entries and multiple missing ones.

## Solution

### Overview

Three parallel changes with no breaking Kubernetes surface area — the single ConfigMap `{fullname}-config` is preserved.

1. **Template restructuring:** Move each config domain's logic into a `_`-prefixed named template partial (`.tpl`). `config.yaml` becomes a thin orchestrator that includes them all. One ConfigMap in Kubernetes, as today.

2. **values.yaml alignment:** Add the 3 missing fields. Set optional fields (those with zod `default`/`prefault`) to `null` — templates guard them with `{{- if ... }}` so the env var is only emitted when the operator explicitly provides a value, letting zod defaults apply naturally.

3. **.env.example cleanup:** Remove stale entries, add all missing vars with documentation matching zod descriptions.

### Architecture

**Template files — new layout:**

```
templates/
  _config-app.tpl        # defines chart.config.app
  _config-auth.tpl       # defines chart.config.auth
  _config-logs.tpl       # defines chart.config.logs
  _config-microsoft.tpl  # defines chart.config.microsoft
  _config-unique.tpl     # defines chart.config.unique
  config.yaml            # single ConfigMap, includes all partials
  _helpers.tpl           # unchanged
  ...
```

**`config.yaml` shape after refactor:**

```yaml
{{- if .Values.mcpConfig.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "chart.fullname" . }}-config
  labels:
    {{- include "chart.labels" . | nindent 4 }}
data:
  {{- include "chart.config.app" . | nindent 2 }}
  {{- include "chart.config.auth" . | nindent 2 }}
  {{- include "chart.config.logs" . | nindent 2 }}
  {{- include "chart.config.microsoft" . | nindent 2 }}
  {{- include "chart.config.unique" . | nindent 2 }}
{{- end }}
```

**Env var inventory by partial:**

| Partial | Env Var | Required? | Guard |
|---|---|---|---|
| `chart.config.app` | `SELF_URL` | yes | always emitted |
| `chart.config.app` | `DEFAULT_MAIL_FILTERS` | yes | always emitted |
| `chart.config.app` | `MCP_DEBUG_MODE` | no | `{{- if .Values.mcpConfig.app.mcpDebugMode }}` |
| `chart.config.app` | `BUFFER_LOGS` | no | `{{- if .Values.mcpConfig.app.bufferLogs }}` |
| `chart.config.auth` | `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` | no | `{{- if .Values.mcpConfig.auth.accessTokenExpiresInSeconds }}` |
| `chart.config.auth` | `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` | no | `{{- if .Values.mcpConfig.auth.refreshTokenExpiresInSeconds }}` |
| `chart.config.logs` | `LOGS_DIAGNOSTICS_DATA_POLICY` | no | `{{- if .Values.mcpConfig.logs.diagnosticsDataPolicy }}` |
| `chart.config.microsoft` | `MICROSOFT_CLIENT_ID` | yes | always emitted |
| `chart.config.microsoft` | `MICROSOFT_PUBLIC_WEBHOOK_URL` | no | `{{- if .Values.mcpConfig.microsoft.publicWebhookUrl }}` |
| `chart.config.microsoft` | `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` | no | `{{- if not (kindIs "invalid" ...) }}` (0 is valid) |
| `chart.config.unique` | `UNIQUE_SERVICE_AUTH_MODE` | yes | always emitted |
| `chart.config.unique` | `UNIQUE_INGESTION_SERVICE_BASE_URL` | yes | always emitted |
| `chart.config.unique` | `UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL` | yes | always emitted |
| `chart.config.unique` | `UNIQUE_STORE_INTERNALLY` | no | `{{- if .Values.mcpConfig.unique.storeInternally }}` |
| `chart.config.unique` | `UNIQUE_SERVICE_EXTRA_HEADERS` | cluster_local | `{{- if eq ... "cluster_local" }}` |
| `chart.config.unique` | `UNIQUE_ZITADEL_CLIENT_ID` | external | `{{- if eq ... "external" }}` |
| `chart.config.unique` | `UNIQUE_ZITADEL_OAUTH_TOKEN_URL` | external | `{{- if eq ... "external" }}` |
| `chart.config.unique` | `UNIQUE_ZITADEL_PROJECT_ID` | external | `{{- if eq ... "external" }}` |

Note: `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` uses `kindIs "invalid"` nil check because `0` (midnight UTC) is a valid value and would be skipped by a plain `{{- if ... }}`.

**values.yaml `mcpConfig` changes:**

| Field | Before | After | Reason |
|---|---|---|---|
| `app.bufferLogs` | missing | `null` | new field, zod optional |
| `app.mcpDebugMode` | `disabled` | `null` | zod has default |
| `auth.accessTokenExpiresInSeconds` | `60` | `null` | zod default: 60 |
| `auth.refreshTokenExpiresInSeconds` | `2592000` | `null` | zod default: 2592000 |
| `logs.diagnosticsDataPolicy` | `conceal` | `null` | zod prefault: conceal |
| `microsoft.subscriptionExpirationTimeHoursUTC` | missing | `null` | new field, zod default: 3 |
| `unique.storeInternally` | missing | `null` | new field, zod optional |

**.env.example changes:**

Remove (no longer in any config file):
- `UNIQUE_API_BASE_URL`
- `UNIQUE_SERVICE_ID`
- `UNIQUE_API_VERSION`
- `UNIQUE_ROOT_SCOPE_PATH`
- `UNIQUE_USER_FETCH_CONCURRENCY`

Add (present in config files, missing from .env.example):
- `MCP_DEBUG_MODE`
- `BUFFER_LOGS`
- `LOGS_DIAGNOSTICS_DATA_POLICY`
- `UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL`
- `UNIQUE_STORE_INTERNALLY`
- `UNIQUE_ZITADEL_OAUTH_TOKEN_URL`
- `UNIQUE_ZITADEL_CLIENT_ID`
- `UNIQUE_ZITADEL_CLIENT_SECRET`
- `UNIQUE_ZITADEL_PROJECT_ID`

### Error Handling

No runtime error handling applies. Misconfigured optional fields (e.g. wrong format) are caught by zod on startup. Required fields left as `unset_default_value` in values.yaml will cause zod startup failure — this is intentional and already the pattern in the chart.

### Testing Strategy

No automated tests. Validate by running `helm template` against the updated chart and diffing the rendered ConfigMap against the expected env vars from `src/config`. Manual review is sufficient given the purely declarative nature of the change.

## Out of Scope

- Splitting into multiple Kubernetes ConfigMaps.
- Adding Helm schema validation (`values.schema.json`) for required fields.
- Any changes to `src/config` TypeScript files.
- OTEL env vars in `.env.example` (already present and correct).

## Tasks

1. **Create `_config-app.tpl`** — Define `chart.config.app` named template with `SELF_URL`, `DEFAULT_MAIL_FILTERS` (always emitted) and `MCP_DEBUG_MODE`, `BUFFER_LOGS` (guarded).

2. **Create `_config-auth.tpl`** — Define `chart.config.auth` named template with `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` and `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS`, both guarded.

3. **Create `_config-logs.tpl`** — Define `chart.config.logs` named template with `LOGS_DIAGNOSTICS_DATA_POLICY`, guarded.

4. **Create `_config-microsoft.tpl`** — Define `chart.config.microsoft` named template with `MICROSOFT_CLIENT_ID` (always), `MICROSOFT_PUBLIC_WEBHOOK_URL` (guarded), `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` (kindIs nil guard).

5. **Create `_config-unique.tpl`** — Define `chart.config.unique` named template with required fields always emitted, `UNIQUE_STORE_INTERNALLY` guarded, and the existing cluster_local / external conditional blocks.

6. **Refactor `config.yaml`** — Replace the monolithic `data:` block with five `{{- include ... | nindent 2 }}` calls.

7. **Update `values.yaml`** — Add `bufferLogs`, `subscriptionExpirationTimeHoursUTC`, `storeInternally`; set optional fields to `null`; update comments.

8. **Clean up `.env.example`** — Remove 5 stale entries, add 9 missing entries with comments matching zod field descriptions.
