from django.contrib import admin
from django.contrib.auth import logout
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from bookings.models import MfaDevice
from bookings.session_views import (
    LOGIN_ATTEMPT_WINDOW_SECONDS,
    _clear_successful_attempt,
    _reserve_login_attempt,
    _throttle_limits,
)


@never_cache
@csrf_protect
def throttled_admin_login(request):
    limits = None
    if request.method == "POST":
        username = request.POST.get("username", "")
        if not isinstance(username, str):
            username = ""
        limits = _throttle_limits(request, username)
        if not _reserve_login_attempt(limits):
            response = HttpResponse(
                "Too many sign-in attempts. Try again later.",
                status=429,
                content_type="text/plain",
            )
            response["Retry-After"] = str(LOGIN_ATTEMPT_WINDOW_SECONDS)
            return response

    response = admin.site.login(request)
    if limits and request.user.is_authenticated:
        if MfaDevice.objects.filter(user=request.user).exists():
            logout(request)
            return HttpResponse(
                "MFA is enabled. Sign in to IMMploy and complete Microsoft "
                "Authenticator sign-in before opening Administration.",
                status=403,
                content_type="text/plain",
            )
        _clear_successful_attempt(limits)
    return response
