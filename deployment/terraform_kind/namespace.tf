resource "kubernetes_namespace_v1" "app" {
  metadata {
    name = var.namespace
  }
}

resource "kubernetes_namespace_v1" "monitoring" {
  count = local.run_observability ? 1 : 0

  metadata {
    name = var.monitoring_namespace
  }
}

resource "kubernetes_config_map_v1" "app" {
  for_each = {
    mongodb-config = {
      connection_string = "mongodb://mongodb:27017/customers_and_orders"
    }
    sql-config = {
      connection_string = "jdbc:postgresql://postgres:5432/eventuate"
      sql_password      = "eventuate"
      sql_user          = "eventuate"
      sql_driver        = "org.postgresql.Driver"
    }
    otel-config = {
      OTEL_EXPORTER_OTLP_ENDPOINT = "http://otel-collector:4317"
      OTEL_EXPORTER_OTLP_PROTOCOL = "grpc"
      OTEL_TRACES_EXPORTER        = "otlp"
      OTEL_METRICS_EXPORTER       = "otlp"
      OTEL_LOGS_EXPORTER          = "otlp"
      OTEL_RESOURCE_ATTRIBUTES    = "service.namespace=${var.namespace},deployment.environment=kind"
    }
  }

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.app.metadata[0].name
  }

  data = each.value
}
