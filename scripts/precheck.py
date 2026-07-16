#!/usr/bin/env python3
"""IAP Helm chart pre-install / pre-upgrade environment verification.

Runs the same assertions documented in docs/pre-install-verification.md as
automated pass/fail checks, so any customer can validate their environment
before `helm install` or `helm upgrade`.

Design goals:
  * Portable  -- pure Python 3 standard library + the `kubectl` and (for the
                 TLS expiry check) `openssl` binaries the operator already has.
                 No `pip install`. Runs on Linux, macOS, and Windows.
  * Zero editing -- environment-specific names (namespace, storage class,
                 issuer, secret names) are read from the Helm values file when
                 one is supplied. Any value can be overridden with a flag.

Usage:
    python3 scripts/precheck.py install -n my-namespace -f values-prod.yaml
    python3 scripts/precheck.py upgrade -n my-namespace -f values-prod.yaml

    # Without a values file, supply the names explicitly:
    python3 scripts/precheck.py install -n my-namespace \\
        --storage-class longhorn --issuer iap-ca-issuer --ca-secret itential-ca

Exit code is 0 when every assertion passes, 1 otherwise -- suitable for
gating an install in CI.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys

try:
    import yaml  # PyYAML -- optional; enables reading names from the values file.
    _HAVE_YAML = True
except ImportError:  # pragma: no cover - depends on the operator's environment
    _HAVE_YAML = False


# ── Result tracking ────────────────────────────────────────────────────────────

class Checker:
    """Accumulates PASS/FAIL/WARN results and prints them as they happen."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def ok(self, msg: str) -> None:
        print(f"  PASS  {msg}")
        self.passed += 1

    def bad(self, msg: str) -> None:
        print(f"  FAIL  {msg}")
        self.failed += 1

    def warn(self, msg: str) -> None:
        # A WARN never fails the run; it flags a check that could not be executed.
        print(f"  WARN  {msg}")

    def assert_(self, cond: bool, ok_msg: str, bad_msg: str) -> bool:
        (self.ok if cond else self.bad)(ok_msg if cond else bad_msg)
        return cond


def header(title: str) -> None:
    print(f"\n── {title} ──")


# ── kubectl / openssl helpers ────────────────────────────────────────────────

def kubectl(*args: str) -> tuple[int, str, str]:
    """Run kubectl and return (returncode, stdout, stderr), all stripped."""
    proc = subprocess.run(
        ["kubectl", *args], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def kubectl_json(*args: str) -> dict | None:
    """Run `kubectl ... -o json` and return the parsed object, or None on error."""
    rc, out, _ = kubectl(*args, "--output=json")
    if rc != 0 or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def current_namespace() -> str:
    rc, out, _ = kubectl(
        "config", "view", "--minify", "--output=jsonpath={..namespace}"
    )
    return out if rc == 0 and out else "default"


# ── Values-file resolution ────────────────────────────────────────────────────

class Config:
    """Effective configuration after merging flags > values file > defaults."""

    def __init__(self, args: argparse.Namespace) -> None:
        values = self._load_values(args.values)

        # Names used to derive resource names.
        chart_name = "iap"
        name_override = values.get("nameOverride")
        fullname_override = values.get("fullnameOverride")
        self.release = args.release
        self.fullname = self._fullname(
            self.release, chart_name, name_override, fullname_override
        )

        self.namespace = args.namespace or os.environ.get("NAMESPACE") or current_namespace()
        self.replica_count = int(values.get("replicaCount", 2))
        self.use_tls = _as_bool(values.get("useTLS", True))

        self.platform_secret = args.platform_secret or "itential-platform-secrets"

        # Image pull secret: --image-pull-secret > first imagePullSecrets entry.
        self.image_pull_secret = args.image_pull_secret or _first_pull_secret(values)

        # cert-manager / issuer / certificate.
        cert = values.get("certificate") or {}
        issuer = values.get("issuer") or {}
        issuer_ref = cert.get("issuerRef") or {}

        self.cert_manager_namespace = args.cert_manager_namespace or "cert-manager"
        self.issuer_name = args.issuer or issuer_ref.get("name") or issuer.get("name")
        self.issuer_kind = args.issuer_kind or issuer_ref.get("kind") or issuer.get("kind") or "ClusterIssuer"
        self.ca_secret = args.ca_secret or issuer.get("caSecretName")
        # cert-manager writes the release Certificate as "<fullname>-tls".
        self.certificate_name = f"{self.fullname}-tls"
        # TLS secret is read live from the Certificate spec at check time; the
        # values entry (certificate.secretName) is only a fallback.
        self.cert_secret_hint = args.cert_secret or cert.get("secretName") or ""

        self.storage_class = args.storage_class or (values.get("storageClass") or {}).get("name")

    @staticmethod
    def _load_values(path: str | None) -> dict:
        if not path:
            return {}
        if not _HAVE_YAML:
            print(
                "  WARN  PyYAML not installed -- cannot read the values file. "
                "Falling back to flags/defaults.\n"
                "        Install with `pip install pyyaml`, or pass names via flags.",
                file=sys.stderr,
            )
            return {}
        if not os.path.isfile(path):
            print(f"  WARN  values file not found: {path}", file=sys.stderr)
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    @staticmethod
    def _fullname(
        release: str,
        chart_name: str,
        name_override: str | None,
        fullname_override: str | None,
    ) -> str:
        """Replicate the `iap.fullname` helper from _helpers.tpl."""
        if fullname_override:
            return fullname_override[:63].rstrip("-")
        name = name_override or chart_name
        if name in release:
            return release[:63].rstrip("-")
        return f"{release}-{name}"[:63].rstrip("-")


def _as_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "on")


