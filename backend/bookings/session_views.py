import json
from datetime import timedelta
from hashlib import sha256

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from bookings.booking_times import booking_time_step_seconds_for_user
from bookings.mfa import verify_device_code
from bookings.mfa_assurance import (
    current_mfa_generation,
    mark_session_mfa_generation,
    mark_session_mfa_verified,
    session_has_mfa_assurance,
)
from bookings.models import (
    LEGACY_ACCESS_RULE_FIELDS,
    LegacyUserProfile,
    LoginAttempt,
    MfaDevice,
)
from bookings.permissions import (
    user_can_manage_bookings,
    user_can_manage_candidates,
    user_can_override_approved_rates,
    user_can_view_candidate_pay_rates,
    user_can_view_client_charge_rates,
)
from bookings.trusted_mfa import issue_trusted_browser, trusted_browser_allows_login


LOGIN_IDENTITY_LIMIT = 5
LOGIN_IP_LIMIT = 100
LOGIN_ATTEMPT_WINDOW_SECONDS = 300
MFA_CHALLENGE_TTL_SECONDS = 300
MFA_PENDING_USER_SESSION_KEY = "mfa_pending_user_id"
MFA_PENDING_EXPIRES_SESSION_KEY = "mfa_pending_expires_at"
MFA_PENDING_GENERATION_SESSION_KEY = "mfa_pending_generation"


@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST", "DELETE"])
def session_view(request):
    if request.method == "GET":
        return JsonResponse(_session_payload(request))

    if request.method == "DELETE":
        logout(request)
        return JsonResponse({"authenticated": False, "user": None})

    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid request."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Invalid request."}, status=400)

    if "mfa_code" in payload:
        return _complete_mfa_login(request, payload.get("mfa_code"))

    username = payload.get("username", "")
    password = payload.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"error": "Invalid request."}, status=400)
    throttle_limits = _throttle_limits(request, username)
    if not _reserve_login_attempt(throttle_limits):
        response = JsonResponse(
            {"error": "Too many sign-in attempts. Try again later."},
            status=429,
        )
        response["Retry-After"] = str(LOGIN_ATTEMPT_WINDOW_SECONDS)
        return response

    user = authenticate(
        request,
        username=username,
        password=password,
    )
    if user is None or not user.is_staff:
        return JsonResponse({"error": "Invalid username or password."}, status=400)

    try:
        device = user.mfa_device
    except MfaDevice.DoesNotExist:
        pass
    else:
        if trusted_browser_allows_login(request, user, device):
            _clear_successful_attempt(throttle_limits)
            login(request, user)
            mark_session_mfa_verified(request, device)
            return JsonResponse(_session_payload(request))
        request.session.cycle_key()
        request.session[MFA_PENDING_USER_SESSION_KEY] = user.pk
        request.session[MFA_PENDING_GENERATION_SESSION_KEY] = current_mfa_generation(user.pk)
        request.session[MFA_PENDING_EXPIRES_SESSION_KEY] = int(
            timezone.now().timestamp()
        ) + MFA_CHALLENGE_TTL_SECONDS
        return JsonResponse({"mfa_required": True}, status=202)

    _clear_successful_attempt(throttle_limits)
    login(request, user)
    mark_session_mfa_generation(request)
    return JsonResponse(_session_payload(request))


def _complete_mfa_login(request, code):
    pending_user_id = request.session.get(MFA_PENDING_USER_SESSION_KEY)
    pending_generation = request.session.get(MFA_PENDING_GENERATION_SESSION_KEY)
    expires_at = request.session.get(MFA_PENDING_EXPIRES_SESSION_KEY, 0)
    if (
        not pending_user_id
        or not isinstance(expires_at, int)
        or not isinstance(pending_generation, int)
    ):
        return JsonResponse({"error": "Start sign-in again."}, status=400)
    if expires_at < int(timezone.now().timestamp()):
        _clear_mfa_challenge(request)
        return JsonResponse({"error": "Authenticator challenge expired."}, status=400)
    try:
        device = MfaDevice.objects.select_related("user").get(
            user_id=pending_user_id,
            user__is_active=True,
            user__is_staff=True,
        )
    except MfaDevice.DoesNotExist:
        _clear_mfa_challenge(request)
        return JsonResponse({"error": "Start sign-in again."}, status=400)

    throttle_limits = _throttle_limits(request, device.user.get_username())
    if not _reserve_login_attempt(throttle_limits):
        response = JsonResponse(
            {"error": "Too many sign-in attempts. Try again later."},
            status=429,
        )
        response["Retry-After"] = str(LOGIN_ATTEMPT_WINDOW_SECONDS)
        return response
    if not verify_device_code(device.pk, code):
        return JsonResponse({"error": "Invalid authenticator code."}, status=400)
    if (
        current_mfa_generation(device.user_id) != pending_generation
        or not MfaDevice.objects.filter(pk=device.pk).exists()
    ):
        _clear_mfa_challenge(request)
        return JsonResponse({"error": "Start sign-in again."}, status=400)

    user = device.user
    _clear_mfa_challenge(request)
    _clear_successful_attempt(throttle_limits)
    login(request, user)
    mark_session_mfa_verified(request, device, pending_generation)
    response = JsonResponse(_session_payload(request))
    issue_trusted_browser(response, request, device)
    return response


