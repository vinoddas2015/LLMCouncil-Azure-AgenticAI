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

The memory backend is pluggable via the `MEMORY_BACKEND` environment variable:

| Backend     | Env Value   | Use Case                        |
|------------|-------------|----------------------------------|
| Local JSON | `local`     | Dev, single-instance             |
| Redis      | `redis`     | Multi-instance, low-latency      |
| DynamoDB   | `dynamodb`  | AWS serverless, auto-scaling     |
| Cosmos DB  | `cosmosdb`  | Azure, global distribution       |

## AWS Deployment (ECS / Fargate)

```bash
# Build & push to ECR
aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
docker build -t llm-council .
docker tag llm-council:latest <account>.dkr.ecr.<region>.amazonaws.com/llm-council:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/llm-council:latest

# Deploy with ECS task definition (set MEMORY_BACKEND=dynamodb)
```

## Azure Deployment (Container Apps)

```bash
# Build & push to ACR
az acr build --registry <acr-name> --image llm-council:latest .

# Deploy to Container Apps
az containerapp create \
  --name llm-council \
  --resource-group <rg> \
  --image <acr-name>.azurecr.io/llm-council:latest \
  --target-port 8001 \
  --env-vars MEMORY_BACKEND=cosmosdb COSMOS_ENDPOINT=<endpoint> COSMOS_KEY=<key>
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

- **Horizontal**: Use Redis/DynamoDB/CosmosDB backend for shared memory across instances
- **Memory Store**: TF-IDF index is rebuilt on startup — Redis provides instant warm-start
- **Data Volume**: Mount persistent volume for local backend, or use managed database
- **Health Check**: `/api/health` endpoint available for load balancer probes
