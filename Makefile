SHELL     := /bin/bash
export PATH := $(HOME)/.local/bin:$(PATH)

CLUSTER_NAME := jvm-rca
NAMESPACE    := eventuate-tram-examples-customers-and-orders
GW_PORT      := 8085

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
	mongo:5.0.6

.PHONY: all up down status test images cluster-create load-images \
        deploy-infra init-postgres deploy-apps wait-healthy help

## Default target
all: up

## Build any locally-built images that are missing (api-gateway)
images:
	@docker image inspect \
		eventuateexamples/eventuate-tram-examples-customers-and-orders-api-gateway-service:latest \
		>/dev/null 2>&1 \
	|| { \
		docker build \
			--build-arg baseImageVersion=0.3.0.RELEASE \
			--build-arg serviceImageVersion=0.1.0-SNAPSHOT \
			-t eventuateexamples/eventuate-tram-examples-customers-and-orders-api-gateway-service:latest \
			-f api-gateway-service/api-gateway-service-main/Dockerfile \
			api-gateway-service/api-gateway-service-main/; \
	}
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
	@echo "Seeding Postgres flyway schema history..."
	@PG_POD=$$(kubectl get pod -l role=postgres -n $(NAMESPACE) \
		-o jsonpath='{.items[0].metadata.name}'); \
	kubectl exec -i -n $(NAMESPACE) $$PG_POD -- \
		psql -U eventuate -d eventuate < k8s-deployment/init-postgres.sql
	@echo "Postgres initialised."

## Deploy application services and API Gateway
deploy-apps: init-postgres
	@echo "Deploying application services and API Gateway..."
	@kubectl apply -f k8s-deployment/02-applications-and-gateway.yaml

## Block until every pod in the namespace is Ready
wait-healthy: deploy-apps
	@echo "Waiting for all pods to be Ready (up to 3 min)..."
	@kubectl wait --for=condition=ready pod --all \
		-n $(NAMESPACE) --timeout=180s
	@echo "All pods Ready."

## Spin up the full system from scratch
up:
	@START=$$(date +%s); \
	$(MAKE) wait-healthy; \
	END=$$(date +%s); \
	echo ""; \
	echo "========================================="; \
	echo "  System UP  —  elapsed: $$(( END - START )) s"; \
	echo "========================================="; \
	kubectl get pods -n $(NAMESPACE)

## Tear down the entire kind cluster
down:
	@echo "Deleting kind cluster '$(CLUSTER_NAME)'..."
	@kind delete cluster --name $(CLUSTER_NAME)
	@echo "Cluster deleted."

## Show pod status and node resource usage
status:
	@echo "=== Pods in $(NAMESPACE) ==="
	@kubectl get pods -n $(NAMESPACE) -o wide 2>/dev/null \
		|| echo "(cluster not running)"
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
