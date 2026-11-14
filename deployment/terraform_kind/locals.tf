locals {
  # Every env entry has the same shape so the service definitions below can be a
  # single map: either a literal `value`, or a ConfigMap `config_map`/`key` ref.
  sql_env = [
    { name = "SPRING_DATASOURCE_URL", value = null, config_map = "sql-config", key = "connection_string" },
    { name = "SPRING_DATASOURCE_USERNAME", value = null, config_map = "sql-config", key = "sql_user" },
    { name = "SPRING_DATASOURCE_PASSWORD", value = null, config_map = "sql-config", key = "sql_password" },
    { name = "SPRING_DATASOURCE_DRIVER_CLASS_NAME", value = null, config_map = "sql-config", key = "sql_driver" },
  ]

  kafka_env = [
    { name = "EVENTUATELOCAL_KAFKA_BOOTSTRAP_SERVERS", value = "kafka:29092", config_map = null, key = null },
    { name = "EVENTUATELOCAL_ZOOKEEPER_CONNECTION_STRING", value = "zookeeper:2181", config_map = null, key = null },
  ]

  mongo_env = [
    { name = "SPRING_MONGODB_URI", value = null, config_map = "mongodb-config", key = "connection_string" },
    { name = "SPRING_DATA_MONGODB_URI", value = null, config_map = "mongodb-config", key = "connection_string" },
  ]

  services = {
    cdc-service = {
      image           = var.cdc_image
      service_port    = 8080
      cpu_request     = "300m"
      memory_request  = "512Mi"
      cpu_limit       = "1000m"
      memory_limit    = "1024Mi"
      readiness_delay = 20
      liveness_delay  = 30
      otel_agent      = true
      env = concat(local.sql_env, local.kafka_env, [
        { name = "OTEL_SERVICE_NAME", value = "cdc-service", config_map = null, key = null },
        { name = "JAVA_TOOL_OPTIONS", value = "-javaagent:/otel/opentelemetry-javaagent.jar", config_map = null, key = null },
        { name = "EVENTUATELOCAL_CDC_READER_NAME", value = "PostgresWalReader", config_map = null, key = null },
        { name = "SPRING_PROFILES_ACTIVE", value = "PostgresWal", config_map = null, key = null },
        { name = "EVENTUATE_OUTBOX_ID", value = "1", config_map = null, key = null },
        { name = "JAVA_OPTS", value = "-Xmx256m", config_map = null, key = null },
      ])
    }

    customer-service = {
      image           = "${var.service_image_repository}-customer-service:${var.service_image_tag}"
      service_port    = 8082
      cpu_request     = "300m"
      memory_request  = "512Mi"
      cpu_limit       = "1500m"
      memory_limit    = "1024Mi"
      readiness_delay = 30
      liveness_delay  = 45
      otel_agent      = false
      env = concat(local.sql_env, local.kafka_env, [
        { name = "OTEL_SERVICE_NAME", value = "customer-service", config_map = null, key = null },
        { name = "CDC_SERVICE_URL", value = "http://cdc-service:8080", config_map = null, key = null },
      ])
    }

    order-service = {
      image           = "${var.service_image_repository}-order-service:${var.service_image_tag}"
      service_port    = 8081
      cpu_request     = "300m"
      memory_request  = "512Mi"
      cpu_limit       = "1500m"
      memory_limit    = "1024Mi"
      readiness_delay = 30
      liveness_delay  = 45
      otel_agent      = false
      env = concat(local.sql_env, local.kafka_env, [
        { name = "OTEL_SERVICE_NAME", value = "order-service", config_map = null, key = null },
        { name = "CDC_SERVICE_URL", value = "http://cdc-service:8080", config_map = null, key = null },
      ])
    }

    order-history-service = {
      image           = "${var.service_image_repository}-order-history-service:${var.service_image_tag}"
      service_port    = 8083
      cpu_request     = "300m"
      memory_request  = "512Mi"
      cpu_limit       = "1500m"
      memory_limit    = "1024Mi"
      readiness_delay = 30
      liveness_delay  = 45
      otel_agent      = false
      env = concat(local.mongo_env, local.kafka_env, [
        { name = "OTEL_SERVICE_NAME", value = "order-history-service", config_map = null, key = null },
      ])
    }

    api-gateway-service = {
      image           = "${var.service_image_repository}-api-gateway-service:${var.service_image_tag}"
      service_port    = 8080
      cpu_request     = "300m"
      memory_request  = "512Mi"
      cpu_limit       = "1500m"
      memory_limit    = "1024Mi"
      readiness_delay = 30
      liveness_delay  = 45
      otel_agent      = false
      env = [
        { name = "OTEL_SERVICE_NAME", value = "api-gateway-service", config_map = null, key = null },
        { name = "customer.destinations.customerServiceUrl", value = "http://customer-service:8082", config_map = null, key = null },
        { name = "order.destinations.orderServiceUrl", value = "http://order-service:8081", config_map = null, key = null },
        { name = "orderhistory.destinations.orderHistoryServiceUrl", value = "http://order-history-service:8083", config_map = null, key = null },
        { name = "MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE", value = "*", config_map = null, key = null },
      ]
    }
  }

  # Single-container infrastructure workloads. Infra pods are labelled role=<name>,
  # application pods svc=<name>.
  infra = {
    zookeeper = {
      image          = var.zookeeper_image
      label_key      = "role"
      ports          = [{ name = "zookeeper", port = 2181, target = 2181 }]
      cpu_request    = "200m"
      memory_request = "256Mi"
      cpu_limit      = "1000m"
      memory_limit   = "512Mi"
      env = [
        { name = "ZOOKEEPER_CLIENT_PORT", value = "2181", config_map = null, key = null },
        { name = "KAFKA_HEAP_OPTS", value = "-Xmx128m", config_map = null, key = null },
      ]
    }

    kafka = {
      image     = var.kafka_image
      label_key = "role"
      ports = [
        { name = "kafka", port = 29092, target = 29092 },
        { name = "external", port = 9092, target = 9092 },
      ]
      cpu_request    = "300m"
      memory_request = "512Mi"
      cpu_limit      = "1500m"
      memory_limit   = "1024Mi"
      env = [
        { name = "KAFKA_LISTENERS", value = "LC://:29092,LX://:9092", config_map = null, key = null },
        { name = "KAFKA_ADVERTISED_LISTENERS", value = "LC://kafka:29092,LX://kafka:9092", config_map = null, key = null },
        { name = "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP", value = "LC:PLAINTEXT,LX:PLAINTEXT", config_map = null, key = null },
        { name = "KAFKA_INTER_BROKER_LISTENER_NAME", value = "LC", config_map = null, key = null },
        { name = "KAFKA_ZOOKEEPER_CONNECT", value = "zookeeper:2181", config_map = null, key = null },
        { name = "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR", value = "1", config_map = null, key = null },
        { name = "KAFKA_HEAP_OPTS", value = "-Xmx384m", config_map = null, key = null },
      ]
    }

    postgres = {
      image          = var.postgres_image
      label_key      = "role"
      ports          = [{ name = "postgres", port = 5432, target = 5432 }]
      cpu_request    = "250m"
      memory_request = "256Mi"
      cpu_limit      = "1000m"
      memory_limit   = "512Mi"
      env = [
        { name = "POSTGRES_USER", value = "eventuate", config_map = null, key = null },
        { name = "POSTGRES_PASSWORD", value = "eventuate", config_map = null, key = null },
        { name = "POSTGRES_HOST_AUTH_METHOD", value = "trust", config_map = null, key = null },
      ]
    }

    mongodb = {
      image          = var.mongodb_image
      label_key      = "role"
      ports          = [{ name = "mongodb", port = 27017, target = 27017 }]
      cpu_request    = "250m"
      memory_request = "256Mi"
      cpu_limit      = "1000m"
      memory_limit   = "512Mi"
      env            = []
    }
  }

  # ServiceMonitors are created for every service that exposes /actuator/prometheus.
  monitored_services = keys(local.services)

  run_infrastructure = var.deploy_infrastructure
  run_observability  = var.deploy_observability
  run_postgres_init  = var.init_postgres && var.deploy_infrastructure
}
