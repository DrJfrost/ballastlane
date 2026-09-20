"""Celery application."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from taskflow.infrastructure.config.settings import Settings, get_settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    settings = settings or get_settings()

    app = Celery(
        "taskflow",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["taskflow.infrastructure.tasks.jobs"],
    )

    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        # JSON only. The default used to include pickle, which deserialises
        # arbitrary objects -- a broker an attacker can write to then becomes
        # remote code execution on every worker.
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Ack *after* the job finishes, so a worker killed mid-task has its
        # message redelivered instead of silently dropped.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        # Bounded prefetch: with the default of 4 a slow job blocks three
        # others that are already reserved to that worker.
        worker_prefetch_multiplier=1,
        task_time_limit=300,
        task_soft_time_limit=270,
        task_default_retry_delay=10,
        task_track_started=True,
        result_expires=3600,
        broker_connection_retry_on_startup=True,
        # Set in tests so ``.delay()`` runs inline and assertions stay simple.
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=settings.celery_task_always_eager,
        beat_schedule={
            "scan-overdue-tasks-daily": {
                "task": "taskflow.scan_overdue_tasks",
                "schedule": crontab(hour=settings.overdue_scan_cron_hour, minute=0),
            },
        },
    )
    return app


celery_app = create_celery_app()