def _clear_mfa_challenge(request):
    request.session.pop(MFA_PENDING_USER_SESSION_KEY, None)
    request.session.pop(MFA_PENDING_EXPIRES_SESSION_KEY, None)
    request.session.pop(MFA_PENDING_GENERATION_SESSION_KEY, None)


def _session_payload(request):
    user = request.user
    if not user.is_authenticated or not user.is_staff:
        return {"authenticated": False, "user": None}
    if not session_has_mfa_assurance(request):
        return {"authenticated": False, "user": None, "mfa_required": True}
    can_send_booking_sms = user.has_perm("bookings.send_booking_sms")
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        access_rules = None
        can_manage_bookings = user_can_manage_bookings(user)
        can_manage_candidates = user_can_manage_candidates(user)
    else:
        access_rules = {
            field: getattr(profile, field)
            for field in LEGACY_ACCESS_RULE_FIELDS
        }
        can_manage_bookings = user_can_manage_bookings(user)
        can_manage_candidates = user_can_manage_candidates(user)
    return {
        "authenticated": True,
        "booking_time_step_seconds": booking_time_step_seconds_for_user(user),
        "mfa_enabled": MfaDevice.objects.filter(user=user).exists(),
        "user": {
            "username": user.get_username(),
            "display_name": user.first_name or user.get_username(),
        },
        "access_rules": access_rules,
        "permissions": {
            "manage_bookings": can_manage_bookings,
            "manage_candidates": can_manage_candidates,
            "send_booking_sms": can_send_booking_sms,
            "view_candidate_pay_rates": user_can_view_candidate_pay_rates(user),
            "view_client_charge_rates": user_can_view_client_charge_rates(user),
            "override_approved_rates": user_can_override_approved_rates(user),
        },
    }


def _throttle_limits(request, username):
    remote_address = request.META.get("REMOTE_ADDR", "unknown")
    return {
        "ip:" + sha256(remote_address.encode()).hexdigest(): LOGIN_IP_LIMIT,
        "identity:" + sha256(username.casefold().encode()).hexdigest(): LOGIN_IDENTITY_LIMIT,
    }


@transaction.atomic
def _reserve_login_attempt(limits):
    now = timezone.now()
    expires_at = now + timedelta(seconds=LOGIN_ATTEMPT_WINDOW_SECONDS)
    LoginAttempt.objects.filter(expires_at__lte=now).delete()
    attempts = []
    for key in sorted(limits):
        attempt, created = LoginAttempt.objects.select_for_update().get_or_create(
            key=key,
            defaults={"failures": 0, "expires_at": expires_at},
        )
        if not created and attempt.expires_at <= now:
            attempt.failures = 0
        attempts.append(attempt)

    if any(attempt.failures >= limits[attempt.key] for attempt in attempts):
        return False

    for attempt in attempts:
        attempt.failures += 1
        attempt.expires_at = expires_at
        attempt.save(update_fields=["failures", "expires_at"])
    return True


@transaction.atomic
def _clear_successful_attempt(limits):
    identity_keys = [key for key in limits if key.startswith("identity:")]
    LoginAttempt.objects.filter(key__in=identity_keys).delete()
    for attempt in LoginAttempt.objects.select_for_update().filter(
        key__in=[key for key in limits if key.startswith("ip:")]
    ):
        if attempt.failures <= 1:
            attempt.delete()
        else:
            attempt.failures -= 1
            attempt.save(update_fields=["failures"])
