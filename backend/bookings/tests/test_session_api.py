import json
import time

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings
from django.utils import timezone

from bookings.mfa import decrypt_secret, encrypt_secret
from bookings.mfa_assurance import (
    MFA_ACCOUNT_GENERATION_SESSION_KEY,
    current_mfa_generation,
)
from bookings.models import (
    LegacyUserProfile,
    LoginAttempt,
    MfaAccountState,
    MfaDevice,
    MfaTrustedBrowser,
)


def pending_mfa_secret(browser):
    encrypted_secret = browser.session["pending_mfa_secret"]
    return decrypt_secret(encrypted_secret.encode("ascii"))


@pytest.mark.django_db
def test_session_endpoint_logs_staff_user_in_with_csrf_protection():
    get_user_model().objects.create_user(
        username="consultant",
        password="local-test-password",
        is_staff=True,
        first_name="Nandi",
    )
    browser = Client(enforce_csrf_checks=True)

    session_response = browser.get("/api/session/")
    csrf_token = session_response.cookies["csrftoken"].value
    login_response = browser.post(
        "/api/session/",
        data=json.dumps(
            {"username": "consultant", "password": "local-test-password"}
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert session_response.json() == {"authenticated": False, "user": None}
    assert login_response.status_code == 200
    assert login_response.json() == {
        "authenticated": True,
        "booking_time_step_seconds": 900,
        "mfa_enabled": False,
        "user": {"username": "consultant", "display_name": "Nandi"},
        "access_rules": None,
        "permissions": {
            "manage_bookings": False,
            "manage_candidates": False,
            "send_booking_sms": False,
            "view_candidate_pay_rates": False,
            "view_client_charge_rates": False,
            "override_approved_rates": False,
        },
    }
    assert browser.get("/api/shifts/").status_code == 403


@pytest.mark.django_db
def test_edit_candidate_access_is_exposed_without_scheduling_access():
    user = get_user_model().objects.create_user(
        username="candidate-editor",
        is_staff=True,
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=991,
        link_conf=False,
        edit_cand=True,
    )
    browser = Client()
    browser.force_login(user)

    payload = browser.get("/api/session/").json()

    assert payload["permissions"] == {
        "manage_bookings": False,
        "manage_candidates": True,
        "send_booking_sms": False,
        "view_candidate_pay_rates": False,
        "view_client_charge_rates": False,
        "override_approved_rates": False,
    }
    assert browser.get("/api/candidates/creation-options/").status_code == 200
    assert browser.get("/api/vacancies/creation-options/").status_code == 403


@pytest.mark.django_db
def test_booking_sms_permission_is_exposed_independently():
    user = get_user_model().objects.create_user(
        username="sms-capability-user",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="send_booking_sms"))
    browser = Client()
    browser.force_login(user)

    payload = browser.get("/api/session/").json()

    assert payload["permissions"] == {
        "manage_bookings": False,
        "manage_candidates": False,
        "send_booking_sms": True,
        "view_candidate_pay_rates": False,
        "view_client_charge_rates": False,
        "override_approved_rates": False,
    }


@pytest.mark.django_db
def test_permanent_desk_session_uses_one_minute_booking_times():
    user = get_user_model().objects.create_user(
        username="per-minute-session-user",
        is_staff=True,
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=992,
        assigned_desk=6,
        link_conf=True,
    )
    browser = Client()
    browser.force_login(user)

    payload = browser.get("/api/session/").json()

    assert payload["booking_time_step_seconds"] == 60


@pytest.mark.django_db
def test_session_endpoint_rejects_invalid_credentials():
    LoginAttempt.objects.all().delete()
    browser = Client(enforce_csrf_checks=True)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value

    response = browser.post(
        "/api/session/",
        data=json.dumps({"username": "unknown", "password": "wrong"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid username or password."}


@pytest.mark.django_db
def test_session_endpoint_rejects_non_object_json():
    browser = Client(enforce_csrf_checks=True)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value

    response = browser.post(
        "/api/session/",
        data="[]",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}

    invalid_encoding = browser.post(
        "/api/session/",
        data=b"\xff",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert invalid_encoding.status_code == 400
    assert invalid_encoding.json() == {"error": "Invalid request."}


@pytest.mark.django_db
def test_session_endpoint_throttles_repeated_invalid_logins():
    LoginAttempt.objects.all().delete()
    browser = Client(enforce_csrf_checks=True, REMOTE_ADDR="192.0.2.10")
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value

    for _ in range(5):
        response = browser.post(
            "/api/session/",
            data=json.dumps({"username": "unknown", "password": "wrong"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert response.status_code == 400

    throttled = browser.post(
        "/api/session/",
        data=json.dumps({"username": "unknown", "password": "wrong"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert throttled.status_code == 429
    assert throttled.json() == {"error": "Too many sign-in attempts. Try again later."}
    assert throttled.headers["Retry-After"] == "300"
    assert LoginAttempt.objects.count() == 2


@pytest.mark.django_db
def test_alternate_login_endpoints_cannot_bypass_throttling():
    LoginAttempt.objects.all().delete()
    csrf_browser = Client(enforce_csrf_checks=True, REMOTE_ADDR="192.0.2.21")
    denied = csrf_browser.post(
        "/admin/login/",
        {"username": "unknown-admin", "password": "wrong"},
    )
    assert denied.status_code == 403
    assert LoginAttempt.objects.count() == 0

    browser = Client(REMOTE_ADDR="192.0.2.20")

    assert browser.get("/api-auth/login/").status_code == 404
    for _ in range(5):
        response = browser.post(
            "/admin/login/",
            {"username": "unknown-admin", "password": "wrong"},
        )
        assert response.status_code == 200

    throttled = browser.post(
        "/admin/login/",
        {"username": "unknown-admin", "password": "wrong"},
    )
    assert throttled.status_code == 429
    assert throttled.headers["Retry-After"] == "300"


@pytest.mark.django_db
def test_staff_user_can_start_microsoft_authenticator_enrollment():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value

    setup_response = browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert setup_response.status_code == 200
    setup = setup_response.json()
    assert "provisioning_uri" not in setup
    assert setup["qr_code_data_url"].startswith("data:image/svg+xml;base64,")
    assert setup["enabled"] is False
    assert "no-store" in setup_response.headers["Cache-Control"]
    assert "private" in setup_response.headers["Cache-Control"]
    assert setup_response.headers["Pragma"] == "no-cache"
    assert setup_response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.django_db
def test_microsoft_authenticator_enrollment_requires_current_password():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value

    response = browser.post(
        "/api/mfa/",
        data="{}",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Current password is required."}


@pytest.mark.django_db
def test_pending_authenticator_secret_is_encrypted_in_session_storage():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value

    setup = browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    ).json()
    secret = pending_mfa_secret(browser)
    stored_value = browser.session["pending_mfa_secret"]

    assert stored_value != secret
    assert secret not in stored_value


@pytest.mark.django_db
def test_pending_authenticator_enrollment_expires():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client()
    browser.force_login(user)
    browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
    )
    secret = pending_mfa_secret(browser)
    session = browser.session
    session["pending_mfa_expires_at"] = int(time.time()) - 1
    session.save()

    confirmation = browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
    )

    assert confirmation.status_code == 400
    assert confirmation.json() == {"error": "MFA enrollment expired. Start again."}
    assert "pending_mfa_secret" not in browser.session
    assert "pending_mfa_expires_at" not in browser.session


@pytest.mark.django_db
def test_corrupt_pending_authenticator_secret_fails_closed():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client()
    browser.force_login(user)
    session = browser.session
    session["pending_mfa_secret"] = "not-valid-ciphertext"
    session["pending_mfa_expires_at"] = int(time.time()) + 300
    session.save()

    confirmation = browser.put(
        "/api/mfa/",
        data=json.dumps({"code": "123456"}),
        content_type="application/json",
    )

    assert confirmation.status_code == 400
    assert confirmation.json() == {
        "error": "Invalid authenticator enrollment. Start again."
    }
    assert "pending_mfa_secret" not in browser.session
    assert "pending_mfa_expires_at" not in browser.session


@pytest.mark.django_db
def test_staff_user_confirms_microsoft_authenticator_enrollment_with_valid_code():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value
    setup = browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    ).json()
    secret = pending_mfa_secret(browser)

    confirmation = browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert confirmation.status_code == 200
    assert confirmation.json() == {"enabled": True}
    assert browser.get("/api/session/").json()["mfa_enabled"] is True


@pytest.mark.django_db
def test_stale_setup_session_cannot_replace_an_enabled_authenticator_device():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    first_browser = Client()
    second_browser = Client()
    first_browser.force_login(user)
    second_browser.force_login(user)

    first_setup = first_browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
    ).json()
    second_setup = second_browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
    ).json()
    first_secret = pending_mfa_secret(first_browser)
    second_secret = pending_mfa_secret(second_browser)
    first_browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(first_secret).now()}),
        content_type="application/json",
    )

    stale_confirmation = second_browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(second_secret).now()}),
        content_type="application/json",
    )

    assert stale_confirmation.status_code == 403
    assert stale_confirmation.json() == {"error": "Authentication required."}


