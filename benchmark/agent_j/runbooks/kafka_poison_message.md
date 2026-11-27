# Kafka Poison Message

## Symptoms
- Consumer pod repeatedly fails to deserialize or process a specific message offset.
- Consumer lag stalls on a single partition while pod logs show deserialization or unhandled exceptions.

## Diagnosis
1. Inspect consumer pod logs for serialization/deserialization or handler exceptions.
2. Run `kafka_group_describe` to confirm lag is stuck at a specific partition offset.

## Remediation
- Route malformed messages to a dead-letter topic (DLT) or skip the poison offset safely.
- Deploy a schema/deserialization fix for the consumer.
