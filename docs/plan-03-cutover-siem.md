# Plan 03 — Cutover: SIEM Alert Ingress

**Parent:** [production_data_architecture.md](production_data_architecture.md), step 4 (per-source cutover)
**Status:** Draft — step list to flesh out at implementation time once the target SIEM is chosen.

## Goal

Replace the static [data/advanced_siem_dataset.jsonl](../data/advanced_siem_dataset.jsonl) reader with real-time alert ingress from production SIEM platforms (Splunk, Sentinel, Elastic, CrowdStrike).

## Scope

- **In:** Kafka consumer, FastAPI webhook endpoint, batch API endpoint, schema normalization, Kafka-based DLQ with automatic reprocessing.
- **Out:** GCP Bucket output (JSONL format), SIEM-side rule authoring; alert deduplication strategy beyond simple idempotency (deferred to v2).

## Pinned decisions

| Decision | Choice | Rationale |
| :--- | :--- | :--- |
| Primary ingress | Kafka topic consumer | Most production SIEMs publish to Kafka or can be configured to |
| Bridge ingress | FastAPI webhook | Adapter for SIEMs that cannot publish to Kafka |
| Batch ingress | FastAPI batch API (asynchronous) | For batch JSONL uploads, returns job ID immediately |
| Queue | Kafka topic (single source of truth) | Kafka is purpose-built for event streaming, durable, replayable |
| Schema | Normalize to existing `Alert` pydantic schema | Keeps downstream call sites unchanged |
| Webhook auth | HMAC-SHA256 over body, per-tenant secret | Industry-standard webhook signing |
| Output | GCP Bucket (JSONL format) | Flexible destination, industry standard for log storage |
| Bad events | Push to DLQ Kafka topic, log, alert; pipeline continues | Don't block live pipeline on malformed events |
| Idempotency | Kafka consumer group offsets | Prevents re-processing on consumer restart |
| DLQ reprocessing | Automatic reprocessing from DLQ topic (max 3 retries) | Self-healing for transient failures |
| Error retry | 3 retries with 30s delay for service unavailability | Handles service startup delays |
| Agent down | Stop pipeline with error message | Requires manual intervention for agent failures |

## Schema Normalization Strategy

### Target SIEM Field Mappings

**Splunk (primary example):**
```python
splunk_mapping = {
    "_time": "timestamp",
    "_raw": "payload",
    "source": "source",
    "sourcetype": "rule_name",
    "host": "hostname",
    "result.source_ip": "source_ip",
    "result.dest_ip": "dest_ip",
    "result.alert_id": "id"
}
```

**Microsoft Sentinel:**
```python
sentinel_mapping = {
    "properties.alertDisplayName": "rule_name",
    "properties.startTimeUtc": "timestamp",
    "systemAlertId": "id",
    "entities.host.name": "hostname",
    "entities.ipAddress.address": "source_ip"
}
```

**CrowdStrike:**
```python
crowdstrike_mapping = {
    "detection_id": "id",
    "timestamp": "timestamp",
    "severity": "severity",  # Map to P1-P4 via severity_to_prio()
    "composite.hostname": "hostname",
    "composite.source_ip": "source_ip"
}
```

### Mapper Implementation Structure

Create SIEM-specific mappers in `soc_claw/connectors/siem_{splunk|sentinel|crowdstrike}.py`:

```python
# Base interface
class SIEMMapper(ABC):
    @abstractmethod
    def normalize(self, raw_event: dict) -> dict:
        """Transform SIEM-specific JSON to Alert schema."""
        pass

    @abstractmethod
    def extract_source(self, raw_event: dict) -> str:
        """Return SIEM platform identifier for idempotency."""
        pass
```

### Missing Field Handling

