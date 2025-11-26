# Platform Helm Tests

This document describes the Helm tests available for the Itential Automation Platform (Platform) Helm chart. Helm tests are Kubernetes Jobs that run validation checks after a Helm chart is deployed to verify that your release is working correctly.

## Overview

Helm tests provide automated validation of your Platform deployment by running comprehensive checks against the deployed application. The Platform test suite validates:

- ✅ **Health Endpoint**: Application health and all components (apps, adapters, redis, mongo) status
- ✅ **Version Verification**: Deployed version matches expected image tag
- ✅ **Process Count**: All required Pronghorn processes are running
- ✅ **Multi-Pod Support**: Tests all replicas individually via headless services
- ✅ **Automatic Cleanup**: Tests self-delete after configurable TTL period

## Running Tests

### Basic Test Execution

Run the comprehensive post-install test for a deployed release:

```bash
helm test <release-name> -n <namespace>
```

**Example:**
```bash
helm test iap -n development
```

### With Options

```bash
# Run tests with extended timeout (default: 5 minutes)
helm test <release-name> -n <namespace> --timeout 10m

# Run tests and keep detailed output
helm test <release-name> -n <namespace> --debug

# Clean up previous test runs first  
helm test <release-name> -n <namespace> --cleanup
```

### Viewing Test Results

```bash
# View test job logs (recommended)
kubectl logs job/<release-name>-test-post-install -n <namespace>

# View test job status
kubectl get jobs -n <namespace> | grep test

# Check test job details
kubectl describe job <release-name>-test-post-install -n <namespace>

# View all test-related resources
kubectl get pods,jobs -n <namespace> -l "helm.sh/hook=test"
```

## Test Configuration

Tests are configured in the `values.yaml` file under the `postInstallTests` section:

```yaml
# Post-installation test configuration 
postInstallTests:
  # -- Enable or disable all post-install tests (helm test command)
  enabled: true
  # -- Maximum time to wait for tests to pass before failing (in seconds)
  readinessTimeout: 300
  # -- Time to live after test completion (in seconds)
  # Job, pod resources including logs will be automatically deleted after this duration
  ttlSecondsAfterFinished: 300  # 5 minutes default
  # Process count verification configuration
  processCountTest:
    # -- Optional Itential applications that won't cause test failure if missing
    optionalProcesses:
      - "Pronghorn_LifecycleManager_Application"
      - "Pronghorn_ConfigurationManager_Application"
      - "Pronghorn_NSOManager_Application"
      - "Pronghorn_AppArtifacts_Application"
```

### Configuration Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `postInstallTests.enabled` | Enable or disable all tests | `true` |
| `postInstallTests.readinessTimeout` | Maximum time to wait for application readiness (seconds) | `300` |
| `postInstallTests.ttlSecondsAfterFinished` | Automatic cleanup delay after test completion (seconds) | `300` |
| `postInstallTests.processCountTest.optionalProcesses` | List of optional processes that won't fail tests if missing | See values |

## Comprehensive Post-Install Test

**File**: `templates/tests/test-post-install.yaml`  
**Resource Type**: `Job` (batch/v1)  
**Hook Weight**: `1`  
**Purpose**: Validates complete Platform deployment health and functionality

### What it Tests

The comprehensive test performs three validation checks on each pod replica:

#### 1. Health Endpoint Validation
- ✅ Health endpoint (`/health/status`) returns HTTP 200
- ✅ All replica pods respond individually via headless services
- ✅ Component status verification:
  - `apps`: running
  - `adapters`: running  
  - `redis`: running
  - `mongo`: running

#### 2. Version Verification  
- ✅ Version endpoint (`/version`) returns expected version
- ✅ Deployed version matches `values.image.tag`
- ✅ Version consistency across all replicas

#### 3. Process Count Validation
- ✅ **Required Processes** (14 core processes):
  - Pronghorn_core
  - Pronghorn_Jst_Application
  - Pronghorn_TemplateBuilder_Application
  - Pronghorn_AGManager_Application
  - Pronghorn_Tags_Application
  - Pronghorn_FormBuilder_Application
  - Pronghorn_JsonForms_Application
  - Pronghorn_MOP_Application
  - Pronghorn_AutomationStudio_Application
  - Pronghorn_OperationsManager_Application
  - Pronghorn_GatewayManager_Application
  - Pronghorn_WorkflowBuilder_Application
  - Pronghorn_WorkFlowEngine_Application
  - Pronghorn_Search_Application

