{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
Fails the render with an actionable message when a plain `helm install` would otherwise
crash-loop. Without these checks the failure only surfaces as a pydantic ValidationError in pod
logs after CrashLoopBackOff, not at `helm install`/`helm template` time.

The checks run whenever the deployment resolves to production, which includes an unset
`env.APP_ENV`, because production is config.py's own default for `app_env`:
  - PUBLIC_BASE_URL must be set. Unset leaves config.py's `http://localhost:9544` default, which
    `_reject_local_base_url_in_production` rejects.
  - PUBLIC_BASE_URL must not be cleartext. `_reject_cleartext_base_url_in_production` rejects it,
    because the OAuth discovery, authorize and token endpoints are published under it.
  - ENTRA_TENANT_ID and ENTRA_CLIENT_ID must be set. `EntraConfig` gives them no defaults.

Two things stay out of here on purpose. ENTRA_CLIENT_SECRET arrives through `envVars` as a secret
reference, so this helper cannot see its value. The single-tenant rule on ENTRA_TENANT_ID stays in
`EntraConfig._reject_multi_tenant_authority`, the one place the authority aliases are listed.

The cleartext check tests for an `http://` prefix rather than requiring `https://`, so an overlay
that builds the URL from a template expression still renders. config.py remains the backstop.

An `env` value (per the base chart schema) is either a plain string/number/boolean or an
object with a `value` key — either form is unwrapped to its value before being checked, and any
non-empty result counts as "set".
*/}}
{{- define "office-mcp.validateValues" -}}
{{- $env := .Values.env | default dict -}}
{{- $appEnv := index $env "APP_ENV" -}}
{{- if eq (kindOf $appEnv) "map" -}}
{{- $appEnv = index $appEnv "value" -}}
{{- end -}}
{{- $isProduction := or (not $appEnv) (eq (lower (toString $appEnv)) "production") -}}
{{- if $isProduction -}}
{{- $publicBaseUrl := index $env "PUBLIC_BASE_URL" -}}
{{- if eq (kindOf $publicBaseUrl) "map" -}}
{{- $publicBaseUrl = index $publicBaseUrl "value" -}}
{{- end -}}
{{- if not $publicBaseUrl -}}
{{- fail "env.PUBLIC_BASE_URL is required: it is the externally-reachable OAuth issuer URL clients are redirected to. Set it in the overlay." -}}
{{- end -}}
{{- if hasPrefix "http://" (lower (toString $publicBaseUrl)) -}}
{{- fail "env.PUBLIC_BASE_URL must not be cleartext: the OAuth discovery, authorize and token endpoints are published under it, and over http the consent cookies lose their Secure flag. Set an https URL in the overlay." -}}
{{- end -}}
{{- $tenantId := index $env "ENTRA_TENANT_ID" -}}
{{- if eq (kindOf $tenantId) "map" -}}
{{- $tenantId = index $tenantId "value" -}}
{{- end -}}
{{- if not $tenantId -}}
{{- fail "env.ENTRA_TENANT_ID is required: it is the single tenant whose issuer every access token is validated against. Set it in the overlay." -}}
{{- end -}}
{{- $clientId := index $env "ENTRA_CLIENT_ID" -}}
{{- if eq (kindOf $clientId) "map" -}}
{{- $clientId = index $clientId "value" -}}
{{- end -}}
{{- if not $clientId -}}
{{- fail "env.ENTRA_CLIENT_ID is required: it is the Entra app registration users sign in through. Set it in the overlay." -}}
{{- end -}}
{{- end -}}
{{- end -}}