- **Required fields** (`id`, `timestamp`, `hostname`, `rule_name`): Reject with `SCHEMA_VALIDATION` error
- **Optional fields** (`source_ip`, `dest_ip`, `payload`): Use `None` or empty string
- **Unknown fields**: Preserve via `Alert.model_config = ConfigDict(extra="allow")`
- **ground_truth**: Strip entirely from production alerts (dev-only field)

### Normalization Steps

1. Extract SIEM source identifier
2. Apply field mapping based on SIEM type
3. Validate against `Alert` pydantic schema
4. Strip `ground_truth` if present
5. Return normalized dict or raise `NormalizationError`

## Kafka Configuration

### Kafka Topic Specification

```yaml
alerts_topic: "soc-claw-alerts"
dlq_topic: "soc-claw-alerts-dlq"
partitions: 3
replication_factor: 1
consumer_group: "soc-claw-consumers"
auto_offset_reset: "earliest"
enable_auto_commit: false
```

### Producer Operations

**Webhook/Batch API (Kafka producer):**
```python
await kafka_producer.send(
    "soc-claw-alerts",
    value=json.dumps(alert).encode(),
    key=alert["id"].encode()
)
```

### Consumer Operations

**Pipeline trigger (Kafka consumer):**
```python
async for message in consumer:
    alert = json.loads(message.value)
    result = await run_pipeline(alert)
    await output_gcp.upload(result)
    # Manual offset commit after successful processing
    await consumer.commit()
```

### Topic Initialization

```bash
# Create topics
kafka-topics --create --topic soc-claw-alerts --partitions 3 --replication-factor 1
kafka-topics --create --topic soc-claw-alerts-dlq --partitions 1 --replication-factor 1
```

## Idempotency Implementation

### Kafka Consumer Group Offsets

**How it works:**
- Each consumer group tracks its own offset per partition
- Offsets are committed after successful processing
- On restart, consumer resumes from last committed offset
- No duplicate processing within offset commit window

### Offset Management

```python
# Manual offset commit (recommended)
async for message in consumer:
    try:
        alert = json.loads(message.value)
        result = await run_pipeline(alert)
        await output_gcp.upload(result)
        # Commit offset only after successful processing
        await consumer.commit()
    except Exception as e:
        # Don't commit offset on failure
        # Message will be reprocessed on restart
        logger.error(f"Failed to process alert: {e}")
```

### Idempotency Window

- **Within offset commit window**: No duplicates (Kafka guarantees)
- **After offset commit**: Possible duplicates if consumer crashes before commit
- **Mitigation**: Idempotent pipeline operations (tools are safe to retry)

### No Additional Storage Needed

- **No Redis sorted sets** required
- **No hash computation** required
- **Kafka offsets** provide sufficient deduplication for most use cases

## Kafka Consumer Configuration

### Consumer Settings

```python
# Consumer configuration
consumer_settings = {
    "bootstrap_servers": "localhost:9092",
    "group_id": "soc-claw-consumers",
    "auto_offset_reset": "earliest",
    "enable_auto_commit": False,  # Manual commit for reliability
    "max_poll_records": 10,
    "session_timeout_ms": 30000,
    "heartbeat_interval_ms": 3000,
}
```

### Concurrency Model

- **Partitions**: 3 (for parallelism)
- **Consumer instances**: 2 (for high availability)
- **Workers per instance**: 10 (concurrent processing)
- **Total throughput**: 20 alerts processed concurrently

### Backpressure Handling

Kafka handles backpressure natively:
- **Producer**: Slows down if consumer can't keep up
- **Consumer**: Processes at its own pace
- **No data loss**: Kafka buffers messages

### Consumer Lag Monitoring

```python
# Monitor consumer lag
lag = consumer.get_watermark_offsets()
if lag > 10000:
    logger.warning(f"High consumer lag: {lag} messages behind")
```

## Error Handling & Dead-Letter Queue

### Error Classification

