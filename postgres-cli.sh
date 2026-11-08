#! /bin/bash -e

docker exec -it jvm-rca-postgres-1 psql -U eventuate -d eventuate "$@"

