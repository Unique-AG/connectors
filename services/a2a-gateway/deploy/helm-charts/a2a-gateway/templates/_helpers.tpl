{{- define "a2a-gateway.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "a2a-gateway.fullname" -}}
{{- if .Values.fullnameOverride }}{{ .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}{{- else }}{{ include "a2a-gateway.name" . }}{{- end }}
{{- end }}

{{- define "a2a-gateway.labels" -}}
app.kubernetes.io/name: {{ include "a2a-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "a2a-gateway.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}{{ default (include "a2a-gateway.fullname" .) .Values.serviceAccount.name }}{{- else }}{{ default "default" .Values.serviceAccount.name }}{{- end }}
{{- end }}