```python
class ErrorType(Enum):
    INVALID_JSON = "invalid_json"              # Malformed JSON body
    SCHEMA_VALIDATION = "schema_validation"    # Missing required fields
    NORMALIZATION_FAILURE = "normalization"     # SIEM mapper failed
    PIPELINE_TIMEOUT = "pipeline_timeout"      # Pipeline took too long
    AGENT_UNAVAILABLE = "agent_unavailable"    # Agent service down
    SERVICE_UNAVAILABLE = "service_unavailable" # External service not ready
```

### DLQ Entry Structure

```python
@dataclass
class DLQEntry:
    original_event: dict
    error_type: ErrorType
    error_message: str
    siem_source: str
    ingested_at: str
    retry_count: int = 0
```

### DLQ Kafka Topic Configuration

```yaml
topic_name: "soc-claw-alerts-dlq"
partitions: 1
replication_factor: 1
retention: 7 days
```

### DLQ Write Operation

```python
async def push_to_dlq(raw_event: dict, error: Exception, source: str):
    entry = {
        "original_event": raw_event,
        "error_type": error_type.value,
        "error_message": str(error),
        "siem_source": source,
        "ingested_at": datetime.utcnow().isoformat(),
        "retry_count": 0
    }
    await dlq_producer.send(
        "soc-claw-alerts-dlq",
        value=json.dumps(entry).encode(),
        key=raw_event.get("id", "unknown").encode()
    )

    # Emit metric
    otel_counter("soc_claw_alerts_dlq_total", {"error_type": error_type.value}).add(1)

    # Alert if DLQ rate exceeds threshold
    dlq_rate = await get_dlq_rate()
    if dlq_rate > 10:  # 10/min
        logger.error(f"High DLQ rate: {dlq_rate}/min")
        # Send alert via GCP Cloud Monitoring
```

### Error Handling Flow

```python
try:
    # 1. Parse JSON
    raw_event = json.loads(body)
except json.JSONDecodeError as e:
    await push_to_dlq({"body": body}, ErrorType.INVALID_JSON, source)
    return {"status": "error", "reason": "invalid_json"}

# 2. Normalize
try:
    alert = mapper.normalize(raw_event)
except NormalizationError as e:
    await push_to_dlq(raw_event, ErrorType.NORMALIZATION_FAILURE, source)
    return {"status": "error", "reason": "normalization_failed"}

# 3. Validate schema
try:
    Alert.model_validate(alert)
except ValidationError as e:
    await push_to_dlq(alert, ErrorType.SCHEMA_VALIDATION, source)
    return {"status": "error", "reason": "schema_validation_failed"}

# 4. Publish to Kafka
try:
    await kafka_producer.send("soc-claw-alerts", value=json.dumps(alert).encode())
except Exception as e:
    await push_to_dlq(alert, ErrorType.SERVICE_UNAVAILABLE, source)
    return {"status": "error", "reason": "kafka_unavailable"}
```

### DLQ Automatic Reprocessing

```python
async def reprocess_dlq():
    """Automatically reprocess DLQ entries."""
    while True:
        for message in dlq_consumer:
            entry = json.loads(message.value)
            retry_count = entry.get("retry_count", 0)

            if retry_count >= 3:
                logger.error(f"Max retries exceeded for alert {entry.get('original_event', {}).get('id')}")
                continue

            try:
                # Reprocess alert
                result = await run_pipeline(entry["original_event"])
                await output_gcp.upload(result)
                # Success: don't put back in DLQ
            except Exception as e:
                # Failure: increment retry count and put back in DLQ
                entry["retry_count"] = retry_count + 1
                await push_to_dlq(entry, e, entry["siem_source"])

        await asyncio.sleep(300)  # Check every 5 minutes
```

## Monitoring & Observability

### OpenTelemetry Metrics

