# Data Pipeline

## Ingestion Architecture

### Pipeline Stages
```
External API -> OAuth2 Client -> Extractor -> Transform -> Persistence -> PostgreSQL
                                    |
                                    v
                              Celery Worker (async)
```

### Stage 1: OAuth2 Client
- Handles authentication with external API
- Token refresh and management
- Rate limit awareness
- Retry logic with exponential backoff

**Reusable Insight:** External API clients should be resilient. Handle token expiration, rate limits, and network errors gracefully.

### Stage 2: Extractor
- Orchestrates resource pulls
- Manages pagination
- Handles partial failures
- Logs extraction metrics

**Reusable Insight:** Extraction should be idempotent. Running it twice should produce the same result as running it once.

### Stage 3: Transform
- Converts external API format to normalized schema
- Validates data integrity
- Handles missing or malformed data
- Enriches data with tenant context

**Reusable Insight:** Transformation is where data quality is enforced. Validate early, fail fast, log everything.

### Stage 4: Persistence
- UPSERT pattern (INSERT ... ON CONFLICT)
- Batch operations for performance
- Transaction boundaries for consistency
- Audit trail via run logs

**Reusable Insight:** UPSERT is the key to idempotent data loading. If the same data arrives twice, the second load is a no-op.

## Celery Task Design

### Task Categories
- **Scheduled tasks:** Run on a schedule (every 6 hours)
- **Manual tasks:** Triggered by user action
- **Retry tasks:** Failed tasks with retry logic

### Celery Beat Schedule
```python
beat_schedule = {
    'tenant-refresh': {
        'task': 'refresh_all_tenants',
        'schedule': crontab(minute=0, hour='*/6'),
    }
}
```

**Reusable Insight:** Use Celery Beat for cron-like scheduling. It's more reliable than system cron for distributed systems.

### Retry Strategy
- Exponential backoff with jitter
- Maximum retry count
- Dead letter queue for permanent failures
- Alerting on repeated failures

**Reusable Insight:** Every external call should have a retry policy. Network failures are inevitable; your pipeline should handle them.

## Data Quality

### Validation Rules
- Required fields must be present
- Data types must match schema
- Referential integrity (foreign keys)
- Business rule validation

### Error Handling
- Invalid rows are logged, not silently dropped
- Partial failures are reported
- Run logs track success/failure per resource
- Alerts on data quality issues

**Reusable Insight:** Data quality is not optional. Log every validation failure. Make it easy to diagnose and fix data issues.

## Idempotency

### UPSERT Pattern
```sql
INSERT INTO visits (...)
VALUES (...)
ON CONFLICT (tenant_id, visit_id)
DO UPDATE SET ...
```

### Idempotency Keys
- External API IDs as natural keys
- Composite keys for uniqueness
- Hash-based keys for complex data

**Reusable Insight:** Idempotency is the foundation of reliable data pipelines. Design every operation to be safe to retry.

## Monitoring

### Metrics
- Rows ingested per run
- Duration per resource
- Error rates
- Queue depth

### Logging
- Structured JSON logs
- Correlation IDs per run
- Resource-level detail
- Error context

**Reusable Insight:** Monitor what matters: ingestion lag, error rates, and data freshness. These are the metrics that indicate pipeline health.

## Schema Management

### SQL-Based Schema
- Explicit schema definition (dashboard_schema.sql)
- Versioned migrations (Alembic)
- Backward-compatible changes
- Rollback capability

**Reusable Insight:** Schema changes should be backward-compatible. Add columns, don't remove them. Use default values for new columns.
