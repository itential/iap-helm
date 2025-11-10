# InitContainer Adapter Installer

The InitContainer Adapter Installer is a powerful feature that automatically installs and manages Platform adapters from Itential's open source repositories into the Itential Automation Platform persistent volume. This documentation covers configuration, usage, and troubleshooting.

## Overview

The adapter installer uses a Kubernetes initContainer that runs before the main IAP container starts. It clones Node.js adapters from specified repositories, installs their dependencies, and manages their lifecycle through upgrades and removals.

## Key Features

- **Smart Version Detection**: Only reinstalls adapters when versions change
- **Automatic Cleanup**: Removes obsolete adapters not in the repositories list
- **Branch/Tag Support**: Install specific versions or use default branches
- **Multi-Repository**: Support for multiple adapter repositories
- **Comprehensive Reporting**: Detailed installation and error reporting
- **Security**: Runs as non-root user with restricted permissions
- **Automatic Restarts**: Pods restart automatically when repository configuration changes

## Prerequisites

- `mountAdapterVolume` must be set to `true` (the installer needs a persistent volume to install adapters)
- Persistent volume claims must be enabled
- Network access to Git repositories (GitLab, GitHub, Bitbucket, etc.)

## Configuration

### Basic Configuration

Enable the adapter installer in your `values.yaml`:

```yaml
# Enable adapter volume mounting
mountAdapterVolume: true

# Configure the adapter installer
initAdapterInstaller:
  enabled: true
  image:
    repository: node
    tag: "18-bullseye"
    pullPolicy: IfNotPresent
  securityContext:
    runAsUser: 1001
    runAsGroup: 1001
    runAsNonRoot: true
    allowPrivilegeEscalation: false
  repositories:
    - url: "https://gitlab.com/itentialopensource/adapters/adapter-example.git"
      branch: "v1.2.3"
    - "https://gitlab.com/itentialopensource/adapters/adapter-other.git"
```

### Repository Configuration

Repositories can be configured in two formats:

#### 1. String Format (Default Branch)
```yaml
repositories:
  - "https://gitlab.com/itentialopensource/adapters/adapter-example.git"
```

#### 2. Object Format (Specific Branch/Tag)
```yaml
repositories:
  - url: "https://gitlab.com/itentialopensource/adapters/adapter-example.git"
    branch: "v1.2.3"  # Can be a branch name or tag
```

#### 3. Multiple Git Providers
```yaml
repositories:
  # GitLab
  - url: "https://gitlab.com/itentialopensource/adapters/adapter-six_connect.git"
    branch: "v0.8.1"
  # GitHub  
  - url: "https://github.com/company/adapter-custom.git"
    branch: "v1.0.0"
  # Bitbucket
  - url: "https://bitbucket.org/team/adapter-internal.git"
    branch: "main"
```

### Advanced Configuration

```yaml
initAdapterInstaller:
  enabled: true
  image:
    repository: node
    tag: "18-bullseye"
    pullPolicy: IfNotPresent
  securityContext:
    runAsUser: 1001          # Must match podSecurityContext
    runAsGroup: 1001         # Must match podSecurityContext
    runAsNonRoot: true
    allowPrivilegeEscalation: false
  repositories:
    # Mix of formats is supported
    - url: "https://gitlab.com/itentialopensource/adapters/adapter-six_connect.git"
      branch: "v0.8.1"
    - url: "https://gitlab.com/itentialopensource/adapters/adapter-aruba_central.git" 
      branch: "v2.3.0"
    - "https://gitlab.com/itentialopensource/adapters/adapter-github.git"
  # Custom npm install options (optional)
  npmInstallOptions:
    - "--silent"
    - "--no-audit" 
    - "--no-fund"
    - "--production"  # Example additional option
```

### NPM Install Options

The adapter installer allows customization of npm install command options through the `npmInstallOptions` configuration:

```yaml
initAdapterInstaller:
  # Default options (used if npmInstallOptions is not specified)
  npmInstallOptions:
    - "--silent"      # Suppress npm output
    - "--no-audit"    # Skip security audit
    - "--no-fund"     # Skip funding messages
```

**Common Options:**
- `--production`: Install only production dependencies
- `--ignore-scripts`: Skip running package scripts
- `--no-optional`: Skip optional dependencies  
- `--legacy-peer-deps`: Use legacy peer dependency resolution
- `--force`: Force npm to ignore conflicts