```python
# Counter metrics
alerts_ingested_total = otel_counter(
    "soc_claw_alerts_ingested_total",
    {"source": "splunk|sentinel|crowdstrike"}
)

alerts_processed_total = otel_counter(
    "soc_claw_alerts_processed_total",
    {"severity": "P1|P2|P3|P4"}
)

alerts_dropped_total = otel_counter(
    "soc_claw_alerts_dropped_total",
    {"reason": "backpressure|validation|dlq"}
)

alerts_dlq_total = otel_counter(
    "soc_claw_alerts_dlq_total",
    {"error_type": "invalid_json|schema_validation|..."}
)

# Gauge metrics
alert_queue_depth = otel_gauge("soc_claw_alert_queue_depth")
dlq_queue_depth = otel_gauge("soc_claw_dlq_queue_depth")
consumer_paused = otel_gauge("soc_claw_consumer_paused")

# Histogram metrics
processing_latency = otel_histogram(
    "soc_claw_processing_latency_seconds",
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0]
)

ingestion_to_triage_latency = otel_histogram(
    "soc_claw_ingestion_to_triage_latency_seconds",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)
```

### Logging Strategy

```python
# Alert ingestion
logger.info(
    "alert_ingested",
    extra={
        "alert_id": alert["id"],
        "source": source,
        "timestamp": alert["timestamp"],
        "severity": alert.get("severity")
    }
)

# Normalization warnings
logger.warning(
    "normalization_warning",
    extra={
        "source": source,
        "missing_fields": missing_fields,
        "used_defaults": used_defaults
    }
)

# DLQ entries
logger.error(
    "dlq_entry",
    extra={
        "error_type": error_type.value,
        "error_message": str(error),
        "siem_source": source,
        "alert_id": alert.get("id", "unknown")
    }
)

# Kafka consumer events
logger.info(
    "kafka_consumer",
    extra={
        "topic": "soc-claw-alerts",
        "partition": message.partition,
        "offset": message.offset,
        "lag": consumer_lag
    }
)

# GCP upload events
logger.info(
    "gcp_upload",
    extra={
        "alert_id": alert["id"],
        "bucket": bucket_name,
        "path": object_path,
        "status": "success"
    }
)
```

### GCP Cloud Monitoring Alerting

```yaml
# Alert policies
- name: High Consumer Lag
  condition: soc_claw_kafka_consumer_lag > 10000 for 5m
  notification: PagerDuty

- name: High DLQ Rate
  condition: rate(soc_claw_alerts_dlq_total[5m]) > 10
  notification: Slack #security-ops

- name: High Processing Latency
  condition: histogram_percentile(soc_claw_processing_latency_seconds, 95) > 30s
  notification: Email

- name: GCP Upload Failures
  condition: rate(soc_claw_gcp_upload_failed_total[5m]) > 5
  notification: Slack #devops
```

### Dashboard Queries

```promql
# Consumer lag over time
soc_claw_kafka_consumer_lag

# Ingestion rate by source
sum(rate(soc_claw_alerts_ingested_total[5m])) by (source)

# Processing latency p95
histogram_quantile(0.95, rate(soc_claw_processing_latency_seconds_bucket[5m]))

# DLQ rate by error type
sum(rate(soc_claw_alerts_dlq_total[5m])) by (error_type)

# GCP upload success rate
rate(soc_claw_gcp_upload_success_total[5m])
```

## Performance & Capacity Planning

### Expected Alert Volume

```yaml
peak_volume: 1000 alerts/sec
average_volume: 200 alerts/sec
burst_duration: 15 minutes
daily_volume: ~17 million alerts
```

### Pipeline Capacity Analysis

**Per-alert latency:**
- Triage: 2s (includes tool calls)
- Verification: 1s
- Response: 1s
- **Total**: 4s per alert

**Throughput requirements:**
- Peak: 1000 alerts/sec
- Per-pod capacity: 100 alerts/sec (4s latency × 25 concurrent workers)
- **Required pods**: 10 pods

### Infrastructure Requirements

**Kafka:**
```yaml
brokers: 3
replication_factor: 3
partitions: 3
retention: 7 days
throughput: 1000 msg/sec
```

