ARG baseImageVersion=0.3.0.RELEASE
ARG otelJavaAgentVersion=2.20.1
FROM ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:$otelJavaAgentVersion AS otel
FROM eventuateio/eventuate-examples-docker-images-spring-example-base-image:$baseImageVersion
ARG jarDir=build/libs
ARG serviceImageVersion=0.1.0-SNAPSHOT
COPY $jarDir/order-history-service-main-$serviceImageVersion.jar service.jar
COPY --from=otel /javaagent.jar /otel/opentelemetry-javaagent.jar
ENV JAVA_TOOL_OPTIONS="-javaagent:/otel/opentelemetry-javaagent.jar"
