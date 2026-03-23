{{- define "chart.config.auth" -}}
{{- with .Values.mcpConfig.auth }}
{{- if .accessTokenExpiresInSeconds }}
AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS: {{ .accessTokenExpiresInSeconds | quote }}
{{- end }}
{{- if .refreshTokenExpiresInSeconds }}
AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS: {{ .refreshTokenExpiresInSeconds | quote }}
{{- end }}
{{- end }}
{{- end }}
