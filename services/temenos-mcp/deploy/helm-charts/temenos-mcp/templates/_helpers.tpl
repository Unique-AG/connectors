{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{- define "temenos-mcp.validateValues" -}}
{{- $apiBaseUrl := tpl (.Values.mcpConfig.temenos.apiBaseUrl | default "") . -}}
{{- if not $apiBaseUrl -}}
{{- fail "mcpConfig.temenos.apiBaseUrl is set but empty: it is the Temenos DataHub REST API this server calls. Unset it to take the chart default, or set an https URL in the overlay." -}}
{{- end -}}
{{- if hasPrefix "http://" (lower $apiBaseUrl) -}}
{{- fail "mcpConfig.temenos.apiBaseUrl must not be cleartext: the Temenos API key is sent as the apikey header on every request. Set an https URL in the overlay." -}}
{{- end -}}
{{- end -}}

{{- define "chart.config.mcpEnv" -}}
- name: TEMENOS_API_BASE_URL
  value: {{ tpl .Values.mcpConfig.temenos.apiBaseUrl . | quote }}
{{- include "base.valueSource.env" (dict "name" "MCP_API_KEY" "src" .Values.mcpConfig.app.apiKey "ctx" .) | nindent 0 }}
{{- include "base.valueSource.env" (dict "name" "TEMENOS_API_KEY" "src" .Values.mcpConfig.temenos.apiKey "ctx" .) | nindent 0 }}
{{- end -}}
