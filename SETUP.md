# SOC-Claw Setup Guide

This guide will help you get SOC-Claw running in different environments.

## Quick Start (Local Development)

### Prerequisites

- Docker and Docker Compose installed
- Python 3.11+ (for running outside Docker)
- vLLM installed locally (optional, for local inference)

### Step 1: Clone and Configure

```bash
# Clone the repository
git clone <repository-url>
cd SoC-Claw

# Copy environment file
cp .env.example .env

# Generate a secret key for session cookies
python -c "import secrets; print(secrets.token_hex(32))" >> .env
```

### Step 2: Start Services

```bash
# Start all services (Redis, Kafka, Zookeeper, App)
docker compose up

# Or start in detached mode
docker compose up -d
```

This will:
- Start Redis for job tracking
- Start Zookeeper and Kafka for message streaming
- Automatically create Kafka topics (`soc-claw-alerts` and `soc-claw-alerts-dlq`)
- Start the SOC-Claw application

### Step 3: Access the Application

- **Web UI**: http://localhost:7860
- **Default credentials**: `analyst` / `analyst` (⚠️ **Do not use in production!**)

### Step 4: Run vLLM (Optional)

For local inference, start vLLM on your host:

```bash
# Install vLLM (if not already installed)
uv pip install vllm --torch-backend=auto

# Start vLLM server
vllm serve mistral:7b-instruct --port 8000
```

The app will automatically connect to vLLM at `http://localhost:8000/v1`.

## Production Setup

### Prerequisites

- Kubernetes cluster or production server
- GCP project and service account
- Kafka cluster (or use managed Kafka)
- SIEM platform (Splunk, Sentinel, CrowdStrike)

### Step 1: Configure Environment Variables

Create a production `.env` file with the following values:

```bash
# --- Authentication ---
# Generate a secure secret key
SOC_CLAW_SECRET_KEY=<generate-with: python -c "import secrets; print(secrets.token_hex(32))">

# Create analyst accounts
SOC_CLAW_USERS=alice:$2b$12$<hash>,bob:$2b$12$<hash>
# Generate hashes with: python -m soc_claw.backend.auth <password>

# --- Kafka ---
# Your Kafka broker addresses
KAFKA_BOOTSTRAP_SERVERS=kafka-1:9092,kafka-2:9092,kafka-3:9092

# --- GCP ---
# Your GCP project ID
GCP_PROJECT_ID=your-project-id

# Your GCP bucket name (create this first)
GCP_BUCKET_NAME=soc-claw-results

# Service account key file path
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# --- Webhook ---
# Generate a secure webhook secret
WEBHOOK_SECRET=<generate-with: python -c "import secrets; print(secrets.token_hex(32))">
```

### Step 2: Create GCP Resources

```bash
# Create GCP bucket
gsutil mb -p your-project-id gs://soc-claw-results

# Create service account
gcloud iam service-accounts create soc-claw-sa \
    --display-name "SOC-Claw Service Account"

# Grant storage permissions
gsutil iam ch serviceAccount:soc-claw-sa@your-project-id.iam.gserviceaccount.com:objectAdmin \
    gs://soc-claw-results

# Create service account key
gcloud iam service-accounts keys create service-account-key.json \
    --iam-account soc-claw-sa@your-project-id.iam.gserviceaccount.com
```

### Step 3: Configure SIEM Webhook

Configure your SIEM to send alerts to the SOC-Claw webhook:

**Webhook URL**: `https://your-soc-claw-domain/api/siem/webhook`

**Headers**:
- `X-Signature`: HMAC-SHA256 signature of `timestamp.body`
- `X-Timestamp`: Unix timestamp in seconds
- `X-SIEM-Type`: `splunk` | `sentinel` | `crowdstrike`

**Signature Calculation**:
```python
import hmac
import hashlib
import time

body = b'{"id": "ALT-001", ...}'
timestamp = str(int(time.time()))
secret = "your-webhook-secret"

signature = hmac.new(
    secret.encode(),
    f"{timestamp}.{body.decode()}".encode(),
    hashlib.sha256
).hexdigest()
```

### Step 4: Deploy

**Using Docker Compose**:
```bash
# Build and start
docker compose up -d

# Check logs
docker compose logs -f app
```

