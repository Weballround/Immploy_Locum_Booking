import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.utils import timezone

from bookings.models import MfaDevice


@pytest.mark.django_db
def test_user_admin_exposes_existing_mfa_device_for_secure_reset_only():
    user_admin = admin.site._registry[get_user_model()]
    request = RequestFactory().get("/admin/auth/user/")
    request.user = get_user_model().objects.create_superuser(
        username="mfa-admin",
        password="local-test-password",
    )

    mfa_inline = next(
        (inline(user_admin.model, admin.site) for inline in user_admin.inlines
         if inline.model is MfaDevice),
        None,
    )

    assert mfa_inline is not None
    assert mfa_inline.can_delete is True
    assert mfa_inline.has_add_permission(request) is False
    assert "secret_ciphertext" not in mfa_inline.get_fields(request)
    assert "mfa_status" in user_admin.readonly_fields
    assert "mfa_status" in user_admin.list_display
    assert "mfa_recovery_guidance" in user_admin.readonly_fields
    assert user_admin.mfa_status(request.user) == "Not enrolled"
    assert "administrators cannot create or view" in user_admin.mfa_recovery_guidance(request.user)


@pytest.mark.django_db
def test_user_admin_renders_mfa_reset_without_exposing_encrypted_secret():
    admin_user = get_user_model().objects.create_superuser(
        username="recovery-admin",
        password="local-test-password",
    )
    target = get_user_model().objects.create_user(username="mfa-recovery-target")
    MfaDevice.objects.create(
        user=target,
        secret_ciphertext=b"encrypted-secret-must-not-render",
        confirmed_at=timezone.now(),
    )
    browser = Client()
    browser.force_login(admin_user)

    response = browser.get(f"/admin/auth/user/{target.pk}/change/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "MFA recovery" in content
    assert "Microsoft Authenticator enrollment" in content
    assert 'name="mfa_device-0-DELETE"' in content
    assert "encrypted-secret-must-not-render" not in content