**Example Custom Configuration:**
```yaml
npmInstallOptions:
  - "--silent"
  - "--no-audit"
  - "--production"
  - "--ignore-scripts"
```

## How It Works

### Installation Process

1. **Pod-0 Only Execution**: Only runs on the first replica to avoid redundant installations
2. **Cleanup Phase**: Removes adapters not in the current repositories list
3. **Version Detection**: Checks if existing adapters need updates using git commit comparison
4. **Installation Phase**: Clones and installs new/updated adapters
5. **Permission Setting**: Sets proper file ownership and permissions (775, itential:users)
6. **Reporting**: Generates comprehensive installation report

### Automatic Restart Mechanism

The system uses a checksum annotation that triggers pod restarts when the repositories list changes:

```yaml
# Automatically added to pod template
annotations:
  checksum/repositories: {{ .Values.initAdapterInstaller.repositories | toYaml | sha256sum }}
```

This ensures:
- **Repository changes** → Automatic pod restart
- **No changes** → No unnecessary restarts
- **Version updates** → Selective reinstallation

## File Structure

After installation, adapters are located at:
```
/opt/itential/platform/services/custom/
├── adapter-six_connect/
│   ├── node_modules/
│   ├── package.json
│   └── ... (adapter files)
├── adapter-aruba_central/
│   ├── node_modules/
│   ├── package.json
│   └── ... (adapter files)
└── lost+found/
```

## Lifecycle Management

### Adding a New Adapter

1. Add the repository to the `repositories` list in `values.yaml`
2. Run `helm upgrade`
3. Pod automatically restarts and installs the new adapter

### Updating an Adapter Version

1. Change the `branch` field for the adapter in `values.yaml`
2. Run `helm upgrade`  
3. Pod automatically restarts and reinstalls the adapter with the new version

### Removing an Adapter

1. Remove the repository from the `repositories` list in `values.yaml`
2. Run `helm upgrade`
3. Pod automatically restarts and removes the obsolete adapter

## Logging and Monitoring

### Installation Logs

View initContainer logs:
```bash
kubectl logs <pod-name> -c adapter-installer -n <namespace>
```

### Sample Log Output

```
Installing adapters...
Current user: itential (1001)
Pod hostname: iap-na-0
Running adapter installation on pod-0...

Cleaning up obsolete adapters...
✅ Keeping existing adapter: adapter-aruba_central
🗑️ Removing obsolete adapter: adapter-old_adapter

=========================================
Processing adapter: adapter-six_connect
Repository URL: https://gitlab.com/itentialopensource/adapters/adapter-six_connect.git
Branch/Tag: v0.8.1
=========================================
✅ Adapter adapter-six_connect already on correct branch/tag: v0.8.1 (commit: 260b1c6c)
⏭️ Skipping adapter-six_connect installation (already up to date)

=========================================
ADAPTER INSTALLATION REPORT
=========================================
Total adapters processed: 2
Successful installations: 2
Failed installations: 0
Obsolete adapters removed: 1

✅ Successfully installed adapters:
  - adapter-six_connect (already installed)
  - adapter-aruba_central (already installed)

🗑️ Removed obsolete adapters:
  - adapter-old_adapter
=========================================
```

## Troubleshooting

### Common Issues

#### 1. initContainer Not Running
**Symptom**: No initContainer logs found
**Cause**: `mountAdapterVolume` is set to `false` or `initAdapterInstaller.enabled` is `false`
**Solution**: 
```yaml
mountAdapterVolume: true
initAdapterInstaller:
  enabled: true
```

#### 2. Permission Errors
**Symptom**: `chmod: operation not permitted` or `chown: operation not permitted`
**Cause**: Security context mismatch or cluster security policies
**Solution**: Ensure `initAdapterInstaller.securityContext` matches `podSecurityContext`:
```yaml
podSecurityContext:
  fsGroup: 1001
  runAsGroup: 1001
  runAsUser: 1001
  runAsNonRoot: true

initAdapterInstaller:
  securityContext:
    runAsUser: 1001
    runAsGroup: 1001
    runAsNonRoot: true
    allowPrivilegeEscalation: false
```