@pytest.mark.django_db
def test_enabling_mfa_requires_assurance_on_existing_api_and_admin_sessions():
    user = get_user_model().objects.create_superuser(
        username="mfa.admin",
        password="local-test-password",
    )
    enrollment_browser = Client()
    existing_browser = Client()
    enrollment_browser.force_login(user)
    existing_browser.force_login(user)

    setup = enrollment_browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
    ).json()
    secret = pending_mfa_secret(enrollment_browser)
    confirmation = enrollment_browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
    )

    assert confirmation.status_code == 200
    assert enrollment_browser.get("/api/shifts/").status_code == 200
    assert enrollment_browser.get("/admin/").status_code == 200
    assert existing_browser.get("/api/shifts/").status_code == 403
    assert existing_browser.get("/admin/").status_code in {302, 403}


@pytest.mark.django_db
def test_enrolled_staff_user_must_complete_authenticator_challenge_before_login():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value
    setup = browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    ).json()
    secret = pending_mfa_secret(browser)
    browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    browser.delete("/api/session/", HTTP_X_CSRFTOKEN=csrf_token)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value

    password_response = browser.post(
        "/api/session/",
        data=json.dumps(
            {"username": "mfa.consultant", "password": "local-test-password"}
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert password_response.status_code == 202
    assert password_response.json() == {"mfa_required": True}
    assert browser.get("/api/shifts/").status_code == 403

    code_response = browser.post(
        "/api/session/",
        data=json.dumps({"mfa_code": pyotp.TOTP(secret).at(time.time() + 30)}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert code_response.status_code == 200
    assert code_response.json()["authenticated"] is True
    assert code_response.json()["mfa_enabled"] is True
    assert browser.get("/api/shifts/").status_code == 200


@pytest.mark.django_db
@override_settings(
    MFA_TRUSTED_LAN_NETWORKS=["10.0.0.0/16"],
    MFA_TRUSTED_PROXY_NETWORKS=["127.0.0.0/8", "::1/128"],
    MFA_TRUSTED_BROWSER_MAX_AGE_SECONDS=30 * 24 * 60 * 60,
)
def test_trusted_lan_browser_can_reuse_mfa_assurance_for_thirty_days():
    user = get_user_model().objects.create_user(
        username="lan-mfa-consultant",
        password="local-test-password",
        is_staff=True,
    )
    secret = pyotp.random_base32()
    MfaDevice.objects.create(
        user=user,
        secret_ciphertext=encrypt_secret(secret),
        confirmed_at=timezone.now(),
    )
    browser = Client(REMOTE_ADDR="10.0.1.75")

    password_response = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": user.username,
            "password": "local-test-password",
        }),
        content_type="application/json",
    )
    assert password_response.status_code == 202

    code_response = browser.post(
        "/api/session/",
        data=json.dumps({"mfa_code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
    )
    assert code_response.status_code == 200
    assert code_response.cookies["immploy_mfa_trusted_browser"]["max-age"] == (
        30 * 24 * 60 * 60
    )

    browser.delete("/api/session/")
    remembered_login = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": user.username,
            "password": "local-test-password",
        }),
        content_type="application/json",
    )

    assert remembered_login.status_code == 200
    assert remembered_login.json()["authenticated"] is True


