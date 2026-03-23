{{- define "chart.config.microsoft" -}}
MICROSOFT_CLIENT_ID: {{ .Values.mcpConfig.microsoft.clientId | quote }}
{{- if .Values.mcpConfig.microsoft.publicWebhookUrl }}
MICROSOFT_PUBLIC_WEBHOOK_URL: {{ .Values.mcpConfig.microsoft.publicWebhookUrl | quote }}
{{- end }}
{{- if not (kindIs "invalid" .Values.mcpConfig.microsoft.subscriptionExpirationTimeHoursUTC) }}
MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC: {{ .Values.mcpConfig.microsoft.subscriptionExpirationTimeHoursUTC | quote }}
{{- end }}
{{- end }}
