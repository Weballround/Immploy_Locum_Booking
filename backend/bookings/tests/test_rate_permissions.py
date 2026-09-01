from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client as DjangoClient
from rest_framework.test import APIClient

from bookings.models import (
    Booking,
    Client,
    ClientProfessionRate,
    Profession,
    Shift,
    Site,
)


RATE_PERMISSIONS = {
    "view_candidate_pay_rates": "Can view Candidate pay rates",
    "view_client_charge_rates": "Can view Client charges and profitability",
    "override_approved_rates": "Can override approved rates",
}


def grant_permission(user, codename):
    content_type = ContentType.objects.get_for_model(Booking)
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=codename,
        defaults={"name": RATE_PERMISSIONS[codename]},
    )
    user.user_permissions.add(permission)


def booking_user(username, *rate_permissions):
    user = get_user_model().objects.create_user(username=username, is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    for codename in rate_permissions:
        grant_permission(user, codename)
    return user


def rate_setup(prefix):
    profession = Profession.objects.create(name=f"{prefix} Nurse")
    client = Client.objects.create(name=f"{prefix} Hospital")
    site = Site.objects.create(client=client, name=f"{prefix} Facility")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="220.00",
        bill_rate="410.00",
    )
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at="2026-09-12T06:00:00+02:00",
        ends_at="2026-09-12T13:00:00+02:00",
        pay_rate="220.00",
        bill_rate="410.00",
    )
    return profession, site, shift


@pytest.mark.django_db
def test_session_reports_rate_permissions_independently():
    user = booking_user("pay-only-session", "view_candidate_pay_rates")
    browser = DjangoClient()
    browser.force_login(user)

    response = browser.get("/api/session/")

    assert response.status_code == 200
    assert response.json()["permissions"] == {
        "manage_bookings": True,
        "manage_candidates": True,
        "send_booking_sms": False,
        "view_candidate_pay_rates": True,
        "view_client_charge_rates": False,
        "override_approved_rates": False,
    }


@pytest.mark.django_db
def test_booking_only_shift_response_omits_both_commercial_rates():
    user = booking_user("no-rate-reader")
    _, _, shift = rate_setup("No rate")
    api = APIClient()
    api.force_authenticate(user=user)

    response = api.get(f"/api/shifts/{shift.id}/")

    assert response.status_code == 200
    assert "pay_rate" not in response.json()
    assert "bill_rate" not in response.json()


@pytest.mark.django_db
def test_pay_and_client_charge_permissions_reveal_only_their_own_field():
    pay_user = booking_user("pay-rate-reader", "view_candidate_pay_rates")
    charge_user = booking_user("charge-rate-reader", "view_client_charge_rates")
    _, _, shift = rate_setup("Split rate")

    pay_api = APIClient()
    pay_api.force_authenticate(user=pay_user)
    pay_response = pay_api.get(f"/api/shifts/{shift.id}/")

    charge_api = APIClient()
    charge_api.force_authenticate(user=charge_user)
    charge_response = charge_api.get(f"/api/shifts/{shift.id}/")

    assert pay_response.json()["pay_rate"] == "220.00"
    assert "bill_rate" not in pay_response.json()
    assert charge_response.json()["bill_rate"] == "410.00"
    assert "pay_rate" not in charge_response.json()


@pytest.mark.django_db
def test_site_role_options_redact_each_rate_independently():
    no_rate_user = booking_user("role-no-rates")
    pay_user = booking_user("role-pay-rate", "view_candidate_pay_rates")
    charge_user = booking_user("role-charge-rate", "view_client_charge_rates")
    profession, site, _ = rate_setup("Role options")

    def role_payload(user):
        api = APIClient()
        api.force_authenticate(user=user)
        response = api.get("/api/vacancies/site-role-options/", {"site": site.id})
        assert response.status_code == 200
        return response.json()["professions"][0]

    assert role_payload(no_rate_user) == {"id": profession.id, "name": profession.name}
    assert role_payload(pay_user) == {
        "id": profession.id,
        "name": profession.name,
        "pay_rate": "220.00",
    }
    assert role_payload(charge_user) == {
        "id": profession.id,
        "name": profession.name,
        "bill_rate": "410.00",
    }


@pytest.mark.django_db
def test_booking_user_without_override_gets_server_approved_pay_rate():
    user = booking_user("approved-rate-only")
    profession, site, _ = rate_setup("Approved default")
    api = APIClient()
    api.force_authenticate(user=user)

    response = api.post(
        "/api/vacancies/",
        {
            "reference": "Approved rate",
            "site": site.id,
            "profession": profession.id,
            "shift_items": [{
                "starts_at": "2026-10-01T06:00:00+02:00",
                "ends_at": "2026-10-01T13:00:00+02:00",
            }],
        },
        format="json",
    )

    assert response.status_code == 201
    created = Shift.objects.get(vacancy_id=response.json()["id"])
    assert created.pay_rate == Decimal("220.00")
    assert created.bill_rate == Decimal("410.00")


@pytest.mark.django_db
def test_booking_user_without_override_cannot_submit_a_different_pay_rate():
    user = booking_user("forbidden-rate-override")
    profession, site, _ = rate_setup("Forbidden override")
    api = APIClient()
    api.force_authenticate(user=user)

    response = api.post(
        "/api/vacancies/",
        {
            "reference": "Forbidden override",
            "site": site.id,
            "profession": profession.id,
            "shift_items": [{
                "starts_at": "2026-10-03T06:00:00+02:00",
                "ends_at": "2026-10-03T13:00:00+02:00",
                "pay_rate": "999.00",
            }],
        },
        format="json",
    )

    assert response.status_code == 400
    assert "permission" in str(response.json()).lower()
    assert not Shift.objects.filter(vacancy__reference="Forbidden override").exists()


@pytest.mark.django_db
def test_explicit_override_permission_allows_shift_pay_override_without_changing_approved_rate():
    user = booking_user(
        "approved-rate-overrider",
        "view_candidate_pay_rates",
        "override_approved_rates",
    )
    profession, site, _ = rate_setup("Approved override")
    approved = ClientProfessionRate.objects.get(client=site.client, profession=profession)
    api = APIClient()
    api.force_authenticate(user=user)

    response = api.post(
        "/api/vacancies/",
        {
            "reference": "Approved override",
            "site": site.id,
            "profession": profession.id,
            "shift_items": [{
                "starts_at": "2026-10-02T06:00:00+02:00",
                "ends_at": "2026-10-02T13:00:00+02:00",
                "pay_rate": "235.00",
            }],
        },
        format="json",
    )

    assert response.status_code == 201
    created = Shift.objects.get(vacancy_id=response.json()["id"])
    assert created.pay_rate == Decimal("235.00")
    approved.refresh_from_db()
    assert approved.pay_rate == Decimal("220.00")
    assert approved.bill_rate == Decimal("410.00")
