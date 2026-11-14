resource "kubernetes_service_v1" "app" {
  for_each = local.services

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { svc = each.key }
  }

  spec {
    selector = { svc = each.key }

    port {
      name        = "http"
      port        = each.value.service_port
      target_port = 8080
    }
  }
}

resource "kubernetes_deployment_v1" "app" {
  for_each = local.services

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { svc = each.key }
  }

  spec {
    replicas = var.replicas

    selector {
      match_labels = { svc = each.key }
    }

    template {
      metadata {
        labels = { svc = each.key }
      }

      spec {
        # The CDC service is instrumented with the OpenTelemetry Java agent,
        # copied into a shared emptyDir by an init container.
        dynamic "init_container" {
          for_each = each.value.otel_agent ? [1] : []
          content {
            name              = "otel-agent"
            image             = var.java_agent_image
            image_pull_policy = "IfNotPresent"
            command           = ["cp", "/javaagent.jar", "/otel/opentelemetry-javaagent.jar"]

            volume_mount {
              name       = "otel-agent"
              mount_path = "/otel"
            }
          }
        }

        container {
          name              = each.key
          image             = each.value.image
          image_pull_policy = "IfNotPresent"

          port {
            name           = "http"
            container_port = 8080
          }

          env_from {
            config_map_ref {
              name = "otel-config"
            }
          }

          dynamic "env" {
            for_each = each.value.env
            content {
              name  = env.value.name
              value = env.value.config_map == null ? env.value.value : null

              dynamic "value_from" {
                for_each = env.value.config_map == null ? [] : [1]
                content {
                  config_map_key_ref {
                    name = env.value.config_map
                    key  = env.value.key
                  }
                }
              }
            }
          }

          resources {
            requests = {
              cpu    = each.value.cpu_request
              memory = each.value.memory_request
            }
            limits = {
              cpu    = each.value.cpu_limit
              memory = each.value.memory_limit
            }
          }

          readiness_probe {
            http_get {
              path = "/actuator/health"
              port = 8080
            }
            initial_delay_seconds = each.value.readiness_delay
            period_seconds        = 10
          }

          liveness_probe {
            http_get {
              path = "/actuator/health"
              port = 8080
            }
            initial_delay_seconds = each.value.liveness_delay
            period_seconds        = 15
          }

          dynamic "volume_mount" {
            for_each = each.value.otel_agent ? [1] : []
            content {
              name       = "otel-agent"
              mount_path = "/otel"
            }
          }
        }

        dynamic "volume" {
          for_each = each.value.otel_agent ? [1] : []
          content {
            name = "otel-agent"

            empty_dir {}
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_namespace_v1.app,
    kubernetes_config_map_v1.app,
  ]
}

# Prometheus picks these up because kube-prometheus-stack is installed with
# prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false.
resource "kubernetes_manifest" "service_monitor" {
  for_each = { for name in local.monitored_services : name => name if local.run_observability }

  manifest = {
    apiVersion = "monitoring.coreos.com/v1"
    kind       = "ServiceMonitor"
    metadata = {
      name      = each.key
      namespace = kubernetes_namespace_v1.app.metadata[0].name
      labels = {
        release = "monitoring"
        svc     = each.key
      }
    }
    spec = {
      selector = {
        matchLabels = { svc = each.key }
      }
      endpoints = [{
        port          = "http"
        path          = "/actuator/prometheus"
        interval      = "15s"
        scrapeTimeout = "10s"
      }]
    }
  }

  depends_on = [helm_release.kube_prometheus_stack]
}
