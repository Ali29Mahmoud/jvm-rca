resource "kubernetes_service_v1" "infra" {
  for_each = var.deploy_infrastructure ? local.infra : {}

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { (each.value.label_key) = each.key }
  }

  spec {
    selector = { (each.value.label_key) = each.key }

    dynamic "port" {
      for_each = each.value.ports
      content {
        name        = port.value.name
        port        = port.value.port
        target_port = port.value.target
      }
    }
  }
}

resource "kubernetes_deployment_v1" "infra" {
  for_each = var.deploy_infrastructure ? local.infra : {}

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = { (each.value.label_key) = each.key }
  }

  spec {
    replicas = 1

    selector {
      match_labels = { (each.value.label_key) = each.key }
    }

    template {
      metadata {
        labels = { (each.value.label_key) = each.key }
      }

      spec {
        container {
          name              = each.key
          image             = each.value.image
          image_pull_policy = "IfNotPresent"

          dynamic "port" {
            for_each = each.value.ports
            content {
              name           = port.value.name
              container_port = port.value.target
            }
          }

          dynamic "env" {
            for_each = each.value.env
            content {
              name  = env.value.name
              value = env.value.value
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
        }
      }
    }
  }

  depends_on = [kubernetes_namespace_v1.app]
}
