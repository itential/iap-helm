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

#### AWS Application Load Balancer (ALB)

This load balancing solution uses AWS Application Load Balancer through the AWS Load Balancer Controller.

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

**SSL/TLS Certificate Configuration:**

For SSL/TLS termination at the ALB level, specify an AWS Certificate Manager (ACM) certificate using the `certificate-arn` annotation:

```yaml
annotations:
  alb.ingress.kubernetes.io/certificate-arn: "arn:aws:acm:region:account-id:certificate/certificate-id"
```

The `certificate-arn` annotation:
- Specifies the ARN (Amazon Resource Name) of an ACM certificate
- Enables SSL/TLS termination at the load balancer
- Supports multiple certificates by providing comma-separated ARNs
- The certificate must be in the same AWS region as the ALB
- Requires the ALB to have HTTPS listeners configured (via `listen-ports`)

**Example with certificate:**

```yaml
ingress:
  annotations:
    alb.ingress.kubernetes.io/certificate-arn: "arn:aws:acm:us-east-1:123456789012:certificate/12345678-1234-1234-1234-123456789012"
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
    alb.ingress.kubernetes.io/ssl-policy: "ELBSecurityPolicy-TLS-1-2-2017-01"
```

#### HAProxy - Bare-Metal / On-Premises Option

The HAProxy Kubernetes Ingress Controller is a high-performance, enterprise-grade ingress controller well suited to bare-metal and on-premises clusters. Because IAP terminates TLS at the pod (port 443), HAProxy must be configured to re-encrypt the backend connection — it terminates TLS from the client, then reconnects to the IAP pod over HTTPS.

**Step 1 — Install HAProxy Kubernetes Ingress Controller:**

```bash
helm repo add haproxytech https://haproxytech.github.io/helm-charts
helm repo update
helm install haproxy-ingress haproxytech/kubernetes-ingress \
  --namespace haproxy-controller \
  --create-namespace \
  --set controller.ingressClass=haproxy \
  --set controller.ingressClassResource.enabled=true \
  --set controller.ingressClassResource.name=haproxy \
  --set controller.ingressClassResource.isDefaultClass=false
```

**TLS certificate considerations:**

`haproxy.org/server-ssl-verify: "none"` only affects the **backend connection** (HAProxy → IAP pod). It has no effect on the **frontend connection** (client browser → HAProxy), which uses the certificate from `iap-tls-secret`. Clients only ever see the frontend certificate.

| Connection | Certificate | Verified by |
|---|---|---|
| Client → HAProxy | `iap-tls-secret` (customer-provided or CA-signed) | Client browser |
| HAProxy → IAP pod | Self-signed (pod-level) | Skipped via `server-ssl-verify: none` |

This is a common and accepted pattern. Pod IPs and their derived DNS names are ephemeral — they change on every pod restart — making it impractical to maintain a static certificate for backend pods. The recommended approach is to skip verification for the backend and ensure the frontend certificate presented to clients is properly signed.

**Step 2 — Helm values configuration:**

```yaml
ingress:
  enabled: true
  className: "haproxy"
  loadBalancer:
    enabled: true
    host: iap.example.com
    path: /
  directAccess:
    enabled: true
    baseDomain: example.com
    path: /
  annotations:
    # Re-encrypt to backend IAP pods over HTTPS (IAP terminates TLS at the pod)
    haproxy.org/server-ssl: "true"
    # Skip backend certificate verification — IAP pods use self-signed certs without pod IP SANs
    haproxy.org/server-ssl-verify: "none"
    # Redirect HTTP to HTTPS
    haproxy.org/ssl-redirect: "true"
    # Cookie-based session affinity — required for IAP UI actions that must reach the same pod
    haproxy.org/cookie-persistence: "iap-server"
    # Connection and request timeouts
    haproxy.org/timeout-connect: "5s"
    haproxy.org/timeout-client: "300s"
    haproxy.org/timeout-server: "300s"
    # WebSocket tunnel timeout — keep alive for long-lived WebSocket connections
    haproxy.org/timeout-tunnel: "3600s"
    # TCP health check for backend IAP pods — do not use haproxy.org/check-http here.
    # check-http applies to every backend in the Ingress, including the /ws WebSocket backend
    # on port 8080. The WebSocket server does not respond to HTTP GETs, so an HTTP health check
    # causes HAProxy to mark that backend as DOWN and return 503 for WebSocket connections.
    # Using check alone falls back to a TCP health check, which works for both backends.
    haproxy.org/check: "true"
  tls:
    secretName: iap-tls-secret
```

> **WebSocket support (IAG5/Gateway Manager):** When `useWebSockets: true` is set, the IAP chart renders a single Ingress with two backends: `/` → port 443 (HTTPS) and `/ws` → port 8080 (WSS). HAProxy applies `haproxy.org/server-ssl: "true"` to every backend in the Ingress object — this correctly re-encrypts both the main application traffic and the WebSocket traffic to the IAP pod.

> **Cloud environments:** On EKS, GKE, or AKS, HAProxy's `LoadBalancer` service is automatically assigned an external IP by the cloud provider. No additional configuration is needed.

