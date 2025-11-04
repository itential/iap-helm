# Ingress Configuration for IAP

The IAP Helm chart provides comprehensive ingress configuration options to enable both load-balanced access and direct pod access for your Itential Automation Platform deployment.

## Overview

The ingress configuration supports two primary access patterns:

1. **Load Balancer Access**: Routes traffic to all IAP pods through a single hostname
2. **Direct Access**: Provides individual hostnames for each IAP pod instance

## Load Balancer Access

Load balancer access distributes incoming requests across all available IAP pods, providing high availability and load distribution.

### Configuration

```yaml
ingress:
  enabled: true
  loadBalancer:
    enabled: true
    host: "iap.example.com"
    path: "/"
```

### Features

- Automatic load distribution across all pods
- Single entry point for the application
- Supports WebSocket connections (when `useWebSockets` is enabled)
- Integrates with AWS ALB or other ingress controllers

### Load Balancer Options

The chart supports multiple ingress controllers. Choose the one that best fits your environment.

#### AWS Application Load Balancer (ALB) - Default Option

The default load balancing solution uses AWS Application Load Balancer through the AWS Load Balancer Controller.

**ALB Configuration Example:**

```yaml
ingress:
  enabled: true
  className: "alb"
  loadBalancer:
    enabled: true
    host: "iap.example.com"
  annotations:
    alb.ingress.kubernetes.io/backend-protocol: "HTTPS"
    alb.ingress.kubernetes.io/healthcheck-path: "/health/status?exclude-services=true"
    alb.ingress.kubernetes.io/healthcheck-port: "3443"
    alb.ingress.kubernetes.io/healthcheck-protocol: "HTTPS"
    alb.ingress.kubernetes.io/healthcheck-interval-seconds: "15"
    alb.ingress.kubernetes.io/healthcheck-timeout-seconds: "5"
    alb.ingress.kubernetes.io/healthy-threshold-count: "2"
    # Include port 8080 if using Gateway Manager with IAG5, otherwise remove it
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443},{"HTTPS": 8080}]'
    alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=60
    alb.ingress.kubernetes.io/load-balancer-name: "itential-example-lb"
    alb.ingress.kubernetes.io/scheme: "internet-facing"
    alb.ingress.kubernetes.io/success-codes: "200"
    alb.ingress.kubernetes.io/target-type: "ip"
    alb.ingress.kubernetes.io/unhealthy-threshold-count: "2"
    alb.ingress.kubernetes.io/websocket-paths: "/ws"
    alb.ingress.kubernetes.io/target-group-attributes: stickiness.enabled=true,stickiness.lb_cookie.duration_seconds=3600
```

#### NGINX Ingress Controller - Alternative Option

For environments where ALB is not available or preferred, NGINX Ingress Controller can be used as an alternative.

**NGINX Configuration Example:**

```yaml
ingress:
  enabled: true
  className: "nginx"
  loadBalancer:
    enabled: true
    host: "iap.example.com"
  annotations:    
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/use-regex: "true"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/affinity-mode: "persistent"
    nginx.ingress.kubernetes.io/session-cookie-name: "iap-server"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "3600"
    nginx.ingress.kubernetes.io/websocket-services: "iap-service"
```

#### Load Balancer Comparison

| Feature | ALB | NGINX |
|---------|-----|-------|
| **Provider** | AWS Native | Third-party |
| **SSL Termination** | At load balancer | At load balancer or pod |
| **WebSocket Support** | Native | Requires annotation |
| **Session Affinity** | Target group level | Cookie-based |
| **Health Checks** | Advanced AWS health checks | HTTP/HTTPS probes |

## Direct Access

Direct access allows you to connect to specific IAP pod instances. This is particularly useful for:

- Debugging specific pod instances
- Administrative tasks that require direct pod access
- UI actions that need direct pod connectivity
- Development and troubleshooting scenarios

### Default Hostname Generation

By default, direct access hostnames are generated using this pattern:

```
{iap.name}-{namespace}-{pod-index}.{baseDomain}
```

**Example Configuration:**
```yaml
ingress:
  directAccess:
    enabled: true
    baseDomain: "example.com"
```

**Generated Hostnames** (with `replicaCount: 3`, namespace `production`):
- `iap-production-0.example.com`
- `iap-production-1.example.com` 
- `iap-production-2.example.com`

### Custom Hostname Override

Use the `hostOverride` setting to customize the hostname prefix:

```yaml
ingress:
  directAccess:
    enabled: true
    baseDomain: "example.com"
    hostOverride: "iap-prod"
```

**Generated Hostnames** (with `replicaCount: 3`):
- `iap-prod-0.example.com`
- `iap-prod-1.example.com`
- `iap-prod-2.example.com`

### Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ingress.directAccess.enabled` | bool | `true` | Enable direct access to individual pods |
| `ingress.directAccess.baseDomain` | string | `"example.com"` | Base domain for generating hostnames |
| `ingress.directAccess.hostOverride` | string | `""` | Custom prefix for hostnames (optional) |
| `ingress.directAccess.path` | string | `"/"` | URL path for direct access routes |

## Complete Configuration Example

Here's a comprehensive example combining both access methods:

```yaml
ingress:
  enabled: true
  className: "alb"
  pathType: "Prefix"
  
  # Load balancer configuration
  loadBalancer:
    enabled: true
    host: "iap.your-domain.com"
    path: "/"
  
  # Direct access configuration
  directAccess:
    enabled: true
    baseDomain: "your-domain.com"
    hostOverride: "iap-prod"
    path: "/"
  
  # ALB-specific annotations
  annotations:
    alb.ingress.kubernetes.io/scheme: "internet-facing"
    alb.ingress.kubernetes.io/target-type: "ip"
    alb.ingress.kubernetes.io/backend-protocol: "HTTPS"
    alb.ingress.kubernetes.io/healthcheck-path: "/health/status"
```

## TLS Configuration

Both access methods support TLS termination. Configure certificates using cert-manager or manually:

```yaml
ingress:
  tls:
    - secretName: iap-tls-secret
      hosts:
        - "iap.your-domain.com"
        - "iap-prod-0.your-domain.com"
        - "iap-prod-1.your-domain.com"
        - "iap-prod-2.your-domain.com"
```

## Process Exporter Integration

When `processExporter.enabled` is `true`, direct access routes automatically include metrics endpoints:

- **Metrics Path**: `/metrics`
- **Port**: Process exporter port (default: 9256)
- **Protocol**: HTTP

This allows monitoring systems to scrape metrics from individual pod instances.

## Troubleshooting

### Common Issues

1. **Invalid hostname errors**: Ensure `hostOverride` doesn't contain invalid characters
2. **DNS resolution problems**: Verify your DNS provider supports the generated hostnames
3. **TLS certificate issues**: Make sure certificates cover all generated hostnames

### Validation

Test your configuration with:

```bash
# Generate template to verify hostnames
helm template iap charts/iap/ -f your-values.yaml | grep -A5 "host:"

# Test specific pod access
curl -k https://iap-prod-0.your-domain.com/health/status
```