def _first_pull_secret(values: dict) -> str | None:
    secrets = values.get("imagePullSecrets") or []
    if not secrets:
        return None
    first = secrets[0]
    if isinstance(first, dict):
        return first.get("name")
    return str(first)


# ── Check groups ───────────────────────────────────────────────────────────────

def check_secrets(c: Checker, cfg: Config) -> None:
    header("1. Secrets")

    # 1a/1b — platform secret exists and is Opaque
    obj = kubectl_json("get", "secret", cfg.platform_secret, "-n", cfg.namespace)
    if obj is None:
        c.bad(f"{cfg.platform_secret} not found in namespace {cfg.namespace}")
    else:
        c.ok(f"{cfg.platform_secret} exists")
        c.assert_(
            obj.get("type") == "Opaque",
            f"{cfg.platform_secret} type is Opaque",
            f"{cfg.platform_secret} type is '{obj.get('type')}', expected Opaque",
        )
        # 1c/1d — required keys present and non-empty
        data = obj.get("data") or {}
        required = [
            "ITENTIAL_DEFAULT_USER_PASSWORD",
            "ITENTIAL_ENCRYPTION_KEY",
            "ITENTIAL_MONGO_PASSWORD",
            "ITENTIAL_MONGO_URL",
            "ITENTIAL_REDIS_PASSWORD",
            "ITENTIAL_REDIS_SENTINEL_PASSWORD",
        ]
        missing = [k for k in required if k not in data]
        empty = [
            k for k in required
            if k in data and not _b64_nonempty(data[k])
        ]
        if missing:
            c.bad(f"{cfg.platform_secret} missing keys: {', '.join(missing)}")
        elif empty:
            c.bad(f"{cfg.platform_secret} has empty keys: {', '.join(empty)}")
        else:
            c.ok(f"{cfg.platform_secret} has all {len(required)} required keys, non-empty")

    # 1e/1f — image pull secret exists, correct type, has a registry entry
    if not cfg.image_pull_secret:
        c.warn(
            "no image pull secret configured (imagePullSecrets empty and "
            "--image-pull-secret not set) -- skipping pull-secret checks"
        )
    else:
        obj = kubectl_json("get", "secret", cfg.image_pull_secret, "-n", cfg.namespace)
        if obj is None:
            c.bad(f"image pull secret {cfg.image_pull_secret} not found in namespace {cfg.namespace}")
        else:
            c.assert_(
                obj.get("type") == "kubernetes.io/dockerconfigjson",
                f"{cfg.image_pull_secret} has type kubernetes.io/dockerconfigjson",
                f"{cfg.image_pull_secret} type is '{obj.get('type')}', "
                "expected kubernetes.io/dockerconfigjson",
            )
            raw = (obj.get("data") or {}).get(".dockerconfigjson")
            registries = _dockerconfig_registries(raw)
            if registries:
                c.ok(f"{cfg.image_pull_secret} has registry entries: {', '.join(registries)}")
            else:
                c.bad(f"{cfg.image_pull_secret} has no registry entries in .dockerconfigjson")

    # 1g/1h — CA secret in the cert-manager namespace (only when TLS is used)
    if not cfg.use_tls:
        c.warn("useTLS is false -- skipping CA secret checks")
        return
    if not cfg.ca_secret:
        # Try to resolve it live from the issuer before giving up.
        cfg.ca_secret = _resolve_ca_secret_from_issuer(cfg)
    if not cfg.ca_secret:
        c.warn(
            "CA secret name unknown (set issuer.caSecretName in values or pass "
            "--ca-secret) -- skipping CA secret checks"
        )
        return

    obj = kubectl_json("get", "secret", cfg.ca_secret, "-n", cfg.cert_manager_namespace)
    if obj is None:
        c.bad(f"CA secret {cfg.ca_secret} not found in namespace {cfg.cert_manager_namespace}")
    else:
        c.assert_(
            obj.get("type") == "kubernetes.io/tls",
            f"CA secret {cfg.ca_secret} exists in {cfg.cert_manager_namespace} with type kubernetes.io/tls",
            f"CA secret {cfg.ca_secret} has type '{obj.get('type')}', expected kubernetes.io/tls",
        )
        data = obj.get("data") or {}
        missing = [k for k in ("tls.crt", "tls.key") if not data.get(k)]
        c.assert_(
            not missing,
            f"CA secret {cfg.ca_secret} has tls.crt and tls.key",
            f"CA secret {cfg.ca_secret} missing fields: {', '.join(missing)}",
        )


