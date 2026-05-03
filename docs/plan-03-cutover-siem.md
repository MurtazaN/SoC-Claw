# Plan 03 — Cutover: SIEM Alert Ingress

**Parent:** [production_data_architecture.md](production_data_architecture.md), step 4 (per-source cutover)
**Status:** Draft — step list to flesh out at implementation time once the target SIEM is chosen.

## Goal

Replace the static [data/advanced_siem_dataset.jsonl](../data/advanced_siem_dataset.jsonl) reader with real-time alert ingress from production SIEM platforms (Splunk, Sentinel, Elastic, CrowdStrike).

## Scope

- **In:** Kafka consumer adapter, FastAPI webhook endpoint, internal AlertQueue, schema normalization, dead-letter queue (DLQ).
- **Out:** SIEM-side rule authoring; alert deduplication strategy beyond simple idempotency (deferred to v2).

## Pinned decisions

| Decision | Choice | Rationale |
| :--- | :--- | :--- |
| Primary ingress | Kafka topic consumer | Most production SIEMs publish to Kafka or can be configured to |
| Bridge ingress | FastAPI webhook | Adapter for SIEMs that cannot publish to Kafka |
| AlertQueue | Redis stream | Lightest fanout for single-pipeline consumer; Redis is already in stack |
| Schema | Normalize to existing `Alert` pydantic schema | Keeps downstream call sites unchanged |
| Webhook auth | HMAC-SHA256 over body, per-tenant secret | Industry-standard webhook signing |
| Bad events | Push to DLQ stream, log, alert; pipeline continues | Don't block live pipeline on malformed events |
| Idempotency | Hash of `(source, alert_id, timestamp)` checked against a recent-events set | Prevents re-processing on webhook retries / Kafka rebalance |
| Backpressure | Kafka consumer pauses when AlertQueue depth exceeds threshold | Drop nothing; slow producers instead |

## Steps (skeleton — flesh out at implementation)

1. Confirm `Alert` pydantic schema matches `advanced_siem_dataset.jsonl` shape; record any normalization the adapter must do.
2. Build Kafka consumer in `soc_claw/connectors/siem_kafka.py` — consumer group, offset commit *after* AlertQueue write.
3. Build webhook endpoint in `soc_claw/backend/routes/siem_webhook.py` with HMAC verification + max-age timestamp check.
4. AlertQueue helpers (Redis stream `XADD` / `XREADGROUP`).
5. Update pipeline trigger to consume from AlertQueue (replaces the JSONL load).
6. DLQ stream + a brief ops note in monitoring docs.
7. Tests: HMAC roundtrip, schema normalization, malformed event → DLQ, idempotency on duplicate `(source, alert_id)`.

## Acceptance criteria

- E2E: Kafka publish → AlertQueue → triage agent runs.
- E2E: webhook POST with valid HMAC → AlertQueue → triage runs.
- Invalid HMAC → `401`, no queue write.
- Malformed event → DLQ; pipeline keeps running.
- Replay of identical event → ignored on second arrival.
- `data/advanced_siem_dataset.jsonl` retained as a test fixture; no longer loaded at runtime.

## Risks

- **Per-tenant webhook secret distribution** → handled via k8s `Secret`s; document the rotation procedure.
- **Replay attacks** on webhooks → max-age on signed timestamp + idempotency check.
- **Kafka consumer offset management** → commit only after the AlertQueue write succeeds; otherwise reprocess on restart.
- **Backpressure** → bounded AlertQueue with consumer-side pause, never drop.

## Open questions / unknowns at planning time

- Which SIEM platform is the first integration target. Each speaks slightly different JSON; pick the priority customer's SIEM and write its mapper first.
- DLQ retention policy and re-processing UI — defer to v2 unless launch requires it.
