SHELL     := /bin/bash
export PATH := $(HOME)/.local/bin:$(PATH)

CLUSTER_NAME := jvm-rca
NAMESPACE    := eventuate-tram-examples-customers-and-orders
MONITORING_NAMESPACE := monitoring
GW_PORT      := 8085

# Terraform module that deploys infrastructure, application and observability
TERRAFORM_DIR := deployment/terraform_kind
TF            ?= terraform
TF_REQUIRED    = command -v $(TF) >/dev/null 2>&1 || { \
	echo "✗ $(TF) not found in PATH; install it: https://developer.hashicorp.com/terraform/install" >&2; \
	exit 1; \
}

# All images that must exist in the kind node
IMAGES := \
	eventuateexamples/eventuate-tram-examples-customers-and-orders-customer-service:latest \
	eventuateexamples/eventuate-tram-examples-customers-and-orders-order-service:latest \
	eventuateexamples/eventuate-tram-examples-customers-and-orders-order-history-service:latest \
	eventuateexamples/eventuate-tram-examples-customers-and-orders-api-gateway-service:latest \
	eventuateio/eventuate-cdc-service:0.20.0.RELEASE \
	eventuateio/eventuate-kafka:0.20.0.RELEASE \
	eventuateio/eventuate-postgres:0.22.0.RELEASE \
	eventuateio/eventuate-zookeeper:0.22.0.RELEASE \
	mongo:5.0.6 \
	otel/opentelemetry-collector:0.115.1 \
	grafana/tempo:2.7.1 \
	ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.20.1

.PHONY: all up down status test images cluster-create load load-images \
        deploy-infra init-postgres deploy-monitoring deploy-apps wait-healthy wait-ready \
        tf-init tf-apply help

## Default target
all: up

## Build application microservice images and ensure all required images exist locally
images:
	@echo "Building application microservice images..."
	@for svc in api-gateway-service customer-service order-service order-history-service; do \
		echo "Building $$svc..."; \
		docker build \
			--build-arg baseImageVersion=0.3.0.RELEASE \
			--build-arg serviceImageVersion=0.1.0-SNAPSHOT \
			-t eventuateexamples/eventuate-tram-examples-customers-and-orders-$$svc:latest \
			-f $$svc/$$svc-main/Dockerfile \
			$$svc/$$svc-main/ || exit 1; \
	done
	@echo "Checking infrastructure images..."
	@for img in $(IMAGES); do \
		if ! docker image inspect "$$img" >/dev/null 2>&1; then \
			echo "Pulling missing image: $$img..."; \
			docker pull "$$img" || exit 1; \
		fi; \
	done
	@echo "All images present in local daemon."

## Create the kind cluster (no-op if already exists)
cluster-create:
	@if kind get clusters 2>/dev/null | grep -q "^$(CLUSTER_NAME)$$"; then \
		echo "Kind cluster '$(CLUSTER_NAME)' already exists."; \
	else \
		echo "Creating kind cluster '$(CLUSTER_NAME)'..."; \
		kind create cluster --name $(CLUSTER_NAME); \
		echo "Cluster created."; \
	fi

## Load all required images into the kind node
load-images: images cluster-create
	@echo "Loading images into kind node (this may take a few minutes)..."
	@kind load docker-image $(IMAGES) --name $(CLUSTER_NAME)
	@echo "Images loaded."

## Load all required images into the kind node (creates the cluster if needed)
load: load-images

## Initialise the Terraform module (downloads the kubernetes and helm providers)
tf-init:
	@$(TF_REQUIRED); \
	$(TF) -chdir=$(TERRAFORM_DIR) init -input=false

## Reconcile the cluster with the Terraform module
## First pass installs kube-prometheus-stack so its CRDs exist, second pass
## creates the ServiceMonitors and the rest of the stack in one graph.
tf-apply: load tf-init
	@echo "Applying Terraform (infrastructure, application, observability)..."; \
	$(TF) -chdir=$(TERRAFORM_DIR) apply -input=false -auto-approve \
		-target=helm_release.kube_prometheus_stack && \
	$(TF) -chdir=$(TERRAFORM_DIR) apply -input=false -auto-approve

## Apply namespace + ConfigMaps + infrastructure pods
deploy-infra: load-images
	@echo "Applying namespace and ConfigMaps..."
	@kubectl apply -f k8s-deployment/00-namespace-and-configs.yaml
	@echo "Deploying infrastructure (Zookeeper, Kafka, Postgres, MongoDB)..."
	@kubectl apply -f k8s-deployment/01-infrastructure.yaml

