{{- define "chart.config.logs" -}}
{{- if .Values.mcpConfig.logs.diagnosticsDataPolicy }}
LOGS_DIAGNOSTICS_DATA_POLICY: {{ .Values.mcpConfig.logs.diagnosticsDataPolicy | quote }}
{{- end }}
{{- end }}