def _establish_trusted_lan_browser(user, secret):
    browser = Client(REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="10.0.1.75")
    password_response = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": user.username,
            "password": "local-test-password",
        }),
        content_type="application/json",
    )
    assert password_response.status_code == 202
    code_response = browser.post(
        "/api/session/",
        data=json.dumps({"mfa_code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
    )
    assert code_response.status_code == 200
    browser.delete("/api/session/")
    return browser


@pytest.mark.django_db
@override_settings(
    MFA_TRUSTED_LAN_NETWORKS=["10.0.0.0/16"],
    MFA_TRUSTED_PROXY_NETWORKS=["127.0.0.0/8", "::1/128"],
    MFA_TRUSTED_BROWSER_MAX_AGE_SECONDS=30 * 24 * 60 * 60,
)
def test_remembered_mfa_is_ignored_off_lan_and_spoofed_header_is_ignored():
    user = get_user_model().objects.create_user(
        username="off-lan-mfa-consultant",
        password="local-test-password",
        is_staff=True,
    )
    secret = pyotp.random_base32()
    MfaDevice.objects.create(
        user=user,
        secret_ciphertext=encrypt_secret(secret),
        confirmed_at=timezone.now(),
    )
    browser = _establish_trusted_lan_browser(user, secret)

    response = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": user.username,
            "password": "local-test-password",
        }),
        content_type="application/json",
        REMOTE_ADDR="198.51.100.20",
        HTTP_X_REAL_IP="10.0.1.75",
    )

    assert response.status_code == 202
    assert response.json() == {"mfa_required": True}