**Using Kubernetes**:
```bash
# Create secrets
kubectl create secret generic soc-claw-secrets \
    --from-literal=secret-key=<your-secret-key> \
    --from-literal=webhook-secret=<your-webhook-secret>

# Create configmap
kubectl create configmap soc-claw-config \
    --from-file=.env

# Deploy
kubectl apply -f k8s/
```

## Environment-Specific Configuration

### Local Development

- **Kafka**: `localhost:9092` (Docker Compose)
- **Redis**: `localhost:6379` (Docker Compose)
- **GCP**: Optional (results logged to console)
- **vLLM**: `http://localhost:8000/v1` (host machine)

### Staging

- **Kafka**: Staging Kafka cluster
- **Redis**: Staging Redis instance
- **GCP**: Staging bucket
- **vLLM**: Cloud inference (OpenRouter, NVIDIA, etc.)

### Production

- **Kafka**: Production Kafka cluster (3+ brokers)
- **Redis**: Production Redis with persistence
- **GCP**: Production bucket with lifecycle policies
- **vLLM**: Cloud inference or local vLLM cluster

## Verification

### Check Service Health

```bash
# Check app health
curl http://localhost:7860/api/health

# Check webhook health
curl http://localhost:7860/api/siem/health

# Check batch API health
curl http://localhost:7860/api/batch/health
```

### Check Kafka Topics

```bash
# List topics
docker compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Check topic details
docker compose exec kafka kafka-topics --bootstrap-server localhost:9092 --describe --topic soc-claw-alerts
```

### Test Webhook

```bash
# Send test alert
curl -X POST http://localhost:7860/api/siem/webhook \
  -H "X-Signature: <signature>" \
  -H "X-Timestamp: <timestamp>" \
  -H "X-SIEM-Type: splunk" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ALT-001",
    "_time": "2026-04-25T14:32:00Z",
    "host": "DC-FINANCE-01",
    "sourcetype": "Suspicious PowerShell",
    "source": "Splunk",
    "_raw": "powershell.exe -enc ..."
  }'
```

### Test Batch API

```bash
# Upload JSONL file
curl -X POST http://localhost:7860/api/batch/upload \
  -F "file=@alerts.jsonl"

# Check job status
curl http://localhost:7860/api/batch/status/<job-id>

# Download results
curl http://localhost:7860/api/batch/results/<job-id>
```

## Troubleshooting

### Kafka Not Starting

```bash
# Check Kafka logs
docker compose logs kafka

# Check Zookeeper logs
docker compose logs zookeeper

# Restart Kafka
docker compose restart kafka
```

### App Can't Connect to Kafka

```bash
# Check Kafka is reachable
docker compose exec app nc -zv kafka 9092

# Check environment variables
docker compose exec app env | grep KAFKA
```

### GCP Upload Failing

```bash
# Check GCP credentials
docker compose exec app gcloud auth list

# Test GCP connection
docker compose exec app gsutil ls
```

### Webhook Signature Verification Failing

```bash
# Check webhook secret matches
docker compose exec app env | grep WEBHOOK_SECRET

# Verify signature calculation
python -c "
import hmac
import hashlib
import time

body = b'{\"id\": \"ALT-001\"}'
timestamp = str(int(time.time()))
secret = 'your-webhook-secret'

sig = hmac.new(
    secret.encode(),
    f'{timestamp}.{body.decode()}'.encode(),
    hashlib.sha256
).hexdigest()
print(f'Signature: {sig}')
"
```

## Monitoring

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f app
docker compose logs -f kafka
docker compose logs -f redis
```

### Check Metrics

The application emits OpenTelemetry metrics. Configure your monitoring system to scrape metrics from the application.

### GCP Cloud Monitoring

If using GCP, set up alert policies for:
- Consumer lag > 10000 for 5min
- DLQ rate > 10/min for 5min
- Processing latency p95 > 30s
- GCP upload failures > 5/min for 5min

## Next Steps

- Configure your SIEM to send alerts to the webhook
- Set up monitoring and alerting
- Review and tune the pipeline for your environment
- Set up automated backups for Redis and Kafka
- Configure log aggregation (e.g., ELK, Splunk)
- Set up automated testing and CI/CD

## Support

For issues or questions:
- Check the logs: `docker compose logs -f`
- Review the documentation in `docs/`
- Open an issue on GitHub
