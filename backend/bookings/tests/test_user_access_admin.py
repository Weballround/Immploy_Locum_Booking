import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from bookings.admin import ImmployUserAdmin, LegacyUserAccessInline
from bookings.department_scope import user_department_ids
from bookings.models import Department, LegacyUserProfile
from bookings.permissions import user_can_manage_bookings, user_can_manage_candidates


@pytest.mark.django_db
def test_local_booking_overrides_control_permissions_and_department_scope():
    nursing = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    radiology = Department.objects.create(legacy_mysql_id=9, name="Radiology")
    user = get_user_model().objects.create_user(
        username="permanent.consultant",
        is_active=True,
        is_staff=True,
    )
    profile = LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=9001,
        assigned_desk=6,
        link_conf=False,
        edit_cand=False,
        booking_access_override=True,
        candidate_access_override=True,
    )
    profile.booking_departments.add(nursing, radiology)

    assert user_can_manage_bookings(user) is True
    assert user_can_manage_candidates(user) is True
    assert set(user_department_ids(user)) == {nursing.id, radiology.id}


@pytest.mark.django_db
def test_all_booking_departments_override_is_explicit_and_unscoped():
    user = get_user_model().objects.create_user(
        username="cross.desk.consultant",
        is_active=True,
        is_staff=True,
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=9002,
        assigned_desk=6,
        all_booking_departments=True,
    )

    assert user_department_ids(user) is None


@pytest.mark.django_db
def test_user_admin_combines_account_source_access_and_booking_overrides():
    user_admin = ImmployUserAdmin(get_user_model(), admin.site)
    inline = LegacyUserAccessInline(get_user_model(), admin.site)

    assert LegacyUserAccessInline in user_admin.inlines
    assert inline.can_delete is False
    assert inline.extra == 0
    assert "access_summary" in user_admin.list_display
    assert "access_problem" in user_admin.list_display
    assert "legacy_profile__assigned_desk" in user_admin.list_filter
    assert "legacy_profile__link_conf" in user_admin.list_filter
    assert "legacy_profile__edit_cand" in user_admin.list_filter


@pytest.mark.django_db
def test_user_admin_flags_active_booking_user_with_no_department_scope():
    user = get_user_model().objects.create_user(
        username="unmapped.consultant",
        is_active=True,
        is_staff=True,
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=9003,
        assigned_desk=6,
        link_conf=True,
        edit_cand=True,
    )
    request = RequestFactory().get("/admin/auth/user/")
    request.user = get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.test",
        password=None,
    )
    user_admin = ImmployUserAdmin(get_user_model(), admin.site)

    assert "No Booking department scope" in str(user_admin.access_problem(user))
