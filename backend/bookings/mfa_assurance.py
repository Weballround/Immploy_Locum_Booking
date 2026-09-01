from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from bookings.models import MfaAccountState, MfaDevice


MFA_VERIFIED_DEVICE_SESSION_KEY = "mfa_verified_device_id"
MFA_ACCOUNT_GENERATION_SESSION_KEY = "mfa_account_generation"


def session_mfa_device(request):
    user = request.user
    if not user or not user.is_authenticated or not user.is_staff:
        return None
    try:
        return user.mfa_device
    except MfaDevice.DoesNotExist:
        return None


def session_has_mfa_assurance(request, device=None):
    device = device or session_mfa_device(request)
    generation = current_mfa_generation(request.user.pk)
    if generation and request.session.get(MFA_ACCOUNT_GENERATION_SESSION_KEY) != generation:
        return False
    if device is None:
        return True
    return request.session.get(MFA_VERIFIED_DEVICE_SESSION_KEY) == device.pk


def mark_session_mfa_verified(request, device, generation=None):
    request.session[MFA_VERIFIED_DEVICE_SESSION_KEY] = device.pk
    mark_session_mfa_generation(request, generation)


def mark_session_mfa_generation(request, generation=None):
    if generation is None:
        generation = current_mfa_generation(request.user.pk)
    request.session[MFA_ACCOUNT_GENERATION_SESSION_KEY] = generation


def clear_session_mfa_assurance(request):
    request.session.pop(MFA_VERIFIED_DEVICE_SESSION_KEY, None)
    request.session.pop(MFA_ACCOUNT_GENERATION_SESSION_KEY, None)


def current_mfa_generation(user_id):
    generation = MfaAccountState.objects.filter(user_id=user_id).values_list(
        "generation", flat=True
    ).first()
    return generation or 0


def advance_mfa_generation(user_id):
    with transaction.atomic():
        state, _ = MfaAccountState.objects.select_for_update().get_or_create(
            user_id=user_id
        )
        state.generation += 1
        state.save(update_fields=["generation", "updated_at"])
        return state.generation


def invalidate_other_user_sessions(user_id, keep_session_key):
    session_keys = []
    sessions = Session.objects.filter(expire_date__gt=timezone.now())
    if keep_session_key:
        sessions = sessions.exclude(session_key=keep_session_key)
    for session in sessions.iterator():
        if str(session.get_decoded().get(SESSION_KEY, "")) == str(user_id):
            session_keys.append(session.session_key)
    if session_keys:
        Session.objects.filter(session_key__in=session_keys).delete()


class MfaAssuranceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        protected_path = request.path.startswith("/api/") or request.path.startswith(
            "/admin/"
        )
        if not protected_path or request.path == "/api/session/":
            return self.get_response(request)

        if (
            request.user.is_authenticated
            and request.user.is_staff
            and not session_has_mfa_assurance(request)
        ):
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"error": "Microsoft Authenticator verification required."},
                    status=403,
                )
            return HttpResponse(
                "Complete Microsoft Authenticator sign-in before opening Administration.",
                status=403,
                content_type="text/plain",
            )
        return self.get_response(request)
