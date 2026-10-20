{{/* Chart name, overridable with .Values.nameOverride. */}}
{{- define "multi-env-app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Uses the release name so several environments
can live side by side (myapp-dev, myapp-test, ...).
*/}}
{{- define "multi-env-app.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "multi-env-app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Image tag: explicit value or the chart's appVersion. */}}
{{- define "multi-env-app.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/* Application version shown on the dashboard. */}}
{{- define "multi-env-app.appVersion" -}}
{{- .Values.app.version | default (include "multi-env-app.imageTag" .) }}
{{- end }}

{{- define "multi-env-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "multi-env-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "multi-env-app.labels" -}}
helm.sh/chart: {{ include "multi-env-app.chart" . }}
{{ include "multi-env-app.selectorLabels" . }}
app.kubernetes.io/version: {{ include "multi-env-app.appVersion" . | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/environment: {{ .Values.environment }}
{{- end }}
