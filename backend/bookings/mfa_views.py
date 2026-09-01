import base64
import json
from io import BytesIO

import pyotp
import qrcode
from cryptography.fernet import InvalidToken
from qrcode.image.svg import SvgPathImage
from django.conf import settings
from django.contrib.auth import authenticate, logout
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from bookings.mfa import (
    decrypt_secret,
    encrypt_secret,
    matching_totp_step,
    verify_device_code,
)
from bookings.mfa_assurance import (
    advance_mfa_generation,
    invalidate_other_user_sessions,
    mark_session_mfa_verified,
)
from bookings.models import MfaDevice
from bookings.session_views import (
    LOGIN_ATTEMPT_WINDOW_SECONDS,
    _clear_successful_attempt,
    _reserve_login_attempt,
    _throttle_limits,
)


PENDING_MFA_SECRET_SESSION_KEY = "pending_mfa_secret"
PENDING_MFA_EXPIRES_SESSION_KEY = "pending_mfa_expires_at"
MFA_ENROLLMENT_TTL_SECONDS = 300


def _clear_pending_enrollment(request):
    request.session.pop(PENDING_MFA_SECRET_SESSION_KEY, None)
    request.session.pop(PENDING_MFA_EXPIRES_SESSION_KEY, None)


def _reserve_mfa_attempt(request):
    limits = _throttle_limits(request, request.user.get_username())
    if _reserve_login_attempt(limits):
        return limits, None
    response = JsonResponse(
        {"error": "Too many sign-in attempts. Try again later."}, status=429
    )
    response["Retry-After"] = str(LOGIN_ATTEMPT_WINDOW_SECONDS)
    return limits, response


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST", "PUT", "DELETE"])
def mfa_view(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"error": "Authentication required."}, status=403)

    if request.method == "GET":
        return JsonResponse({
            "enabled": MfaDevice.objects.filter(user=request.user).exists(),
        })

    throttle_limits, throttle_response = _reserve_mfa_attempt(request)
    if throttle_response is not None:
        return throttle_response

    if request.method == "DELETE":
        try:
            payload = json.loads(request.body or "{}")
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid request."}, status=400)
        code = payload.get("code", "") if isinstance(payload, dict) else ""
        with transaction.atomic():
            try:
                device = MfaDevice.objects.select_for_update().get(user=request.user)
            except MfaDevice.DoesNotExist:
                return JsonResponse({"enabled": False})
            if not verify_device_code(device.pk, code):
                return JsonResponse({"error": "Invalid authenticator code."}, status=400)
            logout(request)
            device.delete()
        _clear_successful_attempt(throttle_limits)
        return JsonResponse({"enabled": False})

    if request.method == "PUT":
        try:
            payload = json.loads(request.body or "{}")
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid request."}, status=400)
        code = payload.get("code", "") if isinstance(payload, dict) else ""
        expires_at = request.session.get(PENDING_MFA_EXPIRES_SESSION_KEY)
        if not isinstance(expires_at, int) or expires_at <= int(timezone.now().timestamp()):
            _clear_pending_enrollment(request)
            return JsonResponse(
                {"error": "MFA enrollment expired. Start again."}, status=400
            )
        encrypted_secret = request.session.get(PENDING_MFA_SECRET_SESSION_KEY)
        try:
            secret = decrypt_secret(encrypted_secret.encode()) if encrypted_secret else None
        except (AttributeError, InvalidToken, ValueError):
            _clear_pending_enrollment(request)
            return JsonResponse(
                {"error": "Invalid authenticator enrollment. Start again."},
                status=400,
            )
        matched_step = matching_totp_step(secret, code) if secret else None
        if matched_step is None:
            return JsonResponse({"error": "Invalid authenticator code."}, status=400)

        try:
            with transaction.atomic():
                generation = advance_mfa_generation(request.user.pk)
                device = MfaDevice.objects.create(
                    user=request.user,
                    secret_ciphertext=encrypt_secret(secret),
                    confirmed_at=timezone.now(),
                    last_used_step=matched_step,
                )
        except IntegrityError:
            _clear_pending_enrollment(request)
            return JsonResponse({"error": "MFA is already enabled."}, status=409)
        _clear_pending_enrollment(request)
        invalidate_other_user_sessions(request.user.pk, request.session.session_key)
        mark_session_mfa_verified(request, device, generation)
        _clear_successful_attempt(throttle_limits)
        return JsonResponse({"enabled": True})

    if request.method != "POST":
        return JsonResponse({"error": "MFA operation is not available yet."}, status=405)

    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid request."}, status=400)
    password = payload.get("password", "") if isinstance(payload, dict) else ""
    verified_user = authenticate(
        request,
        username=request.user.get_username(),
        password=password,
    )
    if verified_user is None or verified_user.pk != request.user.pk:
        return JsonResponse({"error": "Current password is required."}, status=400)
    if MfaDevice.objects.filter(user=request.user).exists():
        return JsonResponse({"error": "MFA is already enabled."}, status=409)

    secret = pyotp.random_base32()
    request.session[PENDING_MFA_SECRET_SESSION_KEY] = encrypt_secret(secret).decode("ascii")
    request.session[PENDING_MFA_EXPIRES_SESSION_KEY] = (
        int(timezone.now().timestamp()) + MFA_ENROLLMENT_TTL_SECONDS
    )
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
        name=request.user.get_username(),
        issuer_name=settings.MFA_ISSUER_NAME,
    )
    image = qrcode.make(provisioning_uri, image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    qr_code_data_url = "data:image/svg+xml;base64," + base64.b64encode(
        output.getvalue()
    ).decode("ascii")
    response = JsonResponse({
        "enabled": False,
        "qr_code_data_url": qr_code_data_url,
    })
    response["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate, private"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    _clear_successful_attempt(throttle_limits)
    return response
