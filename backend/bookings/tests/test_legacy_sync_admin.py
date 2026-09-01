from contextlib import contextmanager

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import CommandError
from django.test import Client as DjangoClient
from django.test import override_settings

from bookings.management.commands.sync_legacy_mysql import Command
from bookings import legacy_sync
from bookings.models import LegacySyncRun


@pytest.mark.django_db
def test_legacy_sync_run_is_audited_and_has_a_narrow_permission():
    sync_run_model = next(
        (
            model
            for model in apps.get_models()
            if model._meta.label_lower == "bookings.legacysyncrun"
        ),
        None,
    )

    assert sync_run_model is not None
    sync_run = sync_run_model.objects.create(dry_run=True)
    assert sync_run.status == "pending"
    assert sync_run.source_counts == {}
    assert sync_run.imported_counts == {}
    assert (
        "run_legacy_sync",
        "Can run the read-only legacy synchronisation",
    ) in sync_run_model._meta.permissions


@pytest.mark.django_db
def test_legacy_sync_admin_requires_narrow_permission_and_get_only_confirms():
    user = get_user_model().objects.create_user(
        username="sync-operator",
        password="local-test-password",
        is_staff=True,
    )
    client = DjangoClient()
    client.force_login(user)

    denied = client.get("/admin/bookings/legacysyncrun/run/")

    assert denied.status_code == 403
    assert LegacySyncRun.objects.count() == 0

    user.user_permissions.add(Permission.objects.get(codename="run_legacy_sync"))
    change_list = client.get("/admin/bookings/legacysyncrun/")
    confirmation = client.get("/admin/bookings/legacysyncrun/run/")

    assert change_list.status_code == 200
    assert b"Run legacy synchronisation" in change_list.content
    assert confirmation.status_code == 200
    assert b"Read-only legacy synchronisation" in confirmation.content
    assert b"Booking records are not synchronized in either direction" in confirmation.content
    assert b"Dry run" in confirmation.content
    assert b"Synchronise now" in confirmation.content
    assert LegacySyncRun.objects.count() == 0


@pytest.mark.django_db
@override_settings(LEGACY_MYSQL_CONFIG="/protected/legacy-read-only.json")
def test_legacy_sync_admin_dry_run_counts_without_writing(monkeypatch):
    user = get_user_model().objects.create_user(
        username="sync-dry-run-operator",
        password="local-test-password",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="run_legacy_sync"))
    client = DjangoClient()
    client.force_login(user)
    dataset = {
        "roles": [{"legacy_id": 1}],
        "clients": [{"legacy_id": 2}],
        "client_rates": [],
        "candidates": [{"legacy_id": 3}],
        "candidate_roles": [],
        "experiences": [],
    }
    monkeypatch.setattr(Command, "read_dataset", lambda self, path: dataset)

    def unexpected_write(self, source_dataset):
        raise AssertionError("A dry run must not write imported records")

    monkeypatch.setattr(Command, "sync_dataset", unexpected_write)

    response = client.post(
        "/admin/bookings/legacysyncrun/run/",
        {"action": "dry_run"},
    )

    assert response.status_code == 302
    sync_run = LegacySyncRun.objects.get()
    assert sync_run.started_by == user
    assert sync_run.dry_run is True
    assert sync_run.status == LegacySyncRun.Status.SUCCEEDED
    assert sync_run.source_counts == {
        "roles": 1,
        "clients": 1,
        "client_rates": 0,
        "candidates": 1,
        "candidate_roles": 0,
        "experiences": 0,
    }
    assert sync_run.imported_counts == {}
    assert sync_run.started_at is not None
    assert sync_run.finished_at is not None


@pytest.mark.django_db
@override_settings(LEGACY_MYSQL_CONFIG="/protected/legacy-read-only.json")
def test_legacy_sync_admin_syncs_once_and_records_imported_counts(monkeypatch):
    user = get_user_model().objects.create_user(
        username="sync-write-operator",
        password="local-test-password",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="run_legacy_sync"))
    client = DjangoClient()
    client.force_login(user)
    dataset = {
        "roles": [],
        "clients": [],
        "client_rates": [],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    }
    monkeypatch.setattr(Command, "read_dataset", lambda self, path: dataset)
    imported_datasets = []

    def sync_once(self, source_dataset):
        imported_datasets.append(source_dataset)
        return {"clients": 12, "candidates": 7}

    monkeypatch.setattr(Command, "sync_dataset", sync_once)

    response = client.post(
        "/admin/bookings/legacysyncrun/run/",
        {"action": "sync"},
    )

    assert response.status_code == 302
    assert imported_datasets == [dataset]
    sync_run = LegacySyncRun.objects.get()
    assert sync_run.dry_run is False
    assert sync_run.status == LegacySyncRun.Status.SUCCEEDED
    assert sync_run.imported_counts == {"clients": 12, "candidates": 7}


@pytest.mark.django_db
def test_legacy_sync_blocks_a_second_overlapping_run(monkeypatch):
    sync_run = LegacySyncRun.objects.create(dry_run=True)

    @contextmanager
    def already_locked():
        raise legacy_sync.LegacySyncAlreadyRunning
        yield

    monkeypatch.setattr(legacy_sync, "exclusive_legacy_sync", already_locked)
    monkeypatch.setattr(
        Command,
        "read_dataset",
        lambda self, path: pytest.fail("A blocked run must not read source data"),
    )

    legacy_sync.execute_legacy_sync(sync_run, "/protected/config.json")

    sync_run.refresh_from_db()
    assert sync_run.status == LegacySyncRun.Status.BLOCKED
    assert sync_run.error_message == (
        "Another legacy synchronisation is already running."
    )
    assert sync_run.finished_at is not None


@pytest.mark.django_db
def test_legacy_sync_records_safe_command_failure(monkeypatch):
    sync_run = LegacySyncRun.objects.create(dry_run=True)

    def unavailable_source(self, path):
        raise CommandError("Unable to read the protected MySQL profile.")

    monkeypatch.setattr(Command, "read_dataset", unavailable_source)

    legacy_sync.execute_legacy_sync(sync_run, "/protected/config.json")

    sync_run.refresh_from_db()
    assert sync_run.status == LegacySyncRun.Status.FAILED
    assert sync_run.error_message == "Unable to read the protected MySQL profile."
    assert "/protected/config.json" not in sync_run.error_message
    assert sync_run.finished_at is not None
