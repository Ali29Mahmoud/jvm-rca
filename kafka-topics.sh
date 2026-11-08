#! /bin/bash -e

docker exec -it jvm-rca-kafka-1 /usr/local/kafka_2.13-3.2.3/bin/kafka-topics.sh --bootstrap-server kafka:29092 "$@"


