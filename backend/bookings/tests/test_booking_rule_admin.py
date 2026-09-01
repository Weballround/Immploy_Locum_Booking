import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client as DjangoClient

from bookings.models import BookingRule


@pytest.mark.django_db
def test_booking_rules_are_visible_and_editable_in_django_admin():
    user = get_user_model().objects.create_superuser(
        username="booking-rule-admin",
        password="local-test-password",
    )
    browser = DjangoClient()
    browser.force_login(user)
    rule = BookingRule.objects.get(pk=1)

    change_list = browser.get("/admin/bookings/bookingrule/")
    change_form = browser.get(
        f"/admin/bookings/bookingrule/{rule.pk}/change/"
    )

    assert change_list.status_code == 200
    assert b"No Candidate double booking" in change_list.content
    assert change_form.status_code == 200
    assert b"No Candidate double booking" in change_form.content
    assert b"different Clients, facilities or locations" in change_form.content
    assert b'name="minimum_rest_minutes"' in change_form.content
    assert b'name="prevent_candidate_overlap"' not in change_form.content


@pytest.mark.django_db
def test_booking_overlap_rule_is_mandatory_and_cannot_be_deleted():
    rule = BookingRule.objects.get(pk=1)
    model_admin = admin.site._registry[BookingRule]

    assert rule.prevent_candidate_overlap is True
    assert model_admin.has_delete_permission(None, rule) is False
    assert "prevent_candidate_overlap" in model_admin.readonly_fields
