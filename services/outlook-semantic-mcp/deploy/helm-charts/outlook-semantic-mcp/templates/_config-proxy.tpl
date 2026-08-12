{{- define "chart.config.proxy" -}}
{{- with .Values.proxyConfig }}
- name: PROXY_AUTH_MODE
  value: {{ .authMode | quote }}
{{- if ne .authMode "none" }}
- name: PROXY_HOST
  value: {{ .host | quote }}
- name: PROXY_PORT
  value: {{ .port | quote }}
- name: PROXY_PROTOCOL
  value: {{ .protocol | quote }}
{{- end }}
{{- if eq .authMode "username_password" }}
- name: PROXY_USERNAME
  value: {{ .username | quote }}
{{- end }}
{{- if eq .authMode "ssl_tls" }}
- name: PROXY_SSL_CERT_PATH
  value: {{ .sslCertPath | quote }}
- name: PROXY_SSL_KEY_PATH
  value: {{ .sslKeyPath | quote }}
{{- end }}
{{- if .sslCaBundlePath }}
- name: PROXY_SSL_CA_BUNDLE_PATH
  value: {{ .sslCaBundlePath | quote }}
{{- end }}
{{- if .headers }}
- name: PROXY_HEADERS
  value: {{ .headers | quote }}
{{- end }}
{{- end }}
{{- end }}
