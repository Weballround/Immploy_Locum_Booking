from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
import pytest
from rest_framework.test import APIClient

from bookings.models import (
    Booking,
    Candidate,
    Client,
    Profession,
    Shift,
    Site,
    SiteProfessionRate,
    Vacancy,
)


@pytest.mark.django_db
def test_candidate_directory_returns_stable_profession_ids():
    user = get_user_model().objects.create_user(username="candidate-directory-booker", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    profession = Profession.objects.create(name="Directory Profession")
    candidate = Candidate.objects.create(
        first_name="Directory",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)

    response = api_client.get("/api/candidates/")

    assert response.status_code == 200
    assert response.json()[0]["profession_ids"] == [profession.id]


@pytest.mark.django_db
def test_candidate_origin_rejects_browser_rate_fields_without_side_effects():
    user = get_user_model().objects.create_user(username="strict-candidate-booker", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    profession = Profession.objects.create(name="Strict Candidate Nurse")
    client = Client.objects.create(name="Strict Candidate Hospital")
    site = Site.objects.create(client=client, name="Strict Candidate Ward")
    SiteProfessionRate.objects.create(
        site=site,
        profession=profession,
        pay_rate="250.00",
        bill_rate="460.00",
    )
    candidate = Candidate.objects.create(
        first_name="Strict",
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
            "shift_items": [{
                "starts_at": "2026-09-13T07:00:00+02:00",
                "ends_at": "2026-09-13T15:00:00+02:00",
                "pay_rate": "1.00",
                "bill_rate": "1.00",
            }],
        },
        format="json",
    )

    assert response.status_code == 400
    assert not Vacancy.objects.exists()
    assert not Shift.objects.exists()
    assert not Booking.objects.exists()
