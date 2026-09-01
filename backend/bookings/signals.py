from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete
from django.dispatch import receiver

from bookings.mfa_assurance import advance_mfa_generation, invalidate_other_user_sessions
from bookings.models import MfaDevice


@receiver(post_delete, sender=MfaDevice)
def invalidate_sessions_after_mfa_device_deletion(sender, instance, **kwargs):
    origin = kwargs.get("origin")
    user_model = get_user_model()
    if isinstance(origin, user_model) or getattr(origin, "model", None) is user_model:
        return
    advance_mfa_generation(instance.user_id)
    invalidate_other_user_sessions(instance.user_id, keep_session_key=None)