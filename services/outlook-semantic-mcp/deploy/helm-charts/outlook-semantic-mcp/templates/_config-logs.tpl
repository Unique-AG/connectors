{{- define "chart.config.logs" -}}
{{- with .Values.mcpConfig.logs }}
{{- if .diagnosticsDataPolicy }}
LOGS_DIAGNOSTICS_DATA_POLICY: {{ .diagnosticsDataPolicy | quote }}
{{- end }}
{{- end }}
{{- end }}