@pytest.mark.django_db
@override_settings(
    MFA_TRUSTED_LAN_NETWORKS=["10.0.0.0/16"],
    MFA_TRUSTED_PROXY_NETWORKS=["127.0.0.0/8", "::1/128"],
    MFA_TRUSTED_BROWSER_MAX_AGE_SECONDS=30 * 24 * 60 * 60,
)
def test_password_change_and_expiry_revoke_remembered_mfa():
    user = get_user_model().objects.create_user(
        username="revoked-lan-mfa-consultant",
        password="local-test-password",
        is_staff=True,
    )
    secret = pyotp.random_base32()
    MfaDevice.objects.create(
        user=user,
        secret_ciphertext=encrypt_secret(secret),
        confirmed_at=timezone.now(),
    )
    browser = _establish_trusted_lan_browser(user, secret)
    trusted_browser = MfaTrustedBrowser.objects.get()
    trusted_browser.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    trusted_browser.save(update_fields=["expires_at"])

    expired_response = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": user.username,
            "password": "local-test-password",
        }),
        content_type="application/json",
    )
    assert expired_response.status_code == 202

    user.set_password("changed-local-test-password")
    user.save(update_fields=["password"])
    trusted_browser.expires_at = timezone.now() + timezone.timedelta(days=1)
    trusted_browser.save(update_fields=["expires_at"])
    changed_password_response = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": user.username,
            "password": "changed-local-test-password",
        }),
        content_type="application/json",
    )
    assert changed_password_response.status_code == 202


