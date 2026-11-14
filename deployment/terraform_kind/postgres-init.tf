# The Postgres image already contains the Eventuate schema, so the services must
# not re-run the Flyway migrations: this one-shot job creates the schema and
# seeds eventuate.flyway_schema_history (same SQL as `make init-postgres`).
resource "kubernetes_config_map_v1" "postgres_init_sql" {
  count = local.run_postgres_init ? 1 : 0

  metadata {
    name      = "postgres-init-sql"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
  }

  data = {
    "init-postgres.sql" = file("${path.module}/../../k8s-deployment/init-postgres.sql")
  }
}

resource "kubernetes_job_v1" "postgres_init" {
  count = local.run_postgres_init ? 1 : 0

  metadata {
    name      = "postgres-init"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
  }

  spec {
    backoff_limit              = 10
    ttl_seconds_after_finished = 3600

    template {
      metadata {
        labels = { job = "postgres-init" }
      }

      spec {
        restart_policy = "Never"

        container {
          name  = "psql"
          image = var.postgres_image

          command = ["/bin/sh", "-c"]

          args = [
            "until psql -h postgres -U eventuate -d eventuate -c 'SELECT 1' >/dev/null 2>&1; do echo 'waiting for postgres'; sleep 2; done; psql -h postgres -U eventuate -d eventuate -v ON_ERROR_STOP=1 -f /sql/init-postgres.sql",
          ]

          env {
            name = "PGPASSWORD"

            value_from {
              config_map_key_ref {
                name = "sql-config"
                key  = "sql_password"
              }
            }
          }

          volume_mount {
            name       = "sql"
            mount_path = "/sql"
          }
        }

        volume {
          name = "sql"

          config_map {
            name = kubernetes_config_map_v1.postgres_init_sql[0].metadata[0].name
          }
        }
      }
    }
  }

  wait_for_completion = true

  depends_on = [
    kubernetes_deployment_v1.infra,
    kubernetes_config_map_v1.app,
  ]
}
