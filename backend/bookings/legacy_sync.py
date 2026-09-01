import logging
import threading
from contextlib import contextmanager

from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from bookings.management.commands.sync_legacy_mysql import Command
from bookings.models import LegacySyncRun


logger = logging.getLogger(__name__)
LEGACY_SYNC_LOCK_NAME = "immploy-read-only-legacy-reference-sync"
_fallback_lock = threading.Lock()


class LegacySyncAlreadyRunning(Exception):
    pass


@contextmanager
def exclusive_legacy_sync():
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s))",
                [LEGACY_SYNC_LOCK_NAME],
            )
            acquired = cursor.fetchone()[0]
        if not acquired:
            raise LegacySyncAlreadyRunning
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))",
                    [LEGACY_SYNC_LOCK_NAME],
                )
        return

    acquired = _fallback_lock.acquire(blocking=False)
    if not acquired:
        raise LegacySyncAlreadyRunning
    try:
        yield
    finally:
        _fallback_lock.release()


def execute_legacy_sync(sync_run, config_path):
    sync_run.status = LegacySyncRun.Status.RUNNING
    sync_run.started_at = timezone.now()
    sync_run.error_message = ""
    sync_run.save(update_fields=["status", "started_at", "error_message"])

    try:
        with exclusive_legacy_sync():
            command = Command()
            dataset = command.read_dataset(config_path)
            sync_run.source_counts = {
                name: len(rows) for name, rows in dataset.items()
            }
            if not sync_run.dry_run:
                sync_run.imported_counts = command.sync_dataset(dataset)
    except LegacySyncAlreadyRunning:
        sync_run.status = LegacySyncRun.Status.BLOCKED
        sync_run.error_message = "Another legacy synchronisation is already running."
    except CommandError as exc:
        sync_run.status = LegacySyncRun.Status.FAILED
        sync_run.error_message = str(exc)
    except Exception:
        logger.exception("Unexpected legacy synchronisation failure")
        sync_run.status = LegacySyncRun.Status.FAILED
        sync_run.error_message = "Unexpected synchronisation failure. Check server logs."
    else:
        sync_run.status = LegacySyncRun.Status.SUCCEEDED
    finally:
        sync_run.finished_at = timezone.now()
        sync_run.save(
            update_fields=[
                "status",
                "source_counts",
                "imported_counts",
                "error_message",
                "finished_at",
            ]
        )

    return sync_run
