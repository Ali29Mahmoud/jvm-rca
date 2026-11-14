variable "kubeconfig_path" {
  description = "Path to the kubeconfig used by the kubernetes and helm providers."
  type        = string
  default     = "~/.kube/config"
}

variable "kube_context" {
  description = "kubectl context to deploy into (the kind cluster created by `make cluster-create`)."
  type        = string
  default     = "kind-jvm-rca"
}

variable "namespace" {
  description = "Namespace holding Zookeeper, Kafka, Postgres, MongoDB, the services and the OTel collector/Tempo."
  type        = string
  default     = "eventuate-tram-examples-customers-and-orders"
}

variable "monitoring_namespace" {
  description = "Namespace for kube-prometheus-stack (Prometheus, Grafana, Alertmanager)."
  type        = string
  default     = "monitoring"
}

variable "deploy_infrastructure" {
  description = "Deploy Zookeeper, Kafka, Postgres and MongoDB."
  type        = bool
  default     = true
}

variable "deploy_observability" {
  description = "Deploy the OTel collector, Tempo, the Tempo Grafana datasource and kube-prometheus-stack."
  type        = bool
  default     = true
}

variable "init_postgres" {
  description = "Run a one-shot job that creates the eventuate schema and seeds the Flyway history."
  type        = bool
  default     = true
}

variable "replicas" {
  description = "Replica count for each application service."
  type        = number
  default     = 1
}

variable "service_image_repository" {
  description = "Repository prefix of the application images built by `make images`."
  type        = string
  default     = "eventuateexamples/eventuate-tram-examples-customers-and-orders"
}

variable "service_image_tag" {
  description = "Tag of the application images."
  type        = string
  default     = "latest"
}

variable "cdc_image" {
  description = "Eventuate CDC service image."
  type        = string
  default     = "eventuateio/eventuate-cdc-service:0.20.0.RELEASE"
}

variable "zookeeper_image" {
  description = "Zookeeper image."
  type        = string
  default     = "eventuateio/eventuate-zookeeper:0.22.0.RELEASE"
}

variable "kafka_image" {
  description = "Kafka image."
  type        = string
  default     = "eventuateio/eventuate-kafka:0.20.0.RELEASE"
}

variable "postgres_image" {
  description = "Postgres image (also used by the schema-init job)."
  type        = string
  default     = "eventuateio/eventuate-postgres:0.22.0.RELEASE"
}

variable "mongodb_image" {
  description = "MongoDB image."
  type        = string
  default     = "mongo:5.0.6"
}

variable "java_agent_image" {
  description = "Image providing the OpenTelemetry Java agent used by the CDC service."
  type        = string
  default     = "ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.20.1"
}

variable "otel_collector_image" {
  description = "OpenTelemetry collector image."
  type        = string
  default     = "otel/opentelemetry-collector:0.115.1"
}

variable "tempo_image" {
  description = "Grafana Tempo image."
  type        = string
  default     = "grafana/tempo:2.7.1"
}

variable "kube_prometheus_stack_chart_version" {
  description = "kube-prometheus-stack chart version; null follows the repository's latest."
  type        = string
  default     = null
}

variable "grafana_admin_password" {
  description = "Grafana admin password. Override it, the default is only for local kind clusters."
  type        = string
  sensitive   = true
  default     = "admin"
}

variable "helm_timeout" {
  description = "Seconds to wait for each Helm release."
  type        = number
  default     = 900
}
