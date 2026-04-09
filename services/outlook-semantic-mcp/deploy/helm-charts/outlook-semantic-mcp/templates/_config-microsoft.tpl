{{- define "chart.config.microsoft" -}}
{{- with .Values.mcpConfig.microsoft }}
MICROSOFT_CLIENT_ID: {{ .clientId | quote }}
{{- if .publicWebhookUrl }}
MICROSOFT_PUBLIC_WEBHOOK_URL: {{ .publicWebhookUrl | quote }}
{{- end }}
{{- if not (kindIs "invalid" .subscriptionExpirationTimeHoursUTC) }}
MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC: {{ .subscriptionExpirationTimeHoursUTC | quote }}
{{- end }}
{{- end }}
{{- end }}
