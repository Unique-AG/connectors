{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
Guards PUBLIC_BASE_URL beyond what values.schema.json can express. `env.required` there already
fails a missing PUBLIC_BASE_URL, ENTRA_TENANT_ID or ENTRA_CLIENT_ID at `helm install` time, for
every APP_ENV; what it cannot see is the value.

Overlays build this URL from a tpl expression, so it can render empty or cleartext while still
satisfying `required`. The scheme test is a `http://` prefix rather than a required `https://`
precisely so an unresolved tpl expression still renders. config.py's
`_reject_local_base_url_in_production` and `_reject_cleartext_base_url_in_production` remain the
backstop.

Runs only when the deployment resolves to production, which includes an unset `env.APP_ENV`,
because production is config.py's own default for `app_env`.

An `env` value (per the base chart schema) is either a plain string/number/boolean or an object
with a `value` key — either form is unwrapped before being checked.
*/}}
{{- define "office-365-mcp.validateValues" -}}
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
{{- fail "env.PUBLIC_BASE_URL is set but empty: it is the externally-reachable OAuth issuer URL clients are redirected to. Set it in the overlay." -}}
{{- end -}}
{{- if hasPrefix "http://" (lower (toString $publicBaseUrl)) -}}
{{- fail "env.PUBLIC_BASE_URL must not be cleartext: the OAuth discovery, authorize and token endpoints are published under it, and over http the consent cookies lose their Secure flag. Set an https URL in the overlay." -}}
{{- end -}}
{{- end -}}
{{- end -}}
