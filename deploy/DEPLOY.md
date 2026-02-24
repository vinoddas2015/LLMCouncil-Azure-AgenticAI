# LLM Council MGA — Cloud Deployment Guide

## Quick Start (Local)

```bash
# Backend (Terminal 1)
uv run python -m backend.main

# Frontend (Terminal 2)
cd frontend && npm run dev

# Or use the start script
./start.sh
```

## Cloud-Agnostic Architecture

The storage and memory backends are pluggable via environment variables:

| Component          | Backend     | Env Trigger                      | Use Case                         |
|-------------------|-------------|----------------------------------|----------------------------------|
| **Conversations** | Local Files | `user_id == "local-user"`        | Dev, single-instance             |
| **Conversations** | Cosmos DB   | `COSMOS_ENDPOINT` + `COSMOS_KEY` | Azure cloud (primary)            |
| **Conversations** | Blob Storage| `AZURE_STORAGE_CONNECTION_STRING`| Azure cloud (legacy fallback)    |
| **Memory**        | Local JSON  | Default (no Cosmos config)       | Dev, single-instance             |
| **Memory**        | Cosmos DB   | `COSMOS_ENDPOINT` + `COSMOS_KEY` | Azure cloud (primary)            |
| **Files**         | Blob Storage| `AZURE_STORAGE_CONNECTION_STRING`| File attachments in cloud        |

---

## Azure Cosmos DB Setup (CLI)

> **Reference**: <https://learn.microsoft.com/en-us/cli/azure/cosmosdb?view=azure-cli-latest>

### Prerequisites

```powershell
# Install / update Azure CLI
winget install -e --id Microsoft.AzureCLI

# Login
az login

# Set subscription (if multiple)
az account set -s <subscription-name-or-id>
```

### 1. Create Resource Group

```bash
az group create \
  --name rg-llmcouncil \
  --location eastus
```

### 2. Create Cosmos DB Account (NoSQL API)

```bash
# Create a Cosmos DB account with Session consistency and Continuous backup
az cosmosdb create \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --kind GlobalDocumentDB \
  --default-consistency-level Session \
  --locations regionName=eastus failoverPriority=0 isZoneRedundant=False \
  --backup-policy-type Continuous \
  --continuous-tier Continuous7Days \
  --enable-automatic-failover true \
  --enable-free-tier true \
  --minimal-tls-version Tls12 \
  --public-network-access ENABLED \
  --tags project=llm-council environment=production
```

**Key parameters** (from latest `az cosmosdb create`):
| Parameter | Values | Description |
|---|---|---|
| `--kind` | `GlobalDocumentDB`, `MongoDB`, `Parse` | NoSQL API = GlobalDocumentDB |
| `--default-consistency-level` | `Strong`, `BoundedStaleness`, `Session`, `ConsistentPrefix`, `Eventual` | Session recommended for web apps |
| `--backup-policy-type` | `Continuous`, `Periodic` | Continuous enables PITR |
| `--continuous-tier` | `Continuous7Days`, `Continuous30Days` | Retention window |
| `--enable-free-tier` | `true/false` | 1 free-tier account per subscription |
| `--enable-burst-capacity` | `true/false` | Burst unused RU/s (Preview) |
| `--enable-partition-merge` | `true/false` | Merge underutilised partitions |
| `--capacity-mode` | `None`, `Provisioned`, `Serverless` | Preview extension only |
| `--minimal-tls-version` | `Tls`, `Tls11`, `Tls12` | Use Tls12 for security |
| `--public-network-access` | `ENABLED`, `DISABLED`, `SECUREDBYPERIMETER` | Network access control |

### 3. Check Account Name Availability

```bash
az cosmosdb check-name-exists --name llmcouncil-cosmos
```

### 4. Create SQL Database

```bash
az cosmosdb sql database create \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --name llm-council
```

### 5. Create SQL Containers

```bash
# Conversations container (partitioned by user_id)
az cosmosdb sql container create \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --database-name llm-council \
  --name conversations \
  --partition-key-path /user_id \
  --throughput 400

# Memory container (partitioned by collection)
az cosmosdb sql container create \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --database-name llm-council \
  --name memory \
  --partition-key-path /collection \
  --throughput 400
```

### 6. Get Connection Keys

```bash
# List keys (primary, secondary, read-only)
az cosmosdb keys list \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil

# List connection strings
az cosmosdb keys list \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --type connection-strings
```

### 7. Get Account Details

```bash
az cosmosdb show \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil
```

### 8. Set Environment Variables

After provisioning, configure your `.env`:

```dotenv
COSMOS_ENDPOINT=https://llmcouncil-cosmos.documents.azure.com:443/
COSMOS_KEY=<primaryKey from step 6>
COSMOS_DATABASE=llm-council
COSMOS_CONVERSATIONS_CONTAINER=conversations
COSMOS_MEMORY_CONTAINER=memory
```

### Optional: Multi-Region Replication

```bash
# Add a read region (UK South, zone-redundant)
az cosmosdb update \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --locations regionName=eastus failoverPriority=0 isZoneRedundant=False \
  --locations regionName=uksouth failoverPriority=1 isZoneRedundant=True
```

### Optional: Configure Throughput Autoscale

```bash
# Switch conversations container to autoscale (400–4000 RU/s)
az cosmosdb sql container throughput migrate \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --database-name llm-council \
  --name conversations \
  --throughput-type autoscale
```

