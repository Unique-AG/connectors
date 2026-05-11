{{- define "chart.config.kyckr" -}}
{{- with .Values.mcpConfig.kyckr }}
{{- if .apiBaseUrl }}
KYCKR_API_BASE_URL: {{ .apiBaseUrl | quote }}
{{- end }}
{{- if .defaultCustomerReference }}
KYCKR_DEFAULT_CUSTOMER_REFERENCE: {{ .defaultCustomerReference | quote }}
{{- end }}
{{- if .defaultContactEmail }}
KYCKR_DEFAULT_CONTACT_EMAIL: {{ .defaultContactEmail | quote }}
{{- end }}
{{- end }}
{{- end }}