- ℹ️ **Optional Processes** (configurable):
  - Pronghorn_LifecycleManager_Application
  - Pronghorn_ConfigurationManager_Application
  - Pronghorn_NSOManager_Application
  - Pronghorn_AppArtifacts_Application

### Test Execution Flow

1. **Initialization**: Configure test parameters and display test setup
2. **Multi-Round Testing**: Retry logic with 15-second intervals until timeout
3. **Per-Pod Validation**: Test each replica individually using headless services
4. **Comprehensive Scoring**: All three test types must pass for pod success
5. **Success Criteria**: All replicas must pass all tests
6. **Automatic Cleanup**: Job and pods deleted after TTL expires

### Example Output

```
🚀 Starting Platform Post-Installation Comprehensive Test Suite...
⏰ Test started at: Wed Nov 26 17:14:37 UTC 2025

📋 Test Configuration:
  Protocol: https
  Replicas: 1
  Namespace: na
  Expected version: 6.1.1
  Required processes: 14
  Optional processes: 4
  Max wait time: 300s
  Retry interval: 15s

🔄 Starting comprehensive test cycle...

=== Test Round 1 ===
🔍 Testing pod 0 - Comprehensive Check
  🔍 Health check for pod 0: https://iap-service-headless-0.local:443/health/status
    ✅ Health endpoint responded
    ✅ Apps: running
    ✅ Adapters: running
    ✅ Redis: running
    ✅ Mongo: running
  🔍 Version check for pod 0: https://iap-service-headless-0.local:443/version
    ✅ Version endpoint responded
    📄 Version Installed: "6.1.1"
    ✅ Version matches: 6.1.1
  🔍 Process check for pod 0: iap-na-0
    📊 Processes: 14/14 required, 1/4 optional
    ✅ All required processes running
  📊 Pod 0 Summary:
    Health: ✅ PASS
    Version: ✅ PASS
    Processes: ✅ PASS

📊 Round Summary:
  Pods passed all tests: 1/1
  Pods with failures: 0/1
  Time elapsed: 0s
  ✅ All pods passed comprehensive testing!

🎉 Platform POST-INSTALLATION TESTS PASSED!
📋 Final Results:
  ✅ All 1 pod(s) passed comprehensive testing
  ✅ Health endpoints: All components healthy
  ✅ Version verification: Expected version deployed
  ✅ Process verification: All required processes running
  ⏱️  Total test duration: 0s
⏰ Test completed at: Wed Nov 26 17:14:39 UTC 2025
```

### Service Discovery

The test uses **headless service URLs** for reliable pod-specific communication:

- **Format**: `https://{service.name}-headless-{pod-index}.{namespace}.svc.cluster.local:{service.port}/{endpoint}`
- **Example**: `https://iap-service-headless-0.na.svc.cluster.local:443/health/status`

This approach provides:
- Direct pod-to-pod communication
- Independence from external load balancers
- Faster, more reliable internal cluster networking
- Individual pod validation (important for StatefulSets)

### Automatic Cleanup (TTL)

The test uses Kubernetes Job with `ttlSecondsAfterFinished` for automatic resource cleanup:

- ⏱️ **Default TTL**: 300 seconds (5 minutes)
- 🔍 **Debugging Window**: Logs available during entire TTL period
- 🗑️ **Auto-Cleanup**: Job and pod resources automatically deleted after TTL
- ⚙️ **Configurable**: Adjust via `postInstallTests.ttlSecondsAfterFinished`

**Timeline Example:**
1. Test runs and completes (success/failure)
2. TTL countdown begins (5 minutes)
3. Logs remain accessible: `kubectl logs job/iap-test-post-install -n na`
4. After 5 minutes: Job and pod are automatically deleted
5. No manual cleanup required

### Troubleshooting

If tests fail, check the following in order:

#### 1. View Test Logs
```bash
# Get detailed test output
kubectl logs job/<release-name>-test-post-install -n <namespace>

# If job is deleted, check recent events
kubectl get events -n <namespace> --sort-by='.lastTimestamp'
```