@pytest.mark.django_db
def test_mfa_device_reset_deletes_remembered_browsers():
    user = get_user_model().objects.create_user(username="reset-trusted-browser")
    device = MfaDevice.objects.create(
        user=user,
        secret_ciphertext=encrypt_secret(pyotp.random_base32()),
        confirmed_at=timezone.now(),
    )
    MfaTrustedBrowser.objects.create(
        device=device,
        token_digest="a" * 64,
        password_fingerprint="b" * 64,
        expires_at=timezone.now() + timezone.timedelta(days=30),
    )

    device.delete()

    assert not MfaTrustedBrowser.objects.exists()


@pytest.mark.django_db
def test_staff_user_can_disable_mfa_only_with_a_valid_authenticator_code():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    csrf_token = browser.get("/api/session/").cookies["csrftoken"].value
    setup = browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    ).json()
    secret = pending_mfa_secret(browser)
    browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    invalid = browser.delete(
        "/api/mfa/",
        data=json.dumps({"code": "000000"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    status_before = browser.get("/api/mfa/")
    disabled = browser.delete(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).at(time.time() + 30)}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert invalid.status_code == 400
    assert status_before.json() == {"enabled": True}
    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False}
    assert browser.get("/api/session/").json()["authenticated"] is False
    assert browser.get("/api/mfa/").status_code == 403


@pytest.mark.django_db
def test_invalid_mfa_disable_codes_are_throttled():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    browser = Client()
    browser.force_login(user)
    browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
    )
    secret = pending_mfa_secret(browser)
    browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
    )

    for _ in range(5):
        response = browser.delete(
            "/api/mfa/",
            data=json.dumps({"code": "invalid"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    blocked = browser.delete(
        "/api/mfa/",
        data=json.dumps({"code": "invalid"}),
        content_type="application/json",
    )

    assert blocked.status_code == 429
    assert blocked.json() == {"error": "Too many sign-in attempts. Try again later."}
    assert int(blocked.headers["Retry-After"]) > 0


@pytest.mark.django_db
def test_disabling_mfa_invalidates_other_authenticated_sessions():
    user = get_user_model().objects.create_user(
        username="mfa.consultant",
        password="local-test-password",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    browser = Client()
    other_browser = Client()
    browser.force_login(user)
    setup = browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
    ).json()
    secret = pending_mfa_secret(browser)
    browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
    )
    device = user.mfa_device
    other_browser.force_login(user)
    other_session = other_browser.session
    other_session["mfa_verified_device_id"] = device.pk
    other_session[MFA_ACCOUNT_GENERATION_SESSION_KEY] = current_mfa_generation(user.pk)
    other_session.save()
    assert other_browser.get("/api/shifts/").status_code == 200

    disabled = browser.delete(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).at(time.time() + 30)}),
        content_type="application/json",
    )

    assert disabled.status_code == 200
    assert browser.get("/api/session/").json()["authenticated"] is False
    assert other_browser.get("/api/shifts/").status_code == 403


@pytest.mark.django_db
def test_admin_password_form_cannot_bypass_enabled_mfa():
    user = get_user_model().objects.create_superuser(
        username="mfa.admin",
        password="local-test-password",
    )
    browser = Client()
    browser.force_login(user)
    setup = browser.post(
        "/api/mfa/",
        data=json.dumps({"password": "local-test-password"}),
        content_type="application/json",
    ).json()
    secret = pending_mfa_secret(browser)
    browser.put(
        "/api/mfa/",
        data=json.dumps({"code": pyotp.TOTP(secret).now()}),
        content_type="application/json",
    )
    browser.delete("/api/session/")

    response = browser.post(
        "/admin/login/",
        {"username": "mfa.admin", "password": "local-test-password"},
    )

    assert response.status_code == 403
    assert b"complete Microsoft Authenticator sign-in" in response.content


