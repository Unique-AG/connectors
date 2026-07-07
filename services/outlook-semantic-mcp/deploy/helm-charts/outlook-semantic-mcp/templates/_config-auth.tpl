{{- define "chart.config.auth" -}}
{{- with .Values.mcpConfig.auth }}
{{- if .accessTokenExpiresInSeconds }}
- name: AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS
  value: {{ .accessTokenExpiresInSeconds | quote }}
{{- end }}
{{- if .refreshTokenExpiresInSeconds }}
- name: AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS
  value: {{ .refreshTokenExpiresInSeconds | quote }}
{{- end }}
{{- end }}
{{- end }}