### Optional: Network Security

```bash
# Restrict to specific VNet
az cosmosdb network-rule add \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --virtual-network <vnet-name> \
  --subnet <subnet-name>

# Disable public access
az cosmosdb update \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --public-network-access DISABLED

# Enable private endpoint
az cosmosdb private-endpoint-connection approve \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --name <pe-connection-name>
```

### Optional: Managed Identity (Passwordless Auth)

```bash
# Assign system-managed identity
az cosmosdb identity assign \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil

# Create SQL role assignment for the identity
az cosmosdb sql role assignment create \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --role-definition-id 00000000-0000-0000-0000-000000000002 \
  --principal-id <managed-identity-principal-id> \
  --scope /
```

### Teardown

```bash
# Delete specific containers
az cosmosdb sql container delete \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --database-name llm-council \
  --name conversations --yes

# Delete database
az cosmosdb sql database delete \
  --account-name llmcouncil-cosmos \
  --resource-group rg-llmcouncil \
  --name llm-council --yes

# Delete entire account
az cosmosdb delete \
  --name llmcouncil-cosmos \
  --resource-group rg-llmcouncil --yes

# Delete resource group (removes everything)
az group delete --name rg-llmcouncil --yes
```

---

## Azure Blob Storage Setup (CLI)

```bash
# Create storage account
az storage account create \
  --name llmcouncilstorage \
  --resource-group rg-llmcouncil \
  --location eastus \
  --sku Standard_LRS

# Create blob container
az storage container create \
  --account-name llmcouncilstorage \
  --name conversations

# Get connection string
az storage account show-connection-string \
  --name llmcouncilstorage \
  --resource-group rg-llmcouncil
```

---

## Azure Deployment (Container Apps)

```bash
# Build & push to ACR
az acr build --registry <acr-name> --image llm-council:latest .

# Deploy to Container Apps
az containerapp create \
  --name llm-council \
  --resource-group rg-llmcouncil \
  --image <acr-name>.azurecr.io/llm-council:latest \
  --target-port 8001 \
  --env-vars \
    COSMOS_ENDPOINT=https://llmcouncil-cosmos.documents.azure.com:443/ \
    COSMOS_KEY=<key> \
    COSMOS_DATABASE=llm-council \
    AZURE_STORAGE_CONNECTION_STRING=<blob-conn-string>
```

## GCP Deployment (Cloud Run)

```bash
# Build & push to Artifact Registry
gcloud builds submit --tag gcr.io/<project>/llm-council

# Deploy to Cloud Run
gcloud run deploy llm-council \
  --image gcr.io/<project>/llm-council \
  --port 8001 \
  --set-env-vars MEMORY_BACKEND=redis,REDIS_URL=<redis-url>
```

## Kubernetes (Any Cloud)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-council
spec:
  replicas: 3
  selector:
    matchLabels:
      app: llm-council
  template:
    metadata:
      labels:
        app: llm-council
    spec:
      containers:
      - name: council
        image: llm-council:latest
        ports:
        - containerPort: 8001
        env:
        - name: MEMORY_BACKEND
          value: redis
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: council-secrets
              key: redis-url
        livenessProbe:
          httpGet:
            path: /api/health
            port: 8001
          initialDelaySeconds: 15
          periodSeconds: 30
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
---
apiVersion: v1
kind: Service
metadata:
  name: llm-council
spec:
  selector:
    app: llm-council
  ports:
  - port: 80
    targetPort: 8001
  type: LoadBalancer
```

## Scaling Considerations

- **Horizontal**: Cosmos DB backend shares state across instances automatically
- **Memory Store**: TF-IDF index is rebuilt on startup for local backend; Cosmos DB provides instant warm-start
- **Data Volume**: Cosmos DB autoscale (400–4000 RU/s) handles variable traffic
- **Health Check**: `/api/health` endpoint available for load balancer probes
- **Cost**: Free tier provides 1000 RU/s + 25 GB storage; autoscale for production

## CLI Quick Reference

| Action | Command |
|---|---|
| Create account | `az cosmosdb create -n <name> -g <rg> --kind GlobalDocumentDB` |
| Check name | `az cosmosdb check-name-exists --name <name>` |
| List accounts | `az cosmosdb list [-g <rg>]` |
| Show account | `az cosmosdb show -n <name> -g <rg>` |
| Get keys | `az cosmosdb keys list -n <name> -g <rg>` |
| Regenerate key | `az cosmosdb keys regenerate -n <name> -g <rg> --key-kind primary` |
| Create database | `az cosmosdb sql database create -a <acct> -g <rg> -n <db>` |
| Create container | `az cosmosdb sql container create -a <acct> -g <rg> -d <db> -n <ctr> -p <pk>` |
| Show throughput | `az cosmosdb sql container throughput show -a <acct> -g <rg> -d <db> -n <ctr>` |
| Update throughput | `az cosmosdb sql container throughput update -a <acct> -g <rg> -d <db> -n <ctr> --throughput 800` |
| Failover test | `az cosmosdb failover-priority-change -n <name> -g <rg> --failover-policies <region>=0` |
| Delete account | `az cosmosdb delete -n <name> -g <rg> --yes` |
| Offline region | `az cosmosdb offline-region -n <name> -g <rg> --region <region>` |
