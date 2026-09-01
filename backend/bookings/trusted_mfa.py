from datetime import timedelta
from hashlib import sha256
from ipaddress import ip_address, ip_network
import secrets

from django.conf import settings
from django.utils import timezone

from bookings.models import MfaTrustedBrowser


TRUSTED_BROWSER_COOKIE = "immploy_mfa_trusted_browser"


def _networks(setting_name):
    return [ip_network(value, strict=False) for value in getattr(settings, setting_name, [])]


def client_ip(request):
    try:
        direct_ip = ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return None
    if any(direct_ip in network for network in _networks("MFA_TRUSTED_PROXY_NETWORKS")):
        try:
            return ip_address(request.META.get("HTTP_X_REAL_IP", ""))
        except ValueError:
            return None
    return direct_ip


def request_is_trusted_lan(request):
    address = client_ip(request)
    return address is not None and any(
        address in network for network in _networks("MFA_TRUSTED_LAN_NETWORKS")
    )


def _digest(value):
    return sha256(value.encode()).hexdigest()


def _password_fingerprint(user):
    return _digest(user.password)


def issue_trusted_browser(response, request, device):
    if not request_is_trusted_lan(request):
        return
    max_age = settings.MFA_TRUSTED_BROWSER_MAX_AGE_SECONDS
    now = timezone.now()
    token = secrets.token_urlsafe(32)
    MfaTrustedBrowser.objects.filter(expires_at__lte=now).delete()
    MfaTrustedBrowser.objects.create(
        device=device,
        token_digest=_digest(token),
        password_fingerprint=_password_fingerprint(device.user),
        expires_at=now + timedelta(seconds=max_age),
    )
    response.set_cookie(
        TRUSTED_BROWSER_COOKIE,
        token,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="Strict",
        path="/",
    )


def trusted_browser_allows_login(request, user, device):
    if not request_is_trusted_lan(request):
        return False
    token = request.COOKIES.get(TRUSTED_BROWSER_COOKIE)
    if not token:
        return False
    now = timezone.now()
    trusted_browser = MfaTrustedBrowser.objects.filter(
        device=device,
        token_digest=_digest(token),
        expires_at__gt=now,
        password_fingerprint=_password_fingerprint(user),
    ).first()
    if trusted_browser is None:
        return False
    trusted_browser.save(update_fields=["last_used_at"])
    return True
