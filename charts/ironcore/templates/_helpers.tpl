{{/*
IronCore Helm Chart — Shared Template Helpers
*/}}

{{/* Expand the name of the chart. */}}
{{- define "ironcore.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncate to 63 chars (DNS limit). If release name contains chart name, use release name.
*/}}
{{- define "ironcore.fullname" -}}
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

{{/* Create chart label */}}
{{- define "ironcore.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Common labels */}}
{{- define "ironcore.labels" -}}
helm.sh/chart: {{ include "ironcore.chart" . }}
{{ include "ironcore.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: ironcore
ironcore.dev/edition: {{ .Values.edition.value | quote }}
{{- end }}

{{/* Selector labels */}}
{{- define "ironcore.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ironcore.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Worker selector labels */}}
{{- define "ironcore.workerSelectorLabels" -}}
app.kubernetes.io/name: {{ include "ironcore.name" . }}-worker
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: worker
{{- end }}

{{/* Service account name */}}
{{- define "ironcore.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ironcore.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* Worker full name */}}
{{- define "ironcore.workerFullname" -}}
{{- printf "%s-worker" (include "ironcore.fullname" .) }}
{{- end }}
