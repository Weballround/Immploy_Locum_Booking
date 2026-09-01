from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import (
    Booking,
    Candidate,
    CandidateChangeAudit,
    Client,
    ClientProfessionRate,
    Department,
    FacilityExperience,
    LegacyUserProfile,
    Profession,
    Shift,
    Site,
    SiteProfessionRate,
    Vacancy,
)


@pytest.fixture
def api_client(db):
    user = get_user_model().objects.create_user(username="consultant", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(codename__in=[
        "manage_bookings",
        "view_candidate_pay_rates",
        "view_client_charge_rates",
        "override_approved_rates",
    ]))
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_anonymous_users_cannot_read_shift_data():
    response = APIClient().get("/api/shifts/")

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_non_staff_users_cannot_read_booking_data():
    user = get_user_model().objects.create_user(username="locum")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/shifts/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_direct_shift_creation_ignores_submitted_bill_rate(api_client):
    profession = Profession.objects.create(name="Direct Shift Nurse")
    client = Client.objects.create(name="Direct Shift Hospital")
    site = Site.objects.create(client=client, name="Direct Shift Ward")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="220.00",
        bill_rate="410.00",
    )

    response = api_client.post(
        "/api/shifts/",
        {
            "site": site.id,
            "profession": profession.id,
            "starts_at": "2026-09-12T06:00:00+02:00",
            "ends_at": "2026-09-12T18:00:00+02:00",
            "pay_rate": "225.00",
            "bill_rate": "9999.99",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["bill_rate"] == "410.00"
    assert Shift.objects.get(pk=response.json()["id"]).bill_rate == Decimal("410.00")


@pytest.mark.django_db
def test_shift_calendar_query_is_scoped_by_site_and_month_overlap(api_client):
    profession = Profession.objects.create(name="Calendar Nurse")
    first_client = Client.objects.create(name="Duplicate Hospital")
    second_client = Client.objects.create(name="Duplicate Hospital")
    first_site = Site.objects.create(client=first_client, name="Main Ward")
    second_site = Site.objects.create(client=second_client, name="Main Ward")
    starts_at = timezone.make_aware(datetime(2026, 8, 31, 23, 30))
    ends_at = timezone.make_aware(datetime(2026, 9, 1, 7, 30))
    included = Shift.objects.create(
        site=first_site,
        profession=profession,
        starts_at=starts_at,
        ends_at=ends_at,
        pay_rate="200.00",
        bill_rate="400.00",
    )
    Shift.objects.create(
        site=second_site,
        profession=profession,
        starts_at=starts_at,
        ends_at=ends_at,
        pay_rate="200.00",
        bill_rate="400.00",
    )

    response = api_client.get(
        "/api/shifts/",
        {
            "site": first_site.id,
            "starts_before": "2026-10-01T00:00:00+02:00",
            "ends_after": "2026-09-01T00:00:00+02:00",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [included.id]
    assert response.json()[0]["site_id"] == first_site.id
    assert response.json()[0]["profession_id"] == profession.id


@pytest.mark.django_db
def test_site_role_options_only_returns_linked_roles_with_rates(api_client):
    client = Client.objects.create(name="Linked Roles Hospital")
    site = Site.objects.create(client=client, name="Main facility")
    linked = Profession.objects.create(name="Linked Nurse")
    overridden = Profession.objects.create(name="Override Nurse")
    Profession.objects.create(name="Unlinked Nurse")
    ClientProfessionRate.objects.create(
        client=client,
        profession=linked,
        legacy_mysql_id=101,
        pay_rate="245.50",
        bill_rate="455.75",
    )
    ClientProfessionRate.objects.create(
        client=client,
        profession=overridden,
        legacy_mysql_id=102,
        pay_rate="200.00",
        bill_rate="400.00",
    )
    SiteProfessionRate.objects.create(
        site=site,
        profession=overridden,
        pay_rate="275.00",
        bill_rate="510.00",
    )

    with CaptureQueriesContext(connection) as queries:
        response = api_client.get(
            "/api/vacancies/site-role-options/",
            {"site": site.id},
        )

    assert response.status_code == 200
    assert response.json() == {
        "professions": [
            {
                "id": linked.id,
                "name": "Linked Nurse",
                "pay_rate": "245.50",
                "bill_rate": "455.75",
            },
            {
                "id": overridden.id,
                "name": "Override Nurse",
                "pay_rate": "275.00",
                "bill_rate": "510.00",
            },
        ]
    }
    # The endpoint uses three data queries plus staff/profile permission checks.
    assert len(queries) <= 6


@pytest.mark.django_db
def test_site_role_options_handles_empty_and_invalid_facilities(api_client):
    client = Client.objects.create(name="Facility Without Role Links")
    site = Site.objects.create(client=client, name="Main facility")
    inactive_client = Client.objects.create(
        name="Inactive Facility",
        legacy_mysql_id=993,
        is_active=False,
    )
    inactive_site = Site.objects.create(client=inactive_client, name="Old facility")

    empty_response = api_client.get(
        f"/api/vacancies/site-role-options/?site={site.id}"
    )
    invalid_response = api_client.get(
        "/api/vacancies/site-role-options/?site=not-an-id"
    )
    inactive_response = api_client.get(
        f"/api/vacancies/site-role-options/?site={inactive_site.id}"
    )

    assert empty_response.status_code == 200
    assert empty_response.json() == {"professions": []}
    assert invalid_response.status_code == 400
    assert inactive_response.status_code == 404


@pytest.mark.django_db
def test_scheduler_can_add_a_local_candidate_pending_compliance(api_client):
    profession = Profession.objects.create(name="Locum Pharmacist")
    Client.objects.create(
        name="Candidate Location Source",
        city="Sandton",
        region="Gauteng",
    )

    response = api_client.post(
        "/api/candidates/",
        {
            "first_name": "Naledi",
            "last_name": "Mokoena",
            "home_area": "Sandton",
            "home_region": "Gauteng",
            "profession_ids": [profession.id],
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "first_name": "Naledi",
        "last_name": "Mokoena",
        "full_name": "Naledi Mokoena",
        "email": "",
        "phone": "",
        "compliance_status": "pending",
        "home_area": "Sandton",
        "home_region": "Gauteng",
        "postal_code": "",
        "is_active": True,
        "profession_names": ["Locum Pharmacist"],
        "profession_ids": [profession.id],
    }
    candidate = Candidate.objects.get(pk=response.json()["id"])
    assert candidate.legacy_mysql_id is None
    assert candidate.is_active is True
    assert candidate.email == ""
    assert candidate.phone == ""


@pytest.mark.django_db
def test_candidate_creation_options_return_region_scoped_area_dropdowns(api_client):
    Profession.objects.create(name="Dropdown Nurse")
    Candidate.objects.create(
        first_name="Active",
        last_name="Candidate",
        home_area=" Sandton ",
        home_region="Gauteng",
    )
    Candidate.objects.create(
        first_name="Inactive",
        last_name="Candidate",
        home_area="Hidden town",
        home_region="Hidden region",
        is_active=False,
    )
    Client.objects.create(
        name="Cape Facility",
        city="Cape Town",
        region="Western Cape",
    )
    Candidate.objects.create(
        first_name="KwaZulu",
        last_name="Candidate",
        home_area="Durban",
        home_region="Kwazulu Natal",
    )
    Client.objects.create(
        name="KwaZulu Facility",
        city="Pietermaritzburg",
        region="Kwazulu-Natal",
    )
    Client.objects.create(
        name="Inactive Facility",
        city="Hidden city",
        region="Hidden region",
        is_active=False,
    )

    response = api_client.get("/api/candidates/creation-options/")

    assert response.status_code == 200
    assert response.json()["locations"] == [
        {"region": "Gauteng", "areas": ["Sandton"]},
        {
            "region": "KwaZulu-Natal",
            "areas": ["Durban", "Pietermaritzburg"],
        },
        {"region": "Western Cape", "areas": ["Cape Town"]},
    ]


@pytest.mark.django_db
def test_candidate_update_rejects_an_area_from_a_different_region(api_client):
    profession = Profession.objects.create(name="Location Validation Nurse")
    Candidate.objects.create(
        first_name="Gauteng",
        last_name="Location",
        home_area="Sandton",
        home_region="Gauteng",
    )
    Client.objects.create(
        name="Cape Location Facility",
        city="Cape Town",
        region="Western Cape",
    )
    candidate = Candidate.objects.create(
        first_name="Edited",
        last_name="Location",
        home_area="Sandton",
        home_region="Gauteng",
    )
    candidate.professions.add(profession)

    response = api_client.patch(
        f"/api/candidates/{candidate.id}/",
        {"home_area": "Cape Town", "home_region": "Gauteng"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "home_area": ["Select an Area that belongs to the selected Region."]
    }
    candidate.refresh_from_db()
    assert candidate.home_area == "Sandton"


@pytest.mark.django_db
def test_candidate_editor_can_update_booking_profile_and_roles(api_client):
    previous_role = Profession.objects.create(name="Previous Candidate Role")
    updated_role = Profession.objects.create(name="Updated Candidate Role")
    Client.objects.create(
        name="Candidate Profile Location",
        city="New area",
        region="Gauteng",
    )
    candidate = Candidate.objects.create(
        first_name="Before",
        last_name="Profile",
        legacy_mysql_id=91001,
        home_area="Old area",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(previous_role)

    response = api_client.patch(
        f"/api/candidates/{candidate.id}/",
        {
            "first_name": "Updated",
            "last_name": "Candidate",
            "email": "updated@example.test",
            "phone": "+27110000000",
            "home_area": "New area",
            "home_region": "Gauteng",
            "postal_code": "2000",
            "is_active": True,
            "profession_ids": [updated_role.id],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": candidate.id,
        "first_name": "Updated",
        "last_name": "Candidate",
        "full_name": "Updated Candidate",
        "email": "updated@example.test",
        "phone": "+27110000000",
        "home_area": "New area",
        "home_region": "Gauteng",
        "postal_code": "2000",
        "is_active": True,
        "compliance_status": "cleared",
        "profession_names": ["Updated Candidate Role"],
        "profession_ids": [updated_role.id],
    }
    candidate.refresh_from_db()
    assert candidate.profile_locally_managed is True
    assert list(candidate.professions.values_list("id", flat=True)) == [updated_role.id]
    audit = CandidateChangeAudit.objects.get(candidate=candidate)
    assert audit.changed_by.username == "consultant"
    assert audit.changed_fields == [
        "email",
        "first_name",
        "home_area",
        "home_region",
        "last_name",
        "phone",
        "postal_code",
        "profession_ids",
    ]
    assert audit.before == {
        "home_area": "Old area",
        "home_region": "",
        "profession_ids": [previous_role.id],
    }
    assert audit.after == {
        "home_area": "New area",
        "home_region": "Gauteng",
        "profession_ids": [updated_role.id],
    }
    assert "email" not in audit.before
    assert "phone" not in audit.after


@pytest.mark.django_db
def test_candidate_update_rejects_protected_fields_and_empty_active_roles(api_client):
    profession = Profession.objects.create(name="Protected Candidate Role")
    candidate = Candidate.objects.create(
        first_name="Protected",
        last_name="Candidate",
        legacy_mysql_id=91002,
        compliance_status=Candidate.ComplianceStatus.PENDING,
    )
    candidate.professions.add(profession)

    protected_response = api_client.patch(
        f"/api/candidates/{candidate.id}/",
        {
            "compliance_status": Candidate.ComplianceStatus.CLEARED,
            "legacy_mysql_id": 99999,
            "profile_locally_managed": True,
        },
        format="json",
    )
    empty_roles_response = api_client.patch(
        f"/api/candidates/{candidate.id}/",
        {"profession_ids": []},
        format="json",
    )

    assert protected_response.status_code == 400
    assert set(protected_response.json()) == {
        "compliance_status",
        "legacy_mysql_id",
        "profile_locally_managed",
    }
    assert empty_roles_response.status_code == 400
    candidate.refresh_from_db()
    assert candidate.legacy_mysql_id == 91002
    assert candidate.compliance_status == Candidate.ComplianceStatus.PENDING
    assert candidate.profile_locally_managed is False
    assert list(candidate.professions.values_list("id", flat=True)) == [profession.id]
    assert not CandidateChangeAudit.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_confirm_booking_via_api_marks_shift_booked(api_client):
    profession = Profession.objects.create(name="Theatre Nurse")
    client = Client.objects.create(name="Sandton Hospital")
    site = Site.objects.create(client=client, name="Theatre 1")
    candidate = Candidate.objects.create(
        first_name="Thandi",
        last_name="Nkosi",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 6, 8, 0))
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=10),
        pay_rate="220.00",
        bill_rate="420.00",
    )

    response = api_client.post(
        "/api/bookings/",
        {"shift": shift.id, "candidate": candidate.id, "status": "confirmed"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "confirmed"
    shift.refresh_from_db()
    assert shift.status == Shift.Status.BOOKED


@pytest.mark.django_db
def test_bulk_booking_creates_multiple_confirmed_assignments_atomically(api_client):
    profession = Profession.objects.create(name="Bulk Booking Doctor")
    client = Client.objects.create(name="Bulk Booking Hospital")
    site = Site.objects.create(client=client, name="Consulting rooms")
    candidate = Candidate.objects.create(
        first_name="Multi",
        last_name="Doctor",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 9, 8, 8, 0))
    shifts = [
        Shift.objects.create(
            site=site,
            profession=profession,
            starts_at=start + timedelta(days=index),
            ends_at=start + timedelta(days=index, hours=8),
            pay_rate="500.00",
            bill_rate="800.00",
        )
        for index in range(2)
    ]

    response = api_client.post(
        "/api/bookings/bulk/",
        {"assignments": [
            {"shift": shift.id, "candidate": candidate.id, "status": "confirmed"}
            for shift in shifts
        ]},
        format="json",
    )

    assert response.status_code == 201
    assert len(response.json()) == 2
    assert Booking.objects.filter(status=Booking.Status.CONFIRMED).count() == 2
    assert set(Shift.objects.values_list("status", flat=True)) == {Shift.Status.BOOKED}


@pytest.mark.django_db
@pytest.mark.parametrize("raw_payload", ["[]", '"invalid"', "null"])
def test_bulk_booking_rejects_non_object_json_without_side_effects(api_client, raw_payload):
    response = api_client.generic(
        "POST",
        "/api/bookings/bulk/",
        raw_payload,
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not Booking.objects.exists()


@pytest.mark.django_db
def test_bulk_booking_rolls_back_every_assignment_when_one_is_ineligible(api_client):
    doctor = Profession.objects.create(name="Atomic Doctor")
    nurse = Profession.objects.create(name="Atomic Nurse")
    client = Client.objects.create(name="Atomic Hospital")
    site = Site.objects.create(client=client, name="Main facility")
    candidate = Candidate.objects.create(
        first_name="Atomic",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(doctor)
    start = timezone.make_aware(datetime(2026, 9, 10, 8, 0))
    doctor_shift = Shift.objects.create(
        site=site,
        profession=doctor,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="500.00",
        bill_rate="800.00",
    )
    nurse_shift = Shift.objects.create(
        site=site,
        profession=nurse,
        starts_at=start + timedelta(days=1),
        ends_at=start + timedelta(days=1, hours=8),
        pay_rate="300.00",
        bill_rate="500.00",
    )

    response = api_client.post(
        "/api/bookings/bulk/",
        {"assignments": [
            {"shift": doctor_shift.id, "candidate": candidate.id, "status": "confirmed"},
            {"shift": nurse_shift.id, "candidate": candidate.id, "status": "confirmed"},
        ]},
        format="json",
    )

    assert response.status_code == 400
    assert Booking.objects.count() == 0
    assert set(Shift.objects.values_list("status", flat=True)) == {Shift.Status.OPEN}


@pytest.mark.django_db
def test_shift_list_includes_privacy_limited_filled_booking_details(api_client):
    profession = Profession.objects.create(name="Filled Booking Nurse")
    client = Client.objects.create(name="Filled Booking Hospital")
    site = Site.objects.create(client=client, name="Main facility")
    candidate = Candidate.objects.create(
        first_name="Naledi",
        last_name="Mokoena",
        email="private@example.test",
        phone="+27000000000",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.now() + timedelta(days=2)
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="250.00",
        bill_rate="460.00",
    )
    booking = Booking.objects.create(
        shift=shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    response = api_client.get("/api/shifts/")

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["status"] == "booked"
    assert payload["confirmed_booking"] == {
        "id": booking.id,
        "candidate_id": candidate.id,
        "candidate_name": "Naledi Mokoena",
        "status": "confirmed",
    }
    assert "email" not in payload["confirmed_booking"]
    assert "phone" not in payload["confirmed_booking"]


@pytest.mark.django_db
def test_create_vacancy_generates_multiple_open_shifts(api_client):
    profession = Profession.objects.create(name="Emergency Nurse")
    client = Client.objects.create(name="Rapid Fill Hospital")
    site = Site.objects.create(client=client, name="Emergency Unit")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="220.00",
        bill_rate="410.00",
    )

    response = api_client.post(
        "/api/vacancies/",
        {
            "reference": "Weekend cover",
            "site": site.id,
            "profession": profession.id,
            "notes": "Urgent fill",
            "shift_items": [
                {
                    "starts_at": "2026-09-12T06:00:00+02:00",
                    "ends_at": "2026-09-12T18:00:00+02:00",
                    "pay_rate": "225.00",
                    "bill_rate": "425.00",
                },
                {
                    "starts_at": "2026-09-13T06:00:00+02:00",
                    "ends_at": "2026-09-13T18:00:00+02:00",
                    "pay_rate": "225.00",
                    "bill_rate": "425.00",
                },
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["reference"] == "Weekend cover"
    assert len(response.json()["shifts"]) == 2
    assert {shift["bill_rate"] for shift in response.json()["shifts"]} == {"410.00"}
    assert Shift.objects.filter(
        vacancy_id=response.json()["id"],
        status=Shift.Status.OPEN,
    ).count() == 2


@pytest.mark.django_db
def test_create_large_vacancy_uses_bounded_queries(api_client):
    profession = Profession.objects.create(name="Bulk Vacancy Nurse")
    client = Client.objects.create(name="Bulk Vacancy Hospital")
    site = Site.objects.create(client=client, name="Bulk Ward")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="250.00",
        bill_rate="460.00",
    )
    starts_at = datetime.fromisoformat("2027-01-01T06:00:00+02:00")
    shift_items = [
        {
            "starts_at": (starts_at + timedelta(days=index)).isoformat(),
            "ends_at": (starts_at + timedelta(days=index, hours=12)).isoformat(),
            "pay_rate": "250.00",
            "bill_rate": "460.00",
        }
        for index in range(31)
    ]

    with CaptureQueriesContext(connection) as queries:
        response = api_client.post(
            "/api/vacancies/",
            {
                "reference": "Month-long cover",
                "site": site.id,
                "profession": profession.id,
                "shift_items": shift_items,
            },
            format="json",
        )

    assert response.status_code == 201
    assert len(response.json()["shifts"]) == 31
    assert len(queries) <= 40


@pytest.mark.django_db
def test_invalid_vacancy_shift_rolls_back_the_entire_vacancy(api_client):
    profession = Profession.objects.create(name="Rollback Nurse")
    client = Client.objects.create(name="Rollback Hospital")
    site = Site.objects.create(client=client, name="Ward R")

    response = api_client.post(
        "/api/vacancies/",
        {
            "reference": "Invalid cover",
            "site": site.id,
            "profession": profession.id,
            "notes": "Must not partially save",
            "shift_items": [
                {
                    "starts_at": "2026-09-12T06:00:00+02:00",
                    "ends_at": "2026-09-12T18:00:00+02:00",
                    "pay_rate": "225.00",
                    "bill_rate": "425.00",
                },
                {
                    "starts_at": "2026-09-13T18:00:00+02:00",
                    "ends_at": "2026-09-13T06:00:00+02:00",
                    "pay_rate": "225.00",
                    "bill_rate": "425.00",
                },
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    assert not Vacancy.objects.filter(reference="Invalid cover").exists()
    assert not Shift.objects.filter(site=site).exists()


@pytest.mark.django_db
def test_vacancy_override_does_not_change_approved_rate_default(api_client):
    profession = Profession.objects.create(name="Rate Default Nurse")
    client = Client.objects.create(name="Rate Default Hospital")
    site = Site.objects.create(client=client, name="Rate Default Ward")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="230.00",
        bill_rate="430.25",
    )

    create_response = api_client.post(
        "/api/vacancies/",
        {
            "reference": "Rate-learning cover",
            "site": site.id,
            "profession": profession.id,
            "shift_items": [{
                "starts_at": "2026-09-14T06:00:00+02:00",
                "ends_at": "2026-09-14T18:00:00+02:00",
                "pay_rate": "235.50",
                "bill_rate": "9999.99",
            }],
        },
        format="json",
    )
    assert create_response.status_code == 201

    default_response = api_client.get(
        "/api/vacancies/rate-default/",
        {"site": site.id, "profession": profession.id},
    )

    assert default_response.status_code == 200
    assert default_response.json() == {
        "pay_rate": "230.00",
        "bill_rate": "430.25",
    }


@pytest.mark.django_db
def test_rate_default_falls_back_to_latest_existing_shift(api_client):
    profession = Profession.objects.create(name="Fallback Rate Nurse")
    client = Client.objects.create(name="Fallback Rate Hospital")
    site = Site.objects.create(client=client, name="Fallback Ward")
    Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=datetime.fromisoformat("2026-09-14T06:00:00+02:00"),
        ends_at=datetime.fromisoformat("2026-09-14T18:00:00+02:00"),
        pay_rate="245.00",
        bill_rate="455.00",
    )

    response = api_client.get(
        "/api/vacancies/rate-default/",
        {"site": site.id, "profession": profession.id},
    )

    assert response.status_code == 200
    assert response.json() == {"pay_rate": "245.00", "bill_rate": "455.00"}


@pytest.mark.django_db
def test_vacancy_rejects_mixed_rates_across_its_shifts(api_client):
    profession = Profession.objects.create(name="Consistent Rate Nurse")
    client = Client.objects.create(name="Consistent Rate Hospital")
    site = Site.objects.create(client=client, name="Consistent Rate Ward")

    response = api_client.post(
        "/api/vacancies/",
        {
            "reference": "Mixed rates",
            "site": site.id,
            "profession": profession.id,
            "shift_items": [
                {
                    "starts_at": "2026-09-14T06:00:00+02:00",
                    "ends_at": "2026-09-14T18:00:00+02:00",
                    "pay_rate": "235.50",
                    "bill_rate": "445.75",
                },
                {
                    "starts_at": "2026-09-15T06:00:00+02:00",
                    "ends_at": "2026-09-15T18:00:00+02:00",
                    "pay_rate": "240.00",
                    "bill_rate": "450.00",
                },
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    assert not Vacancy.objects.filter(reference="Mixed rates").exists()


@pytest.mark.django_db
def test_vacancy_rolls_back_if_rate_learning_fails(api_client, monkeypatch):
    profession = Profession.objects.create(name="Rate Failure Nurse")
    client = Client.objects.create(name="Rate Failure Hospital")
    site = Site.objects.create(client=client, name="Rate Failure Ward")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="230.00",
        bill_rate="430.00",
    )

    def fail_rate_learning(*args, **kwargs):
        raise RuntimeError("simulated rate persistence failure")

    monkeypatch.setattr(
        SiteProfessionRate.objects,
        "update_or_create",
        fail_rate_learning,
    )

    with pytest.raises(RuntimeError, match="simulated rate persistence failure"):
        api_client.post(
            "/api/vacancies/",
            {
                "reference": "Must fully roll back",
                "site": site.id,
                "profession": profession.id,
                "shift_items": [{
                    "starts_at": "2026-09-14T06:00:00+02:00",
                    "ends_at": "2026-09-14T18:00:00+02:00",
                    "pay_rate": "235.50",
                    "bill_rate": "445.75",
                }],
            },
            format="json",
        )

    assert not Vacancy.objects.filter(reference="Must fully roll back").exists()
    assert not Shift.objects.filter(site=site).exists()


@pytest.mark.django_db
def test_session_authenticated_vacancy_creation_requires_csrf():
    user = get_user_model().objects.create_user(
        username="csrf-consultant",
        password="test-only-password",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    profession = Profession.objects.create(name="CSRF Nurse")
    client = Client.objects.create(name="CSRF Hospital")
    site = Site.objects.create(client=client, name="CSRF Ward")
    client_api = APIClient(enforce_csrf_checks=True)
    assert client_api.login(username=user.username, password="test-only-password")

    response = client_api.post(
        "/api/vacancies/",
        {
            "reference": "Blocked without CSRF",
            "site": site.id,
            "profession": profession.id,
            "shift_items": [{
                "starts_at": "2026-09-14T06:00:00+02:00",
                "ends_at": "2026-09-14T18:00:00+02:00",
                "pay_rate": "235.50",
                "bill_rate": "445.75",
            }],
        },
        format="json",
    )

    assert response.status_code == 403
    assert not Vacancy.objects.filter(reference="Blocked without CSRF").exists()

    book_now = client_api.post(
        "/api/vacancies/book-now/",
        {},
        format="json",
    )

    assert book_now.status_code == 403


@pytest.mark.django_db
def test_candidate_directory_supports_name_search_without_exposing_inactive_people(api_client):
    profession = Profession.objects.create(name="Directory Nurse")
    active = Candidate.objects.create(
        first_name="Nomsa",
        last_name="DirectoryUnique",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    active.professions.add(profession)
    Candidate.objects.create(
        first_name="Inactive",
        last_name="DirectoryUnique",
        is_active=False,
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )

    response = api_client.get(
        "/api/candidates/",
        {"search": "Nomsa DirectoryUnique"},
    )

    assert response.status_code == 200
    assert response.json() == [{
        "id": active.id,
        "first_name": "Nomsa",
        "last_name": "DirectoryUnique",
        "full_name": "Nomsa DirectoryUnique",
        "email": "",
        "phone": "",
        "compliance_status": "cleared",
        "home_area": "",
        "home_region": "",
        "postal_code": "",
        "is_active": True,
        "profession_names": ["Directory Nurse"],
        "profession_ids": [profession.id],
    }]


@pytest.mark.django_db
def test_candidate_directory_profession_filter_excludes_unrelated_candidates(api_client):
    doctor = Profession.objects.create(name="Directory Doctor")
    nurse = Profession.objects.create(name="Directory Nurse Filter")
    matching = Candidate.objects.create(
        first_name="Doctor",
        last_name="Match",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    matching.professions.add(doctor)
    unrelated = Candidate.objects.create(
        first_name="Nurse",
        last_name="Unrelated",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    unrelated.professions.add(nurse)

    response = api_client.get("/api/candidates/", {"profession": doctor.id})

    assert response.status_code == 200
    assert [candidate["id"] for candidate in response.json()] == [matching.id]

    malformed = api_client.get("/api/candidates/?profession=doctor")
    assert malformed.status_code == 400
    assert malformed.json()["profession"] == "Select a valid role."


@pytest.mark.django_db
def test_candidate_compatible_shifts_only_returns_related_open_nonconflicting_work(api_client):
    doctor = Profession.objects.create(name="Compatible Doctor")
    nurse = Profession.objects.create(name="Compatible Nurse")
    client = Client.objects.create(name="Compatible Hospital")
    site = Site.objects.create(client=client, name="Main facility")
    candidate = Candidate.objects.create(
        first_name="Compatible",
        last_name="Doctor",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(doctor)
    start = timezone.make_aware(datetime(2026, 10, 5, 8, 0))
    related = Shift.objects.create(
        site=site,
        profession=doctor,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="500.00",
        bill_rate="800.00",
    )
    Shift.objects.create(
        site=site,
        profession=nurse,
        starts_at=start + timedelta(days=1),
        ends_at=start + timedelta(days=1, hours=8),
        pay_rate="300.00",
        bill_rate="500.00",
    )
    conflicting = Shift.objects.create(
        site=site,
        profession=doctor,
        starts_at=start + timedelta(days=2),
        ends_at=start + timedelta(days=2, hours=8),
        pay_rate="500.00",
        bill_rate="800.00",
    )
    booked_shift = Shift.objects.create(
        site=site,
        profession=doctor,
        starts_at=conflicting.starts_at + timedelta(hours=1),
        ends_at=conflicting.ends_at + timedelta(hours=1),
        pay_rate="500.00",
        bill_rate="800.00",
    )
    Booking.objects.create(
        shift=booked_shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    response = api_client.get(f"/api/candidates/{candidate.id}/compatible-shifts/")

    assert response.status_code == 200
    assert [shift["id"] for shift in response.json()] == [related.id]


@pytest.mark.django_db
def test_candidate_editor_cannot_read_scheduling_candidate_actions(api_client):
    user = get_user_model().objects.create_user(
        username="candidate-editor-only",
        password="test-only-password",
        is_staff=True,
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=701,
        edit_cand=True,
        link_conf=False,
    )
    candidate = Candidate.objects.create(
        first_name="Candidate",
        last_name="Editor Scope",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    api_client.force_authenticate(user)

    response = api_client.get(f"/api/candidates/{candidate.id}/compatible-shifts/")
    facility_response = api_client.get(
        "/api/candidates/?site=1&profession=1"
    )

    assert response.status_code == 403
    assert facility_response.status_code == 403


@pytest.mark.django_db
def test_shift_cannot_disagree_with_its_parent_vacancy():
    profession = Profession.objects.create(name="Vacancy Integrity Nurse")
    client = Client.objects.create(name="Vacancy Integrity Hospital")
    vacancy_site = Site.objects.create(client=client, name="Ward V")
    other_site = Site.objects.create(client=client, name="Ward Other")
    vacancy = Vacancy.objects.create(
        reference="Integrity cover",
        site=vacancy_site,
        profession=profession,
    )
    start = timezone.make_aware(datetime(2026, 9, 12, 6, 0))

    with pytest.raises(ValidationError, match="same facility and role"):
        Shift.objects.create(
            vacancy=vacancy,
            site=other_site,
            profession=profession,
            starts_at=start,
            ends_at=start + timedelta(hours=8),
            pay_rate="225.00",
            bill_rate="425.00",
        )

    valid_shift = Shift.objects.create(
        vacancy=vacancy,
        site=vacancy_site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="225.00",
        bill_rate="425.00",
    )
    with pytest.raises(ValueError, match="Shift scope"):
        Shift.objects.filter(pk=valid_shift.pk).update(site=other_site)
    with pytest.raises(ValidationError, match="same facility and role"):
        Shift.objects.bulk_create([
            Shift(
                vacancy=vacancy,
                site=other_site,
                profession=profession,
                starts_at=start + timedelta(days=1),
                ends_at=start + timedelta(days=1, hours=8),
                pay_rate="225.00",
                bill_rate="425.00",
            )
        ])


@pytest.mark.django_db
def test_shift_bulk_create_accepts_generator_input():
    profession = Profession.objects.create(name="Generator Nurse")
    client = Client.objects.create(name="Generator Hospital")
    site = Site.objects.create(client=client, name="Generator Ward")
    start = timezone.now() + timedelta(days=1)
    shifts = (
        Shift(
            site=site,
            profession=profession,
            starts_at=start,
            ends_at=start + timedelta(hours=8),
            pay_rate="200.00",
            bill_rate="400.00",
        )
        for _ in range(1)
    )

    created = Shift.objects.bulk_create(shifts)

    assert len(created) == 1
    assert Shift.objects.filter(site=site, profession=profession).count() == 1


@pytest.mark.django_db
def test_legacy_link_confirmation_rule_controls_booking_writes():
    user = get_user_model().objects.create_user(
        username="restricted-consultant",
        password="test-only-password",
        is_staff=True,
    )
    department = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    profile = LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=700,
        assigned_desk=3,
        link_conf=False,
    )
    profession = Profession.objects.create(name="Access-controlled Nurse")
    client = Client.objects.create(name="Access-controlled Hospital")
    client.departments.add(department)
    site = Site.objects.create(client=client, name="Ward A")
    candidate = Candidate.objects.create(
        first_name="Eligible",
        last_name="Locum",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    candidate.departments.add(department)
    start = timezone.make_aware(datetime(2026, 9, 5, 8, 0))
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="220.00",
        bill_rate="420.00",
    )
    client_api = APIClient()
    client_api.force_authenticate(user=user)

    denied = client_api.post(
        "/api/bookings/",
        {"shift": shift.id, "candidate": candidate.id, "status": "confirmed"},
        format="json",
    )
    assert denied.status_code == 403
    bulk_denied = client_api.post(
        "/api/bookings/bulk/",
        {"assignments": [
            {"shift": shift.id, "candidate": candidate.id, "status": "confirmed"},
        ]},
        format="json",
    )
    assert bulk_denied.status_code == 403
    assert Booking.objects.count() == 0

    profile.link_conf = True
    profile.save(update_fields=["link_conf"])
    allowed = client_api.post(
        "/api/bookings/",
        {"shift": shift.id, "candidate": candidate.id, "status": "confirmed"},
        format="json",
    )
    assert allowed.status_code == 201


@pytest.mark.django_db
def test_shift_list_includes_booking_board_details(api_client):
    profession = Profession.objects.create(name="Registered Nurse")
    client = Client.objects.create(name="Rosebank Day Hospital")
    site = Site.objects.create(client=client, name="Ward A")
    start = timezone.make_aware(datetime(2026, 8, 7, 7, 30))
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=12),
        pay_rate="210.00",
        bill_rate="400.00",
    )

    response = api_client.get("/api/shifts/")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": shift.id,
            "vacancy": None,
            "site_id": site.id,
            "profession_id": profession.id,
            "client_name": "Rosebank Day Hospital",
            "site_name": "Ward A",
            "profession_name": "Registered Nurse",
            "starts_at": "2026-08-07T07:30:00+02:00",
            "ends_at": "2026-08-07T19:30:00+02:00",
            "pay_rate": "210.00",
            "bill_rate": "400.00",
            "status": "open",
            "notes": "",
            "confirmed_booking": None,
        }
    ]


@pytest.mark.django_db
def test_shift_candidate_list_only_returns_cleared_matching_candidates(api_client):
    nurse = Profession.objects.create(name="Registered Nurse")
    pharmacist = Profession.objects.create(name="Locum Pharmacist")
    client = Client.objects.create(name="Midrand Clinic")
    site = Site.objects.create(client=client, name="Ward B")
    start = timezone.make_aware(datetime(2026, 8, 8, 8, 0))
    shift = Shift.objects.create(
        site=site,
        profession=nurse,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="210.00",
        bill_rate="400.00",
    )
    eligible = Candidate.objects.create(
        first_name="Lerato",
        last_name="Maseko",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    eligible.professions.add(nurse)
    pending = Candidate.objects.create(
        first_name="Sam",
        last_name="Pending",
        compliance_status=Candidate.ComplianceStatus.PENDING,
    )
    pending.professions.add(nurse)
    wrong_profession = Candidate.objects.create(
        first_name="Pat",
        last_name="Pharmacist",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    wrong_profession.professions.add(pharmacist)

    response = api_client.get(f"/api/shifts/{shift.id}/candidates/")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": eligible.id,
            "full_name": "Lerato Maseko",
            "compliance_status": "cleared",
            "role_name": "Registered Nurse",
            "home_area": "",
            "home_region": "",
            "worked_at_facility": False,
            "facility_shift_count": 0,
            "last_worked_on": None,
            "proximity_label": "",
            "eligibility_reasons": [
                "Compliance cleared",
                "Registered Nurse role matched",
            ],
        }
    ]


@pytest.mark.django_db
def test_candidate_matching_ranks_imported_facility_history_and_location(api_client):
    profession = Profession.objects.create(
        name="Theatre Locum",
        legacy_mysql_id=1201,
    )
    client = Client.objects.create(
        name="Rosebank Surgical Centre",
        legacy_mysql_id=901,
        region="Gauteng",
        city="Johannesburg",
    )
    site = Site.objects.create(client=client, name="Main Theatre")
    experienced = Candidate.objects.create(
        first_name="Experienced",
        last_name="Locum",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        legacy_mysql_id=501,
        home_area="Polokwane",
        home_region="Limpopo",
    )
    nearby = Candidate.objects.create(
        first_name="Nearby",
        last_name="Locum",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        legacy_mysql_id=502,
        home_area="Parktown",
        home_region="Gauteng",
    )
    experienced.professions.add(profession)
    nearby.professions.add(profession)
    FacilityExperience.objects.create(
        candidate=experienced,
        client=client,
        profession=profession,
        completed_shift_count=8,
        total_hours="84.00",
        last_worked_on=datetime(2026, 6, 14).date(),
    )
    start = timezone.make_aware(datetime(2026, 8, 22, 8, 0))
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="220.00",
        bill_rate="420.00",
    )
    future_booking_shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start - timedelta(days=7),
        ends_at=start - timedelta(days=7) + timedelta(hours=8),
        pay_rate="220.00",
        bill_rate="420.00",
    )
    Booking.objects.create(
        shift=future_booking_shift,
        candidate=nearby,
        status=Booking.Status.CONFIRMED,
    )
    booked_only_history_shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 6, 1, 8, 0)),
        ends_at=timezone.make_aware(datetime(2026, 6, 1, 16, 0)),
        pay_rate="220.00",
        bill_rate="420.00",
    )
    Booking.objects.create(
        shift=booked_only_history_shift,
        candidate=nearby,
        status=Booking.Status.CONFIRMED,
    )
    booked_only_history_shift.refresh_from_db()
    assert booked_only_history_shift.status == Shift.Status.BOOKED
    cancelled_history_shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 7, 1, 8, 0)),
        ends_at=timezone.make_aware(datetime(2026, 7, 1, 16, 0)),
        pay_rate="220.00",
        bill_rate="420.00",
    )
    Booking.objects.create(
        shift=cancelled_history_shift,
        candidate=nearby,
        status=Booking.Status.CONFIRMED,
    )
    cancelled_history_shift.status = Shift.Status.CANCELLED
    cancelled_history_shift.save(update_fields=["status"])

    response = api_client.get(f"/api/shifts/{shift.id}/candidates/")

    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [experienced.id, nearby.id]
    assert rows[0]["role_name"] == "Theatre Locum"
    assert rows[0]["worked_at_facility"] is True
    assert rows[0]["facility_shift_count"] == 8
    assert rows[0]["last_worked_on"] == "2026-06-14"
    assert rows[0]["eligibility_reasons"][:3] == [
        "Compliance cleared",
        "Theatre Locum role matched",
        "8 completed shifts at this facility",
    ]
    assert rows[1]["worked_at_facility"] is False
    assert rows[1]["proximity_label"] == "Same region as facility"


@pytest.mark.django_db
def test_shift_candidate_list_excludes_candidates_with_booking_clashes(api_client):
    profession = Profession.objects.create(name="ICU Nurse")
    client = Client.objects.create(name="West Hospital")
    site = Site.objects.create(client=client, name="ICU")
    candidate = Candidate.objects.create(
        first_name="Zanele",
        last_name="Zulu",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 10, 8, 0))
    existing = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="220.00", bill_rate="420.00",
    )
    requested = Shift.objects.create(
        site=site, profession=profession, starts_at=start + timedelta(hours=4),
        ends_at=start + timedelta(hours=12), pay_rate="220.00", bill_rate="420.00",
    )
    Booking.objects.create(
        shift=existing, candidate=candidate, status=Booking.Status.CONFIRMED,
    )

    response = api_client.get(f"/api/shifts/{requested.id}/candidates/")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.django_db
def test_confirmed_booking_rejects_inactive_legacy_candidate(api_client):
    profession = Profession.objects.create(name="Inactive Candidate Role")
    client = Client.objects.create(name="Inactive Candidate Facility")
    site = Site.objects.create(client=client, name="Main Ward")
    candidate = Candidate.objects.create(
        first_name="Inactive",
        last_name="Locum",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        is_active=False,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 9, 1, 8, 0))
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="220.00",
        bill_rate="420.00",
    )

    response = api_client.post(
        "/api/bookings/",
        {"shift": shift.id, "candidate": candidate.id, "status": "confirmed"},
        format="json",
    )

    assert response.status_code == 400
    assert "candidate" in response.json()


@pytest.mark.django_db
def test_invalid_booking_update_returns_400(api_client):
    nurse = Profession.objects.create(name="Update Nurse")
    pharmacist = Profession.objects.create(name="Update Pharmacist")
    client = Client.objects.create(name="Update Clinic")
    site = Site.objects.create(client=client, name="Ward H")
    candidate = Candidate.objects.create(
        first_name="Valid", last_name="Nurse",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    replacement = Candidate.objects.create(
        first_name="Wrong", last_name="Profession",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(nurse)
    replacement.professions.add(pharmacist)
    start = timezone.make_aware(datetime(2026, 8, 15, 8, 0))
    shift = Shift.objects.create(
        site=site, profession=nurse, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="200.00", bill_rate="380.00",
    )
    booking = Booking.objects.create(
        shift=shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )

    response = api_client.patch(
        f"/api/bookings/{booking.id}/",
        {"candidate": replacement.id},
        format="json",
    )

    assert response.status_code == 400
    assert "candidate" in response.json()


@pytest.mark.django_db
def test_candidate_matching_only_excludes_confirmed_overlaps(api_client):
    profession = Profession.objects.create(name="Matching Nurse")
    client = Client.objects.create(name="Matching Clinic")
    site = Site.objects.create(client=client, name="Ward I")
    candidate = Candidate.objects.create(
        first_name="Eligible", last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    requested_start = timezone.make_aware(datetime(2026, 8, 20, 8, 0))
    previous_shift = Shift.objects.create(
        site=site, profession=profession,
        starts_at=requested_start - timedelta(days=1),
        ends_at=requested_start - timedelta(days=1) + timedelta(hours=8),
        pay_rate="200.00", bill_rate="380.00",
    )
    offered_shift = Shift.objects.create(
        site=site, profession=profession,
        starts_at=requested_start + timedelta(hours=2),
        ends_at=requested_start + timedelta(hours=6),
        pay_rate="200.00", bill_rate="380.00",
    )
    requested_shift = Shift.objects.create(
        site=site, profession=profession,
        starts_at=requested_start,
        ends_at=requested_start + timedelta(hours=8),
        pay_rate="200.00", bill_rate="380.00",
    )
    Booking.objects.create(
        shift=previous_shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )
    Booking.objects.create(
        shift=offered_shift, candidate=candidate, status=Booking.Status.OFFERED,
    )

    response = api_client.get(f"/api/shifts/{requested_shift.id}/candidates/")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [candidate.id]


@pytest.mark.django_db
def test_authorized_staff_can_create_a_shift(api_client):
    profession = Profession.objects.create(name="New Shift Nurse")
    client = Client.objects.create(name="New Shift Hospital")
    site = Site.objects.create(client=client, name="Ward N")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="220.00",
        bill_rate="415.00",
    )

    response = api_client.post(
        "/api/shifts/",
        {
            "site": site.id,
            "profession": profession.id,
            "starts_at": "2026-09-12T06:00:00+02:00",
            "ends_at": "2026-09-12T18:00:00+02:00",
            "pay_rate": "225.00",
            "bill_rate": "425.00",
            "notes": "Day shift",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["client_name"] == "New Shift Hospital"
    assert response.json()["site_name"] == "Ward N"
    assert response.json()["profession_name"] == "New Shift Nurse"
    assert response.json()["bill_rate"] == "415.00"
    assert response.json()["status"] == Shift.Status.OPEN
    assert Shift.objects.filter(site=site, profession=profession).count() == 1


@pytest.mark.django_db
def test_shift_creation_options_list_sites_and_professions(api_client):
    profession = Profession.objects.create(name="Options Nurse")
    client = Client.objects.create(name="Options Hospital")
    site = Site.objects.create(client=client, name="Ward O")
    inactive_client = Client.objects.create(
        name="Inactive Legacy Hospital",
        legacy_mysql_id=991,
        is_active=False,
    )
    Site.objects.create(client=inactive_client, name="Old Ward")

    response = api_client.get("/api/shifts/creation-options/")

    assert response.status_code == 200
    assert response.json() == {
        "sites": [{
            "id": site.id,
            "name": "Ward O",
            "client_name": "Options Hospital",
        }],
        "professions": [{"id": profession.id, "name": "Options Nurse"}],
    }


@pytest.mark.django_db
def test_booking_inputs_reject_sites_for_inactive_clients():
    from bookings.serializers import (
        CandidateBookShiftsInputSerializer,
        FacilityBookNowInputSerializer,
        RankedFacilityCandidateQuerySerializer,
        ShiftSerializer,
        VacancySerializer,
    )

    inactive_client = Client.objects.create(
        name="Inactive Input Hospital",
        legacy_mysql_id=992,
        is_active=False,
    )
    site = Site.objects.create(client=inactive_client, name="Closed Ward")
    profession = Profession.objects.create(name="Inactive Input Nurse")
    candidate = Candidate.objects.create(
        first_name="Eligible",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    shift_item = {
        "starts_at": "2026-09-12T06:00:00+02:00",
        "ends_at": "2026-09-12T18:00:00+02:00",
    }
    serializers_and_payloads = (
        (
            RankedFacilityCandidateQuerySerializer,
            {"site": site.id, "profession": profession.id},
        ),
        (
            ShiftSerializer,
            {
                "site": site.id,
                "profession": profession.id,
                **shift_item,
                "pay_rate": "225.00",
            },
        ),
        (
            VacancySerializer,
            {
                "site": site.id,
                "profession": profession.id,
                "shift_items": [{**shift_item, "pay_rate": "225.00"}],
            },
        ),
        (
            FacilityBookNowInputSerializer,
            {
                "site": site.id,
                "profession": profession.id,
                "candidate": candidate.id,
                **shift_item,
            },
        ),
        (
            CandidateBookShiftsInputSerializer,
            {
                "site": site.id,
                "profession": profession.id,
                "candidate": candidate.id,
                "shift_items": [shift_item],
            },
        ),
    )

    for serializer_class, payload in serializers_and_payloads:
        serializer = serializer_class(data=payload)
        assert serializer.is_valid() is False, serializer_class.__name__
        assert "site" in serializer.errors, serializer_class.__name__


@pytest.mark.django_db
def test_staff_without_scheduling_permission_cannot_create_shift():
    user = get_user_model().objects.create_user(username="restricted", is_staff=True)
    client_api = APIClient()
    client_api.force_authenticate(user=user)
    profession = Profession.objects.create(name="Restricted Nurse")
    client = Client.objects.create(name="Restricted Hospital")
    site = Site.objects.create(client=client, name="Ward R")

    response = client_api.post(
        "/api/shifts/",
        {
            "site": site.id,
            "profession": profession.id,
            "starts_at": "2026-09-12T06:00:00+02:00",
            "ends_at": "2026-09-12T18:00:00+02:00",
            "pay_rate": "225.00",
            "bill_rate": "425.00",
        },
        format="json",
    )

    assert response.status_code == 403
    assert Shift.objects.filter(site=site).count() == 0

    vacancy_response = client_api.post(
        "/api/vacancies/",
        {
            "reference": "Restricted vacancy",
            "site": site.id,
            "profession": profession.id,
            "shift_items": [{
                "starts_at": "2026-09-12T06:00:00+02:00",
                "ends_at": "2026-09-12T18:00:00+02:00",
                "pay_rate": "225.00",
                "bill_rate": "425.00",
            }],
        },
        format="json",
    )

    assert vacancy_response.status_code == 403
    assert not Vacancy.objects.filter(reference="Restricted vacancy").exists()


@pytest.mark.django_db
def test_legacy_booking_permission_does_not_grant_candidate_edit_access():
    user = get_user_model().objects.create_user(
        username="booking-only-consultant",
        is_staff=True,
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=8101,
        link_conf=True,
        edit_cand=False,
    )
    profession = Profession.objects.create(name="Permission Nurse")
    client_api = APIClient()
    client_api.force_authenticate(user=user)

    assert client_api.get("/api/candidates/").status_code == 200
    denied = client_api.post(
        "/api/candidates/",
        {
            "first_name": "Denied",
            "last_name": "Candidate",
            "profession_ids": [profession.id],
        },
        format="json",
    )

    assert denied.status_code == 403
    assert not Candidate.objects.filter(first_name="Denied").exists()
    existing = Candidate.objects.create(
        first_name="Existing",
        last_name="Protected",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    existing.professions.add(profession)
    update_denied = client_api.patch(
        f"/api/candidates/{existing.id}/",
        {"home_area": "Unauthorized change"},
        format="json",
    )
    assert update_denied.status_code == 403
    existing.refresh_from_db()
    assert existing.home_area == ""
    assert not CandidateChangeAudit.objects.filter(candidate=existing).exists()


@pytest.mark.django_db
def test_legacy_user_without_scheduling_or_candidate_access_cannot_read_directories():
    user = get_user_model().objects.create_user(
        username="directory-restricted-consultant",
        is_staff=True,
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=8102,
        link_conf=False,
        edit_cand=False,
    )
    client_api = APIClient()
    client_api.force_authenticate(user=user)

    assert client_api.get("/api/candidates/").status_code == 403
    assert client_api.get("/api/shifts/").status_code == 403


@pytest.mark.django_db
def test_facility_candidate_directory_is_cleared_role_matched_and_ranked(api_client):
    profession = Profession.objects.create(name="Facility Doctor")
    other_profession = Profession.objects.create(name="Facility Pharmacist")
    client = Client.objects.create(
        name="Ranking Hospital",
        city="Sandton",
        region="Gauteng",
    )
    site = Site.objects.create(client=client, name="Main Facility")

    worked_before = Candidate.objects.create(
        first_name="Zed",
        last_name="Experienced",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        home_area="Cape Town",
        home_region="Western Cape",
    )
    same_town = Candidate.objects.create(
        first_name="Amy",
        last_name="Town",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        home_area="Sandton",
        home_region="Gauteng",
    )
    same_province = Candidate.objects.create(
        first_name="Aaron",
        last_name="Province",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        home_area="Pretoria",
        home_region="Gauteng",
    )
    other_location = Candidate.objects.create(
        first_name="Aardvark",
        last_name="Other",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        home_area="Cape Town",
        home_region="Western Cape",
    )
    pending = Candidate.objects.create(
        first_name="Eve",
        last_name="Pending",
        compliance_status=Candidate.ComplianceStatus.PENDING,
        home_area="Sandton",
        home_region="Gauteng",
    )
    wrong_role = Candidate.objects.create(
        first_name="Faye",
        last_name="Wrong Role",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        home_area="Sandton",
        home_region="Gauteng",
    )
    for candidate in [worked_before, same_town, same_province, other_location, pending]:
        candidate.professions.add(profession)
    wrong_role.professions.add(other_profession)
    FacilityExperience.objects.create(
        candidate=worked_before,
        client=client,
        profession=profession,
        completed_shift_count=3,
        total_hours="24.00",
        last_worked_on=datetime(2026, 7, 1).date(),
    )

    response = api_client.get(
        f"/api/candidates/?search=&profession={profession.id}&site={site.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert [candidate["full_name"] for candidate in payload] == [
        "Zed Experienced",
        "Amy Town",
        "Aaron Province",
        "Aardvark Other",
    ]
    assert payload[0]["worked_at_facility"] is True
    assert payload[0]["facility_shift_count"] == 3
    assert payload[1]["proximity_label"] == "Same town as facility"
    assert payload[2]["proximity_label"] == "Same province as facility"


@pytest.mark.django_db
def test_facility_candidate_directory_validates_profession_and_excludes_conflicts(api_client):
    profession = Profession.objects.create(name="Available Doctor")
    client = Client.objects.create(name="Availability Hospital")
    site = Site.objects.create(client=client, name="Availability Facility")
    candidate = Candidate.objects.create(
        first_name="Busy",
        last_name="Doctor",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    conflicting_shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=datetime.fromisoformat("2026-09-15T09:00:00+02:00"),
        ends_at=datetime.fromisoformat("2026-09-15T17:00:00+02:00"),
        pay_rate="300.00",
        bill_rate="500.00",
    )
    Booking.objects.create(
        shift=conflicting_shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    invalid_profession = api_client.get(
        f"/api/candidates/?profession=999999&site={site.id}"
    )
    conflicting = api_client.get(
        "/api/candidates/",
        {
            "profession": profession.id,
            "site": site.id,
            "starts_at": "2026-09-15T08:00:00+02:00",
            "ends_at": "2026-09-15T16:00:00+02:00",
        },
    )

    assert invalid_profession.status_code == 400
    assert "profession" in invalid_profession.json()
    assert conflicting.status_code == 200
    assert conflicting.json() == []


@pytest.mark.django_db
def test_facility_candidate_history_uses_johannesburg_end_date(api_client):
    profession = Profession.objects.create(name="Overnight Doctor")
    client = Client.objects.create(name="Overnight Hospital")
    site = Site.objects.create(client=client, name="Overnight Facility")
    candidate = Candidate.objects.create(
        first_name="Night",
        last_name="Doctor",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    completed_shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=datetime.fromisoformat("2026-07-01T18:00:00+02:00"),
        ends_at=datetime.fromisoformat("2026-07-02T00:30:00+02:00"),
        pay_rate="300.00",
        bill_rate="500.00",
    )
    Booking.objects.create(
        shift=completed_shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )
    completed_shift.status = Shift.Status.COMPLETED
    completed_shift.save(update_fields=["status"])

    response = api_client.get(
        f"/api/candidates/?profession={profession.id}&site={site.id}"
    )

    assert response.status_code == 200
    assert response.json()[0]["last_worked_on"] == "2026-07-02"


@pytest.mark.django_db
def test_facility_book_now_creates_vacancy_shift_and_booking_atomically(api_client):
    profession = Profession.objects.create(name="Book Now Doctor")
    client = Client.objects.create(name="Book Now Hospital")
    site = Site.objects.create(client=client, name="Book Now Facility")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="300.00",
        bill_rate="500.00",
    )
    candidate = Candidate.objects.create(
        first_name="Grace",
        last_name="Eligible",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)

    response = api_client.post(
        "/api/vacancies/book-now/",
        {
            "reference": "Urgent Facility booking",
            "site": site.id,
            "profession": profession.id,
            "notes": "Created and booked together",
            "candidate": candidate.id,
            "starts_at": "2026-09-12T08:00:00+02:00",
            "ends_at": "2026-09-12T16:00:00+02:00",
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    shift = Shift.objects.get(pk=payload["vacancy"]["shifts"][0]["id"])
    booking = Booking.objects.get(pk=payload["booking"]["id"])
    assert shift.status == Shift.Status.BOOKED
    assert booking.shift == shift
    assert booking.candidate == candidate
    assert booking.status == Booking.Status.CONFIRMED
    assert shift.pay_rate == Decimal("300.00")
    assert shift.bill_rate == Decimal("500.00")
    assert not SiteProfessionRate.objects.filter(site=site, profession=profession).exists()

    pending = Candidate.objects.create(
        first_name="Hana",
        last_name="Pending",
        compliance_status=Candidate.ComplianceStatus.PENDING,
    )
    pending.professions.add(profession)
    counts_before = (Vacancy.objects.count(), Shift.objects.count(), Booking.objects.count())

    rejected = api_client.post(
        "/api/vacancies/book-now/",
        {
            "reference": "Must roll back",
            "site": site.id,
            "profession": profession.id,
            "candidate": pending.id,
            "starts_at": "2026-09-13T08:00:00+02:00",
            "ends_at": "2026-09-13T16:00:00+02:00",
        },
        format="json",
    )

    assert rejected.status_code == 400
    assert (Vacancy.objects.count(), Shift.objects.count(), Booking.objects.count()) == counts_before
    assert not SiteProfessionRate.objects.filter(site=site, profession=profession).exists()


@pytest.mark.django_db
def test_facility_book_now_rejects_non_object_and_browser_rate_fields(api_client):
    api_client.raise_request_exception = False
    malformed = api_client.post(
        "/api/vacancies/book-now/",
        [],
        format="json",
    )

    assert malformed.status_code == 400

    profession = Profession.objects.create(name="Strict Book Now Nurse")
    client = Client.objects.create(name="Strict Book Now Hospital")
    site = Site.objects.create(client=client, name="Strict Book Now Ward")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="250.00",
        bill_rate="450.00",
    )
    candidate = Candidate.objects.create(
        first_name="Strict",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)

    injected = api_client.post(
        "/api/vacancies/book-now/",
        {
            "site": site.id,
            "profession": profession.id,
            "candidate": candidate.id,
            "starts_at": "2026-10-01T08:00:00+02:00",
            "ends_at": "2026-10-01T16:00:00+02:00",
            "pay_rate": "1.00",
            "bill_rate": "1.00",
        },
        format="json",
    )

    assert injected.status_code == 400
    assert not Vacancy.objects.exists()
    assert not Shift.objects.exists()
    assert not Booking.objects.exists()
    assert not SiteProfessionRate.objects.exists()


@pytest.mark.django_db
def test_complete_vacancy_candidate_booking_board_and_calendar_journey(api_client):
    profession = Profession.objects.create(name="Journey Nurse")
    client = Client.objects.create(name="Journey Hospital")
    site = Site.objects.create(client=client, name="Journey Ward")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="275.00",
        bill_rate="475.00",
    )
    candidate = Candidate.objects.create(
        first_name="Complete",
        last_name="Journey",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    created = api_client.post(
        "/api/vacancies/",
        {
            "reference": "Complete user journey",
            "site": site.id,
            "profession": profession.id,
            "notes": "Follow from Vacancy through Calendar",
            "shift_items": [{
                "starts_at": "2026-10-10T08:00:00+02:00",
                "ends_at": "2026-10-10T16:00:00+02:00",
                "pay_rate": "275.00",
            }],
        },
        format="json",
    )
    assert created.status_code == 201
    shift_id = created.json()["shifts"][0]["id"]
    assert created.json()["shifts"][0]["status"] == Shift.Status.OPEN

    shortlist = api_client.get(f"/api/shifts/{shift_id}/candidates/")
    assert shortlist.status_code == 200
    assert [item["id"] for item in shortlist.json()] == [candidate.id]

    confirmed = api_client.post(
        "/api/bookings/",
        {"shift": shift_id, "candidate": candidate.id, "status": Booking.Status.CONFIRMED},
        format="json",
    )
    assert confirmed.status_code == 201

    board = api_client.get("/api/shifts/")
    assert board.status_code == 200
    board_shift = next(item for item in board.json() if item["id"] == shift_id)
    assert board_shift["status"] == Shift.Status.BOOKED
    assert board_shift["confirmed_booking"]["candidate_name"] == "Complete Journey"

    calendar = api_client.get(
        "/api/shifts/",
        {
            "site": site.id,
            "starts_before": "2026-11-01T00:00:00+02:00",
            "ends_after": "2026-10-01T00:00:00+02:00",
        },
    )
    assert calendar.status_code == 200
    calendar_shift = next(item for item in calendar.json() if item["id"] == shift_id)
    assert calendar_shift["status"] == Shift.Status.BOOKED
    assert calendar_shift["confirmed_booking"]["candidate_id"] == candidate.id


@pytest.mark.django_db
def test_facility_book_now_failures_are_authorized_and_leave_no_partial_records(api_client):
    profession = Profession.objects.create(name="Guarded Nurse")
    other_profession = Profession.objects.create(name="Guarded Pharmacist")
    client = Client.objects.create(name="Guarded Hospital")
    site = Site.objects.create(client=client, name="Guarded Ward")
    eligible = Candidate.objects.create(
        first_name="Eligible", last_name="Guarded",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    eligible.professions.add(profession)
    wrong_role = Candidate.objects.create(
        first_name="Wrong", last_name="Role",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    wrong_role.professions.add(other_profession)
    inactive = Candidate.objects.create(
        first_name="Inactive", last_name="Guarded", is_active=False,
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    inactive.professions.add(profession)

    def payload(candidate):
        return {
            "site": site.id,
            "profession": profession.id,
            "candidate": candidate.id,
            "starts_at": "2026-10-12T08:00:00+02:00",
            "ends_at": "2026-10-12T16:00:00+02:00",
        }

    missing_rate = api_client.post(
        "/api/vacancies/book-now/", payload(eligible), format="json"
    )
    assert missing_rate.status_code == 400
    assert not Vacancy.objects.exists()
    assert not Shift.objects.exists()
    assert not Booking.objects.exists()

    ClientProfessionRate.objects.create(
        client=client, profession=profession,
        pay_rate="280.00", bill_rate="480.00",
    )
    for rejected_candidate in (wrong_role, inactive):
        before = (Vacancy.objects.count(), Shift.objects.count(), Booking.objects.count())
        response = api_client.post(
            "/api/vacancies/book-now/", payload(rejected_candidate), format="json"
        )
        assert response.status_code == 400
        assert (Vacancy.objects.count(), Shift.objects.count(), Booking.objects.count()) == before
        assert not SiteProfessionRate.objects.exists()

    conflicting_shift = Shift.objects.create(
        site=site, profession=profession,
        starts_at=datetime.fromisoformat("2026-10-12T09:00:00+02:00"),
        ends_at=datetime.fromisoformat("2026-10-12T17:00:00+02:00"),
        pay_rate="280.00", bill_rate="480.00",
    )
    Booking.objects.create(
        shift=conflicting_shift, candidate=eligible,
        status=Booking.Status.CONFIRMED,
    )
    before = (Vacancy.objects.count(), Shift.objects.count(), Booking.objects.count())
    conflict = api_client.post(
        "/api/vacancies/book-now/", payload(eligible), format="json"
    )
    assert conflict.status_code == 400
    assert (Vacancy.objects.count(), Shift.objects.count(), Booking.objects.count()) == before
    assert not SiteProfessionRate.objects.exists()

    unauthorized_user = get_user_model().objects.create_user(
        username="book-now-unauthorized", is_staff=True
    )
    unauthorized = APIClient()
    unauthorized.force_authenticate(user=unauthorized_user)
    denied = unauthorized.post(
        "/api/vacancies/book-now/", payload(eligible), format="json"
    )
    assert denied.status_code == 403
    assert (Vacancy.objects.count(), Shift.objects.count(), Booking.objects.count()) == before


@pytest.mark.django_db
def test_facility_book_now_rejects_multi_shift_payload_without_side_effects(api_client):
    profession = Profession.objects.create(name="Single Shift Nurse")
    client = Client.objects.create(name="Single Shift Hospital")
    site = Site.objects.create(client=client, name="Single Shift Ward")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="260.00",
        bill_rate="460.00",
    )
    candidate = Candidate.objects.create(
        first_name="Single",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)

    response = api_client.post(
        "/api/vacancies/book-now/",
        {
            "site": site.id,
            "profession": profession.id,
            "candidate": candidate.id,
            "shift_items": [
                {
                    "starts_at": "2026-10-02T08:00:00+02:00",
                    "ends_at": "2026-10-02T16:00:00+02:00",
                    "pay_rate": "260.00",
                },
                {
                    "starts_at": "2026-10-03T08:00:00+02:00",
                    "ends_at": "2026-10-03T16:00:00+02:00",
                    "pay_rate": "260.00",
                },
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    assert not Vacancy.objects.exists()
    assert not Shift.objects.exists()
    assert not Booking.objects.exists()
    assert not SiteProfessionRate.objects.exists()


@pytest.mark.django_db
def test_candidate_origin_creates_and_books_multiple_new_shifts_atomically(api_client):
    profession = Profession.objects.create(name="Candidate Origin Nurse")
    client = Client.objects.create(name="Candidate Origin Hospital")
    site = Site.objects.create(client=client, name="Candidate Origin Ward")
    SiteProfessionRate.objects.create(
        site=site, profession=profession, pay_rate="245.00", bill_rate="455.00"
    )
    candidate = Candidate.objects.create(
        first_name="Nomsa",
        last_name="New Shifts",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)

    response = api_client.post(
        "/api/vacancies/book-candidate-shifts/",
        {
            "candidate": candidate.id,
            "site": site.id,
            "profession": profession.id,
            "reference": "Candidate-created work",
            "shift_items": [
                {"starts_at": "2026-09-10T07:00:00+02:00", "ends_at": "2026-09-10T15:00:00+02:00"},
                {"starts_at": "2026-09-11T07:00:00+02:00", "ends_at": "2026-09-11T15:00:00+02:00"},
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    vacancy = Vacancy.objects.get(reference="Candidate-created work")
    shifts = list(vacancy.shifts.order_by("starts_at"))
    assert len(shifts) == 2
    assert {shift.pay_rate for shift in shifts} == {Decimal("245.00")}
    assert {shift.bill_rate for shift in shifts} == {Decimal("455.00")}
    assert {shift.status for shift in shifts} == {Shift.Status.BOOKED}
    assert Booking.objects.filter(
        shift__vacancy=vacancy, candidate=candidate, status=Booking.Status.CONFIRMED
    ).count() == 2
    assert len(response.json()["bookings"]) == 2


@pytest.mark.django_db
def test_candidate_origin_rolls_back_all_new_work_when_one_shift_is_invalid(api_client):
    profession = Profession.objects.create(name="Atomic Candidate Nurse")
    client = Client.objects.create(name="Atomic Candidate Hospital")
    site = Site.objects.create(client=client, name="Atomic Candidate Ward")
    SiteProfessionRate.objects.create(
        site=site, profession=profession, pay_rate="250.00", bill_rate="460.00"
    )
    candidate = Candidate.objects.create(
        first_name="Atomic",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)

    response = api_client.post(
        "/api/vacancies/book-candidate-shifts/",
        {
            "candidate": candidate.id,
            "site": site.id,
            "profession": profession.id,
            "shift_items": [
                {"starts_at": "2026-09-12T07:00:00+02:00", "ends_at": "2026-09-12T15:00:00+02:00"},
                {"starts_at": "2026-09-12T14:00:00+02:00", "ends_at": "2026-09-12T22:00:00+02:00"},
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    assert not Vacancy.objects.exists()
    assert not Shift.objects.exists()
    assert not Booking.objects.exists()
