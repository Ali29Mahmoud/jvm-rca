# Kafka Partition Skew

## Symptoms
- One partition accumulates significantly higher lag or offset count than sibling partitions.
- A single consumer instance is saturated while others are idle.

## Diagnosis
1. Run `kafka_partition_skew` on the topic or consumer group.
2. Check `skew_ratio` and `hot_partitions`.

## Remediation
- Review the producer partition key strategy to avoid hot keys.
- Increase partition count and redistribute keys if a single entity dominates traffic.