def check_storage(c: Checker, cfg: Config, mode: str) -> None:
    header(f"2. Persistent Volumes ({mode})")

    if not cfg.storage_class:
        c.warn(
            "storage class name unknown (set storageClass.name in values or pass "
            "--storage-class) -- skipping StorageClass checks"
        )
    else:
        # 2a — StorageClass exists
        obj = kubectl_json("get", "storageclass", cfg.storage_class)
        if obj is None:
            c.bad(f"StorageClass {cfg.storage_class} not found")
        else:
            c.ok(f"StorageClass {cfg.storage_class} exists")
            # 2b — provisioner is reported (backend-specific value is informational)
            prov = obj.get("provisioner")
            if prov:
                c.ok(f"StorageClass {cfg.storage_class} provisioner is {prov}")
            else:
                c.bad(f"StorageClass {cfg.storage_class} has no provisioner")

    # 2c — no stale PVCs (Terminating / Lost)
    pvcs = _list_pvcs(cfg.namespace)
    stale = [(n, ph) for n, ph, _ in pvcs if ph in ("Terminating", "Lost")]
    c.assert_(
        not stale,
        f"no stale PVCs (Terminating/Lost) in namespace {cfg.namespace}",
        "stale PVCs found -- resolve before proceeding: "
        + ", ".join(f"{n} ({ph})" for n, ph in stale),
    )

    if mode != "upgrade":
        return

    # 2d — all expected PVCs exist
    expected = _expected_pvc_names(cfg)
    present = {n for n, _, _ in pvcs}
    for name in expected:
        c.assert_(
            name in present,
            f"PVC {name} exists",
            f"PVC {name} not found in namespace {cfg.namespace}",
        )

    # 2e — all PVCs are Bound
    not_bound = [(n, ph) for n, ph, _ in pvcs if ph != "Bound"]
    c.assert_(
        not not_bound,
        f"all {len(pvcs)} PVCs are Bound",
        "PVCs not Bound: " + ", ".join(f"{n} ({ph})" for n, ph in not_bound),
    )

    # 2f — PVCs on the expected StorageClass
    if cfg.storage_class:
        wrong = [(n, sc) for n, _, sc in pvcs if sc and sc != cfg.storage_class]
        c.assert_(
            not wrong,
            f"all PVCs are on StorageClass {cfg.storage_class}",
            "PVCs on unexpected StorageClass: "
            + ", ".join(f"{n} -> {sc}" for n, sc in wrong),
        )


