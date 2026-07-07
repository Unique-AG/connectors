{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
Ensure URL has trailing slash.
Accepts a context with .url containing the URL to process.
*/}}
{{- define "chart.ensureTrailingSlash" -}}
{{- $url := .url }}
{{- if hasSuffix "/" $url }}
{{- $url }}
{{- else }}
{{- printf "%s/" $url }}
{{- end }}
{{- end }}

{{/*
Ensure URL has no trailing slash.
Accepts a context with .url containing the URL to process.
*/}}
{{- define "chart.ensureNoTrailingSlash" -}}
{{- .url | trimSuffix "/" }}
{{- end }}
