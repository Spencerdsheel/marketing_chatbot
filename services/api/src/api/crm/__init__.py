"""Outbound CRM sync module -- CSV export lives in api.leads; this package
carries the per-tenant CRM config, the CRMSync Protocol + webhook impl, the
config route, and the idempotent/retryable crm.sync_lead Celery task.
"""
