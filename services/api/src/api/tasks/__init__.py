"""Celery task package for the chatbot API.

This package exposes the shared ``celery_app`` instance (``api.tasks.celery_app``)
and all registered task modules. The API process imports tasks here to ``.delay()``
them; the worker process runs ``celery -A api.tasks.celery_app worker``.

No worker is started in-process — the API only enqueues.
"""
