from bookings.models import LegacyUserProfile


PERMANENT_DESK_LEGACY_ID = 6
DEFAULT_BOOKING_TIME_STEP_MINUTES = 15
PERMANENT_BOOKING_TIME_STEP_MINUTES = 1


def booking_time_step_minutes_for_user(user):
    if not user or not user.is_authenticated:
        return DEFAULT_BOOKING_TIME_STEP_MINUTES
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        return DEFAULT_BOOKING_TIME_STEP_MINUTES
    if profile.assigned_desk == PERMANENT_DESK_LEGACY_ID:
        return PERMANENT_BOOKING_TIME_STEP_MINUTES
    return DEFAULT_BOOKING_TIME_STEP_MINUTES


def booking_time_step_seconds_for_user(user):
    return booking_time_step_minutes_for_user(user) * 60