**GCP Bucket:**
```yaml
bucket_name: soc-claw-results
storage_class: STANDARD
lifecycle_policy: 30 days
location: us-central1
```

**Pipeline workers:**
```yaml
pods: 2
cpu_per_pod: 2 cores
memory_per_pod: 4GB
concurrent_workers_per_pod: 10
```

### Bottleneck Analysis

**Potential bottlenecks (ordered by likelihood):**

1. **LLM inference** (vLLM throughput)
   - Mitigation: Scale vLLM horizontally, use batch inference

2. **Tool calls** (external API latency)
   - Mitigation: Cache results, parallelize tool calls

3. **Network bandwidth**
   - Requirement: 1Gbps minimum
   - Mitigation: Compress payloads, use dedicated network

4. **Kafka consumer throughput**
   - Requirement: 1000 msg/sec
   - Mitigation: Increase partitions, scale consumers

5. **GCP upload latency**
   - Requirement: < 1s per result
   - Mitigation: Batch uploads, retry on failure

### Performance Testing Plan

```yaml
load_test:
  duration: 30 minutes
  rate: 1000 alerts/sec
  phases:
    - ramp: 0 → 1000 over 5 min
    - sustain: 1000 for 20 min
    - ramp_down: 1000 → 0 over 5 min

metrics_to_capture:
  - p50/p95/p99 latency
  - consumer lag over time
  - error rate
  - DLQ rate
  - GCP upload success rate
  - resource utilization (cpu, memory, network)

success_criteria:
  - p95 latency < 10s
  - error rate < 0.1%
  - consumer lag < 10000
  - DLQ rate < 10/min
  - GCP upload success rate > 99%
```

## Steps (implementation detail)

### Phase 1: Schema Normalization

1. **Document field mappings** for target SIEM (start with Splunk as primary example)
   - Create `soc_claw/connectors/siem_splunk.py` with `SplunkMapper` class
   - Map Splunk fields (`_time`, `_raw`, `host`, etc.) to `Alert` schema
   - Add missing field handling with sensible defaults
   - Strip `ground_truth` field from production alerts

2. **Create base mapper interface**
   - Define `SIEMMapper` abstract base class in `soc_claw/connectors/base.py`
   - Implement `normalize()` and `extract_source()` methods
   - Add `NormalizationError` exception class

3. **Add mappers for other SIEMs** (as needed)
   - `soc_claw/connectors/siem_sentinel.py` for Microsoft Sentinel
   - `soc_claw/connectors/siem_crowdstrike.py` for CrowdStrike
   - Follow same interface as Splunk mapper

### Phase 2: Kafka Setup

4. **Add Kafka to docker-compose.yml**
   - Add Kafka service (confluentinc/cp-kafka)
   - Add Zookeeper service (confluentinc/cp-zookeeper)
   - Configure networking and ports
   - Set environment variables

5. **Create Kafka topics** (one-time setup)
   - Create `soc-claw-alerts` topic with 3 partitions
   - Create `soc-claw-alerts-dlq` topic with 1 partition
   - Document in ops playbook for production deployment

### Phase 3: Ingress Adapters

6. **Build webhook endpoint** in `soc_claw/backend/routes/siem_webhook.py`
   - HMAC-SHA256 verification with per-tenant secret
   - Max-age timestamp check: reject if > 5 minutes old
   - SIEM type detection from headers or payload
   - Route to appropriate mapper
   - Publish to Kafka topic (not Redis)
   - Return `401` on invalid HMAC, `400` on malformed event
   - Push to DLQ on normalization/validation failures

7. **Build batch API endpoint** in `soc_claw/backend/routes/batch_api.py`
   - `POST /api/batch/upload` - Upload JSONL file
   - Parse JSONL file and validate each alert
   - Create job record in Redis (for job tracking)
   - Publish alerts to Kafka topic
   - Return job ID immediately (asynchronous)
   - `GET /api/batch/status/{job_id}` - Check job status
   - `GET /api/batch/results/{job_id}` - Download results

