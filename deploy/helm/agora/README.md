# Agora Helm Chart

Multi-Agent Deliberation Platform for Kubernetes.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- PV provisioner (for workspace storage)

## Quick Start

```bash
helm install agora deploy/helm/agora
```

With embedded Postgres password:

```bash
helm install agora deploy/helm/agora \
  --set database.embedded.password=changeme \
  --set jwtSecret.value=$(openssl rand -hex 32)
```

Verify:

```bash
kubectl get pods -l app.kubernetes.io/name=agora
```

## Chart Structure

```
deploy/helm/agora/
├── Chart.yaml
├── values.yaml
├── values-prod.yaml
├── templates/
│   ├── _helpers.tpl
│   ├── coordinator-deployment.yaml
│   ├── coordinator-service.yaml
│   ├── coordinator-hpa.yaml
│   ├── hermes-bridge-deployment.yaml
│   ├── hermes-bridge-service.yaml
│   ├── redis.yaml
│   ├── postgres.yaml
│   ├── postgres-secret.yaml
│   ├── secrets.yaml
│   ├── configmap.yaml
│   ├── pvc.yaml
│   ├── ingress.yaml
│   └── servicemonitor.yaml
```

## Configuration

### Global

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `2` | Number of coordinator replicas |
| `image.repository` | `ghcr.io/yzy806806/agora-coordinator` | Container image |
| `image.tag` | `0.14.0` | Image tag |
| `image.pullPolicy` | `IfNotPresent` | Image pull policy |
| `nameOverride` | `""` | Override chart name |
| `fullnameOverride` | `""` | Override full release name |

### Coordinator

| Key | Default | Description |
|-----|---------|-------------|
| `coordinator.resources` | see values.yaml | CPU/memory requests and limits |
| `coordinator.autoscaling.enabled` | `true` | Enable HPA |
| `coordinator.autoscaling.minReplicas` | `2` | Minimum replicas |
| `coordinator.autoscaling.maxReplicas` | `10` | Maximum replicas |
| `coordinator.affinity` | `{}` | Override default anti-affinity |

Default anti-affinity spreads coordinator pods across nodes using
`preferredDuringSchedulingIgnoredDuringExecution` with labels matching
the pod template selector.

### Service & Ingress

| Key | Default | Description |
|-----|---------|-------------|
| `service.type` | `ClusterIP` | Service type |
| `service.port` | `8000` | Service port |
| `service.sessionAffinity` | `ClientIP` | Sticky sessions for WS |
| `ingress.enabled` | `true` | Enable ingress |
| `ingress.className` | `nginx` | Ingress class |
| `ingress.host` | `agora.example.com` | Hostname |
| `ingress.tls.enabled` | `true` | Enable TLS |
| `ingress.tls.secretName` | `agora-tls` | TLS secret |

### Database

| Key | Default | Description |
|-----|---------|-------------|
| `database.embedded.enabled` | `true` | Deploy embedded Postgres |
| `database.embedded.image` | `postgres:16-alpine` | Postgres image |
| `database.embedded.storage` | `10Gi` | PVC size |
| `database.embedded.password` | `""` | Postgres password (required when embedded) |
| `database.externalUrl` | `""` | External Postgres URL |

### Redis

| Key | Default | Description |
|-----|---------|-------------|
| `redis.embedded.enabled` | `true` | Deploy embedded Redis |
| `redis.embedded.image` | `redis:7-alpine` | Redis image |
| `redis.embedded.storage` | `5Gi` | PVC size |
| `redis.externalUrl` | `""` | External Redis URL |

### Secrets

| Key | Default | Description |
|-----|---------|-------------|
| `secrets.databaseUrl` | `""` | Database URL (stored in Secret) |
| `secrets.redisUrl` | `""` | Redis URL (stored in Secret) |
| `secrets.jwtSecret` | `""` | JWT secret (stored in Secret) |
| `jwtSecret.value` | `""` | Alternative: set JWT secret directly |
| `jwtSecret.existingSecret` | `""` | Reference existing Secret |

### Hermes Bridge

| Key | Default | Description |
|-----|---------|-------------|
| `hermesBridge.enabled` | `false` | Deploy Hermes Bridge |
| `hermesBridge.image.repository` | `ghcr.io/.../agora-hermes-bridge` | Bridge image |
| `hermesBridge.image.tag` | `0.14.0` | Image tag |
| `hermesBridge.resources` | see values.yaml | CPU/memory |

### Workspace Storage

| Key | Default | Description |
|-----|---------|-------------|
| `workspace.storage.backend` | `local` | `local` (PVC) or `s3` |
| `workspace.persistence.enabled` | `true` | Enable PVC |
| `workspace.persistence.size` | `20Gi` | PVC size |
| `workspace.persistence.storageClass` | `""` | Storage class |
| `workspace.s3.bucket` | `""` | S3 bucket |
| `workspace.s3.endpoint` | `""` | S3 endpoint |
| `workspace.s3.accessKey` | `""` | S3 access key |
| `workspace.s3.secretKey` | `""` | S3 secret key |

### Monitoring

| Key | Default | Description |
|-----|---------|-------------|
| `monitoring.serviceMonitor.enabled` | `true` | Create ServiceMonitor |
| `monitoring.serviceMonitor.interval` | `30s` | Scrape interval |

### Service Account

| Key | Default | Description |
|-----|---------|-------------|
| `serviceAccount.create` | `true` | Create ServiceAccount |
| `serviceAccount.name` | `""` | Override SA name |

## Production Deployment

Use `values-prod.yaml` for production overrides:

```bash
helm install agora deploy/helm/agora \
  -f deploy/helm/agora/values-prod.yaml \
  --set database.externalUrl="postgresql://user:pass@pg-host:5432/agora" \
  --set redis.externalUrl="redis://redis-host:6379/0" \
  --set jwtSecret.value=$(openssl rand -hex 32) \
  --set workspace.s3.bucket=my-agora-workspace
```

### Bring Your Own Postgres

```bash
helm install agora deploy/helm/agora \
  --set database.embedded.enabled=false \
  --set database.externalUrl="postgresql://user:pass@pg-host:5432/agora"
```

### Bring Your Own Redis

```bash
helm install agora deploy/helm/agora \
  --set redis.embedded.enabled=false \
  --set redis.externalUrl="redis://redis-host:6379/0"
```

Required for multi-instance deployments. Enables cross-pod broadcast
of WebSocket events via Redis pub/sub.

### S3 Workspace Storage (Multi-Instance)

Required when running multiple replicas. PVC storage only works with
a single replica (ReadWriteOnce).

## Upgrading

```bash
helm upgrade agora deploy/helm/agora
```

Database migrations run automatically on startup via init container.

## Uninstall

```bash
helm uninstall agora
```

Persistent data (PVC) is retained by default. To delete PVCs:

```bash
kubectl delete pvc -l app.kubernetes.io/name=agora
```
