#! /bin/bash -e

# docker compose style
# docker exec -it jvm-rca-postgres-1 psql -U eventuate -d eventuate "$@"


# K8s Cluster

kubectl exec -it -n eventuate-tram-examples-customers-and-orders \
$(kubectl get pod -l role=postgres -n eventuate-tram-examples-customers-and-orders -o jsonpath='{.items[0].metadata.name}') \
-- psql -U eventuate -d eventuate
