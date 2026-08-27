{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
Guards mcpConfig.app.publicBaseUrl beyond what values.schema.json can express. `mcpConfig.app`'s
`required` there already fails a missing publicBaseUrl at `helm install` time, for every APP_ENV;
what it cannot see is the value.

Overlays build this URL from a tpl expression, so it can render empty or cleartext while still
satisfying `required`. The scheme test is a `http://` prefix rather than a required `https://`
precisely so an unresolved tpl expression still renders. config.py's
`_reject_local_base_url_in_production` and `_reject_cleartext_base_url_in_production` remain the
backstop.

Runs only when the deployment resolves to production, which includes an unset `env.APP_ENV`,
because production is config.py's own default for `app_env`.
*/}}
{{- define "office-365-mcp.validateValues" -}}
{{- $env := .Values.env | default dict -}}
{{- $appEnv := index $env "APP_ENV" -}}
{{- if eq (kindOf $appEnv) "map" -}}
{{- $appEnv = index $appEnv "value" -}}
{{- end -}}
{{- $isProduction := or (not $appEnv) (eq (lower (toString $appEnv)) "production") -}}
{{- if $isProduction -}}
{{- $publicBaseUrl := tpl .Values.mcpConfig.app.publicBaseUrl . -}}
{{- if not $publicBaseUrl -}}
{{- fail "mcpConfig.app.publicBaseUrl is set but empty: it is the externally-reachable OAuth issuer URL clients are redirected to. Set it in the overlay." -}}
{{- end -}}
{{- if hasPrefix "http://" (lower $publicBaseUrl) -}}
{{- fail "mcpConfig.app.publicBaseUrl must not be cleartext: the OAuth discovery, authorize and token endpoints are published under it, and over http the consent cookies lose their Secure flag. Set an https URL in the overlay." -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
All mcpConfig environment variables, shared by deployment (and hook job, if this chart ever gains
one) containers.
*/}}
{{- define "chart.config.mcpEnv" -}}
- name: PUBLIC_BASE_URL
  value: {{ tpl .Values.mcpConfig.app.publicBaseUrl . | quote }}
- name: ENTRA_TENANT_ID
  value: {{ tpl .Values.mcpConfig.entra.tenantId . | quote }}
- name: ENTRA_CLIENT_ID
  value: {{ tpl .Values.mcpConfig.entra.clientId . | quote }}
{{- include "base.valueSource.env" (dict "name" "ENTRA_CLIENT_SECRET" "src" .Values.mcpConfig.entra.clientSecret "ctx" .) | nindent 0 }}
{{- if .Values.mcpConfig.tools.preset }}
- name: TOOLS_PRESET
  value: {{ .Values.mcpConfig.tools.preset | quote }}
{{- end }}
{{- if .Values.mcpConfig.tools.enabled }}
- name: TOOLS_ENABLED
  value: {{ .Values.mcpConfig.tools.enabled | quote }}
{{- end }}
{{- end -}}
