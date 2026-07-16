# IAP Helm — Pre-Install / Pre-Upgrade Environment Verification

Before running `helm install` or `helm upgrade`, every assertion in this document must pass.
A failing assertion means the environment is not ready and the install/upgrade will likely fail or produce a broken deployment.

The companion script `scripts/precheck.py` encodes these same checks as automated
pass/fail. It is pure Python 3 (standard library only) and shells out to the `kubectl`
and `openssl` binaries you already have — no `pip install` required, and it runs on
Linux, macOS, and Windows.

```bash
# Before a first install:
python3 scripts/precheck.py install -n <your-namespace> -f <your-values-file>

# Before an upgrade (install checks + PVC/certificate health):
python3 scripts/precheck.py upgrade -n <your-namespace> -f <your-values-file>
```

Environment-specific names (StorageClass, issuer, CA secret, image pull secret, etc.)
are read from the values file you pass with `-f`. Reading the values file needs
[PyYAML](https://pypi.org/project/PyYAML/) (`pip install pyyaml`); if it is not
installed, or you prefer not to pass a values file, supply the names with flags instead:

```bash
python3 scripts/precheck.py install -n <your-namespace> \
  --release <helm-release-name> \
  --storage-class <storageClass.name> \
  --issuer <certificate.issuerRef.name> --issuer-kind ClusterIssuer \
  --ca-secret <issuer.caSecretName> \
  --image-pull-secret <imagePullSecrets[0]>
```

Any flag overrides the corresponding value read from the file. A check whose name
cannot be resolved from either the values file or a flag is reported as `WARN` and
skipped rather than failing the run. Run `python3 scripts/precheck.py --help` for the
full flag list. Any `FAIL` exits with code 1, so the script can gate an install in CI.

To sanity-check the script itself — including the resource-name derivation it relies on —
without a cluster, run its built-in self-test (exits non-zero if any assertion fails):

```bash
python3 scripts/precheck.py --self-test
```

> **Example environment used in the assertions below:** namespace `md`, values file
> `values-perflab.yaml`. Replace `md` with your namespace in every manual command.

---

## 1. Required Secrets

### Why secrets must exist before install

The chart does **not** create application secrets — it only references them. If a secret is missing or has a wrong key, the StatefulSet pods will fail to start with `CreateContainerConfigError`. For TLS, the certificate will not be issued and the ingress will serve no traffic.

There are three secrets the chart depends on at install time:

| Secret | Namespace | Created by |
|---|---|---|
| `itential-platform-secrets` | your namespace | Operator (you), before install |
| `ecr-registry-secret` | your namespace | Operator (you), before install |
| CA secret (see §1g) | `cert-manager` | Operator (you), one-time cluster setup |

---

### 1a. `itential-platform-secrets` — exists

```bash
kubectl get secret itential-platform-secrets -n <your-namespace> \
  --output=jsonpath='{.metadata.name}' 2>/dev/null | grep -q "itential-platform-secrets" \
  && echo "PASS" || echo "FAIL: secret itential-platform-secrets not found"
```

### 1b. `itential-platform-secrets` — correct type

```bash
kubectl get secret itential-platform-secrets -n <your-namespace> \
  --output=jsonpath='{.type}' | grep -q "^Opaque$" \
  && echo "PASS" || echo "FAIL: secret type is not Opaque"
```

### 1c. `itential-platform-secrets` — all required keys present

The container loads this secret via `envFrom.secretRef`. Every key listed below must exist or the corresponding environment variable will be absent at runtime.

```bash
SECRET_DATA=$(kubectl get secret itential-platform-secrets -n <your-namespace> \
  --output=jsonpath='{.data}' 2>/dev/null || echo '{}')
echo "$SECRET_DATA" | python3 -c "
import sys, json
data = json.load(sys.stdin)
required = [
    'ITENTIAL_DEFAULT_USER_PASSWORD',
    'ITENTIAL_ENCRYPTION_KEY',
    'ITENTIAL_MONGO_PASSWORD',
    'ITENTIAL_MONGO_URL',
    'ITENTIAL_REDIS_PASSWORD',
    'ITENTIAL_REDIS_SENTINEL_PASSWORD',
]
missing = [k for k in required if k not in data]
print('PASS: all required keys present') if not missing else (print('FAIL: missing keys:', missing), sys.exit(1))
"
```

### 1d. `itential-platform-secrets` — keys are non-empty

A key that exists but holds an empty value is as broken as a missing key.

```bash
SECRET_DATA=$(kubectl get secret itential-platform-secrets -n <your-namespace> \
  --output=jsonpath='{.data}' 2>/dev/null || echo '{}')
echo "$SECRET_DATA" | python3 -c "
import sys, json, base64
data = json.load(sys.stdin)
required = [
    'ITENTIAL_DEFAULT_USER_PASSWORD',
    'ITENTIAL_ENCRYPTION_KEY',
    'ITENTIAL_MONGO_PASSWORD',
    'ITENTIAL_MONGO_URL',
    'ITENTIAL_REDIS_PASSWORD',
    'ITENTIAL_REDIS_SENTINEL_PASSWORD',
]
empty = [k for k in required if k in data and not base64.b64decode(data[k]).strip()]
print('PASS: all required keys are non-empty') if not empty else (print('FAIL: empty keys:', empty), sys.exit(1))
"
```

---

### 1e. `ecr-registry-secret` — exists with correct type

This is the image pull secret named in your values file under `imagePullSecrets`.
If it is absent, pods will fail with `ImagePullBackOff`.

> The secret name must match exactly what is set under `imagePullSecrets` in your values file.
> The example here uses `ecr-registry-secret`.

```bash
kubectl get secret ecr-registry-secret -n <your-namespace> \
  --output=jsonpath='{.type}' 2>/dev/null | grep -q "kubernetes.io/dockerconfigjson" \
  && echo "PASS" || echo "FAIL: ecr-registry-secret not found or wrong type"
```

### 1f. `ecr-registry-secret` — registry hostname is present

```bash
ECR_DATA=$(kubectl get secret ecr-registry-secret -n <your-namespace> \
  --output=jsonpath='{.data.\.dockerconfigjson}' 2>/dev/null || true)
echo "$ECR_DATA" | base64 -d | python3 -c "
import sys, json
cfg = json.load(sys.stdin)
auths = cfg.get('auths', {})
if not auths:
    print('FAIL: no registry entries in dockerconfigjson'); sys.exit(1)
print('PASS: registry entries found:', list(auths.keys()))
"
```

---

### 1g. CA secret — exists in cert-manager namespace

The `ClusterIssuer` used to sign IAP's TLS certificate is backed by a CA secret stored in the
`cert-manager` namespace. **The name of this secret is set in your values file** under
`issuer.caSecretName` (when `issuer.enabled: true`) or directly in your pre-existing ClusterIssuer
configuration when the issuer is managed outside the chart.

**How to find the CA secret name for your environment:**

```bash
# Option 1 — read it from your values file (issuer.caSecretName)
grep "caSecretName" values-<your-env>.yaml

# Option 2 — read it from the ClusterIssuer already installed in the cluster
kubectl get clusterissuer <your-issuer-name> \
  --output=jsonpath='{.spec.ca.secretName}'
```

Once you know the name, verify the secret exists and has the right type:

```bash
CA_SECRET=<secret-name-from-above>

kubectl get secret "$CA_SECRET" -n cert-manager \
  --output=jsonpath='{.type}' 2>/dev/null | grep -q "kubernetes.io/tls" \
  && echo "PASS" || echo "FAIL: CA secret $CA_SECRET not found in namespace cert-manager"
```

> **Example:** in the `values-perflab.yaml` environment the CA secret is named `itential-ca`
> and lives in the `cert-manager` namespace. Your environment may use a different name.

### 1h. CA secret — contains both tls.crt and tls.key

```bash
CA_SECRET=<secret-name-from-above>

CA_DATA=$(kubectl get secret "$CA_SECRET" -n cert-manager \
  --output=jsonpath='{.data}' 2>/dev/null || echo '{}')
echo "$CA_DATA" | python3 -c "
import sys, json
data = json.load(sys.stdin)
missing = [k for k in ['tls.crt', 'tls.key'] if k not in data or not data[k]]
print('PASS: CA secret has tls.crt and tls.key') if not missing else (print('FAIL: CA secret missing fields:', missing), sys.exit(1))
"
```

---

## 2. Persistent Volumes

### Why storage must be verified before install

The chart creates PersistentVolumeClaims (PVCs) as part of the StatefulSet's `volumeClaimTemplates`.
These PVCs are **not** deleted when the release is uninstalled — they persist and are rebound on reinstall.
Before a fresh install the StorageClass must exist. Before an upgrade the existing PVCs must be Bound.

**StorageClass used:** set in your values file under `storageClass.name` (example: `longhorn`)
**PVC naming pattern:** `{claim-name}-{release-name}-{pod-index}`
**Expected PVCs (replicaCount: 2, release name: `iap`):**

| PVC | Mount path in pod |
|---|---|
| `iap-assets-volume-iap-0` | `/opt/itential/platform/services/custom` |
| `iap-assets-volume-iap-1` | `/opt/itential/platform/services/custom` |
| `iap-logs-volume-iap-0` | `/var/log/itential` |
| `iap-logs-volume-iap-1` | `/var/log/itential` |

> PVC count scales with `replicaCount`. Adjust the list if your replica count differs.

---

### PRE-INSTALL checks

#### 2a. StorageClass exists

Replace `longhorn` with the value of `storageClass.name` in your values file.

```bash
STORAGE_CLASS=longhorn   # set to your storageClass.name value

kubectl get storageclass "$STORAGE_CLASS" \
  --output=jsonpath='{.metadata.name}' 2>/dev/null | grep -q "$STORAGE_CLASS" \
  && echo "PASS" || echo "FAIL: StorageClass $STORAGE_CLASS not found"
```

#### 2b. StorageClass provisioner is correct

```bash
STORAGE_CLASS=longhorn

kubectl get storageclass "$STORAGE_CLASS" \
  --output=jsonpath='{.provisioner}' 2>/dev/null
# Verify the output matches the provisioner expected for your storage backend
# e.g. driver.longhorn.io for Longhorn, ebs.csi.aws.com for AWS EBS
```

#### 2c. No stale PVCs from a previous release blocking the install

StatefulSet PVCs that are stuck in `Terminating` or `Lost` will block pod scheduling.

```bash
kubectl get pvc -n <your-namespace> \
  --output=jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\n"}{end}' | \
grep -E "Terminating|Lost" \
  && echo "FAIL: stale PVCs found — resolve before installing" || echo "PASS: no stale PVCs"
```

---

### PRE-UPGRADE checks

#### 2d. All expected PVCs exist

```bash
for PVC in iap-assets-volume-iap-0 iap-assets-volume-iap-1 \
           iap-logs-volume-iap-0   iap-logs-volume-iap-1; do
  kubectl get pvc "$PVC" -n <your-namespace> --no-headers 2>/dev/null \
    && echo "PASS: $PVC" \
    || echo "FAIL: $PVC not found"
done
```

#### 2e. All PVCs are Bound

A PVC in any state other than `Bound` means the backing volume is unavailable.
Proceeding with an upgrade while a PVC is `Pending` or `Lost` will leave the pod unschedulable.

```bash
PVC_PHASES=$(kubectl get pvc -n <your-namespace> \
  --output=jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\n"}{end}' 2>/dev/null)
echo "$PVC_PHASES" | python3 -c "
import sys
lines = [l for l in sys.stdin.read().strip().splitlines() if l]
failed = [(n, s) for n, s in (l.split('\t') for l in lines) if s != 'Bound']
if failed:
    [print(f'FAIL: {n} is {s}') for n, s in failed]; sys.exit(1)
print(f'PASS: all {len(lines)} PVCs are Bound')
"
```

#### 2f. PVCs are on the expected StorageClass

```bash
STORAGE_CLASS=longhorn   # set to your storageClass.name value

PVC_SC=$(kubectl get pvc -n <your-namespace> \
  --output=jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.storageClassName}{"\n"}{end}' 2>/dev/null)
echo "$PVC_SC" | python3 -c "
import sys, os
sc = os.environ['STORAGE_CLASS']
lines = [l for l in sys.stdin.read().strip().splitlines() if l]
wrong = [(n, s) for n, s in (l.split('\t') for l in lines) if s != sc]
if wrong:
    [print(f'FAIL: {n} is on StorageClass \"{s}\", expected {sc}') for n, s in wrong]; sys.exit(1)
print(f'PASS: all {len(lines)} PVCs are on StorageClass {sc}')
" STORAGE_CLASS="$STORAGE_CLASS"
```

---

## 3. cert-manager

### How cert-manager is used in this deployment

cert-manager is **not** installed by this chart (`certManager.enabled: false`). It is expected to be
a shared cluster-wide installation managed by the platform team. The chart only creates a `Certificate`
resource — cert-manager fulfills it by reading the `ClusterIssuer`, signing the certificate against
the CA secret, and writing the result into the TLS secret that IAP pods mount.

```
ClusterIssuer/<issuer-name>  ──references──►  secret/<ca-secret>  (ns: cert-manager)
        │
        └── fulfills ──►  Certificate/iap-tls  (ns: your-namespace)
                                │
                                └── writes ──►  secret/<tls-secret>  (ns: your-namespace)
                                                        │
                                                        └── mounted into IAP pods at
                                                            /etc/ssl/platform/
```

The ClusterIssuer name, CA secret name, and TLS secret name all come from your values file:

| Values field | Purpose |
|---|---|
| `certificate.issuerRef.name` | Name of the ClusterIssuer to use |
| `certificate.issuerRef.kind` | `ClusterIssuer` or `Issuer` |
| `issuer.caSecretName` | CA secret referenced by the issuer (when `issuer.enabled: true`) |
| `certificate.secretName` | TLS secret cert-manager will write into your namespace |
| `certificate.dnsNames` | SANs the certificate must cover |

---

### 3a. cert-manager pods are running

```bash
kubectl get pods -n cert-manager --no-headers | python3 -c "
import sys
lines = sys.stdin.read().strip().splitlines()
not_running = [l for l in lines if l and 'Running' not in l]
if not_running:
    [print('FAIL:', l) for l in not_running]; sys.exit(1)
print(f'PASS: all {len(lines)} cert-manager pods are Running')
"
```

### 3b. All three cert-manager components are present

```bash
NAMES=$(kubectl get pods -n cert-manager --no-headers \
  --output=custom-columns=NAME:.metadata.name 2>/dev/null | tr '\n' ' ')
for COMPONENT in "cert-manager" "cainjector" "webhook"; do
  echo "$NAMES" | grep -q "$COMPONENT" \
    && echo "PASS: $COMPONENT present" \
    || echo "FAIL: $COMPONENT not found"
done
```

### 3c. cert-manager CRDs are installed

The chart applies a `Certificate` resource. If the CRD is absent the install fails immediately.

```bash
for CRD in certificates.cert-manager.io clusterissuers.cert-manager.io; do
  kubectl get crd "$CRD" --output=jsonpath='{.metadata.name}' 2>/dev/null | grep -q "$CRD" \
    && echo "PASS: CRD $CRD installed" \
    || echo "FAIL: CRD $CRD not found — is cert-manager installed cluster-wide?"
done
```

### 3d. ClusterIssuer exists

Replace `iap-ca-issuer` with the value of `certificate.issuerRef.name` in your values file.

```bash
ISSUER_NAME=iap-ca-issuer   # set to certificate.issuerRef.name in your values file

kubectl get clusterissuer "$ISSUER_NAME" \
  --output=jsonpath='{.metadata.name}' 2>/dev/null | grep -q "$ISSUER_NAME" \
  && echo "PASS" || echo "FAIL: ClusterIssuer $ISSUER_NAME not found"
```

### 3e. ClusterIssuer is Ready

```bash
ISSUER_NAME=iap-ca-issuer

kubectl get clusterissuer "$ISSUER_NAME" \
  --output=jsonpath='{.status.conditions[?(@.type=="Ready")].status}' | grep -q "True" \
  && echo "PASS" || echo "FAIL: ClusterIssuer $ISSUER_NAME is not Ready"
```

### 3f. ClusterIssuer references the expected CA secret

```bash
ISSUER_NAME=iap-ca-issuer

kubectl get clusterissuer "$ISSUER_NAME" \
  --output=jsonpath='{.spec.ca.secretName}'
# Verify the output matches the CA secret name you provided in your cluster setup
```

---

### PRE-UPGRADE only: Certificate and TLS secret are healthy

#### 3g. Certificate `iap-tls` is Ready

```bash
kubectl get certificate iap-tls -n <your-namespace> \
  --output=jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q "True" \
  && echo "PASS" || echo "FAIL: Certificate iap-tls is not Ready — cert-manager may not have fulfilled it"
```

#### 3h. TLS secret exists and has all three keys

The secret name is read from the `Certificate` spec — adapts to any environment.

```bash
CERT_JSON=$(kubectl get certificate iap-tls -n <your-namespace> --output=json 2>/dev/null || echo '{}')
CERT_SECRET=$(echo "$CERT_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('spec',{}).get('secretName',''))")

TLS_DATA=$(kubectl get secret "$CERT_SECRET" -n <your-namespace> \
  --output=jsonpath='{.data}' 2>/dev/null || echo '{}')
echo "$TLS_DATA" | python3 -c "
import sys, json, os
secret = os.environ['CERT_SECRET']
data = json.load(sys.stdin)
missing = [k for k in ['tls.crt', 'tls.key', 'ca.crt'] if k not in data or not data[k]]
print(f'PASS: {secret} has tls.crt, tls.key, ca.crt') if not missing else (print(f'FAIL: {secret} missing fields:', missing), sys.exit(1))
" CERT_SECRET="$CERT_SECRET"
```

#### 3i. TLS certificate is not expired and covers all hostnames declared in the Certificate spec

Both the TLS secret name and the expected hostnames are read from the live `Certificate` spec —
no hardcoded values. This adapts automatically to any customer environment.

```bash
CERT_JSON=$(kubectl get certificate iap-tls -n <your-namespace> --output=json 2>/dev/null || echo '{}')
CERT_SECRET=$(echo "$CERT_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('spec',{}).get('secretName',''))")
CERT_HOSTS=$(echo "$CERT_JSON" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('spec',{}).get('dnsNames',[])))")
export CERT_SECRET CERT_HOSTS

TLS_CRT=$(kubectl get secret "$CERT_SECRET" -n <your-namespace> \
  --output=jsonpath='{.data.tls\.crt}' 2>/dev/null || true)
echo "$TLS_CRT" | base64 -d | python3 -c "
import sys, subprocess, datetime, re, os
cert_pem = sys.stdin.buffer.read()
result = subprocess.run(['openssl', 'x509', '-noout', '-text'], input=cert_pem, capture_output=True)
text = result.stdout.decode()
not_after = re.search(r'Not After\s*:\s*(.+)', text)
if not_after:
    expiry = datetime.datetime.strptime(not_after.group(1).strip(), '%b %d %H:%M:%S %Y %Z')
    days_left = (expiry - datetime.datetime.utcnow()).days
    if days_left < 2:
        print(f'FAIL: certificate expires in {days_left} day(s) on {expiry.date()}'); sys.exit(1)
    print(f'PASS: certificate valid for {days_left} more day(s), expires {expiry.date()}')
else:
    print('FAIL: could not parse certificate expiry'); sys.exit(1)
expected = [h for h in os.environ.get('CERT_HOSTS','').split(',') if h]
if not expected:
    print('FAIL: could not read dnsNames from Certificate spec'); sys.exit(1)
missing = [h for h in expected if h not in text]
if missing:
    print('FAIL: certificate does not cover hostnames declared in Certificate spec:', missing); sys.exit(1)
print(f'PASS: certificate covers all {len(expected)} hostnames:', ', '.join(expected))
"
```

---

## Summary table

| # | Assertion | Pre-install | Pre-upgrade |
|---|---|:---:|:---:|
| 1a | `itential-platform-secrets` exists | ✓ | ✓ |
| 1b | `itential-platform-secrets` type is Opaque | ✓ | ✓ |
| 1c | All 6 required keys present | ✓ | ✓ |
| 1d | All 6 required keys non-empty | ✓ | ✓ |
| 1e | Image pull secret exists with correct type | ✓ | ✓ |
| 1f | Image pull secret registry hostname present | ✓ | ✓ |
| 1g | CA secret exists in cert-manager namespace | ✓ | ✓ |
| 1h | CA secret has tls.crt and tls.key | ✓ | ✓ |
| 2a | StorageClass exists | ✓ | ✓ |
| 2b | StorageClass provisioner matches expected | ✓ | ✓ |
| 2c | No stale PVCs in Terminating or Lost state | ✓ | ✓ |
| 2d | All expected PVCs exist | — | ✓ |
| 2e | All PVCs are Bound | — | ✓ |
| 2f | All PVCs are on the expected StorageClass | — | ✓ |
| 3a | cert-manager pods are Running | ✓ | ✓ |
| 3b | All 3 cert-manager components present | ✓ | ✓ |
| 3c | cert-manager CRDs installed | ✓ | ✓ |
| 3d | ClusterIssuer exists | ✓ | ✓ |
| 3e | ClusterIssuer is Ready | ✓ | ✓ |
| 3f | ClusterIssuer references expected CA secret | ✓ | ✓ |
| 3g | Certificate `iap-tls` is Ready | — | ✓ |
| 3h | TLS secret has all 3 TLS keys | — | ✓ |
| 3i | TLS cert not expired, covers all declared hostnames | — | ✓ |