def check_cert_manager(c: Checker, cfg: Config, mode: str) -> None:
    if not cfg.use_tls:
        return
    header("3. cert-manager")

    # 3c — CRDs present
    for crd in ("certificates.cert-manager.io", "clusterissuers.cert-manager.io"):
        rc, out, _ = kubectl("get", "crd", crd, "--output=jsonpath={.metadata.name}")
        c.assert_(
            rc == 0 and out == crd,
            f"CRD {crd} installed",
            f"CRD {crd} not found -- is cert-manager installed cluster-wide?",
        )

    # 3a/3b — pods running, all three components present
    pods = kubectl_json("get", "pods", "-n", cfg.cert_manager_namespace)
    items = (pods or {}).get("items", [])
    if not items:
        c.bad(f"no pods found in namespace {cfg.cert_manager_namespace}")
    else:
        not_running = [
            p["metadata"]["name"]
            for p in items
            if p.get("status", {}).get("phase") != "Running"
        ]
        c.assert_(
            not not_running,
            f"all {len(items)} cert-manager pods are Running",
            "cert-manager pods not Running: " + ", ".join(not_running),
        )
        names = " ".join(p["metadata"]["name"] for p in items)
        for component in ("cert-manager", "cainjector", "webhook"):
            c.assert_(
                component in names,
                f"cert-manager component '{component}' present",
                f"cert-manager component '{component}' not found",
            )

    # 3d/3e/3f — issuer exists, Ready, references the expected CA secret
    if not cfg.issuer_name:
        c.warn(
            "issuer name unknown (set certificate.issuerRef.name in values or "
            "pass --issuer) -- skipping issuer checks"
        )
    else:
        kind = cfg.issuer_kind.lower()
        ns_args = [] if kind == "clusterissuer" else ["-n", cfg.namespace]
        obj = kubectl_json("get", kind, cfg.issuer_name, *ns_args)
        if obj is None:
            c.bad(f"{cfg.issuer_kind} {cfg.issuer_name} not found")
        else:
            c.ok(f"{cfg.issuer_kind} {cfg.issuer_name} exists")
            ready = _condition_status(obj, "Ready")
            c.assert_(
                ready == "True",
                f"{cfg.issuer_kind} {cfg.issuer_name} is Ready",
                f"{cfg.issuer_kind} {cfg.issuer_name} is not Ready (status: {ready})",
            )
            ref = obj.get("spec", {}).get("ca", {}).get("secretName")
            if cfg.ca_secret:
                c.assert_(
                    ref == cfg.ca_secret,
                    f"{cfg.issuer_kind} references CA secret {cfg.ca_secret}",
                    f"{cfg.issuer_kind} references '{ref}', expected {cfg.ca_secret}",
                )
            elif ref:
                c.ok(f"{cfg.issuer_kind} references CA secret {ref}")

    if mode != "upgrade":
        return

    # 3g/3h/3i — Certificate and its TLS secret are healthy
    cert = kubectl_json("get", "certificate", cfg.certificate_name, "-n", cfg.namespace)
    if cert is None:
        c.bad(f"Certificate {cfg.certificate_name} not found in namespace {cfg.namespace}")
        return
    ready = _condition_status(cert, "Ready")
    c.assert_(
        ready == "True",
        f"Certificate {cfg.certificate_name} is Ready",
        f"Certificate {cfg.certificate_name} is not Ready -- cert-manager may not have fulfilled it",
    )

    spec = cert.get("spec", {})
    cert_secret = spec.get("secretName") or cfg.cert_secret_hint
    cert_hosts = spec.get("dnsNames", [])

    # 3h — TLS secret has all three keys
    obj = kubectl_json("get", "secret", cert_secret, "-n", cfg.namespace)
    if obj is None:
        c.bad(f"TLS secret {cert_secret} not found in namespace {cfg.namespace}")
        return
    data = obj.get("data") or {}
    missing = [k for k in ("tls.crt", "tls.key", "ca.crt") if not data.get(k)]
    c.assert_(
        not missing,
        f"TLS secret {cert_secret} has tls.crt, tls.key, ca.crt",
        f"TLS secret {cert_secret} missing fields: {', '.join(missing)}",
    )

    # 3i — TLS cert not expired and covers the declared hostnames
    _check_cert_validity(c, data.get("tls.crt"), cert_hosts)


# ── Low-level helpers used by the check groups ──────────────────────────────────

def _b64_nonempty(b64_value: str) -> bool:
    try:
        return bool(base64.b64decode(b64_value).strip())
    except (ValueError, TypeError):
        return False


def _dockerconfig_registries(b64_value: str | None) -> list[str]:
    if not b64_value:
        return []
    try:
        cfg = json.loads(base64.b64decode(b64_value))
    except (ValueError, TypeError, json.JSONDecodeError):
        return []
    return list((cfg.get("auths") or {}).keys())


def _list_pvcs(namespace: str) -> list[tuple[str, str, str]]:
    """Return [(name, phase, storageClassName), ...] for PVCs in the namespace."""
    obj = kubectl_json("get", "pvc", "-n", namespace)
    out = []
    for item in (obj or {}).get("items", []):
        name = item["metadata"]["name"]
        phase = item.get("status", {}).get("phase", "")
        sc = item.get("spec", {}).get("storageClassName", "")
        out.append((name, phase, sc))
    return out