> **Bare-metal environments:** Without a cloud provider, the `LoadBalancer` service will remain in `<pending>` state. Install [MetalLB](https://metallb.universe.tf/) to assign external IPs, or consult your cluster administrator for how external traffic is routed to the cluster.

---

#### Traefik - Bare-Metal / On-Premises Option

Traefik is a cloud-native ingress controller well suited to bare-metal and on-premises Kubernetes clusters. Because IAP terminates TLS at the pod (port 443), Traefik must be configured to re-encrypt the backend connection — it terminates TLS from the client, then reconnects to the IAP pod over HTTPS.

**Step 1 — Install Traefik:**

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm install traefik traefik/traefik \
  --namespace traefik \
  --create-namespace \
  --set ingressClass.enabled=true \
  --set ingressClass.isDefaultClass=false \
  --set "additionalArguments[0]=--serversTransport.insecureSkipVerify=true"
```

The `--serversTransport.insecureSkipVerify=true` flag tells Traefik to skip TLS certificate verification when connecting to backend pods. This is required because IAP pods use self-signed certificates that do not include pod IP SANs.

> **Note:** In Traefik v3, the `ServersTransport` CRD annotation (`traefik.ingress.kubernetes.io/service.serversTransport`) on standard Kubernetes Ingress objects does not reliably apply per-service backend TLS settings. The global `--serversTransport.insecureSkipVerify=true` flag is the recommended approach for IAP deployments.

**TLS certificate considerations:**

`insecureSkipVerify` only affects the **backend connection** (Traefik → IAP pod). It has no effect on the **frontend connection** (client browser → Traefik), which uses the certificate from `iap-tls-secret`. Clients only ever see the frontend certificate.

| Connection | Certificate | Verified by |
|---|---|---|
| Client → Traefik | `iap-tls-secret` (customer-provided or CA-signed) | Client browser |
| Traefik → IAP pod | Self-signed (pod-level) | Skipped via `insecureSkipVerify` |

This is a common and accepted pattern. If a customer provides a CA-signed certificate that includes pod DNS names as SANs, `insecureSkipVerify` can be removed. However, pod IPs and their derived DNS names (e.g., `10-200-2-131.na.pod.cluster.local`) are ephemeral — they change on every pod restart — making it impractical to maintain a static certificate for them. The recommended approach is to keep `insecureSkipVerify=true` for the backend and ensure the frontend certificate presented to clients is properly signed.

**Step 2 — Apply the ServersTransport CRD** (namespace-scoped, required for Traefik to identify the backend transport configuration):

```bash
kubectl apply -f - <<EOF
apiVersion: traefik.io/v1alpha1
kind: ServersTransport
metadata:
  name: iap-servers-transport
  namespace: <your-namespace>
spec:
  insecureSkipVerify: true
EOF
```

**Step 3 — Helm values configuration:**

```yaml
ingress:
  enabled: true
  className: "traefik"
  loadBalancer:
    enabled: true
    host: iap.example.com
    path: /
  directAccess:
    enabled: true
    baseDomain: example.com
    path: /
  annotations:
    # Route incoming traffic through the HTTPS (websecure) entrypoint
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    # Enable TLS on this router
    traefik.ingress.kubernetes.io/router.tls: "true"
    # Reference the ServersTransport CRD — format: <namespace>-<name>@kubernetescrd
    # If deploying to the default namespace, use: default-iap-servers-transport@kubernetescrd
    traefik.ingress.kubernetes.io/service.serversTransport: <namespace>-iap-servers-transport@kubernetescrd
  tls:
    secretName: iap-tls-secret
```

> **Cloud environments:** On EKS, GKE, or AKS, Traefik's `LoadBalancer` service is automatically assigned an external IP by the cloud provider. No additional configuration is needed.

> **Bare-metal environments:** Without a cloud provider, the `LoadBalancer` service will remain in `<pending>` state. Install [MetalLB](https://metallb.universe.tf/) to assign external IPs, or consult your cluster administrator for how external traffic is routed to the cluster.

> **WebSocket support:** Traefik supports WebSockets natively. No additional annotation is required.

---

### Backend SSL Behavior by Controller

IAP pods terminate TLS internally at port 3443 (self-signed certificates). Every ingress controller must re-encrypt the backend connection it terminates TLS from the client and then reconnects to the IAP pod over HTTPS. How each controller handles this, and how granular that configuration is, differs significantly.

| Controller | How Backend SSL is Configured | Granularity |
|---|---|---|
| **ALB** | `alb.ingress.kubernetes.io/backend-protocol: HTTPS` annotation | Per-Ingress |
| **HAProxy** | `haproxy.org/server-ssl: "true"` annotation | Per-Ingress object (applies to all backends in the Ingress) |
| **Traefik** | Global `--serversTransport.insecureSkipVerify=true` startup flag | Global (all backends) |

#### WebSocket (IAG5/Gateway Manager) Backend SSL

When `useWebSockets: true` is set, the IAP chart renders a single Ingress with two backends:

- `/` → `iap-service:443` — speaks HTTPS
- `/ws` → `iap-service:8080` — speaks WSS (WebSocket Secure)

Both backends require backend SSL re-encryption. All supported controllers handle this correctly in a single Ingress — no separate Ingress or special per-path configuration is needed.

---

#### Load Balancer Comparison

> **Note:** Ingress NGINX is not included below. Kubernetes SIG Network has announced its retirement — best-effort maintenance has ended as of March 2026, with no further releases or security fixes. Existing deployments will continue to function, but new deployments should use one of the supported options below.

| Controller | Provider | Backend HTTPS | Backend SSL Granularity | SSL Termination | WebSocket + SSL mix | WebSocket Support | Session Affinity | Health Checks | Pod-Level Routing | Prerequisite CRD | Best For |
|------------|----------|---------------|-------------------------|-----------------|---------------------|-------------------|------------------|---------------|-------------------|------------------|----------|
| **ALB** | AWS Native | Annotation | Per-Ingress | At load balancer | Supported natively | Native | Target group level | Annotations | `target-type: ip` | None | AWS EKS |
| **HAProxy** | Self-hosted | Annotation | Per-Ingress object | At ingress (re-encrypt) | Supported natively | Native (tunnel timeout annotation) | Annotation (cookie) | Annotations | Default | None | Bare-metal / on-prem |
| **Traefik** | Self-hosted | Global flag | Global (all backends) | At ingress (re-encrypt) | Supported natively | Native | Middleware (sticky sessions) | Passive (via response codes) | Default | ServersTransport CRD | Bare-metal / on-prem |

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

Both access methods support TLS termination. Configure certificates using cert-manager or manually.

**Recommended: cluster-wide cert-manager.** Most enterprise environments run a shared cert-manager
instance managed by the platform team. Leave `certManager.enabled: false` (the default) and
reference it via the `issuer` and `certificate` values in your values file.

**Dev and test only: chart-managed cert-manager.** If no cluster-wide cert-manager is available,
set `certManager.enabled: true`. In this mode, use `--atomic` on every install and upgrade:

```bash
helm install iap ./charts/iap --atomic --timeout 10m -f values.yaml
```

Without `--atomic`, a timing issue between cert-manager's webhook pod becoming ready and the
webhook being fully initialized can cause the Ingress to be silently rejected while Helm still
reports `STATUS: deployed`. `--atomic` ensures that outcome is a hard failure instead.

The chart automatically generates the full list of TLS hostnames from your `loadBalancer` and `directAccess` configuration — there is no need to list hosts manually. Only the `secretName` is required:

```yaml
ingress:
  tls:
    secretName: iap-tls-secret
```

Given `replicaCount: 3`, `loadBalancer.host: iap.your-domain.com`, and `directAccess.hostOverride: iap-prod`, the chart will generate the following host list in the ingress TLS spec:

- `iap.your-domain.com` — load balancer hostname
- `iap-prod-0.your-domain.com` — direct access, pod 0
- `iap-prod-1.your-domain.com` — direct access, pod 1
- `iap-prod-2.your-domain.com` — direct access, pod 2

The `secretName` should reference a Kubernetes TLS secret containing the certificate and private key. This is typically the secret created by the `certificate` object in this chart (see `certificate.secretName`).

### Additional Hostnames

If you need to include hostnames beyond what the chart generates (e.g. a CDN endpoint, an admin hostname, or a secondary ingress address), add them under `hosts` in either form. The auto-generated hostnames are always included first, with any extra entries appended after:

```yaml
# Simplified form
ingress:
  tls:
    secretName: iap-tls-secret
    hosts:
      - "admin.your-domain.com"
      - "cdn.your-domain.com"
```

```yaml
# List form — use when multiple secrets are needed
ingress:
  tls:
    - secretName: iap-tls-secret
      hosts:
        - "admin.your-domain.com"
        - "cdn.your-domain.com"
```

> **Note:** Hosts listed here are **appended** to the auto-generated list — they do not replace it. There is no need to repeat the load balancer or direct access hostnames.

## Process Exporter Integration

When `processExporter.enabled` is `true`, direct access routes automatically include metrics endpoints:

- **Metrics Path**: `/metrics`
- **Port**: Process exporter port (default: 9256)
- **Protocol**: HTTP

This allows monitoring systems to scrape metrics from individual pod instances.

## Job Metrics Exporter Integration

When `jobMetricsExporter.enabled`, `jobMetricsExporter.ingressEnabled` and `ingress.directAccess.enabled` are all `true`, the Ingress gets one more rule for the exporter:

- **Host**: `<fullname>-<namespace>-job-metrics.<baseDomain>` (the same naming convention as direct access, using `ingress.directAccess.baseDomain`)
- **Path**: `/metrics`
- **Backend**: the `<fullname>-job-metrics-exporter` Service, port `job-metrics` (default 9477)

The exporter is one Deployment for the whole release, not one per pod, so there is a single host rather than one per replica.

> **Note:** The certificate's automatically generated hostname list does not include this host. When using TLS, provide the complete list yourself with `certificate.dnsNames` (a manual list replaces the generated one) and include this host.

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

