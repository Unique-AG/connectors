{{- define "chart.config.microsoft" -}}
{{- with .Values.mcpConfig.microsoft }}
- name: MICROSOFT_CLIENT_ID
  value: {{ tpl .clientId $ | quote }}
{{- if .publicWebhookUrl }}
- name: MICROSOFT_PUBLIC_WEBHOOK_URL
  value: {{ .publicWebhookUrl | quote }}
{{- end }}
{{- if not (kindIs "invalid" .subscriptionExpirationTimeHoursUTC) }}
- name: MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC
  value: {{ .subscriptionExpirationTimeHoursUTC | quote }}
{{- end }}
{{- end }}
{{- end }}
