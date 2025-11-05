# Loki and Promtail Configuration

This document outlines the configuration options for Loki (log aggregation) and Promtail (log collection) components in the Itential Automation Platform Helm chart.

## Overview

Loki is a horizontally scalable, highly available log aggregation system inspired by Prometheus. Promtail is an agent which ships the contents of local logs to Loki. Together, they provide a complete log management solution for your IAP deployment.

## Loki Configuration

Loki aggregates and stores logs from various sources. It provides a query interface for searching and analyzing log data.

### Basic Loki Configuration in values.yaml

```yaml
loki:
  # Enable Loki for log collection
  enabled: true
  image:
    repository: grafana/loki
    tag: 2.9.0
    pullPolicy: IfNotPresent
  # Loki HTTP port
  httpPort: 3100
  # Loki GRPC port
  grpcPort: 9095
  # Storage configuration
  storage:
    storageClass: "gp3"
    size: "20Gi"
  # Resource limits and requests
  resources:
    limits:
      memory: "1Gi"
      cpu: "500m"
    requests:
      memory: "512Mi"
      cpu: "200m"
```

### Loki with External Access (Ingress)

```yaml
loki:
  enabled: true
  image:
    repository: grafana/loki
    tag: 2.9.0
  httpPort: 3100
  grpcPort: 9095
  storage:
    storageClass: "gp3"
    size: "50Gi"
  resources:
    limits:
      memory: "2Gi"
      cpu: "1000m"
    requests:
      memory: "1Gi"
      cpu: "500m"
  # External access configuration
  ingress:
    enabled: true
    className: "alb"
    host: "loki.example.com"
    annotations:
      alb.ingress.kubernetes.io/scheme: "internet-facing"
      alb.ingress.kubernetes.io/target-type: "ip"
      alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}]'
      alb.ingress.kubernetes.io/healthcheck-path: "/ready"
      alb.ingress.kubernetes.io/healthcheck-port: "3100"
      alb.ingress.kubernetes.io/healthcheck-protocol: "HTTP"
      alb.ingress.kubernetes.io/success-codes: "200"
      external-dns.alpha.kubernetes.io/ttl: "300"
```

## Promtail Configuration

Promtail is the log collection agent that ships logs to Loki. It runs as a DaemonSet on each node and collects logs from various sources.

### Basic Promtail Configuration in values.yaml

```yaml
promtail:
  # Enable Promtail for log shipping to Loki
  enabled: true
  image:
    repository: grafana/promtail
    tag: 2.9.0
    pullPolicy: IfNotPresent
  # Loki endpoint for Promtail to send logs to
  lokiUrl: "http://loki:3100/loki/api/v1/push"
  # Resource limits and requests
  resources:
    limits:
      memory: "256Mi"
      cpu: "200m"
    requests:
      memory: "128Mi"
      cpu: "100m"
```

### Promtail with External Loki Instance

```yaml
promtail:
  enabled: true
  image:
    repository: grafana/promtail
    tag: 2.9.0
  # External Loki endpoint
  lokiUrl: "https://loki.external.com/loki/api/v1/push"
  resources:
    limits:
      memory: "512Mi"
      cpu: "300m"
    requests:
      memory: "256Mi"
      cpu: "150m"
```

## Complete Logging Setup Example

Here's a complete example for enabling both Loki and Promtail with recommended production settings:

```yaml
# Production-ready Loki and Promtail configuration
loki:
  enabled: true
  image:
    repository: grafana/loki
    tag: 2.9.0
    pullPolicy: IfNotPresent
  httpPort: 3100
  grpcPort: 9095
  storage:
    storageClass: "gp3"
    size: "100Gi"
  resources:
    limits:
      memory: "4Gi"
      cpu: "2000m"
    requests:
      memory: "2Gi"
      cpu: "1000m"
  ingress:
    enabled: true
    className: "alb"
    host: "loki.itential.example.com"
    annotations:
      alb.ingress.kubernetes.io/scheme: "internet-facing"
      alb.ingress.kubernetes.io/target-type: "ip"
      alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'
      alb.ingress.kubernetes.io/certificate-arn: "arn:aws:acm:region:account:certificate/cert-id"
      alb.ingress.kubernetes.io/ssl-redirect: "443"
      alb.ingress.kubernetes.io/healthcheck-path: "/ready"
      alb.ingress.kubernetes.io/healthcheck-port: "3100"
      alb.ingress.kubernetes.io/success-codes: "200"

promtail:
  enabled: true
  image:
    repository: grafana/promtail
    tag: 2.9.0
    pullPolicy: IfNotPresent
  lokiUrl: "http://loki:3100/loki/api/v1/push"
  resources:
    limits:
      memory: "512Mi"
      cpu: "300m"
    requests:
      memory: "256Mi"
      cpu: "150m"
```

## Log Collection Targets

Promtail is configured to collect logs from multiple sources:

### IAP Application Logs
- **Source**: `/var/log/pods/namespace_iap-*_*/iap/*.log`
- **Format**: JSON structured logs with timestamp parsing
- **Labels**: `job=iap-logs`

### Kubernetes Pod Logs
- **Source**: All pods in the cluster via Kubernetes service discovery
- **Labels**: Automatically extracted from pod metadata including:
  - `app`: Application name
  - `instance`: Instance identifier
  - `component`: Component name
  - `namespace`: Kubernetes namespace
  - `pod`: Pod name
  - `container`: Container name
  - `node_name`: Node where pod is running

## Configuration Validation

After deploying with Loki and Promtail enabled, verify the setup:

1. **Check Loki status**:
   ```bash
   kubectl port-forward svc/loki 3100:3100
   curl http://localhost:3100/ready
   ```

2. **Check Promtail DaemonSet**:
   ```bash
   kubectl get daemonset promtail
   kubectl logs -l app.kubernetes.io/component=promtail
   ```

3. **Query logs via Loki**:
   ```bash
   curl -G -s "http://localhost:3100/loki/api/v1/query" --data-urlencode 'query={job="iap-logs"}'
   ```

## Key Features

| Feature | Loki | Promtail |
|---------|------|----------|
| **Purpose** | Log aggregation and storage | Log collection and shipping |
| **Deployment** | Single deployment/statefulset | DaemonSet (one per node) |
| **Storage** | Persistent volume required | Stateless |
| **Network** | HTTP/GRPC endpoints | Outbound HTTP to Loki |
| **Resource Usage** | Memory and CPU intensive | Lightweight agent |
| **Scaling** | Vertical scaling recommended | Horizontal (per node) |

## Performance Considerations

- **Loki Storage**: Use fast storage classes (gp3, io1) for better query performance
- **Memory Allocation**: Loki requires adequate memory for caching and query processing
- **Retention**: Configure log retention policies to manage storage growth
- **Network**: Ensure reliable network connectivity between Promtail and Loki