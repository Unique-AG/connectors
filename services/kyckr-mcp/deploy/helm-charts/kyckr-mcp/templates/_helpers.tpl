{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{- define "kyckr-mcp.validateValues" -}}
{{- $apiBaseUrl := tpl (.Values.mcpConfig.kyckr.apiBaseUrl | default "") . -}}
{{- if not $apiBaseUrl -}}
{{- fail "mcpConfig.kyckr.apiBaseUrl is set but empty: it is the Kyckr REST API this server calls. Unset it to take the chart default, or set an https URL in the overlay." -}}
{{- end -}}
{{- if hasPrefix "http://" (lower $apiBaseUrl) -}}
{{- fail "mcpConfig.kyckr.apiBaseUrl must not be cleartext: the Kyckr API key is sent as a Bearer token on every request. Set an https URL in the overlay." -}}
{{- end -}}
{{- end -}}

{{- define "chart.config.mcpEnv" -}}
- name: KYCKR_API_BASE_URL
  value: {{ tpl .Values.mcpConfig.kyckr.apiBaseUrl . | quote }}
{{- include "base.valueSource.env" (dict "name" "MCP_API_KEY" "src" .Values.mcpConfig.app.apiKey "ctx" .) | nindent 0 }}
{{- include "base.valueSource.env" (dict "name" "KYCKR_API_KEY" "src" .Values.mcpConfig.kyckr.apiKey "ctx" .) | nindent 0 }}
{{- with .Values.mcpConfig.kyckr.defaultCustomerReference }}
- name: KYCKR_DEFAULT_CUSTOMER_REFERENCE
  value: {{ tpl . $ | quote }}
{{- end }}
{{- with .Values.mcpConfig.kyckr.defaultContactEmail }}
- name: KYCKR_DEFAULT_CONTACT_EMAIL
  value: {{ tpl . $ | quote }}
{{- end }}
{{- end -}}