8. **Create job manager** in `soc_claw/connectors/job_manager.py`
   - Track batch job status (pending → processing → completed/failed)
   - Store job metadata in Redis
   - Update job progress
   - Store results location

### Phase 4: Kafka Consumer & Pipeline

9. **Build Kafka consumer** in `soc_claw/connectors/kafka_consumer.py`
   - Subscribe to `soc-claw-alerts` topic
   - Consumer group: `soc-claw-consumers`
   - Manual offset commit (after successful processing)
   - Process messages concurrently
   - Pass to pipeline
   - Handle errors per requirements

10. **Update pipeline** in `soc_claw/pipeline.py`
    - Remove `load_alerts()` function (no longer needed)
    - Remove `load_alerts_from_queue()` function (no longer needed)
    - Remove `ALERT_SOURCE` feature flag (no longer needed)
    - Keep `run_pipeline()` function
    - Keep `execute_approved_action()` function

### Phase 5: Output & DLQ

11. **Build GCP output API** in `soc_claw/connectors/output_gcp.py`
    - Accept pipeline results
    - Write to GCP Bucket (JSONL format)
    - File organization: `realtime/{year}/{month}/{day}/{hour}/alerts_{timestamp}.jsonl`
    - Handle authentication (service account key)
    - Retry on failure (3 retries, 30s delay)

12. **Build DLQ handler** in `soc_claw/connectors/dlq_kafka.py`
    - Separate Kafka topic: `soc-claw-alerts-dlq`
    - Write failed alerts with error details
    - Error classification: `INVALID_JSON`, `SCHEMA_VALIDATION`, `NORMALIZATION_FAILURE`, `PIPELINE_TIMEOUT`, `AGENT_UNAVAILABLE`, `SERVICE_UNAVAILABLE`
    - Write DLQ entries to GCP Bucket

13. **Build DLQ reprocessor** in `soc_claw/connectors/dlq_reprocessor.py`
    - Read from DLQ topic
    - Attempt to reprocess failed alerts
    - Max retries: 3
    - Retry delay: 60 seconds
    - On success: write to main topic
    - On failure: increment retry count and keep in DLQ

### Phase 6: Error Handling

14. **Implement error handling strategy**
    - Log parsing errors → DLQ
    - Agent down → Stop pipeline with error message
    - Service not started → Retry 3 times with 30s delay
    - Pipeline timeout → DLQ, continue processing next alert

### Phase 7: Monitoring & Testing

15. **Add OpenTelemetry instrumentation**
    - Kafka consumer lag metric
    - Ingestion/processing rate counters
    - Latency histograms
    - DLQ rate counter
    - GCP upload success/failure metrics
    - Batch job metrics

16. **Add structured logging**
    - Alert ingestion events
    - Normalization warnings
    - DLQ entries
    - Kafka consumer events
    - GCP upload events

17. **Create GCP Cloud Monitoring alert policies**
    - Consumer lag > 10000 for 5min
    - DLQ rate > 10/min for 5min
    - Processing latency p95 > 30s
    - GCP upload failures > 5/min for 5min

18. **Write comprehensive tests**
    - Unit: HMAC verification, schema normalization, error classification
    - Integration: Kafka → pipeline → GCP, webhook → Kafka → pipeline → GCP
    - Batch API: JSONL upload, job tracking, results download
    - Error cases: Invalid HMAC → 401, malformed event → DLQ, agent down → stop pipeline
    - Performance: 1000 alerts/sec for 5min, verify consumer lag, verify GCP upload

### Phase 8: Configuration

19. **Update `.env.example`**
    - Add Kafka configuration
    - Add GCP configuration
    - Add batch API configuration
    - Add error handling configuration
    - Add DLQ reprocessing configuration

20. **Update docker-compose.yml**
    - Add Kafka service
    - Add Zookeeper service
    - Update environment variables
    - Configure networking

