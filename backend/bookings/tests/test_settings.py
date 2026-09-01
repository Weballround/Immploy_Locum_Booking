import hashlib
import os
import subprocess
import sys


def _debug_mfa_key_fingerprint(django_secret_key):
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_DEBUG": "true",
            "DJANGO_SECRET_KEY": django_secret_key,
            "DJANGO_SETTINGS_MODULE": "config.settings",
        }
    )
    environment.pop("DJANGO_MFA_ENCRYPTION_KEY", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import hashlib; from django.conf import settings; "
                "print(hashlib.sha256(settings.MFA_ENCRYPTION_KEY.encode()).hexdigest())"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.strip()


def test_debug_mfa_encryption_key_survives_django_secret_key_rotation():
    first = _debug_mfa_key_fingerprint("first-process-only-django-secret")
    second = _debug_mfa_key_fingerprint("second-process-only-django-secret")

    assert first == second
