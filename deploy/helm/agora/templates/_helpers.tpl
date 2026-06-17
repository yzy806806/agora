{{/*
Expand the name of the chart.
*/}}
{{- define "agora.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "agora.fullname" -}}
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

{{/*
Component fullnames.
*/}}
{{- define "agora.coordinator.fullname" -}}
{{- printf "%s-coordinator" (include "agora.fullname" .) }}
{{- end }}

{{- define "agora.redis.fullname" -}}
{{- printf "%s-redis" (include "agora.fullname" .) }}
{{- end }}

{{- define "agora.postgres.fullname" -}}
{{- printf "%s-postgres" (include "agora.fullname" .) }}
{{- end }}

{{- define "agora.hermes-bridge.fullname" -}}
{{- printf "%s-hermes-bridge" (include "agora.fullname" .) }}
{{- end }}

{{/*
Chart version string used in labels.
*/}}
{{- define "agora.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "agora.labels" -}}
helm.sh/chart: {{ include "agora.chart" . }}
{{ include "agora.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels used in matchLabels and pod templates.
*/}}
{{- define "agora.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agora.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Service account name.
*/}}
{{- define "agora.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "agora.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