### Phase 9: Documentation

21. **Update ops documentation**
    - Kafka topic management
    - Consumer lag monitoring
    - DLQ inspection and reprocessing
    - Webhook secret rotation procedure
    - GCP Bucket management

## Acceptance criteria

### Functional Requirements

- **E2E Kafka flow**: Kafka publish → pipeline → triage agent runs → response plan generated → GCP Bucket
- **E2E webhook flow**: webhook POST with valid HMAC → Kafka → pipeline → triage runs → response plan generated → GCP Bucket
- **E2E batch API flow**: JSONL upload → job ID → Kafka → pipeline → results → GCP Bucket
- **Invalid HMAC**: Returns `401`, no Kafka write, no metric increment
- **Malformed event**: Pushed to DLQ with error classification, pipeline continues running
- **Schema normalization**: Splunk/Sentinel/CrowdStrike events normalized to `Alert` schema
- **Missing fields**: Required fields rejected with `SCHEMA_VALIDATION` error, optional fields use defaults
- **ground_truth stripping**: Production alerts have no `ground_truth` field

### Performance Requirements

- **Throughput**: Handle 1000 alerts/sec peak
- **Latency**: p95 processing latency < 10s (ingestion → triage start)
- **Consumer lag**: < 10000 messages behind
- **Error rate**: < 0.1% of alerts end up in DLQ
- **GCP upload**: > 99% success rate

### Monitoring Requirements

- **Metrics emitted**: All OpenTelemetry metrics visible in GCP Cloud Monitoring
- **Alerts configured**: Consumer lag, DLQ rate, latency, GCP upload failures
- **Logging**: Structured JSON logs for all alert ingestion, normalization, DLQ, Kafka consumer, GCP upload events
- **Dashboard**: GCP dashboard showing consumer lag, ingestion rate, processing latency, error rate, GCP upload success rate

### Data Requirements

- **Idempotency**: Duplicate alerts ignored via Kafka consumer group offsets
- **DLQ retention**: DLQ entries retained for 7 days in Kafka
- **Kafka retention**: Alerts retained for 7 days in Kafka
- **GCP retention**: Results retained for 30 days in GCP Bucket
- **Data integrity**: No alerts dropped (Kafka provides durability)

### Testing Requirements

- **Unit tests**: HMAC verification, schema normalization, error classification
- **Integration tests**: Kafka → pipeline → GCP, webhook → Kafka → pipeline → GCP, batch API → Kafka → pipeline → GCP
- **Error tests**: Invalid HMAC → 401, malformed event → DLQ, agent down → stop pipeline, service unavailable → retry
- **Performance tests**: 1000 alerts/sec for 5min, verify consumer lag, verify GCP upload
- **Load tests**: 30-minute sustained load at 1000 alerts/sec

### Deployment Requirements

- **Kafka setup**: 3 brokers, 3 partitions, replication factor 3
- **GCP Bucket**: Created and configured with appropriate permissions
- **Documentation**: Ops guide updated with Kafka management, DLQ reprocessing, webhook secret rotation, GCP Bucket management

## Risks

### Security Risks

- **Per-tenant webhook secret distribution** → handled via k8s `Secret`s; document the rotation procedure
- **Replay attacks** on webhooks → max-age on signed timestamp (5 min)
- **HMAC secret compromise** → immediate rotation procedure documented; revoke old secret after 24h

### Operational Risks

- **Kafka consumer offset management** → commit only after successful processing; otherwise reprocess on restart
- **Kafka broker failure** → Consumer pauses; alerts buffered in Kafka; mitigated by 3-broker cluster with replication factor 3
- **GCP Bucket unavailability** → Retry 3 times with 30s delay; mitigated by GCP's high availability
- **Job manager failure** → Job status lost; mitigated by Redis persistence for job metadata

### Performance Risks