## Seed the Postgres flyway_schema_history so services don't re-run migrations
init-postgres: deploy-infra
	@echo "Waiting for Postgres pod to be Ready..."
	@kubectl wait --for=condition=ready pod -l role=postgres \
		-n $(NAMESPACE) --timeout=120s
	@echo "Waiting for PostgreSQL to accept connections..."
	@PG_POD=$$(kubectl get pod -l role=postgres -n $(NAMESPACE) \
		-o jsonpath='{.items[0].metadata.name}'); \
	for i in $$(seq 1 30); do \
		kubectl exec -n $(NAMESPACE) $$PG_POD -- \
			psql -U eventuate -d eventuate -c "SELECT 1" >/dev/null 2>&1 \
			&& break; \
		echo "   waiting for PostgreSQL socket... ($$i/30)"; \
		sleep 2; \
		if [ "$$i" = "30" ]; then \
			echo "✗ PostgreSQL did not accept connections in time" >&2; exit 1; \
		fi; \
	done
	@echo "Applying Postgres schema..."
	@PG_POD=$$(kubectl get pod -l role=postgres -n $(NAMESPACE) \
		-o jsonpath='{.items[0].metadata.name}'); \
	kubectl exec -i -n $(NAMESPACE) $$PG_POD -- \
		psql -U eventuate -d eventuate < k8s-deployment/postgres-schema.sql >/dev/null 2>&1 || true
	@echo "Seeding Postgres flyway schema history..."
	@PG_POD=$$(kubectl get pod -l role=postgres -n $(NAMESPACE) \
		-o jsonpath='{.items[0].metadata.name}'); \
	kubectl exec -i -n $(NAMESPACE) $$PG_POD -- \
		psql -U eventuate -d eventuate < k8s-deployment/init-postgres.sql
	@echo "Postgres initialised."

## Deploy Prometheus and Grafana monitoring stack via Helm
deploy-monitoring:
	@echo "Deploying Prometheus and Grafana monitoring stack..."
	@if ! helm status monitoring -n $(MONITORING_NAMESPACE) >/dev/null 2>&1; then \
		helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true; \
		helm repo update prometheus-community; \
		helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
			--namespace $(MONITORING_NAMESPACE) --create-namespace \
			--set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
			--set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false; \
	else \
		echo "Monitoring stack already deployed."; \
	fi

## Deploy application services, API Gateway, and ServiceMonitors
deploy-apps: init-postgres deploy-monitoring
	@echo "Deploying OpenTelemetry Collector..."
	@kubectl apply -f k8s-deployment/04-otel-collector.yaml
	@echo "Deploying application services and API Gateway..."
	@kubectl apply -f k8s-deployment/02-applications-and-gateway.yaml
	@echo "Deploying ServiceMonitors..."
	@kubectl apply -f k8s-deployment/03-service-monitors.yaml

## Block until every pod in the application and monitoring namespaces is Ready
## Uses a retry loop because kubectl wait resolves its pod list once: a pod
## replaced by a rolling update mid-wait otherwise makes it fail with NotFound.
wait-ready:
	@echo "Waiting for all application pods to be Ready (up to 3 min)..."
	@for i in $$(seq 1 36); do \
		if kubectl wait --for=condition=ready pod --all \
			-n $(NAMESPACE) --timeout=5s >/dev/null 2>&1; then \
			echo "Application pods Ready."; break; \
		fi; \
		if [ "$$i" = "36" ]; then \
			echo "✗ Application pods did not become Ready in time" >&2; \
			kubectl get pods -n $(NAMESPACE); exit 1; \
		fi; \
		sleep 5; \
	done
	@echo "Waiting for Prometheus and Grafana pods to be Ready (up to 5 min)..."
	@for i in $$(seq 1 60); do \
		if kubectl wait --for=condition=ready pod --all \
			-n $(MONITORING_NAMESPACE) --timeout=5s >/dev/null 2>&1; then \
			echo "Monitoring pods Ready."; break; \
		fi; \
		if [ "$$i" = "60" ]; then \
			echo "✗ Monitoring pods did not become Ready in time" >&2; \
			kubectl get pods -n $(MONITORING_NAMESPACE); exit 1; \
		fi; \
		sleep 5; \
	done
	@echo "All pods Ready."

## Deploy the stack with kubectl, then block until it is Ready
wait-healthy: deploy-apps wait-ready

## Spin up the full system from scratch: kind cluster, Terraform, application
up: tf-apply
	@set -e; \
	START=$$(date +%s); \
	$(MAKE) wait-ready; \
	END=$$(date +%s); \
	echo ""; \
	echo "========================================="; \
	echo "  System UP  —  elapsed: $$(( END - START )) s"; \
	echo "========================================="; \
	kubectl get pods -n $(NAMESPACE); \
	echo ""; \
	kubectl get pods -n $(MONITORING_NAMESPACE)

## Tear down the Terraform-managed resources and the entire kind cluster
down:
	@if [ -f $(TERRAFORM_DIR)/terraform.tfstate ]; then \
		$(TF_REQUIRED); \
		echo "Destroying Terraform-managed resources..."; \
		$(TF) -chdir=$(TERRAFORM_DIR) destroy -input=false -auto-approve; \
	else \
		echo "No Terraform state; skipping destroy."; \
	fi
	@echo "Deleting kind cluster '$(CLUSTER_NAME)'..."
	@kind delete cluster --name $(CLUSTER_NAME)
	@echo "Cluster deleted."

## Show pod status and node resource usage
status:
	@echo "=== Pods in $(NAMESPACE) ==="
	@kubectl get pods -n $(NAMESPACE) -o wide 2>/dev/null \
		|| echo "(cluster not running)"
	@echo ""
	@echo "=== Pods in $(MONITORING_NAMESPACE) ==="
	@kubectl get pods -n $(MONITORING_NAMESPACE) -o wide 2>/dev/null \
		|| echo "(monitoring not running)"
	@echo ""
	@echo "=== Kind node resource usage ==="
	@docker stats --no-stream \
		--format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}" \
		$$(docker ps --filter "name=$(CLUSTER_NAME)" -q) 2>/dev/null || true

## Run the end-to-end curl smoke test through the gateway port-forward
test:
	@bash run_flow.sh

## Print this help
help:
	@grep -E '^##' Makefile | sed 's/## /  /'
