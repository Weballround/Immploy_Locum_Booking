from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest
from time import time

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction

from bookings.models import MfaDevice


def _fernet():
    key = urlsafe_b64encode(sha256(settings.MFA_ENCRYPTION_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode())


def decrypt_secret(ciphertext):
    return _fernet().decrypt(bytes(ciphertext)).decode()


def matching_totp_step(secret, code, timestamp=None):
    if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
        return None
    current_step = int(timestamp if timestamp is not None else time()) // 30
    totp = pyotp.TOTP(secret)
    for offset in (-1, 0, 1):
        step = current_step + offset
        if compare_digest(totp.at(step * 30), code):
            return step
    return None


@transaction.atomic
def verify_device_code(device_id, code):
    device = MfaDevice.objects.select_for_update().get(pk=device_id)
    try:
        secret = decrypt_secret(device.secret_ciphertext)
    except (InvalidToken, TypeError, UnicodeDecodeError, ValueError):
        return False
    step = matching_totp_step(secret, code)
    if step is None or (
        device.last_used_step is not None and step <= device.last_used_step
    ):
        return False
    device.last_used_step = step
    device.save(update_fields=["last_used_step", "updated_at"])
    return True
