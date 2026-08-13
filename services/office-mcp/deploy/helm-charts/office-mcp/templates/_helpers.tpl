{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
Fails the render with an actionable message when a plain `helm install` would otherwise
crash-loop: config.py defaults `app_env` to production, and `_reject_local_base_url_in_production`
there rejects the localhost default for `PUBLIC_BASE_URL` whenever `app_env` is production —
which is also what an unset `env.APP_ENV` resolves to, since that's the code's own default.
Without this, the failure only surfaces as a pydantic ValidationError in pod logs after
CrashLoopBackOff, not at `helm install`/`helm template` time.

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
{{- end -}}
{{- end -}}
