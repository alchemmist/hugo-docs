{{- define "wiki.name" -}}
{{- printf "%s-wiki" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- define "wiki.labels" -}}
app.kubernetes.io/name: hugo-docs-wiki
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
