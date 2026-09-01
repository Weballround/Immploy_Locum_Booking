from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from rest_framework.test import APIClient

from bookings.admin import CandidateAdmin, ClientAdmin
from bookings.management.commands.sync_legacy_mysql import Command
from bookings.models import (
    Candidate,
    Client,
    Department,
    LegacyUserProfile,
    Profession,
    Shift,
    Site,
)


def _desk_user(username, desk_id):
    user = get_user_model().objects.create_user(username=username, is_staff=True)
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=90_000 + desk_id,
        assigned_desk=desk_id,
        link_conf=True,
        edit_cand=True,
    )
    return user


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_legacy_sync_imports_recent_candidate_and_client_department_memberships():
    dataset = {
        "departments": [
            {"legacy_id": 3, "name": "Nursing"},
            {"legacy_id": 9, "name": "Radiology"},
        ],
        "roles": [{"legacy_id": 101, "name": "Scoped Role"}],
        "clients": [{
            "legacy_id": 201,
            "name": "Scoped Client",
            "region": "Gauteng",
            "city": "Sandton",
        }],
        "client_departments": [
            {"client_id": 201, "department_id": 3},
            {"client_id": 201, "department_id": 9},
        ],
        "client_rates": [{
            "legacy_id": 301,
            "client_id": 201,
            "role_id": 101,
            "pay_rate": Decimal("200.00"),
            "bill_rate": Decimal("400.00"),
        }],
        "candidates": [{
            "legacy_id": 401,
            "first_name": "Scoped",
            "last_name": "Candidate",
            "home_area": "Sandton",
            "home_region": "Gauteng",
            "compliance_code": 216,
        }],
        "candidate_departments": [
            {"candidate_id": 401, "department_id": 3},
        ],
        "candidate_roles": [{"candidate_id": 401, "role_id": 101}],
        "experiences": [],
    }

    Command().sync_dataset(dataset)

    candidate = Candidate.objects.get(legacy_mysql_id=401)
    client = Client.objects.get(legacy_mysql_id=201)
    assert set(candidate.departments.values_list("legacy_mysql_id", flat=True)) == {3}
    assert set(client.departments.values_list("legacy_mysql_id", flat=True)) == {3, 9}


@pytest.mark.django_db
def test_legacy_membership_queries_match_their_candidate_and_client_windows():
    candidate_sql = Command._candidate_departments_sql()
    assert "timesheet.cand_no AS candidate_id" in candidate_sql
    assert "timesheet.date_from >= '2025-08-01'" in candidate_sql
    assert "timesheet.date_from <= CURRENT_DATE" in candidate_sql
    assert "timesheet.desk IN (1, 2, 3, 5, 9)" in candidate_sql

    client_sql = Command._client_departments_sql()
    assert "timesheet.client_no AS client_id" in client_sql
    assert "timesheet.date_from >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)" in client_sql
    assert "timesheet.date_from <= CURRENT_DATE" in client_sql
    assert "timesheet.desk IN (1, 2, 3, 5, 9)" in client_sql


@pytest.mark.django_db
def test_desk_user_only_sees_candidates_clients_and_shifts_for_assigned_desk():
    nursing = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    radiology = Department.objects.create(legacy_mysql_id=9, name="Radiology")
    role = Profession.objects.create(name="Department Scope Role")

    own_candidate = Candidate.objects.create(
        first_name="Own",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    own_candidate.professions.add(role)
    own_candidate.departments.add(nursing)
    other_candidate = Candidate.objects.create(
        first_name="Other",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    other_candidate.professions.add(role)
    other_candidate.departments.add(radiology)

    own_client = Client.objects.create(name="Own Client")
    own_client.departments.add(nursing)
    other_client = Client.objects.create(name="Other Client")
    other_client.departments.add(radiology)
    own_site = Site.objects.create(client=own_client, name="Own Facility")
    other_site = Site.objects.create(client=other_client, name="Other Facility")
    own_shift = Shift.objects.create(
        site=own_site,
        profession=role,
        starts_at="2026-09-01T08:00:00+02:00",
        ends_at="2026-09-01T16:00:00+02:00",
        pay_rate="200.00",
        bill_rate="400.00",
    )
    other_shift = Shift.objects.create(
        site=other_site,
        profession=role,
        starts_at="2026-09-02T08:00:00+02:00",
        ends_at="2026-09-02T16:00:00+02:00",
        pay_rate="200.00",
        bill_rate="400.00",
    )

    client = _api_for(_desk_user("nursing.user", 3))

    assert [row["id"] for row in client.get("/api/candidates/").json()] == [own_candidate.id]
    options = client.get("/api/vacancies/creation-options/").json()
    assert [site["id"] for site in options["sites"]] == [own_site.id]
    assert [row["id"] for row in client.get("/api/shifts/").json()] == [own_shift.id]
    assert client.get(f"/api/shifts/{other_shift.id}/").status_code == 404
    assert client.post(
        "/api/bookings/",
        {
            "shift": own_shift.id,
            "candidate": other_candidate.id,
            "status": "confirmed",
        },
        format="json",
    ).status_code == 403
    assert client.post(
        "/api/bookings/",
        {
            "shift": other_shift.id,
            "candidate": own_candidate.id,
            "status": "confirmed",
        },
        format="json",
    ).status_code == 403


@pytest.mark.django_db
def test_django_admin_user_sees_all_departments_but_desk_admin_is_scoped():
    nursing = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    radiology = Department.objects.create(legacy_mysql_id=9, name="Radiology")
    nursing_candidate = Candidate.objects.create(first_name="Nursing", last_name="Candidate")
    nursing_candidate.departments.add(nursing)
    radiology_candidate = Candidate.objects.create(first_name="Radiology", last_name="Candidate")
    radiology_candidate.departments.add(radiology)
    nursing_client = Client.objects.create(name="Nursing Client")
    nursing_client.departments.add(nursing)
    radiology_client = Client.objects.create(name="Radiology Client")
    radiology_client.departments.add(radiology)

    django_admin = get_user_model().objects.create_superuser(
        username="system.admin",
        email="admin@example.test",
        password=None,
    )
    desk_admin = _desk_user("desk.admin", 3)
    factory = RequestFactory()

    admin_request = factory.get("/admin/")
    admin_request.user = django_admin
    desk_request = factory.get("/admin/")
    desk_request.user = desk_admin

    candidate_admin = CandidateAdmin(Candidate, admin.site)
    client_admin = ClientAdmin(Client, admin.site)
    assert set(candidate_admin.get_queryset(admin_request)) == {
        nursing_candidate,
        radiology_candidate,
    }
    assert set(client_admin.get_queryset(admin_request)) == {
        nursing_client,
        radiology_client,
    }
    assert list(candidate_admin.get_queryset(desk_request)) == [nursing_candidate]
    assert list(client_admin.get_queryset(desk_request)) == [nursing_client]


@pytest.mark.django_db
def test_locally_permissioned_admin_without_legacy_profile_sees_all_departments():
    user = get_user_model().objects.create_user(username="local.admin", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    nursing = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    radiology = Department.objects.create(legacy_mysql_id=9, name="Radiology")
    first = Candidate.objects.create(first_name="First", last_name="Candidate")
    first.departments.add(nursing)
    second = Candidate.objects.create(first_name="Second", last_name="Candidate")
    second.departments.add(radiology)

    response = _api_for(user).get("/api/candidates/")

    assert {row["id"] for row in response.json()} == {first.id, second.id}
