output "namespace" {
  description = "Namespace holding the application and its infrastructure."
  value       = kubernetes_namespace_v1.app.metadata[0].name
}

output "api_gateway_url" {
  description = "In-cluster URL of the API gateway."
  value       = "http://api-gateway-service.${var.namespace}.svc.cluster.local:8080"
}

output "grafana_port_forward" {
  description = "Command that exposes Grafana on localhost:3000."
  value       = local.run_observability ? "kubectl port-forward -n ${var.monitoring_namespace} svc/monitoring-grafana 3000:80" : null
}

output "prometheus_port_forward" {
  description = "Command that exposes Prometheus on localhost:9090."
  value       = local.run_observability ? "kubectl port-forward -n ${var.monitoring_namespace} svc/monitoring-kube-prometheus-prometheus 9090:9090" : null
}

output "tempo_endpoint" {
  description = "In-cluster OTLP endpoint of Tempo."
  value       = local.run_observability ? "tempo.${var.namespace}.svc.cluster.local:4317" : null
}

output "otel_collector_endpoint" {
  description = "In-cluster OTLP endpoint the services export to."
  value       = local.run_observability ? "otel-collector.${var.namespace}.svc.cluster.local:4317" : null
}