@pytest.mark.django_db
def test_corrupt_enabled_device_secret_fails_closed_during_login():
    user = get_user_model().objects.create_user(
        username="corrupt-mfa-user",
        password="local-test-password",
        is_staff=True,
    )
    MfaDevice.objects.create(
        user=user,
        secret_ciphertext=b"not-valid-fernet-ciphertext",
        confirmed_at=timezone.now(),
    )
    browser = Client()

    password_response = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": "corrupt-mfa-user",
            "password": "local-test-password",
        }),
        content_type="application/json",
    )
    code_response = browser.post(
        "/api/session/",
        data=json.dumps({"mfa_code": "123456"}),
        content_type="application/json",
    )

    assert password_response.status_code == 202
    assert code_response.status_code == 400
    assert code_response.json() == {"error": "Invalid authenticator code."}
    assert browser.get("/api/session/").json()["authenticated"] is False


@pytest.mark.django_db
def test_deleting_mfa_device_invalidates_all_authenticated_sessions():
    user = get_user_model().objects.create_user(
        username="admin-reset-mfa-user",
        is_staff=True,
    )
    device = MfaDevice.objects.create(
        user=user,
        secret_ciphertext=encrypt_secret(pyotp.random_base32()),
        confirmed_at=timezone.now(),
    )
    first_browser = Client()
    second_browser = Client()
    for browser in (first_browser, second_browser):
        browser.force_login(user)
        session = browser.session
        session["mfa_verified_device_id"] = device.pk
        session.save()

    device.delete()

    assert first_browser.get("/api/session/").json()["authenticated"] is False
    assert second_browser.get("/api/session/").json()["authenticated"] is False
    assert "_auth_user_id" not in first_browser.session
    assert "_auth_user_id" not in second_browser.session


@pytest.mark.django_db(transaction=True)
def test_device_reset_during_mfa_verification_cannot_establish_a_session(monkeypatch):
    user = get_user_model().objects.create_user(
        username="mfa-reset-race-user",
        password="local-test-password",
        is_staff=True,
    )
    device = MfaDevice.objects.create(
        user=user,
        secret_ciphertext=encrypt_secret(pyotp.random_base32()),
        confirmed_at=timezone.now(),
    )
    browser = Client()
    password_response = browser.post(
        "/api/session/",
        data=json.dumps({
            "username": user.username,
            "password": "local-test-password",
        }),
        content_type="application/json",
    )
    assert password_response.status_code == 202

    def reset_device_during_verification(device_id, code):
        MfaDevice.objects.filter(pk=device_id).delete()
        return True

    monkeypatch.setattr(
        "bookings.session_views.verify_device_code",
        reset_device_during_verification,
    )
    code_response = browser.post(
        "/api/session/",
        data=json.dumps({"mfa_code": "123456"}),
        content_type="application/json",
    )

    assert code_response.status_code == 400
    assert code_response.json() == {"error": "Start sign-in again."}
    assert browser.get("/api/session/").json()["authenticated"] is False


@pytest.mark.django_db
def test_stale_mfa_generation_is_rejected_after_device_is_already_absent():
    user = get_user_model().objects.create_user(
        username="stale-generation-user",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    MfaAccountState.objects.create(user=user, generation=2)
    browser = Client()
    browser.force_login(user)
    session = browser.session
    session[MFA_ACCOUNT_GENERATION_SESSION_KEY] = 1
    session.save()

    assert browser.get("/api/session/").json() == {
        "authenticated": False,
        "user": None,
        "mfa_required": True,
    }
    assert browser.get("/api/shifts/").status_code == 403


@pytest.mark.django_db(transaction=True)
def test_deleting_user_does_not_recreate_mfa_state_during_device_cascade():
    user = get_user_model().objects.create_user(
        username="deleted-mfa-user",
        is_staff=True,
    )
    MfaDevice.objects.create(
        user=user,
        secret_ciphertext=encrypt_secret(pyotp.random_base32()),
        confirmed_at=timezone.now(),
    )
    user_id = user.pk

    user.delete()

    assert not MfaDevice.objects.filter(user_id=user_id).exists()
    assert not MfaAccountState.objects.filter(user_id=user_id).exists()
