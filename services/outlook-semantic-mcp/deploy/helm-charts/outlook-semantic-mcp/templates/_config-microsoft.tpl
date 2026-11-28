{{- define "chart.config.microsoft" -}}
{{- with .Values.mcpConfig.microsoft }}
- name: MICROSOFT_CLIENT_ID
  value: {{ tpl .clientId $ | quote }}
{{- if .signInTenantId }}
- name: MICROSOFT_SIGN_IN_TENANT_ID
  value: {{ .signInTenantId | quote }}
{{- end }}
{{- if .adminConsentRedirectUri }}
- name: MICROSOFT_ADMIN_CONSENT_REDIRECT_URI
  value: {{ .adminConsentRedirectUri | quote }}
{{- end }}
{{- if eq .offlineAccess "disabled" }}
{{- $app := $.Values.mcpConfig.app }}
{{- if ne $app.mcpBackend "microsoft_graph" }}
{{- fail "mcpConfig.microsoft.offlineAccess disabled needs mcpConfig.app.mcpBackend microsoft_graph: no background job can run without a refresh token." }}
{{- end }}
{{- if ne $app.directorySyncMode "on_demand" }}
{{- fail "mcpConfig.microsoft.offlineAccess disabled needs mcpConfig.app.directorySyncMode on_demand: no background job can run without a refresh token." }}
{{- end }}
{{- if ne $.Values.mcpConfig.delegatedAccess.scan "disabled" }}
{{- fail "mcpConfig.microsoft.offlineAccess disabled needs mcpConfig.delegatedAccess.scan disabled: no background job can run without a refresh token." }}
{{- end }}
{{- $session := (($.Values.mcpConfig.auth | default dict).refreshTokenExpiresInSeconds) }}
{{- if or (not $session) (gt (int $session) 3600) }}
{{- fail "mcpConfig.microsoft.offlineAccess disabled needs mcpConfig.auth.refreshTokenExpiresInSeconds of at most 3600, so the MCP session ends before the Microsoft access token does." }}
{{- end }}
{{- end }}
- name: MICROSOFT_OFFLINE_ACCESS
  value: {{ .offlineAccess | quote }}
- name: MICROSOFT_PROFILE_SCOPES
  value: {{ .profileScopes | quote }}
{{- with .allowedTenantIds }}
- name: MICROSOFT_ALLOWED_TENANT_IDS
  value: {{ join "," . | quote }}
{{- end }}
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