#### 2. Check Application Status
```bash
# Verify IAP pods are running
kubectl get pods -n <namespace>

# Check application logs
kubectl logs <pod-name> -n <namespace> -c iap

# Verify services and endpoints
kubectl get svc,endpoints -n <namespace>
```

#### 3. Manual Health Check
```bash
# Port-forward and test endpoints directly
kubectl port-forward <pod-name> 3443:3443 -n <namespace>

# Test health endpoint
curl -k https://localhost:3443/health/status

# Test version endpoint  
curl -k https://localhost:3443/version
```

#### 4. Process Validation
```bash
# Check processes in pod
kubectl exec <pod-name> -n <namespace> -c iap -- ps aux | grep -i pronghorn
```

### Common Failure Scenarios

| Issue | Symptoms | Solution |
|-------|----------|----------|
| **Application Starting** | Health/version endpoints fail initially | Wait longer or increase `readinessTimeout` |
| **Database Connectivity** | Health endpoint shows mongo/redis not running | Check database connections and credentials |
| **Resource Constraints** | Missing processes or pods failing | Increase CPU/memory requests/limits |
| **Network Policies** | Connection timeouts | Verify network policies allow test pod → Platform communication |
| **TLS Issues** | SSL/certificate errors | Check certificate configuration and trust chain |
| **Version Mismatch** | Version check fails | Verify `values.image.tag` matches actual deployment |

## Integration with CI/CD

Helm tests integrate seamlessly with deployment pipelines:

```bash
#!/bin/bash
set -e

echo "Deploying Platform..."
helm upgrade --install iap-prod ./chart -f values-prod.yaml -n production

echo "Running comprehensive post-install tests..."
if helm test iap-prod -n production --timeout 10m; then
  echo "✅ Platform deployment validation successful"
  echo "🚀 Application is ready for traffic"
else
  echo "❌ Platform deployment validation failed"
  echo "📋 Test logs:"
  kubectl logs job/iap-prod-test-post-install -n production
  exit 1
fi
```

### GitLab CI Example

```yaml
deploy_and_test:
  stage: deploy
  script:
    - helm upgrade --install ${CI_ENVIRONMENT_NAME} ./chart -f values-${CI_ENVIRONMENT_NAME}.yaml -n ${CI_ENVIRONMENT_NAME}
    - helm test ${CI_ENVIRONMENT_NAME} -n ${CI_ENVIRONMENT_NAME} --timeout 15m
  environment:
    name: ${CI_COMMIT_REF_SLUG}
  only:
    - main
    - develop
```

## Development and Customization

### Adding Optional Processes

To add new optional processes that won't fail tests if missing:

```yaml
postInstallTests:
  processCountTest:
    optionalProcesses:
      - "Pronghorn_LifecycleManager_Application"
      - "Pronghorn_ConfigurationManager_Application" 
      - "Pronghorn_NSOManager_Application"
      - "Pronghorn_AppArtifacts_Application"
      - "Pronghorn_CustomApp_Application"  # Add your custom process
```

### Adjusting Timeouts

For slower environments or longer startup times:

```yaml
postInstallTests:
  readinessTimeout: 600  # 10 minutes instead of default 5
  ttlSecondsAfterFinished: 1800  # Keep logs for 30 minutes
```

### Environment-Specific Configuration

Different environments may need different test configurations:

```yaml
# values-dev.yaml - More lenient for development
postInstallTests:
  readinessTimeout: 600
  ttlSecondsAfterFinished: 1800  # Keep logs longer for debugging

# values-prod.yaml - Strict for production  
postInstallTests:
  readinessTimeout: 300
  ttlSecondsAfterFinished: 300   # Clean up quickly
```

## Best Practices

1. **Run tests after every deployment** to catch issues early
2. **Monitor test results** in CI/CD pipelines for automated validation
3. **Adjust timeouts** based on environment performance characteristics
4. **Review test logs** when failures occur for detailed diagnostics
5. **Keep TTL reasonable** - balance debugging needs with resource cleanup
6. **Test in staging** before deploying to production environments

## Contributing

When modifying the test suite:

1. Update test templates in `templates/tests/test-post-install.yaml`
2. Update values files if new configuration options are needed
3. Test changes against running deployment  
4. Update this documentation with new features or changes
5. Ensure backward compatibility with existing deployments

For questions or issues with Helm tests, check the [Troubleshooting](#troubleshooting) section or review the application deployment logs.