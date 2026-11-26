{{/* mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00 */}}
{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/* mcpConfig as environment variables; unset values are skipped. Secrets stay out of it. */}}
{{- define "chart.config.mcpEnv" -}}
{{- $c := .Values.mcpConfig }}
{{- $env := dict
  "MCP_BASE_URL" (tpl ($c.app.publicBaseUrl | default "") .)
  "ZITADEL_BASE_URL" (tpl ($c.zitadel.baseUrl | default "") .)
  "ZITADEL_CLIENT_ID" ($c.zitadel.clientId | default "")
  "ZITADEL_ORG_ID" ($c.zitadel.orgId | default "")
  "UPSTREAM_API_URL" (tpl ($c.kyckr.apiUrl | default "") .)
  "UPSTREAM_TIMEOUT_SECONDS" ($c.kyckr.timeoutSeconds | default "")
  "UPSTREAM_DEFAULT_CUSTOMER_REFERENCE" ($c.kyckr.defaultCustomerReference | default "")
  "UPSTREAM_DEFAULT_CONTACT_EMAIL" ($c.kyckr.defaultContactEmail | default "")
  "MCP_RATE_LIMIT_TOOL_CALLS_PER_WINDOW" ($c.rateLimit.toolCallsPerWindow | default "")
  "MCP_RATE_LIMIT_WINDOW_SECONDS" ($c.rateLimit.windowSeconds | default "")
}}
{{- range $name, $value := $env }}
{{- if $value }}
- name: {{ $name }}
  value: {{ $value | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{/* Hosts the pods call over https: Zitadel and the Kyckr API, as a JSON list. */}}
{{- define "chart.egressHosts" -}}
{{- $hosts := list }}
{{- range (list .Values.mcpConfig.zitadel.baseUrl .Values.mcpConfig.kyckr.apiUrl) }}
{{- if . }}
{{- $hosts = append $hosts (tpl . $ | urlParse).hostname }}
{{- end }}
{{- end }}
{{- $hosts | toJson }}
{{- end -}}