#### 3. Git Clone Failures
**Symptom**: `Failed to clone repository`
**Cause**: Network connectivity, repository access, or invalid URL
**Solution**:
- Verify repository URL is accessible
- Check network policies allow outbound HTTPS
- Ensure repository exists and is public

#### 4. NPM Install Failures
**Symptom**: `NPM install failed`
**Cause**: Missing dependencies, network issues, or invalid package.json
**Solution**:
- Check adapter's package.json is valid
- Verify network access to npm registry
- Review specific NPM error messages in logs

#### 5. Pod Not Restarting After Repository Changes
**Symptom**: Repository changes don't trigger adapter updates
**Cause**: Checksum annotation not working or pod not restarting
**Solution**:
- Verify the checksum annotation is present: `kubectl describe pod <pod-name>`
- Manually restart pod: `kubectl delete pod <pod-name>`

### Debugging Commands

```bash
# Check pod events
kubectl describe pod <pod-name> -n <namespace>

# View initContainer logs
kubectl logs <pod-name> -c adapter-installer -n <namespace>

# Check pod annotations (verify checksum)
kubectl get pod <pod-name> -o yaml | grep -A 5 annotations

# List installed adapters
kubectl exec <pod-name> -n <namespace> -- ls -la /opt/itential/platform/services/custom

# Check adapter permissions
kubectl exec <pod-name> -n <namespace> -- ls -la /opt/itential/platform/services/custom/adapter-*
```

## Best Practices

### Repository Management
- Use specific version tags (e.g., `v1.2.3`) instead of branch names for production
- Keep the repositories list organized and well-documented
- Test adapter compatibility before adding to production

### Version Control
- Use semantic versioning for adapter releases
- Tag releases properly in Git repositories
- Maintain compatibility between adapter versions and IAP versions

### Security
- Run initContainer as non-root user
- Use least-privilege security contexts
- Regularly update base images (node:18-bullseye)

### Monitoring
- Monitor initContainer logs for failures
- Set up alerts for failed adapter installations
- Track adapter installation metrics

## Architecture Details

### Components

1. **StatefulSet Template**: Generates repository arrays and mounts ConfigMap
2. **ConfigMap Template**: Contains the complete installation script
3. **Init Container**: Executes the installation script with repository arrays
4. **Persistent Volume**: Shared storage between initContainer and main container

### Template Files

- `templates/statefulset.yaml`: InitContainer definition and repository array generation
- `templates/configmap-adapter-installer.yaml`: Installation script logic
- `values.yaml`: Configuration schema and defaults

### Security Model

- Non-root execution (user/group 1001)
- Read-only ConfigMap mounting
- Shared persistent volume with main container
- Restricted security context with no privilege escalation

## Migration Guide

### From Inline Script to ConfigMap

If migrating from an older version with inline scripts in values:

1. Remove any `script` field from `initAdapterInstaller`
2. Ensure only `repositories` field is configured
3. The system automatically uses the ConfigMap-based script

### Upgrading Helm Chart

When upgrading the Helm chart:
1. Existing adapter installations are preserved
2. Only changed adapters are reinstalled
3. ConfigMap changes trigger automatic pod restarts

## Support

For issues related to the adapter installer:

1. Check this documentation for common issues
2. Review initContainer logs for specific error messages
3. Verify configuration matches the examples provided
4. Test with a minimal configuration first

## Examples

### Production Configuration
```yaml
mountAdapterVolume: true

initAdapterInstaller:
  enabled: true
  image:
    repository: node
    tag: "18-bullseye"
    pullPolicy: IfNotPresent
  securityContext:
    runAsUser: 1001
    runAsGroup: 1001
    runAsNonRoot: true
    allowPrivilegeEscalation: false
  repositories:
    - url: "https://gitlab.com/itentialopensource/adapters/adapter-six_connect.git"
      branch: "v0.8.1"
    - url: "https://gitlab.com/itentialopensource/adapters/adapter-aruba_central.git"
      branch: "v2.3.0"
    - url: "https://gitlab.com/itentialopensource/adapters/adapter-github.git"
      branch: "v1.5.2"
```

### Development Configuration
```yaml
mountAdapterVolume: true

initAdapterInstaller:
  enabled: true
  repositories:
    # Use default branches for development
    - "https://gitlab.com/itentialopensource/adapters/adapter-six_connect.git"
    - "https://gitlab.com/itentialopensource/adapters/adapter-aruba_central.git"
```