def _expected_pvc_names(cfg: Config) -> list[str]:
    """StatefulSet PVC names: <vct>-<statefulset>-<ordinal>.

    Volume claim templates are "<fullname>-assets-volume" / "<fullname>-logs-volume"
    and the StatefulSet itself is named <fullname>.
    """
    names = []
    for claim in ("assets-volume", "logs-volume"):
        for i in range(cfg.replica_count):
            names.append(f"{cfg.fullname}-{claim}-{cfg.fullname}-{i}")
    return names


def _condition_status(obj: dict, cond_type: str) -> str | None:
    for cond in obj.get("status", {}).get("conditions", []):
        if cond.get("type") == cond_type:
            return cond.get("status")
    return None


def _resolve_ca_secret_from_issuer(cfg: Config) -> str | None:
    if not cfg.issuer_name:
        return None
    kind = cfg.issuer_kind.lower()
    ns_args = [] if kind == "clusterissuer" else ["-n", cfg.namespace]
    obj = kubectl_json("get", kind, cfg.issuer_name, *ns_args)
    if obj is None:
        return None
    return obj.get("spec", {}).get("ca", {}).get("secretName")


def _check_cert_validity(c: Checker, tls_crt_b64: str | None, hosts: list[str]) -> None:
    if not tls_crt_b64:
        c.bad("TLS certificate data missing from secret")
        return
    if not shutil.which("openssl"):
        c.warn("openssl not found on PATH -- skipping certificate expiry/SAN check")
        return
    import datetime
    import re

    pem = base64.b64decode(tls_crt_b64)
    proc = subprocess.run(
        ["openssl", "x509", "-noout", "-text"],
        input=pem, capture_output=True,
    )
    text = proc.stdout.decode(errors="replace")

    match = re.search(r"Not After\s*:\s*(.+)", text)
    if not match:
        c.bad("could not parse certificate expiry")
        return
    try:
        expiry = datetime.datetime.strptime(match.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        c.bad(f"could not parse expiry date: {match.group(1).strip()}")
        return
    days_left = (expiry - datetime.datetime.utcnow()).days
    if days_left < 2:
        c.bad(f"TLS certificate expires in {days_left} day(s) on {expiry.date()}")
    else:
        c.ok(f"TLS certificate valid for {days_left} more day(s), expires {expiry.date()}")

    expected = [h for h in hosts if h]
    if not expected:
        c.warn("Certificate spec declares no dnsNames -- skipping SAN coverage check")
        return
    missing = [h for h in expected if h not in text]
    c.assert_(
        not missing,
        f"certificate covers all {len(expected)} declared hostnames: {', '.join(expected)}",
        f"certificate does not cover declared hostnames: {', '.join(missing)}",
    )


# ── Self-test ──────────────────────────────────────────────────────────────────

def run_self_test() -> int:
    """Exercise the cluster-independent logic without touching a live cluster.

    This is a regression guard for the one place the script encodes assumptions
    about the chart's templates -- the `iap.fullname` replication and the PVC
    naming derived from it. If `_helpers.tpl` or the StatefulSet volume claim
    templates change, these assertions should be updated in lockstep.

    Run with:  python3 scripts/precheck.py --self-test
    """
    failures: list[str] = []

    def expect(cond: bool, desc: str) -> None:
        if cond:
            print(f"  PASS  {desc}")
        else:
            print(f"  FAIL  {desc}")
            failures.append(desc)

    print("Self-test: cluster-independent logic\n")

    # iap.fullname replication (see _helpers.tpl "iap.fullname").
    f = Config._fullname
    expect(f("iap", "iap", None, None) == "iap",
           "fullname: release containing chart name is used as-is")
    expect(f("prod", "iap", None, None) == "prod-iap",
           "fullname: release without chart name gets '-iap' appended")
    expect(f("anything", "iap", None, "myoverride") == "myoverride",
           "fullname: fullnameOverride wins")
    expect(f("x" * 70, "iap", None, None) == ("x" * 63),
           "fullname: truncated to 63 chars")

    # PVC names derived from fullname must match the documented pattern.
    class _Cfg:
        fullname = "iap"
        replica_count = 2
    expect(
        _expected_pvc_names(_Cfg()) == [
            "iap-assets-volume-iap-0", "iap-assets-volume-iap-1",
            "iap-logs-volume-iap-0", "iap-logs-volume-iap-1",
        ],
        "expected PVC names match docs/pre-install-verification.md",
    )

    # Values-file parsing helpers.
    expect(_first_pull_secret({"imagePullSecrets": [{"name": "ecr"}]}) == "ecr",
           "pull secret: object entry with 'name'")
    expect(_first_pull_secret({"imagePullSecrets": ["plainstr"]}) == "plainstr",
           "pull secret: plain string entry")
    expect(_first_pull_secret({}) is None,
           "pull secret: none configured -> None")

    # Boolean coercion for values like useTLS.
    expect(_as_bool("true") and _as_bool(True) and _as_bool("yes"),
           "bool: truthy values")
    expect(not _as_bool("false") and not _as_bool("") and not _as_bool(None),
           "bool: falsy values")

    # base64 / dockerconfig helpers.
    expect(_b64_nonempty(base64.b64encode(b"secret").decode()),
           "b64: non-empty decoded value")
    expect(not _b64_nonempty(base64.b64encode(b"   ").decode()),
           "b64: whitespace-only decodes as empty")
    expect(not _b64_nonempty("not-valid-base64!!!"),
           "b64: invalid input -> not non-empty")
    dockercfg = base64.b64encode(
        json.dumps({"auths": {"registry.example.com": {}}}).encode()
    ).decode()
    expect(_dockerconfig_registries(dockercfg) == ["registry.example.com"],
           "dockerconfig: registry hostnames extracted")
    expect(_dockerconfig_registries(None) == [],
           "dockerconfig: missing data -> empty list")

    print("\n" + "─" * 40)
    if failures:
        print(f"  Self-test FAILED: {len(failures)} assertion(s) failed")
        print("─" * 40)
        return 1
    print("  Self-test passed.")
    print("─" * 40)
    return 0


# ── Entry point ────────────────────────────────────────────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Verify the environment before helm install/upgrade of the IAP chart.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("mode", nargs="?", choices=["install", "upgrade"],
                   help="install: pre-install checks; upgrade: install checks + PVC/cert health")
    p.add_argument("--self-test", action="store_true",
                   help="Run the built-in checks of the script's own logic and exit (no cluster needed)")
    p.add_argument("-n", "--namespace",
                   help="Target namespace (default: $NAMESPACE, else current kubectl context, else 'default')")
    p.add_argument("-f", "--values",
                   help="Helm values file to read environment-specific names from (needs PyYAML)")
    p.add_argument("-r", "--release", default="iap",
                   help="Helm release name, used to derive resource names (default: iap)")
    # Explicit overrides -- take precedence over the values file.
    p.add_argument("--storage-class", help="StorageClass name (overrides storageClass.name)")
    p.add_argument("--issuer", help="Issuer/ClusterIssuer name (overrides certificate.issuerRef.name)")
    p.add_argument("--issuer-kind", help="Issuer kind: ClusterIssuer or Issuer")
    p.add_argument("--ca-secret", help="CA secret name (overrides issuer.caSecretName)")
    p.add_argument("--cert-secret", help="TLS secret name (overrides certificate.secretName)")
    p.add_argument("--platform-secret", help="Platform secret name (default: itential-platform-secrets)")
    p.add_argument("--image-pull-secret", help="Image pull secret name (overrides imagePullSecrets[0])")
    p.add_argument("--cert-manager-namespace", help="Namespace cert-manager runs in (default: cert-manager)")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.mode:
        print("error: mode is required (install or upgrade); "
              "or use --self-test", file=sys.stderr)
        return 2

    if not shutil.which("kubectl"):
        print("error: kubectl not found on PATH", file=sys.stderr)
        return 2

    cfg = Config(args)
    c = Checker()

    print(f"IAP pre-{args.mode} verification")
    print(f"  namespace:    {cfg.namespace}")
    print(f"  release:      {cfg.release}  (fullname: {cfg.fullname})")
    print(f"  values file:  {args.values or '(none — using flags/defaults)'}")

    check_secrets(c, cfg)
    check_storage(c, cfg, args.mode)
    check_cert_manager(c, cfg, args.mode)

    print("\n" + "─" * 40)
    print(f"  Results: {c.passed} passed, {c.failed} failed")
    print("─" * 40)
    if c.failed == 0:
        print(f"  Environment is ready for helm {args.mode}.")
        return 0
    print(f"  Fix the failures above before running helm {args.mode}.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
