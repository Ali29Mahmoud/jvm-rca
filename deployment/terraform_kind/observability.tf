# ---------------------------------------------------------------------------
# Metrics: Prometheus, Grafana and Alertmanager (Helm)
# ---------------------------------------------------------------------------
resource "helm_release" "kube_prometheus_stack" {
  count = local.run_observability ? 1 : 0

  name       = "monitoring"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = var.kube_prometheus_stack_chart_version
  namespace  = kubernetes_namespace_v1.monitoring[0].metadata[0].name

  timeout = var.helm_timeout

  # Pick up every ServiceMonitor/PodMonitor in the cluster, not only the ones
  # labelled with this Helm release (the application ServiceMonitors are not).
  set {
    name  = "prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues"
    value = "false"
  }

  set {
    name  = "prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues"
    value = "false"
  }

  set {
    name  = "grafana.adminPassword"
    value = var.grafana_admin_password
  }
}

# ---------------------------------------------------------------------------
# Traces: OpenTelemetry collector -> Tempo (plain manifests, matching
# k8s-deployment/04-otel-collector.yaml)
# ---------------------------------------------------------------------------
resource "kubernetes_config_map_v1" "otel_collector_config" {
  count = local.run_observability ? 1 : 0

  metadata {
    name      = "otel-collector-config"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
  }

  data = {
    "config.yaml" = yamlencode({
      receivers = {
        otlp = {
          protocols = {
            grpc = { endpoint = "0.0.0.0:4317" }
            http = { endpoint = "0.0.0.0:4318" }
          }
        }
      }
      exporters = {
        "otlp/tempo" = {
          endpoint = "tempo:4317"
          tls      = { insecure = true }
        }
        debug = { verbosity = "basic" }
      }
      service = {
        pipelines = {
          traces  = { receivers = ["otlp"], exporters = ["otlp/tempo"] }
          metrics = { receivers = ["otlp"], exporters = ["debug"] }
          logs    = { receivers = ["otlp"], exporters = ["debug"] }
        }
      }
    })
  }
}

resource "kubernetes_service_v1" "otel_collector" {
  count = local.run_observability ? 1 : 0

  metadata {
    name      = "otel-collector"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { svc = "otel-collector" }
  }

  spec {
    selector = { svc = "otel-collector" }

    port {
      name        = "otlp-grpc"
      port        = 4317
      target_port = 4317
    }

    port {
      name        = "otlp-http"
      port        = 4318
      target_port = 4318
    }
  }
}

resource "kubernetes_deployment_v1" "otel_collector" {
  count = local.run_observability ? 1 : 0

  metadata {
    name      = "otel-collector"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { svc = "otel-collector" }
  }

  spec {
    replicas = 1

    selector {
      match_labels = { svc = "otel-collector" }
    }

    template {
      metadata {
        labels = { svc = "otel-collector" }
      }

      spec {
        container {
          name              = "otel-collector"
          image             = var.otel_collector_image
          image_pull_policy = "IfNotPresent"
          args              = ["--config=/etc/otelcol/config.yaml"]

          port {
            name           = "otlp-grpc"
            container_port = 4317
          }

          port {
            name           = "otlp-http"
            container_port = 4318
          }

          resources {
            requests = { cpu = "100m", memory = "128Mi" }
            limits   = { cpu = "500m", memory = "512Mi" }
          }

          volume_mount {
            name       = "config"
            mount_path = "/etc/otelcol"
          }
        }

        volume {
          name = "config"

          config_map {
            name = kubernetes_config_map_v1.otel_collector_config[0].metadata[0].name
          }
        }
      }
    }
  }

  depends_on = [kubernetes_namespace_v1.app]
}

resource "kubernetes_config_map_v1" "tempo_config" {
  count = local.run_observability ? 1 : 0

  metadata {
    name      = "tempo-config"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
  }

  data = {
    "tempo.yaml" = yamlencode({
      server = { http_listen_port = 3200 }
      distributor = {
        receivers = {
          otlp = {
            protocols = {
              grpc = { endpoint = "0.0.0.0:4317" }
              http = { endpoint = "0.0.0.0:4318" }
            }
          }
        }
      }
      storage = {
        trace = {
          backend = "local"
          local   = { path = "/var/tempo/traces" }
          wal     = { path = "/var/tempo/wal" }
        }
      }
      compactor = {
        compaction = { block_retention = "1h" }
      }
      usage_report = { reporting_enabled = false }
    })
  }
}

resource "kubernetes_service_v1" "tempo" {
  count = local.run_observability ? 1 : 0

  metadata {
    name      = "tempo"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { svc = "tempo" }
  }

  spec {
    selector = { svc = "tempo" }

    port {
      name        = "otlp-grpc"
      port        = 4317
      target_port = 4317
    }

    port {
      name        = "otlp-http"
      port        = 4318
      target_port = 4318
    }

    port {
      name        = "http"
      port        = 3200
      target_port = 3200
    }
  }
}

resource "kubernetes_deployment_v1" "tempo" {
  count = local.run_observability ? 1 : 0

  metadata {
    name      = "tempo"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { svc = "tempo" }
  }

  spec {
    replicas = 1

    selector {
      match_labels = { svc = "tempo" }
    }

    template {
      metadata {
        labels = { svc = "tempo" }
      }

      spec {
        container {
          name              = "tempo"
          image             = var.tempo_image
          image_pull_policy = "IfNotPresent"
          args              = ["-config.file=/etc/tempo/tempo.yaml"]

          port {
            name           = "otlp-grpc"
            container_port = 4317
          }

          port {
            name           = "otlp-http"
            container_port = 4318
          }

          port {
            name           = "http"
            container_port = 3200
          }

          readiness_probe {
            http_get {
              path = "/ready"
              port = 3200
            }
            initial_delay_seconds = 10
            period_seconds        = 10
          }

          resources {
            requests = { cpu = "100m", memory = "256Mi" }
            limits   = { cpu = "500m", memory = "1Gi" }
          }

          volume_mount {
            name       = "config"
            mount_path = "/etc/tempo"
          }

          volume_mount {
            name       = "data"
            mount_path = "/var/tempo"
          }
        }

        volume {
          name = "config"

          config_map {
            name = kubernetes_config_map_v1.tempo_config[0].metadata[0].name
          }
        }

        volume {
          name = "data"

          empty_dir {}
        }
      }
    }
  }

  depends_on = [kubernetes_namespace_v1.app]
}

# Grafana's datasource sidecar loads ConfigMaps labelled grafana_datasource=1.
resource "kubernetes_config_map_v1" "tempo_datasource" {
  count = local.run_observability ? 1 : 0

  metadata {
    name      = "tempo-datasource"
    namespace = kubernetes_namespace_v1.monitoring[0].metadata[0].name
    labels    = { grafana_datasource = "1" }
  }

  data = {
    "tempo-datasource.yaml" = yamlencode({
      apiVersion = 1
      datasources = [{
        name      = "Tempo"
        type      = "tempo"
        access    = "proxy"
        url       = "http://tempo.${var.namespace}.svc.cluster.local:3200"
        isDefault = false
        editable  = true
      }]
    })
  }

  depends_on = [helm_release.kube_prometheus_stack]
}