- **Alert volume exceeds capacity** → Consumer lag grows; mitigated by horizontal scaling of consumers
- **LLM inference bottleneck** → Triage latency increases; mitigated by horizontal scaling of vLLM
- **Tool call latency** → External API slowdown affects triage; mitigated by caching and parallelization
- **Network bandwidth saturation** → 1Gbps required; mitigated by dedicated network and payload compression
- **Kafka consumer throughput** → 1000 msg/sec required; mitigated by increasing partitions and scaling consumers

### Data Risks

- **Schema evolution** → New SIEM fields added, old fields removed; mitigated by permissive `Alert` schema (`extra="allow"`)
- **Normalization errors** → SIEM-specific mapper fails; mitigated by DLQ with error classification
- **DLQ overflow** → High error rate fills DLQ; mitigated by 7-day retention and automatic reprocessing
- **GCP upload failures** → Retry 3 times with 30s delay; mitigated by GCP's retry logic

### Capacity Risks

- **Kafka disk space** → 7-day retention at 1000 alerts/sec = 600M messages; mitigated by adequate disk provisioning and monitoring
- **GCP Bucket storage** → 30-day retention at 1000 alerts/sec; mitigated by lifecycle policies and monitoring
- **Pod resource limits** → CPU/memory exhaustion under load; mitigated by 2-core/4GB per pod and horizontal pod autoscaling

### Integration Risks

- **SIEM API changes** → Field mappings break; mitigated by versioned mappers and comprehensive tests
- **Webhook endpoint discovery** → SIEM can't find endpoint; mitigated by documented URL and DNS configuration
- **Kafka topic configuration** → Wrong topic or partition count; mitigated by infrastructure-as-code and pre-deployment validation
- **GCP authentication** → Service account key expires; mitigated by key rotation procedures

### Monitoring Risks

- **Metric gaps** → Critical issues not detected; mitigated by comprehensive OpenTelemetry instrumentation
- **Alert fatigue** → Too many false positives; mitigated by tuned thresholds and alert grouping
- **Dashboard lag** → GCP Cloud Monitoring latency; mitigated by real-time metrics and log streaming

## Open questions / unknowns at planning time

### Resolved

- **Which SIEM platform is the first integration target** → Splunk (primary example), with Sentinel and CrowdStrike mappers as needed
- **DLQ retention policy and re-processing** → 7-day retention in Kafka; automatic reprocessing (max 3 retries)
- **Alert volume expectations** → 1000 alerts/sec peak, 200 alerts/sec average (industry standard for enterprise SOC)
- **Monitoring stack** → OpenTelemetry + GCP Cloud Monitoring
- **Output destination** → GCP Bucket (JSONL format)
- **Batch API behavior** → Asynchronous (returns job ID immediately)
- **Retry policy** → 3 retries with 30s delay for service unavailability
- **Architecture** → Simplified: Webhook/Batch API → Kafka → Pipeline → GCP Bucket

### Remaining Unknowns

- **SIEM-specific field variations** → Actual Splunk/Sentinel/CrowdStrike schemas may differ from examples; will be discovered during integration testing
- **Kafka topic naming** → Topic name and partition count depend on customer infrastructure; will be configured per deployment
- **Webhook endpoint URL** → Depends on customer DNS and load balancer configuration; will be documented in deployment guide
- **Secret rotation cadence** → Per-tenant webhook secret rotation frequency depends on customer security policy; will be documented as procedure
- **GCP Bucket naming** → Bucket name and location depend on customer GCP project; will be configured per deployment

### Deferred to v2

- **Automated DLQ re-processing UI** → Manual reprocessing via Kafka consumer sufficient for v1
- **Alert deduplication beyond simple idempotency** → Complex deduplication (correlation, merging) deferred to v2
- **SIEM-side rule authoring** → Out of scope for this plan; handled by customer SIEM team
- **Batch API synchronous processing** → Asynchronous processing (job ID) is sufficient for v1
